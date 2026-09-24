<p align="center">
  <img src="logo.png" alt="Wisip" width="96">
</p>

<h1 align="center">Wisip</h1>

<p align="center">
  <b>Dictado local push-to-talk para Windows.</b><br>
  Mantén una tecla, habla (español, inglés o los dos), suelta: el texto aparece en la app que tengas activa.<br>
  100 % sin internet. Sin cuentas, sin API keys, sin suscripción.
</p>

<p align="center">
  <a href="README.md">Read in English</a> ·
  <a href="docs/MANUAL.es.md">Manual completo</a> ·
  <a href="docs/ROADMAP.md">Roadmap</a>
</p>

---

## Por qué

Las herramientas de dictado en la nube mandan tu voz a un servidor y cobran
al mes. Wisip corre [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
en tu propio equipo, transcribe **mientras sigues hablando** y pega el
resultado en ChatGPT, VS Code, WhatsApp Web, Notion, un formulario, lo que sea.

En una RTX 3060 con `large-v3-turbo`, 30 segundos de voz se transcriben en
medio segundo. Sin GPU cae a CPU automáticamente.

## Qué hace

- **Hotkey global push-to-talk.** Mantén, habla, suelta. Funciona en modo usuario (sin administrador).
- **Transcripción incremental.** El audio se corta solo en silencios y se
  transcribe en segundo plano; al soltar la tecla la espera es de ~1–2 s sin
  importar cuánto dictaste.
- **Español + inglés en el mismo dictado.** El idioma se re-detecta por
  segmento: una frase completa en inglés queda en inglés y la siguiente en
  español queda en español. Los términos técnicos en inglés dentro de frases en
  español se anclan con un prompt y `hotwords`.
- **Guardas anti-alucinación.** Whisper inventa créditos de subtítulos,
  "gracias por ver el video" y risas sobre el ruido. Wisip descarta segmentos
  por lista negra exacta, confianza (`avg_logprob` / `no_speech_prob`), eco del
  prompt, recorte del ruido de cola y un detector de micrófono en mute.
- **Pestaña Vocabulario.** Hotwords editables con medidor de tokens real (el
  presupuesto de 224 tokens del prompt de Whisper), reemplazos personales que
  aplican en vivo y un botón "Analizar mis dictados" que mina el registro local
  en busca de palabras mal oídas (filtradas con
  [wordfreq](https://github.com/rspeer/wordfreq)).
- **Diccionarios de reemplazo.** Términos técnicos y marcas (`chat gpt` →
  `ChatGPT`, `memu` → `MEmu`), correcciones seguras de español y un "modo
  técnico" opcional para símbolos.
- **Dictar URLs y correos.** "wisip punto ai slash dashboard" →
  `wisip.ai/dashboard`, "soporte arroba gmail punto com" → `soporte@gmail.com`.
- **Registro local de dictados.** JSONL mensual (texto crudo, texto final,
  descartes con confianza, reemplazos aplicados) más WAV de los dictados
  sospechosos, con un analizador que convierte patrones en entradas de
  diccionario. Se puede apagar.
- **Asistente de primer arranque.** Consentimiento del registro local,
  selector de micrófono con medidor en vivo, captura de la tecla, idioma y
  modo mixto, oferta de aceleración GPU. Cinco pasos cortos, una sola vez.
- **Detalles de escritorio.** Barra flotante con nivel de micro en vivo, cuatro
  temas oscuros, icono en bandeja, inicio con Windows, instancia única, log de
  errores con diálogos nativos.

## Empezar (desde el código)

```powershell
git clone https://github.com/RodrigoVergaraCO/wisip.git
cd wisip
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Opcional: aceleración NVIDIA (runtime CUDA 12 vía pip, ~1,3 GB)
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12

python main.py
```

La primera ejecución descarga el modelo a `~/.cache/huggingface/hub` (`small`
≈ 480 MB en CPU; `large-v3-turbo` ≈ 1,6 GB se elige solo cuando detecta una
GPU que funciona). El atajo por defecto es <kbd>Ctrl</kbd> + <kbd>Win</kbd> + <kbd>Espacio</kbd>
(mantener para hablar); se cambia desde la app.

> Si abres `main.py` con doble clic, Wisip se relanza con el intérprete del
> venv para encontrar las librerías CUDA. `WISIP_NO_VENV_REEXEC=1` desactiva
> ese guard.

## Instalador

Un solo instalador para todos, de unos 70 MB. Lo pesado se descarga en el
primer arranque, con ventana de progreso, y una sola vez:

| Descarga | Tamaño | Cuándo |
|---|---|---|
| Modelo Whisper | 480 MB (`small`, CPU) o 1,6 GB (`large-v3-turbo`, GPU) | Primer arranque |
| Paquete de aceleración NVIDIA | ~1,2 GB (cuBLAS / cuDNN / cudart / nvrtc, sacados de los wheels oficiales de NVIDIA en PyPI por rangos HTTP, con verificación de checksum) | Se ofrece al detectar GPU NVIDIA; se puede posponer e instalar después desde la app |

El paquete vive en `%LOCALAPPDATA%\Wisip\cuda` y se carga al arrancar. Las
GPU AMD e Intel van por CPU por ahora (ver roadmap). `EXE/` contiene el
pipeline de empaquetado (PyInstaller `--onedir --windowed` + Inno Setup); ver
[`EXE/README-build.md`](EXE/README-build.md). Todavía no se publican como
Releases de GitHub.

## Ciclo de calidad

```
dictar   →  logs/dictados-YYYY-MM.jsonl (+ WAV si es sospechoso)
         →  scripts/analyze_logs.py --dias 7      (patrones, descartes, colas)
         →  pestaña Vocabulario / replacements.py (hotwords, diccionarios, lista negra)
         →  scripts/check_*.py                    (validadores, corren en CI)
```

Cada guarda del código cita el dictado real que la motivó. Los validadores
corren sin cargar el modelo: `check_replacements`, `check_normalizer`,
`check_join_chunks`, `check_tail_guards`, `check_dictation_log`, `check_vocab`, `check_setup_assets`, `check_audio_devices`, `check_license`.

## Requisitos

- Windows 10 / 11
- Python 3.10 – 3.12 (recomendado 3.11) para correr desde el código
- Micrófono. GPU NVIDIA opcional (AMD/Intel van por CPU por ahora, ver roadmap)

## Roadmap

Set de evaluación medido, abstracción de motor (Parakeet vía ONNX /
whisper.cpp Vulkan para AMD e Intel), capa opcional de limpieza con LLM local,
selector de idioma por dictado y UI en inglés. Detalle en
[docs/ROADMAP.md](docs/ROADMAP.md).

## Modelo de licencia (el producto)

El código es GPL-3.0. Los instaladores se venden como licencia de por vida
por equipo: 30 días de prueba gratis y luego una clave de la tienda activa un
PC a través de la License API de Lemon Squeezy. Se desactiva desde la pestaña
Licencia, o simplemente desinstalando, para pasar la clave a otro equipo.
Se revalida cada 30 días y tolera 90 días sin internet. Sin cuenta, sin
telemetría.

## Licencia

[GPL-3.0](LICENSE). Construido sobre faster-whisper, CTranslate2, OpenAI
Whisper, CustomTkinter, sounddevice, keyboard, pystray, Pillow y wordfreq.
