"""Traducción local español ↔ inglés (2.12.0).

Modelos OPUS-MT (Helsinki-NLP/opus-mt-es-en y opus-mt-en-es) convertidos a
CTranslate2 int8 (~80 MB cada uno). Corren en CPU en unas décimas de segundo
por párrafo; no hace falta internet después de descargar el paquete.

Flujo: el usuario mantiene el atajo de "dictar y traducir" → Whisper
transcribe como siempre (con vocabulario, reemplazos y normalizador) →
`Translator.translate(texto, origen, destino)` traduce el texto FINAL. Si el
idioma detectado ya es el destino, no se toca nada.

Los paquetes se descargan a %LOCALAPPDATA%\\Wisip\\models\\opus-mt-<par>\\ la
primera vez que se usan (con progreso, vía app/setup_assets.download_file).
"""

import os
import re
import shutil
import threading
import zipfile
from pathlib import Path

from . import config
from . import setup_assets

MT_DIR = Path(
    os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
) / "Wisip" / "models"

_REQUIRED = ("model.bin", "source.spm", "target.spm")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[^\s])")
SUPPORTED = {"es", "en"}


class TranslationError(Exception):
    pass


def pair_for(src: str, tgt: str) -> str:
    return f"{src}-{tgt}"


def pack_dir(pair: str) -> Path:
    return MT_DIR / f"opus-mt-{pair}"


def pack_installed(pair: str) -> bool:
    d = pack_dir(pair)
    return all((d / f).is_file() for f in _REQUIRED)


def ensure_pack(pair: str, progress=None, cancel=None, on_log=None) -> Path:
    """Descarga y extrae el paquete del par si falta. Devuelve su carpeta."""
    log = on_log or (lambda m: None)
    d = pack_dir(pair)
    if pack_installed(pair):
        return d
    info = config.MT_PACKS.get(pair)
    if not info:
        raise TranslationError(f"no hay paquete de traducción para {pair}")
    MT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MT_DIR / f"opus-mt-{pair}.zip"
    setup_assets.download_file(
        info["url"], zip_path, int(info.get("size", 0)), progress or (lambda d_, t, l: None),
        cancel, sha256=info.get("sha256"), label=f"Traducción {pair}",
    )
    staging = MT_DIR / f"opus-mt-{pair}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    # El zip puede traer los archivos en la raíz o dentro de una carpeta.
    root = staging
    if not (root / "model.bin").is_file():
        subs = [p for p in staging.iterdir() if p.is_dir()]
        if len(subs) == 1 and (subs[0] / "model.bin").is_file():
            root = subs[0]
    if not all((root / f).is_file() for f in _REQUIRED):
        shutil.rmtree(staging, ignore_errors=True)
        raise TranslationError(f"el paquete {pair} no trae {', '.join(_REQUIRED)}")
    shutil.rmtree(d, ignore_errors=True)
    os.replace(root, d)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        zip_path.unlink()
    except OSError:
        pass
    log(f"[traductor] paquete {pair} instalado en {d}")
    return d


def split_sentences(text: str) -> list:
    """[(párrafo_idx, oración)] conservando saltos de línea entre párrafos."""
    out = []
    for i, para in enumerate((text or "").split("\n")):
        para = para.strip()
        if not para:
            continue
        for sent in _SENT_SPLIT.split(para):
            sent = sent.strip()
            if sent:
                out.append((i, sent))
    return out


def join_sentences(items: list, translated: list) -> str:
    """Inverso de split_sentences: junta por párrafo con espacios y párrafos
    con saltos de línea."""
    paras: dict = {}
    for (idx, _), t in zip(items, translated):
        paras.setdefault(idx, []).append(t.strip())
    return "\n".join(" ".join(v) for _, v in sorted(paras.items()))


class Translator:
    """Carga perezosa de un traductor por par y tokenizadores SentencePiece."""

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda m: None)
        self._lock = threading.Lock()
        self._loaded: dict = {}   # pair -> (ct2.Translator, sp_src, sp_tgt)

    def _load(self, pair: str):
        with self._lock:
            if pair in self._loaded:
                return self._loaded[pair]
            import ctranslate2
            import sentencepiece as spm
            d = pack_dir(pair)
            if not pack_installed(pair):
                raise TranslationError(f"paquete {pair} no instalado")
            tr = ctranslate2.Translator(str(d), device="cpu", compute_type="int8", inter_threads=1, intra_threads=0)
            sp_src = spm.SentencePieceProcessor(model_file=str(d / "source.spm"))
            sp_tgt = spm.SentencePieceProcessor(model_file=str(d / "target.spm"))
            self._loaded[pair] = (tr, sp_src, sp_tgt)
            self.on_log(f"[traductor] modelo {pair} cargado (CPU int8)")
            return self._loaded[pair]

    def translate(self, text: str, src: str, tgt: str) -> str:
        src = (src or "").lower()[:2]
        tgt = (tgt or "").lower()[:2]
        if not text or not text.strip():
            return text
        if src == tgt:
            return text
        if src not in SUPPORTED or tgt not in SUPPORTED:
            raise TranslationError(f"par no soportado: {src}→{tgt}")
        pair = pair_for(src, tgt)
        tr, sp_src, sp_tgt = self._load(pair)
        items = split_sentences(text)
        if not items:
            return text
        # Marian/OPUS-MT espera el token de fin de secuencia "</s>" al final de
        # la fuente; sin él el modelo no sabe dónde termina la frase y se
        # queda repitiendo ("viernes viernes…").
        batch = [sp_src.encode(s, out_type=str) + ["</s>"] for _, s in items]
        results = tr.translate_batch(
            batch, beam_size=4, max_decoding_length=256, repetition_penalty=1.05,
        )
        out = []
        for r in results:
            tokens = r.hypotheses[0] if r.hypotheses else []
            tokens = [t for t in tokens if t not in ("</s>", "<s>", "<pad>")]
            out.append(sp_tgt.decode(tokens))
        return join_sentences(items, out)
