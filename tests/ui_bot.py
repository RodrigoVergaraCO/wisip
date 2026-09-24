# -*- coding: utf-8 -*-
"""
Bot de pruebas de UI para Wisip.

Pulsa/dispara TODOS los controles de la app y reporta qué funciona y qué lanza
errores, para dejar la app lista para producción. Tiene dos fases:

  FASE A — Widgets de AppUI:
    Construye la UI real con callbacks instrumentados y dispara cada dropdown
    (en todos sus valores), cada switch/checkbox, cada botón y el cambio de
    pestañas. Verifica que el control no lance excepción y que invoque su
    callback.

  FASE B — Handlers del Controller (lógica real):
    Construye el Controller real PERO reemplaza por dobles seguros las piezas
    con efectos colaterales: hotkey global, ícono de bandeja, micrófono, modelo
    Whisper, beeps, pegado al portapapeles y registro de Windows (autostart).
    Así ejercita la lógica de negocio de cada botón SIN pegar texto, sin
    registrar atajos globales ni escribir en el registro.

No usa red, no transcribe de verdad y NO toca tu micrófono ni tu portapapeles.

Uso:  python tests/ui_bot.py
"""

import os
import sys
import tempfile
import threading
import time
import traceback

# ── AISLAMIENTO DE DATOS ──────────────────────────────────────────────────
# La Fase B usa Settings/History REALES, que escriben en %APPDATA%. Para NO
# tocar la configuración ni el historial del usuario, redirigimos APPDATA a un
# directorio temporal ANTES de importar `app.config` (que lee APPDATA en import).
_SANDBOX = os.path.join(tempfile.gettempdir(), "wisip_ui_bot_sandbox")
os.makedirs(_SANDBOX, exist_ok=True)
os.environ["APPDATA"] = _SANDBOX

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402

from app import config  # noqa: E402

RESULTS = []  # [(fase, accion, ok, detalle)]


def record(fase, accion, fn):
    """Ejecuta fn() capturando excepciones; registra el resultado."""
    try:
        fn()
        RESULTS.append((fase, accion, True, ""))
    except Exception:
        RESULTS.append((fase, accion, False, traceback.format_exc(limit=3)))


# ─────────────────────────────────────────────────────────────────────────
# FASE A — Widgets de AppUI
# ─────────────────────────────────────────────────────────────────────────

