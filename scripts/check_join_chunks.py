# -*- coding: utf-8 -*-
"""Valida la unión de tramos incrementales (join_chunks) SIN cargar el modelo.

Cubre los tres defectos de frontera detectados en el registro real:
  1. Mayúscula de arranque de tramo cuando la frase anterior sigue abierta
     (2026-07-21, 35% de los dictados).
  2. "punto + minúscula" en la frontera: el punto de cierre de tramo sobra
     (2026-09-23, 45% de los dictados multi-tramo).
  3. Palabra repetida en la frontera (2026-09-23, 7% de los multi-tramo).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_join_chunks.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.incremental import join_chunks  # noqa: E402

FAILS = []


def check(name: str, parts: list, expected: str):
    got = join_chunks(parts)
    ok = got == expected
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {name}")
    if not ok:
        print(f"         esperado: {expected!r}")
        print(f"         obtenido: {got!r}")
        FAILS.append(name)


def main():
    print("── 1. Mayúscula de arranque con frase abierta (2026-07-21) ──")
    check("frase abierta → minúscula",
          ["Voy a colocar el proxy", "En la máquina nueva."],
          "Voy a colocar el proxy en la máquina nueva.")
    check("frase cerrada → se respeta la mayúscula",
          ["Listo, ya quedó.", "Ahora sigue el login."],
          "Listo, ya quedó. Ahora sigue el login.")
    check("acrónimo no se toca",
          ["Se genera en el archivo", "PSD con todas las capas."],
          "Se genera en el archivo PSD con todas las capas.")
    check("coma al final → minúscula",
          ["Termina de llenar un campo,", "Luego baja hasta el fondo."],
          "Termina de llenar un campo, luego baja hasta el fondo.")

    print("\n── 2. Punto de cierre de tramo + continuación en minúscula (2026-09-23) ──")
    check("caso real: XAPK",
          ["lo único que encuentro es puro XAPK.", "por todos lados de internet."],
          "lo único que encuentro es puro XAPK por todos lados de internet.")
    check("caso real: GitHub",
          ["subir este proyecto al GitHub.", "para tener proyectos base subidos."],
          "subir este proyecto al GitHub para tener proyectos base subidos.")
    check("tres tramos encadenados",
          ["Necesito que revises.", "el código de Brave.", "y lo dejes listo."],
          "Necesito que revises el código de Brave y lo dejes listo.")
    check("punto + mayúscula → frase nueva (se conserva)",
          ["Ya está listo.", "Ahora vamos con el segundo paso."],
          "Ya está listo. Ahora vamos con el segundo paso.")
    check("signo de apertura + minúscula tras punto",
          ["Revisa el letrero.", "¿que dice verify?"],
          "Revisa el letrero ¿que dice verify?")
    check("'?' al final no se toca aunque siga minúscula",
          ["¿Ya lo revisaste?", "porque sigue fallando."],
          "¿Ya lo revisaste? porque sigue fallando.")
    check("'...' al final no se toca",
          ["Bueno, no sé...", "creo que sí."],
          "Bueno, no sé... creo que sí.")

    print("\n── 3. Palabra duplicada en la frontera (2026-09-23) ──")
    check("caso real: mi mi",
          ["para intentar mejorar mi", "mi GitHub y mi hoja de vida."],
          "para intentar mejorar mi mi GitHub y mi hoja de vida."
          .replace("mi mi", "mi"))
    check("duplicado con punto de cierre",
          ["y lo marca como.", "como listo el comando."],
          "y lo marca como listo el comando.")
    check("duplicado con coma tras la copia",
          ["así como", "como, dices, vinculadas."],
          "así como dices, vinculadas.")
    check("duplicado con mayúscula en la copia",
          ["notificármelo en", "En el software de escritorio."],
          "notificármelo en el software de escritorio.")
    check("NO es duplicado: palabras distintas",
          ["subir el archivo", "archivos nuevos también."],
          "subir el archivo archivos nuevos también.")
    check("tramo que queda vacío tras quitar el duplicado se omite",
          ["cierra la app", "app"],
          "cierra la app")
    check("una letra no cuenta como duplicado",
          ["voy a", "a la máquina."],
          "voy a a la máquina.")

    print("\n── 4. Robustez ──")
    check("tramos vacíos se ignoran", ["Hola.", "", None, "Sigo aquí."], "Hola. Sigo aquí.")
    check("un solo tramo intacto", ["Solo un tramo."], "Solo un tramo.")
    check("lista vacía", [], "")

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de join_chunks pasaron.")


if __name__ == "__main__":
    main()
