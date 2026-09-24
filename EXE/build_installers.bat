@echo off
REM Compila los instaladores de las variantes disponibles:
REM   EXE\Wisip\           -> Wisip-Setup-{version}-GPU.exe  (NVIDIA, con CUDA)
REM   EXE\dist-cpu\Wisip\  -> Wisip-Setup-{version}-CPU.exe  (universal)
REM Requiere Inno Setup 6 (auto-detectado igual que build_installer.bat).

setlocal EnableExtensions

set "EXE_DIR=%~dp0"
set "EXE_DIR_NS=%EXE_DIR:~0,-1%"

if defined ISCC_EXE goto :have_iscc
set "ISCC_EXE="
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE (
    where iscc >nul 2>&1
    if not errorlevel 1 set "ISCC_EXE=iscc"
)
:have_iscc
if not defined ISCC_EXE (
    echo [installers] No encuentro ISCC.exe. Instala Inno Setup 6.
    exit /b 1
)

set "BUILT=0"

if exist "%EXE_DIR_NS%\Wisip\Wisip.exe" (
    echo [installers] Compilando variante GPU...
    "%ISCC_EXE%" /DVariant=GPU "%EXE_DIR_NS%\installer.iss"
    if errorlevel 1 exit /b 1
    set "BUILT=1"
) else (
    echo [installers] Aviso: no hay build GPU en EXE\Wisip\ - saltada.
)

if exist "%EXE_DIR_NS%\dist-cpu\Wisip\Wisip.exe" (
    echo [installers] Compilando variante CPU...
    "%ISCC_EXE%" /DVariant=CPU /DSourceDir=dist-cpu\Wisip "%EXE_DIR_NS%\installer.iss"
    if errorlevel 1 exit /b 1
    set "BUILT=1"
) else (
    echo [installers] Aviso: no hay build CPU en EXE\dist-cpu\ - saltada.
)

if "%BUILT%"=="0" (
    echo [installers] Nada que compilar. Corre EXE\build.bat y/o EXE\build_cpu.bat.
    exit /b 1
)

echo.
echo [installers] OK. Salida en: %EXE_DIR_NS%\installer\
endlocal
