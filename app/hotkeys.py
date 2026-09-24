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
# Modificadores que Windows interpreta al SOLTARLOS si no se pulsó otra tecla
# entre medias: Win abre el menú Inicio, Alt activa la barra de menús.
_MASKED_MODIFIERS = {"windows", "alt"}
# Tecla virtual sin asignar (0xE8). Se inyecta pulsación+liberación al
# dispararse un chord con Win/Alt: Windows ve "otra tecla" y no abre Inicio al
# soltar. Es la misma técnica que usa AutoHotkey para los atajos con #.
_MASK_VK = 0xE8


def _needs_mask(keys) -> bool:
    return bool(_MASKED_MODIFIERS & set(keys))


def _mask_win_key():
    """Pulsa y suelta la tecla fantasma. Nunca lanza."""
    try:
        import ctypes
        u32 = ctypes.windll.user32
        u32.keybd_event(_MASK_VK, 0, 0, 0)
        u32.keybd_event(_MASK_VK, 0, 2, 0)   # KEYEVENTF_KEYUP
    except Exception:
        pass


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

    def _fire(self, fn, args=(), mask=False):
        """Ejecuta el callback fuera del hook. Si el chord lleva Win/Alt,
        inyecta antes la tecla fantasma (ver _mask_win_key)."""
        if mask:
            _mask_win_key()
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as e:
            self.on_log(f"[hotkey] error en callback: {e}")

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
                            target=self._fire, args=(self.on_press, (), _needs_mask(self._keys)),
                            daemon=True,
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

    def rebind(self, new_hotkey: str):
        if new_hotkey == self._hotkey and self._registered:
            return
        self.stop()
        self._hotkey = new_hotkey
        self.start()


class MultiHotkeyManager(HotkeyManager):
    """Varios atajos push-to-talk con nombre (2.12.0): "dictate" y
    "translate". Si dos chords se cumplen a la vez (Ctrl+Win está contenido
    en Ctrl+Win+Shift), gana el MÁS LARGO y solo dispara ese. Los callbacks
    reciben el nombre del chord.

    2.12.1: si un chord ya está activo y el usuario añade teclas hasta
    completar otro MÁS LARGO que lo contiene (Ctrl+Win → +Shift), se cambia
    de chord sin soltar: `on_switch(viejo, nuevo)` (si no se da, se llama
    `on_press(nuevo)`). Soltar cualquier tecla del chord activo dispara
    `on_release(nombre)`. Los chords con Win/Alt inyectan una tecla fantasma
    al dispararse para que soltar no abra el menú Inicio / la barra de menús.
    """

    def __init__(self, on_press, on_release, on_log=None, hotkeys: dict | None = None,
                 is_enabled=None, on_switch=None):
        self._hotkeys: dict = dict(hotkeys or {"dictate": config.DEFAULT_HOTKEY})
        super().__init__(on_press, on_release, on_log=on_log,
                         hotkey=self._hotkeys.get("dictate", config.DEFAULT_HOTKEY),
                         is_enabled=is_enabled)
        self.on_switch = on_switch
        self._keys: dict = {}
        self._fired = None   # nombre del chord activo, o None

    @property
    def current(self) -> str:
        return self._hotkeys.get("dictate", "")

    def current_for(self, name: str) -> str:
        return self._hotkeys.get(name, "")

    def start(self):
        if self._registered:
            return
        self._keys = {n: _normalize_keys(v) for n, v in self._hotkeys.items() if v and v.strip()}
        if not self._keys:
            self.on_log("[hotkey] sin atajos, no registro nada")
            return
        try:
            self._pressed.clear()
            self._fired = None
            self._hook_handle = keyboard.hook(self._on_event, suppress=True)
            self._registered = True
            self.on_log("[hotkey] registrados (push-to-talk): " + ", ".join(
                f"{n}={v.upper()}" for n, v in self._hotkeys.items() if v))
        except Exception as e:
            self.on_log(f"[hotkey] error registrando atajos: {e}")
            raise

    def _all_keys(self) -> set:
        return {k for keys in self._keys.values() for k in keys}

    def _on_event(self, event):
        try:
            name = _canonicalize_event_name(event.name or "")
            if name not in self._all_keys():
                return True
            if not self.is_enabled():
                return True
            with self._lock:
                if event.event_type == keyboard.KEY_DOWN:
                    self._pressed.add(name)
                    if self._fired is None:
                        satisfied = [n for n, keys in self._keys.items()
                                     if all(k in self._pressed for k in keys)]
                        if satisfied:
                            chosen = max(satisfied, key=lambda n: len(self._keys[n]))
                            self._fired = chosen
                            threading.Thread(
                                target=self._fire,
                                args=(self.on_press, (chosen,), _needs_mask(self._keys[chosen])),
                                daemon=True,
                            ).start()
                    else:
                        # ¿Se completó un chord más largo que contiene al activo?
                        cur = self._fired
                        cur_keys = set(self._keys[cur])
                        longer = [n for n, keys in self._keys.items()
                                  if n != cur and len(keys) > len(cur_keys)
                                  and cur_keys <= set(keys)
                                  and all(k in self._pressed for k in keys)]
                        if longer:
                            new = max(longer, key=lambda n: len(self._keys[n]))
                            self._fired = new
                            if self.on_switch is not None:
                                threading.Thread(target=self._fire, args=(self.on_switch, (cur, new)),
                                                 daemon=True).start()
                            else:
                                threading.Thread(target=self._fire, args=(self.on_press, (new,)),
                                                 daemon=True).start()
                    if self._fired is not None and name in self._keys[self._fired]:
                        return False
                elif event.event_type == keyboard.KEY_UP:
                    self._pressed.discard(name)
                    if self._fired is not None and not all(k in self._pressed for k in self._keys[self._fired]):
                        done = self._fired
                        self._fired = None
                        threading.Thread(target=self._safe_call1, args=(self.on_release, done),
                                         daemon=True).start()
            return True
        except Exception as e:
            try:
                self.on_log(f"[hotkey] error en hook: {e}")
            except Exception:
                pass
            return True

    def _safe_call1(self, fn, arg):
        if fn is None:
            return
        try:
            fn(arg)
        except Exception as e:
            self.on_log(f"[hotkey] error en callback: {e}")

    def rebind(self, name: str, new_hotkey: str):
        if self._hotkeys.get(name) == new_hotkey and self._registered:
            return
        self.stop()
        self._hotkeys[name] = new_hotkey
        self.start()

    def stop(self):
        super().stop()
        with self._lock:
            self._fired = None
