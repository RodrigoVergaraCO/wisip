# Build de Wisip — pasos rápidos

Esta carpeta contiene todo el pipeline de empaquetado.

## Requisitos previos (una sola vez)

```powershell
cd local-voice-typer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
```

Para el instalador también necesitas **Inno Setup 6** instalado (instalador "Compiler IDE"): https://jrsoftware.org/isdl.php

Cuando lo instales, asegúrate de que `iscc.exe` quede en el `PATH` (el instalador suele agregarlo).

## Paso 1 — generar `assets/icon.ico` desde `icon.png`

```powershell
python EXE\make_ico.py
```

Idempotente: solo regenera si `icon.png` cambió. Produce `assets/icon.ico` con tamaños 16/24/32/48/64/128/256.

## Paso 2 — construir el `.exe`

```powershell
EXE\build.bat
```

Este script:

1. Activa el venv en `.\.venv\`.
2. Instala/actualiza dependencias.
3. Genera `assets/icon.ico` si hace falta.
4. Limpia builds previos.
5. Ejecuta PyInstaller con `EXE\Wisip.spec` (modo `--onedir`, `--windowed`, **sin** `--uac-admin` → la app corre en modo usuario, no pide UAC).

Resultado: `EXE\Wisip\Wisip.exe` con su carpeta `_internal/` al lado.

Para probar el `.exe` directamente sin instalar:

```powershell
.\EXE\Wisip\Wisip.exe
```

## Paso 3 — construir el instalador

Inno Setup **no agrega `iscc.exe` al PATH** al instalar. Tienes 3 opciones:

### Opción A (recomendada) — usar el wrapper

```powershell
EXE\build_installer.bat
```

Auto-detecta `ISCC.exe` en `Program Files (x86)\Inno Setup 6\` y `Program Files\Inno Setup 6\`. Si no aparece, te dice qué setear.

### Opción B — llamar `ISCC.exe` con ruta completa

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" EXE\installer.iss
```

### Opción C — agregar Inno Setup al PATH permanentemente

PowerShell como Administrador:

```powershell
$inno = "C:\Program Files (x86)\Inno Setup 6"
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $inno,
    "Machine"
)
```

Abre PowerShell **nuevo** y ya puedes correr:

```powershell
iscc EXE\installer.iss
```

Resultado de cualquiera de las 3 opciones: `EXE\installer\Wisip-Setup-1.0.0.exe`.

Distribuye **solo** ese archivo. Quien lo ejecute:

1. Verá el wizard de Inno Setup en español.
2. Aceptará UAC **una sola vez** (para que el instalador escriba en Program Files). La app en sí arranca en modo usuario, sin UAC.
3. La app se instala en `C:\Program Files\Wisip\`.
4. Aparece en el menú inicio como **Wisip** con la W lima.
5. Opcionalmente crea acceso directo en el escritorio (checkbox del wizard).
6. Queda registrada en "Programas y características" con su propio uninstaller.

## Estructura de la carpeta `EXE/`

```
EXE/
├── make_ico.py        # PNG → ICO multi-resolución
├── Wisip.spec         # spec de PyInstaller
├── build.bat          # orquesta el build
├── installer.iss      # script Inno Setup
├── README-build.md    # este archivo
└── (generados al construir)
    ├── build/         # caché de PyInstaller (puedes borrarla)
    ├── Wisip/         # app empacada (Wisip.exe + _internal/)
    └── installer/
        └── Wisip-Setup-1.0.0.exe
```

## Actualizar versión

Edita `MyAppVersion` en `installer.iss`. No es necesario cambiar el `AppId` (es el identificador único; mantenerlo permite que el uninstaller reconozca y reemplace la versión anterior).
