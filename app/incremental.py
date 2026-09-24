"""Transcripción incremental: transcribe MIENTRAS grabas.

Idea: en vez de esperar a que sueltes el hotkey para transcribir todo el audio
de golpe (30-40s de espera en dictados largos), un worker en segundo plano va
transcribiendo los tramos ya hablados. Los cortes se hacen SOLO en silencios
(nunca a mitad de palabra), por lo que no hace falta solape ni deduplicación.
Al soltar la tecla solo queda pendiente el último tramo → la espera final es
de ~1-2s sin importar cuánto dictaste.

Uso (lo orquesta el Controller en main.py):

    session = IncrementalSession(transcribe_fn=..., on_log=...)
    recorder.start(chunk_sink=session.feed)   # feed corre en el callback de audio
    ...usuario habla...
    recorder.stop()
    text, stats = session.finalize()          # transcribe el tramo final y une todo
"""

import queue
import re
import threading
import time
from collections import deque

import numpy as np

from . import config

# ─── Unión de tramos ────────────────────────────────────────────────────
# Whisper arranca CADA tramo con mayúscula aunque continúe la frase anterior
# ("...al colocar" + "Voy a colocar..."). El 35% de los dictados reales tenía
# este defecto (análisis del registro, 2026-07-21). Si el tramo previo no cerró
# frase, la primera palabra del siguiente pasa a minúscula — salvo acrónimos
# (PSD), palabras con dígitos o ya en minúscula.

_SENT_END_CHARS = tuple(".!?…:;")
# Mayúscula seguida de minúscula = capitalización de arranque (no acrónimo).
_FIRST_WORD_RE = re.compile(r"^([¿¡\"'(\[]*)([A-ZÁÉÍÓÚÑÜ])([a-záéíóúñü])")


def _decapitalize_first_word(text: str) -> str:
    m = _FIRST_WORD_RE.match(text)
    if not m:
        return text
    # Marca con mayúscula interna (GitHub, AnyDesk, IPRoyal): no es
    # capitalización de arranque, es el nombre. Se respeta.
    word = re.match(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9]+", text[m.start(2):])
    if word and any(c.isupper() for c in word.group(0)[1:]):
        return text
    return text[:m.start(2)] + m.group(2).lower() + text[m.end(2):]


# Análisis del registro 2026-09-23 (2.854 dictados / 31 días): dos defectos
# más que SOLO aparecen en dictados multi-tramo (0% en dictados de un tramo):
#   a) "punto + minúscula" en la frontera (45% de los multi-tramo): Whisper
#      cierra cada tramo con "." porque el audio termina, pero arranca el
#      siguiente en minúscula porque la frase continúa ("...puro XAPK. por
#      todos lados"). El punto sobra: se quita y se une con espacio.
#   b) Palabra repetida en la frontera (7%): el corte cae justo tras una
#      palabra que el usuario repite al retomar ("mejorar mi" + "mi github").
#      Se descarta la copia del tramo siguiente.
_LOWER_START_RE = re.compile(r"^[¿¡\"'(\[]*[a-záéíóúñü]")
_WORD_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9]+")
_BOUNDARY_MAX_OVERLAP = 3
# Palabras que sí abren frase corta tras un punto de tramo ("Muchas gracias.",
# "Listo.", "Ya está."): NO se pegan a la frase anterior.
_SHORT_TAIL_STARTERS = {
    "gracias", "muchas", "listo", "lista", "ok", "okay", "vale", "perfecto", "bueno",
    "hola", "adiós", "adios", "chao", "chau", "sí", "si", "no", "entonces", "ahora",
    "luego", "después", "bien", "claro", "exacto", "correcto", "fin", "dale", "ya",
    "eso", "esto", "es", "está", "así", "hecho", "thanks", "thank", "done", "yes",
    "okey", "nada", "espera",
}


