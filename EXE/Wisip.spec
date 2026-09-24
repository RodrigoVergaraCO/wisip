# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para Wisip (--onedir, --windowed, SIN --uac-admin).

Se invoca desde EXE/build.bat. Salida: EXE/Wisip/Wisip.exe.

NOTA: `uac_admin=False`. Wisip corre en MODO USUARIO. El hook global de
`keyboard` y el pegado (Ctrl+V) funcionan sin administrador contra apps
normales (Chrome, ChatGPT, VS Code, etc.). Solo se requiere administrador
para controlar ventanas que a su vez corran elevadas (limitación de Windows
por UIPI). Forzar admin aquí hacía que la app pidiera UAC en cada arranque.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent

# Recursos a empacar junto al .exe.
DATAS = [
    (str(PROJECT_ROOT / "assets" / "icon.ico"), "assets"),
    (str(PROJECT_ROOT / "icon.png"), "."),
    (str(PROJECT_ROOT / "logo.png"), "."),
]

# faster-whisper + ctranslate2 traen .dll / .py / archivos de tokenizadores.
fw_datas, fw_binaries, fw_hidden = collect_all("faster_whisper")
ct2_datas, ct2_binaries, ct2_hidden = collect_all("ctranslate2")
ck_datas = collect_data_files("customtkinter")
# sentencepiece: tokenizador de los modelos de traducción (app/translator.py
# lo importa perezosamente, así que PyInstaller no lo ve solo).
sp_datas, sp_binaries, sp_hidden = collect_all("sentencepiece")

# wordfreq (pestaña Vocabulario: filtra palabras reales al minar sugerencias).
# Sus datos traen 66 idiomas (~60 MB); solo empacamos español e inglés (~3.4 MB).
# app/vocab.py solo consulta 'es'/'en' y degrada con gracia si faltara el resto.
wfq_datas, wfq_binaries, wfq_hidden = collect_all("wordfreq")
wfq_datas = [
    (src, dest) for (src, dest) in wfq_datas
    if not src.endswith(".msgpack.gz")
    or Path(src).name.split(".")[0].endswith(("_es", "_en"))
]

DATAS += fw_datas + ct2_datas + ck_datas + wfq_datas + sp_datas
BINARIES = fw_binaries + ct2_binaries + wfq_binaries + sp_binaries

# ─── DLLs CUDA (build GPU) ──────────────────────────────────────────────
# Si el venv tiene los paquetes pip nvidia-* (cublas/cudnn/nvrtc/runtime), se
# empaquetan en _internal/nvidia/<lib>/bin y la app usará la GPU NVIDIA
# (app/config.py añade esa ruta al buscador de DLLs vía sys._MEIPASS).
# Si NO están instalados, el glob no encuentra nada y sale el build CPU
# universal de siempre — el mismo spec sirve para ambos.
# Ojo: añaden ~1.9GB sin comprimir (cublas 736MB + cudnn 1GB + nvrtc 178MB).
import glob as _glob
import sysconfig as _sysconfig

NVIDIA_DATAS = []
_nv_root = Path(_sysconfig.get_paths()["purelib"]) / "nvidia"
# 2.7.0: por defecto NO se empaquetan (la app descarga el paquete NVIDIA a
# %LOCALAPPDATA%\Wisip\cuda cuando detecta una GPU). WISIP_BUNDLE_CUDA=1
# recupera el build "todo incluido" de 2,2 GB.
import os as _os
_bundle_cuda = _os.environ.get("WISIP_BUNDLE_CUDA") == "1"
for _bin in (_glob.glob(str(_nv_root / "*" / "bin")) if _bundle_cuda else []):
    _bin_path = Path(_bin)
    _dest = str(Path("nvidia") / _bin_path.parent.name / "bin")
    for _f in _bin_path.iterdir():
        if _f.is_file():
            NVIDIA_DATAS.append((str(_f), _dest))
if NVIDIA_DATAS:
    print(f"[Wisip.spec] build GPU: empaquetando {len(NVIDIA_DATAS)} archivos CUDA")
else:
    print("[Wisip.spec] build liviano: sin DLLs CUDA (la app las descarga si hay GPU NVIDIA)")
DATAS += NVIDIA_DATAS

HIDDEN = list(set(
    fw_hidden + ct2_hidden + wfq_hidden + sp_hidden + [
        "keyboard",
        "pystray._win32",
        "PIL._tkinter_finder",
    ]
))


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=BINARIES,
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Wisip",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    icon=str(PROJECT_ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Wisip",
)