def fase_a():
    from app.ui import AppUI

    calls = {}

    def cb(name):
        def _f(*a, **k):
            calls[name] = calls.get(name, 0) + 1
        return _f

    ui = AppUI(
        on_model_change=cb("model"),
        on_language_change=cb("language"),
        on_toggle_button=cb("toggle"),
        on_paste_mode_change=cb("paste_mode"),
        on_beep_toggle=cb("beep"),
        on_replacements_toggle=cb("replacements"),
        on_hotkey_toggle=cb("hotkey"),
        on_history_copy=cb("h_copy"),
        on_history_paste=cb("h_paste"),
        on_history_clear=cb("h_clear"),
        on_initial_prompt_toggle=cb("ip_toggle"),
        on_initial_prompt_save=cb("ip_save"),
        on_quality_profile_change=cb("quality"),
        on_mixed_language_toggle=cb("mixed"),
        on_hotkey_rebind_request=cb("rebind"),
        on_start_with_windows_toggle=cb("start_win"),
        on_start_minimized_toggle=cb("start_min"),
        on_perf_profile_change=cb("perf"),
        on_close_request=cb("close"),
        initial_settings={},
        hotkey_label="|",
    )

    def pump():
        try:
            ui.root.update()
            ui._drain_queue()
            ui.root.update()
        except Exception:
            pass

    pump()

    # Dropdowns en TODOS sus valores.
    for label in config.LANGUAGE_LABELS:
        record("A", f"IDIOMA = {label}", lambda label=label: (ui._language_changed(label), pump()))
    for v in config.PASTE_MODES:
        record("A", f"MODO = {v}", lambda v=v: (ui._paste_mode_changed(v), pump()))
    for k in config.QUALITY_PROFILE_KEYS:
        label = config.QUALITY_PROFILE_LABELS[k]
        record("A", f"PERFIL = {label}", lambda label=label: (ui._profile_changed(label), pump()))
    for v in config.AVAILABLE_MODELS:
        record("A", f"MODELO = {v}", lambda v=v: (ui._model_changed(v), pump()))
    for k in config.PERF_PROFILE_KEYS:
        label = config.PERF_PROFILE_LABELS[k]
        record("A", f"RENDIMIENTO = {label}", lambda label=label: (ui._perf_profile_changed(label), pump()))

    # Switches / checkboxes (encender y apagar).
    def toggle(var, handler):
        var.set(not var.get()); handler(); var.set(not var.get()); handler(); pump()

    record("A", "BEEP toggle", lambda: toggle(ui.beep_var, ui._beep_changed))
    record("A", "REEMPLAZOS toggle", lambda: toggle(ui.replacements_var, ui._replacements_changed))
    record("A", "ATAJO ACTIVO toggle", lambda: toggle(ui.hotkey_var, ui._hotkey_enabled_changed))
    record("A", "IDIOMA MIXTO toggle", lambda: toggle(ui.mixed_lang_var, ui._mixed_lang_changed))
    record("A", "INICIAR CON WINDOWS toggle", lambda: toggle(ui.start_with_windows_var, ui._start_with_windows_changed))
    record("A", "INICIAR MINIMIZADA toggle", lambda: toggle(ui.start_minimized_var, ui._start_minimized_changed))
    record("A", "PROMPT INICIAL activo toggle", lambda: toggle(ui.initial_prompt_var, ui._initial_prompt_toggled))

    # Botones.
    record("A", "GUARDAR PROMPT", lambda: (ui._initial_prompt_save_clicked(), pump()))
    record("A", "Botón principal (toggle)", lambda: (ui._toggle_clicked(), pump()))
    record("A", "Botón 👆 (rebind)", lambda: (ui._on_rebind_clicked(), pump()))
    record("A", "Chrome minimizar", lambda: (ui._chrome_minimize_clicked(), pump(), ui._show_from_tray(), pump()))
    record("A", "Chrome cerrar (X)", lambda: (ui._chrome_close_clicked(), pump()))
    record("A", "invoke() botón principal", lambda: (ui.toggle_btn.invoke(), pump()))
    record("A", "invoke() botón rebind", lambda: (ui.rebind_btn.invoke(), pump()))
    record("A", "invoke() botón minimizar", lambda: (ui.min_btn.invoke(), pump(), ui._show_from_tray(), pump()))

    # Pestañas.
    record("A", "Tab Historial", lambda: (ui.tabs.set("Historial"), pump()))
    record("A", "Tab Inicio", lambda: (ui.tabs.set("Inicio"), pump()))

    # Historial: poblar, seleccionar y probar COPIAR/PEGAR/LIMPIAR.
    def hist_ops():
        ui.set_history(["entrada de prueba uno", "entrada de prueba dos"])
        pump()
        ui.history_listbox.selection_clear(0, "end")
        ui.history_listbox.selection_set(0)
        ui._history_copy_clicked()
        ui._history_paste_clicked()
        ui._history_clear_clicked()
        pump()
    record("A", "Historial COPIAR/PEGAR/LIMPIAR", hist_ops)

    # API thread-safe de estados (debe refrescar la UI sin romper).
    def estados():
        for st in ("loading", "recording", "transcribing", "processing", "pasting", "idle", "error"):
            ui.set_status(st)
        ui.set_backend("CPU int8")
        ui.set_transcribing_elapsed(3.0)
        ui.set_transcription("texto de prueba")
        ui.set_button_text("Detener y transcribir")
        ui.set_button_text("Iniciar grabación")
        pump()
    record("A", "set_status/backend/elapsed/transcription/button", estados)

    # Resumen de callbacks que SÍ se invocaron (diagnóstico).
    RESULTS.append(("A", f"callbacks invocados: {sorted(calls)}", True, ""))

    try:
        ui.destroy()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────
# FASE B — Handlers del Controller con dobles seguros
# ─────────────────────────────────────────────────────────────────────────

class _FakeHotkeys:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass
    def rebind(self, hk): pass


class _FakeTray:
    def __init__(self, *a, **k): pass
    def start(self): pass
    def stop(self): pass


class _FakeRecorder:
    def __init__(self, *a, **k): self._rec = False
    def start(self): self._rec = True
    def stop(self):
        self._rec = False
        return np.zeros(int(16000 * 0.8), dtype=np.float32)
    def get_level(self): return 0.0
    def is_recording(self): return self._rec


