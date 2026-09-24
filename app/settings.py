import json
import threading
from typing import Any

from . import config


DEFAULTS = {
    "model": config.DEFAULT_MODEL,
    "language": config.LANGUAGE,
    "hotkey": config.DEFAULT_HOTKEY,
    "hotkey_enabled": True,
    "paste_mode": config.PASTE_MODE_PASTE,
    "beep_enabled": True,
    "auto_paste_enabled": True,
    "replacements_enabled": True,
    "start_minimized": False,
    "start_with_windows": config.DEFAULT_START_WITH_WINDOWS,
    "paste_delay_ms": config.DEFAULT_PASTE_DELAY_MS,
    "last_window_geometry": "",
    # Tema de color de la UI (clave de app/themes.py).
    "ui_theme": "carbon_naranja",
    # Whisper avanzado
    "beam_size": config.DEFAULT_BEAM_SIZE,
    "best_of": config.DEFAULT_BEST_OF,
    "temperature": config.DEFAULT_TEMPERATURE,
    "vad_filter": config.DEFAULT_VAD_FILTER,
    "condition_on_previous_text": config.DEFAULT_CONDITION_ON_PREVIOUS_TEXT,
    "initial_prompt_enabled": config.DEFAULT_INITIAL_PROMPT_ENABLED,
    "initial_prompt": config.DEFAULT_INITIAL_PROMPT,
    # Vocabulario inyectado en CADA ventana (términos EN que no deben
    # traducirse). String separado por comas; vacío = desactivado.
    "hotwords": config.DEFAULT_HOTWORDS,
    # Perfil de calidad + compute_type
    "quality_profile": config.DEFAULT_QUALITY_PROFILE,
    "compute_type": config.WHISPER_COMPUTE_TYPE,
    # Rendimiento: device / GPU / batching / perfil de rendimiento
    "device": config.DEFAULT_DEVICE,
    "cpu_threads": config.DEFAULT_CPU_THREADS,
    "num_workers": config.DEFAULT_NUM_WORKERS,
    "enable_gpu_if_available": config.DEFAULT_ENABLE_GPU_IF_AVAILABLE,
    "performance_profile": config.DEFAULT_PERF_PROFILE,
    # Banderas de migración única: el Controller sube a 'Rápido seguro' y al
    # modelo 'Preciso GPU' (large-v3-turbo) a quien tenga GPU. Solo una vez.
    "perf_autotuned": False,
    "model_autotuned": False,
    # El usuario dijo "ahora no" a la descarga del paquete NVIDIA (2.7.0+).
    # No se vuelve a preguntar al arrancar; queda el botón en la UI.
    "gpu_pack_declined": False,
    # Asistente de primer arranque (2.8.0): se muestra una sola vez.
    "first_run_done": False,
    # Micrófono elegido, por NOMBRE (vacío = predeterminado del sistema).
    "input_device_name": "",
    # Auto-actualización (2.11.0). Ver app/updater.py.
    "auto_update_check": True,      # consultar GitHub Releases (cada 6 h)
    "auto_update_install": True,    # descargar e instalar solo cuando la app esté en reposo
    "update_last_check": "",
    # Licencias (2.9.0). Ver app/license.py.
    "trial_started": "",
    "license_key": "",
    "license_instance_id": "",
    "license_status": "",
    "license_activated_at": "",
    "license_last_validated": "",
    "license_email": "",
    "license_product": "",
    "license_message": "",
    "batched": config.DEFAULT_BATCHED,
    "batch_size": config.DEFAULT_BATCH_SIZE,
    # Transcripción incremental (solo diseño; desactivada)
    "incremental_transcription_enabled": config.DEFAULT_INCREMENTAL_TRANSCRIPTION,
    "chunk_seconds": config.DEFAULT_CHUNK_SECONDS,
    "chunk_overlap_seconds": config.DEFAULT_CHUNK_OVERLAP_SECONDS,
    # Idioma mixto / debug / modo técnico (fase correctiva)
    "mixed_language_mode": config.DEFAULT_MIXED_LANGUAGE_MODE,
    "debug_segments": config.DEFAULT_DEBUG_SEGMENTS,
    "debug_replacements": config.DEFAULT_DEBUG_REPLACEMENTS,
    "tech_mode": config.DEFAULT_TECH_MODE,
    # Registro de dictados (ciclo de mejora) + limpieza de "..." de pausas.
    "dictation_log_enabled": config.DEFAULT_DICTATION_LOG_ENABLED,
    "dictation_log_audio": config.DEFAULT_DICTATION_LOG_AUDIO,
    "strip_ellipsis": config.DEFAULT_STRIP_ELLIPSIS,
    # Postprocesador de correos/URLs/símbolos.
    "normalize_emails_urls": config.DEFAULT_NORMALIZE_EMAILS_URLS,
    "debug_normalizer": config.DEFAULT_DEBUG_NORMALIZER,
    "technical_symbol_mode": config.DEFAULT_TECHNICAL_SYMBOL_MODE,
    "email_as_markdown": config.DEFAULT_EMAIL_AS_MARKDOWN,
}


