# -*- coding: utf-8 -*-
"""Instancia única de Wisip: si se abre una nueva, la anterior se cierra sola.

Dos instancias a la vez pelean por el hotkey global y el micrófono (dictados
duplicados, estados colgados en "transcribiendo"). Política: el más NUEVO gana.

Cómo funciona (solo ctypes/kernel32, sin dependencias):
  1. Al arrancar, la instancia nueva SEÑALA un evento con nombre de Windows;
     cualquier instancia previa (con este módulo) lo está escuchando y se
     cierra limpiamente (suelta mic, hotkey y bandeja).
  2. Además mata por PID los Wisip.exe viejos (builds sin este módulo, que no
     escuchan el evento). Nunca el proceso propio.
  3. Después se queda escuchando el mismo evento para cerrarse ella cuando el
     usuario abra OTRA instancia en el futuro.

El evento es manual-reset: tras señalarlo se espera un momento a que la
instancia previa despierte y LUEGO se resetea antes de escuchar (si no, la
nueva se cerraría a sí misma al encontrar el evento todavía señalado).
"""

import ctypes
import os
import subprocess
import threading
import time

# "Local\" = sesión del usuario actual (basta: exe y fuente corren en la misma).
_EVENT_NAME = "Local\\Wisip_CerrarInstanciaPrevia"

_k32 = ctypes.windll.kernel32
_EVENT_MODIFY_STATE = 0x0002
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0


def _signal_previous() -> bool:
    """Señala el evento si otra instancia lo tiene creado. True si existía."""
    h = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, _EVENT_NAME)
    if not h:
        return False
    _k32.SetEvent(h)
    _k32.CloseHandle(h)
    return True


def _kill_old_exes(on_log):
    """Cierra los Wisip.exe que no escuchan el evento (builds antiguos).
    El filtro "PID ne <propio>" garantiza no matarse a sí mismo."""
    try:
        res = subprocess.run(
            ["taskkill", "/F", "/FI", f"PID ne {os.getpid()}", "/IM", "Wisip.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (res.stdout or "").strip()
        # Solo loguear cierres reales ("Correcto: ... PID 1234"); cuando no hay
        # exes, taskkill imprime un INFO de "no hay tareas" que no interesa.
        if res.returncode == 0 and "PID" in out:
            on_log(f"[instancia] exe previo cerrado: {out.splitlines()[0]}")
    except Exception as e:
        on_log(f"[instancia] no se pudo revisar exes previos: {e}")


def enforce_single_instance(on_quit, on_log=None) -> None:
    """Cierra las instancias previas de Wisip y vigila el evento para cerrar
    ESTA instancia cuando se abra una más nueva.

    `on_quit` se llama desde un hilo propio: debe ser thread-safe (en Wisip,
    Controller._tray_quit, que delega el cierre real al hilo de la UI).
    Nunca lanza: si algo falla, la app sigue arrancando sin vigilancia.
    """
    _log = on_log or (lambda m: None)

    def on_log(msg):
        # Un logger roto (p.ej. UnicodeEncodeError en consola cp1252) NO puede
        # tumbar la vigilancia ni impedir el cierre. Misma lección que
        # Settings._safe_log.
        try:
            _log(msg)
        except Exception:
            pass

    try:
        had_prev = _signal_previous()
        _kill_old_exes(on_log)
        if had_prev:
            on_log("[instancia] instancia previa avisada para cerrarse")
            time.sleep(0.8)  # deja que suelte mic/hotkey/bandeja

        h = _k32.CreateEventW(None, True, False, _EVENT_NAME)  # manual-reset
        if not h:
            on_log("[instancia] no se pudo crear el evento; sigo sin vigilancia")
            return
        _k32.ResetEvent(h)  # limpia la señal que nosotros mismos enviamos

        def _listen():
            if _k32.WaitForSingleObject(h, _INFINITE) == _WAIT_OBJECT_0:
                on_log("[instancia] se abrio un Wisip nuevo; cerrando esta instancia")
                try:
                    on_quit()
                except Exception:
                    os._exit(0)  # último recurso: nunca dejar dos instancias vivas

        threading.Thread(target=_listen, daemon=True, name="single-instance").start()
    except Exception as e:
        on_log(f"[instancia] error configurando instancia única: {e}")
