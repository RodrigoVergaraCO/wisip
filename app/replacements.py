import json
import re
import threading

from . import config


# Diccionario base por CATEGORÍAS. Todas se aplican siempre, case-insensitive,
# con límites de palabra y "más-largo-primero" (orden en `_apply_dict`).
#
# OJO con los reemplazos peligrosos ("punto", "coma", "guion", "dos puntos", ...):
# NO van aquí. Esos se manejan vía el pre-procesador `_apply_url_email_patterns`
# (solo dentro de URL/email/path) o vía `tech_mode` (agresivo, opt-in).
#
# Las categorías son organizativas; al final se fusionan en DEFAULT_REPLACEMENTS
# (plano) para mantener compatibilidad con el replacements.json existente.

# 1) url_email_symbols — símbolos inambiguos (nadie dice "slash" en ES normal).
# OJO: las palabras que TAMBIÉN son español corriente ("igual", "porcentaje",
# "diagonal", "dólar", "menor/mayor que") NO van aquí: el registro real mostró
# que el 100% de sus aplicaciones rompían habla normal ("igual que estamos
# haciendo" → "= que...", "punto diagonal derecho" → "punto/derecho"). Viven en
# TECH_MODE_REPLACEMENTS (opt-in) y _load() las retira del JSON ya sembrado.
URL_EMAIL_SYMBOLS = {
    "slash": "/",
    "barra slash": "/",
    "barra inclinada": "/",
    "backslash": "\\",
    "barra invertida": "\\",
    "arroba": "@",
    "underscore": "_",
    "guion bajo": "_",
    "guión bajo": "_",
    "pipe": "|",
    "pleca": "|",
    "ampersand": "&",
    "and symbol": "&",
    "hash": "#",
    "numeral": "#",
    "hashtag": "#",
    "asterisco": "*",
    "signo pesos": "$",
    "signo de pesos": "$",
    "signo de pregunta": "?",
    "abrir paréntesis": "(",
    "abrir parentesis": "(",
    "cerrar paréntesis": ")",
    "cerrar parentesis": ")",
    "abrir corchete": "[",
    "cerrar corchete": "]",
    "abrir llave": "{",
    "cerrar llave": "}",
}

