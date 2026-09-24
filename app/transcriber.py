import re
import threading
import time

import numpy as np
from faster_whisper import BatchedInferencePipeline, WhisperModel

from . import config

try:
    import ctranslate2
    _CT2 = ctranslate2
except Exception:  # pragma: no cover
    _CT2 = None


def _normalize_for_blacklist(text: str) -> str:
    """Normaliza un segmento para compararlo con las frases fantasma conocidas:
    minúsculas y sin puntuación/espacios en los bordes."""
    return text.strip().lower().strip("¡!¿?.,;:… ")


# La lista negra se compara ya normalizada (así "¡Gracias por ver!" y
# "gracias por ver" caen en la misma entrada).
_HALLUCINATION_SET = {_normalize_for_blacklist(p) for p in config.HALLUCINATION_PHRASES}

# Despedidas fantasma de cola: solo se descartan con confianza baja (a
# diferencia de la blacklist, que descarta siempre), porque el usuario puede
# dictarlas de verdad al cerrar un mensaje.
_CLOSING_SET = {_normalize_for_blacklist(p) for p in config.CLOSING_PHRASES}

# Red de seguridad anti-loop a nivel de texto. Aun con la escalera de
# temperaturas, un decode degenerado puede sobrevivir (y el pipeline batched
# ni siquiera tiene fallback: usa solo la primera temperatura). Colapsa rachas
# de una misma unidad corta repetida consecutivamente: más de 4 veces si es
# una palabra ("no, no, no, ..."), más de 2 si son 2-4 palabras ("sin
# respuesta, sin respuesta, ..."). El habla real casi nunca repite así.
_REPEAT_MAX_UNIT_WORDS = 4
_REPEAT_KEEP_SINGLE = 4
_REPEAT_KEEP_MULTI = 2


def _normalize_repeat_word(word: str) -> str:
    return word.strip("¡!¿?.,;:…()[]\"'").lower()


def collapse_repetition_runs(text: str) -> tuple[str, int]:
    """Colapsa repeticiones consecutivas anómalas (loops de Whisper).
    Devuelve (texto_limpio, n_palabras_eliminadas). La comparación ignora
    puntuación y mayúsculas ("no," == "no."), pero emite las palabras
    originales que se conservan."""
    words = text.split()
    n = len(words)
    norm = [_normalize_repeat_word(w) for w in words]
    out: list = []
    dropped = 0
    i = 0
    while i < n:
        best_k = 0
        best_reps = 0
        for k in range(1, _REPEAT_MAX_UNIT_WORDS + 1):
            if i + 2 * k > n:
                break
            unit = norm[i:i + k]
            if not all(unit):  # unidades con tokens de pura puntuación no cuentan
                continue
            reps = 1
            j = i + k
            while j + k <= n and norm[j:j + k] == unit:
                reps += 1
                j += k
            keep = _REPEAT_KEEP_SINGLE if k == 1 else _REPEAT_KEEP_MULTI
            if reps > keep and reps * k > best_reps * best_k:
                best_k, best_reps = k, reps
        if best_k:
            keep = _REPEAT_KEEP_SINGLE if best_k == 1 else _REPEAT_KEEP_MULTI
            out.extend(words[i:i + best_k * keep])
            dropped += (best_reps - keep) * best_k
            i += best_reps * best_k
        else:
            out.append(words[i])
            i += 1
    if not dropped:
        return text, 0
    return " ".join(out), dropped


# Puntos suspensivos que Whisper "oye" en las pausas del hablante: "…" o 3+
# puntos seguidos. NO toca puntos sueltos ("amara.org", "3.14", fin de frase).
_ELLIPSIS_RE = re.compile(r"(?:…+|\.{3,})")


def strip_ellipsis_text(text: str) -> tuple[str, int]:
    """Elimina los puntos suspensivos que Whisper inserta en las pausas.
    Devuelve (texto_limpio, n_eliminados). Limpia el espaciado resultante:
    "Hola... quería" → "Hola quería", "¿Vamos...?" → "¿Vamos?"."""
    if not text:
        return text, 0
    count = len(_ELLIPSIS_RE.findall(text))
    if not count:
        return text, 0
    out = _ELLIPSIS_RE.sub(" ", text)
    out = " ".join(out.split())
    # Sin espacio huérfano antes de puntuación de cierre ("Vamos ?" → "Vamos?").
    out = re.sub(r"\s+([?!,;:.])", r"\1", out)
    return out.strip(), count


