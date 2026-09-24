"""Vocabulario personal: el ciclo de refinado por usuario, dentro de la app.

Tres piezas, todas sin dependencias de UI (testeables con scripts/check_vocab.py):

1. Medidor de tokens del prompt+hotwords con el tokenizer REAL del modelo
   (los dos comparten el presupuesto de ~224 tokens de Whisper; pasarse
   desestabiliza el arranque del dictado — verificado empíricamente 2026-07).
   Si el tokenizer no está en la caché de HF todavía, estima por caracteres.

2. CRUD sobre personal_replacements.json (el diccionario que es DE CADA
   usuario: sus marcas, sus proyectos, los garbles de su acento). La UI llama
   esto y luego Replacements.reload() — sin reiniciar la app.

3. Minería de sugerencias: recorre el registro de dictados (JSONL) y saca las
   palabras raras RECURRENTES — el mismo análisis que se hacía a mano en las
   sesiones de refinado. No intenta adivinar la corrección (eso solo lo sabe
   el usuario); presenta candidatas con frecuencia y contexto. Las palabras
   que el usuario marca "ignorar" van a vocab_ignore.json y no vuelven a salir.
"""

import json
import re
import threading
import unicodedata
from pathlib import Path

from . import config

# Presupuesto de contexto de Whisper que comparten initial_prompt y hotwords.
PROMPT_TOKEN_BUDGET = 224

_IGNORE_PATH = config.APP_DATA_DIR / "vocab_ignore.json"

_tokenizer = None
_tokenizer_tried = False
_tokenizer_lock = threading.Lock()


# ─── 1) Medidor de tokens ───────────────────────────────────────────────────

