@echo off
REM Construye el instalador de Wisip con Inno Setup.
REM Auto-detecta ISCC.exe (Inno Setup no agrega su ruta al PATH por defecto).
REM
REM Requiere que EXE\Wisip\Wisip.exe exista (corre EXE\build.bat antes).
REM Salida: EXE\installer\Wisip-Setup-1.0.0.exe

setlocal EnableExtensions

set "EXE_DIR=%~dp0"
set "EXE_DIR_NS=%EXE_DIR:~0,-1%"

REM Permite override por variable de entorno.
if defined ISCC_EXE goto :check_iscc

REM Busca en ubicaciones estándar de Inno Setup 6 y 5.
REM OJO: NO usar un for (...) con estas rutas: al expandir %ProgramFiles(x86)%
REM el ")" de "(x86)" cierra la lista del for y el parser de cmd se rompe
REM ("do" no se reconoce...). Con if exist secuenciales no hay problema.
set "ISCC_EXE="
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 5\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 5\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"

REM Si no apareció, intenta el PATH.
if not defined ISCC_EXE (
    where iscc >nul 2>&1
    if not errorlevel 1 set "ISCC_EXE=iscc"
)

:check_iscc
if not defined ISCC_EXE (
    echo [installer] No encuentro ISCC.exe.
    echo [installer] Instala Inno Setup 6 desde https://jrsoftware.org/isdl.php
    echo [installer] o setea la variable ISCC_EXE con la ruta completa.
    exit /b 1
)

if not exist "%EXE_DIR_NS%\Wisip\Wisip.exe" (
    echo [installer] No encuentro %EXE_DIR_NS%\Wisip\Wisip.exe
    echo [installer] Corre EXE\build.bat primero.
    exit /b 1
)

echo [installer] Usando: %ISCC_EXE%
echo [installer] Compilando installer.iss ...

"%ISCC_EXE%" "%EXE_DIR_NS%\installer.iss"

if errorlevel 1 (
    echo [installer] Inno Setup fallo
    exit /b 1
)

echo.
echo [installer] OK. Salida en: %EXE_DIR_NS%\installer\ (Wisip-Setup-{version}.exe)
endlocal
