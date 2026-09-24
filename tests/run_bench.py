# -*- coding: utf-8 -*-
"""
Benchmark de transcripción de Wisip (extremo a extremo).

Ruta de la prueba (igual que la del usuario real):
    TTS (voz SAPI)  ->  CABLE Input  ==[cable virtual]==>  CABLE Output
                                                              |
                              AudioRecorder de Wisip  <-------+
                                      |
                              Transcriber (faster-whisper)
                                      |
                              Replacements (pipeline real)
                                      |
                              puntuación de precisión + tiempos

Mide, por modelo y por caso:
  - audio_s        : duración del audio dictado (tiempo real que el usuario habla).
  - record_s       : tiempo de captura (≈ audio_s; es tiempo real ineludible).
  - transcribe_s   : LO QUE EL USUARIO ESPERA tras soltar la tecla.
  - rt_ratio       : transcribe_s / audio_s  (clave para el veredicto de UX).
  - replace_s, wer, key_hits.

Restaura sd.default.device al terminar (no toca el default de Windows).

Uso:
    python tests/run_bench.py                 # modelos base,small  (en caché)
    python tests/run_bench.py --models small  # solo small
    python tests/run_bench.py --direct        # sin cable: alimenta el WAV directo
    python tests/run_bench.py --language auto # fuerza idioma (def: es, el default app)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# Permite importar `app.*` y los módulos hermanos del paquete de pruebas.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402

import audio_io  # noqa: E402
import corpus  # noqa: E402
from app import config  # noqa: E402
from app.audio_recorder import AudioRecorder  # noqa: E402
from app.replacements import Replacements  # noqa: E402
from app.transcriber import Transcriber, cuda_available  # noqa: E402


def _silent(_msg):
    pass


def _record_via_cable(rec: AudioRecorder, wav_path: str):
    """Reproduce el WAV por el output por defecto (CABLE Input) mientras el
    AudioRecorder graba del input por defecto (CABLE Output). Devuelve
    (audio_f32, record_seconds)."""
    audio = audio_io.read_wav_f32(wav_path)
    t0 = time.perf_counter()
    rec.start()
    time.sleep(0.30)                 # lead-in: que el stream esté abierto
    audio_io.play_blocking(audio)    # bloquea hasta terminar de reproducir
    time.sleep(0.45)                 # tail: capturar la última sílaba
    captured = rec.stop()
    return captured, time.perf_counter() - t0


def run(models, use_cable, language, perf_profile, rate):
    results = {
        "meta": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "language": language,
            "perf_profile": perf_profile,
            "tts_rate": rate,
            "path": "cable" if use_cable else "direct",
            "cuda_available": cuda_available(),
        },
        "models": {},
    }

    # Reemplazos: pipeline real (tech_mode off, como el default).
    reps = Replacements(on_log=_silent, tech_mode_getter=lambda: False)
    prompt = config.DEFAULT_INITIAL_PROMPT  # el default que trae la app

    # Resolución de device/compute según el perfil de rendimiento elegido.
    pp = config.PERF_PROFILES.get(perf_profile, config.PERF_PROFILES[config.PERF_PROFILE_QUALITY])

    cable_out = cable_in = None
    if use_cable:
        cable_out, cable_in = audio_io.find_cable()
        if cable_out is None or cable_in is None:
            print("[bench] ⚠ No encontré el cable VB-Audio; cambiando a modo --direct.")
            use_cable = False

    guard = None
    try:
        if use_cable:
            guard = audio_io.DefaultDeviceGuard(
                input_idx=cable_out, output_idx=cable_in, log=print
            )
            guard.__enter__()

        for model_name in models:
            print(f"\n===== MODELO: {model_name} ({pp['device']}/{pp['compute_type']}) =====")
            tr = Transcriber(on_log=_silent)
            t_load0 = time.perf_counter()
            tr.load(
                model_name,
                device=pp["device"],
                compute_type=pp["compute_type"],
                cpu_threads=config.DEFAULT_CPU_THREADS,
                num_workers=config.DEFAULT_NUM_WORKERS,
                enable_gpu=config.DEFAULT_ENABLE_GPU_IF_AVAILABLE,
            )
            load_s = time.perf_counter() - t_load0
            backend = tr.backend_str
            print(f"[bench] backend={backend} · carga={load_s:.1f}s")

            rec = AudioRecorder(on_log=_silent) if use_cable else None
            cases_out = []

            for c in corpus.CASES:
                wav = audio_io.synth_to_wav(c["spoken"], voice=c["voice"], rate=rate)
                audio_s = audio_io.wav_duration_seconds(wav)

                if use_cable:
                    audio, record_s = _record_via_cable(rec, wav)
                    if audio is None or len(audio) == 0:
                        print(f"  [{c['id']}] ⚠ captura vacía (revisa el cable)")
                        audio = audio_io.read_wav_f32(wav)
                        record_s = audio_s
                else:
                    audio = audio_io.read_wav_f32(wav)
                    record_s = audio_s

                lang = None if language == "auto" else language
                text = tr.transcribe(
                    audio,
                    language=lang,
                    beam_size=config.DEFAULT_BEAM_SIZE,
                    best_of=config.DEFAULT_BEST_OF,
                    temperature=config.DEFAULT_TEMPERATURE,
                    vad_filter=config.DEFAULT_VAD_FILTER,
                    condition_on_previous_text=config.DEFAULT_CONDITION_ON_PREVIOUS_TEXT,
                    initial_prompt=prompt,
                    audio_duration=audio_s,
                    mixed_language_mode=config.DEFAULT_MIXED_LANGUAGE_MODE,
                    batched=pp["batched"],
                    batch_size=pp["batch_size"],
                )
                transcribe_s = float(tr.last_transcribe_seconds)

                t_r0 = time.perf_counter()
                final_text, _applied = reps.apply(text)
                replace_s = time.perf_counter() - t_r0

                sc = corpus.score_case(c, final_text)
                rt = (transcribe_s / audio_s) if audio_s > 0 else 0.0

                row = {
                    "id": c["id"],
                    "category": c["category"],
                    "audio_s": round(audio_s, 2),
                    "record_s": round(record_s, 2),
                    "transcribe_s": round(transcribe_s, 2),
                    "rt_ratio": round(rt, 2),
                    "replace_s": round(replace_s, 4),
                    "wer": round(sc["wer"], 3),
                    "accuracy": round(sc["accuracy_words"], 3),
                    "key_hits": sc["key_hits"],
                    "key_total": sc["key_total"],
                    "expected": c["expected"],
                    "got": final_text,
                    "raw": text,
                }
                cases_out.append(row)
                print(f"  [{c['id']:<11}] audio={audio_s:4.1f}s "
                      f"transcribe={transcribe_s:5.2f}s rt={rt:4.2f}x "
                      f"wer={sc['wer']:.2f} keys={sc['key_hits']}/{sc['key_total']}")
                print(f"      got: {final_text!r}")

            # Agregados del modelo.
            n = len(cases_out)
            avg = lambda k: round(sum(r[k] for r in cases_out) / n, 3) if n else 0.0
            tot_keys = sum(r["key_hits"] for r in cases_out)
            tot_keyt = sum(r["key_total"] for r in cases_out)
            results["models"][model_name] = {
                "backend": backend,
                "load_s": round(load_s, 1),
                "avg_audio_s": avg("audio_s"),
                "avg_transcribe_s": avg("transcribe_s"),
                "avg_rt_ratio": avg("rt_ratio"),
                "avg_wer": avg("wer"),
                "avg_accuracy": avg("accuracy"),
                "key_hits": tot_keys,
                "key_total": tot_keyt,
                "key_rate": round(tot_keys / tot_keyt, 3) if tot_keyt else 0.0,
                "cases": cases_out,
            }
    finally:
        if guard is not None:
            guard.__exit__(None, None, None)

    return results


def write_reports(results):
    json_path = os.path.join(_HERE, "report_transcription.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    md = []
    m = results["meta"]
    md.append("# Reporte de transcripción — Wisip\n")
    md.append(f"- Fecha: {m['timestamp']}")
    md.append(f"- Ruta de audio: **{m['path']}**  ·  idioma: `{m['language']}`  "
              f"·  perfil: `{m['perf_profile']}`  ·  TTS rate: {m['tts_rate']}")
    md.append(f"- CUDA disponible: **{m['cuda_available']}**\n")

    md.append("## Resumen por modelo\n")
    md.append("| Modelo | Backend | Carga | Transcribe prom | RT ratio | Precisión palabras | Términos clave |")
    md.append("|---|---|---|---|---|---|---|")
    for name, d in results["models"].items():
        md.append(
            f"| {name} | {d['backend']} | {d['load_s']}s | "
            f"{d['avg_transcribe_s']}s | {d['avg_rt_ratio']}x | "
            f"{d['avg_accuracy']*100:.0f}% | {d['key_hits']}/{d['key_total']} "
            f"({d['key_rate']*100:.0f}%) |"
        )
    md.append("")

    for name, d in results["models"].items():
        md.append(f"## Detalle — {name}\n")
        md.append("| Caso | Cat | audio | transcribe | rt | wer | keys | got |")
        md.append("|---|---|---|---|---|---|---|---|")
        for r in d["cases"]:
            got = r["got"].replace("|", "\\|")
            if len(got) > 70:
                got = got[:67] + "…"
            md.append(
                f"| {r['id']} | {r['category']} | {r['audio_s']}s | "
                f"{r['transcribe_s']}s | {r['rt_ratio']}x | {r['wer']} | "
                f"{r['key_hits']}/{r['key_total']} | {got} |"
            )
        md.append("")

    md_path = os.path.join(_HERE, "report_transcription.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"\n[bench] Reportes escritos:\n  {md_path}\n  {json_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="base,small",
                    help="lista separada por comas (tiny,base,small,medium)")
    ap.add_argument("--direct", action="store_true",
                    help="no usar el cable; alimentar el WAV directo al modelo")
    ap.add_argument("--language", default="es",
                    help="es | en | auto  (def: es, el default de la app)")
    ap.add_argument("--perf", default=config.PERF_PROFILE_QUALITY,
                    help="perfil de rendimiento (quality_current|fast_safe|max_speed)")
    ap.add_argument("--rate", type=int, default=0, help="velocidad TTS (-10..10)")
    args = ap.parse_args()

    models = [s.strip() for s in args.models.split(",") if s.strip()]
    results = run(
        models=models,
        use_cable=not args.direct,
        language=args.language,
        perf_profile=args.perf,
        rate=args.rate,
    )
    write_reports(results)


if __name__ == "__main__":
    main()
