"""Descargas de primer arranque, con progreso y cancelación.

Dos cosas se descargan desde la app (la 2.7.0 quitó 1,9 GB de DLLs CUDA del
instalador, que pasó de ~1 GB a ~70 MB):

1. **Paquete de aceleración NVIDIA**: las DLLs de cuBLAS/cuDNN/cudart/nvrtc
   que CTranslate2 necesita para usar la GPU. Se sacan de los wheels oficiales
   de NVIDIA en PyPI (`config.NVIDIA_WHEELS`) leyendo SOLO los miembros
   `nvidia/<lib>/bin/*.dll` del zip por rangos HTTP (no se baja el wheel
   entero: se lee la tabla central al final del archivo y luego cada DLL).
   Si el servidor no soporta rangos, se baja el wheel completo, se verifica
   el sha256 publicado y se extrae con zipfile. Destino: `config.GPU_PACK_DIR`
   (`%LOCALAPPDATA%\\Wisip\\cuda\\<lib>\\bin\\*.dll`) + `pack.json`.

2. **Modelo Whisper**: mismo `snapshot_download` que usa faster-whisper, pero
   con una clase tqdm propia que reporta bytes al callback de progreso.

Ninguna función aquí toca la UI: reciben `progress(done, total, label)` y un
`threading.Event` de cancelación. `app/setup_window.py` pinta el progreso y
`main.py` orquesta el orden (paquete → modelo → carga).
"""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

from . import config

_UA = "Wisip/2.7 (+https://github.com/acropolifamily-web/wisip)"
_CHUNK = 1 << 20  # 1 MB por lectura
_TIMEOUT = 60
_RETRIES = 3
_CREATE_NO_WINDOW = 0x08000000


class DownloadCancelled(Exception):
    """El usuario canceló (evento de cancelación activado)."""


class DownloadError(Exception):
    """Fallo de red, de verificación o de formato."""


class _NoRangeSupport(Exception):
    """El servidor ignoró la cabecera Range (devolvió 200 en vez de 206)."""


def _noop_progress(done: int, total: int, label: str):
    return None


def _check_cancel(cancel: "threading.Event | None"):
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled()


# ─── GPU NVIDIA ─────────────────────────────────────────────────────────

def detect_nvidia_gpu() -> dict | None:
    """{'name', 'vram_mb'} de la primera GPU NVIDIA, o None si no hay driver
    (nvidia-smi viene con el driver, en System32). No necesita CUDA."""
    if sys.platform != "win32":
        return None
    exe = shutil.which("nvidia-smi")
    if not exe:
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    if not os.path.exists(exe):
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, creationflags=_CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return None
    line = (out or "").strip().splitlines()
    if not line:
        return None
    name, _, mem = line[0].partition(",")
    try:
        vram = int(float(mem.strip()))
    except ValueError:
        vram = 0
    name = name.strip()
    if not name:
        return None
    return {"name": name, "vram_mb": vram}


# ─── Estado del paquete ─────────────────────────────────────────────────

