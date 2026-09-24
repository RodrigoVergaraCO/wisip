@echo off
REM Construye Wisip.exe con PyInstaller usando EXE/Wisip.spec.
REM Salida: EXE\Wisip\Wisip.exe (carpeta lista para distribuir).
REM
REM Uso desde la raíz del proyecto:
REM     EXE\build.bat

setlocal EnableExtensions

REM %~dp0 termina en "\". Para algunos args de pyinstaller eso confunde el
REM parser (\" se interpreta como escape de comilla). Guardamos también una
REM versión sin barra final.
set "EXE_DIR=%~dp0"
set "EXE_DIR_NS=%EXE_DIR:~0,-1%"
set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [build] No encuentro .venv\Scripts\python.exe
    echo [build] Crea el venv primero:
    echo         python -m venv .venv
    echo         .venv\Scripts\activate.bat
    echo         pip install -r requirements.txt
    popd
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo [build] Asegurando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install "pyinstaller>=6.0.0"

echo [build] Generando assets\icon.ico desde icon.png...
python "%EXE_DIR%make_ico.py"
if errorlevel 1 (
    echo [build] Error generando icon.ico
    popd
    exit /b 1
)

echo [build] Sincronizando version (app\version.py -> installer.iss)...
python "%EXE_DIR%sync_version.py"
if errorlevel 1 (
    echo [build] Error sincronizando la version
    popd
    exit /b 1
)

echo [build] Limpiando builds previos...
if exist "%EXE_DIR%build" rmdir /s /q "%EXE_DIR%build"
if exist "%EXE_DIR%Wisip" rmdir /s /q "%EXE_DIR%Wisip"

echo [build] Compilando con PyInstaller...
echo        distpath = %EXE_DIR_NS%
echo        workpath = %EXE_DIR_NS%\build
echo        spec     = %EXE_DIR_NS%\Wisip.spec

pyinstaller ^
    --noconfirm ^
    --clean ^
    --distpath "%EXE_DIR_NS%" ^
    --workpath "%EXE_DIR_NS%\build" ^
    "%EXE_DIR_NS%\Wisip.spec"

if errorlevel 1 (
    echo [build] PyInstaller fallo
    popd
    exit /b 1
)

if not exist "%EXE_DIR_NS%\Wisip\Wisip.exe" (
    echo [build] PyInstaller termino sin error pero no encuentro el .exe en
    echo         %EXE_DIR_NS%\Wisip\Wisip.exe
    echo [build] Revisa salida arriba.
    popd
    exit /b 1
)

echo.
echo [build] OK. Ejecutable en: %EXE_DIR_NS%\Wisip\Wisip.exe
echo [build] Para crear el instalador ejecuta:
echo         iscc "%EXE_DIR_NS%\installer.iss"
popd
endlocal
