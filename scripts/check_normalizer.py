# -*- coding: utf-8 -*-
"""Valida la CADENA COMPLETA de postprocesado sin grabar voz:

    texto  →  Replacements.apply()  →  normalize_emails_urls_symbols()

Es el mismo orden que usa main.py (reemplazos generales + personales, y luego
el normalizador de correos/URLs/símbolos). Imprime entrada → salida y marca
los casos que deben mejorar y los que NO deben romperse.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_normalizer.py

NOTA: los ALIAS de correo (p.ej. 'mi correo principal' → tu correo real)
viven en tu personal_emails.json local y NO se prueban aquí. La regla GENÉRICA
'usuario-hotmail.com' → 'usuario@hotmail.com' funciona sin configurar nada.
"""

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.postprocessor import normalize_emails_urls_symbols  # noqa: E402
from app.replacements import Replacements  # noqa: E402
from app.settings import Settings  # noqa: E402


# (entrada, fragmento_esperado | None, debe_estar_presente)
# debe_estar_presente=True  → el fragmento DEBE aparecer (caso que mejora).
# debe_estar_presente=False → el fragmento NO debe aparecer (caso que no rompe).
CASES = [
    # ── Correos (deben mejorar) ──────────────────────────────────────
    ("Mi correo es juanperez arroba hotmail punto com.", "juanperez@hotmail.com", True),
    ("Mi correo es juanperez arroba jodmail punto com.", "juanperez@hotmail.com", True),
    ("Mi correo puede ser juanperez-hotmail.com.", "juanperez@hotmail.com", True),
    ("El email es juanperez @ hotmail . com.", "juanperez@hotmail.com", True),
    ("Escríbeme a juanperez@ hotmail.com.", "juanperez@hotmail.com", True),
    ("Mi correo es juanperez @hotmail .com.", "juanperez@hotmail.com", True),
    # Genérico (sin alias): cualquier usuario + proveedor conocido.
    ("Mi correo es soporte-gmail.com.", "soporte@gmail.com", True),
    ("Escríbeme a ventas arroba outlook punto com.", "ventas@outlook.com", True),
    # ── URLs (deben seguir funcionando) ──────────────────────────────
    ("Abre wisip punto ai slash dashboard.", "wisip.ai/dashboard", True),
    ("La URL es api punto wisip punto co slash v1 slash users.", "api.wisip.co/v1/users", True),
    ("También puedo dictar api.wisip.cov-v1-users.", "api.wisip.co/v1/users", True),
    ("Una URL como wisip.ai-dashboard.", "wisip.ai/dashboard", True),
    # ── NO deben romperse (texto normal con guiones/puntos) ──────────
    ("Esto es una frase normal con guion medio y no debería cambiarse.", "@", False),
    ("Tengo una arquitectura cliente-servidor con micro-servicios.", "@", False),
    ("Vamos directo al punto importante. Es la reunión de hoy.", "importante.es", False),
    ("El cliente-servidor habla con el micro-servicio principal.", "/", False),
]


def main():
    settings = Settings(on_log=lambda m: None).all()
    settings["normalize_emails_urls"] = True
    settings["debug_normalizer"] = False
    reps = Replacements(on_log=lambda m: None)

    ok = 0
    total = 0
    for text, frag, must_be_present in CASES:
        out, _applied = reps.apply(text)
        out = normalize_emails_urls_symbols(out, settings)
        total += 1
        present = frag in out
        passed = present if must_be_present else (not present)
        ok += int(passed)
        tag = "[OK]" if passed else ("[FALTA]" if must_be_present else "[ROMPIÓ]")
        print(f"{tag}")
        print("  IN :", text)
        print("  OUT:", out)
        if must_be_present:
            print(f"  esperado contiene: {frag!r}")
        else:
            print(f"  NO debe contener:  {frag!r}")
        print("-" * 78)

    print(f"\nCasos correctos: {ok}/{total}")
    if ok < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
