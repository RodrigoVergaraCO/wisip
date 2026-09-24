<p align="center">
  <img src="logo.png" alt="Wisip" width="96">
</p>

<h1 align="center">Wisip</h1>

<p align="center">
  <b>Local push-to-talk dictation for Windows.</b><br>
  Hold a key, speak (Spanish, English or both), release: the text lands in whatever app has focus.<br>
  100 % offline. No accounts, no API keys, no subscription.
</p>

<p align="center">
  <a href="https://github.com/acropolifamily-web/wisip/actions/workflows/validate.yml"><img src="https://github.com/acropolifamily-web/wisip/actions/workflows/validate.yml/badge.svg" alt="validate"></a>
  <img src="https://img.shields.io/badge/python-3.10–3.12-blue" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4" alt="windows">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="license">
</p>

<p align="center">
  <a href="https://acropolifamily-web.github.io/wisip/">Website</a> ·
  <a href="README.es.md">Leer en español</a> ·
  <a href="docs/MANUAL.es.md">Full manual (es)</a> ·
  <a href="docs/ROADMAP.md">Roadmap (es)</a>
</p>

---

## Why

Cloud dictation tools send your voice to a server and charge monthly. Wisip runs
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your own machine,
transcribes **while you are still talking**, and pastes the result into ChatGPT,
VS Code, WhatsApp Web, Notion, a form, anything.

On an RTX 3060 with `large-v3-turbo`, 30 seconds of speech transcribe in
about half a second. Without a GPU it falls back to CPU automatically.

## What it does

- **Push-to-talk global hotkey.** Hold, speak, release. Works in user mode (no admin).
- **Incremental transcription.** Audio is cut only on silences and transcribed in
  the background, so the wait after releasing the key is ~1–2 s regardless of
  how long you spoke.
- **Spanish + English in the same dictation.** Language is re-detected per
  segment, so a full English sentence stays in English and the next Spanish one
  stays in Spanish. English tech terms inside Spanish sentences are anchored
  with a prompt and `hotwords`.
- **Anti-hallucination guards.** Whisper invents subtitles credits, "thanks for
  watching" and laughter on noise. Wisip drops segments by exact blacklist,
  confidence (`avg_logprob` / `no_speech_prob`), prompt echo, trailing-noise
  trimming and a hardware-mute detector.
