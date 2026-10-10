import queue
import threading
import unicodedata

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

# La librería `keyboard` nombra las teclas con GetKeyNameText, que en un
# Windows en español devuelve "Windows izquierda", "Mayúsculas", "Bloq Mayús"…
# (en inglés "left windows", "left shift"). Por eso los modificadores se
# reconocen por SCAN CODE (independiente del idioma y de la distribución) y
# los nombres localizados quedan solo como respaldo (rebind, settings viejos).
_SCAN_TO_KEY = {
    29: "ctrl", 285: "ctrl",          # 0x1D (izq) / 0x11D (der)
    42: "shift", 54: "shift",         # 0x2A / 0x36
    56: "alt", 312: "alt",            # 0x38 / 0x138 (AltGr)
    91: "windows", 92: "windows",     # 0x5B / 0x5C
    58: "capslock",                   # 0x3A
    57: "space",                      # 0x39
}
_VK_TO_KEY = {                        # eventos inyectados sin scan code (scan_code = -vk)
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "windows", 0x5C: "windows",
    0x14: "capslock", 0x20: "space",
}
_LOCALIZED_ALIASES = {
    # español
    "windows izquierda": "windows", "windows derecha": "windows", "windows izq": "windows",
    "mayusculas": "shift", "mayus": "shift", "mayus izquierda": "shift", "mayus derecha": "shift",
    "mayusculas izquierda": "shift", "mayusculas derecha": "shift",
    "control": "ctrl", "control izquierda": "ctrl", "control derecha": "ctrl", "ctrl derecha": "ctrl",
    "ctrl izquierda": "ctrl",
    "alt derecha": "alt", "alt izquierda": "alt", "alt gr": "alt",
    "bloq mayus": "capslock", "bloq mayusculas": "capslock",
    "espacio": "space", "barra espaciadora": "space", "spacebar": "space",
    # inglés (variantes que emite la librería)
    "left windows": "windows", "right windows": "windows", "left win": "windows", "right win": "windows",
    "left shift": "shift", "right shift": "shift",
    "left ctrl": "ctrl", "right ctrl": "ctrl", "left control": "ctrl", "right control": "ctrl",
    "left alt": "alt", "right alt": "alt", "left menu": "alt", "right menu": "alt", "altgr": "alt",
    "caps lock": "capslock", "caps": "capslock",
}


def _fold(name: str) -> str:
    """minúsculas y sin tildes: 'Mayúsculas' → 'mayusculas'."""
    n = unicodedata.normalize("NFKD", (name or "").strip().lower())
    return "".join(c for c in n if not unicodedata.combining(c))


def _canonical_key(event) -> str:
    """Nombre canónico de la tecla de un evento de `keyboard`: primero por
    scan code (modificadores), luego por nombre (con alias localizados)."""
    sc = getattr(event, "scan_code", None)
    if isinstance(sc, int):
        if sc > 0 and sc in _SCAN_TO_KEY:
            return _SCAN_TO_KEY[sc]
        if sc < 0 and -sc in _VK_TO_KEY:
            return _VK_TO_KEY[-sc]
    return _canonicalize_event_name(getattr(event, "name", None) or "")


def _name_for_scan(scan_code: int) -> str:
    """Nombre de la tecla según Windows para un scan code físico (sin
    modificadores): 'ctrl', '|', 'f8'… Vacío si no se puede."""
    try:
        if not isinstance(scan_code, int) or scan_code <= 0:
            return ""
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        ext = 1 if scan_code > 0xFF else 0
        n = ctypes.windll.user32.GetKeyNameTextW(((scan_code & 0xFF) << 16) | (ext << 24), buf, 64)
        return _fold(buf.value) if n > 0 else ""
    except Exception:
        return ""


def _capture_from(events, is_cancel=None) -> str | None:
    """Lógica de captura sobre un iterable de eventos (testeable sin teclado).
    Acumula las teclas que bajan; al primer KEY_UP de una tecla que vimos
    bajar devuelve el chord canónico ('ctrl+|', 'shift+windows', 'f8').
    Esc cancela → None. Las teclas sin nombre (fantasma, multimedia, una
    atascada en la librería) se ignoran en vez de romper la captura."""
    pressed: dict = {}   # scan_code -> nombre canónico, en orden de pulsación
    for e in events:
        name = _canonical_key(e)
        sc = getattr(e, "scan_code", None)
        if not name and isinstance(sc, int) and sc > 0:
            name = _name_for_scan(sc)
        if e.event_type == keyboard.KEY_DOWN:
            if name in ("escape", "esc"):
                return None
            if not name:
                continue
            # Con Shift pulsado la librería nombra la tecla por su carácter
            # desplazado ('°' en vez de '|'); el atajo debe ser la tecla física.
            if name not in _MODIFIERS and "shift" in pressed.values() and len(name) == 1 and isinstance(sc, int) and sc > 0:
                base = _name_for_scan(sc)
                if len(base) == 1:
                    name = base
            if name not in pressed.values():
                pressed[sc if sc is not None else name] = name
        else:
            if not pressed:
                continue   # UP de algo que no vimos bajar: ignorar
            names = list(dict.fromkeys(pressed.values()))
            mods = [n for n in names if n in _MODIFIERS]
            others = [n for n in names if n not in _MODIFIERS]
            return "+".join(mods + others)
    return None


def capture_hotkey(timeout: float | None = None) -> str | None:
    """Bloquea hasta que el usuario pulsa y suelta una tecla o combinación
    (hook propio, sin suprimir nada). None si cancela con Esc o vence el
    timeout. Sustituye a keyboard.read_hotkey, que lanzaba
    "Can only normalize non-empty string names" si una tecla sin nombre
    quedaba marcada como pulsada."""
    q: queue.Queue = queue.Queue()
    handle = keyboard.hook(q.put)
    try:
        def _events():
            while True:
                try:
                    yield q.get(timeout=timeout)
                except queue.Empty:
                    return
        return _capture_from(_events())
    finally:
        try:
            keyboard.unhook(handle)
        except Exception:
            pass


def canonical_hotkey(hotkey: str) -> str:
    """'ctrl+mayusculas+windows izquierda' (lo que devuelve keyboard.read_hotkey
    en un Windows en español) → 'ctrl+shift+windows'. Sin duplicados."""
    out = []
    for k in _normalize_keys(hotkey or ""):
        if k not in out:
            out.append(k)
    return "+".join(out)
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
    parts = [p.strip() for p in hotkey.split("+") if p.strip()]
    out = []
    for p in parts:
        low = p.lower()
        folded = _fold(p)
        out.append(_KEY_ALIASES.get(low) or _LOCALIZED_ALIASES.get(folded) or low)
    return out


def _canonicalize_event_name(name: str) -> str:
    if not name:
        return ""
    n = name.lower()
    return _KEY_ALIASES.get(n) or _LOCALIZED_ALIASES.get(_fold(name)) or n


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
            name = _canonical_key(event)

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
            name = _canonical_key(event)
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
                            self.on_log(f"[hotkey] chord {chosen} completo con '{name}' "
                                        f"(pulsadas: {sorted(self._pressed)})")
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
                            self.on_log(f"[hotkey] cambio {cur} → {new} con '{name}' sin soltar")
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
                        self.on_log(f"[hotkey] chord {done} soltado por '{name}'")
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
