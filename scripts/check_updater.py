# -*- coding: utf-8 -*-
"""Valida la auto-actualización (app/updater.py) SIN red ni GitHub: un servidor
HTTP local imita la API de releases y sirve un "instalador" falso con su
SHA256SUMS.txt.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_updater.py
"""

import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import updater  # noqa: E402
from app.version import __version__, version_tuple  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class _Store:
    files: dict = {}
    latest: dict | None = None


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/latest":
            if _Store.latest is None:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(_Store.latest).encode()
        else:
            body = _Store.files.get(self.path.lstrip("/"))
            if body is None:
                self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    os.environ["WISIP_UPDATE_API"] = base + "latest"
    tmp = Path(tempfile.mkdtemp(prefix="wisip_upd_"))
    orig_dir = updater.UPDATES_DIR
    updater.UPDATES_DIR = tmp / "updates"
    logs = []
    try:
        print("── Versiones ──")
        check("version_tuple", version_tuple("v2.11.0") == (2, 11, 0) and version_tuple("2.9") == (2, 9, 0) and version_tuple("3.0.1-beta") == (3, 0, 1))
        check("__version__ válida", version_tuple(__version__) > (2, 10, 0))
        check("no hay actualización si es igual", not updater.is_update_available({"version": __version__}))
        check("hay actualización si es mayor", updater.is_update_available({"version": "99.0.0"}))
        check("no hay si es menor", not updater.is_update_available({"version": "1.0.0"}))
        check("None → no hay", not updater.is_update_available(None))

        print("── check_latest ──")
        check("sin releases (404) → None", updater.check_latest(logs.append) is None and any("sin releases" in m for m in logs))
        fake = os.urandom(25_000_000)
        sha = hashlib.sha256(fake).hexdigest()
        _Store.files = {"Wisip-Setup-99.0.0.exe": fake, "SHA256SUMS.txt": f"{sha}  Wisip-Setup-99.0.0.exe\n".encode()}
        _Store.latest = {"tag_name": "v99.0.0", "draft": False, "prerelease": False, "body": "- Mejora A\n- Mejora B",
                         "html_url": base + "rel", "assets": [
                             {"name": "Wisip-Setup-99.0.0.exe", "browser_download_url": base + "Wisip-Setup-99.0.0.exe", "size": len(fake)},
                             {"name": "SHA256SUMS.txt", "browser_download_url": base + "SHA256SUMS.txt", "size": 80}]}
        info = updater.check_latest(logs.append)
        check("release parseada", info and info["version"] == "99.0.0" and info["asset_size"] == len(fake) and info["sums_url"], str(info))
        check("notas formateadas", updater.format_notes(info["notes"]).startswith("· Mejora A"))
        _Store.latest["draft"] = True
        check("borrador → None", updater.check_latest() is None)
        _Store.latest["draft"] = False
        _Store.latest["assets"] = _Store.latest["assets"][1:]
        check("release sin instalador → None", updater.check_latest(logs.append) is None)
        _Store.latest["assets"].insert(0, {"name": "Wisip-Setup-99.0.0.exe", "browser_download_url": base + "Wisip-Setup-99.0.0.exe", "size": len(fake)})

        print("── Descarga ──")
        prog = []
        p = updater.download_update(info, progress=lambda d, t, l: prog.append((d, t)), on_log=logs.append)
        check("instalador descargado", p.is_file() and p.stat().st_size == len(fake) and p.name == "Wisip-Setup-99.0.0.exe")
        check("progreso monótono hasta el total", prog and prog[-1][0] == len(fake) and all(prog[i][0] <= prog[i+1][0] for i in range(len(prog)-1)))
        check("sha256 verificado", any("sha256 OK" in m for m in logs))
        check("segunda vez no vuelve a bajar", updater.download_update(info, on_log=logs.append) == p and any("ya descargado" in m for m in logs))
        check("downloaded_installer la encuentra", updater.downloaded_installer(info) == p)
        # sha malo → error y sin archivo
        _Store.files["SHA256SUMS.txt"] = ("0" * 64 + "  Wisip-Setup-99.0.0.exe\n").encode()
        shutil.rmtree(updater.UPDATES_DIR, ignore_errors=True)
        try:
            updater.download_update(info, on_log=logs.append)
            check("sha256 malo → error", False)
        except RuntimeError as e:
            check("sha256 malo → error", "SHA256SUMS" in str(e) and not list(updater.UPDATES_DIR.glob("*.exe")))
        # cancelación
        _Store.files["SHA256SUMS.txt"] = f"{sha}  Wisip-Setup-99.0.0.exe\n".encode()
        cancel = threading.Event()
        try:
            updater.download_update(info, progress=lambda d, t, l: cancel.set(), cancel=cancel, on_log=logs.append)
            check("cancelar → UpdateCancelled", False)
        except updater.UpdateCancelled:
            check("cancelar → UpdateCancelled", True)
        # archivo demasiado pequeño → error
        small = b"x" * 1000
        _Store.files["Wisip-Setup-98.0.0.exe"] = small
        info_small = dict(info, version="98.0.0", asset_name="Wisip-Setup-98.0.0.exe", asset_url=base + "Wisip-Setup-98.0.0.exe", asset_size=len(small), sums_url=None)
        try:
            updater.download_update(info_small, on_log=logs.append)
            check("archivo diminuto → error", False)
        except RuntimeError:
            check("archivo diminuto → error", True)

        print("── Instalación ──")
        cmd = updater.install_command(p, r"C:\y\Wisip.exe")
        script = Path(cmd[-1]); body = script.read_text(encoding="utf-8")
        check("comando auxiliar = cmd /c apply_update.cmd", cmd[:3] == ["cmd.exe", "/d", "/c"] and script.name == "apply_update.cmd" and script.is_file(), str(cmd))
        check("el .cmd instala en silencio y relanza", "/VERYSILENT" in body and f'"{p}"' in body and 'start "" "C:\\y\\Wisip.exe"' in body and "/LOG=" in body, body)
        check("sin comillas escapadas", '\\"' not in body)
        check("relanzar apunta a la instalación por usuario", updater.installed_exe_after_update().lower().endswith(r"programs\wisip\wisip.exe"))
        os.environ.pop("WISIP_UPDATE_DEV", None)
        check("en desarrollo no instala", updater.install_update(p, logs.append) is False and any("modo desarrollo" in m for m in logs))
    finally:
        updater.UPDATES_DIR = orig_dir
        os.environ.pop("WISIP_UPDATE_API", None)
        shutil.rmtree(tmp, ignore_errors=True)
        srv.shutdown()

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks del actualizador pasaron.")


if __name__ == "__main__":
    main()
