@echo off
REM Construye la variante CPU UNIVERSAL de Wisip (sin DLLs CUDA, ~700 MB menos).
REM Usa un venv aparte (.venv-cpu) SIN los paquetes nvidia-*: Wisip.spec decide
REM GPU/CPU segun lo que haya en el venv que ejecuta PyInstaller.
REM Salida: EXE\dist-cpu\Wisip\Wisip.exe
REM
REM Uso desde la raiz del proyecto:
REM     EXE\build_cpu.bat

setlocal EnableExtensions

set "EXE_DIR=%~dp0"
set "EXE_DIR_NS=%EXE_DIR:~0,-1%"
set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%"

if not exist ".venv-cpu\Scripts\python.exe" (
    echo [build-cpu] Creando venv CPU limpio en .venv-cpu ...
    py -3.11 -m venv .venv-cpu 2>nul
    if not exist ".venv-cpu\Scripts\python.exe" python -m venv .venv-cpu
    if not exist ".venv-cpu\Scripts\python.exe" (
        echo [build-cpu] No pude crear .venv-cpu. Instala Python 3.11.
        popd
        exit /b 1
    )
)

call ".venv-cpu\Scripts\activate.bat"

echo [build-cpu] Instalando dependencias (SIN nvidia-*)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.0.0"

echo [build-cpu] Generando assets\icon.ico ...
python "%EXE_DIR%make_ico.py"
if errorlevel 1 (
    echo [build-cpu] Error generando icon.ico
    popd
    exit /b 1
)

echo [build-cpu] Limpiando builds CPU previos...
if exist "%EXE_DIR_NS%\build-cpu" rmdir /s /q "%EXE_DIR_NS%\build-cpu"
if exist "%EXE_DIR_NS%\dist-cpu" rmdir /s /q "%EXE_DIR_NS%\dist-cpu"

echo [build-cpu] Compilando con PyInstaller (variante CPU)...
pyinstaller ^
    --noconfirm ^
    --clean ^
    --distpath "%EXE_DIR_NS%\dist-cpu" ^
    --workpath "%EXE_DIR_NS%\build-cpu" ^
    "%EXE_DIR_NS%\Wisip.spec"

if errorlevel 1 (
    echo [build-cpu] PyInstaller fallo
    popd
    exit /b 1
)

if not exist "%EXE_DIR_NS%\dist-cpu\Wisip\Wisip.exe" (
    echo [build-cpu] No encuentro %EXE_DIR_NS%\dist-cpu\Wisip\Wisip.exe
    popd
    exit /b 1
)

REM Verificacion anti-error: la variante CPU NO debe llevar DLLs CUDA.
if exist "%EXE_DIR_NS%\dist-cpu\Wisip\_internal\nvidia" (
    echo [build-cpu] ERROR: el build CPU contiene DLLs CUDA. El venv .venv-cpu
    echo             tiene paquetes nvidia-* instalados. Borralo y reintenta.
    popd
    exit /b 1
)

echo.
echo [build-cpu] OK. Ejecutable en: %EXE_DIR_NS%\dist-cpu\Wisip\Wisip.exe
echo [build-cpu] Instalador: EXE\build_installers.bat
popd
endlocal
