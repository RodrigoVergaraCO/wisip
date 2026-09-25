"""Versión de la app. ÚNICA fuente de verdad: EXE/sync_version.py copia este
valor a EXE/installer.iss al compilar, y app/updater.py la compara con la
última release de GitHub."""

__version__ = "2.13.0"


def version_tuple(v: str) -> tuple:
    """'v2.11.0' → (2, 11, 0). Tolera sufijos ('2.11.0-beta' → (2, 11, 0))."""
    v = (v or "").strip().lstrip("vV")
    out = []
    for part in v.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])
