"""Correcciones del usuario (2.13.0).

El usuario ve la última transcripción en Inicio, corrige lo que salió mal y
pulsa "Guardar corrección". Se guarda localmente, en la misma carpeta que el
registro de dictados:

  logs/correcciones-AAAA-MM.jsonl   una línea por corrección: texto original,
                                     texto corregido, pares (mal → bien),
                                     idioma, modelo, modo (dictar / traducir)
  logs/correcciones/<id>.wav         el audio del dictado corregido (16 kHz
                                     mono int16), siempre que aún esté en
                                     memoria: audio + texto de referencia =
                                     set de evaluación gratis.

`suggest()` convierte las correcciones en candidatas para la pestaña
Vocabulario (con la forma correcta ya rellenada) y
`scripts/analyze_corrections.py` imprime el informe para revisarlo con la IA.
Nada de esto sale del PC.
"""

import difflib
import json
import re
import threading
import time
import wave
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import config

_lock = threading.Lock()
_STRIP = "\"'“”‘’«»()[]{}.,;:!?¿¡…"
_MAX_PAIR_WORDS = 4   # más largo que esto es una reescritura, no un reemplazo


def logs_dir(base: Path | None = None) -> Path:
    return Path(base) if base else config.DICTATION_LOGS_DIR


def audio_dir(base: Path | None = None) -> Path:
    return logs_dir(base) / "correcciones"


def _current_path(base: Path | None = None) -> Path:
    return logs_dir(base) / time.strftime("correcciones-%Y-%m.jsonl")


def _tokens(text: str) -> list:
    out = []
    for raw in (text or "").split():
        t = raw.strip(_STRIP)
        if t:
            out.append(t)
    return out


def word_diff(original: str, corrected: str) -> list:
    """Pares [mal, bien] entre el texto original y el corregido, a nivel de
    palabra (sin puntuación de los bordes). Borrados → [mal, ""],
    inserciones → ["", bien]."""
    a, b = _tokens(original), _tokens(corrected)
    pairs = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        pairs.append([" ".join(a[i1:i2]), " ".join(b[j1:j2])])
    return pairs


