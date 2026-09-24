# -*- coding: utf-8 -*-
"""
Capa de audio para las pruebas de Wisip.

Responsabilidades:
  1. Sintetizar voz (TTS) con las voces SAPI de Windows → WAV 16 kHz mono.
     Usa System.Speech vía PowerShell (no requiere instalar nada en Python).
  2. Localizar el cable virtual VB-Audio (CABLE Input / CABLE Output).
  3. Guardar y RESTAURAR el dispositivo de audio por defecto del proceso.

IMPORTANTE sobre el micrófono por defecto:
  Solo tocamos `sounddevice.default.device`, que afecta ÚNICAMENTE a este
  proceso de Python. NO modificamos el dispositivo por defecto de Windows, así
  que Wisip y el resto del sistema siguen usando tu micrófono real. Aun así, al
  terminar restauramos el valor previo de `sd.default.device` por prolijidad.
"""

import hashlib
import os
import subprocess
import tempfile
import wave

import numpy as np
import sounddevice as sd

# Voces SAPI instaladas (detectadas en este equipo).
VOICE_ES = "Microsoft Helena Desktop"
VOICE_EN = "Microsoft Zira Desktop"

SAMPLE_RATE = 16000
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "wisip_tts_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


# ─── TTS ────────────────────────────────────────────────────────────────

def _ps_quote(s: str) -> str:
    """Comilla simple para PowerShell (duplica las comillas simples)."""
    return "'" + s.replace("'", "''") + "'"


def synth_to_wav(text: str, voice: str = "es", rate: int = 0) -> str:
    """Sintetiza `text` a un WAV 16 kHz mono 16-bit y devuelve la ruta.
    Cachea por (texto, voz, rate) para no re-sintetizar entre corridas.

    rate: velocidad SAPI (-10..10). 0 = normal. Subirlo simula habla rápida.
    """
    voice_name = VOICE_EN if voice == "en" else VOICE_ES
    key = hashlib.sha1(f"{voice_name}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    out_path = os.path.join(_CACHE_DIR, f"{key}.wav")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return out_path

    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$sp = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"try {{ $sp.SelectVoice({_ps_quote(voice_name)}) }} catch {{}}; "
        f"$sp.Rate = {int(rate)}; "
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$sp.SetOutputToWaveFile({_ps_quote(out_path)}, $fmt); "
        f"$sp.Speak({_ps_quote(text)}); "
        "$sp.Dispose();"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True,
        capture_output=True,
    )
    return out_path


def read_wav_f32(path: str) -> np.ndarray:
    """Lee un WAV mono 16-bit a float32 en [-1, 1]. Asume 16 kHz."""
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
        ch = w.getnchannels()
        sr = w.getframerate()
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SAMPLE_RATE and a.size:
        # Resampleo lineal simple (suficiente para voz de prueba).
        idx = np.linspace(0, len(a) - 1, int(len(a) * SAMPLE_RATE / sr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a


def wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


# ─── Dispositivos ───────────────────────────────────────────────────────

def find_device(name_substr: str, kind: str):
    """Primer índice cuyo nombre contiene `name_substr` y tiene canales del
    tipo pedido. kind: 'input' | 'output'. Devuelve int o None."""
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    name_substr = name_substr.lower()
    for i, d in enumerate(sd.query_devices()):
        if name_substr in d["name"].lower() and d[key] > 0:
            return i
    return None


def find_cable():
    """Devuelve (cable_output_idx, cable_input_idx) o (None, None).
    - CABLE Output = dispositivo de ENTRADA (lo que grabamos).
    - CABLE Input  = dispositivo de SALIDA (donde reproducimos el TTS).
    """
    cable_out = find_device("CABLE Output", "input")    # grabable
    cable_in = find_device("CABLE Input", "output")     # reproducible
    return cable_out, cable_in


class DefaultDeviceGuard:
    """Context manager: fija sd.default.device para el proceso y lo restaura
    al salir, pase lo que pase."""

    def __init__(self, input_idx=None, output_idx=None, log=print):
        self.input_idx = input_idx
        self.output_idx = output_idx
        self.log = log
        self._prev = None

    def __enter__(self):
        # IMPORTANTE: sd.default.device devuelve una lista mutable POR REFERENCIA.
        # Hay que copiarla (list(...)), o al fijar el nuevo valor mutaríamos
        # también nuestra "copia previa" y no podríamos restaurar el original.
        self._prev = list(sd.default.device)
        new_in = self.input_idx if self.input_idx is not None else self._prev[0]
        new_out = self.output_idx if self.output_idx is not None else self._prev[1]
        sd.default.device = (new_in, new_out)
        self.log(f"[audio_io] default.device {tuple(self._prev)} -> ({new_in}, {new_out})")
        return self

    def __exit__(self, *exc):
        try:
            sd.default.device = self._prev
            self.log(f"[audio_io] default.device restaurado a {tuple(self._prev)}")
        except Exception as e:
            self.log(f"[audio_io] no pude restaurar default.device: {e}")
        return False


def play_blocking(audio_f32: np.ndarray, sr: int = SAMPLE_RATE, device=None):
    """Reproduce un array y espera a que termine (usa el output por defecto
    salvo que se pase `device`)."""
    sd.play(audio_f32, sr, device=device)
    sd.wait()
