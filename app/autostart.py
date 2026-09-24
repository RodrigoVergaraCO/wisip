"""Inicio automático con Windows (sin admin).

Registra/borra un valor en HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.
Se elige HKCU Run (no HKLM, no carpeta Startup) porque:

- HKCU es escribible por el usuario → NO requiere administrador.
- Es un único valor de registro: fácil de crear, leer, borrar y verificar.
- No necesita crear accesos directos .lnk (que requerirían COM/pywin32).

El comando guardado apunta al ejecutable real:
- Empaquetado con PyInstaller (`sys.frozen`): el propio `Wisip.exe`.
- En desarrollo (`python main.py`): `pythonw.exe` + ruta a `main.py`.

El arranque minimizado NO se pasa por argumento: la app ya respeta
`start_minimized` desde app_settings.json al iniciar.
"""

import sys
import winreg
from pathlib import Path

from . import config


def get_app_executable_path() -> str:
    """Devuelve el comando completo (ya entrecomillado) para relanzar la app.

    Maneja espacios en rutas entrecomillando cada componente. En modo
    empaquetado devuelve solo el .exe; en desarrollo devuelve el intérprete
    (pythonw para no abrir consola) seguido de main.py.
    """
    if getattr(sys, "frozen", False):
        # Empaquetado: sys.executable es el propio Wisip.exe.
        return f'"{Path(sys.executable).resolve()}"'

    # Desarrollo: usa pythonw.exe (sin consola) si existe, si no python.exe.
    py = Path(sys.executable).resolve()
    pyw = py.with_name("pythonw.exe")
    interpreter = pyw if pyw.exists() else py
    main_py = (Path(__file__).resolve().parent.parent / "main.py")
    return f'"{interpreter}" "{main_py}"'


def is_enabled() -> bool:
    """True si existe el valor de autostart en HKCU Run."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.AUTOSTART_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, config.AUTOSTART_VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def current_command() -> str | None:
    """Devuelve el comando actualmente registrado, o None si no hay."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, config.AUTOSTART_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, config.AUTOSTART_VALUE_NAME)
            return value
    except OSError:
        return None


def enable(on_log=None) -> bool:
    """Crea/actualiza el valor de autostart. Devuelve True si quedó registrado."""
    log = on_log or (lambda m: None)
    cmd = get_app_executable_path()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, config.AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, config.AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        log(f"[autostart] activado · ruta: {cmd}")
        if not getattr(sys, "frozen", False):
            log("[autostart] NOTA: estás en modo desarrollo. El autostart se "
                "recomienda con el .exe empaquetado (la ruta del venv puede cambiar).")
        return True
    except OSError as e:
        log(f"[autostart] error activando: {e}")
        return False


def disable(on_log=None) -> bool:
    """Borra el valor de autostart. Devuelve True si quedó desactivado
    (incluido el caso en que ya no existía)."""
    log = on_log or (lambda m: None)
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, config.AUTOSTART_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, config.AUTOSTART_VALUE_NAME)
        log("[autostart] desactivado (entrada borrada de HKCU\\...\\Run)")
        return True
    except FileNotFoundError:
        log("[autostart] desactivado (no había entrada que borrar)")
        return True
    except OSError as e:
        log(f"[autostart] error desactivando: {e}")
        return False
