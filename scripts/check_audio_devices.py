# -*- coding: utf-8 -*-
"""Valida la enumeración/resolución de micrófonos (app/audio_devices.py) y el
resultado del asistente inicial (app/onboarding.default_result) SIN hardware:
se simula la tabla de dispositivos que PortAudio devuelve en Windows (cada
micro repetido en MME/DirectSound/WASAPI/WDM-KS, nombres truncados en MME).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_audio_devices.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import sounddevice as sd  # noqa: E402

from app import audio_devices as ad  # noqa: E402
from app import config  # noqa: E402
from app.onboarding import default_result  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


HOSTAPIS = [
    {"name": "MME", "default_input_device": 1},
    {"name": "Windows DirectSound", "default_input_device": 9},
    {"name": "Windows WASAPI", "default_input_device": 24},
    {"name": "Windows WDM-KS", "default_input_device": 28},
]
DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "Micrófono (Razer Kraken V3 X)", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "CABLE Output (VB-Audio Virtual ", "hostapi": 0, "max_input_channels": 8, "default_samplerate": 44100},
    {"name": "Altavoces", "hostapi": 0, "max_input_channels": 0, "default_samplerate": 44100},
    {"name": "Controlador primario de captura de sonido", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "Micrófono (Razer Kraken V3 X)", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "CABLE Output (VB-Audio Virtual Cable)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 44100},
    {"name": "Micrófono (Razer Kraken V3 X)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 48000},
    {"name": "Webcam C920", "hostapi": 2, "max_input_channels": 1, "default_samplerate": 48000},
    {"name": "Micrófono (Razer Kraken V3 X)", "hostapi": 3, "max_input_channels": 2, "default_samplerate": 44100},
]


class _FakeDefault:
    device = [1, 4]


def main():
    orig = (sd.query_devices, sd.query_hostapis, sd.default)
    sd.query_devices = lambda *a, **k: DEVICES
    sd.query_hostapis = lambda: HOSTAPIS
    sd.default = _FakeDefault()
    try:
        print("── Lista de micrófonos ──")
        lst = ad.list_input_devices()
        names = [d["name"] for d in lst]
        check("solo WASAPI, deduplicado, sin 'Sound Mapper'",
              names == ["Micrófono (Razer Kraken V3 X)", "CABLE Output (VB-Audio Virtual Cable)", "Webcam C920"], str(names))
        check("el predeterminado va primero y marcado", lst[0]["default"] is True and not lst[1]["default"])
        check("índice WASAPI del Kraken", lst[0]["index"] == 7)

        print("\n── Resolución por nombre ──")
        check("nombre exacto → índice MME (abre a 16 kHz)", ad.resolve_device_index("Micrófono (Razer Kraken V3 X)") == 1)
        check("nombre completo WASAPI → MME truncado por prefijo", ad.resolve_device_index("CABLE Output (VB-Audio Virtual Cable)") == 2)
        check("solo en WASAPI → índice WASAPI", ad.resolve_device_index("Webcam C920") == 8)
        check("extra_settings sin dispositivo → None", ad.stream_extra_settings(None) is None)
        check("vacío → predeterminado (None)", ad.resolve_device_index("") is None)
        check("etiqueta 'Predeterminado' → None", ad.resolve_device_index(ad.DEFAULT_LABEL) is None)
        check("desconectado → None", ad.resolve_device_index("Blue Yeti") is None)
        check("device_label", ad.device_label("") == ad.DEFAULT_LABEL and ad.device_label("Webcam C920") == "Webcam C920")

        print("\n── Sin dispositivos / errores de PortAudio ──")
        sd.query_devices = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PortAudio"))
        check("query_devices lanza → lista vacía", ad.list_input_devices() == [])
        check("query_devices lanza → resolve None", ad.resolve_device_index("x") is None)
    finally:
        sd.query_devices, sd.query_hostapis, sd.default = orig

    print("\n── Asistente inicial: resultado por defecto (modo automático) ──")
    r = default_result({"language": "es", "hotkey": "f8", "mixed_language_mode": False}, {"name": "RTX", "vram_mb": 12288})
    check("respeta idioma/hotkey/mixto", r["language"] == "es" and r["hotkey"] == "f8" and r["mixed_language_mode"] is False)
    check("gpu_pack True con GPU", r["gpu_pack"] is True)
    r2 = default_result({"language": "klingon"}, None)
    check("idioma inválido → default", r2["language"] == config.LANGUAGE and r2["gpu_pack"] is None)
    check("registro local activado por defecto", r2["dictation_log_enabled"] is True)

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de audio_devices/onboarding pasaron.")


if __name__ == "__main__":
    main()
