# -*- coding: utf-8 -*-
"""
Corpus de pruebas de transcripción para Wisip.

Cada caso tiene:
  id        : identificador corto y estable.
  category  : familia (es / en / mixto / email / url / tech / numeros / largo).
  voice     : "es" o "en" → qué voz SAPI usa el TTS para "hablar" el caso.
  spoken    : EXACTAMENTE lo que el TTS pronuncia (como lo diría un humano:
              "arroba", "punto", "slash", etc.).
  expected  : resultado ideal DESPUÉS del pipeline de reemplazos (lo que el
              usuario debería ver pegado). Sirve para WER.
  key_terms : tokens cuya presencia literal (case-insensitive) es lo que de
              verdad importa (correos, URLs, nombres de librerías). Se puntúan
              por acierto exacto, no por palabra.

NOTA sobre el TTS: la voz "Helena" (es-ES) lee los términos en inglés con
fonética española. Eso es un proxy razonable de cómo un hispanohablante dicta
"webhook" o "dashboard", pero es MÁS difícil que el dictado real de una persona
nativa. Por eso los aciertos de términos técnicos vía TTS son un piso, no un
techo: en boca de un humano el modelo suele acertar más.
"""

CASES = [
    # ── Español natural ─────────────────────────────────────────────
    {
        "id": "es_corto_1",
        "category": "es",
        "voice": "es",
        "spoken": "Hola, esta es una prueba de dictado por voz para verificar "
                  "la precisión del sistema.",
        "expected": "Hola, esta es una prueba de dictado por voz para verificar "
                    "la precisión del sistema.",
        "key_terms": [],
    },
    {
        "id": "es_corto_2",
        "category": "es",
        "voice": "es",
        "spoken": "Necesito que la aplicación capture todo lo que digo sin "
                  "cortar las frases ni perder palabras importantes.",
        "expected": "Necesito que la aplicación capture todo lo que digo sin "
                    "cortar las frases ni perder palabras importantes.",
        "key_terms": [],
    },
    # ── Inglés natural ──────────────────────────────────────────────
    {
        "id": "en_corto_1",
        "category": "en",
        "voice": "en",
        "spoken": "I need to create a new endpoint for the user dashboard "
                  "before the next release.",
        "expected": "I need to create a new endpoint for the user dashboard "
                    "before the next release.",
        "key_terms": ["endpoint", "dashboard"],
    },
    # ── Mixto español + términos técnicos en inglés ─────────────────
    {
        "id": "mixto_1",
        "category": "mixto",
        "voice": "es",
        "spoken": "Necesito crear un webhook en n8n que reciba el evento y lo "
                  "guarde en MongoDB.",
        "expected": "Necesito crear un webhook en n8n que reciba el evento y lo "
                    "guarde en MongoDB.",
        "key_terms": ["webhook", "n8n", "MongoDB"],
    },
    {
        "id": "mixto_2",
        "category": "mixto",
        "voice": "es",
        "spoken": "Quiero que el backend valide el login y mantenga la sesión "
                  "abierta usando un token.",
        "expected": "Quiero que el backend valide el login y mantenga la sesión "
                    "abierta usando un token.",
        "key_terms": ["backend", "login", "sesión"],
    },
    # ── Términos técnicos / librerías ───────────────────────────────
    {
        "id": "tech_1",
        "category": "tech",
        "voice": "es",
        "spoken": "Estoy usando Python, JavaScript, TypeScript, React y Node.js "
                  "junto con Docker.",
        "expected": "Estoy usando Python, JavaScript, TypeScript, React y Node.js "
                    "junto con Docker.",
        "key_terms": ["Python", "JavaScript", "TypeScript", "React",
                      "Node.js", "Docker"],
    },
    # ── Correos ─────────────────────────────────────────────────────
    {
        "id": "email_1",
        "category": "email",
        "voice": "es",
        "spoken": "Mi correo es juanperez arroba hotmail punto com.",
        "expected": "Mi correo es juanperez@hotmail.com.",
        "key_terms": ["juanperez@hotmail.com"],
    },
    {
        "id": "email_2",
        "category": "email",
        "voice": "es",
        "spoken": "Escríbeme a soporte arroba wisip punto ai.",
        "expected": "Escríbeme a soporte@wisip.ai.",
        "key_terms": ["soporte@wisip.ai"],
    },
    # ── URLs / rutas ────────────────────────────────────────────────
    {
        "id": "url_1",
        "category": "url",
        "voice": "es",
        "spoken": "Visita wisip punto ai slash dashboard.",
        "expected": "Visita wisip.ai/dashboard.",
        "key_terms": ["wisip.ai/dashboard"],
    },
    {
        "id": "url_2",
        "category": "url",
        "voice": "es",
        "spoken": "La API está en api punto wisip punto co slash v1 slash users.",
        "expected": "La API está en api.wisip.co/v1/users.",
        "key_terms": ["api.wisip.co/v1/users"],
    },
    # ── Números (puertos) ───────────────────────────────────────────
    {
        "id": "num_1",
        "category": "numeros",
        "voice": "es",
        "spoken": "El servidor corre en el puerto tres mil y la base de datos "
                  "en el cinco mil.",
        "expected": "El servidor corre en el puerto 3000 y la base de datos "
                    "en el 5000.",
        "key_terms": ["3000", "5000"],
    },
    # ── Frase larga (para medir RT ratio en audio largo) ────────────
    {
        "id": "largo_1",
        "category": "largo",
        "voice": "es",
        "spoken": (
            "Esta es una prueba completa de transcripción para Wisip. Voy a "
            "hablar de corrido para medir cuánto tarda el sistema con un audio "
            "largo. Necesito crear un webhook para Shopify que reciba una orden "
            "nueva, guarde la información en MongoDB, llame a una API externa, "
            "actualice el dashboard del restaurante y luego envíe un mensaje "
            "por WhatsApp. Después quiero que n8n procese el evento, valide los "
            "datos, cree un JSON limpio y lo mande al backend de mi SaaS sin "
            "romper el login ni la sesión actual."
        ),
        "expected": (
            "Esta es una prueba completa de transcripción para Wisip. Voy a "
            "hablar de corrido para medir cuánto tarda el sistema con un audio "
            "largo. Necesito crear un webhook para Shopify que reciba una orden "
            "nueva, guarde la información en MongoDB, llame a una API externa, "
            "actualice el dashboard del restaurante y luego envíe un mensaje "
            "por WhatsApp. Después quiero que n8n procese el evento, valide los "
            "datos, cree un JSON limpio y lo mande al backend de mi SaaS sin "
            "romper el login ni la sesión actual."
        ),
        "key_terms": ["webhook", "Shopify", "MongoDB", "API", "dashboard",
                      "WhatsApp", "n8n", "JSON", "backend", "SaaS"],
    },
]


