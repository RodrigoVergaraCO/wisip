import threading

import keyboard

from . import config


_KEY_ALIASES = {
    "win": "windows",
    "winkey": "windows",
    "super": "windows",
    "meta": "windows",
    "control": "ctrl",
    "caps lock": "capslock",
    "caps": "capslock",
    "esc": "escape",
}

_MODIFIERS = {"ctrl", "alt", "shift", "windows"}


def _normalize_keys(hotkey: str) -> list[str]:
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    return [_KEY_ALIASES.get(p, p) for p in parts]


def _canonicalize_event_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    if n in ("left ctrl", "right ctrl"):
        return "ctrl"
    if n in ("left alt", "right alt", "alt gr", "altgr"):
        return "alt"
    if n in ("left shift", "right shift"):
        return "shift"
    if n in ("left windows", "right windows", "left win", "right win"):
        return "windows"
    if n in ("caps lock", "caps"):
        return "capslock"
    return n


class HotkeyManager:
    """Hook global push-to-talk con supresión de la tecla del hotkey mientras
    está activa. Eso evita que la tecla escriba caracteres en el input destino
    (ej. mantener `|` no debe meter `|||||||` antes del pegado).

    - `on_press`: cuando todas las teclas del hotkey quedan pulsadas a la vez.
    - `on_release`: cuando, tras estar el chord completo, deja de estarlo.
    - `is_enabled`: getter callable. Si devuelve False, no fira callbacks ni
      suprime la tecla (la tecla funciona normal en cualquier app).
    """

    def __init__(self, on_press, on_release, on_log=None, hotkey: str | None = None,
                 is_enabled=None):
        self.on_press = on_press
        self.on_release = on_release
        self.on_log = on_log or (lambda m: None)
        self.is_enabled = is_enabled or (lambda: True)
        self._hotkey = hotkey or config.DEFAULT_HOTKEY
        self._keys: list[str] = []
        self._pressed: set[str] = set()
        self._fired = False
        self._hook_handle = None
        self._lock = threading.Lock()
        self._registered = False

    @property
    def current(self) -> str:
        return self._hotkey

    def start(self):
        if self._registered:
            return
        self._keys = _normalize_keys(self._hotkey)
        if not self._keys:
            self.on_log("[hotkey] hotkey vacío, no registro nada")
            return
        try:
            self._pressed.clear()
            self._fired = False
            # suppress=True permite que el callback devuelva False para
            # consumir el evento (que no llegue al input activo).
            self._hook_handle = keyboard.hook(self._on_event, suppress=True)
            self._registered = True
            self.on_log(f"[hotkey] registrado (push-to-talk, supresión activa): "
                        f"{self._hotkey.upper()}")
        except Exception as e:
            self.on_log(f"[hotkey] error registrando '{self._hotkey}': {e}")
            raise

    def _on_event(self, event):
        # Devuelve True → la tecla llega al sistema/apps normalmente.
        # Devuelve False → suprime el evento (no llega al input activo).
        # En caso de cualquier error → True (no romper el teclado del usuario).
        try:
            name = _canonicalize_event_name(event.name or "")

            # Tecla fuera de nuestro hotkey: siempre dejar pasar.
            if name not in self._keys:
                return True

            # Hotkey desactivado desde la UI: dejar que la tecla funcione normal.
            if not self.is_enabled():
                return True

            with self._lock:
                if event.event_type == keyboard.KEY_DOWN:
                    self._pressed.add(name)
                    if not self._fired and all(k in self._pressed for k in self._keys):
                        self._fired = True
                        threading.Thread(
                            target=self._safe_call, args=(self.on_press,), daemon=True
                        ).start()
                    # Mientras el chord esté completo, suprimimos KEY_DOWN del
                    # trigger para que no se escriba en el input activo.
                    if self._fired:
                        return False
                elif event.event_type == keyboard.KEY_UP:
                    self._pressed.discard(name)
                    if self._fired and not all(k in self._pressed for k in self._keys):
                        self._fired = False
                        threading.Thread(
                            target=self._safe_call, args=(self.on_release,), daemon=True
                        ).start()
                    # KEY_UP siempre lo dejamos pasar para que el OS mantenga
                    # su estado interno de teclas pulsadas limpio.

            return True
        except Exception as e:
            try:
                self.on_log(f"[hotkey] error en hook: {e}")
            except Exception:
                pass
            return True  # safety: nunca romper el teclado por un bug nuestro

    def _safe_call(self, fn):
        if fn is None:
            return
        try:
            fn()
        except Exception as e:
            self.on_log(f"[hotkey] error en callback: {e}")

    def rebind(self, new_hotkey: str):
        if new_hotkey == self._hotkey and self._registered:
            return
        self.stop()
        self._hotkey = new_hotkey
        self.start()

    def stop(self):
        if not self._registered:
            return
        try:
            if self._hook_handle is not None:
                keyboard.unhook(self._hook_handle)
        except Exception:
            pass
        self._hook_handle = None
        self._registered = False
        with self._lock:
            self._pressed.clear()
            self._fired = False
