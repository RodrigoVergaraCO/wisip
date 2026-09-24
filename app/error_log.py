# -*- coding: utf-8 -*-
"""Errores a archivo + crash handlers + diálogos nativos de error.

El .exe empaquetado corre con console=False: cualquier print/traceback muere
en un stdout inexistente y un fallo de arranque hace que la app "desaparezca
en silencio", imposible de diagnosticar o soportar. Con este módulo:

  - Todo error grave queda en logs/wisip-errors.log (con tope de tamaño).
  - Las excepciones no capturadas (hilo principal Y workers) van al log.
  - faulthandler escribe la traza incluso en crashes duros (segfault en DLL).
  - Los fallos fatales muestran un MessageBox NATIVO (ctypes, no Tk: puede
    que Tk sea justamente lo que falló).

Diseño: nada aquí lanza jamás — un fallo del propio logging no puede tumbar
la app (misma filosofía que dictation_log).
"""

import ctypes
import faulthandler
import sys
import threading
import time
import traceback

from . import config

_MAX_BYTES = 1_000_000  # al superarlo se conserva la mitad final
_faulthandler_file = None  # vivo todo el proceso (faulthandler lo necesita)


def _append(text: str):
    try:
        p = config.ERROR_LOG_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > _MAX_BYTES:
            p.write_bytes(p.read_bytes()[-_MAX_BYTES // 2:])
        with p.open("a", encoding="utf-8", errors="replace") as f:
            f.write(text)
    except Exception:
        pass


def log_error(context: str, exc: BaseException | None = None):
    """Escribe un error con timestamp y, si se pasa la excepción, su traceback."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{stamp}] {context}\n"]
    if exc is not None:
        try:
            lines.append("".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ))
        except Exception:
            lines.append(f"  {type(exc).__name__}: {exc}\n")
    _append("".join(lines))


def show_error_dialog(title: str, message: str):
    """MessageBox nativo de Windows (funciona aunque Tk no haya arrancado).
    Bloquea el hilo llamador: para no congelar la UI usar la variante async."""
    try:
        MB_ICONERROR = 0x10
        MB_SETFOREGROUND = 0x10000
        MB_TOPMOST = 0x40000
        ctypes.windll.user32.MessageBoxW(
            None, str(message), str(title),
            MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST,
        )
    except Exception:
        pass


def show_error_dialog_async(title: str, message: str):
    threading.Thread(
        target=show_error_dialog, args=(title, message),
        daemon=True, name="error-dialog",
    ).start()


def install_crash_handlers():
    """Redirige excepciones no capturadas (main + hilos) y crashes duros al
    log de errores. Llamar UNA vez, lo antes posible en el arranque."""
    global _faulthandler_file
    try:
        config.ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        def _hook(exc_type, exc, tb):
            log_error("excepción no capturada (hilo principal)", exc)

        sys.excepthook = _hook

        def _thread_hook(args):
            name = args.thread.name if args.thread else "?"
            log_error(f"excepción no capturada (hilo {name})", args.exc_value)

        threading.excepthook = _thread_hook

        # Crashes a nivel C (DLL CUDA, ctranslate2...): traza de todos los
        # hilos al mismo log. El file handle debe vivir todo el proceso.
        _faulthandler_file = config.ERROR_LOG_PATH.open("a", encoding="utf-8")
        faulthandler.enable(file=_faulthandler_file)
    except Exception:
        pass