# Risa: "jajaja", "jeje", "hahaha", "jijiji"... (2+ sílabas de risa). Whisper
# la alucina sobre ruido/voz lejana. "ja" suelto NO matchea a propósito.
_LAUGH_TOKEN_RE = re.compile(r"^(?:[jh]+[aeiouáéíóú]+){2,}$")


def _is_laugh_only(normalized: str) -> bool:
    """True si el segmento normalizado consiste SOLO en tokens de risa."""
    tokens = re.findall(r"[a-záéíóúüñ]+", normalized)
    return bool(tokens) and all(_LAUGH_TOKEN_RE.match(t) for t in tokens)


_LAUGH_WORD = r"[jh]+[aeiouáéíóú]+(?:[jh]+[aeiouáéíóú]+)+"
_LAUGH_RUN_RE = re.compile(
    r"(?i)\b(" + _LAUGH_WORD + r")([.!?,;…]*)(?:\s+(?:" + _LAUGH_WORD + r")[.!?,;…]*)+"
)


def collapse_laugh_runs(text: str) -> tuple[str, int]:
    """'Jajaja. Jajaja. Jajaja.' → 'Jajaja.' — la risa repetida consecutiva es
    un loop de ruido, no dictado (una sola risa dictada a propósito se respeta).
    Devuelve (texto_limpio, n_palabras_eliminadas)."""
    if not text:
        return text, 0
    before = len(text.split())
    out = _LAUGH_RUN_RE.sub(lambda m: m.group(1) + m.group(2), text)
    return out, before - len(out.split())


# Cierres de frase: si el texto previo NO termina en uno, la frase quedó
# abierta y un segmento corto siguiente suele ser su continuación.
_SENTENCE_END_CHARS = tuple(".!?…:;")


def is_hallucinated_segment(piece: str, avg_logprob, no_speech_prob,
                            prompt_norm: str = "",
                            prompt_tail: str = "",
                            hotwords_norm: str = "",
                            prev_open: bool = False) -> str | None:
    """Devuelve el motivo si el segmento parece alucinado, o None si es válido.

    Guardas (conservadoras, no tocan habla normal):
    1. Coincidencia EXACTA (normalizada) con frases fantasma típicas de Whisper
       en silencios (créditos de Amara.org, despedidas de YouTube). Variante:
       despedidas cortas ("Muchas gracias.", "Chao.") solo se descartan con
       confianza baja — dictadas de verdad tienen logprob ≥ -0.4 y pasan.
    2. Regla probabilística estilo OpenAI: no_speech_prob muy alto, o alto
       combinado con avg_logprob bajo (el decoder "inventando" sobre silencio).
    3. Segmento que es SOLO risa con confianza baja (risa alucinada en ruido).
    4. Segmento corto (≤3 palabras) con confianza ínfima (garble de voz lejana;
       el habla real corta — "hola, ¿sí?" — promedia logprob ≥ -0.4). Si la
       frase previa quedó abierta (prev_open), el segmento corto suele ser su
       continuación ("...imágenes" + "blancas.") y el umbral baja a -1.5.
    5. Eco del prompt: Whisper RECITA fragmentos del initial_prompt/hotwords
       ("Palabras frecuentes." salió 6 veces en el registro real). Se descarta
       un segmento multi-palabra que sea substring del prompt si además viene
       de la cola del prompt (lo más recitado) o con confianza baja — así
       "commit, push" dictado de verdad y con buena confianza NO se toca.
    """
    normalized = _normalize_for_blacklist(piece)
    if not normalized:
        # Segmentos de pura puntuación ("...", "…", "¿?"): el decoder rellenando
        # una pausa. Nunca son habla real.
        return "solo puntuación (pausa)"
    if normalized in _HALLUCINATION_SET:
        return "frase fantasma conocida"
    if (
        normalized in _CLOSING_SET
        and isinstance(avg_logprob, (int, float))
        and avg_logprob < config.HALLUCINATION_CLOSING_LOGPROB
    ):
        return (f"despedida fantasma de cola "
                f"(avg_logprob={avg_logprob:.2f})")
    if isinstance(no_speech_prob, (int, float)):
        if no_speech_prob > config.HALLUCINATION_NO_SPEECH_MAX:
            return f"no_speech_prob={no_speech_prob:.2f}"
        if (
            no_speech_prob > config.HALLUCINATION_NO_SPEECH_SOFT
            and isinstance(avg_logprob, (int, float))
            and avg_logprob < config.HALLUCINATION_LOGPROB_MIN
        ):
            return (f"no_speech_prob={no_speech_prob:.2f} + "
                    f"avg_logprob={avg_logprob:.2f}")
    if _is_laugh_only(normalized):
        low_conf = (
            isinstance(avg_logprob, (int, float))
            and avg_logprob < config.HALLUCINATION_LAUGH_LOGPROB
        ) or (
            isinstance(no_speech_prob, (int, float)) and no_speech_prob > 0.3
        )
        if low_conf:
            return f"risa alucinada (avg_logprob={avg_logprob})"
    short_threshold = (
        config.HALLUCINATION_SHORT_LOGPROB_OPEN if prev_open
        else config.HALLUCINATION_SHORT_LOGPROB
    )
    if (
        isinstance(avg_logprob, (int, float))
        and avg_logprob < short_threshold
        and len(normalized.split()) <= config.HALLUCINATION_SHORT_MAX_WORDS
    ):
        return f"segmento corto de confianza ínfima (avg_logprob={avg_logprob:.2f})"
    if (
        prompt_norm
        and " " in normalized
        and len(normalized) >= 8
        and normalized in prompt_norm
    ):
        low_conf = isinstance(avg_logprob, (int, float)) and avg_logprob < -0.4
        in_tail = bool(prompt_tail) and normalized in prompt_tail
        # Dos hotwords seguidos ("commit, push") son habla legítima frecuente;
        # solo una RACHA larga de hotwords delata la recitación.
        hotword_run = (
            bool(hotwords_norm)
            and normalized in hotwords_norm
            and (len(normalized) >= 20 or len(normalized.split()) >= 4)
        )
        if in_tail or hotword_run or low_conf:
            return "eco del prompt inicial"
    return None


