# -*- coding: utf-8 -*-
"""Informe de las correcciones guardadas desde la app (Inicio → "Guardar
corrección"): sustituciones recurrentes, borrados, añadidos, últimas
correcciones y tamaño del set de evaluación (WAV + texto de referencia).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/analyze_corrections.py            # todo
    python scripts/analyze_corrections.py --dias 30  # último mes
    python scripts/analyze_corrections.py --json     # crudo, para procesar
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import corrections  # noqa: E402
from app import vocab  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    entries = corrections.load_corrections(days=args.dias)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=1))
        return
    print(corrections.report(entries))
    existing = {w for w, _ in vocab.personal_list()}
    sugg = corrections.suggest(entries, min_count=1, existing=existing)
    if sugg:
        print()
        print("Candidatas a reemplazo personal (aún no añadidas):")
        for s in sugg:
            print(f"  {s['count']:3d}  {s['word']!r} → {s['fix']!r}")
    ev = corrections.eval_set(entries)
    print()
    print(f"Set de evaluación: {len(ev)} audios con referencia en {corrections.audio_dir()}")


if __name__ == "__main__":
    main()
