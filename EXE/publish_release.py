"""Publica (o actualiza) la release de GitHub de la versión actual.

Requisitos: `gh` autenticado con la cuenta dueña del repo y el instalador
EXE/installer/Wisip-Setup-{version}.exe ya compilado (EXE/build.bat +
build_installer.bat).

Uso (desde la raíz del proyecto, con el venv):
    python EXE/publish_release.py            # crea/actualiza la release como BORRADOR
    python EXE/publish_release.py --publish  # la deja publicada (visible para el auto-update)

Sube el instalador y SHA256SUMS.txt (el auto-update verifica el hash).
Las notas salen de la sección de esa versión en CHANGELOG.md.
"""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.version import __version__  # noqa: E402

TAG = f"v{__version__}"
INSTALLER = ROOT / "EXE" / "installer" / f"Wisip-Setup-{__version__}.exe"
SUMS = ROOT / "EXE" / "installer" / "SHA256SUMS.txt"
publish = "--publish" in sys.argv


def changelog_notes() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"## {re.escape(__version__)}[^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
    body = (m.group(1).strip() if m else "").strip()
    header = ("Instalador único para Windows 10/11 (~77 MB). Al primer arranque descarga el modelo de voz "
              "y, si hay GPU NVIDIA, el paquete de aceleración. Prueba gratuita de 30 días.\n\n")
    return header + (body or "Ver CHANGELOG.md.")


def main():
    if not INSTALLER.is_file():
        print(f"no existe {INSTALLER}; compila primero (EXE\\build.bat + EXE\\build_installer.bat)")
        sys.exit(1)
    sha = hashlib.sha256(INSTALLER.read_bytes()).hexdigest()
    SUMS.write_text(f"{sha}  {INSTALLER.name}\n", encoding="utf-8")
    print(f"sha256 {sha[:16]}…  {INSTALLER.name} ({INSTALLER.stat().st_size / 1e6:.0f} MB)")

    exists = subprocess.run(["gh", "release", "view", TAG], capture_output=True, text=True).returncode == 0
    notes = changelog_notes()
    if exists:
        subprocess.run(["gh", "release", "upload", TAG, str(INSTALLER), str(SUMS), "--clobber"], check=True)
        subprocess.run(["gh", "release", "edit", TAG, "--title", f"Wisip {__version__}", "--notes", notes,
                        "--draft=false" if publish else "--draft"], check=True)
        print(f"release {TAG} actualizada" + (" y PUBLICADA" if publish else " (borrador)"))
    else:
        cmd = ["gh", "release", "create", TAG, str(INSTALLER), str(SUMS), "--title", f"Wisip {__version__}", "--notes", notes]
        if not publish:
            cmd.append("--draft")
        subprocess.run(cmd, check=True)
        print(f"release {TAG} creada" + (" y PUBLICADA" if publish else " (borrador)"))


if __name__ == "__main__":
    main()
