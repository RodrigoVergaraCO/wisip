"""Copia app/version.py → EXE/installer.iss (#define MyAppVersion).

Lo llama EXE/build.bat antes de compilar para que el instalador, el nombre
del archivo Wisip-Setup-X.Y.Z.exe y la versión que la app compara con GitHub
sean siempre la misma. Idempotente.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.version import __version__  # noqa: E402

ISS = ROOT / "EXE" / "installer.iss"
text = ISS.read_text(encoding="utf-8")
new, n = re.subn(r'#define MyAppVersion "[^"]*"', f'#define MyAppVersion "{__version__}"', text, count=1)
if n != 1:
    print("[sync_version] no encuentro #define MyAppVersion en installer.iss")
    sys.exit(1)
if new != text:
    ISS.write_text(new, encoding="utf-8")
    print(f"[sync_version] installer.iss -> {__version__}")
else:
    print(f"[sync_version] installer.iss ya esta en {__version__}")
