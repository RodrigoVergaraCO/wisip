# -*- coding: utf-8 -*-
"""Capturas reales de la app para la tienda y la web (site/media/).

Construye las ventanas de Wisip con datos de demostración (sin grabar ni
cargar modelo), las captura del escritorio y compone imágenes de producto
1600×1000 sobre fondo oscuro con un pie de texto. Necesita escritorio:
las ventanas aparecen unos segundos.

Uso (desde la raíz del proyecto, con el venv):
    python tests/shots.py
Salida: site/screenshots/*.png (crudas) y site/media/*.png (compuestas).
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import customtkinter as ctk  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageGrab  # noqa: E402

from app import config, themes  # noqa: E402
from app.onboarding import OnboardingWizard  # noqa: E402
from app.setup_window import SetupWindow  # noqa: E402
from app.ui import AppUI  # noqa: E402

RAW = ROOT / "site" / "screenshots"
OUT = ROOT / "site" / "media"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
PAL = themes.get_palette(themes.DEFAULT_THEME)


def grab(win, path: Path, pad: int = 0):
    """Captura el rectángulo de una ventana Tk (coordenadas de pantalla)."""
    for _ in range(4):
        win.update_idletasks(); win.update()
        time.sleep(0.2)
    x, y = win.winfo_rootx() - pad, win.winfo_rooty() - pad
    w, h = win.winfo_width() + 2 * pad, win.winfo_height() + 2 * pad
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(path)
    print(f"  captura {path.name} {img.size}")
    return img


def font(size, bold=False):
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arialbd.ttf" if bold else "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def compose(shot: Image.Image, title: str, subtitle: str, out: Path, size=(1600, 1000)):
    """Fondo oscuro con degradado sutil, la captura centrada con sombra y
    esquinas redondeadas, y el texto arriba."""
    W, H = size
    bg = Image.new("RGB", size, PAL["BG_BASE"])
    draw = ImageDraw.Draw(bg)
    # Halo naranja muy tenue detrás de la captura.
    halo = Image.new("RGB", size, PAL["BG_BASE"])
    hd = ImageDraw.Draw(halo)
    hd.ellipse((W * 0.15, H * 0.25, W * 0.85, H * 1.05), fill="#2a1a05")
    halo = halo.filter(ImageFilter.GaussianBlur(120))
    bg = Image.blend(bg, halo, 0.9)
    draw = ImageDraw.Draw(bg)
    draw.text((80, 64), title, font=font(46, bold=True), fill=PAL["TEXT"])
    draw.text((80, 128), subtitle, font=font(24), fill=PAL["TEXT_VARIANT"])

    # Escala la captura para que quepa.
    max_w, max_h = W - 160, H - 240
    sw, sh = shot.size
    scale = min(max_w / sw, max_h / sh, 1.0)
    shot = shot.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    sw, sh = shot.size
    x = (W - sw) // 2
    y = 200 + (max_h - sh) // 2

    # Esquinas redondeadas + sombra.
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=18, fill=255)
    shadow = Image.new("RGBA", (sw + 120, sh + 120), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((60, 70, 60 + sw, 70 + sh), radius=18, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    bg.paste(shadow, (x - 60, y - 60), shadow)
    bg.paste(shot, (x, y), mask)
    bg.save(out, optimize=True)
    print(f"  imagen {out.name} {bg.size}")


def main():
    root = ctk.CTk()
    root.withdraw()

    # 1) Ventana principal con datos de demostración.
    noop = lambda *a, **k: None
    ui = AppUI(
        on_model_change=noop, on_language_change=noop, on_toggle_button=noop,
        on_paste_mode_change=noop, on_beep_toggle=noop, on_replacements_toggle=noop,
        on_hotkey_toggle=noop, on_history_copy=noop, on_history_paste=noop,
        on_history_clear=noop, on_initial_prompt_toggle=noop, on_initial_prompt_save=noop,
        on_quality_profile_change=noop, on_mixed_language_toggle=noop,
        on_hotkey_rebind_request=noop, on_start_with_windows_toggle=noop,
        on_start_minimized_toggle=noop, on_perf_profile_change=noop, on_close_request=noop,
        on_theme_change=noop, on_gpu_pack_install=noop, on_input_device_change=noop,
        on_license_activate=noop, on_license_deactivate=noop,
        on_vocab_tokens=lambda t: ("208 / 224 tokens", False),
        on_vocab_list=lambda: [("proxifyr", "Proxifier"), ("herzner", "Hetzner"), ("goblogin", "GoLogin")],
        initial_settings={"hotkey": "ctrl+windows+space", "model": "large-v3-turbo",
                          "quality_profile": "accurate_gpu", "performance_profile": "fast_safe",
                          "input_device_name": "", "hotwords": "proxy, MEmu, GoLogin, Hetzner, Billions Manager"},
        hotkey_label="ctrl+windows+space",
    )
    ui.set_backend("CUDA float16 · large-v3-turbo")
    ui.set_status("idle")
    ui.set_transcription(
        "Hola Andrea, te confirmo la reunión del jueves a las 10. Puedes entrar a wisip.ai/dashboard "
        "o escribirme a soporte@gmail.com. This part stays in English because I said it in English."
    )
    ui.set_history([
        "Hola Andrea, te confirmo la reunión del jueves a las 10.",
        "Después del deploy hice commit y push a la rama main de GitHub.",
        "El precio del producto es 5 dólares con 25 centavos, o sea, 5.25.",
    ])
    ui.set_license_status({"state": "trial", "days_left": 30, "key_masked": "", "email": "",
                           "instance": "MI-PC (a1b2c3d4)",
                           "message": "Prueba gratuita: 30 días restantes. Después necesitarás una licencia."})
    for _ in range(3):
        ui.root.update(); ui._drain_queue()
    ui.root.geometry("740x900+120+60")
    ui.root.deiconify(); ui.root.lift()
    for _ in range(4):
        ui.root.update(); ui._drain_queue()
    time.sleep(0.6)

    shots = {}
    ui.tabs.set("Inicio"); ui.root.update(); shots["inicio"] = grab(ui.root, RAW / "01-inicio.png")
    ui.tabs.set("Ajustes"); [ (ui.root.update(), time.sleep(0.15)) for _ in range(4) ]; shots["ajustes"] = grab(ui.root, RAW / "02-ajustes.png")
    ui.tabs.set("Vocabulario"); [ (ui.root.update(), time.sleep(0.15)) for _ in range(4) ]; shots["vocab"] = grab(ui.root, RAW / "03-vocabulario.png")
    ui.tabs.set("Licencia"); [ (ui.root.update(), time.sleep(0.15)) for _ in range(4) ]; shots["licencia"] = grab(ui.root, RAW / "04-licencia.png")
    ui.root.withdraw()

    # 2) Asistente inicial, paso del micrófono.
    wiz = OnboardingWizard(
        root, palette=PAL, initial={"language": "es", "hotkey": "ctrl+windows+space"},
        devices=[{"index": 1, "name": "Micrófono (Razer Kraken V3 X)", "hostapi": 0, "default": True},
                 {"index": 2, "name": "Webcam C920", "hostapi": 0, "default": False}],
        hotkey_label="ctrl+windows+space", gpu_info={"name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288},
        get_level=lambda: 0.62, on_device_preview=lambda n: True, on_rebind=noop, on_finish=noop,
    )
    root.update(); wiz.win.geometry("+900+120")
    wiz._show_page(1); root.update(); time.sleep(0.4); root.update()
    shots["wizard"] = grab(wiz.win, RAW / "05-asistente-microfono.png")
    wiz._show_page(0); root.update(); shots["wizard0"] = grab(wiz.win, RAW / "06-asistente-bienvenida.png")
    wiz.win.destroy()

    # 3) Ventana de descarga con progreso.
    sw = SetupWindow(root, palette=PAL)
    sw.show("Descargando la aceleración NVIDIA", "Una sola vez. Puedes seguir usando el PC; Wisip se activará al terminar.")
    root.update(); time.sleep(0.3); root.update()
    sw._t0 = time.monotonic() - 41
    sw.set_progress(512_000_000, 1_123_000_000, "cudnn: cudnn_engines_precompiled64_9.dll")
    root.update(); time.sleep(0.3); root.update()
    sw._win.geometry("+900+620")
    root.update()
    shots["descarga"] = grab(sw._win, RAW / "07-descarga.png")
    sw.close(); root.update()

    ui.root.destroy()
    try:
        root.destroy()
    except Exception:
        pass

    print("── Composición ──")
    compose(shots["inicio"], "Mantén una tecla, habla, suelta.",
            "El texto aparece en la app que tengas abierta. Español e inglés, en tu propio PC.",
            OUT / "01-inicio.png")
    compose(shots["wizard"], "Listo en un minuto",
            "Asistente de primer arranque: micrófono con medidor en vivo, tecla, idioma y privacidad.",
            OUT / "02-asistente.png")
    compose(shots["vocab"], "Aprende tu vocabulario",
            "Nombres, marcas y términos técnicos: los añades una vez y salen bien siempre.",
            OUT / "03-vocabulario.png")
    compose(shots["ajustes"], "Rápido con tu GPU, o en CPU",
            "Perfiles de calidad y rendimiento, modelo, tema. Sin internet después de la primera descarga.",
            OUT / "04-ajustes.png")
    compose(shots["descarga"], "Instalador de 77 MB",
            "El modelo de voz y la aceleración NVIDIA se descargan una sola vez, con progreso.",
            OUT / "05-descarga.png")
    compose(shots["licencia"], "Un pago, para siempre",
            "30 días de prueba sin tarjeta. Una licencia por equipo, transferible.",
            OUT / "06-licencia.png")
    print("✓ listo")


if __name__ == "__main__":
    main()