def _find_tokenizer_file(model_name: str) -> Path | None:
    """Busca el tokenizer.json del modelo en la caché de HuggingFace.
    Prefiere el snapshot cuyo repo contenga el nombre del modelo; si no,
    cualquier tokenizer de faster-whisper sirve (todos comparten el BPE de
    Whisper multilingüe)."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if not hub.is_dir():
        return None
    candidates = sorted(hub.glob("models--*/snapshots/*/tokenizer.json"))
    if not candidates:
        return None
    wanted = re.sub(r"[^a-z0-9]+", "", (model_name or "").lower())
    for c in candidates:
        repo = re.sub(r"[^a-z0-9]+", "", c.parts[-4].lower())
        if wanted and wanted in repo:
            return c
    return candidates[0]


def _get_tokenizer(model_name: str):
    global _tokenizer, _tokenizer_tried
    with _tokenizer_lock:
        if _tokenizer is not None or _tokenizer_tried:
            return _tokenizer
        _tokenizer_tried = True
        try:
            from tokenizers import Tokenizer
            path = _find_tokenizer_file(model_name)
            if path is not None:
                _tokenizer = Tokenizer.from_file(str(path))
        except Exception:
            _tokenizer = None
        return _tokenizer


def count_prompt_tokens(prompt: str, hotwords: str, model_name: str) -> tuple[int, bool]:
    """Tokens que consumen prompt+hotwords juntos. Devuelve (n, exacto).
    exacto=False significa estimación por caracteres (tokenizer no disponible:
    primer arranque sin modelo descargado, o caché en otra ruta)."""
    prompt = prompt or ""
    hotwords = hotwords or ""
    tok = _get_tokenizer(model_name)
    if tok is not None:
        try:
            n = len(tok.encode(prompt).ids) + len(tok.encode(hotwords).ids)
            return n, True
        except Exception:
            pass
    # Estimación: en el BPE de Whisper el español ronda ~0.30 tokens/char
    # (medido: prompt real de 520 chars → 153 tokens). Redondeo pesimista.
    return int((len(prompt) + len(hotwords)) * 0.33) + 1, False


def budget_label(prompt: str, hotwords: str, model_name: str) -> tuple[str, bool]:
    """Texto listo para la UI ('182/224 tokens') y si se pasó del presupuesto."""
    n, exact = count_prompt_tokens(prompt, hotwords, model_name)
    prefix = "" if exact else "~"
    over = n > PROMPT_TOKEN_BUDGET
    return f"{prefix}{n}/{PROMPT_TOKEN_BUDGET} tokens (prompt + hotwords)", over


# ─── 2) CRUD de reemplazos personales ───────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def personal_list(path: Path | None = None) -> list[tuple[str, str]]:
    """Pares (mal_oído, corrección) ordenados alfabéticamente."""
    path = path or config.PERSONAL_REPLACEMENTS_PATH
    return sorted(_read_json(path).items(), key=lambda kv: kv[0].lower())


def personal_add(wrong: str, right: str, path: Path | None = None) -> str | None:
    """Agrega/actualiza una entrada. Devuelve mensaje de error o None si ok."""
    path = path or config.PERSONAL_REPLACEMENTS_PATH
    wrong = (wrong or "").strip().lower()
    right = (right or "").strip()
    if not wrong or not right:
        return "Escribe la palabra mal oída y su corrección."
    if wrong == right.lower():
        return "La palabra y la corrección son iguales."
    if len(wrong) < 2:
        return "La palabra mal oída es demasiado corta."
    data = _read_json(path)
    data[wrong] = right
    _write_json(path, data)
    return None


def personal_remove(wrong: str, path: Path | None = None) -> bool:
    path = path or config.PERSONAL_REPLACEMENTS_PATH
    data = _read_json(path)
    if wrong in data:
        del data[wrong]
        _write_json(path, data)
        return True
    return False


# ─── 3) Sugerencias desde el registro ───────────────────────────────────────

# Palabras funcionales y verbos frecuentísimos del español (formas completas).
# NO pretende ser un lexicón: solo baja el ruido obvio. El resto del filtrado
# lo hace el propio usuario con "Ignorar" (vocab_ignore.json), que personaliza
# la lista con el uso.
_COMMON_ES = set("""
el la los las un una unos unas de del a al en y o u que qué se su sus mi mis
tu tus le les lo me te nos os con por para sin sobre entre hasta desde hacia
como cómo cuando cuándo donde dónde quien quién cual cuál cuales cuáles cuyo
es son era eran fue fueron ser sería serían siendo sido está están estaba
estaban estuvo estar estamos estoy estás esté estén hay había habían habrá
habría he has ha hemos han haber hago haces hace hacemos hacen hacía hacían
hizo hicieron hará haría hecho haciendo voy vas va vamos van iba iban irá
quiero quieres quiere queremos quieren quería querían quise quisiera puedo
puedes puede podemos pueden podía podían pudo podrá podría pudiera poder
tengo tienes tiene tenemos tienen tenía tenían tuvo tendrá tendría tener
digo dices dice decimos dicen decía decían dijo dirá diría decir dicho
diciendo sé sabes sabe sabemos saben sabía sabían supo sabrá sabría saber
doy das da damos dan daba daban dio dará daría dar dado dando veo ves ve
vemos ven veía veían vio verá vería ver visto viendo pongo pones pone
ponemos ponen ponía puso pondrá poner puesto salgo sales sale salimos salen
salía salió saldrá salir vengo vienes viene venimos vienen venía vino vendrá
venir llego llegas llega llegamos llegan llegaba llegó llegará llegar paso
pasas pasa pasamos pasan pasaba pasó pasará pasar dejo dejas deja dejamos
dejan dejaba dejó dejará dejar creo crees cree creemos creen creía creyó
creer pienso piensas piensa pensamos piensan pensaba pensó pensar busco
buscas busca buscamos buscan buscaba buscó buscará buscar uso usas usa
usamos usan usaba usó usará usar miro miras mira miramos miran miraba miró
mirar hablo hablas habla hablamos hablan hablaba habló hablar trabajo
trabajas trabaja trabajamos trabajan trabajaba trabajó trabajar sigo sigues
sigue seguimos siguen seguía siguió seguirá seguir empiezo empiezas empieza
empezamos empiezan empezaba empezó empezará empezar termino terminas termina
terminamos terminan terminaba terminó terminará terminar entro entras entra
entramos entran entraba entró entrará entrar salido llegado pasado dejado
creído pensado buscado usado mirado hablado trabajado seguido empezado
terminado entrado pero aunque porque pues entonces luego después antes ahora
ya aún todavía siempre nunca también tampoco sí no ni más menos muy mucho
mucha muchos muchas poco poca pocos pocas todo toda todos todas otro otra
otros otras mismo misma mismos mismas cada cualquier alguna alguno algunos
algunas ninguna ninguno nada nadie algo alguien este esta estos estas ese
esa esos esas aquel aquella aquello esto eso aquí ahí allí allá acá bien
mal mejor peor bueno buena buenos buenas malo mala grande grandes pequeño
pequeña nuevo nueva nuevos nuevas viejo vieja primero primera segundo
segunda tercero tercera último última últimos últimas solo sola solos solas
sólo así según durante mediante contra tras cerca lejos dentro fuera arriba
abajo delante detrás encima debajo junto frente igual casi además apenas
quizá quizás tal vez veces vez día días semana semanas mes meses año años
hora horas minuto minutos segundo segundos hoy ayer mañana noche tarde
temprano momento momentos tiempo tiempos cosa cosas parte partes forma
formas manera maneras modo modos caso casos ejemplo ejemplos persona
personas gente hombre mujer niño niña señor señora don doña uno dos tres
cuatro cinco seis siete ocho nueve diez veinte treinta cien mil digamos
mira oye vale bueno listo dale okay ok claro perfecto exacto correcto
verdad cierto obvio obviamente realmente simplemente solamente básicamente
justamente exactamente directamente realmente generalmente normalmente
prácticamente especialmente principalmente finalmente actualmente
""".split())

_WORD_RE = re.compile(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ][\w'áéíóúüñÁÉÍÓÚÜÑ-]+")

# wordfreq (frecuencias de corpus ES+EN, con TODAS las formas conjugadas) para
# detectar palabras INVENTADAS por Whisper ("herzner", "remulario", "yotml").
# Medido sobre el registro real de agosto: 20/20 garbles con zipf 0.00 y todas
# las conjugaciones/tecnicismos reales por encima de 2.3 — separación limpia
# con umbral 1.5. Lo que SÍ es palabra real mal aplicada ("prótesis" por
# "proxys") es indetectable a nivel de palabra — eso lo resuelve el usuario
# con el formulario manual. Carga perezosa y opcional: sin la librería, cae
# al modo stoplist (más ruidoso pero funcional).
_ZIPF_KNOWN_THRESHOLD = 1.5

_zipf_fn = None
_zipf_lock = threading.Lock()


def _get_zipf():
    global _zipf_fn
    with _zipf_lock:
        if _zipf_fn is None:
            try:
                from wordfreq import zipf_frequency
                _zipf_fn = zipf_frequency
            except Exception:
                _zipf_fn = False
        return _zipf_fn


def _looks_real_word(w: str, zipf_fn) -> bool:
    """True si los corpus de español o inglés conocen la palabra."""
    if not zipf_fn:
        return False
    try:
        return (
            zipf_fn(w, "es") >= _ZIPF_KNOWN_THRESHOLD
            or zipf_fn(w, "en") >= _ZIPF_KNOWN_THRESHOLD
        )
    except Exception:
        return False


def _strip_accents(w: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", w)
        if unicodedata.category(c) != "Mn"
    )


def load_ignored(path: Path | None = None) -> set[str]:
    path = path or _IGNORE_PATH
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return {str(w).lower() for w in data} if isinstance(data, list) else set()
    except Exception:
        return set()


def ignore_word(word: str, path: Path | None = None):
    path = path or _IGNORE_PATH
    words = load_ignored(path)
    words.add((word or "").strip().lower())
    with path.open("w", encoding="utf-8") as f:
        json.dump(sorted(words), f, indent=1, ensure_ascii=False)


def _known_vocabulary() -> set[str]:
    """Palabras que ya están 'resueltas': claves y valores de los diccionarios
    de reemplazos (general + personal) — si ya tienen regla, no son candidatas."""
    known: set[str] = set()
    for p in (config.REPLACEMENTS_PATH, config.PERSONAL_REPLACEMENTS_PATH):
        for k, v in _read_json(p).items():
            known.update(_WORD_RE.findall(k.lower()))
            known.update(_WORD_RE.findall(v.lower()))
    return known


def suggest_from_logs(
    days: int = 30,
    min_count: int = 3,
    min_len: int = 5,
    limit: int = 40,
    logs_dir: Path | None = None,
    hotwords: str = "",
    ignore_path: Path | None = None,
) -> list[dict]:
    """Candidatas a corrección: palabras raras recurrentes del registro.

    Devuelve [{word, count, context}] ordenado por frecuencia. 'Rara' =
    no es palabra funcional común, no está en los diccionarios de reemplazos,
    no está en los hotwords y el usuario no la ha ignorado. La decisión final
    (¿es un error de oído o es mi vocabulario?) es del usuario.
    """
    logs_dir = logs_dir or config.DICTATION_LOGS_DIR
    ignored = load_ignored(ignore_path)
    known = _known_vocabulary()
    zipf_fn = _get_zipf()
    hot = {w.strip().lower() for w in (hotwords or "").split(",") if w.strip()}
    for h in list(hot):
        hot.update(_WORD_RE.findall(h))

    import datetime as _dt
    cutoff = _dt.date.today() - _dt.timedelta(days=days)
    counts: dict[str, int] = {}
    contexts: dict[str, str] = {}

    for jf in sorted(logs_dir.glob("dictados-*.jsonl")):
        # dictados-YYYY-MM.jsonl: salta meses completos anteriores al corte.
        m = re.search(r"(\d{4})-(\d{2})", jf.name)
        if m and _dt.date(int(m.group(1)), int(m.group(2)), 28) < cutoff:
            continue
        try:
            with jf.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = str(d.get("ts", ""))[:10]
                    if ts and ts < cutoff.isoformat():
                        continue
                    text = d.get("final") or ""
                    if not text:
                        continue
                    for match in _WORD_RE.finditer(text):
                        w = match.group(0).lower()
                        if len(w) < min_len or w in ignored or w in hot:
                            continue
                        if w in _COMMON_ES or _strip_accents(w) in _COMMON_ES:
                            continue
                        if w in known:
                            continue
                        if w in counts:
                            counts[w] += 1
                            continue
                        # El chequeo de diccionario es lo más caro: solo para
                        # palabras nuevas, y el resultado queda cacheado en
                        # counts/contexts (o descartado vía known).
                        if _looks_real_word(w, zipf_fn):
                            known.add(w)
                            continue
                        counts[w] = 1
                        if w not in contexts:
                            a = max(0, match.start() - 45)
                            b = min(len(text), match.end() + 45)
                            contexts[w] = "…" + text[a:b].replace("\n", " ") + "…"
        except Exception:
            continue

    out = [
        {"word": w, "count": c, "context": contexts.get(w, "")}
        for w, c in counts.items()
        if c >= min_count
    ]
    out.sort(key=lambda s: (-s["count"], s["word"]))
    return out[:limit]