# ─── Scoring ────────────────────────────────────────────────────────────

import re
import unicodedata


def _norm_words(s: str) -> list:
    """Tokeniza para WER: minúsculas, sin tildes, sin puntuación de borde.
    Mantiene @ . / _ - internos (para no destrozar correos/URLs)."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # quita tildes
    toks = re.findall(r"[a-z0-9@._/\-]+", s)
    # Limpia puntuación de borde que quedó pegada.
    out = []
    for t in toks:
        t = t.strip("._-")
        if t:
            out.append(t)
    return out


def _levenshtein(a: list, b: list) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def word_error_rate(expected: str, got: str) -> float:
    """WER = ediciones / palabras_esperadas. 0.0 = perfecto."""
    exp = _norm_words(expected)
    hyp = _norm_words(got)
    if not exp:
        return 0.0 if not hyp else 1.0
    return _levenshtein(exp, hyp) / len(exp)


def key_term_hits(key_terms: list, got: str) -> tuple:
    """Devuelve (aciertos, total) de términos clave presentes literalmente
    (case-insensitive) en el texto transcrito."""
    if not key_terms:
        return (0, 0)
    low = got.lower()
    hits = sum(1 for t in key_terms if t.lower() in low)
    return (hits, len(key_terms))


def score_case(case: dict, got: str) -> dict:
    wer = word_error_rate(case["expected"], got)
    hits, total = key_term_hits(case.get("key_terms", []), got)
    return {
        "wer": wer,
        "accuracy_words": max(0.0, 1.0 - wer),
        "key_hits": hits,
        "key_total": total,
    }
