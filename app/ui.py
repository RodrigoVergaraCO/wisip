import queue
import re
import threading
import tkinter as tk
from tkinter import font as tkfont

import customtkinter as ctk

from . import audio_devices
from . import config
from . import themes
from .onboarding import pretty_hotkey

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


# ─── Paleta activa (sistema de paletas: ver app/themes.py) ───
#
# Los tokens (BG_BASE, PRIMARY_BTN, ...) viven como globals del módulo y las
# funciones los leen en tiempo de llamada: al cambiar de paleta se vuelcan los
# valores nuevos y se reconstruyen los widgets (AppUI._theme_changed).
def _apply_palette_globals(pal: dict):
    g = globals()
    for token in themes.TOKENS:
        g[token] = pal[token]


_apply_palette_globals(themes.get_palette(themes.DEFAULT_THEME))


def _pick_font(*candidates):
    """Devuelve el primer font instalado de la lista, fallback al último."""
    try:
        installed = set(tkfont.families())
    except Exception:
        return candidates[-1]
    for c in candidates:
        if c in installed:
            return c
    return candidates[-1]


class AppUI:
    """UI principal con tabs (Stitch design). Thread-safe vía cola drenada
    por `after` en el hilo Tk."""

    STATE_LABELS = {
        "idle": "INACTIVO",
        "recording": "GRABANDO",
        "transcribing": "TRANSCRIBIENDO",
        "processing": "PROCESANDO",
        "pasting": "PEGANDO",
        "loading": "CARGANDO MODELO",
        "error": "ERROR",
    }
    # Prefijos visuales para el botón principal según el texto que setea main.py.
    _BTN_ICONS = {
        "Iniciar grabación": "🎙  ",
        "Detener y transcribir": "■  ",
    }

    def __init__(
        self, *,
        on_model_change,
        on_language_change,
        on_toggle_button,
        on_paste_mode_change,
        on_beep_toggle,
        on_replacements_toggle,
        on_hotkey_toggle,
        on_history_copy,
        on_history_paste,
        on_history_clear,
        on_initial_prompt_toggle,
        on_initial_prompt_save,
        on_quality_profile_change,
        on_mixed_language_toggle,
        on_hotkey_rebind_request,
        on_start_with_windows_toggle,
        on_start_minimized_toggle,
        on_perf_profile_change,
        on_close_request,
        initial_settings: dict,
        hotkey_label: str,
        on_theme_change=None,
        # Pestaña Vocabulario (refinado por usuario). Opcionales para no romper
        # a los harnesses que construyen AppUI sin ellos (ui_bot, scripts).
        on_vocab_hotwords_save=None,
        on_vocab_tokens=None,
        on_vocab_list=None,
        on_vocab_add=None,
        on_vocab_remove=None,
        on_vocab_analyze=None,
        on_vocab_ignore=None,
        # Botón "Descargar aceleración NVIDIA" (2.7.0). Opcional.
        on_gpu_pack_install=None,
        # Selector de micrófono (2.8.0). Opcional.
        on_input_device_change=None,
        # Pestaña Licencia (2.9.0). Opcionales.
        on_license_activate=None,
        on_license_deactivate=None,
        buy_url: str = "",
    ):
        self.on_model_change = on_model_change
        self.on_language_change = on_language_change
        self.on_toggle_button = on_toggle_button
        self.on_paste_mode_change = on_paste_mode_change
        self.on_beep_toggle = on_beep_toggle
        self.on_replacements_toggle = on_replacements_toggle
        self.on_hotkey_toggle = on_hotkey_toggle
        self.on_history_copy = on_history_copy
        self.on_history_paste = on_history_paste
        self.on_history_clear = on_history_clear
        self.on_initial_prompt_toggle = on_initial_prompt_toggle
        self.on_initial_prompt_save = on_initial_prompt_save
        self.on_quality_profile_change = on_quality_profile_change
        self.on_mixed_language_toggle = on_mixed_language_toggle
        self.on_hotkey_rebind_request = on_hotkey_rebind_request
        self.on_start_with_windows_toggle = on_start_with_windows_toggle
        self.on_start_minimized_toggle = on_start_minimized_toggle
        self.on_perf_profile_change = on_perf_profile_change
        self.on_close_request = on_close_request
        self.on_theme_change = on_theme_change
        self.on_vocab_hotwords_save = on_vocab_hotwords_save
        self.on_vocab_tokens = on_vocab_tokens
        self.on_vocab_list = on_vocab_list
        self.on_vocab_add = on_vocab_add
        self.on_vocab_remove = on_vocab_remove
        self.on_vocab_analyze = on_vocab_analyze
        self.on_vocab_ignore = on_vocab_ignore
        self.on_gpu_pack_install = on_gpu_pack_install
        self.on_input_device_change = on_input_device_change
        self.on_license_activate = on_license_activate
        self.on_license_deactivate = on_license_deactivate
        self._buy_url = buy_url or config.BUY_URL
        self._last_license: dict | None = None
        self._gpu_pack_btn_text: str | None = None

        # Guard para evitar disparar on_model_change cuando lo cambiamos por código.
        self._suppress_model_change = False
        self._initial = initial_settings or {}
        self._hotkey_label = (hotkey_label or config.DEFAULT_HOTKEY)
        self._history_data: list = []

        # Paleta elegida por el usuario (settings.ui_theme) ANTES de construir.
        self._theme_key = str(self._initial.get("ui_theme") or themes.DEFAULT_THEME)
        if self._theme_key not in themes.PALETTES:
            self._theme_key = themes.DEFAULT_THEME
        _apply_palette_globals(themes.get_palette(self._theme_key))

        # Estado dinámico que _build() no conoce; se usa para restaurarlo al
        # reconstruir la UI en un cambio de tema.
        self._last_state = "idle"
        self._last_backend = "—"
        self._last_transcription = ""
        self._last_btn_text = "Iniciar grabación"

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Wisip")
        self.root.configure(fg_color=BG_BASE)

        # Tamaño fijo (no maximizable). Respeta la posición guardada si existe.
        fixed_size = "740x900"
        saved = self._initial.get("last_window_geometry") or ""
        m = re.match(r"\d+x\d+(?:\+(-?\d+)\+(-?\d+))?", saved)
        if m and m.group(1) is not None:
            self.root.geometry(f"{fixed_size}+{m.group(1)}+{m.group(2)}")
        else:
            self.root.geometry(fixed_size)
        try:
            self.root.resizable(False, False)
        except Exception:
            pass
        # Quita la barra de título del SO; usamos chrome custom en el header.
        try:
            self.root.overrideredirect(True)
        except Exception:
            pass
        self.root.attributes("-topmost", False)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

        # Icono de la ventana. En Windows, `.ico` nativo es lo más fiable para
        # el icono de título, alt-tab y barra de tareas. Como complemento
        # cargamos también el PNG vía iconphoto para entornos que no honran
        # iconbitmap. Mantenemos la PhotoImage viva como atributo.
        self._icon_photo = None
        if config.ICO_PATH.exists():
            try:
                self.root.iconbitmap(default=str(config.ICO_PATH))
            except Exception:
                try:
                    self.root.iconbitmap(str(config.ICO_PATH))
                except Exception:
                    pass
        if _HAS_PIL and config.ICON_PATH.exists():
            try:
                icon_img = Image.open(config.ICON_PATH)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self.root.iconphoto(True, self._icon_photo)
            except Exception:
                self._icon_photo = None

        # Permite minimizar/restaurar correctamente con overrideredirect.
        self.root.bind("<Map>", self._on_root_map)
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        # Fuerza entrada en la barra de tareas pese a overrideredirect.
        # En Windows, las ventanas con WS_POPUP no aparecen en taskbar; setear
        # WS_EX_APPWINDOW (y quitar WS_EX_TOOLWINDOW) las restaura ahí. Se
        # programa con un pequeño delay para que el HWND ya exista.
        self.root.after(50, self._force_taskbar_entry)
        # Esquinas redondeadas reales (Windows 10 no las da a ventanas
        # overrideredirect). Después del taskbar-fix, que hace withdraw/deiconify.
        self.root.after(150, self._apply_rounded_corners)

        # Fuentes (tras crear root).
        self._font_ui = _pick_font("Inter", "Segoe UI")
        self._font_mono = _pick_font("JetBrains Mono", "Consolas")

        self._ui_queue: queue.Queue = queue.Queue()
        self._build()
        self.root.after(100, self._drain_queue)

    # ---------- helpers de estilo ----------
    def _fnt(self, size, bold=False):
        return (self._font_ui, size, "bold" if bold else "normal")

    def _fnt_mono(self, size):
        return (self._font_mono, size)

    # ---------- handlers de cierre y chrome custom ----------
    def _handle_close(self):
        try:
            self.on_close_request()
        except Exception:
            try:
                self.root.destroy()
            except Exception:
                pass

    def _chrome_close_clicked(self):
        # Mismo flujo que el botón X del SO: delega en el callback.
        self._handle_close()

    def _chrome_minimize_clicked(self):
        # Sin barra del SO no hay entrada de taskbar, así que "minimizar" oculta
        # la ventana al tray. El ícono del tray la restaura (click izquierdo
        # o "Mostrar" en el menú contextual).
        try:
            self._hide_to_tray()
        except Exception:
            pass

    def _on_root_map(self, _event):
        # Cuando la ventana se restaura del minimizado, reaplicamos chrome custom.
        try:
            if not self.root.overrideredirect():
                self.root.overrideredirect(True)
        except Exception:
            pass
        # La región puede perderse si Tk recrea el HWND al restaurar.
        try:
            self.root.after(30, self._apply_rounded_corners)
        except Exception:
            pass

    def _apply_rounded_corners(self, radius: int = 16):
        """Recorta la ventana a un rectángulo de esquinas redondeadas vía
        SetWindowRgn (GDI). Windows 10 no redondea ventanas overrideredirect
        por sí solo; con la región el recorte es real (clic incluido). El
        sistema toma posesión del HRGN: no hay que liberarlo."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hwnd = user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            self.root.update_idletasks()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            if w <= 1 or h <= 1:
                return
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius * 2, radius * 2)
            user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _force_taskbar_entry(self):
        """Fuerza WS_EX_APPWINDOW en Windows para que la ventana aparezca en
        la barra de tareas aun con overrideredirect(True). Sin esto la
        ventana es WS_POPUP y Windows la oculta de la taskbar."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            hwnd = user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()

            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080

            # Versión 64-bit safe.
            try:
                GetWLP = user32.GetWindowLongPtrW
                SetWLP = user32.SetWindowLongPtrW
                GetWLP.restype = ctypes.c_ssize_t
                GetWLP.argtypes = [wintypes.HWND, ctypes.c_int]
                SetWLP.restype = ctypes.c_ssize_t
                SetWLP.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            except AttributeError:
                GetWLP = user32.GetWindowLongW
                SetWLP = user32.SetWindowLongW

            style = GetWLP(hwnd, GWL_EXSTYLE)
            new_style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if new_style != style:
                SetWLP(hwnd, GWL_EXSTYLE, new_style)
                # Ocultar/mostrar fuerza a Windows a re-evaluar la presencia
                # en taskbar con el nuevo estilo.
                self.root.withdraw()
                self.root.after(20, self.root.deiconify)
        except Exception:
            pass

    # ---------- arrastrar ventana desde el header ----------
    def _start_drag(self, event):
        try:
            self._drag_offset_x = event.x_root - self.root.winfo_x()
            self._drag_offset_y = event.y_root - self.root.winfo_y()
        except Exception:
            self._drag_offset_x = 0
            self._drag_offset_y = 0

    def _do_drag(self, event):
        try:
            x = event.x_root - self._drag_offset_x
            y = event.y_root - self._drag_offset_y
            self.root.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ---------- construcción ----------
    def _build(self):
        # Header fijo arriba (chrome custom: sin barra de título del SO).
        header = ctk.CTkFrame(self.root, fg_color=BG_SURFACE, corner_radius=0, height=92)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Permite arrastrar la ventana desde el header.
        header.bind("<Button-1>", self._start_drag)
        header.bind("<B1-Motion>", self._do_drag)

        # Fila superior: solo los botones de chrome (esquina superior derecha).
        chrome_row = ctk.CTkFrame(header, fg_color="transparent", height=24)
        chrome_row.pack(fill="x", padx=10, pady=(4, 0))
        chrome_row.pack_propagate(False)
        chrome_row.bind("<Button-1>", self._start_drag)
        chrome_row.bind("<B1-Motion>", self._do_drag)

        # Botón cerrar (✕) — primero a la derecha.
        self.close_btn = ctk.CTkButton(
            chrome_row, text="✕", width=28, height=22, corner_radius=4,
            fg_color=BG_SURFACE_HIGH, hover_color=ERROR_CONTAINER,
            text_color=TEXT_VARIANT, font=self._fnt_mono(12),
            border_color=BORDER, border_width=1,
            command=self._chrome_close_clicked,
        )
        self.close_btn.pack(side="right", padx=(4, 0))

        # Botón minimizar (—).
        self.min_btn = ctk.CTkButton(
            chrome_row, text="—", width=28, height=22, corner_radius=4,
            fg_color=BG_SURFACE_HIGH, hover_color=ACCENT_CONTAINER,
            text_color=TEXT_VARIANT, font=self._fnt_mono(12),
            border_color=BORDER, border_width=1,
            command=self._chrome_minimize_clicked,
        )
        self.min_btn.pack(side="right", padx=(0, 0))

        # Fila inferior: logo a la izquierda + estado a la derecha.
        # pady=(0, 6) deja al logo respirar arriba y lo deja centrado entre
        # la fila de chrome y el borde inferior del header.
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        title_row.bind("<Button-1>", self._start_drag)
        title_row.bind("<B1-Motion>", self._do_drag)

        # Logo (centrado verticalmente, escala manteniendo aspecto).
        self._logo_image = None
        logo_widget = None
        if _HAS_PIL and config.LOGO_PATH.exists():
            try:
                img = Image.open(config.LOGO_PATH)
                # Logo rectangular: alto 52px, ancho proporcional, máximo 260px.
                target_h = 52
                w, h = img.size
                target_w = max(1, int(round(w * (target_h / h))))
                max_w = 260
                if target_w > max_w:
                    target_w = max_w
                    target_h = max(1, int(round(h * (target_w / w))))
                self._logo_image = ctk.CTkImage(
                    light_image=img, dark_image=img,
                    size=(target_w, target_h),
                )
                logo_widget = ctk.CTkLabel(
                    title_row, text="", image=self._logo_image,
                )
            except Exception:
                logo_widget = None
        if logo_widget is None:
            logo_widget = ctk.CTkLabel(
                title_row, text="Wisip",
                font=self._fnt(22, bold=True), text_color=PRIMARY,
            )
        logo_widget.pack(side="left", anchor="center")
        logo_widget.bind("<Button-1>", self._start_drag)
        logo_widget.bind("<B1-Motion>", self._do_drag)

        # Estado a la derecha (dot + texto).
        status_row = ctk.CTkFrame(title_row, fg_color="transparent")
        status_row.pack(side="right", anchor="center")
        status_row.bind("<Button-1>", self._start_drag)
        status_row.bind("<B1-Motion>", self._do_drag)
        self.status_dot = ctk.CTkLabel(
            status_row, text="●", font=self._fnt(13, bold=True),
            text_color=TEXT_VARIANT, width=16,
        )
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_label = ctk.CTkLabel(
            status_row,
            text=f"ESTADO: {self.STATE_LABELS['idle']}",
            font=self._fnt(11, bold=True), text_color=TEXT_VARIANT,
        )
        self.status_label.pack(side="left")

        # Línea separadora.
        sep = ctk.CTkFrame(self.root, fg_color=BORDER, height=1, corner_radius=0)
        sep.pack(fill="x", side="top")

        # Tabs.
        self.tabs = ctk.CTkTabview(
            self.root,
            fg_color=BG_BASE,
            segmented_button_fg_color=BG_SURFACE,
            # Tab activo en ACCENT_CONTAINER (acento oscuro), NUNCA el acento
            # brillante: CTkTabview comparte text_color entre tabs y el texto
            # claro desaparecía sobre lima/naranja ("Transcribe no se ve").
            segmented_button_selected_color=ACCENT_CONTAINER,
            segmented_button_selected_hover_color=ACCENT_CONTAINER_HOVER,
            segmented_button_unselected_color=BG_SURFACE_LOW,
            segmented_button_unselected_hover_color=BG_SURFACE_HIGH,
            text_color=TEXT,
            corner_radius=6,
        )
        self.tabs.pack(fill="both", expand=True, padx=12, pady=12)
        self.tabs.add("Transcribe")
        self.tabs.add("Vocabulario")
        self.tabs.add("Historial")
        self.tabs.add("Licencia")

        self._build_transcribe_tab(self.tabs.tab("Transcribe"))
        self._build_vocab_tab(self.tabs.tab("Vocabulario"))
        self._build_history_tab(self.tabs.tab("Historial"))
        self._build_license_tab(self.tabs.tab("Licencia"))

    # ---------- Tab: Transcribe ----------
    def _build_transcribe_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color=BG_BASE)
        scroll.pack(fill="both", expand=True)

        # Card del hint del hotkey.
        hint = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        hint.pack(fill="x", padx=4, pady=(2, 12))
        hint_inner = ctk.CTkFrame(hint, fg_color="transparent")
        hint_inner.pack(fill="x", padx=14, pady=10)

        left_block = ctk.CTkFrame(hint_inner, fg_color="transparent")
        left_block.pack(side="left", fill="x", expand=True)
        self.hotkey_main_label = ctk.CTkLabel(
            left_block,
            text=f"Mantén {pretty_hotkey(self._hotkey_label)} para grabar",
            font=self._fnt(15, bold=True), text_color=TEXT, anchor="w",
        )
        self.hotkey_main_label.pack(anchor="w")
        self.hotkey_label_widget = ctk.CTkLabel(
            left_block,
            text="Suéltalo para transcribir y pegar  ·  Click 👆 para cambiar la tecla",
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w",
        )
        self.hotkey_label_widget.pack(anchor="w")

        # Botón "👆" clickable para reasignar el hotkey.
        self.rebind_btn = ctk.CTkButton(
            hint_inner, text="👆",
            command=self._on_rebind_clicked,
            fg_color="transparent", hover_color=BG_SURFACE_HIGH,
            text_color=PRIMARY,
            font=self._fnt(22),
            width=48, height=48,
            corner_radius=24,
        )
        self.rebind_btn.pack(side="right", padx=(8, 0))

        # Cómo funciona (3 pasos; para quien abre la app por primera vez).
        how = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        how.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(
            how, text="CÓMO FUNCIONA",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT, anchor="w",
        ).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(
            how,
            text=("1. Pon el cursor donde quieras escribir (chat, correo, editor).\n"
                  "2. Mantén la tecla de dictado y habla con normalidad.\n"
                  "3. Suéltala: el texto se escribe ahí mismo. Todo ocurre en tu PC, sin internet."),
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w", justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # Grid de configuración.
        cfg = ctk.CTkFrame(scroll, fg_color="transparent")
        cfg.pack(fill="x", padx=4, pady=(0, 12))
        cfg.grid_columnconfigure(0, weight=1, uniform="cfg")
        cfg.grid_columnconfigure(1, weight=1, uniform="cfg")

        # Idioma + Modo.
        self._labeled_dropdown(
            cfg, "IDIOMA", row=0, col=0,
            values=config.LANGUAGE_LABELS,
            initial=config.LANGUAGE_CODE_TO_LABEL.get(
                self._resolved_language_code(), config.LANGUAGE_LABEL_ES
            ),
            command=self._language_changed,
            attr_name="language_menu",
        )
        self._labeled_dropdown(
            cfg, "MODO", row=0, col=1,
            values=config.PASTE_MODES,
            initial=self._initial.get("paste_mode", config.PASTE_MODE_PASTE),
            command=self._paste_mode_changed,
            attr_name="paste_mode_menu",
        )

        # Perfil + descripción.
        profile_initial_key = self._resolved_profile_key()
        self._labeled_dropdown(
            cfg, "PERFIL", row=1, col=0, colspan=2,
            values=[config.QUALITY_PROFILE_LABELS[k] for k in config.QUALITY_PROFILE_KEYS],
            initial=config.QUALITY_PROFILE_LABELS[profile_initial_key],
            command=self._profile_changed,
            attr_name="profile_menu",
        )
        self.profile_desc_label = ctk.CTkLabel(
            cfg,
            text=config.QUALITY_PROFILE_DESCRIPTIONS.get(profile_initial_key, ""),
            font=self._fnt_mono(11), text_color=TEXT_MUTED, anchor="w",
        )
        self.profile_desc_label.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 6)
        )

        # Modelo + hint.
        model_initial = self._initial.get("model", config.DEFAULT_MODEL)
        self._labeled_dropdown(
            cfg, "MODELO", row=3, col=0, colspan=2,
            values=config.AVAILABLE_MODELS,
            initial=model_initial,
            command=self._model_changed,
            attr_name="model_menu",
        )
        self.model_hint_label = ctk.CTkLabel(
            cfg, text=self._model_hint_text(model_initial),
            font=self._fnt_mono(11), text_color=TEXT_MUTED, anchor="w",
        )
        self.model_hint_label.grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 0)
        )

        # Perfil de RENDIMIENTO (device/compute/batching). Distinto del de calidad.
        perf_key = self._resolved_perf_key()
        self._labeled_dropdown(
            cfg, "RENDIMIENTO", row=5, col=0, colspan=2,
            values=[config.PERF_PROFILE_LABELS[k] for k in config.PERF_PROFILE_KEYS],
            initial=config.PERF_PROFILE_LABELS[perf_key],
            command=self._perf_profile_changed,
            attr_name="perf_menu",
        )
        self.perf_desc_label = ctk.CTkLabel(
            cfg, text=config.PERF_PROFILE_DESCRIPTIONS.get(perf_key, ""),
            font=self._fnt_mono(11), text_color=TEXT_MUTED, anchor="w",
        )
        self.perf_desc_label.grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=4, pady=(2, 0)
        )
        self.backend_label = ctk.CTkLabel(
            cfg, text="Backend: —",
            font=self._fnt_mono(11), text_color=SECONDARY, anchor="w",
        )
        self.backend_label.grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 2)
        )

        # Botón de descarga del paquete NVIDIA: solo visible cuando hay GPU
        # NVIDIA y faltan las DLLs CUDA (lo decide el Controller).
        self.gpu_pack_btn = ctk.CTkButton(
            cfg, text=self._gpu_pack_btn_text or "", height=30, corner_radius=8,
            fg_color=ACCENT_CONTAINER, hover_color=ACCENT_CONTAINER_HOVER,
            text_color=TEXT, font=self._fnt(12, bold=True),
            command=self._gpu_pack_clicked,
        )
        self.gpu_pack_btn.grid(
            row=8, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 6)
        )
        if not self._gpu_pack_btn_text:
            self.gpu_pack_btn.grid_remove()

        # Tema de color (sistema de paletas; se aplica en vivo y se guarda).
        self._labeled_dropdown(
            cfg, "TEMA", row=9, col=0, colspan=2,
            values=[themes.THEME_LABELS[k] for k in themes.THEME_KEYS],
            initial=themes.THEME_LABELS.get(self._theme_key, ""),
            command=self._theme_changed,
            attr_name="theme_menu",
        )

        # Micrófono (por nombre; vacío = predeterminado del sistema).
        try:
            mic_names = [d["name"] for d in audio_devices.list_input_devices()]
        except Exception:
            mic_names = []
        mic_values = [audio_devices.DEFAULT_LABEL] + mic_names
        mic_initial = audio_devices.device_label(self._initial.get("input_device_name", ""))
        if mic_initial not in mic_values:
            mic_values.append(mic_initial + "  (no conectado)")
            mic_initial = mic_initial + "  (no conectado)"
        self._labeled_dropdown(
            cfg, "MICRÓFONO", row=10, col=0, colspan=2,
            values=mic_values,
            initial=mic_initial,
            command=self._input_device_changed,
            attr_name="mic_menu",
        )

        # Toggles.
        toggles = ctk.CTkFrame(scroll, fg_color="transparent")
        toggles.pack(fill="x", padx=4, pady=(8, 12))
        toggles.grid_columnconfigure(0, weight=1, uniform="t")
        toggles.grid_columnconfigure(1, weight=1, uniform="t")

        self.beep_var = tk.BooleanVar(value=bool(self._initial.get("beep_enabled", True)))
        self._toggle_card(
            toggles, "BEEP AL GRABAR", self.beep_var, self._beep_changed,
            attr_name="beep_chk", row=0, col=0,
        )
        self.replacements_var = tk.BooleanVar(
            value=bool(self._initial.get("replacements_enabled", True))
        )
        self._toggle_card(
            toggles, "REEMPLAZOS", self.replacements_var, self._replacements_changed,
            attr_name="replacements_chk", row=0, col=1,
        )

        # Atajo activo (full-width).
        hk_card = ctk.CTkFrame(
            toggles, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        hk_card.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(
            hk_card, text="ATAJO ACTIVO",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left", padx=12, pady=10)
        self.hotkey_var = tk.BooleanVar(value=bool(self._initial.get("hotkey_enabled", True)))
        self.hotkey_switch = ctk.CTkSwitch(
            hk_card, text="", variable=self.hotkey_var,
            command=self._hotkey_enabled_changed,
            progress_color=PRIMARY_BTN, button_color="#ffffff",
            fg_color=BG_SURFACE_HIGH, border_color=BORDER, width=42,
        )
        self.hotkey_switch.pack(side="right", padx=12, pady=8)

        # Idioma mixto (ES + términos EN). Al activarlo, si el idioma elegido es
        # "es" se fuerza detección automática en faster-whisper para no cortar
        # frases que mezclan español con palabras técnicas en inglés.
        ml_card = ctk.CTkFrame(
            toggles, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        ml_card.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(
            ml_card, text="IDIOMA MIXTO (ES + TÉRMINOS EN)",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left", padx=12, pady=10)
        self.mixed_lang_var = tk.BooleanVar(
            value=bool(self._initial.get("mixed_language_mode", True))
        )
        self.mixed_lang_switch = ctk.CTkSwitch(
            ml_card, text="", variable=self.mixed_lang_var,
            command=self._mixed_lang_changed,
            progress_color=PRIMARY_BTN, button_color="#ffffff",
            fg_color=BG_SURFACE_HIGH, border_color=BORDER, width=42,
        )
        self.mixed_lang_switch.pack(side="right", padx=12, pady=8)

        # Iniciar con Windows (full-width).
        sw_card = ctk.CTkFrame(
            toggles, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        sw_card.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(
            sw_card, text="INICIAR CON WINDOWS",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left", padx=12, pady=10)
        self.start_with_windows_var = tk.BooleanVar(
            value=bool(self._initial.get("start_with_windows", False))
        )
        self.start_with_windows_switch = ctk.CTkSwitch(
            sw_card, text="", variable=self.start_with_windows_var,
            command=self._start_with_windows_changed,
            progress_color=PRIMARY_BTN, button_color="#ffffff",
            fg_color=BG_SURFACE_HIGH, border_color=BORDER, width=42,
        )
        self.start_with_windows_switch.pack(side="right", padx=12, pady=8)

        # Iniciar minimizada al tray (full-width).
        sm_card = ctk.CTkFrame(
            toggles, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        sm_card.grid(row=4, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ctk.CTkLabel(
            sm_card, text="INICIAR MINIMIZADA (AL TRAY)",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left", padx=12, pady=10)
        self.start_minimized_var = tk.BooleanVar(
            value=bool(self._initial.get("start_minimized", False))
        )
        self.start_minimized_switch = ctk.CTkSwitch(
            sm_card, text="", variable=self.start_minimized_var,
            command=self._start_minimized_changed,
            progress_color=PRIMARY_BTN, button_color="#ffffff",
            fg_color=BG_SURFACE_HIGH, border_color=BORDER, width=42,
        )
        self.start_minimized_switch.pack(side="right", padx=12, pady=8)

        # Botón principal.
        self.toggle_btn = ctk.CTkButton(
            scroll,
            text=self._BTN_ICONS["Iniciar grabación"] + "Iniciar grabación",
            command=self._toggle_clicked,
            fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER,
            text_color=PRIMARY_BTN_TEXT,
            font=self._fnt(17, bold=True),
            corner_radius=6, height=64,
        )
        self.toggle_btn.pack(fill="x", padx=4, pady=(4, 12))

        # Ajustes avanzados, plegados: el prompt inicial confunde a quien no
        # sabe qué es Whisper (feedback del usuario, 2026-09-23).
        self._adv_open = False
        self.adv_btn = ctk.CTkButton(
            scroll, text="▸  AJUSTES AVANZADOS (prompt inicial de Whisper)",
            command=self._toggle_advanced, anchor="w",
            fg_color="transparent", hover_color=BG_SURFACE_HIGH,
            text_color=TEXT_MUTED, font=self._fnt(10, bold=True), height=28, corner_radius=4,
        )
        self.adv_btn.pack(fill="x", padx=4, pady=(0, 6))

        # Prompt editor (oculto hasta abrir AVANZADO).
        prompt_card = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        self._prompt_card = prompt_card

        ph = ctk.CTkFrame(prompt_card, fg_color="transparent")
        ph.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            ph, text="PROMPT INICIAL",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left")
        self.initial_prompt_var = tk.BooleanVar(
            value=bool(self._initial.get("initial_prompt_enabled", True))
        )
        self.initial_prompt_chk = ctk.CTkCheckBox(
            ph, text="Activo",
            variable=self.initial_prompt_var,
            command=self._initial_prompt_toggled,
            fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER,
            border_color=BORDER, text_color=TEXT,
            font=self._fnt(10, bold=True),
        )
        self.initial_prompt_chk.pack(side="left", padx=(12, 0))

        ctk.CTkButton(
            ph, text="GUARDAR PROMPT",
            command=self._initial_prompt_save_clicked,
            fg_color="transparent", hover_color=BG_SURFACE_HIGH,
            border_color=SECONDARY, border_width=1, text_color=SECONDARY,
            font=self._fnt(10, bold=True), width=140, height=26,
            corner_radius=4,
        ).pack(side="right")

        self.initial_prompt_box = ctk.CTkTextbox(
            prompt_card, height=80, wrap="word",
            fg_color=BG_INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=self._fnt(12),
        )
        self.initial_prompt_box.pack(fill="x", padx=12, pady=(4, 12))
        self.initial_prompt_box.insert("1.0", self._initial.get("initial_prompt", "") or "")

        # Última transcripción.
        ctk.CTkLabel(
            scroll, text="ÚLTIMA TRANSCRIPCIÓN",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(anchor="w", padx=8, pady=(4, 4))

        self.transcription_box = ctk.CTkTextbox(
            scroll, height=100, wrap="word",
            fg_color=BG_SURFACE_HIGH, text_color=TEXT,
            border_color=PRIMARY_BTN, border_width=1,
            font=self._fnt(13),
        )
        self.transcription_box.pack(fill="x", padx=4, pady=(0, 12))
        self.transcription_box.configure(state="disabled")

    # ---------- Tab: Vocabulario ----------
    # El ciclo de refinado POR USUARIO dentro de la app: hotwords con medidor
    # de tokens, reemplazos personales editables en vivo, y sugerencias minadas
    # del registro de dictados. La lógica vive en app/vocab.py vía callbacks.
    def _build_vocab_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color=BG_BASE)
        scroll.pack(fill="both", expand=True)

        # ── Hotwords ──
        hw_card = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        hw_card.pack(fill="x", padx=4, pady=(2, 12))
        hw_head = ctk.CTkFrame(hw_card, fg_color="transparent")
        hw_head.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            hw_head, text="TUS PALABRAS CLAVE (HOTWORDS)",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left")
        ctk.CTkButton(
            hw_head, text="GUARDAR",
            command=self._vocab_hotwords_save_clicked,
            fg_color="transparent", hover_color=BG_SURFACE_HIGH,
            border_color=SECONDARY, border_width=1, text_color=SECONDARY,
            font=self._fnt(10, bold=True), width=100, height=26,
            corner_radius=4,
        ).pack(side="right")
        ctk.CTkLabel(
            hw_card,
            text="Marcas, proyectos y términos que Whisper debe reconocer. Separa con comas.",
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=12)
        self.hotwords_box = ctk.CTkTextbox(
            hw_card, height=56, wrap="word",
            fg_color=BG_INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=self._fnt(12),
        )
        self.hotwords_box.pack(fill="x", padx=12, pady=(6, 2))
        self.hotwords_box.insert("1.0", self._initial.get("hotwords", "") or "")
        self.hotwords_box.bind("<KeyRelease>", self._vocab_hotwords_typed)
        self.hotwords_meter = ctk.CTkLabel(
            hw_card, text="", font=self._fnt_mono(11),
            text_color=TEXT_MUTED, anchor="w",
        )
        self.hotwords_meter.pack(fill="x", padx=12, pady=(0, 10))
        self._vocab_meter_job = None
        self._vocab_update_meter()

        # ── Reemplazos personales ──
        rep_card = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        rep_card.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(
            rep_card, text="REEMPLAZOS PERSONALES",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT, anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            rep_card,
            text="Corrige lo que Whisper te oye mal. Se aplica al instante, sin reiniciar.",
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=12)

        add_row = ctk.CTkFrame(rep_card, fg_color="transparent")
        add_row.pack(fill="x", padx=12, pady=(8, 2))
        self.vocab_wrong_entry = ctk.CTkEntry(
            add_row, placeholder_text="como lo escribe Wisip",
            fg_color=BG_INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=self._fnt(12), height=30,
        )
        self.vocab_wrong_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            add_row, text="→", font=self._fnt(13, bold=True),
            text_color=TEXT_VARIANT, width=26,
        ).pack(side="left")
        self.vocab_right_entry = ctk.CTkEntry(
            add_row, placeholder_text="como debe quedar",
            fg_color=BG_INPUT, text_color=TEXT,
            border_color=BORDER, border_width=1,
            font=self._fnt(12), height=30,
        )
        self.vocab_right_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            add_row, text="AGREGAR",
            command=self._vocab_add_clicked,
            fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER,
            text_color=PRIMARY_BTN_TEXT,
            font=self._fnt(10, bold=True), width=90, height=30,
            corner_radius=4,
        ).pack(side="left", padx=(8, 0))

        self.vocab_msg = ctk.CTkLabel(
            rep_card, text="", font=self._fnt(11),
            text_color=SECONDARY, anchor="w",
        )
        self.vocab_msg.pack(fill="x", padx=12)

        self.vocab_list_frame = ctk.CTkScrollableFrame(
            rep_card, fg_color=BG_INPUT, height=170,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        self.vocab_list_frame.pack(fill="x", padx=12, pady=(4, 12))
        self._vocab_render_list()

        # ── Sugerencias del registro ──
        sug_card = ctk.CTkFrame(
            scroll, fg_color=BG_SURFACE,
            border_color=BORDER, border_width=1, corner_radius=6,
        )
        sug_card.pack(fill="x", padx=4, pady=(0, 12))
        sug_head = ctk.CTkFrame(sug_card, fg_color="transparent")
        sug_head.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            sug_head, text="SUGERENCIAS DE TUS DICTADOS",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left")
        self.vocab_analyze_btn = ctk.CTkButton(
            sug_head, text="ANALIZAR MIS DICTADOS",
            command=self._vocab_analyze_clicked,
            fg_color="transparent", hover_color=BG_SURFACE_HIGH,
            border_color=SECONDARY, border_width=1, text_color=SECONDARY,
            font=self._fnt(10, bold=True), width=170, height=26,
            corner_radius=4,
        )
        self.vocab_analyze_btn.pack(side="right")
        ctk.CTkLabel(
            sug_card,
            text="Busca palabras raras que se repiten en tus últimos 30 días de dictado.\n"
                 "Tú decides: escribe la corrección, o ignórala si es vocabulario tuyo.",
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w", justify="left",
        ).pack(fill="x", padx=12)
        self.vocab_sug_status = ctk.CTkLabel(
            sug_card, text="", font=self._fnt_mono(11),
            text_color=TEXT_MUTED, anchor="w",
        )
        self.vocab_sug_status.pack(fill="x", padx=12, pady=(2, 0))
        self.vocab_sug_frame = ctk.CTkScrollableFrame(
            sug_card, fg_color=BG_INPUT, height=230,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        self.vocab_sug_frame.pack(fill="x", padx=12, pady=(4, 12))

    # ---- Vocabulario: callbacks (Tk thread) ----
    def _vocab_hotwords_text(self) -> str:
        try:
            raw = self.hotwords_box.get("1.0", "end")
        except Exception:
            raw = ""
        return " ".join(raw.split())

    def _vocab_hotwords_typed(self, _event=None):
        # Debounce: recalcular tokens 300ms después de la última tecla.
        if self._vocab_meter_job is not None:
            try:
                self.root.after_cancel(self._vocab_meter_job)
            except Exception:
                pass
        self._vocab_meter_job = self.root.after(300, self._vocab_update_meter)

    def _vocab_update_meter(self):
        self._vocab_meter_job = None
        if not self.on_vocab_tokens:
            return
        try:
            label, over = self.on_vocab_tokens(self._vocab_hotwords_text())
            extra = "  ¡TE PASASTE! Whisper recorta y el dictado se degrada." if over else ""
            self.hotwords_meter.configure(
                text=label + extra, text_color=(ERROR if over else TEXT_MUTED)
            )
        except Exception:
            pass

    def _vocab_hotwords_save_clicked(self):
        if not self.on_vocab_hotwords_save:
            return
        self.on_vocab_hotwords_save(self._vocab_hotwords_text())
        self._vocab_update_meter()
        self._vocab_flash("Hotwords guardados ✓")

    def _vocab_flash(self, text, error=False):
        try:
            self.vocab_msg.configure(
                text=text, text_color=(ERROR if error else SECONDARY)
            )
            self.root.after(4000, lambda: self.vocab_msg.configure(text=""))
        except Exception:
            pass

    def _vocab_render_list(self):
        for child in self.vocab_list_frame.winfo_children():
            child.destroy()
        pairs = []
        if self.on_vocab_list:
            try:
                pairs = self.on_vocab_list()
            except Exception:
                pairs = []
        for wrong, right in pairs:
            row = ctk.CTkFrame(self.vocab_list_frame, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=1)
            ctk.CTkButton(
                row, text="✕",
                command=lambda w=wrong: self._vocab_remove_clicked(w),
                fg_color="transparent", hover_color=BG_SURFACE_HIGH,
                text_color=ERROR, font=self._fnt(11, bold=True),
                width=26, height=22, corner_radius=4,
            ).pack(side="right")
            ctk.CTkLabel(
                row, text=f"{wrong}  →  {right}",
                font=self._fnt(12), text_color=TEXT, anchor="w",
            ).pack(side="left", fill="x", expand=True)

    def _vocab_add_clicked(self):
        if not self.on_vocab_add:
            return
        wrong = self.vocab_wrong_entry.get()
        right = self.vocab_right_entry.get()
        err = self.on_vocab_add(wrong, right)
        if err:
            self._vocab_flash(err, error=True)
            return
        self.vocab_wrong_entry.delete(0, "end")
        self.vocab_right_entry.delete(0, "end")
        self._vocab_render_list()
        self._vocab_flash(f"Listo: «{wrong.strip()}» se corregirá a «{right.strip()}» ✓")

    def _vocab_remove_clicked(self, wrong):
        if self.on_vocab_remove and self.on_vocab_remove(wrong):
            self._vocab_render_list()
            self._vocab_flash(f"Reemplazo «{wrong}» eliminado.")

    def _vocab_analyze_clicked(self):
        if not self.on_vocab_analyze:
            return
        self.vocab_analyze_btn.configure(state="disabled")
        self.vocab_sug_status.configure(text="Analizando tus dictados…")

        def worker():
            try:
                results = self.on_vocab_analyze()
            except Exception as e:
                results = e
            self.root.after(0, lambda: self._vocab_render_suggestions(results))

        threading.Thread(target=worker, daemon=True).start()

    def _vocab_render_suggestions(self, results):
        self.vocab_analyze_btn.configure(state="normal")
        for child in self.vocab_sug_frame.winfo_children():
            child.destroy()
        if isinstance(results, Exception):
            self.vocab_sug_status.configure(text=f"Error al analizar: {results}")
            return
        if not results:
            self.vocab_sug_status.configure(
                text="Sin candidatas nuevas: tu vocabulario está al día ✓"
            )
            return
        n = len(results)
        plural = "s" if n != 1 else ""
        self.vocab_sug_status.configure(
            text=f"{n} palabra{plural} recurrente{plural} que no reconozco — revísala{plural}:"
        )
        for item in results:
            word, count = item["word"], item["count"]
            card = ctk.CTkFrame(
                self.vocab_sug_frame, fg_color=BG_SURFACE_LOW,
                border_color=BORDER, border_width=1, corner_radius=4,
            )
            card.pack(fill="x", padx=4, pady=3)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=8, pady=(6, 0))
            ctk.CTkLabel(
                top, text=word, font=self._fnt(13, bold=True),
                text_color=TEXT, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                top, text=f"  {count} veces", font=self._fnt_mono(11),
                text_color=TEXT_VARIANT, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                card, text=item.get("context", ""),
                font=self._fnt(11), text_color=TEXT_MUTED,
                anchor="w", wraplength=560, justify="left",
            ).pack(fill="x", padx=8)
            act = ctk.CTkFrame(card, fg_color="transparent")
            act.pack(fill="x", padx=8, pady=(2, 6))
            fix_entry = ctk.CTkEntry(
                act, placeholder_text="corrección…",
                fg_color=BG_INPUT, text_color=TEXT,
                border_color=BORDER, border_width=1,
                font=self._fnt(12), height=26,
            )
            fix_entry.pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                act, text="CORREGIR",
                command=lambda w=word, e=fix_entry, c=card: self._vocab_fix_suggestion(w, e, c),
                fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER,
                text_color=PRIMARY_BTN_TEXT, font=self._fnt(10, bold=True),
                width=86, height=26, corner_radius=4,
            ).pack(side="left", padx=(8, 0))
            ctk.CTkButton(
                act, text="IGNORAR",
                command=lambda w=word, c=card: self._vocab_ignore_suggestion(w, c),
                fg_color="transparent", hover_color=BG_SURFACE_HIGH,
                border_color=BORDER, border_width=1, text_color=TEXT_MUTED,
                font=self._fnt(10, bold=True), width=80, height=26,
                corner_radius=4,
            ).pack(side="left", padx=(6, 0))

    def _vocab_fix_suggestion(self, word, entry, card):
        if not self.on_vocab_add:
            return
        right = entry.get()
        err = self.on_vocab_add(word, right)
        if err:
            self._vocab_flash(err, error=True)
            return
        card.destroy()
        self._vocab_render_list()
        self._vocab_flash(f"Listo: «{word}» se corregirá a «{right.strip()}» ✓")

    def _vocab_ignore_suggestion(self, word, card):
        if self.on_vocab_ignore:
            try:
                self.on_vocab_ignore(word)
            except Exception:
                pass
        card.destroy()

    # ---------- Tab: Historial ----------
    def _build_history_tab(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(
            header, text="HISTORIAL (ÚLTIMAS 10)",
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(side="left")

        btns = ctk.CTkFrame(header, fg_color="transparent")
        btns.pack(side="right")
        for label, cmd, color in [
            ("COPIAR", self._history_copy_clicked, TEXT),
            ("PEGAR", self._history_paste_clicked, TEXT),
            ("LIMPIAR", self._history_clear_clicked, ERROR),
        ]:
            ctk.CTkButton(
                btns, text=label, command=cmd,
                fg_color=BG_SURFACE_LOW, hover_color=BG_SURFACE_HIGHEST,
                border_color=BORDER, border_width=1,
                text_color=color, font=self._fnt(10, bold=True),
                width=80, height=28, corner_radius=4,
            ).pack(side="left", padx=4)

        list_frame = ctk.CTkFrame(
            parent, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.history_listbox = tk.Listbox(
            list_frame,
            bg=BG_INPUT, fg=TEXT,
            selectbackground=PRIMARY_BTN, selectforeground=PRIMARY_BTN_TEXT,
            relief="flat", highlightthickness=0,
            activestyle="none",
            font=(self._font_ui, 11),
        )
        self.history_listbox.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------- Tab: Licencia ----------
    def _build_license_tab(self, parent):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        card = ctk.CTkFrame(wrap, fg_color=BG_SURFACE, border_color=BORDER,
                            border_width=1, corner_radius=6)
        card.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        self.license_state_label = ctk.CTkLabel(
            inner, text="LICENCIA", font=self._fnt(15, bold=True), text_color=TEXT, anchor="w",
        )
        self.license_state_label.pack(anchor="w")
        self.license_msg_label = ctk.CTkLabel(
            inner, text="", font=self._fnt(11), text_color=TEXT_MUTED, anchor="w",
            justify="left", wraplength=620,
        )
        self.license_msg_label.pack(anchor="w", pady=(2, 0))
        self.license_detail_label = ctk.CTkLabel(
            inner, text="", font=self._fnt_mono(11), text_color=TEXT_VARIANT, anchor="w",
            justify="left",
        )
        self.license_detail_label.pack(anchor="w", pady=(6, 0))

        ctk.CTkLabel(
            wrap, text="CLAVE DE LICENCIA", font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(anchor="w", pady=(0, 4))
        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x")
        self.license_entry = ctk.CTkEntry(
            row, placeholder_text="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
            fg_color=BG_INPUT, border_color=BORDER, text_color=TEXT,
            font=self._fnt_mono(12), height=34, corner_radius=4,
        )
        self.license_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.license_activate_btn = ctk.CTkButton(
            row, text="ACTIVAR", command=self._license_activate_clicked,
            fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER, text_color=PRIMARY_BTN_TEXT,
            font=self._fnt(11, bold=True), width=110, height=34, corner_radius=4,
        )
        self.license_activate_btn.pack(side="left")
        self.license_result_label = ctk.CTkLabel(
            wrap, text="", font=self._fnt(11), text_color=TEXT_MUTED, anchor="w",
            justify="left", wraplength=620,
        )
        self.license_result_label.pack(anchor="w", pady=(6, 12))

        btns = ctk.CTkFrame(wrap, fg_color="transparent")
        btns.pack(fill="x")
        self.license_buy_btn = ctk.CTkButton(
            btns, text="COMPRAR LICENCIA DE POR VIDA", command=self._license_buy_clicked,
            fg_color=ACCENT_CONTAINER, hover_color=ACCENT_CONTAINER_HOVER, text_color=TEXT,
            font=self._fnt(11, bold=True), height=32, corner_radius=4,
        )
        self.license_buy_btn.pack(side="left", padx=(0, 8))
        self.license_deactivate_btn = ctk.CTkButton(
            btns, text="DESACTIVAR EN ESTE EQUIPO", command=self._license_deactivate_clicked,
            fg_color=BG_SURFACE_LOW, hover_color=BG_SURFACE_HIGHEST, border_color=BORDER,
            border_width=1, text_color=ERROR, font=self._fnt(11, bold=True), height=32, corner_radius=4,
        )
        self.license_deactivate_btn.pack(side="left")
        ctk.CTkLabel(
            wrap, text="Una licencia vale para un equipo a la vez. Para pasarla a otro PC, "
                       "desactívala aquí (o desinstala Wisip) y actívala en el nuevo.",
            font=self._fnt(11), text_color=TEXT_MUTED, anchor="w", justify="left", wraplength=620,
        ).pack(anchor="w", pady=(12, 0))
        if self._last_license:
            self._apply_license_status(self._last_license)

    def _license_activate_clicked(self):
        key = (self.license_entry.get() or "").strip()
        self.license_result_label.configure(text="Activando…", text_color=TEXT_MUTED)
        self.license_activate_btn.configure(state="disabled")
        if self.on_license_activate:
            self.on_license_activate(key)

    def _license_deactivate_clicked(self):
        self.license_result_label.configure(text="Desactivando…", text_color=TEXT_MUTED)
        if self.on_license_deactivate:
            self.on_license_deactivate()

    def _license_buy_clicked(self):
        try:
            import webbrowser
            webbrowser.open(self._buy_url)
        except Exception:
            pass

    def _apply_license_status(self, st: dict):
        state = st.get("state", "")
        titles = {
            "licensed": ("LICENCIA ACTIVA", PRIMARY),
            "trial": (f"PRUEBA GRATUITA · {st.get('days_left', 0)} DÍAS RESTANTES", SECONDARY),
            "trial_expired": ("PRUEBA TERMINADA", ERROR),
            "invalid": ("LICENCIA NO VÁLIDA", ERROR),
        }
        title, color = titles.get(state, ("LICENCIA", TEXT))
        try:
            self.license_state_label.configure(text=title, text_color=color)
            self.license_msg_label.configure(text=st.get("message", ""))
            detail = f"Equipo: {st.get('instance', '')}"
            if st.get("key_masked"):
                detail += f"\nClave: {st.get('key_masked')}"
            if st.get("email"):
                detail += f"\nComprada por: {st.get('email')}"
            self.license_detail_label.configure(text=detail)
            licensed = state == "licensed"
            if licensed:
                self.license_deactivate_btn.pack(side="left")
            else:
                self.license_deactivate_btn.pack_forget()
        except Exception:
            pass

    def set_license_status(self, st: dict):
        self._ui_queue.put(("license_status", dict(st or {})))

    def set_license_result(self, text: str, error: bool = False):
        self._ui_queue.put(("license_result", (text, bool(error))))

    # ---------- helpers de construcción ----------
    def _labeled_dropdown(self, parent, label_text, *, row, col, colspan=1,
                          values, initial, command, attr_name):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=row, column=col, columnspan=colspan,
                  sticky="ew", padx=4, pady=(4, 4))
        ctk.CTkLabel(
            cell, text=label_text,
            font=self._fnt(10, bold=True), text_color=TEXT_VARIANT,
        ).pack(anchor="w", pady=(0, 4))
        menu = ctk.CTkOptionMenu(
            cell, values=list(values), command=command,
            fg_color=BG_INPUT, button_color=BG_SURFACE_HIGH,
            button_hover_color=BG_SURFACE_HIGHEST,
            text_color=TEXT,
            dropdown_fg_color=BG_SURFACE_HIGH,
            dropdown_hover_color=ACCENT_CONTAINER,
            dropdown_text_color=TEXT,
            corner_radius=4,
            font=self._fnt(12),
        )
        menu.set(initial)
        menu.pack(fill="x")
        setattr(self, attr_name, menu)

    def _toggle_card(self, parent, label_text, var, cmd, *, attr_name, row, col):
        card = ctk.CTkFrame(
            parent, fg_color=BG_SURFACE_LOW,
            border_color=BORDER, border_width=1, corner_radius=4,
        )
        card.grid(row=row, column=col, sticky="ew", padx=4, pady=4)
        chk = ctk.CTkCheckBox(
            card, text=label_text, variable=var, command=cmd,
            fg_color=PRIMARY_BTN, hover_color=PRIMARY_BTN_HOVER,
            border_color=BORDER, text_color=TEXT,
            font=self._fnt(10, bold=True),
        )
        chk.pack(fill="x", padx=10, pady=10)
        setattr(self, attr_name, chk)

    def _resolved_language_code(self):
        c = self._initial.get("language", config.LANGUAGE)
        return c if c in config.LANGUAGE_CODES else config.LANGUAGE

    def _resolved_profile_key(self):
        k = self._initial.get("quality_profile", config.DEFAULT_QUALITY_PROFILE)
        return k if k in config.QUALITY_PROFILE_KEYS else config.DEFAULT_QUALITY_PROFILE

    def _resolved_perf_key(self):
        k = self._initial.get("performance_profile", config.DEFAULT_PERF_PROFILE)
        return k if k in config.PERF_PROFILE_KEYS else config.DEFAULT_PERF_PROFILE

    # ---- Widget callbacks (Tk thread) ----
    def _model_changed(self, value):
        try:
            self.model_hint_label.configure(text=self._model_hint_text(value))
        except Exception:
            pass
        if self._suppress_model_change:
            return
        self.on_model_change(value)

    def _profile_changed(self, label):
        key = config.QUALITY_PROFILE_LABEL_TO_KEY.get(label)
        if not key or key == config.QUALITY_PROFILE_CUSTOM:
            try:
                self.profile_desc_label.configure(
                    text=config.QUALITY_PROFILE_DESCRIPTIONS.get(
                        config.QUALITY_PROFILE_CUSTOM, ""
                    )
                )
            except Exception:
                pass
            return
        try:
            self.profile_desc_label.configure(
                text=config.QUALITY_PROFILE_DESCRIPTIONS.get(key, "")
            )
        except Exception:
            pass
        self.on_quality_profile_change(key)

    def _language_changed(self, label):
        code = config.LANGUAGE_LABEL_TO_CODE.get(label, config.LANGUAGE)
        self.on_language_change(code)

    def _initial_prompt_toggled(self):
        self.on_initial_prompt_toggle(bool(self.initial_prompt_var.get()))

    def _initial_prompt_save_clicked(self):
        try:
            text = self.initial_prompt_box.get("1.0", "end").strip()
        except Exception:
            text = ""
        self.on_initial_prompt_save(text)

    def _model_hint_text(self, model_name: str) -> str:
        hint = config.MODEL_HINTS.get(model_name, "")
        return f"Recomendación: {model_name} — {hint}" if hint else ""

    def _toggle_clicked(self):
        self.on_toggle_button()

    def _paste_mode_changed(self, value):
        self.on_paste_mode_change(value)

    def _beep_changed(self):
        self.on_beep_toggle(bool(self.beep_var.get()))

    def _replacements_changed(self):
        self.on_replacements_toggle(bool(self.replacements_var.get()))

    def _hotkey_enabled_changed(self):
        self.on_hotkey_toggle(bool(self.hotkey_var.get()))

    def _mixed_lang_changed(self):
        self.on_mixed_language_toggle(bool(self.mixed_lang_var.get()))

    def _perf_profile_changed(self, label):
        key = config.PERF_PROFILE_LABEL_TO_KEY.get(label)
        if not key:
            return
        try:
            self.perf_desc_label.configure(
                text=config.PERF_PROFILE_DESCRIPTIONS.get(key, "")
            )
        except Exception:
            pass
        self.on_perf_profile_change(key)

    def _start_with_windows_changed(self):
        self.on_start_with_windows_toggle(bool(self.start_with_windows_var.get()))

    def _start_minimized_changed(self):
        self.on_start_minimized_toggle(bool(self.start_minimized_var.get()))

    def _on_rebind_clicked(self):
        self.on_hotkey_rebind_request()

    # ---- cambio de tema (en vivo) ----
    def _state_colors(self):
        # Se calcula al vuelo (no como atributo de clase) para que siempre
        # refleje la paleta activa.
        return {
            "idle": TEXT_VARIANT,
            "recording": PRIMARY_BTN,
            "transcribing": WARN,
            "processing": WARN,
            "pasting": SECONDARY,
            "loading": SECONDARY,
            "error": ERROR,
        }

    def _toggle_advanced(self):
        self._adv_open = not self._adv_open
        try:
            if self._adv_open:
                self._prompt_card.pack(fill="x", padx=4, pady=(0, 12), after=self.adv_btn)
                self.adv_btn.configure(text="▾  AJUSTES AVANZADOS (prompt inicial de Whisper)")
            else:
                self._prompt_card.pack_forget()
                self.adv_btn.configure(text="▸  AJUSTES AVANZADOS (prompt inicial de Whisper)")
        except Exception:
            pass

    def _input_device_changed(self, label):
        label = (label or "").replace("  (no conectado)", "")
        name = "" if label == audio_devices.DEFAULT_LABEL else label
        self._initial["input_device_name"] = name
        if self.on_input_device_change:
            self.on_input_device_change(name)

    def _theme_changed(self, label):
        key = themes.LABEL_TO_KEY.get(label)
        if not key or key == self._theme_key:
            return
        self._theme_key = key
        self._capture_ui_state()
        _apply_palette_globals(themes.get_palette(key))
        self._rebuild()
        if self.on_theme_change:
            try:
                self.on_theme_change(key)
            except Exception:
                pass

    def _capture_ui_state(self):
        """Vuelca los valores actuales de los widgets a self._initial para que
        el rebuild del tema no pierda lo que el usuario cambió en la sesión."""
        ini = self._initial
        try:
            ini["model"] = self.model_menu.get()
            ini["paste_mode"] = self.paste_mode_menu.get()
            ini["language"] = config.LANGUAGE_LABEL_TO_CODE.get(
                self.language_menu.get(), self._resolved_language_code()
            )
            ini["quality_profile"] = config.QUALITY_PROFILE_LABEL_TO_KEY.get(
                self.profile_menu.get(), self._resolved_profile_key()
            )
            ini["performance_profile"] = config.PERF_PROFILE_LABEL_TO_KEY.get(
                self.perf_menu.get(), self._resolved_perf_key()
            )
            ini["beep_enabled"] = bool(self.beep_var.get())
            ini["replacements_enabled"] = bool(self.replacements_var.get())
            ini["hotkey_enabled"] = bool(self.hotkey_var.get())
            ini["mixed_language_mode"] = bool(self.mixed_lang_var.get())
            ini["start_with_windows"] = bool(self.start_with_windows_var.get())
            ini["start_minimized"] = bool(self.start_minimized_var.get())
            ini["initial_prompt_enabled"] = bool(self.initial_prompt_var.get())
            ini["initial_prompt"] = self.initial_prompt_box.get("1.0", "end").strip()
            ini["hotwords"] = self._vocab_hotwords_text()
            ini["ui_theme"] = self._theme_key
            mic = self.mic_menu.get().replace("  (no conectado)", "")
            ini["input_device_name"] = "" if mic == audio_devices.DEFAULT_LABEL else mic
        except Exception:
            pass

    def _rebuild(self):
        """Destruye y reconstruye todos los widgets con la paleta activa.
        Corre en el hilo Tk (lo llama el callback del dropdown TEMA)."""
        try:
            self.root.configure(fg_color=BG_BASE)
        except Exception:
            pass
        for w in self.root.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._build()
        # Restaura el estado dinámico que _build() no conoce.
        try:
            self.backend_label.configure(text=f"Backend: {self._last_backend}")
        except Exception:
            pass
        if self._last_transcription:
            try:
                self.transcription_box.configure(state="normal")
                self.transcription_box.insert("1.0", self._last_transcription)
                self.transcription_box.configure(state="disabled")
            except Exception:
                pass
        try:
            prefix = self._BTN_ICONS.get(self._last_btn_text, "")
            self.toggle_btn.configure(text=prefix + self._last_btn_text)
        except Exception:
            pass
        self.set_status(self._last_state)
        self.set_history(self._history_data)

    def _history_copy_clicked(self):
        text = self._selected_history_item()
        if text is not None:
            self.on_history_copy(text)

    def _history_paste_clicked(self):
        text = self._selected_history_item()
        if text is not None:
            self.on_history_paste(text)

    def _history_clear_clicked(self):
        self.on_history_clear()

    def _selected_history_item(self):
        sel = self.history_listbox.curselection()
        if not sel:
            return None
        idx = sel[0]
        if 0 <= idx < len(self._history_data):
            return self._history_data[idx]
        return None

    # ---- API thread-safe ----
    def current_model(self) -> str:
        return self.model_menu.get()

    def log(self, msg: str):
        # La tab de Logs fue removida de la UI (era de desarrollo). Mantenemos
        # la API y enviamos a stdout para que sea visible desde una terminal.
        try:
            print(msg, flush=True)
        except Exception:
            pass
        # En el .exe (console=False) el print muere en el vacío: se persiste
        # también a archivo con tope de tamaño para poder dar soporte.
        try:
            p = config.APP_LOG_PATH
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.stat().st_size > 2_000_000:
                p.write_bytes(p.read_bytes()[-1_000_000:])
            with p.open("a", encoding="utf-8", errors="replace") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def set_status(self, state: str):
        self._ui_queue.put(("status", state))

    def set_backend(self, backend_str: str):
        self._ui_queue.put(("backend", backend_str))

    def set_gpu_pack_button(self, text: str | None):
        """Muestra (texto) u oculta (None) el botón de aceleración NVIDIA."""
        self._ui_queue.put(("gpu_pack", text))

    def _gpu_pack_clicked(self):
        if self.on_gpu_pack_install:
            self.on_gpu_pack_install()

    def set_transcribing_elapsed(self, seconds: float):
        self._ui_queue.put(("elapsed", seconds))

    def set_transcription(self, text: str):
        self._ui_queue.put(("trans", text))

    def set_button_text(self, text: str):
        self._ui_queue.put(("btn", text))

    def set_history(self, items: list):
        self._ui_queue.put(("history", list(items)))

    def set_model(self, value: str):
        def _do():
            self._suppress_model_change = True
            try:
                self.model_menu.set(value)
                self.model_hint_label.configure(text=self._model_hint_text(value))
            finally:
                self._suppress_model_change = False
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def set_quality_profile(self, key: str):
        label = config.QUALITY_PROFILE_LABELS.get(key, "")
        desc = config.QUALITY_PROFILE_DESCRIPTIONS.get(key, "")
        def _do():
            try:
                if label:
                    self.profile_menu.set(label)
                self.profile_desc_label.configure(text=desc)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def set_perf_profile(self, key: str):
        """Refleja el perfil de rendimiento en el dropdown sin disparar el
        callback (lo usa el autotune de GPU al arrancar)."""
        label = config.PERF_PROFILE_LABELS.get(key, "")
        desc = config.PERF_PROFILE_DESCRIPTIONS.get(key, "")
        def _do():
            try:
                if label:
                    self.perf_menu.set(label)
                self.perf_desc_label.configure(text=desc)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def set_rebind_mode(self, active: bool):
        """UI feedback durante el modo 'pulsa la nueva tecla'."""
        def _do():
            try:
                if active:
                    self.hotkey_main_label.configure(
                        text="Pulsa la nueva combinación…",
                        text_color=SECONDARY,
                    )
                    self.hotkey_label_widget.configure(
                        text="Esc para cancelar",
                        text_color=SECONDARY,
                    )
                    self.rebind_btn.configure(text="⏺", text_color=SECONDARY)
                else:
                    self.hotkey_main_label.configure(
                        text=f"Mantén {pretty_hotkey(self._hotkey_label)} para grabar",
                        text_color=TEXT,
                    )
                    self.hotkey_label_widget.configure(
                        text="Suéltalo para transcribir y pegar  ·  Click 👆 para cambiar la tecla",
                        text_color=TEXT_MUTED,
                    )
                    self.rebind_btn.configure(text="👆", text_color=PRIMARY)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def update_hotkey_label(self, label: str):
        """Refresca el texto del card cuando cambia el hotkey activo."""
        self._hotkey_label = (label or self._hotkey_label)
        def _do():
            try:
                self.hotkey_main_label.configure(
                    text=f"Mantén {pretty_hotkey(self._hotkey_label)} para grabar",
                )
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def set_start_with_windows(self, enabled: bool):
        """Refleja el estado del switch sin disparar el callback (para revertir
        en caso de fallo del registro)."""
        def _do():
            try:
                self.start_with_windows_var.set(bool(enabled))
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            _do()

    def hide_to_tray(self):
        self.root.after(0, self._hide_to_tray)

    def show_from_tray(self):
        self.root.after(0, self._show_from_tray)

    def _hide_to_tray(self):
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _show_from_tray(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def run_on_ui_thread(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def geometry(self) -> str:
        try:
            return self.root.winfo_geometry()
        except Exception:
            return ""

    def destroy(self):
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---- queue draining (Tk thread) ----
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "status":
                    self._last_state = payload
                    color = self._state_colors().get(payload, TEXT_VARIANT)
                    label = self.STATE_LABELS.get(payload, str(payload).upper())
                    self.status_label.configure(
                        text=f"ESTADO: {label}", text_color=color,
                    )
                    self.status_dot.configure(text_color=color)
                elif kind == "backend":
                    self._last_backend = payload
                    try:
                        self.backend_label.configure(text=f"Backend: {payload}")
                    except Exception:
                        pass
                elif kind == "elapsed":
                    # Solo muestra el contador mientras seguimos transcribiendo.
                    try:
                        cur = self.status_label.cget("text")
                        if "TRANSCRIBIENDO" in cur:
                            self.status_label.configure(
                                text=f"ESTADO: TRANSCRIBIENDO ({payload:.0f}s)",
                                text_color=self._state_colors()["transcribing"],
                            )
                    except Exception:
                        pass
                elif kind == "trans":
                    self._last_transcription = payload
                    self.transcription_box.configure(state="normal")
                    self.transcription_box.delete("1.0", "end")
                    self.transcription_box.insert("1.0", payload)
                    self.transcription_box.configure(state="disabled")
                elif kind == "btn":
                    self._last_btn_text = payload
                    prefix = self._BTN_ICONS.get(payload, "")
                    self.toggle_btn.configure(text=prefix + payload)
                elif kind == "license_status":
                    self._last_license = payload
                    self._apply_license_status(payload)
                elif kind == "license_result":
                    text, err = payload
                    try:
                        self.license_result_label.configure(
                            text=text, text_color=ERROR if err else PRIMARY)
                        self.license_activate_btn.configure(state="normal")
                        if not err:
                            self.license_entry.delete(0, "end")
                    except Exception:
                        pass
                elif kind == "gpu_pack":
                    self._gpu_pack_btn_text = payload
                    try:
                        if payload:
                            self.gpu_pack_btn.configure(text=payload)
                            self.gpu_pack_btn.grid()
                        else:
                            self.gpu_pack_btn.grid_remove()
                    except Exception:
                        pass
                elif kind == "history":
                    self._history_data = list(payload)
                    self.history_listbox.delete(0, tk.END)
                    for item in self._history_data:
                        display = item if len(item) < 140 else item[:137] + "…"
                        self.history_listbox.insert(tk.END, display)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def run(self):
        self.root.mainloop()
