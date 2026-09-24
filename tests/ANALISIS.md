# Análisis de Wisip — tiempos, calidad y readiness de producción

Generado a partir de pruebas automatizadas reales en este equipo (Windows 10,
GPU NVIDIA presente, voces SAPI Helena/Zira). Reproducible con los scripts de
esta carpeta. La voz de prueba se inyecta por el **cable virtual VB-Audio**
(TTS → CABLE Input → CABLE Output → micrófono que captura Wisip), por lo que se
ejercita la misma cadena que usa una persona real.

> Nota de método: el dispositivo de entrada solo se cambia DENTRO del proceso de
> prueba (`sounddevice.default`), nunca el predeterminado de Windows, y se
> **restaura** al terminar. Tu micrófono real (`Microphone (HD Audio)`) quedó
> intacto.

---

## 1. Veredicto de tiempos: ¿es adecuado para un usuario final?

La latencia que **siente** el usuario es el tiempo de transcripción DESPUÉS de
soltar la tecla (la grabación ocurre en tiempo real mientras habla; eso es
ineludible). Medido por frase:

| Configuración | Frase corta (3–6 s) | Audio largo (30 s) | RT ratio | Calidad | Veredicto UX |
|---|---|---|---|---|---|
| `base` · **CPU** int8 | **1.1 – 1.7 s** | 5.1 s | 0.17–0.39× | media | Aceptable, ágil |
| `small` · **CPU** int8 *(default de la app)* | **3.7 – 4.4 s** | 13.5 s | 0.7–1.4× | alta | ❌ **Lento** para dictado corto |
| `small` · **GPU** CUDA float16 + batched | **0.22 – 0.36 s** | 1.38 s | 0.04–0.08× | alta | ✅ **Excelente (instantáneo)** |

Escala de referencia para una herramienta de "escribir con la voz":
`<0.5 s` imperceptible · `0.5–1.5 s` fluido · `1.5–3 s` se nota · `>3 s` molesto.

### Conclusión
- **Tal como sale de fábrica (perfil "Calidad actual" = `small` en CPU), NO es
  adecuado para dictado corto en este equipo: ~4 s de espera por frase.** Para
  textos largos (RT < 1) es tolerable, pero el caso común (frases de 1–2 líneas)
  se siente lento.
- **El mismo `small` en la GPU baja a ~0.3 s: instantáneo y con la mejor
  calidad.** El equipo TIENE GPU NVIDIA usable (verificado: backend
  `CUDA float16`), pero el perfil por defecto la ignora.

---

## 2. Soluciones recomendadas (en orden de impacto)

1. **Auto-seleccionar el perfil de rendimiento según el hardware.**
   En el primer arranque, si `cuda_available()` y el warmup GPU pasa, poner el
   default en **"Rápido seguro"** (`fast_safe`, device `auto` + batched) en vez
   de `quality_current`. Es un cambio de un valor (`config.DEFAULT_PERF_PROFILE`)
   + la detección que ya existe. Impacto medido aquí: de **~4 s → ~0.3 s** sin
   perder calidad. **Es la mejora #1.**

2. **Para equipos sin GPU**, default razonable = `base` (≈1.2 s, calidad media)
   en vez de `small` en CPU (≈4 s). Alternativa: dejar `small` pero con
   `batched` on (ayuda sobre todo en audio largo). Idealmente, un mini-benchmark
   de primer arranque que elija el perfil por el usuario.

3. **Mostrar el costo al elegir el perfil/modelo.** La UI ya tiene el contador
   "TRANSCRIBIENDO (Ns)"; añadir junto al dropdown MODELO/RENDIMIENTO una pista
   tipo "≈0.3 s/frase (GPU)" vs "≈4 s/frase (CPU)" evita que el usuario elija
   `small`/CPU sin saber el costo.

4. **Transcripción incremental (ya diseñada, desactivada).** Para dictados muy
   largos en CPU reduciría la latencia percibida (ir transcribiendo por chunks).
   Baja prioridad: con GPU, 30 s se resuelven en 1.4 s.

5. **El preload del modelo al arrancar ya está bien** (un hilo lo carga al
   inicio). Ojo: la **primera** carga de `small` en CPU tardó ~27 s (incluye
   construir el modelo); en GPU ~2.4 s. Conviene avisar "cargando modelo…" en el
   primer arranque (el estado `loading` ya existe).

