"""Asistente de primer arranque (2.8.0).

Cinco pasos cortos que dejan a un desconocido dictando sin leer un manual:
bienvenida y privacidad → micrófono (con medidor en vivo) → tecla para
dictar → idioma → (aceleración NVIDIA si hay GPU) → listo.

Corre en el hilo de Tk como Toplevel del root (aunque la ventana principal
esté oculta). El Controller le pasa callbacks y recibe un dict con las
decisiones en `on_finish`. La ventana se cierra sola al terminar; cerrarla
con la X equivale a terminar con los valores actuales (no se vuelve a
mostrar: el ajuste `first_run_done` lo decide el Controller).
"""

import tkinter as tk

import customtkinter as ctk

from . import audio_devices
from . import config
from . import themes

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

_LEVEL_MS = 50


class OnboardingWizard:
    def __init__(
        self, root, *, palette: dict | None = None,
        initial: dict | None = None,
        devices: list[dict] | None = None,
        hotkey_label: str = "",
        gpu_info: dict | None = None,
        get_level=None,
        on_device_preview=None,
        on_rebind=None,
        on_finish=None,
        on_log=None,
    ):
        self.root = root
        self.pal = palette or themes.get_palette(themes.DEFAULT_THEME)
        self.initial = dict(initial or {})
        self.devices = list(devices or [])
        self.hotkey_label = hotkey_label or config.DEFAULT_HOTKEY
        self.gpu_info = gpu_info
        self.get_level = get_level or (lambda: 0.0)
        self.on_device_preview = on_device_preview or (lambda name: None)
        self.on_rebind = on_rebind or (lambda: None)
        self.on_finish = on_finish or (lambda result: None)
        self.on_log = on_log or (lambda m: None)

        self._page = 0
        self._pages: list = []
        self._level_job = None
        self._finished = False
        self._logo = None

        # Estado editable.
        self.var_log = tk.BooleanVar(value=bool(self.initial.get("dictation_log_enabled", True)))
        dev_name = str(self.initial.get("input_device_name") or "")
        self.var_device = tk.StringVar(value=audio_devices.device_label(dev_name))
        lang = str(self.initial.get("language") or config.LANGUAGE)
        self.var_lang = tk.StringVar(value=lang if lang in config.LANGUAGE_CODES else config.LANGUAGE)
        self.var_mixed = tk.BooleanVar(value=bool(self.initial.get("mixed_language_mode", True)))
        self.var_gpu = tk.StringVar(value="yes")

        self._build()

    # ── construcción ────────────────────────────────────────────────────
    def _build(self):
        pal = self.pal
        win = ctk.CTkToplevel(self.root, fg_color=pal["BG_BASE"])
        win.title("Wisip — primeros pasos")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self._finish)
        try:
            if config.ICO_PATH.exists():
                win.after(200, lambda: win.iconbitmap(str(config.ICO_PATH)))
        except Exception:
            pass
        self.win = win

        outer = ctk.CTkFrame(win, fg_color=pal["BG_SURFACE"], corner_radius=12)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        head = ctk.CTkFrame(outer, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 4))
        if _HAS_PIL and config.LOGO_PATH.exists():
            try:
                img = Image.open(config.LOGO_PATH)
                w, h = img.size
                th = 34
                self._logo = ctk.CTkImage(light_image=img, dark_image=img,
                                          size=(min(int(w * th / h), 170), th))
                ctk.CTkLabel(head, image=self._logo, text="").pack(side="left", padx=(0, 12))
            except Exception:
                self._logo = None
        self.step_lbl = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=11),
                                     text_color=pal["TEXT_MUTED"], anchor="e")
        self.step_lbl.pack(side="right")

        self.body = ctk.CTkFrame(outer, fg_color="transparent", height=300)
        self.body.pack(fill="both", expand=True, padx=20, pady=(4, 4))
        self.body.pack_propagate(False)

        nav = ctk.CTkFrame(outer, fg_color="transparent")
        nav.pack(fill="x", padx=20, pady=(4, 16))
        self.back_btn = self._button(nav, "Atrás", self._back, primary=False)
        self.back_btn.pack(side="left")
        self.next_btn = self._button(nav, "Siguiente", self._next, primary=True)
        self.next_btn.pack(side="right")

        self._pages = [self._page_welcome, self._page_mic, self._page_hotkey, self._page_language]
        if self.gpu_info:
            self._pages.append(self._page_gpu)
        self._pages.append(self._page_done)

        win.update_idletasks()
        w, h = 560, 470
        try:
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            win.geometry(f"{w}x{h}+{int((sw - w) / 2)}+{int((sh - h) / 2.4)}")
        except Exception:
            pass
        self._show_page(0)

    def _button(self, parent, text, cmd, primary: bool):
        pal = self.pal
        return ctk.CTkButton(
            parent, text=text, command=cmd, height=34, width=120, corner_radius=8,
            fg_color=pal["PRIMARY_BTN"] if primary else pal["BG_SURFACE_HIGH"],
            hover_color=pal["PRIMARY_BTN_HOVER"] if primary else pal["ACCENT_CONTAINER"],
            text_color=pal["PRIMARY_BTN_TEXT"] if primary else pal["TEXT"],
            border_width=0 if primary else 1, border_color=pal["BORDER"],
            font=ctk.CTkFont(size=12, weight="bold" if primary else "normal"),
        )

    def _title(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=self.pal["TEXT"], anchor="w", justify="left").pack(fill="x", pady=(6, 6))

    def _text(self, parent, text, muted=False, size=12):
        lbl = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=size),
                           text_color=self.pal["TEXT_MUTED"] if muted else self.pal["TEXT_VARIANT"],
                           anchor="w", justify="left", wraplength=500)
        lbl.pack(fill="x", pady=(0, 8))
        return lbl

    def _check(self, parent, text, var):
        pal = self.pal
        cb = ctk.CTkCheckBox(parent, text=text, variable=var, fg_color=pal["PRIMARY_BTN"],
                             hover_color=pal["PRIMARY_BTN_HOVER"], border_color=pal["BORDER"],
                             text_color=pal["TEXT"], font=ctk.CTkFont(size=12))
        cb.pack(anchor="w", pady=(4, 4))
        return cb

    def _radio(self, parent, text, var, value):
        pal = self.pal
        rb = ctk.CTkRadioButton(parent, text=text, variable=var, value=value,
                                fg_color=pal["PRIMARY_BTN"], hover_color=pal["PRIMARY_BTN_HOVER"],
                                border_color=pal["BORDER"], text_color=pal["TEXT"],
                                font=ctk.CTkFont(size=12))
        rb.pack(anchor="w", pady=(3, 3))
        return rb

    # ── páginas ─────────────────────────────────────────────────────────
    def _page_welcome(self, f):
        self._title(f, "Bienvenido a Wisip")
        self._text(f, "Mantén una tecla, habla, suéltala: el texto aparece en la app que "
                      "tengas abierta. Todo el reconocimiento de voz ocurre en este equipo. "
                      "Tu voz y tus textos no salen de tu PC.")
        self._text(f, "Privacidad", size=13)
        self._check(f, "Guardar un registro local de mis dictados (solo en este equipo) para "
                       "que Wisip aprenda mi vocabulario", self.var_log)
        self._text(f, "Se guarda en tu carpeta de usuario y puedes apagarlo cuando quieras "
                      "desde la pestaña Transcribe. Sin él, Wisip funciona igual.", muted=True, size=11)

    def _page_mic(self, f):
        self._title(f, "Tu micrófono")
        self._text(f, "Elige el micrófono y di algo: la barra debe moverse.")
        names = [audio_devices.DEFAULT_LABEL] + [d["name"] for d in self.devices]
        if self.var_device.get() not in names:
            self.var_device.set(audio_devices.DEFAULT_LABEL)
        pal = self.pal
        menu = ctk.CTkOptionMenu(
            f, values=names, variable=self.var_device, command=self._device_changed,
            fg_color=pal["BG_INPUT"], button_color=pal["BG_SURFACE_HIGH"],
            button_hover_color=pal["BG_SURFACE_HIGHEST"], text_color=pal["TEXT"],
            dropdown_fg_color=pal["BG_SURFACE_HIGH"], dropdown_hover_color=pal["ACCENT_CONTAINER"],
            dropdown_text_color=pal["TEXT"], corner_radius=6, font=ctk.CTkFont(size=12),
        )
        menu.pack(fill="x", pady=(2, 12))
        self.level_bar = ctk.CTkProgressBar(f, height=14, corner_radius=7,
                                            progress_color=pal["PRIMARY"], fg_color=pal["BG_SURFACE_HIGH"])
        self.level_bar.pack(fill="x", pady=(0, 6))
        self.level_bar.set(0)
        self.level_hint = self._text(f, "Escuchando…", muted=True, size=11)
        self._text(f, "Si la barra no se mueve: revisa el botón de silencio del micrófono, "
                      "el volumen de entrada en Windows (Sonido → Entrada) o elige otro "
                      "dispositivo. Puedes cambiarlo luego en la pestaña Transcribe.",
                   muted=True, size=11)

    def _page_hotkey(self, f):
        self._title(f, "La tecla para dictar")
        self._text(f, "Wisip es push-to-talk: MANTÉN la tecla mientras hablas y SUÉLTALA "
                      "para que el texto se pegue donde tengas el cursor.")
        pal = self.pal
        box = ctk.CTkFrame(f, fg_color=pal["BG_SURFACE_HIGH"], corner_radius=10)
        box.pack(fill="x", pady=(4, 10))
        self.hotkey_big = ctk.CTkLabel(box, text=self._pretty_hotkey(), font=ctk.CTkFont(size=30, weight="bold"),
                                       text_color=pal["PRIMARY"])
        self.hotkey_big.pack(pady=(14, 2))
        ctk.CTkLabel(box, text="tecla actual", font=ctk.CTkFont(size=11),
                     text_color=pal["TEXT_MUTED"]).pack(pady=(0, 12))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x")
        self.rebind_btn = self._button(row, "Cambiar tecla…", self._rebind_clicked, primary=False)
        self.rebind_btn.configure(width=160)
        self.rebind_btn.pack(side="left")
        self.rebind_status = ctk.CTkLabel(row, text="", font=ctk.CTkFont(size=11),
                                          text_color=pal["TEXT_MUTED"], anchor="w")
        self.rebind_status.pack(side="left", padx=12)
        self._text(f, "Consejo: una tecla que no uses al escribir (F8, Bloq Despl, la tecla "
                      "junto al 1) evita pulsaciones accidentales.", muted=True, size=11)

    def _page_language(self, f):
        self._title(f, "Idioma")
        self._text(f, "¿En qué idioma dictas la mayor parte del tiempo?")
        self._radio(f, "Español (recomendado si dictas sobre todo en español)", self.var_lang, "es")
        self._radio(f, "English", self.var_lang, "en")
        self._radio(f, "Automático (detecta el idioma en cada dictado)", self.var_lang, "auto")
        self._text(f, "", size=6)
        self._check(f, "Dicto frases completas en inglés dentro del español (modo mixto)", self.var_mixed)
        self._text(f, "Con el modo mixto cada frase conserva su idioma. Los términos técnicos "
                      "sueltos en inglés se reconocen siempre.", muted=True, size=11)

    def _page_gpu(self, f):
        g = self.gpu_info or {}
        vram = g.get("vram_mb") or 0
        vram_txt = f" · {vram / 1024:.0f} GB" if vram else ""
        self._title(f, "Acelerar con tu GPU NVIDIA")
        self._text(f, f"Se detectó {g.get('name', 'una GPU NVIDIA')}{vram_txt}. Con la aceleración "
                      f"GPU la transcripción es entre 10 y 20 veces más rápida y se usa el "
                      f"modelo más preciso.")
        self._radio(f, f"Descargar ahora (~{config.GPU_PACK_DOWNLOAD_MB / 1000:.1f} GB, una sola vez)",
                    self.var_gpu, "yes")
        self._radio(f, "Ahora no (Wisip funciona en CPU; podrás descargarla luego desde la app)",
                    self.var_gpu, "no")

    def _page_done(self, f):
        self._title(f, "Listo")
        lang_lbl = config.LANGUAGE_CODE_TO_LABEL.get(self.var_lang.get(), self.var_lang.get())
        lines = [
            f"Tecla: {self._pretty_hotkey()}",
            f"Micrófono: {self.var_device.get()}",
            f"Idioma: {lang_lbl}" + (" + modo mixto" if self.var_mixed.get() else ""),
            f"Registro local de dictados: {'sí' if self.var_log.get() else 'no'}",
        ]
        if self.gpu_info:
            lines.append("Aceleración NVIDIA: " + ("se descarga ahora" if self.var_gpu.get() == "yes" else "más tarde"))
        self._text(f, "\n".join(lines))
        model = str(self.initial.get("model") or config.DEFAULT_MODEL)
        if self.gpu_info and self.var_gpu.get() == "yes":
            model = config.GPU_RECOMMENDED_MODEL
        mb = config.MODEL_DOWNLOAD_MB.get(model, 0)
        size_txt = f"~{mb / 1000:.1f} GB" if mb >= 1000 else f"~{mb} MB"
        self._text(f, f"Al pulsar Empezar, Wisip descargará el modelo de voz ({model}, {size_txt}) "
                      "una sola vez y quedará listo. Luego prueba: mantén la tecla, di una "
                      "frase y suéltala.", muted=True, size=11)

    # ── navegación ──────────────────────────────────────────────────────
    def _show_page(self, i: int):
        self._leave_page(self._page)
        self._page = max(0, min(i, len(self._pages) - 1))
        for w in self.body.winfo_children():
            w.destroy()
        frame = ctk.CTkFrame(self.body, fg_color="transparent")
        frame.pack(fill="both", expand=True)
        self._pages[self._page](frame)
        self.step_lbl.configure(text=f"Paso {self._page + 1} de {len(self._pages)}")
        self.back_btn.configure(state="normal" if self._page > 0 else "disabled")
        last = self._page == len(self._pages) - 1
        self.next_btn.configure(text="Empezar" if last else "Siguiente")
        self._enter_page(self._page)

    def _enter_page(self, i: int):
        if self._pages[i] == self._page_mic:
            self._device_changed(self.var_device.get())
            self._tick_level()

    def _leave_page(self, i: int):
        if self._pages and self._pages[i] == self._page_mic:
            if self._level_job is not None:
                try:
                    self.win.after_cancel(self._level_job)
                except Exception:
                    pass
                self._level_job = None
            self._safe(lambda: self.on_device_preview(None))

    def _tick_level(self):
        try:
            lvl = float(self.get_level() or 0.0)
            self.level_bar.set(max(0.0, min(1.0, lvl)))
            if lvl > 0.04:
                self.level_hint.configure(text="Te escucho ✓", text_color=self.pal["PRIMARY"])
        except Exception:
            return
        self._level_job = self.win.after(_LEVEL_MS, self._tick_level)

    def _device_changed(self, label):
        name = "" if label == audio_devices.DEFAULT_LABEL else label
        self._safe(lambda: self.on_device_preview(name))
        try:
            self.level_hint.configure(text="Escuchando…", text_color=self.pal["TEXT_MUTED"])
        except Exception:
            pass

    def _rebind_clicked(self):
        self.rebind_status.configure(text="Pulsa la tecla nueva… (Esc cancela)")
        self.rebind_btn.configure(state="disabled")
        self._safe(self.on_rebind)

    def set_hotkey(self, label: str | None):
        """Llamado por el Controller al terminar el rebind (cualquier hilo)."""
        def _do():
            if label:
                self.hotkey_label = label
            try:
                self.hotkey_big.configure(text=self._pretty_hotkey())
                self.rebind_status.configure(text="Tecla cambiada ✓" if label else "Sin cambios")
                self.rebind_btn.configure(state="normal")
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def _pretty_hotkey(self) -> str:
        return (self.hotkey_label or "").upper().replace("+", " + ")

    def _back(self):
        self._show_page(self._page - 1)

    def _next(self):
        if self._page >= len(self._pages) - 1:
            self._finish()
        else:
            self._show_page(self._page + 1)

    # ── cierre ──────────────────────────────────────────────────────────
    def result(self) -> dict:
        dev = self.var_device.get()
        return {
            "dictation_log_enabled": bool(self.var_log.get()),
            "input_device_name": "" if dev == audio_devices.DEFAULT_LABEL else dev,
            "language": self.var_lang.get(),
            "mixed_language_mode": bool(self.var_mixed.get()),
            "gpu_pack": (self.var_gpu.get() == "yes") if self.gpu_info else None,
            "hotkey": self.hotkey_label,
        }

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        self._leave_page(self._page)
        res = self.result()
        try:
            self.win.destroy()
        except Exception:
            pass
        self._safe(lambda: self.on_finish(res))

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            self.on_log(f"[onboarding] callback falló: {e}")


def default_result(initial: dict | None, gpu_info: dict | None) -> dict:
    """Resultado equivalente a aceptar el asistente sin cambiar nada (modo
    automático de pruebas e2e: WISIP_SETUP_AUTO_YES=1)."""
    ini = dict(initial or {})
    lang = str(ini.get("language") or config.LANGUAGE)
    return {
        "dictation_log_enabled": bool(ini.get("dictation_log_enabled", True)),
        "input_device_name": str(ini.get("input_device_name") or ""),
        "language": lang if lang in config.LANGUAGE_CODES else config.LANGUAGE,
        "mixed_language_mode": bool(ini.get("mixed_language_mode", True)),
        "gpu_pack": True if gpu_info else None,
        "hotkey": str(ini.get("hotkey") or config.DEFAULT_HOTKEY),
    }