- **Vocabulary tab.** Editable hotwords with a real token meter (Whisper's
  224-token prompt budget), personal replacements that apply live, and a
  "analyze my dictations" button that mines the local log for misheard words
  (filtered with [wordfreq](https://github.com/rspeer/wordfreq)).
- **Replacement dictionaries.** Tech terms and brand casing (`chat gpt` →
  `ChatGPT`, `memu` → `MEmu`), safe Spanish fixes, and an opt-in "tech mode"
  for symbols.
- **Dictating URLs and emails.** "wisip punto ai slash dashboard" →
  `wisip.ai/dashboard`, "soporte arroba gmail punto com" → `soporte@gmail.com`.
- **Local dictation log.** Monthly JSONL (raw text, final text, discarded
  segments with confidence, applied replacements) plus WAV for suspicious
  dictations, with an analyzer script that turns patterns into dictionary
  entries. Can be switched off.
- **First-run wizard.** Privacy consent for the local log, microphone picker
  with a live level meter, hotkey capture, language and mixed mode, GPU
  acceleration offer. Five short steps, shown once.
- **Desktop polish.** Floating status pill with live mic level, four dark
  themes, tray icon, start with Windows, single instance, error log with
  native crash dialogs.

## Quick start (from source)

```powershell
git clone https://github.com/acropolifamily-web/wisip.git
cd wisip
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Optional: NVIDIA GPU acceleration (CUDA 12 runtime via pip, ~1.3 GB)
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12

python main.py
```

The first run downloads the Whisper model to `~/.cache/huggingface/hub`
(`small` ≈ 480 MB on CPU; `large-v3-turbo` ≈ 1.6 GB is selected automatically
when a working GPU is found). Default hotkey is <kbd>Ctrl</kbd> + <kbd>Win</kbd> + <kbd>Space</kbd>
(hold to talk); change it from the app.

> If you double-click `main.py`, Wisip re-launches itself with the venv's
> interpreter so the CUDA libraries are found. Set `WISIP_NO_VENV_REEXEC=1` to
> disable that guard.

## Installer

One installer for everyone, about 70 MB. Everything heavy is downloaded on
first run, with a progress window, and only once:

| Download | Size | When |
|---|---|---|
| Whisper model | 480 MB (`small`, CPU) or 1.6 GB (`large-v3-turbo`, GPU) | First start |
| NVIDIA acceleration pack | ~1.2 GB (cuBLAS / cuDNN / cudart / nvrtc, taken straight from NVIDIA's PyPI wheels by HTTP range requests, checksum-verified) | Offered when an NVIDIA GPU is detected; can be declined and installed later from the app |

The pack lives in `%LOCALAPPDATA%\Wisip\cuda` and is loaded at startup. AMD
and Intel GPUs run on CPU for now (see the roadmap). `EXE/` contains the
packaging pipeline (PyInstaller `--onedir --windowed` + Inno Setup); see
[`EXE/README-build.md`](EXE/README-build.md). Binaries are not published as
GitHub Releases yet.

## How the quality loop works

```
dictate  →  logs/dictados-YYYY-MM.jsonl (+ WAV when suspicious)
         →  scripts/analyze_logs.py --dias 7      (patterns, discards, tails)
         →  Vocabulary tab / replacements.py      (hotwords, dictionaries, blacklist)
         →  scripts/check_*.py                    (validators, run in CI)
```

Every guard in the code cites the real dictation that motivated it. The
validators run without loading a model:

| Script | Covers |
|---|---|
| `scripts/check_replacements.py` | dictionaries, brand casing, URL/email rebuild, "must not break" Spanish |
| `scripts/check_normalizer.py` | degraded emails/URLs (`usuario-hotmail.com`, fused `@`) |
| `scripts/check_join_chunks.py` | joining incremental chunks: casing, stray periods, boundary duplicates |
| `scripts/check_tail_guards.py` | trailing-noise trim, closing-phrase and low-confidence discards |
| `scripts/check_dictation_log.py` | JSONL log, stats, audio retention |
| `scripts/check_vocab.py` | token meter, personal CRUD, suggestion mining |
| `scripts/check_setup_assets.py` | first-run downloads: range-based wheel extraction, checksums, cancel, fallback (local HTTP server) |
| `scripts/check_audio_devices.py` | microphone enumeration (WASAPI dedupe, name-based resolution) and onboarding defaults |
| `scripts/check_license.py` | trial, activation, revalidation, offline grace and deactivation against a mock Lemon Squeezy server |

## Architecture

```
main.py                 controller: hotkey → recorder → transcriber → replacements → paste
app/audio_recorder.py   sounddevice capture, gain normalization, digital-silence detector
app/incremental.py      silence-based chunking, background worker, chunk joining
app/transcriber.py      faster-whisper wrapper, GPU/CPU selection, hallucination guards
app/replacements.py     dictionaries + URL/email pre-processor
app/postprocessor.py    generic email/URL/symbol normalizer
app/vocab.py            token meter, personal replacements CRUD, log mining (wordfreq)
app/dictation_log.py    monthly JSONL + WAV retention
app/setup_assets.py     first-run downloads: NVIDIA pack (range reads of PyPI wheels) + model
app/setup_window.py     progress window (model / GPU pack) with cancel
app/onboarding.py       first-run wizard: privacy, microphone (live level), hotkey, language, GPU
app/audio_devices.py    microphone enumeration (WASAPI, deduplicated) and name-based resolution
app/license.py          30-day trial + lifetime key per machine (Lemon Squeezy License API)
app/ui.py, themes.py    CustomTkinter window, palettes, Vocabulary tab
app/floating_bar.py     always-on-top status pill with live mic bars
app/hotkeys.py, typer.py, tray.py, autostart.py, single_instance.py, error_log.py
```

Everything user-specific lives in `%APPDATA%\local-voice-typer\`
(`app_settings.json`, `replacements.json`, `personal_replacements.json`,
`personal_emails.json`, `history.json`, `logs\`). Nothing leaves the machine.

## Requirements

- Windows 10 / 11
- Python 3.10 – 3.12 (3.11 recommended) for running from source
- A microphone. NVIDIA GPU optional (AMD/Intel run on CPU for now, see the roadmap)

## Roadmap

Measured evaluation set, engine abstraction (Parakeet via ONNX / whisper.cpp
Vulkan for AMD and Intel), an opt-in local-LLM cleanup pass, per-dictation
language switch and an English UI. Details in [docs/ROADMAP.md](docs/ROADMAP.md).

## Licensing model (the product)

The source is GPL-3.0. The installers are sold as a lifetime license per
machine: 30-day free trial, then a key from the store activates one PC
through the Lemon Squeezy License API. Deactivate from the Licencia tab, or
just uninstall, to move the key to another computer. Revalidation happens
every 30 days and tolerates 90 days offline. No account, no telemetry.

## License

[GPL-3.0](LICENSE). Built on faster-whisper, CTranslate2, OpenAI Whisper,
CustomTkinter, sounddevice, keyboard, pystray, Pillow and wordfreq.