def save_correction(original: str, corrected: str, *, audio_f32=None, meta: dict | None = None,
                    base: Path | None = None) -> dict | None:
    """Guarda una corrección. Devuelve la entrada escrita, o None si no había
    nada que guardar (texto igual o vacío). Nunca lanza por el audio: si el
    WAV falla, la corrección se guarda sin él."""
    original = (original or "").strip()
    corrected = (corrected or "").strip()
    if not corrected or original == corrected:
        return None
    meta = dict(meta or {})
    entry_id = meta.pop("id", None) or (time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}")
    audio_name = None
    if audio_f32 is not None and len(audio_f32) > 0:
        try:
            audio_dir(base).mkdir(parents=True, exist_ok=True)
            audio_name = f"{entry_id}.wav"
            data = np.clip(np.asarray(audio_f32, dtype=np.float32), -1.0, 1.0)
            pcm = (data * 32767.0).astype(np.int16)
            with wave.open(str(audio_dir(base) / audio_name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.SAMPLE_RATE)
                w.writeframes(pcm.tobytes())
        except Exception:
            audio_name = None
    entry = {
        "id": entry_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "original": original,
        "corregido": corrected,
        "pares": word_diff(original, corrected),
        "audio": audio_name,
    }
    for k in ("crudo", "audio_s", "modelo", "idioma", "modo"):
        if meta.get(k) is not None:
            entry[k] = meta[k]
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        logs_dir(base).mkdir(parents=True, exist_ok=True)
        with _current_path(base).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return entry


def load_corrections(days: int | None = None, base: Path | None = None) -> list:
    """Todas las correcciones (o las de los últimos `days` días), más antiguas primero."""
    out = []
    cutoff = time.time() - days * 86400 if days else None
    for path in sorted(logs_dir(base).glob("correcciones-*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if cutoff is not None:
                        try:
                            if time.mktime(time.strptime(e.get("ts", ""), "%Y-%m-%dT%H:%M:%S")) < cutoff:
                                continue
                        except Exception:
                            pass
                    out.append(e)
        except OSError:
            continue
    return out


def count_this_month(base: Path | None = None) -> int:
    try:
        with _current_path(base).open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def aggregate(entries: list) -> Counter:
    """Counter {(mal, bien): veces} solo de sustituciones (ambos lados con texto)."""
    c = Counter()
    for e in entries:
        for pair in e.get("pares") or word_diff(e.get("original", ""), e.get("corregido", "")):
            wrong, right = (pair + ["", ""])[:2]
            if wrong and right:
                c[(wrong, right)] += 1
    return c


def suggest(entries: list, min_count: int = 1, existing: set | None = None, limit: int = 40) -> list:
    """Candidatas para la pestaña Vocabulario a partir de las correcciones:
    [{word, fix, count, context, source}] ordenadas por frecuencia. Se saltan
    los pares ya presentes en `existing` (formas mal, en minúsculas), los de
    una sola letra y las reescrituras largas."""
    existing = {w.lower() for w in (existing or set())}
    counts = aggregate(entries)
    last_seen = {}
    for e in entries:
        for pair in e.get("pares") or []:
            if len(pair) == 2 and pair[0] and pair[1]:
                last_seen[(pair[0], pair[1])] = e.get("ts", "")
    out = []
    for (wrong, right), n in counts.items():
        if n < min_count or wrong.lower() in existing:
            continue
        if len(wrong) < 2 or len(wrong.split()) > _MAX_PAIR_WORDS or len(right.split()) > _MAX_PAIR_WORDS:
            continue
        if re.fullmatch(r"[\W\d_]+", wrong):
            continue
        veces = "vez" if n == 1 else "veces"
        out.append({
            "word": wrong, "fix": right, "count": n, "source": "correcciones",
            "context": f"Lo corregiste tú {n} {veces}: «{wrong}» → «{right}»",
            "_ts": last_seen.get((wrong, right), ""),
        })
    out.sort(key=lambda d: (-d["count"], d["_ts"]), reverse=False)
    out.sort(key=lambda d: d["count"], reverse=True)
    for d in out:
        d.pop("_ts", None)
    return out[:limit]


def eval_set(entries: list, base: Path | None = None) -> list:
    """[(ruta_wav, texto_referencia)] de las correcciones que conservan audio."""
    out = []
    for e in entries:
        name = e.get("audio")
        if not name:
            continue
        p = audio_dir(base) / name
        if p.is_file():
            out.append((p, e.get("corregido", "")))
    return out


def report(entries: list) -> str:
    """Informe en texto para revisar con la IA."""
    lines = []
    n = len(entries)
    lines.append(f"Correcciones: {n}")
    if not n:
        return "\n".join(lines)
    with_audio = sum(1 for e in entries if e.get("audio"))
    by_mode = Counter(e.get("modo", "dictate") for e in entries)
    lines.append(f"Con audio (set de evaluación): {with_audio}  ·  modos: {dict(by_mode)}")
    counts = aggregate(entries)
    lines.append("")
    lines.append("Sustituciones (mal → bien · veces):")
    for (wrong, right), c in counts.most_common(60):
        lines.append(f"  {c:3d}  {wrong!r} → {right!r}")
    dels = Counter(); ins = Counter()
    for e in entries:
        for pair in e.get("pares") or []:
            if len(pair) == 2:
                if pair[0] and not pair[1]:
                    dels[pair[0]] += 1
                elif pair[1] and not pair[0]:
                    ins[pair[1]] += 1
    if dels:
        lines.append("")
        lines.append("Borrados (sobraba): " + ", ".join(f"{w!r}×{c}" for w, c in dels.most_common(20)))
    if ins:
        lines.append("Añadidos (faltaba): " + ", ".join(f"{w!r}×{c}" for w, c in ins.most_common(20)))
    lines.append("")
    lines.append("Últimas 10 (original → corregido):")
    for e in entries[-10:]:
        lines.append(f"  [{e.get('ts', '')}] {e.get('original', '')[:140]!r}")
        lines.append(f"      → {e.get('corregido', '')[:140]!r}")
    return "\n".join(lines)