# 2) tech_terms — términos y librerías técnicas + formas mal oídas frecuentes.
# NOTA: NO incluimos "whisper"→"Whisper" genérico a propósito: rompería
# "faster-whisper" (el \b tras el guion haría match). El mishear "wisper" sí.
TECH_TERMS = {
    "chat gpt": "ChatGPT",
    "chat yipiti": "ChatGPT",
    "chatgpt": "ChatGPT",
    "gipi ti": "GPT",
    "gpt": "GPT",
    "claud": "Claude",
    "claude": "Claude",
    "yason": "JSON",
    "jason": "JSON",
    "json": "JSON",
    "java script": "JavaScript",
    "javascript": "JavaScript",
    "type script": "TypeScript",
    "typescript": "TypeScript",
    "react": "React",
    "next js": "Next.js",
    "nextjs": "Next.js",
    "node js": "Node.js",
    "nodejs": "Node.js",
    "mongo db": "MongoDB",
    "mongodb": "MongoDB",
    "mongo de ve": "MongoDB",
    "api": "API",
    "a p i": "API",
    "web hook": "webhook",
    "webhook": "webhook",
    "n eight n": "n8n",
    "n 8 n": "n8n",
    "n ocho n": "n8n",
    "ene ocho ene": "n8n",
    "coolify": "Coolify",
    "docker": "Docker",
    "wasender": "Wasender",
    "whatsender": "Wasender",
    "whatsapp": "WhatsApp",
    "wasap": "WhatsApp",
    "guasa": "WhatsApp",
    "shopify": "Shopify",
    "rappi": "Rappi",
    "linkedin": "LinkedIn",
    "linked in": "LinkedIn",
    # Photoshop: Whisper oye "PCD" cuando se dicta "PSD" (registro 2026-07-21).
    "pcd": "PSD",
    "psd": "PSD",
    # "archivo PSD" dictado sale como "archivo PC" (registro 2026-07-24,
    # confirmado por el usuario). SOLO junto a "archivo": "PC" suelto es habla
    # normal y no se toca.
    "archivo pc": "archivo PSD",
    # Cripto/trading (registro 2026-08-03, confirmado por el usuario). Whisper
    # inventa una grafía distinta casi cada vez; "memecoins" es la canónica.
    "mimcoins": "memecoins",
    "mincoins": "memecoins",
    "memetoins": "memecoins",
    "meme toins": "memecoins",
    "memecoins": "memecoins",
    "pnln": "PNL",
    "pnl": "PNL",
    "rookpool": "rug pull",
    "leaders boards": "leaderboards",
    "leader boards": "leaderboards",
    # "UI UX" dictado sale como "Wii UX" (registro 2026-08-03).
    "wii ux": "UI UX",
    # "API key" dictada rápida se fusiona en "APIK" (registro 2026-07-24).
    "apik": "API key",
    "saas": "SaaS",
    "vps": "VPS",
    # Librerías Python (formas mal oídas en la prueba real).
    "fast raja whisper": "faster-whisper",
    "faster whisper": "faster-whisper",
    "fast whisper": "faster-whisper",
    "custom ticking ringer": "CustomTkinter",
    "custom tkinter": "CustomTkinter",
    "customtkinter": "CustomTkinter",
    "pi outlook guy": "pyautogui",
    "pie auto gui": "pyautogui",
    "py auto gui": "pyautogui",
    "pyautogui": "pyautogui",
    "piper clip": "pyperclip",
    "piperclip": "pyperclip",
    "pyperclip": "pyperclip",
    "sound device": "sounddevice",
    "sounddevice": "sounddevice",
    "hotcake": "hotkey",
    "hot cake": "hotkey",
    "hotkey": "hotkey",
    "wisip": "Wisip",
    "wisper": "Whisper",
    # Más formas mal oídas (prueba real 2).
    "custom thinker": "CustomTkinter",
    "custom thinking": "CustomTkinter",
    "note.js": "Node.js",
    "node.js": "Node.js",
    "next.js": "Next.js",
    "react next.js": "React, Next.js",
    # Navegadores, marcas y herramientas de infraestructura (registro
    # 2026-08-23): Whisper las escribe en minúscula. Las grafías inventadas
    # ("herzner", "goblogin", "anidesc"...) son propias de cada acento y viven
    # en personal_replacements.json, no aquí.
    "firefox": "Firefox",
    "mozilla": "Mozilla",
    "chrome": "Chrome",
    "google": "Google",
    "telegram": "Telegram",
    "iphone": "iPhone",
    "samsung": "Samsung",
    "kindle": "Kindle",
    "hetzner": "Hetzner",
    "gologin": "GoLogin",
    "go login": "GoLogin",
    "anydesk": "AnyDesk",
    "any desk": "AnyDesk",
    "proxifier": "Proxifier",
    "iproyal": "IPRoyal",
    "ip royal": "IPRoyal",
    # MEmu (emulador Android) y su gestor multi-instancia Multi-MEmu.
    "memu": "MEmu",
    "multi-memu": "Multi-MEmu",
    "multi memu": "Multi-MEmu",
    # Registro 2026-09-23 (2.854 dictados): marcas que Whisper escribe en
    # minúscula o deforma. "amazon" salió 36x en minúscula; "gmail" 40x (los
    # correos van enmascarados antes de este diccionario, no se tocan).
    "amazon": "Amazon",
    "gmail": "Gmail",
    "youtube": "YouTube",
    "you tube": "YouTube",
    "github": "GitHub",
    "git hub": "GitHub",
    "alexa": "Alexa",
    "bluestacks": "BlueStacks",
    "bluestack": "BlueStacks",
    "blue stacks": "BlueStacks",
    "play protect": "Play Protect",
    "playprotect": "Play Protect",
    "play store": "Play Store",
    "google play": "Google Play",
    "magisk": "Magisk",
    "pexels": "Pexels",
    "valorant": "Valorant",
    "elevenlabs": "ElevenLabs",
    "eleven labs": "ElevenLabs",
    "anthropic": "Anthropic",
    "antropic": "Anthropic",
    "antropik": "Anthropic",
    "antropix": "Anthropic",
    # "API key" dictada de corrido sale pegada (2026-09).
    "apikey": "API key",
    "workhook": "webhook",
}

# 3) personal_terms — correcciones de MARCA y de proveedores mal oídos.
# Viven en personal_replacements.json (separados de los generales) y se aplican
# en una pre-pasada ANTES del parser de email/URL. NO incluyen arroba/punto/slash.
#
# IMPORTANTE: aquí NO van nombres propios ni correos personales (PII). La app es
# pública. Cada usuario añade sus propios nombres en su personal_replacements.json
# local, y sus alias de correo en personal_emails.json (ver app/postprocessor.py).
DEFAULT_PERSONAL_REPLACEMENTS = {
    "jodmail": "hotmail",
    "hot mail": "hotmail",
    "wism": "Wisip",
    "wisin": "Wisip",
    "wisp": "Wisip",
    # Dropi (plataforma de dropshipping): Whisper la oye "Dropip" a veces
    # (registro 2026-07-21) y sin mayúscula.
    "dropip": "Dropi",
    "dropi": "Dropi",
    # Kimi (modelo de IA): Whisper lo oye "Kimmy" (registro 2026-07-24). Va en
    # personales porque "Kimmy" es nombre real de persona para otros usuarios.
    "kimmy": "Kimi",
    "kimi": "Kimi",
    # ScreenViewer: Whisper duplica la sílaba (registro 2026-07-23).
    "screenenviewer": "ScreenViewer",
    # "API key" dictada sale a veces como "AppKey" (registro 2026-07-24).
    "appkey": "API key",
}

