import json
import threading
from collections import deque

from . import config


class History:
    """Historial simple persistido a history.json (últimas N entradas)."""

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda m: None)
        self._lock = threading.Lock()
        self._items = deque(maxlen=config.HISTORY_MAX)
        self._load()

    def _load(self):
        path = config.HISTORY_PATH
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, list):
                with self._lock:
                    self._items = deque(
                        [str(x) for x in items][:config.HISTORY_MAX],
                        maxlen=config.HISTORY_MAX,
                    )
                self.on_log(f"[history] cargadas {len(self._items)} entradas")
        except Exception as e:
            self.on_log(f"[history] error leyendo: {e}")

    def _save_unlocked(self):
        try:
            with config.HISTORY_PATH.open("w", encoding="utf-8") as f:
                json.dump(list(self._items), f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.on_log(f"[history] error guardando: {e}")

    def add(self, text: str):
        if not text:
            return
        with self._lock:
            self._items.appendleft(text)
            self._save_unlocked()

    def items(self) -> list:
        with self._lock:
            return list(self._items)

    def clear(self):
        with self._lock:
            self._items.clear()
            self._save_unlocked()
        self.on_log("[history] limpiado")
