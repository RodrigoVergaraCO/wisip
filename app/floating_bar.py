"""Barra flotante compacta estilo "píldora" (inspirada en el dictado de macOS).

Cápsula oscura con esquinas totalmente redondeadas: un punto de estado a la
izquierda y una onda de voz de barras verticales que se desplaza de derecha a
izquierda con el nivel real del micro (estilo Voice Memos). Sin texto en los
estados normales — el color del punto y el movimiento comunican el estado;
solo "listo" (✓) y error muestran un glifo/mensaje corto.

Toplevel sin chrome con `-transparentcolor` para esquinas redondeadas reales
en Windows. Aplica `WS_EX_NOACTIVATE` vía ctypes para no robar foco al
input destino (necesario para que el Ctrl+V termine en la app correcta).
"""

import math
import tkinter as tk


# ---- dimensiones / colores (pill oscura neutra, paleta iOS dark) ----
TRANSPARENT_COLOR = "#000001"  # casi negro, sirve de máscara
BAR_W = 172
BAR_H = 34
BAR_R = 17               # = BAR_H/2 → cápsula perfecta
BG = "#1c1c1e"           # superficie oscura (iOS systemGray6 dark)
BG_BORDER = "#3a3a3c"    # borde hairline

DOT_REC = "#ff453a"      # rojo grabación (systemRed dark)
DOT_BUSY = "#ff9f0a"     # naranja transcribiendo (systemOrange dark)
DOT_OK = "#30d158"       # verde pegando (systemGreen dark)

WAVE_ACTIVE = "#f2f2f7"  # blanco suave: barras con voz
WAVE_IDLE = "#8e8e93"    # gris: barras en espera/procesando
OK_COLOR = "#30d158"
ERR_COLOR = "#ff453a"

# Punto de estado y zona de onda
DOT_X = 16               # centro del punto
DOT_R = 3
WAVE_X = 30              # inicio de las barras
WAVE_N = 26              # nº de barras
WAVE_W = 2               # ancho de cada barra
WAVE_GAP = 3             # separación entre barras
WAVE_MAX_H = 20          # altura máxima de barra (deja 7px de aire arriba/abajo)
WAVE_MIN_H = 2           # línea base (silencio)

ANIM_MS = 50             # ~20 fps


