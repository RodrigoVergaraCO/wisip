# -*- coding: utf-8 -*-
"""Prueba de humo de la ventana principal con las pestañas Inicio / Ajustes /
Vocabulario / Historial / Licencia (2.10.0). Construye AppUI con callbacks
falsos, recorre pestañas, cambia el tema (rebuild completo), pliega y
despliega "Ajustes avanzados", y aplica los setters thread-safe. Necesita
escritorio (no corre en CI).

Uso (desde la raíz del proyecto, con el venv):
    python tests/smoke_ui_tabs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import config  # noqa: E402
from app import themes  # noqa: E402
from app.ui import AppUI  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    calls = {}

    def cb(name):
        def _f(*a, **k):
            calls[name] = calls.get(name, 0) + 1
        return _f

    ui = AppUI(
        on_model_change=cb("model"), on_language_change=cb("language"),
        on_toggle_button=cb("toggle"), on_paste_mode_change=cb("paste_mode"),
        on_beep_toggle=cb("beep"), on_replacements_toggle=cb("replacements"),
        on_hotkey_toggle=cb("hotkey"), on_history_copy=cb("h_copy"),
        on_history_paste=cb("h_paste"), on_history_clear=cb("h_clear"),
        on_initial_prompt_toggle=cb("ip_toggle"), on_initial_prompt_save=cb("ip_save"),
        on_quality_profile_change=cb("quality"), on_mixed_language_toggle=cb("mixed"),
        on_hotkey_rebind_request=cb("rebind"), on_start_with_windows_toggle=cb("start_win"),
        on_start_minimized_toggle=cb("start_min"), on_perf_profile_change=cb("perf"),
        on_close_request=cb("close"), on_theme_change=cb("theme"),
        on_gpu_pack_install=cb("gpu_pack"), on_input_device_change=cb("mic"),
        on_license_activate=cb("lic_act"), on_license_deactivate=cb("lic_deact"),
        on_correction_save=lambda o, c: (calls.__setitem__("corr", (o, c)) or "Guardada ✓"),
        initial_settings={"hotkey": "ctrl+windows", "input_device_name": "Micrófono X"},
        hotkey_label="ctrl+windows",
    )

    def pump(n=2):
        for _ in range(n):
            ui.root.update()
            ui._drain_queue()

    pump()
    print("── Pestañas ──")
    names = list(ui.tabs._name_list) if hasattr(ui.tabs, "_name_list") else []
    check("cinco pestañas en orden", names == ["Inicio", "Ajustes", "Vocabulario", "Historial", "Licencia"], str(names))
    for t in ["Ajustes", "Vocabulario", "Historial", "Licencia", "Inicio"]:
        ui.tabs.set(t); pump()
    check("cambiar de pestaña no rompe", True)

    print("── Widgets en su sitio ──")
    for attr in ["hotkey_main_label", "rebind_btn", "mic_menu", "language_menu", "mixed_lang_switch",
                 "toggle_btn", "transcription_box", "backend_label", "profile_menu", "model_menu",
                 "perf_menu", "gpu_pack_btn", "paste_mode_menu", "_theme_chips", "beep_chk",
                 "replacements_chk", "hotkey_switch", "start_with_windows_switch",
                 "start_minimized_switch", "adv_btn", "initial_prompt_box", "initial_prompt_chk",
                 "license_entry", "license_state_label", "history_listbox"]:
        check(f"existe {attr}", hasattr(ui, attr))
    check("tecla legible", ui.hotkey_key_label.cget("text").strip() == "Ctrl + Win", ui.hotkey_key_label.cget("text"))
    check("micro no conectado marcado", "(no conectado)" in ui.mic_menu.get(), ui.mic_menu.get())

    print("── Avanzado plegado / desplegado ──")
    check("prompt oculto al inicio", not ui._prompt_card.winfo_manager())
    ui._toggle_advanced(); pump()
    check("prompt visible tras abrir", bool(ui._prompt_card.winfo_manager()))
    ui._toggle_advanced(); pump()
    check("prompt oculto tras cerrar", not ui._prompt_card.winfo_manager())

    print("── Modo rebind en la tarjeta correcta ──")
    ui.set_rebind_mode(True, "translate"); pump(3)
    check("rebind traducir: la tecla de traducir muestra …", ui.translate_key_label.cget("text") == "…", ui.translate_key_label.cget("text"))
    check("rebind traducir: la tecla de dictar NO cambia", ui.hotkey_key_label.cget("text").strip() == "Ctrl + Win", ui.hotkey_key_label.cget("text"))
    ui.set_rebind_mode(False, "translate"); pump(3)
    check("fin del rebind: tecla de traducir restaurada", "Ctrl + Win + Shift" in ui.translate_key_label.cget("text"), ui.translate_key_label.cget("text"))
    ui.set_rebind_mode(True, "dictate"); pump(3)
    check("rebind dictar: la tecla de dictar muestra …", ui.hotkey_key_label.cget("text") == "…", ui.hotkey_key_label.cget("text"))
    ui.set_rebind_mode(False, "dictate"); pump(3)

    print("── Corrección de la última transcripción ──")
    import time as _t
    check("existe correction_btn", hasattr(ui, "correction_btn") and hasattr(ui, "correction_status"))
    ui.set_transcription("Los prótesis de Amazon."); pump(3)
    ui._correction_save_clicked(); pump(3)
    check("sin cambios → aviso", "No hay cambios" in ui.correction_status.cget("text"), ui.correction_status.cget("text"))
    ui.transcription_box.delete("1.0", "end"); ui.transcription_box.insert("1.0", "Los proxys de Amazon.")
    ui._correction_save_clicked(); _t.sleep(0.4); pump(3)
    check("callback recibe original y corregido", calls.get("corr") == ("Los prótesis de Amazon.", "Los proxys de Amazon."), str(calls.get("corr")))
    check("estado muestra el mensaje del callback", "Guardada" in ui.correction_status.cget("text"), ui.correction_status.cget("text"))
    check("botón reactivado", ui.correction_btn.cget("state") == "normal")
    ui.set_correction_status("3 correcciones guardadas este mes."); pump(2)

    print("── Setters thread-safe ──")
    ui.set_backend("CUDA float16"); ui.set_transcription("Hola mundo"); ui.set_status("idle")
    ui.set_history(["uno", "dos"]); ui.set_gpu_pack_button("⚡ Descargar aceleración NVIDIA")
    ui.set_license_status({"state": "trial", "days_left": 30, "message": "Prueba", "instance": "PC"})
    ui.set_license_result("Activada", error=False); pump(3)
    check("backend pintado", "CUDA" in ui.backend_label.cget("text"))
    check("transcripción pintada", "Hola mundo" in ui.transcription_box.get("1.0", "end"))
    check("botón GPU visible", bool(ui.gpu_pack_btn.winfo_manager()))
    check("licencia pintada", "30" in ui.license_state_label.cget("text"))
    check("historial 2 filas", ui.history_listbox.size() == 2)

    print("── Cambio de tema (rebuild) ──")
    other = [k for k in themes.THEME_KEYS if k != ui._theme_key][0]
    ui._theme_changed(themes.THEME_LABELS[other]); pump(3)
    check("rebuild conserva backend", "CUDA" in ui.backend_label.cget("text"))
    check("rebuild conserva transcripción", "Hola mundo" in ui.transcription_box.get("1.0", "end"))
    check("rebuild conserva botón GPU", bool(ui.gpu_pack_btn.winfo_manager()))
    check("rebuild conserva licencia", "30" in ui.license_state_label.cget("text"))
    check("rebuild conserva micro", "Micrófono X" in ui.mic_menu.get())
    check("rebuild conserva estado de correcciones", "3 correcciones" in ui.correction_status.cget("text"), ui.correction_status.cget("text"))
    check("callback de tema llamado", calls.get("theme", 0) >= 1)

    print("── Callbacks ──")
    ui._input_device_changed("Predeterminado del sistema"); ui._language_changed(config.LANGUAGE_LABEL_EN)
    ui.mixed_lang_var.set(False); ui._mixed_lang_changed(); ui._license_activate_clicked(); pump()
    check("callbacks disparan", all(calls.get(k) for k in ("mic", "language", "mixed", "lic_act")), str(calls))

    ui.root.destroy()
    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Prueba de humo de la UI (Inicio/Ajustes) pasada.")


if __name__ == "__main__":
    main()
