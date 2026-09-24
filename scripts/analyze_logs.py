# -*- coding: utf-8 -*-
"""Analiza el registro de dictados de Wisip y resume los errores recurrentes.

Lee los JSONL de %APPDATA%\\local-voice-typer\\logs\\dictados-*.jsonl y muestra:

  - Volumen: dictados, minutos de audio, palabras, dictados vacíos.
  - Puntos suspensivos de pausa eliminados (cuántos y en qué % de dictados).
  - Segmentos descartados por alucinación, agrupados por texto → los que se
    repiten son candidatos a HALLUCINATION_PHRASES (blacklist).
  - Finales de dictado más repetidos (últimas palabras) → detecta las "varias
    palabras" fantasma que Whisper añade al terminar.
  - Reemplazos más aplicados y dictados sospechosos con audio guardado.

El resumen es el insumo del ciclo de mejora: con él se deciden nuevas entradas
para replacements.json, la blacklist o los hotwords.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/analyze_logs.py            # todo el registro
    python scripts/analyze_logs.py --dias 5   # solo los últimos 5 días
    python scripts/analyze_logs.py --crudo    # además, volcado de crudo≠final
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402


def load_entries(dias: int | None) -> list:
    """Carga todas las entradas de los JSONL, opcionalmente solo N días atrás."""
    entries = []
    cutoff = None
    if dias is not None:
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - dias * 86400)
        )
    for path in sorted(config.DICTATION_LOGS_DIR.glob("dictados-*.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if cutoff and str(e.get("ts", "")) < cutoff:
                    continue
                entries.append(e)
    return entries


def _tail_words(text: str, n: int = 4) -> str:
    words = text.split()
    return " ".join(words[-n:]).lower().strip("¡!¿?.,;:… ") if words else ""


def main():
    ap = argparse.ArgumentParser(description="Resumen del registro de dictados de Wisip")
    ap.add_argument("--dias", type=int, default=None, help="solo los últimos N días")
    ap.add_argument("--crudo", action="store_true",
                    help="volcar también los dictados donde crudo != final")
    args = ap.parse_args()

    entries = load_entries(args.dias)
    if not entries:
        print(f"No hay entradas en {config.DICTATION_LOGS_DIR}")
        print("(el registro se llena al dictar con la app; revisa que "
              "'dictation_log_enabled' esté activo en app_settings.json)")
        return

    periodo = f"{entries[0].get('ts', '?')[:10]} a {entries[-1].get('ts', '?')[:10]}"
    total = len(entries)
    vacios = [e for e in entries if not e.get("final")]
    audio_min = sum(float(e.get("audio_s") or 0.0) for e in entries) / 60.0
    palabras = sum(len(str(e.get("final") or "").split()) for e in entries)
    con_ellipsis = [e for e in entries if e.get("puntos_suspensivos")]
    sospechosos = [e for e in entries if e.get("sospechoso")]
    con_audio = [e for e in entries if e.get("audio")]

    print(f"── Registro de dictados · {periodo} " + "─" * 30)
    print(f"Dictados: {total}   audio: {audio_min:.1f} min   palabras: {palabras}")
    print(f"Vacíos (todo descartado): {len(vacios)}   "
          f"con '...' eliminados: {len(con_ellipsis)} "
          f"({100.0 * len(con_ellipsis) / total:.0f}%)   "
          f"sospechosos: {len(sospechosos)}")

    # ── Descartes por alucinación (candidatos a blacklist) ──────────────
    desc = Counter()
    for e in entries:
        for d in e.get("descartes") or []:
            texto = str(d.get("texto", "")).strip()
            if texto:
                desc[texto.lower()] += 1
    if desc:
        print("\n── Segmentos descartados (candidatos a blacklist si se repiten) ──")
        for texto, n in desc.most_common(15):
            print(f"  {n:3d}x  {texto!r}")

    # ── Finales repetidos (las 'varias palabras' fantasma al terminar) ──
    tails = Counter()
    for e in entries:
        t = _tail_words(str(e.get("crudo") or e.get("final") or ""))
        if t:
            tails[t] += 1
    repetidos = [(t, n) for t, n in tails.most_common(10) if n >= 3]
    if repetidos:
        print("\n── Finales de dictado más repetidos (¿cola fantasma?) ──")
        for t, n in repetidos:
            print(f"  {n:3d}x  ...{t!r}")

    # ── Colas de despedida en el texto FINAL (se colaron las guardas) ────
    # Whisper "cierra el video" sobre el ruido de cola: "Muchas gracias.",
    # "Chao.", "suscríbete"... Si aparecen aquí es que pasaron los filtros;
    # verificar a oído (columna audio) si de verdad se dictaron.
    cierre_re = re.compile(
        r"(?:muchas gracias|gracias(?: a todos)?|chao|chau|adiós|hasta luego|"
        r"hasta la próxima|nos vemos|un saludo|saludos|buenas noches|"
        r"suscríbete[^.]*|gracias por ver[^.]*|thank you|thanks|bye)"
        r"[\s.!¡…]*$", re.IGNORECASE)
    con_cierre = [e for e in entries
                  if e.get("final") and cierre_re.search(str(e["final"]).strip())]
    if con_cierre:
        print(f"\n── Dictados que TERMINAN en fórmula de despedida ({len(con_cierre)}) ──")
        print("   (¿real o cola fantasma? verificar a oído si hay audio)")
        for e in con_cierre[-10:]:
            final = str(e["final"])
            print(f"  [{e.get('ts')}] logprob={e.get('min_avg_logprob')} "
                  f"audio={e.get('audio') or '-'}")
            print(f"    ...{final[-90:]!r}")

    # ── Reemplazos más aplicados ─────────────────────────────────────────
    reps = Counter()
    for e in entries:
        for par in e.get("reemplazos") or []:
            try:
                k, v = par
                reps[f"{k} -> {v}"] += 1
            except Exception:
                continue
    if reps:
        print("\n── Reemplazos más aplicados ──")
        for r, n in reps.most_common(10):
            print(f"  {n:3d}x  {r}")

    # ── Audio guardado para verificación ────────────────────────────────
    if con_audio:
        print(f"\n── Audio guardado ({len(con_audio)} dictados) en "
              f"{config.DICTATION_LOG_AUDIO_DIR} ──")
        for e in con_audio[-10:]:
            print(f"  {e.get('audio')}  ({e.get('audio_s')}s)  "
                  f"final={str(e.get('final'))[:60]!r}")

    # ── Volcado crudo != final (para revisar palabras mal oídas) ────────
    if args.crudo:
        difs = [e for e in entries if e.get("crudo") and e.get("crudo") != e.get("final")]
        print(f"\n── Dictados con crudo != final ({len(difs)}) ──")
        for e in difs:
            print(f"  [{e.get('ts')}]")
            print(f"    crudo: {e.get('crudo')!r}")
            print(f"    final: {e.get('final')!r}")

    print("\nSiguiente paso: llevar este resumen a una sesión de Claude Code y")
    print("convertir los patrones en reemplazos / blacklist / hotwords.")


if __name__ == "__main__":
    main()
