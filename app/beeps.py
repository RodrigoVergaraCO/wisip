import threading

from . import config

try:
    import winsound
    _AVAILABLE = True
except ImportError:
    winsound = None
    _AVAILABLE = False


class Beeps:
    """Beeps de feedback (start, stop, error). Asíncronos para no bloquear el hilo del hotkey."""

    def __init__(self, enabled: bool = True, on_log=None):
        self.enabled = enabled
        self.on_log = on_log or (lambda m: None)
        if not _AVAILABLE:
            self.on_log("[beeps] winsound no disponible en este sistema")

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def _play(self, freq: int, dur: int):
        if not (_AVAILABLE and self.enabled):
            return
        try:
            winsound.Beep(freq, dur)
        except Exception as e:
            # No spamear el log si el sistema no quiere reproducir.
            self.on_log(f"[beeps] error tocando ({freq}Hz, {dur}ms): {e}")

    def _async(self, freq: int, dur: int):
        threading.Thread(target=self._play, args=(freq, dur), daemon=True).start()

    def start(self):
        self._async(*config.BEEP_START)

    def stop(self):
        self._async(*config.BEEP_STOP)

    def error(self):
        self._async(*config.BEEP_ERROR)