def cuda_available() -> bool:
    """True si CTranslate2 ve al menos una GPU NVIDIA. No garantiza que las DLLs
    (cuBLAS/cuDNN) carguen; eso lo valida el warmup en load()."""
    if _CT2 is None:
        return False
    try:
        return _CT2.get_cuda_device_count() > 0
    except Exception:
        return False


class Transcriber:
    """Wrapper sobre faster-whisper. Carga el modelo una sola vez y lo reutiliza.

    Soporta device 'auto'/'cpu'/'cuda'. Con 'auto' (o 'cuda') intenta GPU y, si
    el warmup falla (DLLs cuBLAS/cuDNN ausentes, VRAM, incompatibilidad), cae a
    CPU automáticamente sin romper la app.
    """

    def __init__(self, on_log=None):
        self.on_log = on_log or (lambda msg: None)
        self._model = None
        self._batched = None  # BatchedInferencePipeline lazy, por modelo cargado
        self._current_model_name = None
        self._current_device = None
        self._current_compute_type = None
        self._current_cpu_threads = None
        self._current_num_workers = None
        self._backend_str = "—"
        self.last_transcribe_seconds = 0.0
        # Si CUDA falla una vez (DLLs ausentes, VRAM, etc.), no reintentamos en
        # toda la sesión: evita recargas lentas y cuelgues del contexto CUDA.
        self._cuda_failed = False
        self._load_lock = threading.Lock()
        # Stats acumuladas del dictado en curso (se resetean con begin_dictation).
        # En modo incremental un dictado son VARIAS llamadas a transcribe(); aquí
        # se acumulan descartes/limpiezas de todas para el registro de dictados.
        self._dict_stats = self._new_dictation_stats()

    # ---------------- stats por dictado (para el registro) ----------------
    @staticmethod
    def _new_dictation_stats() -> dict:
        return {
            # [{"texto", "motivo", "avg_logprob", "no_speech_prob"}]
            "descartes": [],
            "puntos_suspensivos": 0,   # nº de "..." eliminados del texto
            "repeticiones": 0,         # palabras recortadas por loops
            "segmentos": 0,            # segmentos emitidos por Whisper (total)
            "min_avg_logprob": None,   # confianza mínima de lo que SÍ se conservó
            "max_no_speech": None,
            # Último texto conservado del dictado (cruza tramos incrementales):
            # permite saber si la frase quedó abierta al evaluar el siguiente
            # segmento corto (guarda 4, umbral de continuación).
            "last_kept_text": "",
            # Idioma detectado por ventana (para "dictar y traducir").
            "idiomas": {},
        }

    def dictation_language(self) -> str | None:
        """Idioma mayoritario detectado en el dictado actual (p.ej. 'es')."""
        langs = (self._dict_stats or {}).get("idiomas") or {}
        if not langs:
            return None
        return max(langs.items(), key=lambda kv: kv[1])[0]

    def begin_dictation(self):
        """Resetea las stats acumuladas. Llamar al INICIO de cada grabación
        (antes de que el worker incremental haga la primera transcripción)."""
        self._dict_stats = self._new_dictation_stats()

    def dictation_stats(self) -> dict:
        """Stats acumuladas desde el último begin_dictation(). Leer al final
        del pipeline (tras finalize() en incremental: el join del worker
        garantiza que ya no hay escrituras en curso)."""
        s = dict(self._dict_stats)
        s["descartes"] = list(s["descartes"])
        return s

    @property
    def current_model_name(self):
        return self._current_model_name

    @property
    def current_device(self):
        return self._current_device

    @property
    def current_compute_type(self):
        return self._current_compute_type

    @property
    def backend_str(self) -> str:
        """Texto para la UI, ej. 'CPU int8' o 'CUDA float16'."""
        return self._backend_str

    # ---------------- carga ----------------
    def _resolve_device(self, device: str | None, enable_gpu: bool) -> str:
        d = (device or config.DEFAULT_DEVICE).lower()
        # Si CUDA ya falló esta sesión, todo va a CPU (no reintentamos).
        if self._cuda_failed:
            return "cpu"
        if d == "cpu":
            return "cpu"
        # cuda_available() responde True con solo el driver NVIDIA; sin las
        # DLLs de cuBLAS/cuDNN (build liviano sin el paquete descargado) la
        # carga en GPU fallaría siempre → ni se intenta.
        usable = cuda_available() and config.cuda_dlls_present()
        if d == "cuda":
            return "cuda" if usable else "cpu"
        # auto
        if enable_gpu and usable:
            return "cuda"
        return "cpu"

    def reset_cuda_failed(self):
        """Permite reintentar GPU (p.ej. tras descargar el paquete NVIDIA)."""
        self._cuda_failed = False

    def resolve_backend(self, device: str | None, compute_type: str | None,
                        enable_gpu: bool = True) -> tuple[str, str]:
        """Devuelve (device, compute) que se usarían realmente, sin cargar nada.
        Útil para saber si un cambio de perfil requiere recargar el modelo."""
        rd = self._resolve_device(device, enable_gpu)
        rc = config.resolve_compute_for_device(rd, compute_type or config.WHISPER_COMPUTE_TYPE)
        return rd, rc

    def is_loaded_as(self, device: str, compute_type: str) -> bool:
        return (
            self._model is not None
            and self._current_device == device
            and self._current_compute_type == compute_type
        )

    def _warmup(self, model):
        """Fuerza un encode real (ruido corto, vad off, beam 1) para validar que
        el backend funciona de verdad — el fallo de cuBLAS aparece en el encode,
        no en la construcción del modelo."""
        noise = (np.random.randn(int(config.SAMPLE_RATE * 0.3)) * 0.01).astype(np.float32)
        segments, _ = model.transcribe(noise, beam_size=1, vad_filter=False)
        for _ in segments:
            break

    def load(self, model_name: str, device: str | None = None,
             compute_type: str | None = None, cpu_threads: int = 0,
             num_workers: int = 1, enable_gpu: bool = True):
        with self._load_lock:
            resolved_device = self._resolve_device(device, enable_gpu)
            resolved_compute = config.resolve_compute_for_device(
                resolved_device, compute_type or config.WHISPER_COMPUTE_TYPE
            )

            # ¿Mismo modelo y backend ya cargado? → reutilizar.
            if (
                self._model is not None
                and self._current_model_name == model_name
                and self._current_device == resolved_device
                and self._current_compute_type == resolved_compute
                and self._current_cpu_threads == cpu_threads
                and self._current_num_workers == num_workers
            ):
                self.on_log(f"[whisper] modelo reutilizado ({self._backend_str}, {model_name})")
                return

            self.on_log(
                f"[whisper] recargando por cambio de config: modelo '{model_name}' "
                f"device={resolved_device} compute={resolved_compute} "
                f"cpu_threads={cpu_threads} num_workers={num_workers}"
            )

            ok = self._try_build(model_name, resolved_device, resolved_compute,
                                 cpu_threads, num_workers)
            if not ok and resolved_device == "cuda":
                # Fallback a CPU int8 sin romper la app. Marca CUDA como fallido
                # para no reintentarlo el resto de la sesión.
                self._cuda_failed = True
                self.on_log("[whisper] ⚠ CUDA falló (DLLs cuBLAS/cuDNN, VRAM o "
                            "incompatibilidad). Cayendo a CPU int8 (no se reintentará "
                            "GPU esta sesión).")
                cpu_compute = config.resolve_compute_for_device("cpu", "auto")
                ok = self._try_build(model_name, "cpu", cpu_compute,
                                     cpu_threads, num_workers)
            if not ok:
                raise RuntimeError(f"No se pudo cargar el modelo '{model_name}'.")

    def _try_build(self, model_name, device, compute_type, cpu_threads, num_workers) -> bool:
        t0 = time.perf_counter()
        self.on_log(f"[whisper] cargando '{model_name}' (device={device}, compute={compute_type})...")
        try:
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                cpu_threads=int(cpu_threads or 0),
                num_workers=int(num_workers or 1),
            )
            # Validación real del backend.
            self._warmup(model)
        except Exception as e:
            self.on_log(f"[whisper] fallo cargando en {device}/{compute_type}: "
                        f"{type(e).__name__}: {str(e)[:160]}")
            return False

        self._model = model
        self._batched = None  # se reconstruye lazy para el nuevo modelo
        self._current_model_name = model_name
        self._current_device = device
        self._current_compute_type = compute_type
        self._current_cpu_threads = cpu_threads
        self._current_num_workers = num_workers
        self._backend_str = f"{'CUDA' if device == 'cuda' else 'CPU'} {compute_type}"
        self.on_log(
            f"[whisper] modelo '{model_name}' listo · backend={self._backend_str} "
            f"({time.perf_counter() - t0:.1f}s)"
        )
        return True

    def _get_batched(self):
        if self._batched is None:
            self._batched = BatchedInferencePipeline(model=self._model)
        return self._batched

    # ---------------- transcripción ----------------
    def transcribe(
        self,
        audio_f32,
        *,
        language: str | None = None,
        beam_size: int = config.DEFAULT_BEAM_SIZE,
        best_of: int = config.DEFAULT_BEST_OF,
        temperature: float = config.DEFAULT_TEMPERATURE,
        vad_filter: bool = config.DEFAULT_VAD_FILTER,
        condition_on_previous_text: bool = config.DEFAULT_CONDITION_ON_PREVIOUS_TEXT,
        initial_prompt: str | None = None,
        audio_duration: float | None = None,
        mixed_language_mode: bool = False,
        debug_segments: bool = False,
        batched: bool = False,
        batch_size: int = config.DEFAULT_BATCH_SIZE,
        hotwords: str | None = None,
        strip_ellipsis: bool = True,
    ) -> str:
        if self._model is None:
            raise RuntimeError("El modelo Whisper no está cargado todavía.")

        # "auto" o None → faster-whisper detecta el idioma automáticamente.
        requested = language if language else "auto"
        lang_arg = None if requested == "auto" else requested
        # Idioma mixto (rev3): el flag ya NO fuerza language=None global (rev1:
        # eso traducía TODO el dictado si la primera ventana parecía EN). En su
        # lugar activa `multilingual=True`: faster-whisper RE-DETECTA el idioma
        # POR SEGMENTO, así una frase completa en inglés queda en inglés y la
        # siguiente en español queda en español. 'es' sigue siendo la base.
        multilingual = bool(mixed_language_mode)
        prompt_arg = initial_prompt if (initial_prompt and initial_prompt.strip()) else None
        hotwords_arg = hotwords.strip() if (hotwords and hotwords.strip()) else None
        # Contexto normalizado del prompt+hotwords para la guarda anti-eco
        # (Whisper a veces recita fragmentos del prompt dentro del dictado).
        # La cola del prompt (lo más recitado) y los hotwords van aparte: en
        # el string combinado la cola real del prompt queda en el medio, y a
        # los hotwords se les exige racha larga (2 seguidos son habla normal).
        _p_norm = " ".join((prompt_arg or "").lower().split())
        _h_norm = " ".join((hotwords_arg or "").lower().split())
        prompt_norm = (_p_norm + " " + _h_norm).strip()
        prompt_tail = _p_norm[-80:]

        # Escalera de temperaturas: es el mecanismo anti-repetición de Whisper.
        # Si el decode a una temperatura sale degenerado (compression_ratio >2.4
        # = texto repetitivo, o logprob bajo), reintenta la ventana con la
        # siguiente. Pasar un float único (0.0) DESACTIVABA ese fallback: cuando
        # el beam search caía en un loop ("no, no, no, ..."), no había reintento
        # y el loop se pegaba tal cual. La primera temperatura sigue siendo la
        # configurada, así que el resultado no cambia cuando el decode es sano.
        try:
            t_base = min(1.0, max(0.0, float(temperature)))
        except (TypeError, ValueError):
            t_base = 0.0
        temperature_ladder = [t_base] + [t for t in (0.2, 0.4, 0.6, 0.8, 1.0) if t > t_base]

        self.on_log(
            f"[whisper] params: model={self._current_model_name} backend={self._backend_str} "
            f"idioma={requested} task={config.TASK} beam_size={beam_size} best_of={best_of} "
            f"temperature={t_base} (fallback→{temperature_ladder[-1]}) "
            f"vad_filter={'on' if vad_filter else 'off'} "
            f"cond_prev={'on' if condition_on_previous_text else 'off'} "
            f"prompt={'on' if prompt_arg else 'off'} "
            f"hotwords={'on' if hotwords_arg else 'off'} "
            f"mixed={'on (multilingual por segmento)' if multilingual else 'off'} "
            f"batched={'on(bs=%d)' % batch_size if batched else 'off'}"
        )
        if audio_duration is not None:
            self.on_log(f"[whisper] audio_duracion={audio_duration:.2f}s")

        t0 = time.perf_counter()
        if batched:
            # Batched: mismos parámetros (beam/best_of/temperature/prompt) → misma
            # calidad. Hace su propio chunking por VAD → más rápido en audio largo.
            segments, info = self._get_batched().transcribe(
                audio_f32,
                language=lang_arg,
                task=config.TASK,
                beam_size=beam_size,
                best_of=best_of,
                # OJO: el pipeline batched solo usa temperature_ladder[0] (no
                # tiene fallback); ahí la guarda es collapse_repetition_runs().
                temperature=temperature_ladder,
                vad_filter=True,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=prompt_arg,
                hotwords=hotwords_arg,
                multilingual=multilingual,
                batch_size=int(batch_size),
            )
        else:
            segments, info = self._model.transcribe(
                audio_f32,
                language=lang_arg,
                task=config.TASK,
                beam_size=beam_size,
                best_of=best_of,
                temperature=temperature_ladder,
                vad_filter=vad_filter,
                condition_on_previous_text=condition_on_previous_text,
                initial_prompt=prompt_arg,
                hotwords=hotwords_arg,
                multilingual=multilingual,
            )

        # Concatenamos TODOS los segmentos. Un segmento vacío no detiene la
        # cadena: solo lo saltamos para no introducir doble espacio. Los
        # segmentos alucinados (frases fantasma / no-habla) se descartan.
        text_parts: list = []
        seg_count = 0
        empty_count = 0
        dropped_count = 0
        stats = self._dict_stats
        # Texto conservado previo (persiste ENTRE tramos incrementales vía
        # las stats del dictado): si no cerró frase, el siguiente segmento
        # corto es probable continuación y la guarda 4 exige umbral -1.5.
        prev_kept = str(stats.get("last_kept_text") or "")
        for seg in segments:
            seg_count += 1
            stats["segmentos"] += 1
            piece = (seg.text or "").strip()
            avg_lp_g = getattr(seg, "avg_logprob", None)
            no_sp_g = getattr(seg, "no_speech_prob", None)
            if not piece:
                empty_count += 1
            else:
                prev_open = bool(prev_kept) and not prev_kept.rstrip().endswith(
                    _SENTENCE_END_CHARS
                )
                reason = is_hallucinated_segment(piece, avg_lp_g, no_sp_g,
                                                 prompt_norm=prompt_norm,
                                                 prompt_tail=prompt_tail,
                                                 hotwords_norm=_h_norm,
                                                 prev_open=prev_open)
                if reason is not None:
                    dropped_count += 1
                    stats["descartes"].append({
                        "texto": piece,
                        "motivo": reason,
                        "avg_logprob": round(avg_lp_g, 3) if isinstance(avg_lp_g, (int, float)) else None,
                        "no_speech_prob": round(no_sp_g, 3) if isinstance(no_sp_g, (int, float)) else None,
                    })
                    self.on_log(
                        f"[whisper] segmento descartado (alucinación: {reason}): "
                        f"{piece!r}"
                    )
                else:
                    text_parts.append(piece)
                    prev_kept = piece
                    # Confianza de lo conservado (para marcar dictados sospechosos).
                    if isinstance(avg_lp_g, (int, float)):
                        cur = stats["min_avg_logprob"]
                        stats["min_avg_logprob"] = (
                            round(avg_lp_g, 3) if cur is None else min(cur, round(avg_lp_g, 3))
                        )
                    if isinstance(no_sp_g, (int, float)):
                        cur = stats["max_no_speech"]
                        stats["max_no_speech"] = (
                            round(no_sp_g, 3) if cur is None else max(cur, round(no_sp_g, 3))
                        )
            if debug_segments:
                avg_lp = getattr(seg, "avg_logprob", None)
                no_sp = getattr(seg, "no_speech_prob", None)
                start = getattr(seg, "start", None)
                end = getattr(seg, "end", None)
                start_s = f"{start:.2f}s" if isinstance(start, (int, float)) else "n/a"
                end_s = f"{end:.2f}s" if isinstance(end, (int, float)) else "n/a"
                self.on_log(
                    f"[whisper.seg #{seg_count}] "
                    f"start={start_s} end={end_s} "
                    f"avg_logprob={('%.2f' % avg_lp) if avg_lp is not None else 'n/a'} "
                    f"no_speech_prob={('%.2f' % no_sp) if no_sp is not None else 'n/a'} "
                    f"text={piece!r}"
                )

        elapsed = time.perf_counter() - t0
        self.last_transcribe_seconds = elapsed
        stats["last_kept_text"] = prev_kept
        text = " ".join(text_parts).strip()

        # Última guarda anti-loop (cubre también el modo batched, sin fallback).
        text, rep_dropped = collapse_repetition_runs(text)
        if rep_dropped:
            stats["repeticiones"] += rep_dropped
            self.on_log(
                f"[whisper] ⚠ loop de repetición recortado: {rep_dropped} "
                f"palabras repetidas eliminadas del resultado"
            )
        # Risa repetida ("Jajaja. Jajaja. Jajaja."): loop de ruido que la guarda
        # general no atrapa si la racha es corta o la corta una palabra suelta.
        text, laugh_dropped = collapse_laugh_runs(text)
        if laugh_dropped:
            stats["repeticiones"] += laugh_dropped
            self.on_log(
                f"[whisper] ⚠ risa repetida recortada: {laugh_dropped} palabras"
            )

        # Puntos suspensivos de pausa ("Hola... quería") — Whisper los inserta
        # cuando el hablante calla a mitad de frase. Se quitan aquí (antes de
        # reemplazos) para que apliquen igual en modo incremental (por tramo).
        if strip_ellipsis:
            text, ell_removed = strip_ellipsis_text(text)
            if ell_removed:
                stats["puntos_suspensivos"] += ell_removed
                self.on_log(
                    f"[whisper] puntos suspensivos de pausa eliminados: {ell_removed}"
                )

        dur = float(getattr(info, "duration", 0.0) or 0.0)
        rt_ratio = (elapsed / dur) if dur > 0 else 0.0
        self.on_log(
            f"[whisper] idioma_detectado={info.language} prob={info.language_probability:.2f} "
            f"solicitado={requested} duracion={dur:.2f}s segs={seg_count} "
            f"vacios={empty_count} descartados={dropped_count}"
        )
        try:
            langs = stats.setdefault("idiomas", {})
            langs[info.language] = langs.get(info.language, 0) + 1
        except Exception:
            pass
        self.on_log(
            f"[whisper] transcrito en {elapsed:.2f}s (RT ratio={rt_ratio:.2f}x)"
        )
        return text
