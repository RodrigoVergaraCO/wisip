"""Enumeración y selección de micrófonos (sounddevice / PortAudio).

Windows expone cada micrófono varias veces (MME, DirectSound, WASAPI,
WDM-KS). MME —el host API por defecto de PortAudio— trunca los nombres a 31
caracteres ("CABLE Output (VB-Audio Virtual "), así que la lista que ve el
usuario se toma de WASAPI (nombres completos, latencia baja) y se deduplica
por nombre. La preferencia se guarda por NOMBRE (los índices cambian al
enchufar/desenchufar dispositivos) y se resuelve a índice en cada arranque.
"""

import sounddevice as sd

DEFAULT_LABEL = "Predeterminado del sistema"
_PREFERRED_HOSTAPIS = ("Windows WASAPI", "MME", "Windows DirectSound")


def _hostapi_index(name_fragment: str) -> int | None:
    try:
        for i, h in enumerate(sd.query_hostapis()):
            if name_fragment.lower() in str(h.get("name", "")).lower():
                return i
    except Exception:
        pass
    return None


def _all_inputs() -> list[dict]:
    out = []
    try:
        devices = sd.query_devices()
    except Exception:
        return out
    for i, d in enumerate(devices):
        try:
            if int(d.get("max_input_channels", 0)) <= 0:
                continue
            out.append({
                "index": i,
                "name": str(d.get("name", "")).strip(),
                "hostapi": int(d.get("hostapi", -1)),
                "channels": int(d.get("max_input_channels", 0)),
                "samplerate": float(d.get("default_samplerate", 0) or 0),
            })
        except Exception:
            continue
    return out


def _default_input_index() -> int | None:
    try:
        dev = sd.default.device
        idx = dev[0] if isinstance(dev, (list, tuple)) else dev
        return int(idx) if idx is not None and int(idx) >= 0 else None
    except Exception:
        return None


def list_input_devices() -> list[dict]:
    """[{index, name, hostapi, default}] deduplicados por nombre, tomados del
    mejor host API disponible (WASAPI → MME → DirectSound). El dispositivo
    predeterminado del sistema va primero con default=True."""
    inputs = _all_inputs()
    if not inputs:
        return []
    chosen_api = None
    for frag in _PREFERRED_HOSTAPIS:
        idx = _hostapi_index(frag)
        if idx is not None and any(d["hostapi"] == idx for d in inputs):
            chosen_api = idx
            break
    pool = [d for d in inputs if d["hostapi"] == chosen_api] if chosen_api is not None else inputs

    # Nombre del predeterminado (según su propio host API, normalmente MME).
    default_name = ""
    di = _default_input_index()
    if di is not None:
        for d in inputs:
            if d["index"] == di:
                default_name = d["name"]
                break

    seen = set()
    out = []
    for d in pool:
        key = d["name"].lower()
        if not key or key in seen or "sound mapper" in key or "primario de captura" in key:
            continue
        seen.add(key)
        is_default = bool(default_name) and (
            d["name"].lower() == default_name.lower()
            or d["name"].lower().startswith(default_name.lower())
        )
        out.append({**d, "default": is_default})
    out.sort(key=lambda d: (not d["default"], d["name"].lower()))
    return out


def resolve_device_index(name: str | None) -> int | None:
    """Índice de sounddevice para un nombre guardado. None = predeterminado
    (también si el dispositivo ya no está conectado). Tolera nombres
    truncados de MME comparando por prefijo."""
    name = (name or "").strip()
    if not name or name == DEFAULT_LABEL:
        return None
    low = name.lower()
    inputs = _all_inputs()
    ranked = []
    for d in inputs:
        dn = d["name"].lower()
        if dn == low:
            score = 0
        elif dn.startswith(low) or low.startswith(dn):
            score = 1
        else:
            continue
        api_rank = 0
        try:
            api_name = str(sd.query_hostapis()[d["hostapi"]].get("name", ""))
        except Exception:
            api_name = ""
        for r, frag in enumerate(_PREFERRED_HOSTAPIS):
            if frag.lower() in api_name.lower():
                api_rank = r
                break
        else:
            api_rank = len(_PREFERRED_HOSTAPIS)
        ranked.append((api_rank, score, d["index"]))
    if not ranked:
        return None
    # Primero el mejor host API (WASAPI: nombres completos), luego el nombre
    # más exacto. Así un nombre truncado por MME resuelve al micro de WASAPI.
    ranked.sort()
    return ranked[0][2]


def device_label(name: str | None) -> str:
    name = (name or "").strip()
    return name if name else DEFAULT_LABEL