# 4) safe_general — correcciones de español inambiguas (no son palabras reales).
SAFE_GENERAL = {
    "resaurante": "restaurante",
    # Grafía inventada por Whisper (registro 2026-08-03).
    "aleatoriezar": "aleatorizar",
    # Garbles inambiguos del registro 2026-08 (ninguno es palabra real en ES).
    "autenticización": "autenticación",
    "aprimir": "oprimir",
    "confírame": "confírmame",
    "clenar": "clonar",
    "remulario": "formulario",
    "encimiento": "vencimiento",
    "upago": "pago",
    "portfiles": "perfiles",
    "gamazon": "Amazon",
    # Garbles inambiguos del registro 2026-09 (ninguno es palabra real en ES).
    "premir": "oprimir",
    "aprimamos": "oprimamos",
    "chitosamente": "exitosamente",
    "appelar": "apelar",
    "badeja": "bandeja",
    # Números frecuentes en puertos (extender en JSON si hace falta).
    "tres mil": "3000",
    "cinco mil": "5000",
    "ocho mil": "8000",
    "nueve mil": "9000",
}

# Fusión plana de las generales (compatibilidad con replacements.json existente).
# Los nombres propios viven aparte en personal_replacements.json.
DEFAULT_REPLACEMENTS = {
    **URL_EMAIL_SYMBOLS,
    **TECH_TERMS,
    **SAFE_GENERAL,
}

# Reemplazos extra del "modo técnico" (opt-in vía tech_mode=true en settings).
# Aquí van los peligrosos: rompen dictado natural, solo úsalos si dictas
# comandos/código/markdown todo el día.
TECH_MODE_REPLACEMENTS = {
    "punto": ".",
    "dot": ".",
    "coma": ",",
    "punto y coma": ";",
    "dos puntos": ":",
    "guion": "-",
    "guión": "-",
    "más": "+",
    "menos": "-",
    "espacio": " ",
    "sin espacio": "",
    # Movidas desde URL_EMAIL_SYMBOLS (2026-08-03): son español corriente y en
    # el registro real rompían habla normal el 100% de las veces.
    "igual": "=",
    "porcentaje": "%",
    "diagonal": "/",
    "dólar": "$",
    "dolar": "$",
    "menor que": "<",
    "mayor que": ">",
}

# Migración 2026-08-03: retira del replacements.json ya sembrado las entradas
# que se movieron a TECH_MODE_REPLACEMENTS. Solo si el usuario no las
# personalizó (valor == default viejo); una personalización se respeta.
_MOVED_TO_TECH_MODE = {
    "igual": "=",
    "porcentaje": "%",
    "diagonal": "/",
    "dólar": "$",
    "dolar": "$",
    "menor que": "<",
    "mayor que": ">",
}

# TLDs reconocidos para el pre-procesador (la lista define cuándo "punto X"
# se trata como dominio). Mantener corta y específica.
KNOWN_TLDS = {
    "com", "ai", "ia", "co", "net", "org", "io", "dev", "app",
    "cloud", "tech", "py", "js", "sh", "mx", "es", "pe", "ar", "us", "uk",
}

# TLDs usados SOLO para enmascarar tokens URL/email frente al diccionario.
# Excluimos js/ts/py/sh porque colisionan con nombres de librerías/archivos
# (Node.js, Next.js) que SÍ queremos que el diccionario corrija.
MASK_TLDS = KNOWN_TLDS - {"js", "ts", "py", "sh"}

# ─── VAD contextual ─────────────────────────────────────────────────────
#
# Whisper oye "VAD" como "bad". NO podemos reemplazar "bad"→"VAD" globalmente
# (rompería inglés mezclado: "the button is bad"). Solo lo hacemos cuando hay
# una palabra de contexto técnico cerca (ventana de ±N tokens). Las formas
# deletreadas ("v a d") y "vad" suelto sí son seguras siempre (no son palabras).
_VAD_CONTEXT_WORDS = {
    "modelo", "modelos", "micrófono", "microfono", "whisper", "wisper",
    "segmento", "segmentos", "initial", "prompt", "reemplazo", "reemplazos",
    "transcripción", "transcripcion", "idioma", "audio", "filtro",
}
_VAD_WINDOW = 4  # tokens a cada lado para considerar "contexto técnico"
_VAD_SPELLED = re.compile(r"\b(?:v\s+a\s+d|b\s+a\s+d|vad)\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")