def _read_manifest() -> dict | None:
    try:
        with open(config.GPU_PACK_MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def gpu_pack_installed() -> bool:
    """True si el manifiesto es de la versión actual y todos los archivos
    existen con el tamaño esperado."""
    m = _read_manifest()
    if not m or m.get("version") != config.GPU_PACK_VERSION:
        return False
    files = m.get("files") or []
    if not files:
        return False
    for entry in files:
        p = config.GPU_PACK_DIR / entry.get("path", "")
        try:
            if p.stat().st_size != int(entry.get("size", -1)):
                return False
        except OSError:
            return False
    return True


def gpu_pack_size_bytes() -> int:
    m = _read_manifest() or {}
    return sum(int(e.get("size", 0)) for e in (m.get("files") or []))


def remove_gpu_pack():
    shutil.rmtree(config.GPU_PACK_DIR, ignore_errors=True)


def wanted_dll(member_name: str) -> tuple[str, str] | None:
    """(lib, archivo) si el miembro del wheel es una DLL que queremos:
    `nvidia/<lib>/bin/<x>.dll` y no está en la lista de exclusión."""
    m = re.fullmatch(r"nvidia/([^/]+)/bin/([^/]+\.dll)", member_name.replace("\\", "/"))
    if not m:
        return None
    lib, fname = m.group(1), m.group(2)
    low = fname.lower()
    if any(x.lower() in low for x in config.GPU_PACK_EXCLUDE_DLLS):
        return None
    return lib, fname


# ─── HTTP ───────────────────────────────────────────────────────────────

def _request(url: str, headers: dict | None = None, timeout: float = _TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def pypi_wheel_url(name: str, version: str, expected_sha256: str | None = None) -> tuple[str, int, str]:
    """(url, size, sha256) del wheel win_amd64 publicado en PyPI. Si se pasa
    `expected_sha256`, debe coincidir con el publicado (la versión está
    fijada en config y no se acepta otra)."""
    api = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with _request(api, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        raise DownloadError(f"PyPI no responde para {name} {version}: {e}") from e
    for f in data.get("urls", []):
        if f.get("packagetype") == "bdist_wheel" and "win_amd64" in f.get("filename", ""):
            sha = (f.get("digests") or {}).get("sha256", "")
            if expected_sha256 and sha.lower() != expected_sha256.lower():
                raise DownloadError(f"sha256 inesperado para {f['filename']}")
            return f["url"], int(f.get("size", 0)), sha
    raise DownloadError(f"PyPI no tiene wheel win_amd64 para {name} {version}")


class RemoteZip:
    """Lectura por rangos de un zip remoto (wheel). Solo lee la tabla central
    y los miembros pedidos."""

    def __init__(self, url: str, size: int | None = None):
        self.url = url
        self.size = size or self._head_size()

    def _head_size(self) -> int:
        req = urllib.request.Request(self.url, method="HEAD", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            n = r.headers.get("Content-Length")
        if not n:
            raise DownloadError("el servidor no informa el tamaño del archivo")
        return int(n)

    def _range(self, start: int, end: int):
        """Respuesta streaming para bytes [start, end] inclusive. 206 o error."""
        resp = _request(self.url, {"Range": f"bytes={start}-{end}"})
        if resp.status != 206:
            resp.close()
            raise _NoRangeSupport()
        return resp

    def _read_range(self, start: int, end: int) -> bytes:
        with self._range(start, end) as r:
            return r.read()

    def entries(self) -> list[dict]:
        """Tabla central: [{name, method, crc, csize, usize, header_offset}]."""
        tail_len = min(self.size, 66 * 1024)
        tail = self._read_range(self.size - tail_len, self.size - 1)
        eocd = tail.rfind(b"PK\x05\x06")
        if eocd < 0:
            raise DownloadError("zip sin registro EOCD")
        cd_size, cd_off = struct.unpack_from("<II", tail, eocd + 12)
        if cd_size == 0xFFFFFFFF or cd_off == 0xFFFFFFFF:
            loc = tail.rfind(b"PK\x06\x07", 0, eocd)
            if loc < 0:
                raise DownloadError("zip64 sin localizador")
            (eocd64_off,) = struct.unpack_from("<Q", tail, loc + 8)
            rel = eocd64_off - (self.size - tail_len)
            rec = tail[rel:rel + 56] if rel >= 0 else self._read_range(eocd64_off, eocd64_off + 55)
            if rec[:4] != b"PK\x06\x06":
                raise DownloadError("zip64: registro EOCD64 inválido")
            cd_size, cd_off = struct.unpack_from("<QQ", rec, 40)
        cd = self._read_range(cd_off, cd_off + cd_size - 1)
        out = []
        pos = 0
        while pos + 46 <= len(cd):
            if cd[pos:pos + 4] != b"PK\x01\x02":
                break
            (method, crc, csize, usize, nlen, xlen, clen, lho) = (
                struct.unpack_from("<H", cd, pos + 10)[0],
                *struct.unpack_from("<III", cd, pos + 16),
                *struct.unpack_from("<HHH", cd, pos + 28),
                struct.unpack_from("<I", cd, pos + 42)[0],
            )
            name = cd[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
            extra = cd[pos + 46 + nlen:pos + 46 + nlen + xlen]
            if 0xFFFFFFFF in (csize, usize, lho):
                usize, csize, lho = _zip64_extra(extra, usize, csize, lho)
            out.append({"name": name, "method": method, "crc": crc,
                        "csize": csize, "usize": usize, "header_offset": lho})
            pos += 46 + nlen + xlen + clen
        return out

    def extract(self, entry: dict, dest: Path, progress=_noop_progress,
                cancel=None, base_done: int = 0, total: int = 0, label: str = ""):
        """Descarga y descomprime un miembro a `dest` (archivo temporal + rename).
        Verifica CRC32 y tamaño. `progress` recibe base_done + bytes leídos."""
        lho = entry["header_offset"]
        lh = self._read_range(lho, lho + 29)
        if lh[:4] != b"PK\x03\x04":
            raise DownloadError(f"cabecera local inválida en {entry['name']}")
        nlen, xlen = struct.unpack_from("<HH", lh, 26)
        start = lho + 30 + nlen + xlen
        end = start + entry["csize"] - 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        last_err: Exception | None = None
        for attempt in range(_RETRIES):
            _check_cancel(cancel)
            try:
                self._extract_once(entry, start, end, tmp, progress, cancel, base_done, total, label)
                os.replace(tmp, dest)
                return
            except (DownloadCancelled, _NoRangeSupport):
                raise
            except Exception as e:  # red, CRC, disco…
                last_err = e
                try:
                    tmp.unlink()
                except OSError:
                    pass
                time.sleep(1.5 * (attempt + 1))
        raise DownloadError(f"{entry['name']}: {last_err}")

    def _extract_once(self, entry, start, end, tmp, progress, cancel, base_done, total, label):
        method = entry["method"]
        if method not in (0, 8):
            raise DownloadError(f"método de compresión no soportado ({method}) en {entry['name']}")
        dec = zlib.decompressobj(-15) if method == 8 else None
        crc = 0
        written = 0
        read = 0
        with self._range(start, end) as r, open(tmp, "wb") as f:
            while True:
                _check_cancel(cancel)
                chunk = r.read(_CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                data = dec.decompress(chunk) if dec else chunk
                if data:
                    f.write(data)
                    crc = zlib.crc32(data, crc)
                    written += len(data)
                progress(base_done + read, total, label)
            if dec:
                data = dec.flush()
                if data:
                    f.write(data)
                    crc = zlib.crc32(data, crc)
                    written += len(data)
        if read != entry["csize"]:
            raise DownloadError(f"{entry['name']}: descarga incompleta ({read}/{entry['csize']})")
        if written != entry["usize"] or (crc & 0xFFFFFFFF) != entry["crc"]:
            raise DownloadError(f"{entry['name']}: CRC/tamaño no coinciden")


def _zip64_extra(extra: bytes, usize: int, csize: int, lho: int) -> tuple[int, int, int]:
    pos = 0
    while pos + 4 <= len(extra):
        tag, ln = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4:pos + 4 + ln]
        if tag == 0x0001:
            off = 0
            if usize == 0xFFFFFFFF and off + 8 <= len(body):
                usize = struct.unpack_from("<Q", body, off)[0]; off += 8
            if csize == 0xFFFFFFFF and off + 8 <= len(body):
                csize = struct.unpack_from("<Q", body, off)[0]; off += 8
            if lho == 0xFFFFFFFF and off + 8 <= len(body):
                lho = struct.unpack_from("<Q", body, off)[0]; off += 8
            break
        pos += 4 + ln
    return usize, csize, lho


def download_file(url: str, dest: Path, size: int, progress=_noop_progress,
                  cancel=None, sha256: str | None = None,
                  base_done: int = 0, total: int = 0, label: str = ""):
    """Descarga completa a `dest` (vía .part) con progreso y sha256 opcional."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err = None
    for attempt in range(_RETRIES):
        _check_cancel(cancel)
        h = hashlib.sha256()
        read = 0
        try:
            with _request(url) as r, open(tmp, "wb") as f:
                while True:
                    _check_cancel(cancel)
                    chunk = r.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    read += len(chunk)
                    progress(base_done + read, total or size, label)
            if size and read != size:
                raise DownloadError(f"descarga incompleta ({read}/{size})")
            if sha256 and h.hexdigest().lower() != sha256.lower():
                raise DownloadError("sha256 no coincide")
            os.replace(tmp, dest)
            return
        except DownloadCancelled:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise DownloadError(f"{url.rsplit('/', 1)[-1]}: {last_err}")


# ─── Instalación del paquete NVIDIA ─────────────────────────────────────

def install_gpu_pack(progress=_noop_progress, cancel: "threading.Event | None" = None,
                     on_log=None) -> Path:
    """Descarga las DLLs a una carpeta temporal hermana, escribe pack.json y
    la renombra a `config.GPU_PACK_DIR`. Devuelve la ruta final.

    Lanza DownloadCancelled o DownloadError. Si falla, no deja un paquete a
    medias: la carpeta final solo existe cuando todo se verificó.
    """
    log = on_log or (lambda m: None)
    final = Path(config.GPU_PACK_DIR)
    staging = final.with_name(final.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    # 1) Plan: resolver URLs y leer tablas centrales (4 peticiones pequeñas).
    plan = []
    total = 0
    for w in config.NVIDIA_WHEELS:
        _check_cancel(cancel)
        progress(0, 0, f"Consultando {w['name']}…")
        url, size, sha = pypi_wheel_url(w["name"], w["version"], w.get("sha256"))
        rz = RemoteZip(url, size)
        try:
            entries = [e for e in rz.entries() if wanted_dll(e["name"])]
            if not entries:
                raise DownloadError(f"{w['name']}: el wheel no trae DLLs en nvidia/*/bin")
            plan.append({"wheel": w, "url": url, "size": size, "sha": sha,
                         "mode": "range", "rz": rz, "entries": entries})
            total += sum(e["csize"] for e in entries)
            log(f"[gpu-pack] {w['name']} {w['version']}: {len(entries)} DLLs por rangos "
                f"({sum(e['csize'] for e in entries) / 1e6:.0f} MB)")
        except _NoRangeSupport:
            plan.append({"wheel": w, "url": url, "size": size, "sha": sha,
                         "mode": "full", "rz": None, "entries": None})
            total += size
            log(f"[gpu-pack] {w['name']}: sin soporte de rangos, descarga completa ({size / 1e6:.0f} MB)")

    # 2) Descarga.
    done = 0
    files = []
    for item in plan:
        w = item["wheel"]
        if item["mode"] == "range":
            for e in item["entries"]:
                lib, fname = wanted_dll(e["name"])
                dest = staging / lib / "bin" / fname
                try:
                    item["rz"].extract(e, dest, progress, cancel, done, total, f"{lib}: {fname}")
                except _NoRangeSupport:
                    # El servidor dejó de aceptar rangos a mitad: pasar a completo.
                    log(f"[gpu-pack] {w['name']}: rangos rechazados, descarga completa")
                    total += item["size"]
                    _install_from_full_wheel(item, staging, progress, cancel, done, total)
                    done += item["size"]
                    break
                done += e["csize"]
                files.append({"path": f"{lib}/bin/{fname}", "size": e["usize"], "crc": e["crc"]})
            else:
                continue
            # (llegó aquí por el break del fallback) → registra los archivos extraídos
            files = _collect_files(staging)
        else:
            _install_from_full_wheel(item, staging, progress, cancel, done, total)
            done += item["size"]
            files = _collect_files(staging)

    if not files:
        files = _collect_files(staging)
    if not any(f["path"].lower().endswith("cublas64_12.dll") for f in files):
        raise DownloadError("el paquete no contiene cublas64_12.dll")

    manifest = {
        "version": config.GPU_PACK_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wheels": [{"name": w["name"], "version": w["version"]} for w in config.NVIDIA_WHEELS],
        "files": files,
    }
    with open(staging / "pack.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 3) Publicar: el paquete final solo existe completo.
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staging, final)
    progress(total, total, "Paquete NVIDIA listo")
    log(f"[gpu-pack] instalado en {final} ({len(files)} DLLs, "
        f"{sum(f['size'] for f in files) / 1e9:.2f} GB)")
    return final


def _install_from_full_wheel(item, staging: Path, progress, cancel, done, total):
    w = item["wheel"]
    tmpdir = Path(tempfile.mkdtemp(prefix="wisip_whl_"))
    try:
        whl = tmpdir / (w["name"] + ".whl")
        download_file(item["url"], whl, item["size"], progress, cancel,
                      sha256=w.get("sha256") or item["sha"],
                      base_done=done, total=total, label=w["name"])
        with zipfile.ZipFile(whl) as zf:
            for info in zf.infolist():
                sel = wanted_dll(info.filename)
                if not sel:
                    continue
                lib, fname = sel
                dest = staging / lib / "bin" / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, _CHUNK)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _collect_files(staging: Path) -> list[dict]:
    out = []
    for p in sorted(staging.glob("*/bin/*.dll")):
        with open(p, "rb") as f:
            crc = 0
            while True:
                b = f.read(_CHUNK)
                if not b:
                    break
                crc = zlib.crc32(b, crc)
        out.append({"path": p.relative_to(staging).as_posix(), "size": p.stat().st_size,
                    "crc": crc & 0xFFFFFFFF})
    return out


# ─── Modelo Whisper ─────────────────────────────────────────────────────

_ALLOW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin",
                   "tokenizer.json", "vocabulary.*"]


def model_repo_id(model_name: str) -> str:
    if re.match(r".*/.*", model_name):
        return model_name
    from faster_whisper.utils import _MODELS
    repo = _MODELS.get(model_name)
    if repo is None:
        raise ValueError(f"modelo desconocido: {model_name}")
    return repo


def model_is_cached(model_name: str) -> bool:
    """True si el modelo ya está completo en la caché de Hugging Face
    (sin tocar la red)."""
    try:
        from faster_whisper.utils import download_model
        download_model(model_name, local_files_only=True)
        return True
    except Exception:
        return False


def model_download_mb(model_name: str) -> int:
    return int(config.MODEL_DOWNLOAD_MB.get(model_name, 0))


def download_model(model_name: str, progress=_noop_progress,
                   cancel: "threading.Event | None" = None) -> str:
    """Descarga el modelo a la caché de HF reportando bytes. Devuelve la ruta."""
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm as _tqdm

    repo = model_repo_id(model_name)
    est_total = model_download_mb(model_name) * 1_000_000
    bars: dict[int, list] = {}  # id(bar) -> [n, total]
    lock = threading.Lock()

    def _report():
        with lock:
            done = sum(v[0] for v in bars.values())
            total = sum(v[1] for v in bars.values())
        progress(done, max(total, est_total, 1), f"Modelo {model_name}")

    class _Bar(_tqdm):
        def __init__(self, *a, **k):
            k["disable"] = True
            super().__init__(*a, **k)
            desc = str(k.get("desc") or "")
            self._wisip_bytes = not desc.lower().startswith("fetching")
            if self._wisip_bytes:
                with lock:
                    bars[id(self)] = [0, int(k.get("total") or 0)]

        def update(self, n=1):
            _check_cancel(cancel)
            if self._wisip_bytes:
                with lock:
                    rec = bars.setdefault(id(self), [0, 0])
                    rec[0] += int(n or 0)
                    rec[1] = int(self.total or rec[1] or 0)
                _report()
            return super().update(n)

    try:
        path = snapshot_download(repo, allow_patterns=_ALLOW_PATTERNS, tqdm_class=_Bar)
    except DownloadCancelled:
        raise
    except Exception as e:
        # huggingface_hub envuelve las excepciones de los hilos de descarga.
        if "DownloadCancelled" in type(e).__name__ or (cancel is not None and cancel.is_set()):
            raise DownloadCancelled() from None
        raise DownloadError(f"no se pudo descargar el modelo '{model_name}': {e}") from e
    progress(max(est_total, 1), max(est_total, 1), f"Modelo {model_name} listo")
    return path


# ─── Utilidades de presentación ─────────────────────────────────────────

def format_progress(done: int, total: int, elapsed_s: float) -> str:
    """'42 % · 512 / 1.200 MB · 8,3 MB/s · 1 min 20 s restantes'."""
    parts = []
    if total > 0:
        pct = min(100, int(done * 100 / total))
        parts.append(f"{pct} %")
        parts.append(f"{done / 1e6:,.0f} / {total / 1e6:,.0f} MB".replace(",", "."))
    else:
        parts.append(f"{done / 1e6:,.0f} MB".replace(",", "."))
    if elapsed_s > 0.5 and done > 0:
        speed = done / elapsed_s
        parts.append(f"{speed / 1e6:.1f} MB/s".replace(".", ","))
        if total > done and speed > 0:
            rem = (total - done) / speed
            if rem >= 60:
                parts.append(f"{int(rem // 60)} min {int(rem % 60)} s restantes")
            else:
                parts.append(f"{int(rem)} s restantes")
    return " · ".join(parts)
