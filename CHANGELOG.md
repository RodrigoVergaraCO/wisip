# Changelog

Fechas en formato AAAA-MM-DD. Las versiones corresponden al instalador
(`EXE/installer.iss`).

## 2.10.1 — 2026-09-24

- Defaults de fábrica genéricos (prompt v10, hotwords v3; fuera el vocabulario del desarrollador) y enlace de compra real de Lemon Squeezy en la pestaña Licencia. Flujo de licencia verificado contra la API real: activar, límite de un equipo, validar, desactivar.

## 2.10.0 — 2026-09-24

- **Interfaz simplificada**: la pestaña Transcribe se divide en **Inicio**
  (tecla, cómo funciona, micrófono, idioma y modo mixto, botón de grabar,
  última transcripción) y **Ajustes** (perfil, modelo, rendimiento, modo de
  pegado, tema, interruptores y avanzado). Feedback del usuario: "el panel
  tiene muchos botones".
- Capturas reales de producto para la tienda y la web (`tests/shots.py` →
  `site/media/`), y sección de capturas en la página.
- Prueba de humo `tests/smoke_ui_tabs.py` (pestañas, rebuild de tema,
  setters thread-safe).

## 2.9.2 — 2026-09-24

- URLs: si Whisper escribe la ruta con punto ("wisip.ai.dashboard" por "wisip punto ai slash dashboard", lectura real 2026-09-23), el normalizador la corrige a "wisip.ai/dashboard" cuando el segmento tras el TLD no es otro TLD (amazon.com.mx se respeta). 4 casos nuevos en check_normalizer.

## 2.9.1 — 2026-09-24

- Unión de tramos, a partir de una lectura de prueba real de 90 s (14 tramos):
  se elimina la repetición de hasta 3 palabras en la frontera ("o sea, o sea,")
  y una cola corta capitalizada tras el punto de tramo se pega a la frase
  anterior ("transcribed. Correctly." → "transcribed correctly."), salvo que
  abra frase ("Muchas gracias.", "Listo.", "Ya está."). 12 checks nuevos en
  `scripts/check_join_chunks.py`.

## 2.9.0 — 2026-09-24

- **Licencias** (`app/license.py`): prueba gratuita de 30 días desde el primer
  arranque; después la app abre pero no graba hasta activar una clave. Clave
  de por vida atada a un equipo mediante la License API de Lemon Squeezy
  (activar / validar / desactivar; límite de activaciones lo fija el
  producto en la tienda). Revalidación cada 30 días con 90 días de gracia sin
  internet. Pestaña **Licencia** (estado, activar, desactivar, comprar).
  `Wisip.exe --deactivate-license` libera la clave y el desinstalador lo
  ejecuta solo ("transferible al desinstalar"). Validador
  `scripts/check_license.py` con servidor simulado.
- **Tecla por defecto: Ctrl + Win + Espacio** (la misma de Wispr Flow en
  Windows) para instalaciones nuevas; "|" no existe en muchos teclados. Las
  instalaciones existentes conservan su tecla. Los atajos se muestran
  legibles ("Ctrl + Win + Espacio").
- Asistente inicial (feedback de la primera prueba real): texto del paso 1
  ya no se corta y explica en 3 pasos cómo funciona; el medidor del
  micrófono funciona (los micros vía WASAPI rechazaban 16 kHz: ahora se
  abren por MME o con conversión automática) y avisa si el micro no abre;
  el paso final aclara que todo se puede cambiar después.
- Pestaña Transcribe: tarjeta "Cómo funciona" y el prompt inicial de Whisper
  queda plegado bajo "Ajustes avanzados".

## 2.8.0 — 2026-09-24

- **Asistente de primer arranque** (`app/onboarding.py`): bienvenida y
  consentimiento del registro local de dictados, micrófono con medidor de
  nivel en vivo, tecla para dictar (con cambio en el sitio), idioma y modo
  mixto, aceleración NVIDIA (si hay GPU) y resumen. Se muestra una sola vez
  (`first_run_done`); con la X se aceptan los valores actuales.
- **Selector de micrófono** (`app/audio_devices.py`): lista WASAPI
  deduplicada (nombres completos; MME los trunca a 31 caracteres), guardado
  por nombre (`input_device_name`) y resuelto a índice en cada arranque; si
  el micro no está conectado se usa el predeterminado con aviso. Dropdown
  MICRÓFONO en la pestaña Transcribe; el grabador acepta `device` y tiene un
  monitor de nivel sin grabar para el asistente.
- Nuevo validador `scripts/check_audio_devices.py` (tabla de dispositivos
  simulada) y prueba de humo con Tk real `tests/smoke_onboarding.py`.

## 2.7.0 — 2026-09-24

- **Un solo instalador liviano (~70 MB)** en vez de CPU (66 MB) y GPU (970 MB).
  Las DLLs CUDA (1,9 GB) ya no van dentro: si hay GPU NVIDIA, la app ofrece
  descargar el paquete de aceleración (~1,2 GB) una sola vez a
  `%LOCALAPPDATA%\Wisip\cuda`. Se extraen solo las DLLs necesarias de los
  wheels oficiales de NVIDIA en PyPI leyendo el zip por rangos HTTP, con
  verificación CRC32/sha256; se omiten `cudnn_adv` y `nvblas` (verificado que
  faster-whisper no las usa).
- **Descarga del modelo con progreso** (porcentaje, MB, velocidad, tiempo
  restante, cancelar) en el primer arranque y al cambiar de modelo. Antes
  parecía colgada durante la descarga de 1,6 GB.
- Botón "Descargar aceleración NVIDIA" en la pestaña Transcribe cuando hay GPU
  y falta el paquete. Ajuste `gpu_pack_declined` para no volver a preguntar.
- El autotune a GPU y la selección de dispositivo ya no confían solo en el
  driver: exigen que las DLLs CUDA existan (antes, en un build sin CUDA con
  driver NVIDIA, intentaba GPU en cada arranque y caía a CPU con aviso).
- Nuevo validador `scripts/check_setup_assets.py` (servidor HTTP local con
  rangos, zip64, cancelación, fallback sin rangos, sha256).
- `Wisip.spec` solo empaqueta CUDA con `WISIP_BUNDLE_CUDA=1`; eliminados
  `build_cpu.bat` y `build_installers.bat`.
- Instalador: limpia `_internal` antes de copiar (`[InstallDelete]`; una
  actualización desde un instalador GPU dejaba 1,9 GB de DLLs huérfanas) y
  cierra un Wisip en ejecución antes de instalar (evento de instancia única +
  `taskkill` de respaldo; el Restart Manager de Windows no lograba cerrarlo
  porque la X oculta al tray, y la instalación silenciosa abortaba).

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
