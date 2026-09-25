# Changelog

Fechas en formato AAAA-MM-DD. Las versiones corresponden al instalador
(`EXE/installer.iss`).

## 2.13.0 — 2026-09-24

- **Corrige y Wisip aprende** (`app/corrections.py`): el cuadro "Última
  transcripción" de Inicio ahora es editable. Corriges lo que salió mal,
  pulsas "Guardar corrección" (o Ctrl + Enter) y se guarda en local el texto
  original, el corregido, los pares palabra a palabra (mal → bien) y el audio
  del dictado (`logs/correcciones/`). Ese audio + texto de referencia es el
  set de evaluación para medir la precisión de verdad.
- **Vocabulario → Analizar mis dictados** muestra primero tus correcciones,
  con la forma correcta ya rellenada: un clic y queda como regla personal.
- `scripts/analyze_corrections.py`: informe de sustituciones recurrentes,
  borrados, añadidos y tamaño del set de evaluación, para revisarlo con la IA.
  Validador `scripts/check_corrections.py` (CI).

## 2.12.2 — 2026-09-24

- **Los atajos con Win y Shift no funcionaban en un Windows en español.** La
  librería de teclado nombra las teclas físicas con el texto localizado de
  Windows ("windows izquierda", "mayusculas") y Wisip solo entendía los
  nombres en inglés, así que Ctrl + Win + Shift nunca se completaba (Ctrl sí,
  porque se llama igual en los dos idiomas). Ahora los modificadores se
  reconocen por scan code, independiente del idioma y de la distribución, y
  los nombres localizados quedan como alias de respaldo. Al capturar un atajo
  nuevo se guarda siempre la forma canónica (`ctrl+shift+windows`).
- El aviso "Pulsa la nueva combinación…" aparece en la tarjeta del atajo que
  se está cambiando: antes, al cambiar el de dictar y traducir, salía en la
  de dictar.
- El log registra qué chord se completó, con qué tecla, y qué tecla lo soltó.

## 2.12.1 — 2026-09-24

- **Atajos por defecto sin Espacio**: dictar = `Ctrl + Win`, traducir =
  `Ctrl + Win + Shift`. Los chords con Win + Espacio abrían el selector de
  idioma de teclado de Windows cuando la barra llegaba antes que los
  modificadores (en PCs con dos distribuciones, lo normal en usuarios
  bilingües). Las instalaciones con el default anterior se migran solas; una
  tecla elegida por el usuario se respeta.
- **Cambio de modo sin soltar**: si ya dictas con Ctrl + Win y añades Shift,
  la grabación sigue y al final se traduce (`on_switch` en
  `MultiHotkeyManager`; la barra flotante pasa a mostrar EN/ES al instante).
- **Tecla fantasma anti-menú Inicio**: al dispararse un chord con Win o Alt
  se inyecta una tecla virtual sin asignar (0xE8, la técnica de AutoHotkey)
  para que soltar Win no abra el menú Inicio ni Alt active la barra de menús.
  Verificado inyectando las teclas en los tres órdenes posibles.
- Arreglado `HotkeyManager.stop()` (había quedado dentro de la subclase y el
  gestor múltiple no volvía a disparar tras un rebind).

## 2.12.0 — 2026-09-24

- **Dictar y traducir** (`app/translator.py`): un segundo atajo,
  `Ctrl + Win + Shift + Espacio`, transcribe como siempre y pega el texto ya
  traducido. Funciona en los dos sentidos: hablas en español y sale en inglés,
  o hablas en inglés y sale en español; el destino se elige en Inicio
  ("Traducir a") y si lo dictado ya está en ese idioma se deja tal cual.
  Modelos OPUS-MT (Helsinki-NLP) convertidos a CTranslate2 int8, ~80 MB por
  sentido, se descargan la primera vez que se usan y corren en CPU sin
  internet. La barra flotante muestra "EN"/"ES" mientras traduces.
- **Atajos múltiples** (`app/hotkeys.MultiHotkeyManager`): gana el chord más
  largo, así `Ctrl + Win + Shift + Espacio` no dispara también el dictado.
- **Inicio**: la tecla se muestra como una tecla física con el color de
  acento del tema; tarjeta de traducción con explicación en la app y botón
  para cambiar el atajo.
- **Ajustes** reorganizados por secciones; el tema se elige con fichas de
  color en vez de un desplegable; el prompt inicial queda dentro de "Ajustes
  avanzados".
- **Idioma por defecto según el sistema**: en un Windows en inglés Wisip
  arranca en inglés (`config.system_language()`).
- **Barra flotante**: mientras mantienes la tecla y el micrófono no manda
  audio, la barra avisa "¿Micrófono en silencio?" en ámbar. Arreglado que la
  barra dejara de aparecer tras cambiar de tema (el rebuild la destruía).
- Validador nuevo `scripts/check_translator.py` (oraciones, paquetes,
  atajos múltiples y traducción real si hay modelos).

## 2.11.2 — 2026-09-24

- Segunda entrega por auto-actualización (prueba real: la 2.11.1 se actualizó sola a la 2.11.2 desde un servidor simulado de releases).

## 2.11.1 — 2026-09-24

- Primera versión entregada por auto-actualización (prueba real del flujo completo: detección, descarga verificada, instalación silenciosa por usuario y reinicio).

## 2.11.0 — 2026-09-24

- **Auto-actualización** (`app/updater.py`): la app consulta la última release
  de GitHub al arrancar y cada 6 horas, descarga el instalador en segundo
  plano verificando `SHA256SUMS.txt`, y lo instala sola cuando llevas más de
  un minuto sin dictar; Wisip se reinicia con la versión nueva. Interruptor
  "Actualizar automáticamente" y botón "Buscar actualizaciones" en Ajustes;
  aviso "Instalar ahora" en Inicio si prefieres decidir tú.
- **Instalación por usuario** (`%LOCALAPPDATA%\Programs\Wisip`), sin UAC:
  es lo que hace posible actualizar en silencio. Quien tenga la versión
  anterior en `Program Files` debe desinstalarla una vez.
- Versión única en `app/version.py`; `EXE/sync_version.py` la copia al
  instalador y `EXE/publish_release.py` crea la release con el instalador y
  su SHA256. Validador `scripts/check_updater.py`.

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
