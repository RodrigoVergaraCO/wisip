# -*- coding: utf-8 -*-
"""Valida app/corrections.py sin UI: diff por palabras, guardado JSONL + WAV
en una carpeta temporal, carga, agregado, candidatas y set de evaluación.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_corrections.py
"""

import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import corrections as co  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    print("── word_diff ──")
    d = co.word_diff("Los prótesis de Amazon.", "Los proxys de Amazon.")
    check("sustitución simple", d == [["prótesis", "proxys"]], str(d))
    d = co.word_diff("abrí Williams Memo ayer", "abrí Billions MEmu ayer")
    check("sustitución de dos palabras", d == [["Williams Memo", "Billions MEmu"]], str(d))
    d = co.word_diff("hola, mundo.", "Hola mundo")
    check("solo mayúscula inicial cuenta como par (puntuación ignorada)", d == [["hola", "Hola"]], str(d))
    d = co.word_diff("esto es es una prueba", "esto es una prueba")
    check("borrado", d == [["es", ""]], str(d))
    d = co.word_diff("manda el informe", "manda el informe hoy")
    check("inserción", d == [["", "hoy"]], str(d))
    check("iguales → sin pares", co.word_diff("igual.", "igual") == [])
    d = co.word_diff("entra a wisip.ai.dashboard", "entra a wisip.ai/dashboard")
    check("URL como un token", d == [["wisip.ai.dashboard", "wisip.ai/dashboard"]], str(d))

    print("── guardar / cargar (carpeta temporal) ──")
    tmp = Path(tempfile.mkdtemp(prefix="wisip_corr_"))
    try:
        check("sin cambios → None", co.save_correction("igual", "igual", base=tmp) is None)
        check("vacío → None", co.save_correction("algo", "   ", base=tmp) is None)
        audio = (np.sin(np.linspace(0, 200, 16000)) * 0.5).astype(np.float32)
        e = co.save_correction("Los prótesis de Amazon.", "Los proxys de Amazon.", audio_f32=audio,
                               meta={"id": "20260924-150000-001", "modelo": "large-v3-turbo", "idioma": "es",
                                     "modo": "dictate", "audio_s": 1.0, "crudo": "los prótesis de amazon"}, base=tmp)
        check("entrada devuelta con pares", e and e["pares"] == [["prótesis", "proxys"]] and e["id"] == "20260924-150000-001", str(e))
        wav = co.audio_dir(tmp) / "20260924-150000-001.wav"
        check("WAV escrito", wav.is_file())
        with wave.open(str(wav)) as w:
            check("WAV 16 kHz mono int16 de 1 s", w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getnframes() == 16000)
        e2 = co.save_correction("Los prótesis de Amazon otra vez", "Los proxys de Amazon otra vez", base=tmp)
        check("segunda sin audio", e2 and e2["audio"] is None)
        e3 = co.save_correction("abrí Williams Memo", "abrí Billions MEmu", base=tmp, meta={"modo": "translate"})
        loaded = co.load_corrections(base=tmp)
        check("carga 3 entradas en orden", [x["id"] for x in loaded] == [e["id"], e2["id"], e3["id"]], str([x["id"] for x in loaded]))
        check("count_this_month = 3", co.count_this_month(base=tmp) == 3)
        check("días=0 → todas", len(co.load_corrections(days=None, base=tmp)) == 3)
        agg = co.aggregate(loaded)
        check("agregado cuenta 2 veces prótesis→proxys", agg[("prótesis", "proxys")] == 2 and agg[("Williams Memo", "Billions MEmu")] == 1, str(agg))
        sugg = co.suggest(loaded)
        check("candidatas ordenadas por frecuencia con fix", [(s["word"], s["fix"], s["count"]) for s in sugg] == [("prótesis", "proxys", 2), ("Williams Memo", "Billions MEmu", 1)], str(sugg))
        check("existing filtra", [s["word"] for s in co.suggest(loaded, existing={"PRÓTESIS"})] == ["Williams Memo"])
        check("min_count filtra", [s["word"] for s in co.suggest(loaded, min_count=2)] == ["prótesis"])
        ev = co.eval_set(loaded, base=tmp)
        check("set de evaluación: 1 wav con referencia", len(ev) == 1 and ev[0][1] == "Los proxys de Amazon." and ev[0][0].is_file())
        rep = co.report(loaded)
        check("informe menciona sustituciones", "prótesis" in rep and "Correcciones: 3" in rep)
        # reescrituras largas no son reemplazos
        e4 = co.save_correction("una dos tres cuatro cinco seis", "siete ocho nueve diez once doce", base=tmp)
        check("reescritura larga se guarda pero no se sugiere", e4 is not None and all(s["word"] != "una dos tres cuatro cinco seis" for s in co.suggest(co.load_corrections(base=tmp))))
        check("carpeta vacía → 0", co.count_this_month(base=tmp / "nada") == 0 and co.load_corrections(base=tmp / "nada") == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de correcciones pasaron.")


if __name__ == "__main__":
    main()
