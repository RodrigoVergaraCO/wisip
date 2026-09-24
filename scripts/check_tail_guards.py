# -*- coding: utf-8 -*-
"""Valida las guardas anti-cola-fantasma SIN cargar el modelo.

Cubre las dos capas nuevas (2026-08-03):
  1. IncrementalSession._trim_trailing_silence: recorta el ruido de cola del
     tramo final (de ahí salen los "Muchas gracias."/"Chao." fantasma).
  2. is_hallucinated_segment: despedidas exactas con confianza baja se
     descartan; dictadas de verdad (confianza normal) pasan.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_tail_guards.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np  # noqa: E402

from app.incremental import IncrementalSession  # noqa: E402
from app.transcriber import is_hallucinated_segment  # noqa: E402

SR = 16000
FAILS = []


def check(name: str, ok: bool, detail: str = ""):
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def make_session() -> IncrementalSession:
    logs = []
    return IncrementalSession(transcribe_fn=lambda a: "", on_log=logs.append)


def voice(seconds: float) -> np.ndarray:
    """Pseudo-voz: ruido con amplitud claramente por encima del umbral."""
    rng = np.random.default_rng(7)
    return (rng.standard_normal(int(SR * seconds)) * 0.08).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    """Ruido de sala por debajo del umbral de silencio (RMS ~0.001)."""
    rng = np.random.default_rng(9)
    return (rng.standard_normal(int(SR * seconds)) * 0.001).astype(np.float32)


def main():
    print("── Recorte de cola sin voz (tramo final) ──")
    s = make_session()

    a = np.concatenate([voice(2.0), silence(3.0)])
    t = s._trim_trailing_silence(a)
    check("voz + 3s de ruido de cola → recorta la cola",
          SR * 2.0 <= t.size <= SR * 2.4, f"quedaron {t.size / SR:.2f}s")

    a = silence(3.0)
    t = s._trim_trailing_silence(a)
    check("tramo 100% sin voz → queda vacío (se salta)",
          t.size == 0, f"quedaron {t.size / SR:.2f}s")

    a = voice(2.0)
    t = s._trim_trailing_silence(a)
    check("voz hasta el final → no recorta nada", t.size == a.size)

    a = np.concatenate([silence(1.0), voice(1.5), silence(4.0)])
    t = s._trim_trailing_silence(a)
    check("silencio + voz + cola larga → conserva hasta la voz (+margen)",
          SR * 2.5 <= t.size <= SR * 2.9, f"quedaron {t.size / SR:.2f}s")

    a = voice(0.15)
    t = s._trim_trailing_silence(a)
    check("tramo más corto que una ventana (100ms) → intacto", t.size == a.size)

    s.abort()

    print("\n── Guarda de despedidas fantasma (confianza baja) ──")
    cases = [
        # (texto, avg_logprob, no_speech, se_descarta, nombre)
        ("Muchas gracias.", -0.70, 0.0, True,
         "'Muchas gracias.' con logprob -0.70 → descartada"),
        ("Muchas gracias.", -0.20, 0.0, False,
         "'Muchas gracias.' con logprob -0.20 (dictada real) → pasa"),
        ("Chao.", -0.60, 0.0, True, "'Chao.' con logprob -0.60 → descartada"),
        ("Gracias.", -0.55, 0.0, True, "'Gracias.' con logprob -0.55 → descartada"),
        ("Gracias.", -0.40, 0.0, False,
         "'Gracias.' con logprob -0.40 (dictada real) → pasa"),
        ("Gracias por la ayuda.", -0.90, 0.0, False,
         "frase real que CONTIENE 'gracias' → pasa (no es match exacto)"),
        ("Nos vemos.", -0.52, 0.0, True, "'Nos vemos.' con logprob -0.52 → descartada"),
        ("gracias", None, None, False, "sin métricas de confianza → no se toca"),
        ("Gracias por ver el video.", -0.30, 0.0, True,
         "blacklist clásica sigue descartando SIN mirar confianza"),
        ("Y muchas gracias por acompañarnos en este proceso.", -0.70, 0.0, False,
         "frase larga con despedida dentro → pasa"),
    ]
    for texto, lp, ns, should_drop, name in cases:
        reason = is_hallucinated_segment(texto, lp, ns)
        ok = (reason is not None) == should_drop
        check(name, ok, f"motivo={reason!r}")

    print("\n── Guarda 4 con frase abierta (caso real 'blancas', 2026-08-03) ──")
    open_cases = [
        # (texto, logprob, prev_open, se_descarta, nombre)
        ("blancas.", -1.15, True, False,
         "'...imágenes' + 'blancas.' (-1.15, frase abierta) → se conserva"),
        ("blancas.", -1.15, False, True,
         "'blancas.' (-1.15) tras frase CERRADA → se descarta"),
        ("da ufals.", -1.60, True, True,
         "garble (-1.60) se descarta incluso con frase abierta"),
    ]
    for texto, lp, prev_open, should_drop, name in open_cases:
        reason = is_hallucinated_segment(texto, lp, 0.0, prev_open=prev_open)
        ok = (reason is not None) == should_drop
        check(name, ok, f"motivo={reason!r}")

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    total = 5 + len(cases) + len(open_cases)
    print(f"✓ Los {total} checks pasaron.")


if __name__ == "__main__":
    main()
