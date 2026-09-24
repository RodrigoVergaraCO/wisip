# -*- coding: utf-8 -*-
"""Prueba de humo del asistente inicial (app/onboarding.py) con Tk real.

Construye el asistente sobre un root oculto, recorre TODAS las páginas (con y
sin GPU), cambia valores por código, simula el rebind y termina. No hace
clics: valida que cada página se construye sin excepciones y que el
resultado refleja las elecciones. Necesita escritorio (no corre en CI).

Uso (desde la raíz del proyecto, con el venv):
    python tests/smoke_onboarding.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import customtkinter as ctk  # noqa: E402

from app import audio_devices  # noqa: E402
from app.onboarding import OnboardingWizard  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    root = ctk.CTk()
    root.withdraw()
    events = []
    devices = [
        {"index": 7, "name": "Micrófono (Razer Kraken V3 X)", "hostapi": 2, "default": True},
        {"index": 9, "name": "Webcam C920", "hostapi": 2, "default": False},
    ]

    for gpu in ({"name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288}, None):
        label = "con GPU" if gpu else "sin GPU"
        results = []
        wiz = OnboardingWizard(
            root, initial={"language": "es", "hotkey": "|", "input_device_name": "Webcam C920"},
            devices=devices, hotkey_label="|", gpu_info=gpu,
            get_level=lambda: 0.3,
            on_device_preview=lambda n: events.append(("preview", n)),
            on_rebind=lambda: events.append(("rebind",)),
            on_finish=results.append, on_log=lambda m: events.append(("log", m)),
        )
        n = len(wiz._pages)
        check(f"{label}: número de páginas", n == (6 if gpu else 5), str(n))
        for i in range(n):
            wiz._show_page(i)
            root.update()
        check(f"{label}: todas las páginas construyen", True)
        check(f"{label}: micro inicial conservado", wiz.var_device.get() == "Webcam C920")
        check(f"{label}: preview del micro al entrar y cierre al salir",
              ("preview", "Webcam C920") in events and ("preview", None) in events, str(events[-4:]))
        # Cambios por código y rebind simulado.
        wiz._show_page(2); root.update()
        wiz._rebind_clicked(); root.update()
        check(f"{label}: rebind solicitado", ("rebind",) in events)
        wiz.set_hotkey("f8"); root.update(); root.update()
        check(f"{label}: hotkey actualizado", wiz.hotkey_label == "f8" and wiz.hotkey_big.cget("text") == "F8")
        wiz.var_lang.set("en"); wiz.var_mixed.set(False); wiz.var_log.set(False)
        if gpu:
            wiz.var_gpu.set("no")
        wiz._show_page(n - 1); root.update()
        wiz._next(); root.update()
        check(f"{label}: on_finish llamado una vez", len(results) == 1)
        r = results[0] if results else {}
        check(f"{label}: resultado refleja elecciones",
              r.get("language") == "en" and r.get("mixed_language_mode") is False
              and r.get("dictation_log_enabled") is False and r.get("hotkey") == "f8"
              and r.get("input_device_name") == "Webcam C920"
              and r.get("gpu_pack") == (False if gpu else None), str(r))
        wiz._finish()  # idempotente
        check(f"{label}: finish idempotente", len(results) == 1)
        events.clear()

    # Cierre con la X = terminar con valores actuales.
    results = []
    wiz = OnboardingWizard(root, initial={}, devices=[], hotkey_label="|", gpu_info=None,
                           on_finish=results.append)
    root.update()
    wiz.win.protocol("WM_DELETE_WINDOW")  # existe
    wiz._finish()
    check("cerrar con X termina con defaults",
          len(results) == 1 and results[0]["input_device_name"] == "" and results[0]["language"] == "es")
    check("etiqueta por defecto del micro", audio_devices.DEFAULT_LABEL in wiz.var_device.get())

    root.destroy()
    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Prueba de humo del asistente inicial pasada.")


if __name__ == "__main__":
    main()
