# -*- coding: utf-8 -*-
"""Valida la limpieza de puntos suspensivos y el registro de dictados SIN
grabar voz ni cargar el modelo:

  - strip_ellipsis_text(): quita los "..." de pausa sin romper correos,
    decimales ni puntuación normal.
  - is_hallucinated_segment(): descarta segmentos de pura puntuación ("...").
  - DictationLog: escribe JSONL, guarda WAV y respeta el tope de disco
    (probado contra un directorio temporal, NO toca tu %APPDATA%).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_dictation_log.py
"""

import json
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app import config  # noqa: E402
from app.dictation_log import DictationLog  # noqa: E402
from app.transcriber import (  # noqa: E402
    is_hallucinated_segment,
    strip_ellipsis_text,
)

FALLOS = []


def check(nombre, obtenido, esperado):
    ok = obtenido == esperado
    print(f"  {'OK ' if ok else 'FALLO'} {nombre}")
    if not ok:
        print(f"        esperado: {esperado!r}")
        print(f"        obtenido: {obtenido!r}")
        FALLOS.append(nombre)


print("── strip_ellipsis_text ──")
check("pausa a mitad de frase",
      strip_ellipsis_text("Hola... quería decirte algo"),
      ("Hola quería decirte algo", 1))
check("elipsis unicode",
      strip_ellipsis_text("Bueno… entonces vamos"),
      ("Bueno entonces vamos", 1))
check("al final del dictado",
      strip_ellipsis_text("y eso fue todo..."),
      ("y eso fue todo", 1))
check("varias pausas",
      strip_ellipsis_text("Sí... bueno... no sé..."),
      ("Sí bueno no sé", 3))
check("antes de interrogación",
      strip_ellipsis_text("¿Vamos a ver...?"),
      ("¿Vamos a ver?", 1))
check("texto que es solo puntos",
      strip_ellipsis_text("..."),
      ("", 1))
check("muchos puntos seguidos",
      strip_ellipsis_text("espera...... ya"),
      ("espera ya", 1))
check("NO toca punto de fin de frase",
      strip_ellipsis_text("Hola. Todo bien."),
      ("Hola. Todo bien.", 0))
check("NO toca correos ni dominios",
      strip_ellipsis_text("escribe a user@amara.org ya"),
      ("escribe a user@amara.org ya", 0))
check("NO toca decimales",
      strip_ellipsis_text("mide 3.14 metros"),
      ("mide 3.14 metros", 0))
check("texto vacío",
      strip_ellipsis_text(""),
      ("", 0))

print("── is_hallucinated_segment: pura puntuación ──")
check("segmento '...' se descarta",
      is_hallucinated_segment("...", None, None),
      "solo puntuación (pausa)")
check("segmento '…' se descarta",
      is_hallucinated_segment("…", -0.2, 0.1),
      "solo puntuación (pausa)")
check("habla normal NO se descarta",
      is_hallucinated_segment("Hola, ¿cómo estás?", -0.3, 0.05),
      None)
check("frase fantasma sigue cayendo",
      is_hallucinated_segment("¡Gracias por ver!", -0.3, 0.05),
      "frase fantasma conocida")

print("── DictationLog (en directorio temporal) ──")
tmp = Path(tempfile.mkdtemp(prefix="wisip_log_check_"))
# Redirige las rutas del registro al directorio temporal SOLO en este proceso.
config.DICTATION_LOGS_DIR = tmp / "logs"
config.DICTATION_LOG_AUDIO_DIR = tmp / "logs" / "audio"

logs = []
dlog = DictationLog(on_log=logs.append)

entry_id = dlog.add({
    "id": "20260716-120000-000",
    "audio_s": 3.5,
    "crudo": "Hola... quería",
    "final": "Hola quería",
    "puntos_suspensivos": 1,
    "sospechoso": True,
})
check("add devuelve el id", entry_id, "20260716-120000-000")

archivos = list(config.DICTATION_LOGS_DIR.glob("dictados-*.jsonl"))
check("se creó un JSONL mensual", len(archivos), 1)
with archivos[0].open("r", encoding="utf-8") as f:
    linea = json.loads(f.readline())
check("la entrada conserva el texto crudo", linea["crudo"], "Hola... quería")
check("la entrada tiene ts automático", "ts" in linea, True)

# Audio: 1s de seno a 16kHz → WAV int16 válido.
audio = (0.3 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
name = dlog.save_audio(audio, "20260716-120000-000")
check("se guardó el WAV", name, "20260716-120000-000.wav")
wav_path = config.DICTATION_LOG_AUDIO_DIR / name
check("el WAV existe y pesa ~32KB", 30000 < wav_path.stat().st_size < 34000, True)

# Tope de disco: con tope ~2 archivos, el más viejo debe borrarse.
config.DICTATION_LOG_AUDIO_MAX_MB = 0.07  # ~73KB → caben 2 WAV de 32KB
dlog.save_audio(audio, "20260716-120001-000")
dlog.save_audio(audio, "20260716-120002-000")
restantes = sorted(p.name for p in config.DICTATION_LOG_AUDIO_DIR.glob("*.wav"))
check("el tope borra el WAV más viejo",
      restantes,
      ["20260716-120001-000.wav", "20260716-120002-000.wav"])

print()
if FALLOS:
    print(f"RESULTADO: {len(FALLOS)} fallo(s): {FALLOS}")
    sys.exit(1)
print("RESULTADO: todos los casos OK")
