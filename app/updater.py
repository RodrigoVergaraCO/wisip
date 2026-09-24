"""Auto-actualización (2.11.0) desde GitHub Releases.

Flujo (lo orquesta el Controller en main.py):
  1. `check_latest()` consulta la última release publicada del repo y devuelve
     {version, tag, asset_url, asset_size, sums_url, notes} o None.
  2. `is_update_available(info)` compara con `app.version.__version__`.
  3. `download_update(info, progress, cancel)` baja el instalador a
     %LOCALAPPDATA%\\Wisip\\updates\\ (vía .part), verifica el sha256 si la
     release trae SHA256SUMS.txt, y devuelve la ruta.
  4. `install_update(path)` lanza un proceso independiente que ejecuta el
     instalador en silencio (el instalador cierra Wisip solo) y vuelve a
     abrir Wisip al terminar. Como el instalador es por usuario
     (PrivilegesRequired=lowest), no aparece UAC: la actualización es
     realmente automática.

Sin red o sin releases → None, nunca una excepción hacia arriba.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from .version import __version__, version_tuple

_UA = f"Wisip/{__version__} (+https://github.com/RodrigoVergaraCO/wisip)"
_TIMEOUT = 20
_CHUNK = 1 << 20

RELEASES_API = "https://api.github.com/repos/RodrigoVergaraCO/wisip/releases/latest"
UPDATES_DIR = Path(
    os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
) / "Wisip" / "updates"


def _api_url() -> str:
    # Pruebas end-to-end: WISIP_UPDATE_API apunta a un servidor local.
    return os.environ.get("WISIP_UPDATE_API") or RELEASES_API


class UpdateCancelled(Exception):
    pass


def check_latest(on_log=None) -> dict | None:
    """Última release publicada (no borradores ni pre-releases). None si no
    hay releases, no hay red o la respuesta no trae un instalador."""
    log = on_log or (lambda m: None)
    req = urllib.request.Request(_api_url(), headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("[update] sin releases publicadas todavía")
        else:
            log(f"[update] GitHub respondió HTTP {e.code}")
        return None
    except Exception as e:
        log(f"[update] sin red para comprobar actualizaciones: {e}")
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    asset = None
    sums = None
    for a in data.get("assets") or []:
        name = str(a.get("name") or "")
        if re.fullmatch(r"Wisip-Setup-[\d.]+\.exe", name):
            asset = a
        elif name.upper() == "SHA256SUMS.TXT":
            sums = a
    if not asset or not version:
        log(f"[update] la release {tag or '?'} no trae instalador")
        return None
    return {
        "version": version,
        "tag": tag,
        "asset_name": asset.get("name"),
        "asset_url": asset.get("browser_download_url"),
        "asset_size": int(asset.get("size") or 0),
        "sums_url": (sums or {}).get("browser_download_url"),
        "notes": str(data.get("body") or ""),
        "html_url": str(data.get("html_url") or ""),
    }


def is_update_available(info: dict | None, current: str = __version__) -> bool:
    if not info:
        return False
    return version_tuple(info.get("version", "0")) > version_tuple(current)


def _expected_sha256(info: dict, on_log=None) -> str | None:
    url = info.get("sums_url")
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as e:
        (on_log or (lambda m: None))(f"[update] no pude leer SHA256SUMS.txt: {e}")
        return None
    name = str(info.get("asset_name") or "")
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name and len(parts[0]) == 64:
            return parts[0].lower()
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(_CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def downloaded_installer(info: dict) -> Path | None:
    """Ruta del instalador ya descargado y completo para esa versión, o None."""
    p = UPDATES_DIR / str(info.get("asset_name") or "")
    if p.is_file() and (not info.get("asset_size") or p.stat().st_size == info["asset_size"]):
        return p
    return None


def download_update(info: dict, progress=None, cancel=None, on_log=None) -> Path:
    """Descarga el instalador (si no está ya) y verifica tamaño y sha256."""
    log = on_log or (lambda m: None)
    progress = progress or (lambda d, t, l: None)
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPDATES_DIR / str(info["asset_name"])
    expected = _expected_sha256(info, log)
    ready = downloaded_installer(info)
    if ready is not None and (expected is None or _sha256_file(ready) == expected):
        log(f"[update] instalador {dest.name} ya descargado")
        return ready
    # Limpia instaladores de otras versiones.
    for old in UPDATES_DIR.glob("Wisip-Setup-*.exe*"):
        if old.name != dest.name:
            try:
                old.unlink()
            except OSError:
                pass
    tmp = dest.with_suffix(".exe.part")
    req = urllib.request.Request(info["asset_url"], headers={"User-Agent": _UA})
    h = hashlib.sha256()
    read = 0
    total = int(info.get("asset_size") or 0)
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateCancelled()
            chunk = r.read(_CHUNK)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            read += len(chunk)
            progress(read, total, f"Wisip {info['version']}")
    if total and read != total:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"descarga incompleta ({read}/{total} bytes)")
    if expected and h.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("el instalador descargado no coincide con SHA256SUMS.txt")
    if read < 20_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"el archivo descargado es demasiado pequeño ({read} bytes)")
    os.replace(tmp, dest)
    log(f"[update] descargado {dest.name} ({read / 1e6:.0f} MB)" + (" · sha256 OK" if expected else ""))
    return dest


def installed_exe_after_update() -> str:
    """Ruta del Wisip.exe que hay que relanzar tras instalar. El instalador
    es por usuario ({localappdata}\\Programs\\Wisip); si se actualiza desde una
    instalación antigua en Program Files, la nueva queda en esa ruta."""
    per_user = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Wisip" / "Wisip.exe"
    if getattr(sys, "frozen", False):
        current = Path(sys.executable)
        if current.parent == per_user.parent:
            return str(current)
    return str(per_user)


def install_command(installer: Path, relaunch_exe: str) -> list:
    """Comando del proceso auxiliar: instala en silencio y relanza Wisip."""
    return [
        "cmd.exe", "/d", "/c",
        f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART & '
        f'start "" "{relaunch_exe}"',
    ]


def install_update(installer: Path, on_log=None) -> bool:
    """Lanza la instalación en un proceso independiente y devuelve True. El
    instalador cierra Wisip (evento de instancia única) y el proceso auxiliar
    lo vuelve a abrir al terminar. En modo desarrollo (no frozen) no instala
    salvo WISIP_UPDATE_DEV=1."""
    log = on_log or (lambda m: None)
    if not getattr(sys, "frozen", False) and os.environ.get("WISIP_UPDATE_DEV") != "1":
        log(f"[update] modo desarrollo: no se instala {installer.name}")
        return False
    if not installer.is_file():
        log(f"[update] no encuentro el instalador {installer}")
        return False
    relaunch = installed_exe_after_update()
    cmd = install_command(installer, relaunch)
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    except Exception as e:
        log(f"[update] no pude lanzar el instalador: {e}")
        return False
    log(f"[update] instalando {installer.name}; Wisip se reiniciará solo")
    return True


def format_notes(notes: str, max_lines: int = 6) -> str:
    lines = [ln.strip("-• ").strip() for ln in (notes or "").splitlines() if ln.strip()]
    return "\n".join("· " + ln for ln in lines[:max_lines])


def last_check_age_hours(ts: str | None) -> float:
    try:
        return (time.time() - float(ts or 0)) / 3600.0
    except Exception:
        return 1e9