def _apply_contextual_vad(text: str, log_lines: list) -> str:
    """Convierte 'bad'/'vad'/'v a d'/'b a d' → 'VAD'.

    - 'vad', 'v a d', 'b a d' → siempre (no son palabras reales).
    - 'bad' → solo si hay una palabra de contexto técnico dentro de ±4 tokens
      (evita romper inglés/español normal).
    """
    out = text

    # 1) Formas seguras (deletreadas o 'vad' suelto): siempre.
    def _spelled_sub(m):
        log_lines.append(f"vad: {m.group(0)!r} → 'VAD'")
        return "VAD"

    out = _VAD_SPELLED.sub(_spelled_sub, out)

    # 2) 'bad' suelto: solo en contexto técnico.
    if not re.search(r"\bbad\b", out, re.IGNORECASE):
        return out

    tokens = list(_TOKEN_RE.finditer(out))
    lowered = [t.group(0).lower() for t in tokens]
    # Índices de tokens que son exactamente 'bad'.
    replace_spans = []
    for i, tok in enumerate(lowered):
        if tok != "bad":
            continue
        lo = max(0, i - _VAD_WINDOW)
        hi = min(len(lowered), i + _VAD_WINDOW + 1)
        window = lowered[lo:i] + lowered[i + 1:hi]
        if any(w in _VAD_CONTEXT_WORDS for w in window):
            replace_spans.append(tokens[i].span())

    if not replace_spans:
        return out

    # Reemplaza de derecha a izquierda para no descuadrar offsets.
    for start, end in sorted(replace_spans, reverse=True):
        log_lines.append(f"vad(contexto): {out[start:end]!r} → 'VAD'")
        out = out[:start] + "VAD" + out[end:]
    return out


def _re_word(s: str) -> str:
    """Escapa y permite múltiples espacios entre palabras del key."""
    parts = [re.escape(p) for p in s.split()]
    return r"\s+".join(parts)


# ─── Pre-procesador contextual ──────────────────────────────────────────
#
# Detecta URL/email/path y los reescribe ANTES del diccionario plano. Esto
# permite que "punto", "arroba", "slash" se conviertan en . @ / SOLO cuando
# están en un contexto que claramente es URL/email/ruta — sin romper la frase
# "voy al punto importante".

# Token "palabra" para los componentes (letras/dígitos/guion).
_WORD = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9-]+"