def _drop_boundary_duplicate(prev: str, part: str) -> str:
    """Si el tramo nuevo empieza repitiendo las últimas 1-3 palabras del
    anterior ("mejorar mi" + "mi github", "o sea," + "o sea, 5.25"), quita esa
    repetición del tramo nuevo (y la coma/espacio que la siga)."""
    prev_words = [w.lower() for w in _WORD_TOKEN_RE.findall(prev)][-_BOUNDARY_MAX_OVERLAP:]
    head = list(_WORD_TOKEN_RE.finditer(part))[:_BOUNDARY_MAX_OVERLAP]
    for n in range(min(len(prev_words), len(head)), 0, -1):
        if [m.group(0).lower() for m in head[:n]] != prev_words[-n:]:
            continue
        if n == 1 and len(head[0].group(0)) < 2:
            continue  # "voy a" + "a la máquina": una letra no cuenta
        rest = part[head[n - 1].end():]
        return re.sub(r"^[\s,;:]+", "", rest)
    return part


def _is_short_tail(part: str) -> bool:
    """Tramo de 1-2 palabras que no abre frase ("Correctly.", "blancas."):
    casi siempre es la cola de la frase anterior tras una pausa."""
    words = _WORD_TOKEN_RE.findall(part)
    if not 1 <= len(words) <= 2:
        return False
    if part.rstrip().endswith(("?", "!")):
        return False
    return words[0].lower() not in _SHORT_TAIL_STARTERS


def join_chunks(parts: list) -> str:
    """Une los textos de los tramos arreglando la frontera entre ellos."""
    out: list = []
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        if out:
            prev = out[-1].rstrip()
            part = _drop_boundary_duplicate(prev, part)
            if not part:
                continue
            chunk_dot = prev.endswith(".") and not prev.endswith("...")
            if chunk_dot and _LOWER_START_RE.match(part):
                # Punto de cierre de tramo + continuación en minúscula: sobra.
                out[-1] = prev[:-1].rstrip()
            elif chunk_dot and _is_short_tail(part):
                # "transcribed." + "Correctly.": cola corta capitalizada por
                # Whisper al arrancar el tramo; es continuación.
                out[-1] = prev[:-1].rstrip()
                part = _decapitalize_first_word(part)
            elif not prev.endswith(_SENT_END_CHARS):
                part = _decapitalize_first_word(part)
        out.append(part)
    return " ".join(out).strip()


def _normalize_chunk(audio_f32: np.ndarray) -> np.ndarray:
    """Misma normalización suave que AudioRecorder.stop(): si el mic tiene gain
    bajo, sube el volumen hasta peak~0.6 (tope ×10) para que el VAD de Whisper
    no descarte la voz. Se aplica POR TRAMO para que todos lleguen parejos."""
    if not audio_f32.size:
        return audio_f32
    peak = float(np.max(np.abs(audio_f32)))
    if peak > 0.01:
        gain = min(0.6 / peak, 10.0)
        if gain > 1.5:
            return np.clip(audio_f32 * gain, -1.0, 1.0)
    return audio_f32


