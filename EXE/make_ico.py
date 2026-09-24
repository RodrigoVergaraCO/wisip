"""Convierte icon.png → assets/icon.ico con múltiples resoluciones.

Uso:
    python EXE/make_ico.py
o:
    python EXE\make_ico.py

Idempotente: si el .ico ya está fresco no lo regenera (compara mtime).

Resoluciones generadas: 16, 24, 32, 48, 64, 128, 256. Windows escoge la
adecuada según contexto (icono pequeño de título vs. icono grande del
Escritorio).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "icon.png"
OUT_DIR = ROOT / "assets"
OUT = OUT_DIR / "icon.ico"

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    if not SRC.exists():
        print(f"[make_ico] no encuentro {SRC}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Evita re-generar si el .ico ya está al día.
    if OUT.exists() and OUT.stat().st_mtime >= SRC.stat().st_mtime:
        print(f"[make_ico] {OUT.relative_to(ROOT)} ya está actualizado")
        return 0

    print(f"[make_ico] leyendo {SRC.relative_to(ROOT)} ...")
    img = Image.open(SRC).convert("RGBA")

    # Encuadre cuadrado con padding transparente si la fuente no es cuadrada.
    w, h = img.size
    if w != h:
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
        img = canvas

    print(f"[make_ico] generando {OUT.relative_to(ROOT)} con tamaños {SIZES}")
    img.save(OUT, format="ICO", sizes=SIZES)
    print("[make_ico] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
