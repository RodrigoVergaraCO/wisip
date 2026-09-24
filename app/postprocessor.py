# -*- coding: utf-8 -*-
"""
Postprocesador dedicado de correos, URLs y símbolos para Wisip.

Se ejecuta DESPUÉS de la transcripción y DESPUÉS de los reemplazos (generales y
personales), y ANTES de copiar/pegar. Es complementario a `replacements.py`
(que ya convierte "arroba/punto/slash" + TLD en símbolos): aquí cerramos los
huecos que quedan, sobre todo en CORREOS, de forma **genérica** (funciona con
cualquier email, sin datos personales en el código) e **idempotente** (si el
texto ya está bien, no lo daña).

Función pública:
    normalize_emails_urls_symbols(text: str, settings: dict) -> str

Seguridad ante texto normal:
  - Las reglas de email/URL solo actúan ante señales claras (proveedor conocido,
    "@", dominio.tld, o palabras de contexto como "correo/email").
  - "-" → "@" SOLO cuando la derecha es un proveedor conocido
    (hotmail/gmail/outlook/yahoo/icloud .com). Nunca toca guiones normales
    (cliente-servidor, micro-servicios, rangos 2024-01).
  - La "arroba" agresiva (convertir "arroba" suelta en prosa) solo ocurre con
    `technical_symbol_mode=true`.

Datos personales: NO hay correos ni alias en el código. Los alias opcionales
viven en `personal_emails.json` (en %APPDATA%), que se crea VACÍO.
"""

import json
import re
import time
import unicodedata

from . import config

# ─── Proveedores de correo conocidos (lista cerrada, para el guion→@) ──────
KNOWN_PROVIDERS = ("hotmail.com", "gmail.com", "outlook.com", "yahoo.com", "icloud.com")
_PROVIDER_ALT = "|".join(p.replace(".", r"\.") for p in KNOWN_PROVIDERS)

# Formas mal oídas de "arroba". "arroba" suele venir ya como "@" desde el
# diccionario; aquí cazamos las que se escapan ("a roba", "aroba", "a-rroba").
_ARROBA_VARIANT = r"(?:a\s*-\s*rroba|a\s+rroba|a\s+roba|arroba|aroba)"

# Email con arroba (símbolo o palabra mal oída) + dominio.tld. Genérico.
_EMAIL_ARROBA = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._%+\-]*)\s*(?:@|" + _ARROBA_VARIANT + r")\s*"
    r"([A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,})",
    re.IGNORECASE,
)

# "usuario-proveedor.com" → el guion es un "@" mal oído. Solo proveedor conocido.
_HYPHEN_PROVIDER = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._%+\-]*?)-(" + _PROVIDER_ALT + r")\b",
    re.IGNORECASE,
)

# "usuario proveedor.com" (espacio). Solo se usa si hay contexto de correo.
_SPACE_PROVIDER = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9._%+]*)\s+(" + _PROVIDER_ALT + r")\b",
    re.IGNORECASE,
)

# Contexto de correo para habilitar la regla del espacio.
_EMAIL_CONTEXT = re.compile(r"\b(correo|email|e-?mail)\b", re.IGNORECASE)

# Email ya formado (cualquiera) para alias y compactaciones finales.
_ANY_EMAIL = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

# Email ya dentro de un enlace markdown, para no re-envolverlo.
_MD_EMAIL = re.compile(r"\]\(mailto:")

# Email con espacios alrededor de @ y del punto: "user @ host . com" →
# "user@host.com". CLAVE: exige "@", así NUNCA toca un punto de fin de frase
# ("esto. Es verdad" se queda igual). Cubre los casos con espacios (8, 9, 10).
_SPACED_EMAIL = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._%+\-]*)\s*@\s*([A-Za-z0-9][A-Za-z0-9\-]*)\s*\.\s*([A-Za-z]{2,})\b"
)


# ─── Carga de alias personales (opcional, por usuario) ─────────────────────

# Estructura pública por defecto: VACÍA (sin PII en el código).
DEFAULT_PERSONAL_EMAILS = {
    "personal_emails": {},   # ej. {"main": "tu_correo@dominio.com"}
    "email_aliases": [],     # ej. ["alias1", "alias dos", ...]
}

_cache = {"mtime": None, "data": None}


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _norm_alias(s: str) -> str:
    """Normaliza para comparar alias: minúsculas, sin tildes, sin espacios."""
    return _strip_accents(s).lower().replace(" ", "")