class IncrementalSession:
    """Una sesión = una grabación (press→release del hotkey).

    - `feed(indata)` se llama desde el callback de sounddevice con bloques
      int16. Debe ser MUY barato: acumula y, como mucho, calcula un RMS corto.
    - Un worker propio consume los tramos cerrados y los transcribe en orden.
      Solo ESTE hilo toca el modelo durante la sesión (sin carreras).
    - `finalize()` cierra el tramo final, espera al worker y une los textos.
    """

    def __init__(
        self,
        transcribe_fn,
        on_log=None,
        sample_rate: int = config.SAMPLE_RATE,
        min_chunk_seconds: float = config.INCREMENTAL_MIN_CHUNK_SECONDS,
        silence_seconds: float = config.INCREMENTAL_SILENCE_SECONDS,
        silence_rms: float = config.INCREMENTAL_SILENCE_RMS,
    ):
        self._transcribe = transcribe_fn          # (np.float32 16kHz) -> str
        self.on_log = on_log or (lambda m: None)
        self._sr = int(sample_rate)
        self._min_chunk_samples = int(min_chunk_seconds * self._sr)
        self._silence_samples = int(silence_seconds * self._sr)
        self._silence_rms = float(silence_rms)

        # Buffer del tramo en curso (bloques int16 tal como llegan).
        self._buf: list = []
        self._buf_samples = 0
        # Ventana deslizante de (n_muestras, suma_cuadrados) para calcular el
        # RMS de la cola sin re-concatenar el buffer en cada callback.
        self._recent = deque()
        self._recent_samples = 0
        self._recent_sumsq = 0.0

        self._queue: "queue.Queue" = queue.Queue()
        self._results: dict = {}
        self._chunk_count = 0
        self._transcribe_seconds_total = 0.0
        self._errors = 0
        self._closed = False
        self._feed_lock = threading.Lock()

        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    # ---------------- callback de audio (hilo de sounddevice) ----------------
    def feed(self, indata: np.ndarray):
        """Recibe cada bloque int16 del callback. Acumula y corta en silencios."""
        if self._closed:
            return
        block = np.asarray(indata).reshape(-1)
        with self._feed_lock:
            self._buf.append(block.copy())
            n = block.size
            self._buf_samples += n

            # RMS del bloque en escala [-1,1] (int16/32768; lineal, así que
            # dividir el RMS equivale a escalar las muestras).
            arr = block.astype(np.float32)
            sumsq = float(np.dot(arr, arr)) / (32768.0 * 32768.0)
            self._recent.append((n, sumsq))
            self._recent_samples += n
            self._recent_sumsq += sumsq
            # Recorta la ventana a ~silence_samples.
            while self._recent and (self._recent_samples - self._recent[0][0]) >= self._silence_samples:
                old_n, old_sq = self._recent.popleft()
                self._recent_samples -= old_n
                self._recent_sumsq -= old_sq

            # ¿Cerramos tramo? Solo si ya hay material suficiente Y la cola es
            # silencio (el hablante hizo una pausa → corte seguro entre palabras).
            if self._buf_samples >= self._min_chunk_samples and self._recent_samples >= int(self._silence_samples * 0.8):
                rms = (self._recent_sumsq / max(1, self._recent_samples)) ** 0.5
                if rms < self._silence_rms:
                    self._cut_chunk_unlocked()

    def _trim_trailing_silence(self, raw_f32: np.ndarray) -> np.ndarray:
        """Recorta la cola SIN VOZ del tramo final (ruido de sala, respiración,
        el click de soltar el hotkey). Whisper alucina despedidas ("Muchas
        gracias.", "Chao.") justo sobre ese ruido de cola — si no hay audio,
        no hay alucinación. Deja 0.25s de margen tras la última voz; si el
        tramo entero es no-voz devuelve un array vacío (el tramo se salta)."""
        hop = int(self._sr * 0.1)  # ventanas de 100ms
        n_hops = raw_f32.size // hop
        if n_hops == 0:
            return raw_f32
        windows = raw_f32[: n_hops * hop].reshape(n_hops, hop)
        rms = np.sqrt(np.mean(windows.astype(np.float64) ** 2, axis=1))
        voiced = np.nonzero(rms >= self._silence_rms)[0]
        if voiced.size == 0:
            return raw_f32[:0]
        end = min(raw_f32.size, (int(voiced[-1]) + 1) * hop + int(self._sr * 0.25))
        if end < raw_f32.size:
            self.on_log(
                f"[incremental] cola sin voz recortada del tramo final "
                f"({(raw_f32.size - end) / self._sr:.1f}s)"
            )
        return raw_f32[:end]

    def _cut_chunk_unlocked(self, trim_tail: bool = False):
        """Cierra el buffer actual como tramo y lo encola. Requiere _feed_lock.
        Con trim_tail=True (solo el tramo final) recorta la cola sin voz."""
        if not self._buf:
            return
        audio_i16 = np.concatenate(self._buf)
        self._buf = []
        self._buf_samples = 0
        self._recent.clear()
        self._recent_samples = 0
        self._recent_sumsq = 0.0

        raw_f32 = audio_i16.astype(np.float32) / 32768.0
        if trim_tail:
            raw_f32 = self._trim_trailing_silence(raw_f32)
            if raw_f32.size < int(self._sr * 0.25):
                self.on_log("[incremental] tramo final sin voz tras el recorte; saltado")
                return
        # Tramo prácticamente mudo (usuario en pausa larga con el hotkey
        # presionado): transcribirlo solo invita alucinaciones sobre el ruido
        # de fondo. El umbral es la mitad del aviso de "nivel muy bajo" del
        # recorder, para no comerse micrófonos con gain pobre.
        peak = float(np.max(np.abs(raw_f32))) if raw_f32.size else 0.0
        if peak < 0.005:
            self.on_log(
                f"[incremental] tramo sin voz (peak={peak:.4f}) saltado"
            )
            return

        idx = self._chunk_count
        self._chunk_count += 1
        audio_f32 = _normalize_chunk(raw_f32)
        self._queue.put((idx, audio_f32))
        self.on_log(
            f"[incremental] tramo #{idx + 1} cerrado en silencio "
            f"({audio_f32.size / self._sr:.1f}s) → transcribiendo en segundo plano"
        )

    # ---------------- worker (hilo propio) ----------------
    def _run_worker(self):
        while True:
            item = self._queue.get()
            if item is None:  # sentinela de cierre
                self._queue.task_done()
                return
            idx, audio = item
            t0 = time.perf_counter()
            try:
                text = self._transcribe(audio) or ""
            except Exception as e:
                self._errors += 1
                text = ""
                self.on_log(f"[incremental] error transcribiendo tramo #{idx + 1}: {e}")
            elapsed = time.perf_counter() - t0
            self._transcribe_seconds_total += elapsed
            self._results[idx] = text.strip()
            self._queue.task_done()

    # ---------------- cierre (hilo del pipeline) ----------------
    def finalize(self, timeout: float = 120.0):
        """Cierra el tramo final, espera al worker y devuelve (texto, stats).

        Se llama DESPUÉS de recorder.stop() (ya no llegan más callbacks).
        stats: dict con chunks, espera_final_s, transcripcion_total_s, errores.
        """
        t_wait0 = time.perf_counter()
        with self._feed_lock:
            self._closed = True
            # El tramo final se transcribe aunque sea corto; si es ínfimo
            # (<0.25s) no aporta nada y el VAD lo tiraría igual. trim_tail:
            # este tramo termina al soltar el hotkey (no en un silencio
            # detectado), así que puede arrastrar segundos de ruido de cola.
            if self._buf_samples >= int(self._sr * 0.25):
                self._cut_chunk_unlocked(trim_tail=True)
            else:
                self._buf = []
                self._buf_samples = 0
        self._queue.put(None)  # sentinela: el worker termina tras drenar la cola

        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            self.on_log("[incremental] ⚠ timeout esperando al worker; devuelvo lo listo")

        parts = [self._results[i] for i in sorted(self._results) if self._results[i]]
        text = join_chunks(parts)
        stats = {
            "chunks": self._chunk_count,
            "espera_final_s": time.perf_counter() - t_wait0,
            "transcripcion_total_s": self._transcribe_seconds_total,
            "errores": self._errors,
        }
        return text, stats

    def abort(self):
        """Descarta la sesión (ej. grabación vacía) sin esperar resultados."""
        with self._feed_lock:
            self._closed = True
            self._buf = []
            self._buf_samples = 0
        self._queue.put(None)
