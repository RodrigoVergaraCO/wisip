import threading

import numpy as np
import sounddevice as sd

from . import config

# Umbral de "silencio digital": peak float32 equivalente a ±16 en int16. Un
# micro VIVO siempre tiene ruido de fondo muy por encima de eso; solo un
# driver muteado por hardware entrega ceros (Kraken V3 X: peak 2/32768,
# incidentes 2026-07-16 y 2026-07-21). La duración mínima evita marcar taps
# accidentales del hotkey.
DIGITAL_SILENCE_PEAK = 0.0005
DIGITAL_SILENCE_MIN_SECONDS = 3.0


def is_digital_silence(audio_f32, duration_s: float) -> bool:
    """True si una grabación con duración de habla real (≥3s) llegó en ceros
    digitales: señal de micro muteado por hardware, no de usuario callado."""
    if audio_f32 is None or duration_s < DIGITAL_SILENCE_MIN_SECONDS:
        return False
    try:
        return float(np.max(np.abs(audio_f32))) < DIGITAL_SILENCE_PEAK
    except Exception:
        return False


class AudioRecorder:
    """Captura audio del micrófono. Calcula `level` (RMS escalado) en cada
    callback para que la UI flotante muestre la onda en vivo."""

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda msg: None)
        self._frames = []
        self._stream = None
        self._recording = False
        self._lock = threading.Lock()
        self._current_level = 0.0
        # Consumidor opcional de bloques en vivo (transcripción incremental).
        self._chunk_sink = None

    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def get_level(self) -> float:
        """Devuelve el nivel actual de audio en [0, 1] para visualizar."""
        return self._current_level

    def _callback(self, indata, frames, time_info, status):
        if status:
            self.on_log(f"[audio] status: {status}")
        self._frames.append(indata.copy())
        sink = self._chunk_sink
        if sink is not None:
            try:
                sink(indata)
            except Exception:
                # Nunca dejamos que el sink rompa la captura de audio.
                pass
        try:
            arr = indata.astype(np.float32).flatten()
            if arr.size:
                rms = float(np.sqrt(np.mean(arr * arr))) / 32768.0
                # Voz típica ~0.01-0.1 RMS; multiplicamos para llegar visualmente a 0-1.
                self._current_level = min(1.0, rms * 8.0)
        except Exception:
            pass

    def start(self, chunk_sink=None):
        """`chunk_sink`: callable opcional que recibe cada bloque int16 en vivo
        (lo usa la transcripción incremental). Corre en el callback de audio."""
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._current_level = 0.0
            self._chunk_sink = chunk_sink
            try:
                self._stream = sd.InputStream(
                    samplerate=config.SAMPLE_RATE,
                    channels=config.CHANNELS,
                    dtype="int16",
                    callback=self._callback,
                )
                self._stream.start()
                self._recording = True
                self.on_log("[audio] grabación iniciada")
            except Exception as e:
                self._stream = None
                self.on_log(f"[audio] error iniciando micrófono: {e}")
                raise

    def stop(self):
        """Detiene la grabación y devuelve un numpy float32 mono a 16kHz (o None)."""
        with self._lock:
            if not self._recording:
                return None
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                self.on_log(f"[audio] error cerrando stream: {e}")
            self._recording = False
            self._stream = None
            self._current_level = 0.0
            self._chunk_sink = None

        if not self._frames:
            self.on_log("[audio] no se capturó audio")
            return None

        audio_i16 = np.concatenate(self._frames, axis=0).flatten()
        duration = len(audio_i16) / config.SAMPLE_RATE
        audio_f32 = audio_i16.astype(np.float32) / 32768.0

        # Diagnóstico de nivel
        peak = float(np.max(np.abs(audio_f32))) if audio_f32.size else 0.0
        rms = float(np.sqrt(np.mean(audio_f32 * audio_f32))) if audio_f32.size else 0.0
        self.on_log(
            f"[audio] grabación detenida ({duration:.2f}s) peak={peak:.3f} rms={rms:.4f}"
        )

        # Normalización suave: si tu mic tiene gain bajo, Whisper devuelve 0
        # segmentos porque internamente decide que es no-habla. Subimos el
        # volumen hasta peak~0.6 con tope al gain para no amplificar silencios.
        if peak > 0.01:
            target_peak = 0.6
            gain = min(target_peak / peak, 10.0)
            if gain > 1.5:
                audio_f32 = np.clip(audio_f32 * gain, -1.0, 1.0)
                self.on_log(
                    f"[audio] normalizado ×{gain:.1f} → peak={float(np.max(np.abs(audio_f32))):.3f}"
                )
        elif peak > 0:
            self.on_log(
                "[audio] ⚠ nivel muy bajo (peak<0.01). "
                "Sube el volumen del micro en Windows → Sonido → Entrada."
            )
        else:
            self.on_log("[audio] ⚠ silencio total. Verifica que el micrófono no esté muteado.")

        return audio_f32