def _load_personal_emails() -> dict:
    """Lee personal_emails.json con caché por mtime. Lo crea vacío si falta.
    Nunca lanza: ante error devuelve la estructura por defecto."""
    path = config.PERSONAL_EMAILS_PATH
    try:
        if not path.exists():
            with path.open("w", encoding="utf-8") as f:
                json.dump(DEFAULT_PERSONAL_EMAILS, f, indent=2, ensure_ascii=False)
            _cache["mtime"] = path.stat().st_mtime
            _cache["data"] = dict(DEFAULT_PERSONAL_EMAILS)
            return _cache["data"]
        mtime = path.stat().st_mtime
        if _cache["data"] is not None and _cache["mtime"] == mtime:
            return _cache["data"]
        with path.open("r", encoding="utf-8") as f:
            disk = json.load(f)
        data = {
            "personal_emails": dict(disk.get("personal_emails", {})),
            "email_aliases": list(disk.get("email_aliases", [])),
        }
        _cache["mtime"] = mtime
        _cache["data"] = data
        return data
    except Exception:
        return dict(DEFAULT_PERSONAL_EMAILS)


# ─── Función principal ─────────────────────────────────────────────────────

def normalize_emails_urls_symbols(text: str, settings: dict) -> str:
    """Normaliza correos, URLs y símbolos de forma segura e idempotente.

    `settings` es un dict (p. ej. el de Settings.all()). Respeta:
      - normalize_emails_urls (bool, def True): interruptor maestro.
      - technical_symbol_mode (bool, def False): arroba agresiva en prosa.
      - email_as_markdown (bool, def False): envolver emails en [..](mailto:..).
      - debug_normalizer (bool, def False): loguea antes/después/reglas.
    """
    if not text or not settings.get("normalize_emails_urls", True):
        return text

    out = text
    rules = []
    tech = bool(settings.get("technical_symbol_mode", False))
    t0 = time.perf_counter()

    # 0) Modo técnico: arroba suelta → @ en todo el texto (opt-in).
    if tech:
        new = re.sub(r"\b" + _ARROBA_VARIANT + r"\b", "@", out, flags=re.IGNORECASE)
        if new != out:
            rules.append("tech: arroba→@ global")
            out = new

    # 1) Reconstruir email con espacios alrededor de @ y del punto (casos 8-10).
    #    Gated por "@": no puede romper puntuación normal de frases.
    def _spaced_email_sub(m):
        res = f"{m.group(1)}@{m.group(2).lower()}.{m.group(3).lower()}"
        if res != m.group(0):
            rules.append(f"email-espacios: {m.group(0)!r}→{res}")
        return res
    out = _SPACED_EMAIL.sub(_spaced_email_sub, out)

    # 2) Email con arroba (palabra mal oída) + dominio.tld → user@dominio.tld.
    def _email_arroba_sub(m):
        user, host = m.group(1), m.group(2)
        rules.append(f"email-arroba: {m.group(0)!r}→{user}@{host}")
        return f"{user}@{host}"
    out = _EMAIL_ARROBA.sub(_email_arroba_sub, out)

    # 3) "usuario-proveedor.com" → "usuario@proveedor.com" (proveedor conocido).
    def _hyphen_sub(m):
        user, prov = m.group(1), m.group(2).lower()
        rules.append(f"guion→@: {m.group(0)!r}→{user}@{prov}")
        return f"{user}@{prov}"
    out = _HYPHEN_PROVIDER.sub(_hyphen_sub, out)

    # 4) "usuario proveedor.com" → "usuario@proveedor.com" SOLO con contexto.
    if _EMAIL_CONTEXT.search(out):
        def _space_sub(m):
            user, prov = m.group(1), m.group(2).lower()
            # Evita capturar palabras de contexto como "correo"/"email" de usuario.
            if user.lower() in ("correo", "email", "e-mail", "mail", "es", "el", "mi"):
                return m.group(0)
            rules.append(f"espacio→@: {m.group(0)!r}→{user}@{prov}")
            return f"{user}@{prov}"
        out = _SPACE_PROVIDER.sub(_space_sub, out)

    # 5) Alias personales → correo principal (desde personal_emails.json).
    pe = _load_personal_emails()
    main_email = (pe.get("personal_emails", {}) or {}).get("main")
    aliases = {_norm_alias(a) for a in (pe.get("email_aliases", []) or []) if a}
    if main_email and aliases:
        def _alias_sub(m):
            local = m.group(1)
            if _norm_alias(local) in aliases:
                rules.append(f"alias→main: {m.group(0)!r}→{main_email}")
                return main_email
            return m.group(0)
        out = _ANY_EMAIL.sub(_alias_sub, out)

    # 6) Markdown opcional: envolver emails en [correo](mailto:correo).
    if settings.get("email_as_markdown", False) and not _MD_EMAIL.search(out):
        def _md_sub(m):
            email = m.group(0)
            return f"[{email}](mailto:{email})"
        out = _ANY_EMAIL.sub(_md_sub, out)

    if settings.get("debug_normalizer", False) and rules:
        log_fn = settings.get("_log") if callable(settings.get("_log")) else print
        log_fn(f"[normalizer] antes: {text!r}")
        log_fn(f"[normalizer] después: {out!r}")
        log_fn(f"[normalizer] reglas: {rules}  ({(time.perf_counter()-t0)*1000:.0f}ms)")

    return out