---

## 3. Calidad de transcripción — hallazgos

Precisión global (vía TTS, que es un **piso**: la voz sintética pronuncia los
términos en inglés con fonética española, más difícil que una persona real):

- `small` acierta texto natural ES casi perfecto (WER 0.00–0.13) y **todos** los
  términos técnicos de la prueba (Docker, webhook, n8n, MongoDB, React, Node.js,
  Python, JavaScript, TypeScript).
- `base` es más rápido pero falla términos ("Docker"→"DACA", "webhook"→"bebo").

> **Estado:** los problemas [ALTO] (idioma mixto), [BAJO] (`.ia`/`.ai`) y la
> recomendación #1 (GPU por defecto) ya fueron **CORREGIDOS** y verificados.
> Quedan pendientes el correo por voz [MEDIO] y la nota latente de Tk.

### Problemas reales detectados

- **[ALTO · CORREGIDO] El toggle "IDIOMA MIXTO" no hacía nada.** `transcribe()` recibe
  `mixed_language_mode` pero **nunca lo usa** para cambiar el idioma (solo lo
  loguea). Con `language="es"` (default), una frase en inglés se transcribe/
  traduce como español: *"I need to create a new endpoint…"* salió como
  *"Necesito crear un nuevo endpoint… antes de la próxima relevancia"* en
  `small`. **Fix:** cuando `mixed_language_mode` esté activo y el idioma sea
  `es`/default, pasar `language=None` (auto) a faster-whisper, que es justo lo
  que promete el docstring de `config.py`.

- **[MEDIO] Reconstrucción de correos poco fiable.** `juanperez arroba
  hotmail punto com` salió como `juanperez-hotmail.com` / `juanperez.co`
  (la "arroba" se perdió o se volvió "-"). Parte es artefacto del TTS, pero el
  pipeline no recuperó `@hotmail.com`. Conviene más anclas en el parser y casos
  de regresión con voz real.

- **[BAJO · CORREGIDO] Dominio `.ai` vs `.ia`.** `wisip.ai` salió `wisip.ia` y no se corrige
  porque `KNOWN_TLDS` incluye **ambos** `ai` e `ia`, así que `.ia` se acepta como
  TLD válido. Sugerencia: mapear `wisip.ia → wisip.ai` o quitar `ia` de la lista.

- **[BAJO/latente] Tk `.after()` entre hilos.** `_set_state()` se llama desde
  hilos worker y llega a `FloatingBar.*.after(...)`. Funciona porque hay mainloop,
  pero `.after()` cross-thread no es estrictamente thread-safe; mejor enrutar el
  estado de la barra por la cola de UI (como ya se hace con `set_status`).

---

## 4. Bot de botones (readiness de la UI)

`ui_bot.py` disparó **68 acciones** (cada dropdown en todos sus valores, cada
switch/checkbox encendido y apagado, todos los botones, cambio de pestañas,
historial completo y el ciclo grabar→transcribir→pegar) en dos fases: widgets de
`AppUI` y handlers reales del `Controller` (con dobles seguros: sin pegar de
verdad, sin registrar el hotkey global, sin tocar el registro de Windows).

**Resultado: 68/68 OK, 0 errores.** Detalle en `report_ui.md`. Ningún botón lanza
excepción; todos los callbacks se invocan. La lógica de negocio de cada control
funciona.

---

## 5. Resumen ejecutivo

| Tema | Estado |
|---|---|
| Botones / UI | ✅ 68/68 sin errores |
| Tiempo (default actual) | ❌ ~4 s/frase corta (small/CPU con GPU desaprovechada) |
| Tiempo (con GPU activada) | ✅ ~0.3 s/frase |
| Calidad ES + términos técnicos | ✅ alta con `small` |
| Idioma mixto (toggle) | ❌ no funcional (bug) |
| Correos por voz | ⚠ poco fiable |
| Micrófono del usuario | ✅ intacto (solo se cambió en-proceso y se restauró) |

**Acción de mayor impacto:** activar GPU por defecto cuando exista
(`DEFAULT_PERF_PROFILE = fast_safe` con detección), y arreglar el toggle de
idioma mixto. Con eso, Wisip pasa de "lento y a veces traduce" a "instantáneo y
fiel" en este equipo.