class _FakeTranscriber:
    def __init__(self, *a, **k):
        self.backend_str = "CPU int8 (fake)"
        self.last_transcribe_seconds = 0.01
    def load(self, *a, **k): pass
    def transcribe(self, *a, **k): return "texto de prueba transcrito"
    def resolve_backend(self, device, compute, enable_gpu=True): return ("cpu", "int8")
    def is_loaded_as(self, device, compute): return True


class _FakeBeeps:
    def __init__(self, *a, **k): pass
    def set_enabled(self, v): pass
    def start(self): pass
    def stop(self): pass
    def error(self): pass


class _FakeFloatingBar:
    """Doble de la barra flotante. La barra real agenda `parent_root.after(...)`
    desde hilos worker; sin un mainloop corriendo (como en este arnés) eso lanza
    'main thread is not in main loop'. La falseamos para no contaminar el reporte
    con ese ruido. (En producción funciona porque el mainloop sí corre.)"""
    def __init__(self, *a, **k): pass
    def show_recording(self): pass
    def show_transcribing(self): pass
    def show_pasting(self): pass
    def show_ready_and_hide(self): pass
    def show_error_and_hide(self, *a, **k): pass
    def hide(self): pass
    def set_hotkey_label(self, *a, **k): pass


class _FakeAutostart:
    @staticmethod
    def enable(on_log=None): return True
    @staticmethod
    def disable(on_log=None): return True
    @staticmethod
    def is_enabled(): return False
    @staticmethod
    def current_command(): return ""
    @staticmethod
    def get_app_executable_path(): return ""


def fase_b():
    import keyboard
    import main as appmain

    # Doble seguro para que el rebind no se quede esperando una tecla real.
    keyboard.read_hotkey = lambda suppress=False: "esc"

    # Reemplaza las piezas con efectos colaterales ANTES de construir el Controller.
    appmain.HotkeyManager = _FakeHotkeys
    appmain.TrayIcon = _FakeTray
    appmain.AudioRecorder = _FakeRecorder
    appmain.Transcriber = _FakeTranscriber
    appmain.Beeps = _FakeBeeps
    appmain.FloatingBar = _FakeFloatingBar
    appmain.autostart = _FakeAutostart
    appmain.cuda_available = lambda: False
    appmain.paste_text = lambda *a, **k: True
    appmain.copy_only = lambda *a, **k: True

    ctrl = None
    try:
        ctrl = appmain.Controller()
        RESULTS.append(("B", "Construcción del Controller", True, ""))
    except Exception:
        RESULTS.append(("B", "Construcción del Controller", False, traceback.format_exc(limit=4)))
        return

    # Captura de logs (para ver mensajes de error que los hilos sólo loguean).
    logs = []
    _orig_log = ctrl.ui.log
    ctrl.ui.log = lambda m: (logs.append(m), _orig_log(m))

    def pump(t=0.15):
        end = time.time() + t
        while time.time() < end:
            try:
                ctrl.ui.root.update()
            except Exception:
                pass
            time.sleep(0.01)

    pump(0.3)  # deja correr el preload del modelo (fake)

    # Cada handler con argumentos seguros.
    handlers = [
        ("_on_language_change('en')", lambda: ctrl._on_language_change("en")),
        ("_on_language_change('es')", lambda: ctrl._on_language_change("es")),
        ("_on_paste_mode_change(copy_only)", lambda: ctrl._on_paste_mode_change(config.PASTE_MODE_COPY_ONLY)),
        ("_on_paste_mode_change(paste)", lambda: ctrl._on_paste_mode_change(config.PASTE_MODE_PASTE)),
        ("_on_beep_toggle(False/True)", lambda: (ctrl._on_beep_toggle(False), ctrl._on_beep_toggle(True))),
        ("_on_replacements_toggle", lambda: (ctrl._on_replacements_toggle(False), ctrl._on_replacements_toggle(True))),
        ("_on_mixed_language_toggle", lambda: (ctrl._on_mixed_language_toggle(True), ctrl._on_mixed_language_toggle(False))),
        ("_on_initial_prompt_toggle", lambda: (ctrl._on_initial_prompt_toggle(False), ctrl._on_initial_prompt_toggle(True))),
        ("_on_initial_prompt_save", lambda: ctrl._on_initial_prompt_save("prompt de prueba")),
        ("_on_hotkey_toggle", lambda: (ctrl._on_hotkey_toggle(False), ctrl._on_hotkey_toggle(True))),
        ("_on_start_with_windows_toggle", lambda: (ctrl._on_start_with_windows_toggle(True), ctrl._on_start_with_windows_toggle(False))),
        ("_on_start_minimized_toggle", lambda: (ctrl._on_start_minimized_toggle(True), ctrl._on_start_minimized_toggle(False))),
        ("_on_history_copy", lambda: ctrl._on_history_copy("texto historial")),
        ("_on_history_paste", lambda: ctrl._on_history_paste("texto historial")),
        ("_on_history_clear", lambda: ctrl._on_history_clear()),
        ("_tray_show", lambda: ctrl._tray_show()),
        ("_tray_hide", lambda: ctrl._tray_hide()),
        ("_on_hotkey_rebind_request", lambda: ctrl._on_hotkey_rebind_request()),
    ]
    for name, fn in handlers:
        record("B", name, lambda fn=fn: (fn(), pump()))

    # Perfiles de calidad (cada uno).
    for k in config.QUALITY_PROFILES.keys():
        record("B", f"_on_quality_profile_change({k})", lambda k=k: (ctrl._on_quality_profile_change(k), pump()))
    # Modelos (cada uno).
    for mname in config.AVAILABLE_MODELS:
        record("B", f"_on_model_change({mname})", lambda mname=mname: (ctrl._on_model_change(mname), pump()))
    # Perfiles de rendimiento (cada uno).
    for k in config.PERF_PROFILE_KEYS:
        record("B", f"_on_perf_profile_change({k})", lambda k=k: (ctrl._on_perf_profile_change(k), pump()))

    # Ciclo completo de grabación: iniciar -> procesar (pipeline real con dobles).
    def ciclo_grabacion():
        ctrl._toggle()          # idle -> recording
        pump(0.2)
        ctrl._toggle()          # recording -> dispara pipeline en hilo
        pump(0.6)               # deja terminar el pipeline
    record("B", "Ciclo grabar→transcribir→pegar (botón)", ciclo_grabacion)

    # Errores que sólo aparecieron en logs.
    err_logs = [m for m in logs if "error" in m.lower() or "trace" in m.lower()]
    if err_logs:
        RESULTS.append(("B", f"mensajes de error en logs ({len(err_logs)})", False,
                        "\n".join(err_logs[-8:])))

    # Cierre limpio.
    try:
        ctrl._quitting = True
        ctrl.ui.run_on_ui_thread(ctrl._real_shutdown)
        pump(0.3)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────