# "punto <TLD-conocido>" — un dominio o sufijo de dominio.
_PUNTO_TLD = re.compile(
    r"\bpunto\s+(" + "|".join(sorted(KNOWN_TLDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Cadena de dominios: <word>(\s+punto\s+<word>)+ donde el ÚLTIMO o algún
# segmento es TLD conocido (lo validamos en código para no falso-positivar).
_DOTTED_CHAIN = re.compile(
    r"\b(" + _WORD + r")((?:\s+punto\s+" + _WORD + r")+)\b",
    re.IGNORECASE,
)

# Email: <word> arroba <chain con TLD>
_EMAIL_PATTERN = re.compile(
    r"\b(" + _WORD + r")\s+arroba\s+(" + _WORD + r")((?:\s+punto\s+" + _WORD + r")+)\b",
    re.IGNORECASE,
)

# www / w w w al inicio del dominio.
_WWW_PREFIX = re.compile(
    r"\b(?:w\s+w\s+w|www|doble\s+u\s+doble\s+u\s+doble\s+u)(?=\s+punto\s+)",
    re.IGNORECASE,
)

# "slash <word>" tras un dominio o palabra que parece URL.
_SLASH_PATH = re.compile(
    r"(?<=[A-Za-z0-9])(?:\s+slash\s+(" + _WORD + r"))",
    re.IGNORECASE,
)

# Identifica tokens YA reconstruidos (email/dominio.tld[/path]) para protegerlos
# del diccionario (si no, "wisip.ai" se volvería "Wisip.ai" y "api.wisip.co" →
# "API.Wisip.co"). Usa MASK_TLDS (sin js/ts/py/sh) para NO proteger Node.js/Next.js,
# que sí queremos que el diccionario corrija.
_URLISH = re.compile(
    r"(?:[A-Za-z0-9._%+\-]+@)?"                       # user@ opcional (email)
    r"(?:[A-Za-z0-9\-]+\.)+"                           # uno o más labels con punto
    r"(?:" + "|".join(sorted(MASK_TLDS, key=len, reverse=True)) + r")"
    r"(?![A-Za-z])"                                    # TLD completo (no "com" en "comercial")
    r"(?:/[A-Za-z0-9\-._~/]*)?",                       # /path opcional
    re.IGNORECASE,
)


def _chain_to_dotted(chain_text: str) -> str | None:
    """Convierte ' punto x punto y punto com' → '.x.y.com' si y solo si al
    menos uno de los segmentos es TLD conocido. Devuelve None si no aplica."""
    # chain_text empieza con espacio.
    parts = re.split(r"\s+punto\s+", chain_text, flags=re.IGNORECASE)
    # split deja un primer elemento vacío porque chain_text arranca con " punto ".
    parts = [p for p in (s.strip() for s in parts) if p]
    if not parts:
        return None
    if not any(p.lower() in KNOWN_TLDS for p in parts):
        return None
    return "." + ".".join(parts)


def _apply_url_email_patterns(text: str, log_lines: list, produced: list | None = None) -> str:
    """Reescribe emails, URLs (con www) y dominios punteados.

    Estrategia conservadora: solo actúa cuando hay TLD conocido en la cadena.
    Si no hay TLD reconocible, deja el texto intacto (evita romper frases
    como 'el punto importante').

    Si `produced` es una lista, se le agregan los tokens URL/email resultantes
    (para que el caller pueda protegerlos del diccionario).
    """
    out = text

    # 1) Email completo: usuario arroba dominio.tld (.subdominios.tld posibles)
    def _email_sub(m):
        user, host, chain = m.group(1), m.group(2), m.group(3)
        dotted = _chain_to_dotted(chain)
        if dotted is None:
            return m.group(0)
        result = f"{user}@{host}{dotted}"
        log_lines.append(f"email: {m.group(0)!r} → {result!r}")
        return result

    out = _EMAIL_PATTERN.sub(_email_sub, out)

    # 2) Prefijo www: "w w w punto X..." → "www.X..."
    out = _WWW_PREFIX.sub("www", out)

    # 3) Cadena de dominios sin email previo.
    def _chain_sub(m):
        head, chain = m.group(1), m.group(2)
        dotted = _chain_to_dotted(chain)
        if dotted is None:
            return m.group(0)
        result = f"{head}{dotted}"
        log_lines.append(f"dominio: {m.group(0)!r} → {result!r}")
        return result

    out = _DOTTED_CHAIN.sub(_chain_sub, out)

    # 4) Sufijo: "...com slash dashboard slash users" → "...com/dashboard/users"
    def _slash_sub(m):
        seg = m.group(1)
        return f"/{seg}"

    # Iterativo: aplicar mientras encuentre slash precedido por alfanumérico.
    prev = None
    while prev != out:
        prev = out
        out = _SLASH_PATH.sub(_slash_sub, out)

    # Recolecta los tokens URL/email producidos (para protegerlos del diccionario).
    if produced is not None:
        for m in _URLISH.finditer(out):
            produced.append(m.group(0))

    return out


# ─── Parser dedicado de URLs/emails degradados ──────────────────────────
#
# Maneja las formas que el MODELO degrada (sin las palabras "arroba/punto/slash"):
# "arroba" fusionado, "@.", guiones que deberían ser slashes, "ap."→"api.",
# ".cov"→".co/", y normaliza el host a minúsculas. Se aplica SOLO si el texto
# contiene señales de URL/email (regla 2.7), para no tocar frases normales.

_MASK_TLD_ALT = "|".join(sorted(MASK_TLDS, key=len, reverse=True))

# Disparadores: si ninguno está presente, no tocamos nada.
_URL_TRIGGERS = (
    "@", "arroba", "slash", "punto", ".com", ".ai", ".co", ".net",
    ".org", ".io", ".dev", "http", "www", "wisip",
)

# Dominio (host) para bajar a minúsculas: labels + TLD de MASK_TLDS (sin js/py).
_HOST_RE = re.compile(
    r"\b([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:" + _MASK_TLD_ALT + r"))(?![A-Za-z])"
)
# Dominio.tld con un posible primer segmento de path, seguido de "-seg-seg…"
# (guiones que en realidad eran slashes): "wisip.ai-dashboard", ".co/v1-users".
_HYPHEN_PATH_RE = re.compile(
    r"\b([A-Za-z0-9-]+\.(?:" + _MASK_TLD_ALT + r")(?:/[A-Za-z0-9]+)?)"
    r"((?:-[A-Za-z0-9]+)+)\b",
    re.IGNORECASE,
)


def normalize_urls_and_emails(text: str, log_lines: list) -> str:
    """Normaliza emails/URLs degradados por el modelo. Solo actúa con contexto
    URL/email (regla 2.7). No destruye guiones de frases normales."""
    low = text.lower()
    if not any(t in low for t in _URL_TRIGGERS):
        return text

    out = text

    # 1) "arroba" fusionado al texto → "@".
    #    "perezarroba.hotmail" → "perez@.hotmail" ; "arrobahotmail" → "@hotmail"
    out = re.sub(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9])arroba", "@", out, flags=re.IGNORECASE)
    out = re.sub(r"\barroba(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9])", "@", out, flags=re.IGNORECASE)
    # 2) "@ ." / "@." → "@" (punto pegado tras arroba).
    out = re.sub(r"@\s*\.", "@", out)

    # 3) Compactar espacios alrededor de símbolos (en contexto ya garantizado).
    out = re.sub(r"\b(https?)\s*:\s*/\s*/", lambda m: m.group(1).lower() + "://", out,
                 flags=re.IGNORECASE)
    out = re.sub(r"([A-Za-z0-9])\s*@\s*([A-Za-z0-9])", r"\1@\2", out)
    prev = None
    while prev != out:
        prev = out
        out = re.sub(r"([A-Za-z0-9])\s*/\s*([A-Za-z0-9])", r"\1/\2", out)
    prev = None
    while prev != out:
        prev = out
        # Solo compacta si el TLD viene en MINÚSCULAS en el original. Así
        # "wisip . com" → "wisip.com" (dominio), pero "importante. Es" NO se
        # vuelve "importante.es" (inicio de frase con mayúscula = no es dominio).
        out = re.sub(
            r"([A-Za-z0-9])\s*\.\s*(" + _MASK_TLD_ALT + r")\b",
            lambda m: f"{m.group(1)}.{m.group(2)}" if m.group(2).islower() else m.group(0),
            out, flags=re.IGNORECASE,
        )

    # 4) URLs mal formadas frecuentes (heurístico, gated por contexto). El ORDEN
    #    importa: primero arreglamos ".cov" y los guiones de path, y solo después
    #    "ap."→"api." (su lookahead necesita ver ya el dominio.tld bien formado).
    #    ".cov-" → ".co/"  ;  ".cov<dígito>" → ".co/v<dígito>"
    out = re.sub(r"\.cov-", ".co/", out, flags=re.IGNORECASE)
    out = re.sub(r"\.cov(?=\d)", ".co/v", out, flags=re.IGNORECASE)
    #    guiones que eran slashes dentro de un path tras dominio.tld.
    out = _HYPHEN_PATH_RE.sub(lambda m: m.group(1) + m.group(2).replace("-", "/"), out)
    #    "ap." → "api." cuando le sigue un dominio.tld.
    out = re.sub(r"\bap\.(?=[A-Za-z0-9-]+\.(?:" + _MASK_TLD_ALT + r")\b)", "api.", out,
                 flags=re.IGNORECASE)

    # 4b) ".ia" es casi siempre "ai" mal oído (p.ej. wisip.ai). Como esto solo
    #     corre en contexto URL/email, es seguro reescribir el TLD.
    out = re.sub(r"\.ia\b", ".ai", out, flags=re.IGNORECASE)

    # 5) Host a minúsculas (Wisip.co → wisip.co), preservando el path.
    out = _HOST_RE.sub(lambda m: m.group(1).lower(), out)

    if out != text:
        log_lines.append(f"url/email: {text!r} → {out!r}")
    return out


# ─── Post-procesador ────────────────────────────────────────────────────
#
# Whisper a veces emite directamente "/" o "." con coma y espacios alrededor
# (ej. "endpoint, / API, / users"). Nuestro pre-procesador no actúa porque ya
# no ve la palabra "slash" / "punto". Este paso corre AL FINAL y limpia la
# formateo que sólo aparece en URLs/paths.
#
# También captura el caso donde Whisper fusiona "arroba" con el host
# ("Arrobajotmail.com" en vez de "arroba Hotmail.com"). Recuperamos al menos
# el "@" aunque el host quede garbleado.

# Colapsa "<alnum>(,? )/(,? )<alnum>" → "<alnum>/<alnum>". Iterativo para
# casos encadenados como "a / b / c".
_POST_SLASH = re.compile(r"([A-Za-z0-9])\s*,?\s*/\s*,?\s*([A-Za-z0-9])")

# "arroba<garble>.<TLD>" fusionado → "@<garble>.<TLD>". Sólo si lo que sigue
# termina en TLD conocido (evita destrozar palabras que empiezan por "arroba").
_FUSED_ARROBA = re.compile(
    r"\b[Aa]rroba([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+\.(?:"
    + "|".join(sorted(KNOWN_TLDS, key=len, reverse=True))
    + r"))",
)

# Compactación de símbolos SOLO en contexto (no global, para no pegar frases).
# " @ " entre alfanuméricos → "@" (claramente un email).
_POST_AT = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9])\s*@\s*([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9])")
# "<word> . <tld>" → "<word>.<tld>" solo si el lado derecho es TLD conocido.
_POST_DOT_TLD = re.compile(
    r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9])\s*\.\s*(" +
    "|".join(sorted(KNOWN_TLDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# "https : / /" o "http : //" → "https://" (el ':' con espacios en URLs).
_POST_SCHEME = re.compile(r"\b(https?)\s*:\s*/\s*/", re.IGNORECASE)


def _normalize_post(text: str, log_lines: list) -> str:
    """Limpieza final tras pre-proc + diccionario.

    Compacta espacios alrededor de símbolos SOLO cuando el contexto es claramente
    email/URL/dominio. Nunca toca " . " genérico entre palabras (eso pegaría
    frases): el punto solo se compacta si el lado derecho es un TLD conocido.
    """
    out = text

    # 1) Esquema http(s)://  (antes que el resto para no romper el "//").
    def _scheme_sub(m):
        result = f"{m.group(1).lower()}://"
        log_lines.append(f"scheme: {m.group(0)!r} → {result!r}")
        return result

    out = _POST_SCHEME.sub(_scheme_sub, out)

    # 2) Espacios+comas alrededor de `/`. Iterativo para "a / b / c".
    prev = None
    while prev != out:
        prev = out
        out = _POST_SLASH.sub(r"\1/\2", out)

    # 3) " @ " entre alfanuméricos → "@".
    prev = None
    while prev != out:
        prev = out
        out = _POST_AT.sub(r"\1@\2", out)

    # 4) "<word> . <tld>" → "<word>.<tld>" (solo TLD conocido).
    prev = None
    while prev != out:
        prev = out
        # Guard: solo si el TLD viene en minúsculas (dominio real). Evita pegar
        # "importante. Es" → "importante.es" en frases normales.
        out = _POST_DOT_TLD.sub(
            lambda m: f"{m.group(1)}.{m.group(2)}" if m.group(2).islower() else m.group(0),
            out,
        )

    # 5) arroba fusionado con host
    def _arroba_sub(m):
        rest = m.group(1)
        result = "@" + rest
        log_lines.append(f"arroba fusionado: {m.group(0)!r} → {result!r}")
        return result

    out = _FUSED_ARROBA.sub(_arroba_sub, out)

    return out


# ─── Clase Replacements ─────────────────────────────────────────────────


class Replacements:
    """Diccionario de reemplazos case-insensitive + pre-procesador de URLs/emails.

    Pipeline al aplicar:
      1. Pre-procesador contextual (URLs/emails/paths) → "wisip punto ai" → "wisip.ai"
      2. Diccionario base (símbolos seguros + términos técnicos)
      3. Si tech_mode=True: diccionario agresivo ("punto" global → ".")
    """

    def __init__(self, on_log=None, tech_mode_getter=None):
        self.on_log = on_log or (lambda m: None)
        # Callable que devuelve bool actual de tech_mode. Evita reinit en cambios.
        self._tech_mode_getter = tech_mode_getter or (lambda: False)
        self._lock = threading.Lock()
        self._map: dict = {}
        self._personal: dict = {}
        self._load()
        self._load_personal()

    def _load(self):
        path = config.REPLACEMENTS_PATH
        if not path.exists():
            try:
                with path.open("w", encoding="utf-8") as f:
                    json.dump(DEFAULT_REPLACEMENTS, f, indent=2, ensure_ascii=False)
                self.on_log(f"[replacements] creado defaults en {path}")
            except Exception as e:
                self.on_log(f"[replacements] no pude crear {path}: {e}")
            with self._lock:
                self._map = dict(DEFAULT_REPLACEMENTS)
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                disk = json.load(f)
            if not isinstance(disk, dict):
                raise ValueError("replacements.json debe ser un objeto JSON {clave: valor}")

            # Merge aditivo: lo del disco gana, pero sembramos defaults nuevos.
            disk_norm = {str(k): str(v) for k, v in disk.items()}
            added = 0
            for k, v in DEFAULT_REPLACEMENTS.items():
                if k not in disk_norm:
                    disk_norm[k] = v
                    added += 1

            # Migración: entradas movidas a tech_mode se retiran del JSON si
            # conservan el valor default viejo (rompían habla normal).
            removed = 0
            for k, old_v in _MOVED_TO_TECH_MODE.items():
                if disk_norm.get(k) == old_v:
                    del disk_norm[k]
                    removed += 1
            if removed > 0:
                self.on_log(
                    f"[replacements] {removed} entradas movidas a modo técnico "
                    f"(retiradas del diccionario siempre-activo)"
                )

            if added > 0 or removed > 0:
                try:
                    with path.open("w", encoding="utf-8") as f:
                        json.dump(disk_norm, f, indent=2, ensure_ascii=False)
                    if added > 0:
                        self.on_log(
                            f"[replacements] {added} nuevas entradas default agregadas a {path}"
                        )
                except Exception as e:
                    self.on_log(f"[replacements] no pude actualizar {path}: {e}")

            with self._lock:
                self._map = disk_norm
            self.on_log(f"[replacements] cargado {len(self._map)} entradas desde {path}")
        except Exception as e:
            self.on_log(f"[replacements] error leyendo {path}: {e}")
            with self._lock:
                self._map = dict(DEFAULT_REPLACEMENTS)

    def _load_personal(self):
        """Carga personal_replacements.json (nombres propios / marca). Si no
        existe, lo crea con los defaults. Merge aditivo, igual que el general."""
        path = config.PERSONAL_REPLACEMENTS_PATH
        if not path.exists():
            try:
                with path.open("w", encoding="utf-8") as f:
                    json.dump(DEFAULT_PERSONAL_REPLACEMENTS, f, indent=2, ensure_ascii=False)
                self.on_log(f"[personal] creado defaults en {path}")
            except Exception as e:
                self.on_log(f"[personal] no pude crear {path}: {e}")
            with self._lock:
                self._personal = dict(DEFAULT_PERSONAL_REPLACEMENTS)
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                disk = json.load(f)
            if not isinstance(disk, dict):
                raise ValueError("personal_replacements.json debe ser un objeto JSON")
            disk_norm = {str(k): str(v) for k, v in disk.items()}
            added = 0
            for k, v in DEFAULT_PERSONAL_REPLACEMENTS.items():
                if k not in disk_norm:
                    disk_norm[k] = v
                    added += 1
            if added > 0:
                try:
                    with path.open("w", encoding="utf-8") as f:
                        json.dump(disk_norm, f, indent=2, ensure_ascii=False)
                    self.on_log(f"[personal] {added} nuevas entradas default agregadas a {path}")
                except Exception as e:
                    self.on_log(f"[personal] no pude actualizar {path}: {e}")
            with self._lock:
                self._personal = disk_norm
            self.on_log(f"[personal] cargado {len(self._personal)} entradas desde {path}")
        except Exception as e:
            self.on_log(f"[personal] error leyendo {path}: {e}")
            with self._lock:
                self._personal = dict(DEFAULT_PERSONAL_REPLACEMENTS)

    def reload(self):
        self._load()
        self._load_personal()

    def _apply_dict(self, text: str, mapping: dict) -> tuple[str, list]:
        """Aplica un dict de reemplazos como sub regex, case-insensitive,
        respetando límites de palabra. Más largos primero."""
        items = sorted(mapping.items(), key=lambda kv: -len(kv[0]))
        applied = []
        out = text
        for key, val in items:
            key = key.strip()
            if not key:
                continue
            inner = _re_word(key)
            pattern = r"(?i)\b" + inner + r"\b"
            try:
                new_out, count = re.subn(pattern, val, out)
            except re.error:
                continue
            if count > 0:
                out = new_out
                applied.append((key, val))
        return out, applied

    def apply(self, text: str):
        """Aplica todos los reemplazos. Devuelve (texto_nuevo, [(clave, valor), ...] aplicados).

        Orden:
          0. VAD contextual ('bad'→'VAD' solo en contexto técnico).
          1. Pre-pasada de nombres propios (personal_replacements.json) ANTES del
             reconstructor de email/URL, para que un nombre/host mal oído se
             corrija antes de rearmar el correo (no toca arroba/punto/slash).
          2. Pre-procesador contextual por palabras (URLs/emails/paths con
             "punto"/"arroba"/"slash" + TLD conocido).
          3. Parser de URLs/emails degradados (arroba fusionado, guion→slash,
             ap.→api., .cov→.co/, host a minúsculas), gated por contexto.
          4. Enmascara los tokens URL/email (escaneo) para protegerlos del dict.
          5. Diccionario base (símbolos seguros + términos técnicos).
          6. Diccionario tech (opt-in vía settings.tech_mode).
          7. Restaura tokens + post-procesador (compactación final).
        """
        if not text:
            return text, []

        applied_all = []

        # 0. VAD contextual.
        vad_log: list = []
        out = _apply_contextual_vad(text, vad_log)
        for line in vad_log:
            applied_all.append(("[vad]", line))

        # 1. Pre-pasada de nombres propios (no incluye arroba/punto/slash, así que
        #    no interfiere con el reconstructor de email que viene después).
        with self._lock:
            personal = dict(self._personal)
        out, applied = self._apply_dict(out, personal)
        for k, v in applied:
            applied_all.append((f"[personal] {k}", v))

        # 2. Pre-procesador URL/email/path por palabras.
        url_log: list = []
        out = _apply_url_email_patterns(out, url_log)
        for line in url_log:
            applied_all.append(("[url/email]", line))

        # 3. Parser de URLs/emails degradados (símbolos sin las palabras).
        norm_log: list = []
        out = normalize_urls_and_emails(out, norm_log)
        for line in norm_log:
            applied_all.append(("[url/email]", line))

        # 3b. Segunda pasada de nombres propios: al separar un "arroba" fusionado
        #     (p.ej. "juanperezarroba.hotmail" → "juanperez@hotmail") queda
        #     expuesto el nombre, que ahora sí podemos corregir.
        out, applied = self._apply_dict(out, personal)
        for k, v in applied:
            applied_all.append((f"[personal] {k}", v))

        # 4. Enmascara los tokens URL/email (escaneo) para que el diccionario NO
        #    los toque (evita "wisip.ai"→"Wisip.ai" o "api.wisip.co"→"API.Wisip.co").
        masks: dict = {}
        found = sorted({m.group(0) for m in _URLISH.finditer(out)}, key=len, reverse=True)
        for i, tok in enumerate(found):
            if not tok:
                continue
            ph = f"\x00U{i}\x00"
            if tok in out:
                out = out.replace(tok, ph)
                masks[ph] = tok

        # 5. Diccionario base.
        with self._lock:
            base = dict(self._map)
        out, applied = self._apply_dict(out, base)
        applied_all.extend(applied)

        # 4. Tech mode (opt-in).
        try:
            tech_on = bool(self._tech_mode_getter())
        except Exception:
            tech_on = False
        if tech_on:
            out, applied = self._apply_dict(out, TECH_MODE_REPLACEMENTS)
            for k, v in applied:
                applied_all.append((f"[tech] {k}", v))

        # 4b. Restaura los tokens URL/email enmascarados.
        for ph, tok in masks.items():
            out = out.replace(ph, tok)

        # 5. Post-procesador: limpia formato de Whisper (slashes con espacios,
        #    arroba fusionado con el host, compactación de @ / . : en contexto).
        post_log: list = []
        out = _normalize_post(out, post_log)
        for line in post_log:
            applied_all.append(("[post]", line))

        return out, applied_all
