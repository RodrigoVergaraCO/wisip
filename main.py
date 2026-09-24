import ctypes
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


def _reexec_with_venv_if_needed():
    """Relanza main.py con el pythonw del .venv si se abrió con otro Python.

    Doble clic en main.py usa el Python del sistema: sin las libs CUDA del
    venv, faster-whisper cae a CPU int8 y cada dictado tarda ~15s (incidentes
    2026-07-16 y 2026-07-20). WISIP_NO_VENV_REEXEC=1 desactiva el guard.
    """
    if getattr(sys, "frozen", False) or sys.prefix != sys.base_prefix:
        return  # empaquetado, o ya corremos dentro de un venv
    if os.environ.get("WISIP_NO_VENV_REEXEC"):
        return
    scripts = Path(__file__).resolve().parent / ".venv" / "Scripts"
    interpreter = scripts / "pythonw.exe"
    if not interpreter.exists():
        interpreter = scripts / "python.exe"
        if not interpreter.exists():
            return
    import subprocess
    subprocess.Popen(
        [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=str(Path(__file__).resolve().parent),
    )
    sys.exit(0)


_reexec_with_venv_if_needed()

from app import config


def _set_app_user_model_id():
    """Asigna AppUserModelID antes de crear cualquier ventana Tk para que la
    barra de tareas de Windows agrupe la app como 'Wisip' (con su icono) y no
    como 'Python'."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            config.APP_USER_MODEL_ID
        )
    except Exception:
        pass


_set_app_user_model_id()
from app import autostart
from app import error_log
from app import audio_devices
from app import setup_assets
from app import themes
from app import vocab
from app import updater
from app.license import LicenseManager
from app.version import __version__
from app.onboarding import OnboardingWizard, default_result as onboarding_defaults
from app.setup_window import SetupWindow
from app.audio_recorder import AudioRecorder, DIGITAL_SILENCE_PEAK, is_digital_silence
from app.beeps import Beeps
from app.dictation_log import DictationLog
from app.floating_bar import FloatingBar
from app.history import History
from app.hotkeys import MultiHotkeyManager
from app.incremental import IncrementalSession
from app.postprocessor import normalize_emails_urls_symbols
from app.replacements import Replacements
from app.settings import Settings
from app.single_instance import enforce_single_instance
from app.transcriber import Transcriber, cuda_available
from app import translator as mt
from app.tray import TrayIcon
from app.typer import clean_text, copy_only, paste_text
from app.ui import AppUI


class Controller:
    """Orquesta settings, UI, tray, hotkey push-to-talk, grabación,
    transcripción, reemplazos, historial, pegado/copia y barra flotante."""

    def __init__(self):
        self._pending_logs: list = []

        def buf_log(msg):
            self._pending_logs.append(msg)

        # Configuración y datos persistentes
        self.settings = Settings(on_log=buf_log)
        self.replacements = Replacements(
            on_log=buf_log,
            tech_mode_getter=lambda: bool(self.settings.get("tech_mode")),
        )
        self.history = History(on_log=buf_log)
        self.dictation_log = DictationLog(on_log=buf_log)
        self.beeps = Beeps(enabled=bool(self.settings.get("beep_enabled")), on_log=buf_log)
        self.license = LicenseManager(self.settings, on_log=buf_log)

        # UI principal
        self.ui = AppUI(
            on_model_change=self._on_model_change,
            on_language_change=self._on_language_change,
            on_toggle_button=self._toggle,
            on_paste_mode_change=self._on_paste_mode_change,
            on_beep_toggle=self._on_beep_toggle,
            on_replacements_toggle=self._on_replacements_toggle,
            on_hotkey_toggle=self._on_hotkey_toggle,
            on_history_copy=self._on_history_copy,
            on_history_paste=self._on_history_paste,
            on_history_clear=self._on_history_clear,
            on_initial_prompt_toggle=self._on_initial_prompt_toggle,
            on_initial_prompt_save=self._on_initial_prompt_save,
            on_quality_profile_change=self._on_quality_profile_change,
            on_mixed_language_toggle=self._on_mixed_language_toggle,
            on_hotkey_rebind_request=self._on_hotkey_rebind_request,
            on_start_with_windows_toggle=self._on_start_with_windows_toggle,
            on_start_minimized_toggle=self._on_start_minimized_toggle,
            on_perf_profile_change=self._on_perf_profile_change,
            on_close_request=self._on_close_request,
            on_theme_change=self._on_theme_change,
            on_vocab_hotwords_save=self._on_vocab_hotwords_save,
            on_vocab_tokens=self._on_vocab_tokens,
            on_vocab_list=self._on_vocab_list,
            on_vocab_add=self._on_vocab_add,
            on_vocab_remove=self._on_vocab_remove,
            on_vocab_analyze=self._on_vocab_analyze,
            on_vocab_ignore=self._on_vocab_ignore,
            on_gpu_pack_install=self._on_gpu_pack_install,
            on_input_device_change=self._on_input_device_change,
            on_license_activate=self._on_license_activate,
            on_license_deactivate=self._on_license_deactivate,
            on_translate_target_change=self._on_translate_target_change,
            translate_hotkey_label=self.settings.get("hotkey_translate"),
            on_update_install=self._on_update_install_clicked,
            on_check_updates=self._on_check_updates_clicked,
            on_auto_update_toggle=self._on_auto_update_toggle,
            initial_settings=self.settings.all(),
            hotkey_label=self.settings.get("hotkey"),
        )
        # Volcar logs pendientes ahora que la UI existe
        for m in self._pending_logs:
            self._log(m)
        self._pending_logs = None
        self.settings.on_log = self._log
        self.license.on_log = self._log
        self.replacements.on_log = self._log
        self.history.on_log = self._log
        self.dictation_log.on_log = self._log
        self.beeps.on_log = self._log

        # Instancia única: cierra cualquier Wisip previo (dos instancias pelean
        # por el hotkey y el micrófono) y vigila para cerrarse cuando el usuario
        # abra uno nuevo. Antes de crear recorder/hotkeys para arrancar limpio.
        enforce_single_instance(on_quit=self._tray_quit, on_log=self._log)

        # Componentes runtime
        self.recorder = AudioRecorder(on_log=self._log)
        self._apply_input_device_setting()
        self._onboarding: OnboardingWizard | None = None
        self._onboarding_done = threading.Event()
        self._gpu_pack_preapproved = False
        self.transcriber = Transcriber(on_log=self._log)
        self.hotkeys = MultiHotkeyManager(
            on_press=self._hotkey_press,
            on_release=self._hotkey_release,
            on_switch=self._hotkey_switch,
            on_log=self._log,
            hotkeys={"dictate": self.settings.get("hotkey"),
                     "translate": self.settings.get("hotkey_translate")},
            is_enabled=lambda: bool(self.settings.get("hotkey_enabled")),
        )
        self.translator = mt.Translator(on_log=self._log)
        self._recording_mode = "dictate"      # "dictate" | "translate"
        self._rebind_target = "dictate"
        self.floating_bar = FloatingBar(
            parent_root=self.ui.root,
            hotkey_label=self.settings.get("hotkey"),
            get_level=self.recorder.get_level,
            on_log=self._log,
        )
        self.tray = TrayIcon(
            on_show=self._tray_show,
            on_hide=self._tray_hide,
            on_quit=self._tray_quit,
            on_log=self._log,
        )

        self._state = "idle"
        self._state_lock = threading.Lock()
        self._rebinding = False
        self._recording_source: str | None = None  # "hotkey" o "button"
        self._inc_session: IncrementalSession | None = None
        self._model_ready = threading.Event()
        self._quitting = False
        # Sincroniza press → release para evitar race en taps muy rápidos.
        self._press_done = threading.Event()
        self._press_done.set()
        # CapsLock state save/restore
        self._capslock_was_on: bool | None = None

        self.ui.set_history(self.history.items())
        # Preparación inicial en segundo plano: paquete NVIDIA (si hay GPU y
        # falta) → autotune de perfil/modelo → descarga del modelo con progreso
        # → carga. El autotune va DESPUÉS del paquete para que vea las DLLs.
        self._setup_busy = threading.Lock()
        self._model_download_failed = False
        self._last_activity = time.time()
        self._pending_update: dict | None = None
        self._pending_installer = None
        self._update_lock = threading.Lock()
        threading.Thread(target=self._preload_default_model, daemon=True).start()

        try:
            self.hotkeys.start()
        except Exception:
            self._log("[hotkey] No se pudo registrar el hotkey. Prueba cambiar el "
                      "atajo (botón 👆) o ejecutar como administrador si quieres "
                      "controlar apps elevadas.")

        self.tray.start()

        # Reconcilia el registro de autostart con la preferencia guardada, por si
        # el usuario movió/reinstaló el .exe (la ruta del Run apuntaría a algo viejo).
        self._sync_autostart_on_launch()

        if self.settings.get("start_minimized"):
            self.ui.hide_to_tray()
            self._log("[app] arranque minimizado al tray")

    # ---------------- logging / estado ----------------
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.ui.log(f"{ts}  {msg}")

    def _set_state(self, state: str):
        self._state = state
        if state not in ("idle", "loading"):
            self._last_activity = time.time()
        self.ui.set_status(state)
        self._update_floating_bar(state)

    def _update_floating_bar(self, state: str):
        # `loading` no toca la barra flotante (sólo se ve en la ventana principal).
        if state == "recording":
            self.floating_bar.show_recording()
        elif state in ("transcribing", "processing"):
            self.floating_bar.show_transcribing()
        elif state == "pasting":
            self.floating_bar.show_pasting()
        elif state == "idle":
            self.floating_bar.show_ready_and_hide()
        elif state == "error":
            self.floating_bar.show_error_and_hide("Error")

    # ---------------- modelo ----------------
    def _perf_params(self) -> dict:
        """Resuelve device/compute/batching según el perfil de rendimiento.
        Si el perfil es 'Personalizado', usa device/compute_type crudos de
        settings. cpu_threads/num_workers/enable_gpu siempre vienen de settings."""
        prof = self.settings.get("performance_profile")
        p = config.PERF_PROFILES.get(prof)
        if p is None:  # custom
            device = self.settings.get("device")
            compute = self.settings.get("compute_type")
            batched = bool(self.settings.get("batched"))
            batch_size = int(self.settings.get("batch_size"))
        else:
            device = p["device"]
            compute = p["compute_type"]
            batched = p["batched"]
            batch_size = int(p["batch_size"])
        return {
            "device": device,
            "compute_type": compute,
            "cpu_threads": int(self.settings.get("cpu_threads")),
            "num_workers": int(self.settings.get("num_workers")),
            "enable_gpu": bool(self.settings.get("enable_gpu_if_available")),
            "batched": batched,
            "batch_size": batch_size,
        }

    def _load_model_now(self, model_name: str, prev_state: str | None = None):
        pp = self._perf_params()
        self._set_state("loading")
        try:
            self.transcriber.load(
                model_name,
                device=pp["device"],
                compute_type=pp["compute_type"],
                cpu_threads=pp["cpu_threads"],
                num_workers=pp["num_workers"],
                enable_gpu=pp["enable_gpu"],
            )
            self.ui.set_backend(self.transcriber.backend_str)
            self._model_ready.set()
            keep = prev_state if prev_state == "recording" else "idle"
            self._set_state(keep)
        except Exception as e:
            self._log(f"[whisper] error cargando '{model_name}': {e}")
            error_log.log_error(f"error cargando modelo '{model_name}'", e)
            self._set_state("error")
            self.beeps.error()
            # Sin diálogo, un fallo aquí deja la app en "ERROR" sin explicación
            # (la 1ª descarga del modelo necesita internet; el AV puede bloquear).
            error_log.show_error_dialog_async(
                "Wisip — no se pudo cargar el modelo",
                f"No se pudo cargar el modelo '{model_name}'.\n\n"
                "Causas típicas:\n"
                "• Primera vez con este modelo: se necesita internet para "
                "descargarlo.\n"
                "• Antivirus bloqueando archivos de Wisip.\n"
                "• Disco lleno.\n\n"
                f"Detalle: {type(e).__name__}: {e}\n\n"
                f"Log completo: {config.ERROR_LOG_PATH}",
            )

    def _autotune_perf_profile(self):
        """Migraciones únicas cuando hay GPU NVIDIA usable. No pisan elecciones
        deliberadas: solo migran desde defaults y una sola vez (banderas
        'perf_autotuned' / 'model_autotuned').

        1. Perfil de rendimiento: del antiguo default 'Calidad actual' (CPU
           secuencial) a 'Rápido seguro' (GPU float16 + batched).
        2. Modelo: de los modelos CPU (tiny/base/small/medium) al perfil de
           calidad 'Preciso GPU' (large-v3-turbo float16), que en GPU es a la
           vez el MÁS preciso y más rápido que small.
        """
        gpu = False
        try:
            # cuda_available() da True con solo el driver NVIDIA instalado;
            # sin las DLLs (cuBLAS/cuDNN) la GPU no es usable de verdad.
            gpu = cuda_available() and config.cuda_dlls_present()
        except Exception:
            pass

        # ── 1. Perfil de rendimiento ──
        try:
            if not self.settings.get("perf_autotuned"):
                if (self.settings.get("performance_profile") == config.PERF_PROFILE_QUALITY
                        and gpu):
                    self.settings.set("performance_profile", config.PERF_PROFILE_FAST_SAFE)
                    self.ui.set_perf_profile(config.PERF_PROFILE_FAST_SAFE)
                    self._log("[perf] GPU NVIDIA detectada → perfil 'Rápido seguro' "
                              "activado automáticamente (misma calidad, mucho más "
                              "rápido). Puedes cambiarlo en RENDIMIENTO.")
        except Exception as e:
            self._log(f"[perf] autotune de rendimiento falló: {e}")
        finally:
            try:
                self.settings.set("perf_autotuned", True)
            except Exception:
                pass

        # ── 2. Modelo recomendado para GPU ──
        try:
            if self.settings.get("model_autotuned"):
                return
            eligible_profiles = (
                config.QUALITY_PROFILE_FAST,
                config.QUALITY_PROFILE_BALANCED,
                config.QUALITY_PROFILE_ACCURATE,
            )
            if (gpu
                    and self.settings.get("model") != config.GPU_RECOMMENDED_MODEL
                    and self.settings.get("quality_profile") in eligible_profiles):
                profile = config.QUALITY_PROFILES[config.QUALITY_PROFILE_ACCURATE_GPU]
                self.settings.set("quality_profile", config.QUALITY_PROFILE_ACCURATE_GPU)
                for k, v in profile.items():
                    self.settings.set(k, v)
                self.ui.set_quality_profile(config.QUALITY_PROFILE_ACCURATE_GPU)
                self.ui.set_model(profile["model"])
                self._log(f"[perf] GPU NVIDIA detectada → perfil 'Preciso GPU' "
                          f"({config.GPU_RECOMMENDED_MODEL} float16): máxima "
                          f"precisión y más rápido que 'small'. La primera vez "
                          f"descarga ~1.6GB. Puedes cambiarlo en PERFIL.")
        except Exception as e:
            self._log(f"[perf] autotune de modelo falló: {e}")
        finally:
            try:
                self.settings.set("model_autotuned", True)
            except Exception:
                pass

    def _preload_default_model(self):
        try:
            self.license.ensure_trial_started()
            self.ui.set_license_status(self.license.status())
        except Exception as e:
            self._log(f"[licencia] estado inicial falló: {e}")
        try:
            self._maybe_run_onboarding()
        except Exception as e:
            self._log(f"[onboarding] falló: {e}")
            error_log.log_error("asistente inicial", e)
        try:
            self._first_run_setup()
        except Exception as e:
            self._log(f"[setup] preparación inicial falló: {e}")
            error_log.log_error("preparación inicial", e)
        if self._model_download_failed:
            self._set_state("error")
            self.beeps.error()
            return
        self._load_model_now(self.settings.get("model"))
        try:
            self.license.revalidate_if_due()
            self.ui.set_license_status(self.license.status())
        except Exception as e:
            self._log(f"[licencia] revalidación falló: {e}")
        self._start_update_loop()

    # ─── Auto-actualización (2.11.0) ───

    def _start_update_loop(self):
        if not bool(self.settings.get("auto_update_check")):
            self._log("[update] comprobación de actualizaciones desactivada")
            return
        threading.Thread(target=self._update_loop, daemon=True, name="updater").start()

    def _update_loop(self):
        time.sleep(15)
        while not self._quitting:
            try:
                self._check_and_maybe_update(manual=False)
            except Exception as e:
                self._log(f"[update] error: {e}")
            for _ in range(6 * 60 * 12):   # 6 h en pasos de 5 s
                if self._quitting:
                    return
                time.sleep(5)

    def _check_and_maybe_update(self, manual: bool):
        if not self._update_lock.acquire(blocking=False):
            return
        try:
            info = updater.check_latest(self._log)
            try:
                self.settings.set("update_last_check", str(time.time()))
            except Exception:
                pass
            if not updater.is_update_available(info):
                self._pending_update = None
                self.ui.set_update_status(f"Versión {__version__} · al día")
                if manual:
                    self.ui.set_update_banner(None)
                return
            self._pending_update = info
            self.ui.set_update_status(f"Versión {__version__} · disponible {info['version']}")
            self._log(f"[update] nueva versión {info['version']} (actual {__version__})")
            try:
                path = updater.download_update(info, on_log=self._log)
            except Exception as e:
                self._log(f"[update] descarga falló: {e}")
                self.ui.set_update_banner(f"Nueva versión {info['version']} disponible", info.get("html_url"))
                return
            self._pending_installer = path
            if bool(self.settings.get("auto_update_install")) and not manual:
                self._install_when_idle(info, path)
            else:
                self.ui.set_update_banner(f"Wisip {info['version']} lista para instalar")
        finally:
            self._update_lock.release()

    def _install_when_idle(self, info: dict, path):
        """Espera (hasta 30 min) un momento sin dictado y actualiza sola."""
        for _ in range(360):
            if self._quitting:
                return
            with self._state_lock:
                idle = self._state == "idle"
            quiet = (time.time() - self._last_activity) > 60
            if idle and quiet and self._onboarding is None and not self._rebinding:
                break
            time.sleep(5)
        else:
            self.ui.set_update_banner(f"Wisip {info['version']} lista para instalar")
            return
        self._log(f"[update] instalando Wisip {info['version']} automáticamente")
        try:
            self.tray.notify(f"Actualizando a Wisip {info['version']}. Se reiniciará en unos segundos.")
        except Exception:
            pass
        self._do_install_update(path)

    def _do_install_update(self, path):
        if not updater.install_update(path, self._log):
            self.ui.set_update_banner(f"Wisip {self._pending_update['version'] if self._pending_update else ''} lista para instalar")
            return
        # Cierre limpio: el instalador también manda el evento de cierre.
        time.sleep(1.0)
        self._quitting = True
        self.ui.run_on_ui_thread(self._real_shutdown)

    def _on_update_install_clicked(self):
        def worker():
            if self._pending_installer is not None:
                self._do_install_update(self._pending_installer)
            elif self._pending_update and self._pending_update.get("html_url"):
                import webbrowser
                webbrowser.open(self._pending_update["html_url"])
            else:
                self._check_and_maybe_update(manual=True)
        threading.Thread(target=worker, daemon=True, name="update-install").start()

    def _on_check_updates_clicked(self):
        threading.Thread(target=self._check_and_maybe_update, args=(True,), daemon=True, name="update-check").start()

    def _on_auto_update_toggle(self, enabled: bool):
        self.settings.set("auto_update_install", bool(enabled))

    # ─── Licencias (2.9.0) ───

    def _license_blocked_feedback(self):
        st = self.license.status()
        self._log(f"[licencia] dictado bloqueado: {st.get('message')}")
        self.beeps.error()
        try:
            self.floating_bar.show_error_and_hide("Activa tu licencia", delay_ms=2600)
        except Exception:
            pass
        self.ui.set_license_status(st)
        try:
            self.ui.show_from_tray()
            self.ui.run_on_ui_thread(lambda: self.ui.tabs.set("Licencia"))
        except Exception:
            pass

    def _on_license_activate(self, key: str):
        def worker():
            ok, msg = self.license.activate(key)
            self.ui.set_license_result(msg, error=not ok)
            self.ui.set_license_status(self.license.status())
        threading.Thread(target=worker, daemon=True, name="license-activate").start()

    def _on_license_deactivate(self):
        def worker():
            ok, msg = self.license.deactivate()
            self.ui.set_license_result(msg, error=not ok)
            self.ui.set_license_status(self.license.status())
        threading.Thread(target=worker, daemon=True, name="license-deactivate").start()

    # ─── Micrófono (2.8.0) ───

    def _apply_input_device_setting(self):
        name = str(self.settings.get("input_device_name") or "")
        idx = audio_devices.resolve_device_index(name)
        self.recorder.set_device(idx)
        if name and idx is None:
            self._log(f"[audio] micrófono guardado '{name}' no está conectado: usando el predeterminado")
        elif name:
            self._log(f"[audio] micrófono: '{name}' (índice {idx})")

    def _on_input_device_change(self, name: str):
        self.settings.set("input_device_name", name or "")
        self._apply_input_device_setting()

    def _on_device_preview(self, name):
        """Asistente inicial: abre/cierra el monitor de nivel sobre el micro
        elegido (None = cerrar). Corre en el hilo de Tk; es barato."""
        if name is None:
            self.recorder.stop_monitor()
            return True
        idx = audio_devices.resolve_device_index(name)
        self.recorder.set_device(idx)
        return self.recorder.start_monitor()

    # ─── Asistente inicial (2.8.0) ───

    def _maybe_run_onboarding(self):
        """Corre en el hilo de preload. Bloquea hasta que el usuario termina."""
        if bool(self.settings.get("first_run_done")):
            return
        # Idioma de dictado por defecto según el idioma de Windows (solo la
        # primera vez; el asistente lo muestra preseleccionado y se puede cambiar).
        try:
            if config.system_language() == "en" and self.settings.get("language") == config.LANGUAGE:
                self.settings.set("language", "en")
                self._log("[onboarding] Windows en inglés: idioma de dictado inicial = en")
        except Exception:
            pass
        gpu = None
        try:
            gpu = self._gpu_pack_needed()
        except Exception:
            gpu = None
        if os.environ.get("WISIP_SETUP_AUTO_YES") == "1":
            self._log("[onboarding] modo automático (WISIP_SETUP_AUTO_YES): valores por defecto")
            self._on_onboarding_finished(onboarding_defaults(self.settings.all(), gpu))
            return
        try:
            devices = audio_devices.list_input_devices()
        except Exception:
            devices = []
        pal = themes.get_palette(self.settings.get("ui_theme") or themes.DEFAULT_THEME)
        self._onboarding_done.clear()

        def _build():
            try:
                self._onboarding = OnboardingWizard(
                    self.ui.root, palette=pal, initial=self.settings.all(),
                    devices=devices, hotkey_label=self.settings.get("hotkey"),
                    gpu_info=gpu, get_level=self.recorder.get_level,
                    on_device_preview=self._on_device_preview,
                    on_rebind=self._on_hotkey_rebind_request,
                    on_finish=self._on_onboarding_finished, on_log=self._log,
                )
                self._log("[onboarding] asistente inicial abierto")
            except Exception as e:
                self._log(f"[onboarding] no se pudo abrir: {e}")
                error_log.log_error("abrir asistente inicial", e)
                self._on_onboarding_finished(onboarding_defaults(self.settings.all(), gpu))
        self.ui.run_on_ui_thread(_build)
        self._onboarding_done.wait()

    def _on_onboarding_finished(self, res: dict):
        try:
            self.settings.set("dictation_log_enabled", bool(res.get("dictation_log_enabled", True)))
            self.settings.set("input_device_name", str(res.get("input_device_name") or ""))
            lang = str(res.get("language") or config.LANGUAGE)
            if lang in config.LANGUAGE_CODES:
                self.settings.set("language", lang)
            self.settings.set("mixed_language_mode", bool(res.get("mixed_language_mode", True)))
            gp = res.get("gpu_pack")
            if gp is True:
                self._gpu_pack_preapproved = True
                self.settings.set("gpu_pack_declined", False)
            elif gp is False:
                self.settings.set("gpu_pack_declined", True)
            self.settings.set("first_run_done", True)
            self._apply_input_device_setting()
            self.recorder.stop_monitor()
            self._log(f"[onboarding] terminado: idioma={lang} mixto={res.get('mixed_language_mode')} "
                      f"micro='{res.get('input_device_name') or 'predeterminado'}' "
                      f"registro={res.get('dictation_log_enabled')} gpu={gp}")
        except Exception as e:
            self._log(f"[onboarding] error aplicando resultado: {e}")
        finally:
            self._onboarding = None
            self._onboarding_done.set()

    # ─── Preparación inicial (2.7.0): paquete NVIDIA + modelo con progreso ───

    def _new_setup_window(self) -> SetupWindow:
        pal = themes.get_palette(self.settings.get("ui_theme") or themes.DEFAULT_THEME)
        return SetupWindow(self.ui.root, palette=pal, on_log=self._log)

    def _first_run_setup(self):
        """Corre en el hilo de preload. Muestra la ventana solo si hay algo
        que descargar o preguntar."""
        self._log(f"[cuda] directorios de DLLs registrados: "
                  f"{config.CUDA_DLL_DIRS or 'ninguno'} · usable={config.cuda_dlls_present()}")
        win = self._new_setup_window()
        try:
            self._offer_gpu_pack(win, interactive=not bool(self.settings.get("gpu_pack_declined")),
                                 preapproved=self._gpu_pack_preapproved)
            self._autotune_perf_profile()
            self._refresh_gpu_pack_button()
            self._ensure_model_downloaded(win, self.settings.get("model"))
        finally:
            win.close()

    def _gpu_pack_needed(self) -> dict | None:
        """GPU NVIDIA detectada y sin DLLs CUDA cargables → info de la GPU."""
        if config.cuda_dlls_present():
            return None
        gpu = setup_assets.detect_nvidia_gpu()
        if not gpu:
            return None
        if setup_assets.gpu_pack_installed():
            # Instalado (p.ej. por otra sesión) pero no registrado aún.
            if config.register_cuda_dir(config.GPU_PACK_DIR) and config.cuda_dlls_present():
                self.transcriber.reset_cuda_failed()
                self._log(f"[gpu-pack] paquete NVIDIA cargado desde {config.GPU_PACK_DIR}")
                return None
        return gpu

    def _offer_gpu_pack(self, win: SetupWindow, interactive: bool, preapproved: bool = False):
        gpu = self._gpu_pack_needed()
        if not gpu:
            return
        vram = gpu.get("vram_mb") or 0
        vram_txt = f", {vram / 1024:.0f} GB" if vram else ""
        self._log(f"[gpu-pack] GPU NVIDIA detectada ({gpu['name']}{vram_txt}) sin paquete CUDA")
        if preapproved:
            self._log("[gpu-pack] aceptado en el asistente inicial")
            self._download_gpu_pack(win)
            return
        if not interactive:
            self._log("[gpu-pack] el usuario lo pospuso antes; botón disponible en la pestaña Ajustes")
            return
        ok = win.ask(
            "Acelerar Wisip con tu GPU NVIDIA",
            f"Se detectó {gpu['name']}{vram_txt}. Con la aceleración GPU la "
            f"transcripción es entre 10 y 20 veces más rápida.\n\n"
            f"Descarga única de ~{config.GPU_PACK_DOWNLOAD_MB / 1000:.1f} GB "
            f"(se guarda en tu equipo). Sin ella Wisip funciona igual, en CPU.",
            yes="Descargar", no="Ahora no",
        )
        if not ok:
            self.settings.set("gpu_pack_declined", True)
            self._log("[gpu-pack] pospuesto por el usuario")
            return
        self._download_gpu_pack(win)

    def _download_gpu_pack(self, win: SetupWindow) -> bool:
        win.show(
            "Descargando la aceleración NVIDIA",
            "Una sola vez. Puedes seguir usando el PC; Wisip se activará al terminar.",
            cancellable=True,
        )
        try:
            setup_assets.install_gpu_pack(
                progress=win.set_progress, cancel=win.cancel_event, on_log=self._log,
            )
        except setup_assets.DownloadCancelled:
            self._log("[gpu-pack] descarga cancelada por el usuario")
            self.settings.set("gpu_pack_declined", True)
            win.info("Descarga cancelada",
                     "Wisip funcionará en CPU. Puedes descargar la aceleración "
                     "cuando quieras desde el botón de la pestaña Ajustes.")
            return False
        except setup_assets.DownloadError as e:
            self._log(f"[gpu-pack] error: {e}")
            error_log.log_error("descarga del paquete NVIDIA", e)
            win.info("No se pudo descargar la aceleración",
                     f"{e}\n\nWisip funcionará en CPU. Revisa tu conexión y "
                     "reintenta desde la pestaña Ajustes.")
            return False
        n = config.register_cuda_dir(config.GPU_PACK_DIR)
        self.transcriber.reset_cuda_failed()
        self.settings.set("gpu_pack_declined", False)
        self._log(f"[gpu-pack] {n} directorios de DLLs registrados · CUDA usable: "
                  f"{config.cuda_dlls_present()}")
        return True

    def _refresh_gpu_pack_button(self):
        """Muestra el botón 'Descargar aceleración NVIDIA' solo si hace falta."""
        try:
            gpu = self._gpu_pack_needed()
        except Exception:
            gpu = None
        if gpu:
            self.ui.set_gpu_pack_button(
                f"⚡ Descargar aceleración NVIDIA (~{config.GPU_PACK_DOWNLOAD_MB / 1000:.1f} GB)"
            )
        else:
            self.ui.set_gpu_pack_button(None)

    def _on_gpu_pack_install(self):
        """Botón de la UI. Descarga en un hilo y recarga el modelo en GPU."""
        def worker():
            if not self._setup_busy.acquire(blocking=False):
                self._log("[gpu-pack] ya hay una preparación en curso")
                return
            try:
                win = self._new_setup_window()
                try:
                    ok = self._download_gpu_pack(win)
                finally:
                    win.close()
                self._refresh_gpu_pack_button()
                if ok:
                    # Perfil de rendimiento: si sigue en CPU secuencial, sube.
                    if self.settings.get("performance_profile") == config.PERF_PROFILE_QUALITY:
                        self.settings.set("performance_profile", config.PERF_PROFILE_FAST_SAFE)
                        self.ui.set_perf_profile(config.PERF_PROFILE_FAST_SAFE)
                    self._reload_model(self.settings.get("model"))
            finally:
                self._setup_busy.release()
        threading.Thread(target=worker, daemon=True, name="gpu-pack").start()

    def _ensure_model_downloaded(self, win: SetupWindow, model_name: str) -> bool:
        """Descarga el modelo con progreso si no está en caché. Devuelve True
        si al final está disponible."""
        if setup_assets.model_is_cached(model_name):
            return True
        mb = setup_assets.model_download_mb(model_name)
        size_txt = f"~{mb / 1000:.1f} GB" if mb >= 1000 else f"~{mb} MB"
        self._log(f"[setup] modelo '{model_name}' no está en caché: descargando ({size_txt})")
        self._set_state("loading")
        win.show(
            f"Descargando el modelo de voz ({model_name})",
            f"Primera vez con este modelo: {size_txt}. Se guarda en tu equipo y "
            "no se vuelve a descargar.",
            cancellable=True,
        )
        try:
            setup_assets.download_model(model_name, progress=win.set_progress,
                                        cancel=win.cancel_event)
        except setup_assets.DownloadCancelled:
            self._log("[setup] descarga del modelo cancelada")
            self._model_download_failed = True
            win.info("Descarga cancelada",
                     "Sin el modelo de voz Wisip no puede transcribir. Vuelve a "
                     "abrir Wisip para reintentar la descarga.")
            return False
        except setup_assets.DownloadError as e:
            self._log(f"[setup] error descargando el modelo: {e}")
            error_log.log_error(f"descarga del modelo '{model_name}'", e)
            self._model_download_failed = True
            win.info("No se pudo descargar el modelo",
                     f"{e}\n\nRevisa tu conexión a internet y vuelve a abrir Wisip.")
            return False
        self._log(f"[setup] modelo '{model_name}' descargado")
        return True

    def _on_model_change(self, name: str):
        self.settings.set("model", name)
        self._log(f"[ui] cambio de modelo → '{name}' (perfil → Personalizado)")
        # Cualquier cambio manual de modelo rompe el perfil predefinido.
        self.settings.set("quality_profile", config.QUALITY_PROFILE_CUSTOM)
        self.ui.set_quality_profile(config.QUALITY_PROFILE_CUSTOM)
        self._model_ready.clear()
        threading.Thread(
            target=self._reload_model,
            args=(name, self.settings.get("compute_type")),
            daemon=True,
        ).start()

    def _reload_model(self, name: str, compute_type: str | None = None):
        # compute_type ya no se usa aquí: lo decide el perfil de rendimiento
        # (_perf_params). Se mantiene el parámetro por compatibilidad de llamadas.
        # Modelo nuevo no cacheado → descarga con progreso antes de cargar.
        try:
            if not setup_assets.model_is_cached(name):
                win = self._new_setup_window()
                try:
                    self._model_download_failed = False
                    if not self._ensure_model_downloaded(win, name):
                        self._set_state("error")
                        return
                finally:
                    win.close()
        except Exception as e:
            self._log(f"[setup] descarga previa del modelo falló: {e}")
        self._load_model_now(name, prev_state=self._state)

    # ---------------- benchmark / tiempo transcurrido ----------------
    def _log_benchmark(self, audio_s: float, replacements_s: float, pp: dict,
                       trans_s_override: float | None = None):
        # En modo incremental last_transcribe_seconds solo refleja el último
        # tramo; el total real llega por trans_s_override.
        if trans_s_override is not None:
            trans_s = trans_s_override
        else:
            trans_s = float(getattr(self.transcriber, "last_transcribe_seconds", 0.0) or 0.0)
        ratio = (trans_s / audio_s) if audio_s > 0 else 0.0
        self._log(
            f"[bench] audio={audio_s:.1f}s · transcripcion={trans_s:.2f}s · "
            f"replacements={replacements_s * 1000:.0f}ms · ratio={ratio:.2f}x · "
            f"modelo={self.settings.get('model')} · backend={self.transcriber.backend_str} · "
            f"beam={self.settings.get('beam_size')} · batched={'on' if pp['batched'] else 'off'}"
        )

    def _start_elapsed_timer(self):
        self._elapsed_stop = threading.Event()
        self._elapsed_t0 = time.perf_counter()

        def _tick():
            while not self._elapsed_stop.wait(0.5):
                secs = time.perf_counter() - self._elapsed_t0
                try:
                    self.ui.set_transcribing_elapsed(secs)
                except Exception:
                    pass

        threading.Thread(target=_tick, daemon=True).start()

    def _stop_elapsed_timer(self):
        ev = getattr(self, "_elapsed_stop", None)
        if ev is not None:
            ev.set()

    def _on_perf_profile_change(self, key: str):
        if key not in config.PERF_PROFILE_KEYS:
            return
        self.settings.set("performance_profile", key)
        label = config.PERF_PROFILE_LABELS.get(key, key)
        self._log(f"[perf] perfil de rendimiento → '{label}'")
        if key == config.PERF_PROFILE_MAX_SPEED and not cuda_available():
            self._log("[perf] aviso: no hay GPU NVIDIA usable; 'Máxima velocidad' "
                      "correrá en CPU (batched). Para GPU instala las libs CUDA.")

        # Solo recargamos si cambia el backend real (device/compute). El flag
        # 'batched' y 'batch_size' se aplican en transcribe(), sin recargar.
        pp = self._perf_params()
        device, compute = self.transcriber.resolve_backend(
            pp["device"], pp["compute_type"], pp["enable_gpu"]
        )
        if self.transcriber.is_loaded_as(device, compute):
            self._log(f"[perf] backend sin cambios ({self.transcriber.backend_str}); "
                      f"solo cambia batched. Modelo reutilizado.")
            return
        self._model_ready.clear()
        threading.Thread(
            target=self._reload_model, args=(self.settings.get("model"),), daemon=True
        ).start()

    # ---------------- opciones de UI ----------------
    def _on_language_change(self, code: str):
        if code not in config.LANGUAGE_CODES:
            return
        self.settings.set("language", code)
        self._log(f"[ui] idioma → {code}")

    def _on_paste_mode_change(self, mode: str):
        if mode not in config.PASTE_MODES:
            return
        self.settings.set("paste_mode", mode)
        self.settings.set("auto_paste_enabled", mode == config.PASTE_MODE_PASTE)

    def _on_beep_toggle(self, enabled: bool):
        self.settings.set("beep_enabled", enabled)
        self.beeps.set_enabled(enabled)

    def _on_replacements_toggle(self, enabled: bool):
        self.settings.set("replacements_enabled", enabled)

    def _on_mixed_language_toggle(self, enabled: bool):
        self.settings.set("mixed_language_mode", enabled)
        self._log(
            f"[ui] idioma mixto {'ACTIVADO' if enabled else 'DESACTIVADO'} "
            f"({'es se trata como auto' if enabled else 'es se respeta tal cual'})"
        )

    # ---------------- rebind del hotkey ----------------
    def _on_hotkey_rebind_request(self, target: str = "dictate"):
        if self._rebinding:
            return
        self._rebinding = True
        self._rebind_target = "translate" if target == "translate" else "dictate"
        threading.Thread(target=self._do_rebind, daemon=True).start()

    def _do_rebind(self):
        try:
            self.ui.set_rebind_mode(True, self._rebind_target)
            self._log("[hotkey] esperando nueva combinación... (pulsa la tecla; Esc cancela)")
            # Para a que el hook actual no fire mientras captura la nueva tecla.
            try:
                self.hotkeys.stop()
            except Exception:
                pass

            new_hk = None
            try:
                import keyboard as _kb
                new_hk = _kb.read_hotkey(suppress=False)
            except Exception as e:
                self._log(f"[hotkey] error leyendo nueva tecla: {e}")

            cancelled = (
                not new_hk
                or new_hk.lower() in ("esc", "escape")
            )
            if not cancelled:
                # keyboard.read_hotkey devuelve nombres localizados en un
                # Windows en español ("mayusculas+windows izquierda"):
                # guardamos siempre la forma canónica ("shift+windows").
                from app.hotkeys import canonical_hotkey
                new_hk = canonical_hotkey(new_hk) or new_hk

            if cancelled:
                self._log("[hotkey] rebind cancelado, restaurando hotkey anterior")
                try:
                    self.hotkeys.start()
                except Exception as e:
                    self._log(f"[hotkey] no pude restaurar el hook: {e}")
                wiz = self._onboarding
                if wiz is not None:
                    wiz.set_hotkey(None)
                return

            key_setting = "hotkey_translate" if self._rebind_target == "translate" else "hotkey"
            self.settings.set(key_setting, new_hk)
            try:
                self.hotkeys.rebind(self._rebind_target, new_hk)
            except Exception as e:
                self._log(f"[hotkey] error registrando '{new_hk}': {e}. "
                          f"Edita 'hotkey' en app_settings.json y reinicia.")
                return

            if self._rebind_target == "translate":
                self.ui.update_translate_hotkey_label(new_hk)
            else:
                self.ui.update_hotkey_label(new_hk)
            try:
                self.floating_bar.set_hotkey_label(new_hk)
            except Exception:
                pass
            wiz = self._onboarding
            if wiz is not None:
                wiz.set_hotkey(new_hk)
            self._log(
                f"[hotkey] nueva tecla activa: {new_hk.upper()} "
                f"(la tecla queda suprimida del sistema mientras esté pulsada)"
            )
        finally:
            self.ui.set_rebind_mode(False, self._rebind_target)
            self._rebinding = False

    def _on_initial_prompt_toggle(self, enabled: bool):
        self.settings.set("initial_prompt_enabled", enabled)
        self._log(f"[ui] prompt inicial {'ACTIVADO' if enabled else 'DESACTIVADO'}")

    def _on_initial_prompt_save(self, text: str):
        self.settings.set("initial_prompt", text)
        preview = text if len(text) <= 60 else text[:57] + "…"
        self._log(f"[ui] prompt inicial guardado ({len(text)} chars): {preview!r}")

    # ---- Vocabulario personal (pestaña Vocabulario; lógica en app/vocab.py) ----
    def _on_vocab_hotwords_save(self, text: str):
        self.settings.set("hotwords", text)
        # Se leen de settings en cada dictado → aplican desde el siguiente.
        self._log(f"[vocab] hotwords guardados: {text!r}")

    def _on_vocab_tokens(self, hotwords_text: str):
        return vocab.budget_label(
            self.settings.get("initial_prompt") or "",
            hotwords_text,
            self.settings.get("model") or config.DEFAULT_MODEL,
        )

    def _on_vocab_list(self):
        return vocab.personal_list()

    def _on_vocab_add(self, wrong: str, right: str):
        err = vocab.personal_add(wrong, right)
        if err is None:
            self.replacements.reload()
            self._log(f"[vocab] reemplazo agregado: {wrong.strip()!r} → {right.strip()!r}")
        return err

    def _on_vocab_remove(self, wrong: str) -> bool:
        ok = vocab.personal_remove(wrong)
        if ok:
            self.replacements.reload()
            self._log(f"[vocab] reemplazo eliminado: {wrong!r}")
        return ok

    def _on_vocab_analyze(self):
        return vocab.suggest_from_logs(
            days=30, hotwords=self.settings.get("hotwords") or ""
        )

    def _on_vocab_ignore(self, word: str):
        vocab.ignore_word(word)
        self._log(f"[vocab] palabra ignorada para sugerencias: {word!r}")

    def _on_quality_profile_change(self, profile_key: str):
        profile = config.QUALITY_PROFILES.get(profile_key)
        if profile is None:
            return
        label = config.QUALITY_PROFILE_LABELS.get(profile_key, profile_key)
        self._log(f"[ui] perfil de calidad → '{label}'")

        # Aviso especial: medium es pesado.
        if profile_key == config.QUALITY_PROFILE_ACCURATE:
            self._log(
                "[whisper] perfil Preciso: modelo 'medium' (~1.5GB). "
                "Si es la primera vez se descargará; en CPU puede ser lento."
            )

        prev_model = self.settings.get("model")
        prev_compute = self.settings.get("compute_type")

        # Aplica todos los valores del perfil a settings.
        self.settings.set("quality_profile", profile_key)
        for k, v in profile.items():
            self.settings.set(k, v)

        # Refleja modelo nuevo en la UI sin disparar otro on_model_change.
        new_model = profile["model"]
        self.ui.set_model(new_model)

        # Recarga el modelo solo si modelo o compute_type cambiaron.
        new_compute = profile["compute_type"]
        if new_model != prev_model or new_compute != prev_compute:
            self._model_ready.clear()
            threading.Thread(
                target=self._reload_model,
                args=(new_model, new_compute),
                daemon=True,
            ).start()

    def _on_hotkey_toggle(self, enabled: bool):
        self.settings.set("hotkey_enabled", enabled)
        self._log(f"[hotkey] atajo global {'ACTIVADO' if enabled else 'DESACTIVADO'} "
                  f"({self.settings.get('hotkey').upper()})")

    # ---------------- inicio con Windows / minimizado ----------------
    def _on_start_with_windows_toggle(self, enabled: bool):
        self.settings.set("start_with_windows", enabled)
        if enabled:
            ok = autostart.enable(on_log=self._log)
        else:
            ok = autostart.disable(on_log=self._log)
        if not ok:
            # Revierte el switch en la UI si la operación de registro falló.
            self._log("[autostart] la operación falló; revierto el switch en la UI")
            self.ui.set_start_with_windows(not enabled)
            self.settings.set("start_with_windows", not enabled)

    def _on_start_minimized_toggle(self, enabled: bool):
        self.settings.set("start_minimized", enabled)
        self._log(f"[app] iniciar minimizada {'ACTIVADO' if enabled else 'DESACTIVADO'}")

    def _on_theme_change(self, key: str):
        self.settings.set("ui_theme", key)
        self._log(f"[ui] tema de color → '{key}' (guardado)")

    def _sync_autostart_on_launch(self):
        """Alinea HKCU\\Run con la preferencia guardada. Si está activo, reescribe
        la ruta actual (corrige rutas viejas tras mover/reinstalar el .exe)."""
        try:
            want = bool(self.settings.get("start_with_windows"))
            has = autostart.is_enabled()
            if want and not has:
                autostart.enable(on_log=self._log)
            elif want and has:
                # Reescribe por si la ruta cambió.
                cur = autostart.current_command()
                new = autostart.get_app_executable_path()
                if cur != new:
                    autostart.enable(on_log=self._log)
            elif not want and has:
                autostart.disable(on_log=self._log)
        except Exception as e:
            self._log(f"[autostart] error sincronizando al arranque: {e}")

    # ---------------- historial ----------------
    def _on_history_copy(self, text: str):
        if not text:
            return
        if copy_only(text, on_log=self._log):
            self._log("[history] entrada copiada al portapapeles")

    def _on_history_paste(self, text: str):
        if not text:
            return
        threading.Thread(target=self._do_paste_async, args=(text,), daemon=True).start()

    def _do_paste_async(self, text: str):
        self._set_state("pasting")
        ok = paste_text(text, on_log=self._log,
                        paste_delay_ms=self.settings.get("paste_delay_ms"))
        self._set_state("idle" if ok else "error")
        if not ok:
            self.beeps.error()

    def _on_history_clear(self):
        self.history.clear()
        self.ui.set_history([])

    # ---------------- registro de dictados ----------------
    def _log_dictation(self, *, audio, audio_duration, raw_text, final_text,
                       applied, incremental, chunks=None):
        """Escribe la entrada del dictado en el registro (y su WAV si toca).
        Nunca lanza: un fallo aquí no puede romper el pegado del texto."""
        if not bool(self.settings.get("dictation_log_enabled")):
            return
        try:
            stats = self.transcriber.dictation_stats()
            # "Sospechoso" = hubo que descartar algo o el dictado quedó vacío:
            # los casos que vale la pena auditar con el audio. Los "..." de
            # pausa NO marcan: aparecen en ~29% de dictados normales y llenaban
            # logs/audio de WAVs sin interés (análisis 2026-07-21). Los toques
            # accidentales del hotkey (<0.5s, vacíos) tampoco: eran ~10 WAVs de
            # 0.03s por semana sin nada que auditar (análisis 2026-08-03).
            vacio_relevante = not final_text and float(audio_duration) >= 0.5
            sospechoso = bool(
                stats["descartes"] or stats["repeticiones"] or vacio_relevante
            )
            entry_id = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
            audio_mode = self.settings.get("dictation_log_audio")
            audio_file = None
            if audio_mode == "todos" or (audio_mode == "sospechosos" and sospechoso):
                audio_file = self.dictation_log.save_audio(audio, entry_id)
            self.dictation_log.add({
                "id": entry_id,
                "audio_s": round(float(audio_duration), 2),
                "modelo": self.transcriber.current_model_name,
                "backend": self.transcriber.backend_str,
                "incremental": bool(incremental),
                "tramos": chunks,
                "crudo": raw_text,
                "final": final_text,
                "reemplazos": [[k, v] for k, v in (applied or [])],
                "descartes": stats["descartes"],
                "puntos_suspensivos": stats["puntos_suspensivos"],
                "repeticiones": stats["repeticiones"],
                "min_avg_logprob": stats["min_avg_logprob"],
                "max_no_speech": stats["max_no_speech"],
                "sospechoso": sospechoso,
                "audio": audio_file,
            })
        except Exception as e:
            self._log(f"[registro] error registrando dictado: {e}")

    # ---------------- CapsLock helpers ----------------
    _VK_CAPITAL = 0x14

    def _is_capslock_hotkey(self) -> bool:
        try:
            return "capslock" in self.settings.get("hotkey").lower()
        except Exception:
            return False

    def _read_capslock(self) -> bool:
        try:
            return bool(ctypes.windll.user32.GetKeyState(self._VK_CAPITAL) & 0x0001)
        except Exception:
            return False

    def _toggle_capslock(self):
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(self._VK_CAPITAL, 0x45, 0, 0)
            user32.keybd_event(self._VK_CAPITAL, 0x45, 0x0002, 0)
        except Exception as e:
            self._log(f"[capslock] no se pudo togglear: {e}")

    def _restore_capslock_if_needed(self):
        if self._capslock_was_on is None:
            return
        try:
            current = self._read_capslock()
            if current != self._capslock_was_on:
                self._toggle_capslock()
                self._log(f"[capslock] restaurado a {'ON' if self._capslock_was_on else 'OFF'}")
        finally:
            self._capslock_was_on = None

    # ---------------- hotkey: push-to-talk ----------------
    def _hotkey_press(self, which: str = "dictate"):
        # Si el atajo está desactivado, no hacemos nada (la tecla funciona normal).
        if not bool(self.settings.get("hotkey_enabled")):
            return
        self._recording_mode = "translate" if which == "translate" else "dictate"
        # Marca "press en curso" para que on_release espere.
        self._press_done.clear()
        try:
            with self._state_lock:
                if self._state not in ("idle", "error"):
                    return
                if not self._model_ready.is_set():
                    self._log("[ctrl] aún cargando modelo, espera unos segundos…")
                    self.beeps.error()
                    return
                if not self.license.allows_dictation():
                    self._license_blocked_feedback()
                    return
                self._recording_source = "hotkey"
                # Guarda estado de CapsLock si aplica.
                if self._is_capslock_hotkey():
                    self._capslock_was_on = self._read_capslock()
            self._start_recording_internal()
        finally:
            self._press_done.set()

    def _hotkey_switch(self, old: str, new: str):
        """El usuario completó un chord más largo sin soltar el activo
        (Ctrl+Win → Ctrl+Win+Shift): cambia el modo de la grabación en curso
        sin cortarla. Solo afecta al final (traducir o no) y a la barra."""
        self._recording_mode = "translate" if new == "translate" else "dictate"
        with self._state_lock:
            recording = self._state == "recording" and self._recording_source == "hotkey"
        if not recording:
            return
        tag = None
        if self._recording_mode == "translate":
            tag = str(self.settings.get("translate_target") or "en").upper()
        try:
            self.floating_bar.set_mode_tag(tag, apply_now=True)
        except Exception:
            pass
        self._log(f"[hotkey] {old} → {new} sin soltar: modo {self._recording_mode}")

    def _hotkey_release(self, which: str = "dictate"):
        if not bool(self.settings.get("hotkey_enabled")):
            return
        # Espera a que termine on_press para evitar race en taps rápidos.
        self._press_done.wait(timeout=3.0)
        with self._state_lock:
            if self._recording_source != "hotkey":
                return
        threading.Thread(target=self._process_pipeline, daemon=True).start()

    # ---------------- botón UI: toggle ----------------
    def _toggle(self):
        with self._state_lock:
            if self._state in ("idle", "error"):
                if not self._model_ready.is_set():
                    self._log("[ctrl] aún cargando modelo…")
                    self.beeps.error()
                    return
                if not self.license.allows_dictation():
                    self._license_blocked_feedback()
                    return
                self._recording_source = "button"
                start = True
                process = False
            elif self._state == "recording":
                start = False
                process = True
            else:
                self._log(f"[ctrl] toggle ignorado en estado '{self._state}'")
                return
        if start:
            self._start_recording_internal()
        elif process:
            threading.Thread(target=self._process_pipeline, daemon=True).start()

    def _make_incremental_session(self) -> IncrementalSession | None:
        """Crea la sesión de transcripción incremental para esta grabación.
        Congela los parámetros de Whisper al momento del press (igual que hacía
        el pipeline al final) y transcribe cada tramo en un worker propio."""
        try:
            prompt = (
                self.settings.get("initial_prompt")
                if self.settings.get("initial_prompt_enabled")
                else None
            )
            params = dict(
                language=self.settings.get("language"),
                beam_size=int(self.settings.get("beam_size")),
                best_of=int(self.settings.get("best_of")),
                temperature=float(self.settings.get("temperature")),
                vad_filter=bool(self.settings.get("vad_filter")),
                condition_on_previous_text=bool(self.settings.get("condition_on_previous_text")),
                initial_prompt=prompt,
                hotwords=self.settings.get("hotwords"),
                mixed_language_mode=bool(self.settings.get("mixed_language_mode")),
                debug_segments=bool(self.settings.get("debug_segments")),
                batched=False,  # tramos de ~6-15s: el batching no aporta nada
                strip_ellipsis=bool(self.settings.get("strip_ellipsis")),
            )

            def transcribe_chunk(audio):
                return self.transcriber.transcribe(
                    audio,
                    audio_duration=len(audio) / config.SAMPLE_RATE,
                    **params,
                )

            return IncrementalSession(transcribe_fn=transcribe_chunk, on_log=self._log)
        except Exception as e:
            self._log(f"[incremental] no se pudo iniciar la sesión: {e}. "
                      f"Sigo con transcripción al final (modo clásico).")
            return None

    def _start_recording_internal(self):
        try:
            # Resetea las stats del dictado ANTES de que el worker incremental
            # pueda transcribir el primer tramo (alimentan el registro al final).
            self.transcriber.begin_dictation()
            self._inc_session = None
            sink = None
            if (bool(self.settings.get("incremental_transcription_enabled"))
                    and self._model_ready.is_set()):
                self._inc_session = self._make_incremental_session()
                if self._inc_session is not None:
                    sink = self._inc_session.feed
            self.recorder.start(chunk_sink=sink)
            if self._recording_mode == "translate":
                tgt = str(self.settings.get("translate_target") or "en").upper()
                self.floating_bar.set_mode_tag(tgt)
            else:
                self.floating_bar.set_mode_tag(None)
            self._set_state("recording")
            self.ui.set_button_text("Detener y transcribir")
            self.beeps.start()
            threading.Thread(target=self._watch_mic_silence, daemon=True, name="mic-watch").start()
        except Exception as e:
            self._log(f"[audio] no se pudo iniciar: {e}")
            self._set_state("error")
            self.ui.set_button_text("Iniciar grabación")
            self.beeps.error()

    # ─── Dictar y traducir (2.12.0) ───

    def _on_translate_target_change(self, code: str):
        if code in config.TRANSLATE_TARGET_LABELS:
            self.settings.set("translate_target", code)

    def _translate_final(self, text: str) -> str:
        """Traduce el texto final del dictado al idioma destino. Nunca lanza:
        si algo falla, devuelve el texto tal cual y avisa."""
        tgt = str(self.settings.get("translate_target") or "en")
        src = self.transcriber.dictation_language() or str(self.settings.get("language") or "es")
        if src not in mt.SUPPORTED:
            src = "es" if tgt == "en" else "en"
        if src == tgt:
            self._log(f"[traductor] el dictado ya está en {tgt}: sin traducir")
            return text
        pair = mt.pair_for(src, tgt)
        try:
            if not mt.pack_installed(pair):
                self._set_state("processing")
                win = self._new_setup_window()
                try:
                    win.show(f"Descargando el traductor {src.upper()} → {tgt.upper()}",
                             f"Una sola vez (~{config.MT_PACK_DOWNLOAD_MB} MB). Luego funciona sin internet.",
                             cancellable=True)
                    mt.ensure_pack(pair, progress=win.set_progress, cancel=win.cancel_event, on_log=self._log)
                finally:
                    win.close()
            self._set_state("processing")
            t0 = time.perf_counter()
            out = self.translator.translate(text, src, tgt)
            self._log(f"[traductor] {src}→{tgt} en {time.perf_counter() - t0:.2f}s: {out!r}")
            return out
        except setup_assets.DownloadCancelled:
            self._log("[traductor] descarga cancelada; pego el texto sin traducir")
        except Exception as e:
            self._log(f"[traductor] error ({type(e).__name__}): {e}; pego el texto sin traducir")
            error_log.log_error("traducción", e)
            try:
                self.floating_bar.show_error_and_hide("Traducción falló", delay_ms=2200)
            except Exception:
                pass
        return text

    def _watch_mic_silence(self):
        """Mientras se graba: si tras 3 s el micro sigue en ceros digitales
        (mute por hardware, caso Kraken), lo avisa en la barra flotante en
        vivo en vez de solo al soltar la tecla."""
        t0 = time.time()
        shown = False
        while True:
            time.sleep(0.5)
            with self._state_lock:
                if self._state != "recording":
                    break
            if time.time() - t0 < 3.0:
                continue
            silent = self.recorder.session_peak() < DIGITAL_SILENCE_PEAK
            if silent and not shown:
                self.floating_bar.set_recording_hint("¿Micrófono en silencio?")
                shown = True
            elif not silent and shown:
                self.floating_bar.set_recording_hint(None)
                shown = False

    def _process_pipeline(self):
        try:
            audio = self.recorder.stop()
            inc = getattr(self, "_inc_session", None)
            self._inc_session = None
            self.ui.set_button_text("Iniciar grabación")
            self.beeps.stop()
            if audio is None or len(audio) == 0:
                if inc is not None:
                    inc.abort()
                self._set_state("idle")
                return

            audio_duration = len(audio) / config.SAMPLE_RATE

            # Mute por HARDWARE del headset: el driver entrega ceros digitales
            # a todo el sistema y Windows lo sigue reportando como no-muteado.
            # Transcribir no tiene sentido; avisar en la barra sí.
            if is_digital_silence(audio, audio_duration):
                if inc is not None:
                    inc.abort()
                self._log(f"[audio] ⚠ grabación de {audio_duration:.1f}s en silencio "
                          "DIGITAL absoluto. Revisa el botón de mute físico del "
                          "headset (Windows no lo reporta como muteado).")
                self._log_dictation(
                    audio=audio, audio_duration=audio_duration,
                    raw_text="", final_text="", applied=[],
                    incremental=inc is not None, chunks=None,
                )
                self._set_state("idle")
                self.floating_bar.show_error_and_hide("¿Micrófono en mute?", 3500)
                self.beeps.error()
                return

            self._set_state("transcribing")
            self._start_elapsed_timer()
            t_rep = 0.0
            inc_total_s = None
            inc_chunks = None
            pp = self._perf_params()
            try:
                # NO recargamos el modelo aquí: ya está cargado (preload / cambio
                # de perfil). Recargar a mitad de transcripción causaba cuelgues.
                if inc is not None:
                    # Incremental: los tramos previos ya se transcribieron en
                    # segundo plano mientras hablabas; aquí solo se cierra el
                    # último tramo y se une todo.
                    text, inc_stats = inc.finalize()
                    inc_total_s = float(inc_stats["transcripcion_total_s"])
                    inc_chunks = int(inc_stats["chunks"])
                    self._log(
                        f"[incremental] audio={audio_duration:.1f}s · "
                        f"tramos={inc_stats['chunks']} · "
                        f"espera_final={inc_stats['espera_final_s']:.2f}s · "
                        f"transcripcion_total={inc_total_s:.2f}s · "
                        f"errores={inc_stats['errores']}"
                    )
                else:
                    prompt = (
                        self.settings.get("initial_prompt")
                        if self.settings.get("initial_prompt_enabled")
                        else None
                    )
                    text = self.transcriber.transcribe(
                        audio,
                        language=self.settings.get("language"),
                        beam_size=int(self.settings.get("beam_size")),
                        best_of=int(self.settings.get("best_of")),
                        temperature=float(self.settings.get("temperature")),
                        vad_filter=bool(self.settings.get("vad_filter")),
                        condition_on_previous_text=bool(self.settings.get("condition_on_previous_text")),
                        initial_prompt=prompt,
                        hotwords=self.settings.get("hotwords"),
                        audio_duration=audio_duration,
                        mixed_language_mode=bool(self.settings.get("mixed_language_mode")),
                        debug_segments=bool(self.settings.get("debug_segments")),
                        batched=pp["batched"],
                        batch_size=pp["batch_size"],
                        strip_ellipsis=bool(self.settings.get("strip_ellipsis")),
                    )
            except Exception as e:
                self._log(f"[whisper] error transcribiendo: {e}")
                self._set_state("error")
                self.beeps.error()
                return
            finally:
                self._stop_elapsed_timer()

            text = clean_text(text)
            if not text:
                self._log("[whisper] no se detectó texto en el audio")
                self._log_benchmark(audio_duration, 0.0, pp, trans_s_override=inc_total_s)
                # Dictado vacío: suele ser que TODO se descartó ("..." de pausa,
                # frase fantasma). Registrarlo (con audio) es oro para diagnóstico.
                self._log_dictation(
                    audio=audio, audio_duration=audio_duration,
                    raw_text="", final_text="", applied=[],
                    incremental=inc is not None, chunks=inc_chunks,
                )
                self._set_state("idle")
                return

            raw_text = text  # lo que dijo Whisper, antes de reemplazos/normalizador
            applied_repl: list = []
            if self.settings.get("replacements_enabled"):
                self._set_state("processing")
                t_rep0 = time.perf_counter()
                new_text, applied = self.replacements.apply(text)
                t_rep = time.perf_counter() - t_rep0
                applied_repl = list(applied or [])
                if applied and bool(self.settings.get("debug_replacements")):
                    aplicados = ", ".join(f"{k!r}→{v!r}" for k, v in applied)
                    self._log(f"[replacements] aplicados: {aplicados}")
                text = new_text

            # Normalizador dedicado de correos/URLs/símbolos. Corre DESPUÉS de los
            # reemplazos (generales + personales) y ANTES de mostrar/guardar/pegar.
            # Es genérico, idempotente y se desactiva con normalize_emails_urls=false.
            try:
                norm_settings = self.settings.all()
                norm_settings["_log"] = self._log  # para debug_normalizer
                text = normalize_emails_urls_symbols(text, norm_settings)
            except Exception as e:
                self._log(f"[normalizer] error (texto sin cambios): {e}")

            self._log_benchmark(audio_duration, t_rep, pp, trans_s_override=inc_total_s)

            if self._recording_mode == "translate":
                text = self._translate_final(text)
            self._recording_mode = "dictate"

            self.ui.set_transcription(text)
            self._log(f"[whisper] texto: {text!r}")
            self.history.add(text)
            self.ui.set_history(self.history.items())
            self._log_dictation(
                audio=audio, audio_duration=audio_duration,
                raw_text=raw_text, final_text=text, applied=applied_repl,
                incremental=inc is not None, chunks=inc_chunks,
            )

            mode = self.settings.get("paste_mode")
            auto = bool(self.settings.get("auto_paste_enabled"))
            if mode == config.PASTE_MODE_PASTE and auto:
                self._set_state("pasting")
                ok = paste_text(text, on_log=self._log,
                                paste_delay_ms=self.settings.get("paste_delay_ms"))
                self._set_state("idle" if ok else "error")
                if not ok:
                    self.beeps.error()
            else:
                ok = copy_only(text, on_log=self._log)
                self._set_state("idle" if ok else "error")
                if not ok:
                    self.beeps.error()
        except Exception as e:
            self._log(f"[ctrl] error inesperado en pipeline: {e}")
            error_log.log_error("error inesperado en pipeline de dictado", e)
            self._set_state("error")
            self.beeps.error()
        finally:
            self._recording_source = None
            # Restaura CapsLock si fue el hotkey usado.
            self._restore_capslock_if_needed()

    # ---------------- tray ----------------
    def _tray_show(self):
        self.ui.show_from_tray()

    def _tray_hide(self):
        self.ui.hide_to_tray()

    def _tray_quit(self):
        self._quitting = True
        self.ui.run_on_ui_thread(self._real_shutdown)

    # ---------------- cierre ----------------
    def _on_close_request(self):
        if self._quitting:
            self._real_shutdown()
            return
        self.ui.hide_to_tray()
        self._log("[app] ventana oculta en bandeja. Click derecho en el ícono para salir.")

    def _real_shutdown(self):
        try:
            geom = self.ui.geometry()
            if geom:
                self.settings.set("last_window_geometry", geom)
        except Exception:
            pass
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.floating_bar.hide()
        except Exception:
            pass
        self.ui.destroy()

    # ---------------- entrypoint ----------------
    def run(self):
        self._log(f"[app] iniciada. Atajo global: {self.settings.get('hotkey').upper()}")
        self._log(f"[app] configs en: {config.APP_DATA_DIR}")
        self._log("[app] PUSH-TO-TALK: MANTÉN el hotkey para grabar, suéltalo para transcribir y pegar.")
        self._log("[app] El botón de la ventana sigue siendo toggle (clic = empieza, clic = termina).")
        try:
            self.ui.run()
        finally:
            if not self._quitting:
                self._real_shutdown()


def _cli_deactivate_license() -> int:
    """`Wisip.exe --deactivate-license`: libera la licencia de este equipo sin
    abrir la UI. Lo invoca el desinstalador para que la clave se pueda usar en
    otro PC. Devuelve 0 si quedó libre (o no había licencia)."""
    from app.settings import Settings
    lines = []
    lm = LicenseManager(Settings(on_log=lines.append), on_log=lines.append)
    if not str(lm.settings.get("license_key") or "").strip():
        return 0
    ok, msg = lm.deactivate()
    try:
        error_log.log_error(f"desactivación de licencia al desinstalar: {msg}")
    except Exception:
        pass
    return 0 if ok else 1


def main():
    error_log.install_crash_handlers()
    if "--deactivate-license" in sys.argv:
        sys.exit(_cli_deactivate_license())
    try:
        Controller().run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        # Sin esto, en el .exe (console=False) un fallo de arranque hace que
        # la app "desaparezca" sin ventana ni traza — imposible dar soporte.
        error_log.log_error("fallo fatal iniciando/ejecutando Wisip", e)
        error_log.show_error_dialog(
            "Wisip — error al iniciar",
            "Wisip no pudo iniciar o se cerró por un error inesperado.\n\n"
            f"Detalle: {type(e).__name__}: {e}\n\n"
            f"Traza completa en:\n{config.ERROR_LOG_PATH}",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
