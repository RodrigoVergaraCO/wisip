import time

import keyboard as kb
import pyautogui
import pyperclip

from . import config

pyautogui.FAILSAFE = False


def clean_text(text: str) -> str:
    """Colapsa espacios y normaliza."""
    return " ".join(text.split()).strip()


def _wait_modifiers_released(timeout: float) -> bool:
    """Espera hasta `timeout` segundos a que ctrl/alt/win/shift físicos se suelten.
    Devuelve True si todos están sueltos al salir."""
    start = time.time()
    keys = ("ctrl", "alt", "windows", "shift")
    while time.time() - start < timeout:
        try:
            if not any(kb.is_pressed(k) for k in keys):
                return True
        except Exception:
            return True
        time.sleep(0.02)
    return False


def copy_only(text: str, on_log=None) -> bool:
    """Sólo copia al portapapeles. No pega."""
    log = on_log or (lambda m: None)
    text = clean_text(text)
    if not text:
        log("[typer] texto vacío, nada que copiar")
        return False
    try:
        pyperclip.copy(text)
        log(f"[typer] copiado al portapapeles ({len(text)} chars)")
        return True
    except Exception as e:
        log(f"[typer] error copiando al portapapeles: {e}")
        return False


def _send_ctrl_v(log) -> bool:
    """Envía Ctrl+V con fallback. Primero pyautogui; si falla, keyboard.
    Devuelve True si algún método no lanzó excepción."""
    try:
        pyautogui.hotkey("ctrl", "v")
        return True
    except Exception as e:
        log(f"[typer] pyautogui Ctrl+V falló ({e}); intento con keyboard…")
    try:
        kb.send("ctrl+v")
        return True
    except Exception as e:
        log(f"[typer] keyboard Ctrl+V también falló: {e}")
        return False


def paste_text(text: str, on_log=None, paste_delay_ms: int | None = None) -> bool:
    """Copia y simula Ctrl+V sobre la ventana activa.

    Flujo:
      1. Copia al portapapeles (pyperclip).
      2. Espera a que los modificadores físicos del hotkey (Ctrl/Win/Alt/Shift)
         se suelten, para no enviar Ctrl+V mientras siguen pulsados.
      3. Pausa configurable (`paste_delay_ms`, default en config).
      4. Envía Ctrl+V con fallback (pyautogui → keyboard).

    No requiere administrador para apps normales. Contra ventanas ejecutadas
    como administrador, Windows (UIPI) bloquea el envío de teclas.
    """
    log = on_log or (lambda m: None)
    text = clean_text(text)
    if not text:
        log("[typer] texto vacío, nada que pegar")
        return False

    try:
        pyperclip.copy(text)
        log(f"[typer] copiado al portapapeles ({len(text)} chars)")
    except Exception as e:
        log(f"[typer] error copiando al portapapeles: {e}")
        return False

    if not _wait_modifiers_released(config.PASTE_MODIFIER_WAIT_TIMEOUT):
        log("[typer] modificadores físicos seguían pulsados; intento pegar igual")

    if paste_delay_ms is None:
        delay_s = config.PASTE_DELAY
    else:
        delay_s = max(0, int(paste_delay_ms)) / 1000.0
    time.sleep(delay_s)

    log("[typer] intentando pegar (Ctrl+V) en la ventana activa…")
    if not _send_ctrl_v(log):
        log("[typer] no se pudo enviar Ctrl+V. El texto quedó en el portapapeles; "
            "pégalo manualmente. Si el destino corre como administrador, ejecuta "
            "Wisip también como administrador.")
        return False

    log(f"[typer] pegado OK en ventana activa ({len(text)} chars)")
    return True
