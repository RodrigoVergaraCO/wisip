# Roadmap de calidad — Wisip

> Plan de trabajo para reducir los errores de palabra y dejar el dictado
> bilingüe (español + inglés) a nivel de producto. Estado al 2026-09-23.
> Cada fase termina con un número medible; sin medición no se pasa a la
> siguiente.

## Punto de partida (datos reales, 31 días)

| Métrica | Valor |
|---|---|
| Dictados registrados | 2.918 (761 min de audio, 120.630 palabras) |
| Backend | CUDA float16, `large-v3-turbo`, 100 % de los dictados |
| Dictados en inglés o mixtos | 5 (0,2 %) — el inglés aparece como términos sueltos dentro del español |
| Defecto #1 (arreglado hoy) | "punto + minúscula" al unir tramos: 45 % de los dictados multi-tramo |
| Defecto #2 (arreglado hoy) | palabra repetida en la frontera de tramos: 7 % de los multi-tramo |
| Defecto #3 | nombres propios / marcas mal oídas (Hetzner, IPRoyal, desban, Billions BS…) → diccionarios |
| Defecto #4 | confusiones acústicas entre palabras reales ("prótesis" por "proxys", "cinco" por "sin") → no se arreglan con diccionarios |

Conclusión: los diccionarios ya cubren lo que pueden. Lo que queda (#4) exige
o un modelo mejor, o una capa de corrección con contexto (LLM local), o ambas.

---

## Fase 1 — Medir antes de tocar (1 sesión)

Sin un set de evaluación cada cambio es una opinión.

1. **Set de evaluación propio** (`tests/eval/`): 60-80 dictados reales con
   transcripción de referencia escrita a mano. Mezcla: 50 % español técnico
   (proxies, Amazon, MEmu), 25 % español general, 15 % inglés completo,
   10 % mixto (frase ES con términos EN). Fuente: los WAV que ya guarda el
   registro en `logs/audio` más 30 grabaciones nuevas.
2. **Script `scripts/eval_wer.py`**: corre cualquier motor/configuración sobre
   el set y reporta WER, CER y una lista de sustituciones frecuentes. Usar
   [jiwer](https://github.com/jitsi/jiwer) para las métricas. Normalizar
   puntuación y mayúsculas antes de comparar (lo que importa es la palabra).
3. **Línea base**: `large-v3-turbo` + prompt v9 + hotwords actuales. Ese número
   es el que hay que batir.

Entregable: tabla WER por categoría (ES técnico / ES general / EN / mixto).

## Fase 2 — Exprimir el motor actual (1-2 sesiones)

Experimentos baratos sobre faster-whisper, todos medidos con la Fase 1:

| Experimento | Por qué | Coste |
|---|---|---|
| `large-v3` (no turbo) | turbo recorta el decoder de 32 a 4 capas; pierde más en idiomas distintos al inglés. En una RTX 3060 sigue siendo < 2 s por dictado | VRAM +1,3 GB |
| `beam_size` 5 → 8 | más hipótesis en palabras ambiguas ("cinco"/"sin") | +30 % tiempo |
| `temperature` con fallback `(0.0, 0.2, 0.4)` | reintento cuando la confianza es baja, en vez de aceptar el garble | solo en ventanas malas |
| `vad_parameters` (`min_silence_duration_ms`, `speech_pad_ms`) | evitar que el VAD corte sílabas finales ("scrollear" → "scrolle") | ninguno |
| `word_timestamps=True` + descarte por palabra | descartar solo la palabra de baja confianza, no el segmento | +10 % tiempo |
| Prompt en dos idiomas equilibrado | hoy el prompt es 90 % español; un bloque inglés de 2 frases mejora las frases EN completas | tokens del presupuesto 224 |

Salida esperada: elegir la configuración por defecto para GPU y para CPU con
números, no con impresiones.

## Fase 3 — Abstracción de motor y segundo motor (2-3 sesiones)

Hoy `app/transcriber.py` está casado con faster-whisper. Se introduce
`app/engines/` con una interfaz mínima (`load()`, `transcribe(audio) →
segmentos con texto y confianza`) y tres implementaciones:

1. **faster-whisper** (actual): el mejor para code-switching ES/EN dentro de
   una misma frase (re-detección de idioma por segmento) y el único con
   `initial_prompt` + `hotwords`, que es la base del vocabulario personal.
2. **Parakeet-TDT-0.6B-v3** (NVIDIA) vía ONNX Runtime
   ([onnx-asr](https://github.com/istupakov/onnx-asr) o
   [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)): 25 idiomas europeos
   incluidos ES y EN, puntuación y mayúsculas nativas, muy rápido en CPU y en
   cualquier GPU vía DirectML (resuelve AMD/Intel sin CUDA). Limitaciones a
   validar: no acepta prompt ni hotwords (el vocabulario personal quedaría
   solo en los diccionarios) y no hay evidencia publicada de que maneje el
   cambio de idioma dentro de una frase.
3. **whisper.cpp + Vulkan**: mismo modelo Whisper, binarios oficiales para
   Windows con soporte AMD/Intel/NVIDIA. Alternativa al punto 2 si Parakeet
   no rinde en español técnico.

Decisión al final de la fase: motor por defecto según hardware
(NVIDIA → faster-whisper CUDA; AMD/Intel → Parakeet DirectML o whisper.cpp
Vulkan; sin GPU → Parakeet CPU), siempre con el WER de la Fase 1 delante.

## Fase 4 — Capa de corrección con contexto (LLM local, opt-in) (2 sesiones)

Es lo que hacen Wispr Flow y SuperWhisper ("AI cleanup") y lo único que
arregla el defecto #4: "muestra los prótesis disponibles" solo se corrige si
algo entiende que en una frase sobre proxies "prótesis" no encaja.

- Modelo pequeño en GGUF vía `llama-cpp-python`: Qwen3-1.7B o Gemma 3 4B
  cuantizado Q4 (2-3 GB de VRAM; cabe junto al turbo en 12 GB). Objetivo de
  latencia: < 1 s para un dictado de 50 palabras.
- Entrada: texto crudo + glosario del usuario (hotwords + valores de los
  reemplazos) + idioma detectado. Salida: el mismo texto con correcciones de
  ortografía, mayúsculas, puntuación y vocabulario del glosario.
- Guardas obligatorias: prohibido añadir o quitar contenido; se rechaza la
  salida si la distancia de edición supera el 30 % del original; se registra
  el diff en el registro de dictados para auditarlo con `analyze_logs.py`.
- Desactivable desde la UI; medido con la Fase 1 (WER antes/después).

## Fase 5 — Producto bilingüe (1-2 sesiones)

- **Selector de idioma por dictado**: ES / EN / auto en la barra flotante y un
  segundo hotkey opcional para "dictar en inglés" sin abrir la ventana.
- **Prompt y hotwords por idioma**: perfiles separados (`prompt_es`,
  `prompt_en`) en vez de un único prompt mixto.
- **UI en inglés**: tabla de cadenas `app/i18n.py` (es/en), idioma de la UI
  en ajustes; hoy todo está en español fijo.
- **Set de evaluación EN** dentro de la Fase 1 para vigilar regresiones.

## Fase 6 — Camino a mercado (en paralelo, sin orden fijo)

- ~~Instalador liviano: un solo `.exe` de ~70 MB, paquete NVIDIA y modelo
  descargados desde la app con progreso.~~ **Hecho en 2.7.0 (2026-09-24).**
- ~~Selector de micrófono en la UI y asistente de primer arranque.~~ **Hecho
  en 2.8.0 (2026-09-24).**
- Releases en GitHub con los instaladores CPU y GPU (hoy solo locales).
- ~~Claves de licencia (Lemon Squeezy).~~ **Cliente hecho en 2.9.0
  (2026-09-24)**: falta crear la tienda/producto en Lemon Squeezy (límite de
  activaciones = 1) y poner `BUY_URL` en `config.py`.
- Firma de código (SmartScreen), auto-update.
- Sitio de una página con demo en vídeo.

---

## Proyectos de referencia en GitHub

Para aprender de ellos, no para copiar: Wisip ya tiene cosas que ellos no
(registro de dictados con minería de vocabulario, guardas anti-alucinación
basadas en confianza, modo mixto por segmento).

| Proyecto | Qué mirar |
|---|---|
| [cjpais/Handy](https://github.com/cjpais/Handy) | App de dictado open source más popular (Rust + Tauri, MIT). Abstracción de motores (whisper.cpp + Parakeet), push-to-talk, builds multiplataforma. |
| [OpenWhispr/openwhispr](https://github.com/OpenWhispr/openwhispr) | Electron; combina modelos locales (Parakeet/Whisper) y flujo de "limpieza con IA". |
| [Knuckles92/OpenWhisper](https://github.com/Knuckles92/OpenWhisper) | Motores alternativos en Windows x64: Parakeet, Qwen3-ASR, Nemotron Streaming, Moonshine. Buena lista de candidatos para la Fase 3. |
| [savbell/whisper-writer](https://github.com/savbell/whisper-writer) | El más parecido a Wisip (Python + faster-whisper + hotkey global). Comparar su post-procesado. |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Motor actual. Seguir `hotwords`, `multilingual`, batched pipeline. |
| [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Backend Vulkan para AMD/Intel. |
| [istupakov/onnx-asr](https://github.com/istupakov/onnx-asr) / [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Ejecutar Parakeet-TDT-0.6B-v3 sin NeMo, en CPU o DirectML. |
| [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | Tarjeta del modelo (25 idiomas europeos, puntuación nativa). |
| [Open ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard) | Pista multilingüe con español: para elegir modelos con datos, no con marketing. |
| [jitsi/jiwer](https://github.com/jitsi/jiwer) | WER/CER para la Fase 1. |
