"""Ventana de progreso del primer arranque (descarga de modelo / paquete NVIDIA).

Pequeña, siempre encima, con el logo, un mensaje, una barra de progreso y
una línea de detalle (porcentaje, MB, velocidad, tiempo restante). Toda la
API pública es thread-safe: el hilo de trabajo llama a `show`, `set_progress`,
`ask`, `info` y `close`; internamente todo entra al hilo de Tk con `after`.

`ask()` e `info()` BLOQUEAN al hilo llamador hasta que el usuario responde:
pensadas para el hilo de preparación, nunca para el hilo de Tk.
"""

import os
import threading
import time
import tkinter as tk

import customtkinter as ctk

from . import config
from . import themes

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


class SetupWindow:
    def __init__(self, root, palette: dict | None = None, on_log=None):
        self.root = root
        self.pal = palette or themes.get_palette(themes.DEFAULT_THEME)
        self.on_log = on_log or (lambda m: None)
        self.cancel_event = threading.Event()
        self._win = None
        self._logo = None
        self._t0 = 0.0
        self._last_paint = 0.0
        self._lock = threading.Lock()

    # ── helpers de hilo ──
    def _ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception as e:  # root destruido
            self.on_log(f"[setup-ui] {e}")

    # ── construcción ──
    def _ensure(self):
        if self._win is not None and self._win.winfo_exists():
            return
        pal = self.pal
        win = ctk.CTkToplevel(self.root, fg_color=pal["BG_BASE"])
        win.title("Wisip")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self._cancel_clicked)
        try:
            if config.ICO_PATH.exists():
                win.after(200, lambda: win.iconbitmap(str(config.ICO_PATH)))
        except Exception:
            pass

        body = ctk.CTkFrame(win, fg_color=pal["BG_SURFACE"], corner_radius=12)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 6))
        if _HAS_PIL and config.LOGO_PATH.exists():
            try:
                img = Image.open(config.LOGO_PATH)
                w, h = img.size
                th = 36
                tw = max(1, int(round(w * th / h)))
                self._logo = ctk.CTkImage(light_image=img, dark_image=img, size=(min(tw, 180), th))
                ctk.CTkLabel(top, image=self._logo, text="").pack(side="left", padx=(0, 12))
            except Exception:
                self._logo = None
        self.title_lbl = ctk.CTkLabel(
            top, text="", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=pal["TEXT"], anchor="w", justify="left",
        )
        self.title_lbl.pack(side="left", fill="x", expand=True)

        self.msg_lbl = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont(size=12), text_color=pal["TEXT_VARIANT"],
            anchor="w", justify="left", wraplength=400,
        )
        self.msg_lbl.pack(fill="x", padx=18, pady=(0, 8))

        self.bar = ctk.CTkProgressBar(
            body, height=10, corner_radius=5, progress_color=pal["PRIMARY"],
            fg_color=pal["BG_SURFACE_HIGH"],
        )
        self.bar.pack(fill="x", padx=18, pady=(2, 4))
        self.bar.set(0)

        self.detail_lbl = ctk.CTkLabel(
            body, text="", font=ctk.CTkFont(family="Consolas", size=11),
            text_color=pal["TEXT_MUTED"], anchor="w", justify="left",
        )
        self.detail_lbl.pack(fill="x", padx=18, pady=(0, 8))

        self.btn_row = ctk.CTkFrame(body, fg_color="transparent")
        self.btn_row.pack(fill="x", padx=18, pady=(4, 14))
        self.btn_row.grid_columnconfigure((0, 1, 2), weight=1)
        self._buttons: list = []

        win.update_idletasks()
        self._center(win, 470, 240)
        self._win = win

    def _center(self, win, w, h):
        try:
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            win.geometry(f"{w}x{h}+{int((sw - w) / 2)}+{int((sh - h) / 2.4)}")
        except Exception:
            pass

    def _set_buttons(self, specs: list):
        """specs: [(texto, callback, primario)]"""
        for b in self._buttons:
            b.destroy()
        self._buttons = []
        pal = self.pal
        col = 2
        for text, cb, primary in reversed(specs):
            b = ctk.CTkButton(
                self.btn_row, text=text, command=cb, height=32, corner_radius=8,
                fg_color=pal["PRIMARY_BTN"] if primary else pal["BG_SURFACE_HIGH"],
                hover_color=pal["PRIMARY_BTN_HOVER"] if primary else pal["ACCENT_CONTAINER"],
                text_color=pal["PRIMARY_BTN_TEXT"] if primary else pal["TEXT"],
                border_width=0 if primary else 1, border_color=pal["BORDER"],
                font=ctk.CTkFont(size=12, weight="bold" if primary else "normal"),
            )
            b.grid(row=0, column=col, sticky="ew", padx=4)
            self._buttons.append(b)
            col -= 1

    def _cancel_clicked(self):
        self.cancel_event.set()
        try:
            self.detail_lbl.configure(text="Cancelando…")
        except Exception:
            pass

    # ── API pública (thread-safe) ──
    def show(self, title: str, message: str = "", cancellable: bool = True):
        self.cancel_event.clear()
        self._t0 = time.monotonic()

        def _do():
            self._ensure()
            self.title_lbl.configure(text=title)
            self.msg_lbl.configure(text=message)
            self.bar.configure(mode="determinate")
            self.bar.set(0)
            self.detail_lbl.configure(text="")
            self._set_buttons([("Cancelar", self._cancel_clicked, False)] if cancellable else [])
            self._win.deiconify()
            self._win.lift()
        self._ui(_do)

    def set_message(self, message: str):
        self._ui(lambda: self._win and self.msg_lbl.configure(text=message))

    def set_progress(self, done: int, total: int, label: str = ""):
        """Llamable muchas veces por segundo: se repinta como mucho ~10 veces/s."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_paint < 0.1 and not (total and done >= total):
                return
            self._last_paint = now
        from .setup_assets import format_progress
        frac = (done / total) if total else 0.0
        text = format_progress(done, total, now - self._t0)
        if label:
            text = f"{label}\n{text}"

        def _do():
            if not self._win:
                return
            if total:
                self.bar.configure(mode="determinate")
                self.bar.set(max(0.0, min(1.0, frac)))
            else:
                self.bar.configure(mode="indeterminate")
                self.bar.start()
            self.detail_lbl.configure(text=text)
        self._ui(_do)

    def ask(self, title: str, message: str, yes: str = "Descargar", no: str = "Ahora no") -> bool:
        """Pregunta sí/no. Bloquea el hilo llamador hasta la respuesta."""
        # Pruebas end-to-end sin clics (scripts/e2e): acepta automáticamente.
        if os.environ.get("WISIP_SETUP_AUTO_YES") == "1":
            self.on_log(f"[setup-ui] auto-sí a '{title}' (WISIP_SETUP_AUTO_YES)")
            return True
        ev = threading.Event()
        result = {"v": False}

        def _answer(v):
            result["v"] = v
            ev.set()

        def _do():
            self._ensure()
            self.title_lbl.configure(text=title)
            self.msg_lbl.configure(text=message)
            self.bar.set(0)
            self.detail_lbl.configure(text="")
            self._set_buttons([(no, lambda: _answer(False), False), (yes, lambda: _answer(True), True)])
            self._win.protocol("WM_DELETE_WINDOW", lambda: _answer(False))
            self._win.deiconify()
            self._win.lift()
        self._ui(_do)
        ev.wait()
        self._ui(lambda: self._win and self._win.protocol("WM_DELETE_WINDOW", self._cancel_clicked))
        return result["v"]

    def info(self, title: str, message: str, ok: str = "Entendido"):
        """Aviso con un botón. Bloquea hasta que el usuario lo cierra."""
        ev = threading.Event()

        def _do():
            self._ensure()
            self.title_lbl.configure(text=title)
            self.msg_lbl.configure(text=message)
            self.detail_lbl.configure(text="")
            self._set_buttons([(ok, ev.set, True)])
            self._win.protocol("WM_DELETE_WINDOW", ev.set)
            self._win.deiconify()
            self._win.lift()
        self._ui(_do)
        ev.wait()

    def close(self):
        def _do():
            if self._win is not None:
                try:
                    self._win.destroy()
                except Exception:
                    pass
                self._win = None
        self._ui(_do)