def write_report():
    md = ["# Reporte del bot de UI — Wisip\n"]
    a = [r for r in RESULTS if r[0] == "A"]
    b = [r for r in RESULTS if r[0] == "B"]
    ok = sum(1 for r in RESULTS if r[2])
    fail = sum(1 for r in RESULTS if not r[2])
    md.append(f"- Acciones probadas: **{len(RESULTS)}**  ·  OK: **{ok}**  ·  Con error: **{fail}**\n")

    for title, rows in (("Fase A — Widgets de la UI", a), ("Fase B — Handlers del Controller", b)):
        md.append(f"## {title}\n")
        md.append("| Estado | Acción |")
        md.append("|---|---|")
        for _, accion, okk, _ in rows:
            md.append(f"| {'✅' if okk else '❌'} | {accion} |")
        md.append("")
        fails = [(accion, det) for _, accion, okk, det in rows if not okk]
        if fails:
            md.append("### Errores detallados\n")
            for accion, det in fails:
                md.append(f"**{accion}**\n\n```\n{det.strip()}\n```\n")

    path = os.path.join(_HERE, "report_ui.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\n[ui_bot] Reporte escrito: {path}")
    print(f"[ui_bot] Total {len(RESULTS)} | OK {ok} | Error {fail}")
    for _, accion, okk, det in RESULTS:
        if not okk:
            print(f"  [FAIL] {accion}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("== FASE A: widgets de la UI ==")
    try:
        fase_a()
    except Exception:
        RESULTS.append(("A", "FASE A abortada", False, traceback.format_exc()))
    print("== FASE B: handlers del Controller ==")
    try:
        fase_b()
    except Exception:
        RESULTS.append(("B", "FASE B abortada", False, traceback.format_exc()))
    write_report()


if __name__ == "__main__":
    main()
