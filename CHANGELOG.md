# Changelog

Fechas en formato AAAA-MM-DD. Las versiones corresponden al instalador
(`EXE/installer.iss`).

## 2.6.0 — 2026-09-23

- Unión de tramos incrementales: se elimina el punto de cierre de tramo cuando
  la frase continúa en minúscula (afectaba al 45 % de los dictados multi-tramo)
  y se descarta la palabra repetida en la frontera entre tramos (7 %).
- La minúscula de arranque de tramo respeta marcas con mayúscula interna
  (GitHub, AnyDesk, IPRoyal).
- Diccionario general: marcas en minúscula (Amazon, Gmail, YouTube, GitHub,
  Alexa, BlueStacks, Play Protect, Magisk, Pexels, Valorant, ElevenLabs,
  Anthropic) y garbles inambiguos (premir, chitosamente, appelar, badeja,
  workhook, apikey).
- Nuevo validador `scripts/check_join_chunks.py` (21 checks); los validadores
  devuelven código de salida distinto de cero al fallar.
- Proyecto publicado en GitHub: licencia GPL-3.0, CI en Windows con los seis
  validadores, README en inglés y español, manual movido a `docs/`.

## 2.5.0 — 2026-08-23

- Pestaña **Vocabulario**: hotwords con medidor de tokens real, reemplazos
  personales en vivo y minería de sugerencias del registro (wordfreq).
- Vocabulario y hotwords renovados; lista negra ampliada.

## 2.4.0 — 2026-08-03

- Colas fantasma ("Muchas gracias.", "Chao."): recorte del ruido de cola del
  tramo final y descarte de despedidas exactas con confianza baja.
- Reemplazos de español corriente movidos al modo técnico (opt-in).
- Guarda de segmentos cortos relajada cuando la frase anterior sigue abierta.

## 2.3.0 — 2026-07-21

- Instaladores CPU (66 MB) y GPU (970 MB) desde el mismo `.spec`.
- Eco del prompt diagnosticado y bloqueado (prompt v9 + guarda anti-eco).
- Log de errores con `excepthook`, `faulthandler` y diálogos nativos.
- Esquinas redondeadas, paletas de color, barra flotante compacta.

## 2.2.0 — 2026-07-17

- Registro de dictados (JSONL + WAV de sospechosos) y analizador.
- Instancia única (la nueva cierra a la anterior).
- Detector de micrófono en mute por hardware.

## 2.1.0 — 2026-07-01

- Transcripción incremental (corte en silencios, worker en segundo plano).
- GPU NVIDIA con `large-v3-turbo` y perfiles de rendimiento.
- Modo idioma mixto por segmento (`multilingual=True`) y `hotwords`.
