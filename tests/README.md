# Suite de pruebas de Wisip

Pruebas automatizadas para medir tiempos, precisión y robustez de la UI antes
de producción. Todo es local (no usa APIs externas).

## Archivos

| Archivo | Qué hace |
|---|---|
| `corpus.py` | Textos de prueba (ES/EN/mixto, correos, URLs, términos, números, frase larga) + scoring (WER y aciertos de términos clave). |
| `audio_io.py` | TTS con voces SAPI de Windows → WAV 16 kHz mono; detección del cable VB-Audio; guardar/**restaurar** el dispositivo por defecto del proceso. |
| `run_bench.py` | Benchmark extremo a extremo: TTS → CABLE → `AudioRecorder` → `Transcriber` → reemplazos. Mide tiempos y precisión por modelo. |
| `ui_bot.py` | Bot que dispara TODOS los botones/controles y reporta errores. |
| `ANALISIS.md` | Conclusiones (tiempos, ¿adecuado para usuario final?, soluciones, bugs). |
| `report_*.md` / `report_*.json` | Salidas generadas por los scripts. |

## Requisitos

- El venv del proyecto (`.venv`) con las deps de `requirements.txt`.
- Voces SAPI (Windows trae al menos una; aquí: Helena es-ES, Zira en-US).
- Para la ruta por cable: **VB-Audio Virtual Cable** instalado (CABLE Input/Output).
  Sin cable, usa `--direct` (alimenta el WAV directo al modelo).
- Para medir GPU: runtime CUDA 12 instalado (ver `requirements.txt`).

## Uso

```powershell
# Bot de botones (rápido, no toca audio ni tus datos: usa un APPDATA temporal)
python tests\ui_bot.py

# Benchmark por cable (realista), modelos en caché:
python tests\run_bench.py --models base,small

# Comparar GPU vs CPU (rápido, sin reproducir en tiempo real):
python tests\run_bench.py --models small --perf fast_safe --direct   # GPU si hay
python tests\run_bench.py --models small --perf quality_current --direct  # CPU

# Idioma automático (recomendado para dictado mixto ES/EN):
python tests\run_bench.py --models small --language auto
```

## Seguridad de tus datos

- **`ui_bot.py`** redirige `%APPDATA%` a un directorio temporal antes de importar
  la app, así que **no toca** tu `app_settings.json`, `history.json` ni tus
  diccionarios de reemplazos.
- **`run_bench.py`** usa tu `replacements.json` real (para resultados fieles) pero
  **no modifica** tus settings ni tu historial.
- Ambos solo cambian `sounddevice.default.device` **dentro del proceso** y lo
  restauran al salir. El dispositivo predeterminado de **Windows nunca se toca**.
