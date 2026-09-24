# -*- coding: utf-8 -*-
"""Valida las descargas de primer arranque (app/setup_assets.py) SIN red.

Levanta un servidor HTTP local con soporte de rangos, sirve "wheels" falsos
(zips con nvidia/<lib>/bin/*.dll) y comprueba:
  1. filtro de DLLs (wanted_dll) con exclusiones,
  2. lectura de la tabla central por rangos + extracción con CRC (incl. zip64),
  3. instalación completa del paquete → pack.json → gpu_pack_installed(),
  4. cancelación a mitad de descarga (no deja paquete),
  5. servidor SIN rangos → descarga completa + sha256 + extracción,
  6. detección de modelo en caché y formato de progreso.

Con `--red` añade una prueba real contra PyPI con el wheel más pequeño
(nvidia-cuda-runtime-cu12, 3,6 MB).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_setup_assets.py [--red]
"""

import hashlib
import http.server
import io
import os
import shutil
import sys
import tempfile
import threading
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import config  # noqa: E402
from app import setup_assets as sa  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


# ─── Servidor local con rangos ──────────────────────────────────────────

class _Store:
    files: dict = {}
    ranges = True


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _body(self):
        return _Store.files.get(self.path.lstrip("/"))

    def do_HEAD(self):
        data = self._body()
        if data is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes" if _Store.ranges else "none")
        self.end_headers()

    def do_GET(self):
        data = self._body()
        if data is None:
            self.send_response(404); self.end_headers(); return
        rng = self.headers.get("Range")
        if rng and _Store.ranges:
            start, end = rng.replace("bytes=", "").split("-")
            start = int(start); end = int(end) if end else len(data) - 1
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def _serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _fake_wheel(lib: str, dlls: dict, zip64: bool = False) -> bytes:
    """Zip con nvidia/<lib>/bin/<dll> (deflate), un .lib (no deseado) y un
    nvblas (excluido)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in dlls.items():
            if zip64:
                with zf.open(f"nvidia/{lib}/bin/{name}", "w", force_zip64=True) as f:
                    f.write(data)
            else:
                zf.writestr(f"nvidia/{lib}/bin/{name}", data)
        zf.writestr(f"nvidia/{lib}/lib/{lib}.lib", b"LIB" * 100)
        zf.writestr(f"nvidia/{lib}/bin/nvblas64_12.dll", b"NVBLAS" * 50)
        zf.writestr(f"nvidia_{lib}.dist-info/METADATA", b"Name: x\n", compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


def main():
    red = "--red" in sys.argv
    rng = __import__("random").Random(1)
    big = bytes(rng.getrandbits(8) for _ in range(1_500_000))   # poco comprimible
    small = b"cudart" * 20_000                                    # muy comprimible

    print("── 1. Filtro de DLLs ──")
    check("dll en bin se quiere", sa.wanted_dll("nvidia/cublas/bin/cublas64_12.dll") == ("cublas", "cublas64_12.dll"))
    check("lib/*.lib no", sa.wanted_dll("nvidia/cublas/lib/cublas.lib") is None)
    check("excluida cudnn_adv", sa.wanted_dll("nvidia/cudnn/bin/cudnn_adv64_9.dll") is None)
    check("excluida nvblas", sa.wanted_dll("nvidia/cublas/bin/nvblas64_12.dll") is None)
    check("dist-info no", sa.wanted_dll("nvidia_cublas_cu12-12.9.dist-info/RECORD") is None)
    check("nvrtc se conserva", sa.wanted_dll("nvidia/cuda_nvrtc/bin/nvrtc64_120_0.dll") is not None)

    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    w_runtime = _fake_wheel("cuda_runtime", {"cudart64_12.dll": small})
    w_cublas = _fake_wheel("cublas", {"cublas64_12.dll": big, "cublasLt64_12.dll": big[:700_000]}, zip64=True)
    w_cudnn = _fake_wheel("cudnn", {"cudnn64_9.dll": small, "cudnn_adv64_9.dll": big[:300_000]})
    _Store.files = {"runtime.whl": w_runtime, "cublas.whl": w_cublas, "cudnn.whl": w_cudnn}

    print("\n── 2. Zip remoto por rangos ──")
    rz = sa.RemoteZip(base + "cublas.whl")
    ents = rz.entries()
    names = [e["name"] for e in ents]
    check("tabla central leída (zip64 extra)", "nvidia/cublas/bin/cublas64_12.dll" in names and len(ents) == 5, str(names))
    e = next(x for x in ents if x["name"].endswith("cublas64_12.dll"))
    check("tamaños del miembro", e["usize"] == len(big) and 0 < e["csize"] <= len(big) + 4096)
    tmpd = Path(tempfile.mkdtemp(prefix="wisip_sa_"))
    seen = []
    rz.extract(e, tmpd / "out.dll", progress=lambda d, t, l: seen.append((d, t)), total=e["csize"], label="x")
    check("extracción idéntica al original", (tmpd / "out.dll").read_bytes() == big)
    check("progreso reportado y monótono", len(seen) >= 1 and seen[-1][0] == e["csize"] and all(seen[i][0] <= seen[i+1][0] for i in range(len(seen)-1)))
    e2 = next(x for x in sa.RemoteZip(base + "runtime.whl").entries() if x["name"].endswith("cudart64_12.dll"))
    bad = dict(e2); bad["crc"] = (e2["crc"] + 1) & 0xFFFFFFFF
    try:
        sa.RemoteZip(base + "runtime.whl").extract(bad, tmpd / "bad.dll")
        check("CRC incorrecto → error", False)
    except sa.DownloadError:
        check("CRC incorrecto → error", not (tmpd / "bad.dll").exists())

    print("\n── 3. Instalación completa del paquete ──")
    pack_dir = tmpd / "cuda"
    orig = (config.GPU_PACK_DIR, config.GPU_PACK_MANIFEST, config.NVIDIA_WHEELS, sa.pypi_wheel_url)
    fake_wheels = (
        {"name": "runtime", "version": "1", "lib": "cuda_runtime", "sha256": hashlib.sha256(w_runtime).hexdigest()},
        {"name": "cublas", "version": "1", "lib": "cublas", "sha256": hashlib.sha256(w_cublas).hexdigest()},
        {"name": "cudnn", "version": "1", "lib": "cudnn", "sha256": hashlib.sha256(w_cudnn).hexdigest()},
    )
    config.GPU_PACK_DIR = pack_dir
    config.GPU_PACK_MANIFEST = pack_dir / "pack.json"
    config.NVIDIA_WHEELS = fake_wheels
    sa.pypi_wheel_url = lambda name, version, expected=None: (base + name + ".whl", len(_Store.files[name + ".whl"]), hashlib.sha256(_Store.files[name + ".whl"]).hexdigest())
    try:
        logs = []
        prog = []
        check("antes: no instalado", not sa.gpu_pack_installed())
        out = sa.install_gpu_pack(progress=lambda d, t, l: prog.append((d, t, l)), on_log=logs.append)
        files = sorted(p.relative_to(pack_dir).as_posix() for p in pack_dir.glob("*/bin/*.dll"))
        check("solo DLLs deseadas", files == ["cublas/bin/cublas64_12.dll", "cublas/bin/cublasLt64_12.dll",
                                                "cuda_runtime/bin/cudart64_12.dll", "cudnn/bin/cudnn64_9.dll"], str(files))
        check("contenido íntegro", (pack_dir / "cublas/bin/cublas64_12.dll").read_bytes() == big
              and (pack_dir / "cudnn/bin/cudnn64_9.dll").read_bytes() == small)
        check("pack.json con versión actual", sa.gpu_pack_installed())
        check("progreso termina en total", prog and prog[-1][0] == prog[-1][1] > 0)
        check("sin carpeta .partial", not (tmpd / "cuda.partial").exists())
        check("modo rangos usado", any("por rangos" in m for m in logs))
        # manipular un archivo → deja de contar como instalado
        with open(pack_dir / "cudnn/bin/cudnn64_9.dll", "ab") as f:
            f.write(b"x")
        check("archivo alterado → no instalado", not sa.gpu_pack_installed())
        sa.remove_gpu_pack()
        check("remove_gpu_pack", not pack_dir.exists())

        print("\n── 4. Cancelación ──")
        cancel = threading.Event()
        def _cancel_mid(d, t, l):
            if d > 0:
                cancel.set()
        try:
            sa.install_gpu_pack(progress=_cancel_mid, cancel=cancel)
            check("cancelar lanza DownloadCancelled", False)
        except sa.DownloadCancelled:
            check("cancelar lanza DownloadCancelled", True)
        check("cancelado → sin paquete", not sa.gpu_pack_installed() and not pack_dir.exists())

        print("\n── 5. Servidor sin rangos → descarga completa + sha256 ──")
        _Store.ranges = False
        logs = []
        sa.install_gpu_pack(on_log=logs.append)
        check("instalado vía descarga completa", sa.gpu_pack_installed() and any("descarga completa" in m for m in logs))
        check("contenido íntegro (completa)", (pack_dir / "cublas/bin/cublas64_12.dll").read_bytes() == big)
        sa.remove_gpu_pack()
        # sha256 incorrecto → error
        bad_wheels = tuple(dict(w, sha256="0" * 64) for w in fake_wheels)
        config.NVIDIA_WHEELS = bad_wheels
        sa.pypi_wheel_url = lambda name, version, expected=None: (base + name + ".whl", len(_Store.files[name + ".whl"]), "0" * 64)
        try:
            sa.install_gpu_pack()
            check("sha256 malo → error", False)
        except sa.DownloadError:
            check("sha256 malo → error", not pack_dir.exists())
        _Store.ranges = True
    finally:
        config.GPU_PACK_DIR, config.GPU_PACK_MANIFEST, config.NVIDIA_WHEELS, sa.pypi_wheel_url = orig
        shutil.rmtree(tmpd, ignore_errors=True)
        srv.shutdown()

    print("\n── 6. Modelo y utilidades ──")
    check("modelo inexistente → no cacheado", not sa.model_is_cached("modelo-que-no-existe"))
    check("repo id de turbo", sa.model_repo_id("large-v3-turbo").endswith("faster-whisper-large-v3-turbo"))
    check("tamaño estimado turbo", sa.model_download_mb("large-v3-turbo") == 1600)
    fp = sa.format_progress(512_000_000, 1_200_000_000, 60.0)
    check("format_progress", fp.startswith("42 %") and "MB/s" in fp and "restantes" in fp, fp)
    check("format_progress sin total", "MB" in sa.format_progress(5_000_000, 0, 0.1))
    gpu = sa.detect_nvidia_gpu()
    print(f"     detect_nvidia_gpu() → {gpu}")
    check("detect_nvidia_gpu devuelve dict o None", gpu is None or ("name" in gpu and "vram_mb" in gpu))

    if red:
        print("\n── 7. Red real: wheel más pequeño de PyPI ──")
        w = config.NVIDIA_WHEELS[0]
        url, size, sha = sa.pypi_wheel_url(w["name"], w["version"], w["sha256"])
        rz = sa.RemoteZip(url, size)
        ents = [e for e in rz.entries() if sa.wanted_dll(e["name"])]
        check("PyPI: cudart64_12.dll en el wheel", any(e["name"].endswith("cudart64_12.dll") for e in ents), str([e["name"] for e in ents]))
        tmpd = Path(tempfile.mkdtemp(prefix="wisip_sa_"))
        try:
            e = ents[0]
            rz.extract(e, tmpd / "x.dll", total=e["csize"])
            check("PyPI: extracción por rangos OK", (tmpd / "x.dll").stat().st_size == e["usize"] > 100_000)
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de setup_assets pasaron.")


if __name__ == "__main__":
    main()