def _draw_rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Polígono suavizado que aproxima un rect con esquinas redondeadas."""
    pts = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


class FloatingBar:
    """Barra flotante. Toda llamada pública es thread-safe (entra al hilo Tk
    vía `after(0, ...)`)."""

    def __init__(self, parent_root, hotkey_label: str, get_level=None, on_log=None):
        self.parent_root = parent_root
        self.hotkey_label = (hotkey_label or "").upper()  # ya no se muestra
        self.get_level = get_level or (lambda: 0.0)
        self.on_log = on_log or (lambda m: None)

        self._visible = False
        self._anim_mode = None      # "voice" | "wave" | None
        self._anim_after_id = None
        self._hide_after_id = None
        self._levels = [0.0] * WAVE_N   # historial de niveles (scroll ←)
        self._phase = 0.0               # fase de la onda "procesando"

        self.top = tk.Toplevel(parent_root)
        self.top.title("Local Voice Typer Bar")
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        try:
            self.top.attributes("-alpha", 0.95)
        except Exception:
            pass
        try:
            self.top.attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception:
            pass
        try:
            self.top.attributes("-toolwindow", True)
        except Exception:
            pass
        self.top.configure(bg=TRANSPARENT_COLOR)

        self.canvas = tk.Canvas(
            self.top, width=BAR_W, height=BAR_H,
            bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0,
        )
        self.canvas.pack()
        self._build_canvas()

        # Posicionar y dejarlo oculto hasta que haga falta.
        self._reposition()
        self.top.withdraw()
        # Aplicar NOACTIVATE después de que la ventana exista.
        self.parent_root.after(50, self._apply_noactivate)

    # ---------- construcción del canvas ----------
    def _build_canvas(self):
        c = self.canvas
        cy = BAR_H // 2

        # Cápsula de fondo con borde hairline
        _draw_rounded_rect(c, 1, 1, BAR_W - 1, BAR_H - 1, BAR_R,
                           fill=BG, outline=BG_BORDER, width=1)

        # Punto de estado (izquierda)
        self.dot_id = c.create_oval(
            DOT_X - DOT_R, cy - DOT_R, DOT_X + DOT_R, cy + DOT_R,
            fill=DOT_REC, outline="",
        )

        # Barras de la onda (línea base por defecto)
        self._bar_ids = []
        for i in range(WAVE_N):
            x = WAVE_X + i * (WAVE_W + WAVE_GAP)
            rid = c.create_rectangle(
                x, cy - WAVE_MIN_H // 2, x + WAVE_W, cy + WAVE_MIN_H // 2,
                fill=WAVE_IDLE, outline="",
            )
            self._bar_ids.append(rid)

        # Texto centrado ("✓" / mensaje de error). Oculto por defecto.
        self.text_id = c.create_text(
            BAR_W // 2, cy, text="",
            fill=OK_COLOR, font=("Segoe UI", 9, "bold"),
        )
        c.itemconfigure(self.text_id, state="hidden")

    def _reposition(self):
        try:
            self.top.update_idletasks()
            sw = self.top.winfo_screenwidth()
            sh = self.top.winfo_screenheight()
            x = (sw - BAR_W) // 2
            y = sh - 120
            self.top.geometry(f"{BAR_W}x{BAR_H}+{x}+{y}")
        except Exception as e:
            self.on_log(f"[bar] reposition error: {e}")

    def _apply_noactivate(self):
        """Aplica WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW para que no robe foco."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080

            # winfo_id() en Tk devuelve el HWND del frame Tk; el padre real es
            # el HWND de la ventana overrideredirect.
            hwnd = user32.GetParent(self.top.winfo_id())
            if not hwnd:
                hwnd = self.top.winfo_id()

            # Versión de 64 bits-safe.
            try:
                GetWindowLongPtrW = user32.GetWindowLongPtrW
                SetWindowLongPtrW = user32.SetWindowLongPtrW
                GetWindowLongPtrW.restype = ctypes.c_ssize_t
                GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
                SetWindowLongPtrW.restype = ctypes.c_ssize_t
                SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
                ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            except AttributeError:
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception as e:
            self.on_log(f"[bar] WS_EX_NOACTIVATE no aplicado: {e}")

    # ---------- API pública (thread-safe) ----------
    def show_recording(self):
        self.parent_root.after(0, self._do_show_recording)

    def show_transcribing(self):
        self.parent_root.after(0, self._do_show_transcribing)

    def show_pasting(self):
        self.parent_root.after(0, self._do_show_pasting)

    def show_ready_and_hide(self, delay_ms: int = 1200):
        self.parent_root.after(0, lambda: self._do_show_ready(delay_ms))

    def show_error_and_hide(self, msg: str = "Error", delay_ms: int = 2200):
        self.parent_root.after(0, lambda: self._do_show_error(msg, delay_ms))

    def hide(self):
        self.parent_root.after(0, self._do_hide)

    def set_hotkey_label(self, label: str):
        # La pill compacta ya no muestra el hotkey; se conserva el método por
        # compatibilidad con los callers (rebind).
        self.hotkey_label = (label or "").upper()

    # ---------- implementaciones reales (en hilo Tk) ----------
    def _do_show_recording(self):
        self._show()
        self._set_dot(DOT_REC)
        self._set_text(None)
        self._levels = [0.0] * WAVE_N
        self._set_bars_visible(True, WAVE_ACTIVE)
        self._start_animation("voice")

    def _do_show_transcribing(self):
        self._show()
        self._set_dot(DOT_BUSY)
        self._set_text(None)
        self._set_bars_visible(True, WAVE_IDLE)
        self._start_animation("wave")

    def _do_show_pasting(self):
        self._show()
        self._set_dot(DOT_OK)
        self._set_text(None)
        self._set_bars_visible(True, WAVE_IDLE)
        self._stop_animation()

    def _do_show_ready(self, delay_ms):
        if not self._visible:
            return  # No aparecer "listo" si nunca apareció nada antes.
        self._stop_animation()
        self._set_dot(None)
        self._set_bars_visible(False)
        self._set_text("✓", OK_COLOR)
        self._schedule_hide(delay_ms)

    def _do_show_error(self, msg, delay_ms):
        self._show()
        self._stop_animation()
        self._set_dot(None)
        self._set_bars_visible(False)
        text = msg if msg else "Error"
        if len(text) > 22:
            text = text[:20] + "…"
        self._set_text(f"✕ {text}", ERR_COLOR)
        self._schedule_hide(delay_ms)

    def _do_hide(self):
        self._cancel_hide()
        self._stop_animation()
        try:
            self.top.withdraw()
        except Exception:
            pass
        self._visible = False

    # ---------- helpers internos ----------
    def _show(self):
        self._cancel_hide()
        if not self._visible:
            try:
                self._reposition()
                self.top.deiconify()
                self.top.attributes("-topmost", True)
                self._apply_noactivate()
            except Exception as e:
                self.on_log(f"[bar] show error: {e}")
            self._visible = True

    def _set_dot(self, color):
        try:
            if color is None:
                self.canvas.itemconfigure(self.dot_id, state="hidden")
            else:
                self.canvas.itemconfigure(self.dot_id, state="normal", fill=color)
        except Exception:
            pass

    def _set_text(self, text, color=OK_COLOR):
        try:
            if not text:
                self.canvas.itemconfigure(self.text_id, state="hidden")
            else:
                self.canvas.itemconfigure(
                    self.text_id, state="normal", text=text, fill=color,
                )
        except Exception:
            pass

    def _set_bars_visible(self, show, color=None):
        for rid in self._bar_ids:
            try:
                self.canvas.itemconfigure(rid, state="normal" if show else "hidden")
                if color is not None:
                    self.canvas.itemconfigure(rid, fill=color)
            except Exception:
                pass
        if show:
            self._set_bars_baseline()

    def _set_bars_baseline(self):
        cy = BAR_H // 2
        half = WAVE_MIN_H / 2
        for i, rid in enumerate(self._bar_ids):
            x = WAVE_X + i * (WAVE_W + WAVE_GAP)
            try:
                self.canvas.coords(rid, x, cy - half, x + WAVE_W, cy + half)
            except Exception:
                pass

    # ---------- animación ----------
    def _start_animation(self, mode):
        self._anim_mode = mode
        if self._anim_after_id is None:
            self._animate()

    def _stop_animation(self):
        self._anim_mode = None
        if self._anim_after_id is not None:
            try:
                self.parent_root.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None
        self._set_bars_baseline()

    def _animate(self):
        if self._anim_mode is None:
            self._anim_after_id = None
            return

        if self._anim_mode == "voice":
            # Onda de voz que se desplaza: cada tick entra el nivel actual por
            # la derecha y el historial corre hacia la izquierda (Voice Memos).
            try:
                level = max(0.0, min(1.0, self.get_level()))
            except Exception:
                level = 0.0
            self._levels.pop(0)
            self._levels.append(level ** 0.75)  # realza voz baja sin saturar
            heights = [
                WAVE_MIN_H + lvl * (WAVE_MAX_H - WAVE_MIN_H) for lvl in self._levels
            ]
        else:  # "wave": pulso suave viajando por las barras (procesando)
            self._phase += 0.45
            heights = [
                WAVE_MIN_H + 5.0 * (0.5 + 0.5 * math.sin(i * 0.55 - self._phase))
                for i in range(WAVE_N)
            ]

        cy = BAR_H // 2
        for i, rid in enumerate(self._bar_ids):
            half = heights[i] / 2
            x = WAVE_X + i * (WAVE_W + WAVE_GAP)
            try:
                self.canvas.coords(rid, x, cy - half, x + WAVE_W, cy + half)
            except Exception:
                pass
        try:
            self._anim_after_id = self.parent_root.after(ANIM_MS, self._animate)
        except Exception:
            self._anim_after_id = None

    def _schedule_hide(self, ms):
        self._cancel_hide()
        try:
            self._hide_after_id = self.parent_root.after(ms, self._do_hide)
        except Exception:
            pass

    def _cancel_hide(self):
        if self._hide_after_id is not None:
            try:
                self.parent_root.after_cancel(self._hide_after_id)
            except Exception:
                pass
            self._hide_after_id = None
