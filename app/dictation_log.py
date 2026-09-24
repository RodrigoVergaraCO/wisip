# -*- coding: utf-8 -*-
"""Registro persistente de dictados para el ciclo de mejora de Wisip.

A diferencia del Historial (últimas 10 frases para copiar/pegar), este registro
guarda TODOS los dictados con contexto de diagnóstico: texto crudo (lo que dijo
Whisper), texto final (tras reemplazos/normalizador), segmentos descartados por
alucinación, puntos suspensivos eliminados, confianza, modelo y duración.

Formato: un archivo JSONL por mes en %APPDATA%\\local-voice-typer\\logs\\
(``dictados-YYYY-MM.jsonl``, una línea JSON por dictado). Tras unos días de
uso, ``scripts/analyze_logs.py`` resume los errores recurrentes para
convertirlos en reemplazos, frases de blacklist o hotwords.

Audio de respaldo: los dictados "sospechosos" (descartes, repeticiones o vacío)
pueden guardar su WAV en logs/audio/ — es la única forma de verificar después
qué se dijo REALMENTE cuando Whisper oyó mal. Tope de disco con borrado FIFO.

Diseño: nunca lanza excepciones hacia el pipeline (un fallo del registro no
puede romper un dictado); todo error se reporta por on_log y se sigue.
"""

import json
import threading
import time
import wave

import numpy as np

from . import config


class DictationLog:
    """Escritor del registro de dictados (JSONL mensual + WAV opcional)."""

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda m: None)
        self._lock = threading.Lock()

    def _safe_log(self, msg: str):
        try:
            self.on_log(msg)
        except Exception:
            pass

    # ---------------- entradas JSONL ----------------
    def _current_path(self):
        return config.DICTATION_LOGS_DIR / time.strftime("dictados-%Y-%m.jsonl")

    def add(self, entry: dict) -> str | None:
        """Añade una entrada (dict serializable) al JSONL del mes en curso.
        Devuelve el id de la entrada, o None si falló la escritura."""
        try:
            entry = dict(entry)
            entry.setdefault("id", time.strftime("%Y%m%d-%H%M%S"))
            entry.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
            line = json.dumps(entry, ensure_ascii=False)
            with self._lock:
                config.DICTATION_LOGS_DIR.mkdir(parents=True, exist_ok=True)
                with self._current_path().open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            return entry["id"]
        except Exception as e:
            self._safe_log(f"[registro] error escribiendo entrada: {e}")
            return None

    # ---------------- audio de respaldo ----------------
    def save_audio(self, audio_f32, entry_id: str) -> str | None:
        """Guarda el audio (float32 mono 16kHz) como WAV int16 en logs/audio/.
        Devuelve el nombre del archivo, o None si falló o no había audio."""
        try:
            if audio_f32 is None or len(audio_f32) == 0:
                return None
            config.DICTATION_LOG_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            name = f"{entry_id}.wav"
            path = config.DICTATION_LOG_AUDIO_DIR / name
            data = np.clip(np.asarray(audio_f32, dtype=np.float32), -1.0, 1.0)
            pcm = (data * 32767.0).astype(np.int16)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.SAMPLE_RATE)
                w.writeframes(pcm.tobytes())
            self._enforce_audio_cap()
            return name
        except Exception as e:
            self._safe_log(f"[registro] error guardando audio: {e}")
            return None

    def _enforce_audio_cap(self):
        """Mantiene logs/audio/ por debajo del tope borrando los WAV más viejos."""
        try:
            files = sorted(
                config.DICTATION_LOG_AUDIO_DIR.glob("*.wav"),
                key=lambda p: p.stat().st_mtime,
            )
            max_bytes = config.DICTATION_LOG_AUDIO_MAX_MB * 1024 * 1024
            total = sum(p.stat().st_size for p in files)
            while files and total > max_bytes:
                oldest = files.pop(0)
                total -= oldest.stat().st_size
                oldest.unlink()
                self._safe_log(f"[registro] tope de audio superado: borrado {oldest.name}")
        except Exception as e:
            self._safe_log(f"[registro] error aplicando tope de audio: {e}")
