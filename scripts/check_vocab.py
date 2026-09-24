# -*- coding: utf-8 -*-
"""Valida app/vocab.py (pestaña Vocabulario) SIN cargar el modelo ni la UI:

  - Medidor de tokens: exacto con el tokenizer de la caché HF, estimación si no.
  - CRUD de reemplazos personales contra un JSON temporal (NO toca %APPDATA%).
  - Minería de sugerencias contra un registro JSONL sintético: detecta garbles
    recurrentes, y NO marca español corriente, tecnicismos ya resueltos,
    hotwords ni palabras ignoradas.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_vocab.py
"""

import json
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import vocab  # noqa: E402

FALLOS = []


def check(nombre, ok, detalle=""):
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}" + (f"  ({detalle})" if detalle and not ok else ""))
    if not ok:
        FALLOS.append(nombre)


print("── Medidor de tokens ──")
label, over = vocab.budget_label("hola mundo", "proxy, MEmu", "large-v3-turbo")
check("devuelve etiqueta con presupuesto", label.endswith("tokens (prompt + hotwords)"), label)
check("prompt corto no se pasa del presupuesto", over is False)
n, exact = vocab.count_prompt_tokens("palabra " * 400, "", "large-v3-turbo")
check("prompt gigante supera el presupuesto", n > vocab.PROMPT_TOKEN_BUDGET, str(n))
n_est, exact_est = vocab.count_prompt_tokens("hola", "x", "modelo-inexistente-zz")
check("estimación devuelve entero positivo", isinstance(n_est, int) and n_est > 0)

print("── CRUD de reemplazos personales ──")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "personal.json"
    check("agregar entrada válida", vocab.personal_add("herzner", "Hetzner", p) is None)
    check("agregar segunda entrada", vocab.personal_add("  GoBlogin ", "GoLogin", p) is None)
    pares = vocab.personal_list(p)
    check("lista ordenada con 2 entradas", pares == [("goblogin", "GoLogin"), ("herzner", "Hetzner")], repr(pares))
    check("rechaza entrada vacía", vocab.personal_add("", "x", p) is not None)
    check("rechaza igual a su corrección", vocab.personal_add("Kimi", "kimi", p) is not None)
    check("rechaza clave de 1 letra", vocab.personal_add("a", "b", p) is not None)
    check("eliminar existente", vocab.personal_remove("herzner", p) is True)
    check("eliminar inexistente devuelve False", vocab.personal_remove("nada", p) is False)
    check("queda 1 entrada", len(vocab.personal_list(p)) == 1)

print("── Ignorados ──")
with tempfile.TemporaryDirectory() as td:
    ip = Path(td) / "ignore.json"
    vocab.ignore_word("Randomizar", ip)
    vocab.ignore_word("scrollear", ip)
    check("ignorados en minúscula y persistidos", vocab.load_ignored(ip) == {"randomizar", "scrollear"})

print("── Minería de sugerencias ──")
with tempfile.TemporaryDirectory() as td:
    logs = Path(td)
    ip = Path(td) / "ignore.json"
    import datetime

    hoy = datetime.date.today()
    frases = (
        # garble recurrente (3x) → DEBE salir
        ["quiero montar el servidor en zorbex hoy",
         "el zorbex está lento",
         "revisa el zorbex de nuevo"]
        # garble 2x → por debajo de min_count, NO sale
        + ["abre el flumio", "cierra el flumio"]
        # español corriente + conjugaciones (wordfreq las conoce) → NO salen
        + ["necesito que la aplicación funcione bien y podríamos mejorarla mañana"] * 3
        # palabra ignorada → NO sale
        + ["vamos a pumpear la moneda"] * 3
    )
    with (logs / f"dictados-{hoy:%Y-%m}.jsonl").open("w", encoding="utf-8") as f:
        for i, t in enumerate(frases):
            f.write(json.dumps({"ts": f"{hoy}T10:00:{i:02d}", "final": t}) + "\n")
    vocab.ignore_word("pumpear", ip)
    sug = vocab.suggest_from_logs(
        days=7, logs_dir=logs, ignore_path=ip, hotwords="proxy, MEmu"
    )
    palabras = {s["word"] for s in sug}
    check("detecta el garble recurrente 'zorbex'", "zorbex" in palabras, repr(palabras))
    check("respeta min_count (flumio 2x no sale)", "flumio" not in palabras)
    check("no marca español corriente", not palabras & {"necesito", "aplicación", "funcione", "podríamos", "mejorarla", "mañana", "quiero", "montar", "servidor", "lento", "revisa"}, repr(palabras))
    check("respeta ignorados", "pumpear" not in palabras)
    z = next(s for s in sug if s["word"] == "zorbex")
    check("cuenta bien las repeticiones", z["count"] == 3, str(z["count"]))
    check("trae contexto", "zorbex" in z["context"])
    # hotwords no salen aunque se repitan
    with (logs / f"dictados-{hoy:%Y-%m}.jsonl").open("a", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({"ts": f"{hoy}T11:00:{i:02d}", "final": "configura el memu"}) + "\n")
    sug2 = vocab.suggest_from_logs(days=7, logs_dir=logs, ignore_path=ip, hotwords="proxy, MEmu")
    check("respeta hotwords (memu no sale)", "memu" not in {s["word"] for s in sug2})

print()
if FALLOS:
    print(f"✗ {len(FALLOS)} checks FALLARON: {FALLOS}")
    sys.exit(1)
print("✓ Todos los checks de vocab pasaron.")