class Settings:
    """Lee y guarda app_settings.json en %APPDATA%\\local-voice-typer\\."""

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda m: None)
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _safe_log(self, msg: str):
        """Loguea sin dejar que un logger roto tumbe la carga de settings.
        (Un on_log que lanzaba UnicodeEncodeError hacía que _load descartara
        la config del usuario como si el JSON estuviera corrupto.)"""
        try:
            self.on_log(msg)
        except Exception:
            pass

    def _load(self):
        path = config.SETTINGS_PATH
        if not path.exists():
            self._save_unlocked()
            self._safe_log(f"[settings] creado defaults en {path}")
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                disk = json.load(f)
            merged = dict(DEFAULTS)
            for k, v in disk.items():
                if k in DEFAULTS:
                    merged[k] = v
            # Normaliza idioma a uno de los códigos válidos.
            if merged.get("language") not in config.LANGUAGE_CODES:
                merged["language"] = config.LANGUAGE
            # Validación de parámetros avanzados (si llegan corruptos, fallback al default).
            try:
                bs = int(merged.get("beam_size", config.DEFAULT_BEAM_SIZE))
                merged["beam_size"] = bs if 1 <= bs <= 10 else config.DEFAULT_BEAM_SIZE
            except (TypeError, ValueError):
                merged["beam_size"] = config.DEFAULT_BEAM_SIZE
            try:
                bo = int(merged.get("best_of", config.DEFAULT_BEST_OF))
                merged["best_of"] = bo if 1 <= bo <= 10 else config.DEFAULT_BEST_OF
            except (TypeError, ValueError):
                merged["best_of"] = config.DEFAULT_BEST_OF
            try:
                t = float(merged.get("temperature", config.DEFAULT_TEMPERATURE))
                merged["temperature"] = t if 0.0 <= t <= 1.0 else config.DEFAULT_TEMPERATURE
            except (TypeError, ValueError):
                merged["temperature"] = config.DEFAULT_TEMPERATURE
            merged["vad_filter"] = bool(merged.get("vad_filter", config.DEFAULT_VAD_FILTER))
            merged["condition_on_previous_text"] = bool(
                merged.get("condition_on_previous_text", config.DEFAULT_CONDITION_ON_PREVIOUS_TEXT)
            )
            merged["initial_prompt_enabled"] = bool(
                merged.get("initial_prompt_enabled", config.DEFAULT_INITIAL_PROMPT_ENABLED)
            )
            if not isinstance(merged.get("initial_prompt"), str):
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
            if not isinstance(merged.get("hotwords"), str):
                merged["hotwords"] = config.DEFAULT_HOTWORDS
            # Migración hotwords v1 → v2 (añade Seedance y kie.ai). Igual que
            # las del prompt: solo si coincide EXACTO con el default anterior,
            # para no pisar ediciones manuales del usuario.
            if merged.get("hotwords") == config.V1_DEFAULT_HOTWORDS:
                merged["hotwords"] = config.DEFAULT_HOTWORDS
                self._safe_log(
                    "[settings] hotwords v1 detectados → migrados al v2 "
                    "(añade Seedance, kie.ai)"
                )
            # Migración: si el usuario aún tiene un prompt de generación anterior,
            # lo subimos al nuevo. Solo migra si coincide EXACTO con un default
            # previo (preserva ediciones manuales).
            current_prompt = merged.get("initial_prompt")
            if current_prompt == config.OLD_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v1 detectado → migrado al "
                    "prompt v3 (anchors wisip/email/símbolos, no traducir)"
                )
            elif current_prompt == config.MID_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v2 detectado → migrado al "
                    "prompt v4 (añade librerías Python, VAD, payload, Wasender)"
                )
            elif current_prompt == config.V3_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v3 detectado → migrado al "
                    "prompt v5 (añade librerías, ejemplos de correo/URL y sesión)"
                )
            elif current_prompt == config.V4_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v4 detectado → migrado al "
                    "prompt v6 (ejemplos de correo/URL genéricos, sin datos personales)"
                )
            elif current_prompt == config.V5_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v5 detectado → migrado al "
                    "prompt v7 (estilo transcripción, sin instrucciones)"
                )
            elif current_prompt == config.V6_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v6 detectado → migrado al v8: "
                    "estilo transcripción con code-switching demostrado"
                )
            elif current_prompt == config.V7_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v7 detectado → migrado al v8: "
                    "demuestra code-switching (términos y frases EN se quedan "
                    "en inglés dentro del dictado ES)"
                )
            elif current_prompt == config.V8_DEFAULT_INITIAL_PROMPT:
                merged["initial_prompt"] = config.DEFAULT_INITIAL_PROMPT
                self._safe_log(
                    "[settings] initial_prompt v8 detectado → migrado al v9: "
                    "la cola 'Palabras frecuentes:' era un listado y Whisper "
                    "lo recitaba en el dictado (eco); ahora es frase natural"
                )
            if merged.get("quality_profile") not in config.QUALITY_PROFILE_KEYS:
                merged["quality_profile"] = config.DEFAULT_QUALITY_PROFILE
            if merged.get("compute_type") not in config.VALID_COMPUTE_TYPES:
                merged["compute_type"] = config.WHISPER_COMPUTE_TYPE
            merged["mixed_language_mode"] = bool(
                merged.get("mixed_language_mode", config.DEFAULT_MIXED_LANGUAGE_MODE)
            )
            merged["debug_segments"] = bool(
                merged.get("debug_segments", config.DEFAULT_DEBUG_SEGMENTS)
            )
            merged["debug_replacements"] = bool(
                merged.get("debug_replacements", config.DEFAULT_DEBUG_REPLACEMENTS)
            )
            # Rendimiento.
            if merged.get("device") not in config.VALID_DEVICES:
                merged["device"] = config.DEFAULT_DEVICE
            if merged.get("compute_type") not in config.VALID_COMPUTE_TYPES:
                merged["compute_type"] = config.WHISPER_COMPUTE_TYPE
            try:
                ct = int(merged.get("cpu_threads", config.DEFAULT_CPU_THREADS))
                merged["cpu_threads"] = ct if 0 <= ct <= 64 else config.DEFAULT_CPU_THREADS
            except (TypeError, ValueError):
                merged["cpu_threads"] = config.DEFAULT_CPU_THREADS
            try:
                nw = int(merged.get("num_workers", config.DEFAULT_NUM_WORKERS))
                merged["num_workers"] = nw if 1 <= nw <= 8 else config.DEFAULT_NUM_WORKERS
            except (TypeError, ValueError):
                merged["num_workers"] = config.DEFAULT_NUM_WORKERS
            merged["enable_gpu_if_available"] = bool(
                merged.get("enable_gpu_if_available", config.DEFAULT_ENABLE_GPU_IF_AVAILABLE)
            )
            if merged.get("performance_profile") not in config.PERF_PROFILE_KEYS:
                merged["performance_profile"] = config.DEFAULT_PERF_PROFILE
            merged["batched"] = bool(merged.get("batched", config.DEFAULT_BATCHED))
            try:
                bsz = int(merged.get("batch_size", config.DEFAULT_BATCH_SIZE))
                merged["batch_size"] = bsz if 1 <= bsz <= 64 else config.DEFAULT_BATCH_SIZE
            except (TypeError, ValueError):
                merged["batch_size"] = config.DEFAULT_BATCH_SIZE
            merged["incremental_transcription_enabled"] = bool(
                merged.get("incremental_transcription_enabled",
                           config.DEFAULT_INCREMENTAL_TRANSCRIPTION)
            )
            merged["tech_mode"] = bool(
                merged.get("tech_mode", config.DEFAULT_TECH_MODE)
            )
            merged["dictation_log_enabled"] = bool(
                merged.get("dictation_log_enabled", config.DEFAULT_DICTATION_LOG_ENABLED)
            )
            if merged.get("dictation_log_audio") not in config.DICTATION_LOG_AUDIO_MODES:
                merged["dictation_log_audio"] = config.DEFAULT_DICTATION_LOG_AUDIO
            merged["strip_ellipsis"] = bool(
                merged.get("strip_ellipsis", config.DEFAULT_STRIP_ELLIPSIS)
            )
            merged["normalize_emails_urls"] = bool(
                merged.get("normalize_emails_urls", config.DEFAULT_NORMALIZE_EMAILS_URLS)
            )
            merged["debug_normalizer"] = bool(
                merged.get("debug_normalizer", config.DEFAULT_DEBUG_NORMALIZER)
            )
            merged["technical_symbol_mode"] = bool(
                merged.get("technical_symbol_mode", config.DEFAULT_TECHNICAL_SYMBOL_MODE)
            )
            merged["email_as_markdown"] = bool(
                merged.get("email_as_markdown", config.DEFAULT_EMAIL_AS_MARKDOWN)
            )
            merged["start_with_windows"] = bool(
                merged.get("start_with_windows", config.DEFAULT_START_WITH_WINDOWS)
            )
            merged["start_minimized"] = bool(
                merged.get("start_minimized", False)
            )
            try:
                pd = int(merged.get("paste_delay_ms", config.DEFAULT_PASTE_DELAY_MS))
                merged["paste_delay_ms"] = (
                    pd if config.PASTE_DELAY_MS_MIN <= pd <= config.PASTE_DELAY_MS_MAX
                    else config.DEFAULT_PASTE_DELAY_MS
                )
            except (TypeError, ValueError):
                merged["paste_delay_ms"] = config.DEFAULT_PASTE_DELAY_MS
            self._data = merged
            self._safe_log(f"[settings] cargado desde {path}")
        except Exception as e:
            self._safe_log(f"[settings] error leyendo {path}: {e}; uso defaults")
            self._data = dict(DEFAULTS)

    def _save_unlocked(self):
        try:
            with config.SETTINGS_PATH.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._safe_log(f"[settings] error guardando: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any):
        with self._lock:
            self._data[key] = value
            self._save_unlocked()
        self._safe_log(f"[settings] {key} = {value!r}")

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)
