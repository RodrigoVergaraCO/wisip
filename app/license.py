"""Licencias (2.9.0): prueba gratuita de 30 días + clave de por vida atada a
un equipo, con activación/desactivación contra la License API de Lemon
Squeezy (https://docs.lemonsqueezy.com/api/license-api).

Modelo:
- Prueba: empieza en el primer arranque (`trial_started`) y dura
  `config.TRIAL_DAYS`. Al terminar, la app sigue abriendo pero no graba
  hasta activar una clave.
- Activación: POST /activate con `license_key` + `instance_name` (nombre del
  PC + huella). Lemon Squeezy limita las activaciones por clave
  (activation_limit = 1 en el producto) → "1 equipo". Se guarda
  `license_instance_id` para validar y desactivar.
- Revalidación: cada `LICENSE_REVALIDATE_DAYS` se consulta /validate. Sin
  internet se sigue confiando en la última validación hasta
  `LICENSE_OFFLINE_GRACE_DAYS`.
- Desactivación: POST /deactivate libera la activación para usar la clave en
  otro equipo. La llama el botón de la pestaña Licencia y el desinstalador
  (`Wisip.exe --deactivate-license`).

Todo el estado vive en app_settings.json (claves `license_*`, `trial_started`).
Nada de esto pretende resistir a un usuario que edite el JSON: el objetivo es
que comprar sea más fácil que trampear, no un DRM.
"""

import datetime as _dt
import hashlib
import json
import os
import platform
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import config

_UA = "Wisip/2.9 (+https://github.com/acropolifamily-web/wisip)"
_TIMEOUT = 20

STATE_LICENSED = "licensed"
STATE_TRIAL = "trial"
STATE_TRIAL_EXPIRED = "trial_expired"
STATE_INVALID = "invalid"

# Mensajes en español para los errores más comunes de la License API.
_ERROR_ES = (
    ("activation limit", "Esta clave ya está activada en otro equipo. Desactívala allí (o "
                         "desinstala Wisip en ese equipo) y vuelve a intentarlo."),
    ("not found", "La clave no existe. Revisa que esté completa (formato "
                  "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)."),
    ("disabled", "Esta clave fue desactivada por el vendedor."),
    ("expired", "Esta clave expiró."),
    ("instance", "La activación de este equipo ya no existe. Vuelve a activar la clave."),
)


class LicenseNetworkError(Exception):
    """Sin conexión o el servidor no respondió."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(d: _dt.datetime) -> str:
    return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except Exception:
        try:
            d = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
        except Exception:
            return None


def machine_id() -> str:
    """Huella estable del equipo (MachineGuid de Windows + nombre de host)."""
    raw = ""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                raw = str(winreg.QueryValueEx(k, "MachineGuid")[0])
        except Exception:
            raw = ""
    if not raw:
        import uuid
        raw = f"{uuid.getnode():x}"
    raw += "|" + (socket.gethostname() or "")
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def instance_name() -> str:
    host = socket.gethostname() or platform.node() or "PC"
    return f"{host} ({machine_id()[:8]})"


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if len(key) <= 8:
        return "•" * len(key)
    return key[:4] + "•" * max(4, len(key) - 8) + key[-4:]


def error_message_es(err: str | None) -> str:
    low = (err or "").lower()
    for frag, msg in _ERROR_ES:
        if frag in low:
            return msg
    return err or "La activación fue rechazada."


class LemonSqueezyClient:
    """Los tres endpoints públicos de la License API (no requieren API key)."""

    def __init__(self, base: str | None = None):
        self.base = (base or os.environ.get("WISIP_LICENSE_API") or config.LICENSE_API_BASE).rstrip("/")

    def _post(self, path: str, data: dict) -> dict:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/{path}", data=body, method="POST",
            headers={"Accept": "application/json", "User-Agent": _UA,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600:
                raise LicenseNetworkError(f"servidor de licencias no disponible (HTTP {e.code})") from e
            # Lemon Squeezy responde 4xx con JSON {"error": "...", ...}.
            try:
                raw = e.read()
                data = json.loads(raw.decode("utf-8", "replace"))
                if isinstance(data, dict):
                    data.setdefault("error", f"HTTP {e.code}")
                    return data
            except Exception:
                pass
            return {"error": f"HTTP {e.code}"}
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            raise LicenseNetworkError(f"sin conexión con el servidor de licencias: {e}") from e
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:
            raise LicenseNetworkError(f"respuesta inválida del servidor: {e}") from e
        return data if isinstance(data, dict) else {"error": "respuesta inválida"}

    def activate(self, key: str, name: str) -> dict:
        return self._post("activate", {"license_key": key, "instance_name": name})

    def validate(self, key: str, instance_id: str | None = None) -> dict:
        data = {"license_key": key}
        if instance_id:
            data["instance_id"] = instance_id
        return self._post("validate", data)

    def deactivate(self, key: str, instance_id: str) -> dict:
        return self._post("deactivate", {"license_key": key, "instance_id": instance_id})


class LicenseManager:
    def __init__(self, settings, on_log=None, client: LemonSqueezyClient | None = None, now_fn=None):
        self.settings = settings
        self.on_log = on_log or (lambda m: None)
        self.client = client or LemonSqueezyClient()
        self._now = now_fn or _now

    # ── helpers ──
    def _get(self, k, default=""):
        v = self.settings.get(k)
        return default if v is None else v

    def ensure_trial_started(self):
        if not self._get("trial_started"):
            self.settings.set("trial_started", _iso(self._now()))
            self.on_log(f"[licencia] prueba gratuita iniciada ({config.TRIAL_DAYS} días)")

    def trial_days_left(self) -> int | None:
        start = _parse(self._get("trial_started"))
        if start is None:
            return None
        elapsed = (self._now() - start).days
        return config.TRIAL_DAYS - elapsed

    # ── estado ──
    def status(self) -> dict:
        key = str(self._get("license_key") or "").strip()
        lstatus = str(self._get("license_status") or "")
        if key and lstatus == "active":
            last = _parse(self._get("license_last_validated"))
            stale_days = (self._now() - last).days if last else 0
            msg = "Licencia de por vida activa en este equipo."
            if stale_days > config.LICENSE_OFFLINE_GRACE_DAYS:
                return {"state": STATE_INVALID, "days_left": None, "key_masked": mask_key(key),
                        "email": self._get("license_email"), "instance": instance_name(),
                        "message": f"No se pudo verificar la licencia en {stale_days} días. "
                                   "Conéctate a internet y abre Wisip para verificarla."}
            return {"state": STATE_LICENSED, "days_left": None, "key_masked": mask_key(key),
                    "email": self._get("license_email"), "instance": instance_name(), "message": msg}
        if key and lstatus == "invalid":
            return {"state": STATE_INVALID, "days_left": None, "key_masked": mask_key(key),
                    "email": self._get("license_email"), "instance": instance_name(),
                    "message": str(self._get("license_message") or "La clave ya no es válida.")}
        days = self.trial_days_left()
        if days is None:
            self.ensure_trial_started()
            days = config.TRIAL_DAYS
        if days > 0:
            return {"state": STATE_TRIAL, "days_left": days, "key_masked": "", "email": "",
                    "instance": instance_name(),
                    "message": f"Prueba gratuita: {days} día{'s' if days != 1 else ''} restante"
                               f"{'s' if days != 1 else ''}. Después necesitarás una licencia."}
        return {"state": STATE_TRIAL_EXPIRED, "days_left": 0, "key_masked": "", "email": "",
                "instance": instance_name(),
                "message": "La prueba gratuita terminó. Activa una licencia para seguir dictando."}

    def allows_dictation(self) -> bool:
        return self.status()["state"] in (STATE_LICENSED, STATE_TRIAL)

    # ── acciones (red) ──
    def activate(self, key: str) -> tuple[bool, str]:
        key = (key or "").strip()
        if not key:
            return False, "Escribe la clave de licencia."
        try:
            resp = self.client.activate(key, instance_name())
        except LicenseNetworkError as e:
            self.on_log(f"[licencia] activación sin red: {e}")
            return False, "No hay conexión con el servidor de licencias. Revisa tu internet e inténtalo de nuevo."
        if not resp.get("activated"):
            msg = error_message_es(resp.get("error"))
            self.on_log(f"[licencia] activación rechazada: {resp.get('error')!r}")
            return False, msg
        inst = resp.get("instance") or {}
        meta = resp.get("meta") or {}
        lk = resp.get("license_key") or {}
        now = _iso(self._now())
        self.settings.set("license_key", key)
        self.settings.set("license_instance_id", str(inst.get("id") or ""))
        self.settings.set("license_status", "active")
        self.settings.set("license_activated_at", now)
        self.settings.set("license_last_validated", now)
        self.settings.set("license_email", str(meta.get("customer_email") or ""))
        self.settings.set("license_product", str(meta.get("product_name") or ""))
        self.settings.set("license_message", "")
        self.on_log(f"[licencia] activada ({mask_key(key)}) · instancia {inst.get('id')} · "
                    f"usos {lk.get('activation_usage')}/{lk.get('activation_limit')}")
        return True, "Licencia activada. ¡Gracias por apoyar Wisip!"

    def deactivate(self) -> tuple[bool, str]:
        key = str(self._get("license_key") or "").strip()
        inst = str(self._get("license_instance_id") or "").strip()
        if not key:
            return False, "No hay ninguna licencia activada en este equipo."
        try:
            resp = self.client.deactivate(key, inst) if inst else {"deactivated": True}
        except LicenseNetworkError as e:
            self.on_log(f"[licencia] desactivación sin red: {e}")
            return False, "No hay conexión con el servidor de licencias. Necesitas internet para liberar la clave."
        err = str(resp.get("error") or "")
        if not resp.get("deactivated") and "instance" not in err.lower() and "not found" not in err.lower():
            msg = error_message_es(err)
            self.on_log(f"[licencia] desactivación rechazada: {err!r}")
            return False, msg
        # Éxito, o la instancia ya no existía en el servidor: en ambos casos
        # este equipo queda libre.
        self._clear_local()
        self.on_log(f"[licencia] desactivada en este equipo ({mask_key(key)})")
        return True, "Licencia liberada. Ya puedes activarla en otro equipo."

    def _clear_local(self):
        for k in ("license_key", "license_instance_id", "license_status", "license_activated_at",
                  "license_last_validated", "license_email", "license_product", "license_message"):
            self.settings.set(k, "")

    def revalidate_if_due(self, force: bool = False) -> str | None:
        """Consulta /validate si toca. Devuelve un texto de log o None."""
        key = str(self._get("license_key") or "").strip()
        if not key or str(self._get("license_status") or "") != "active":
            return None
        last = _parse(self._get("license_last_validated"))
        due = force or last is None or (self._now() - last).days >= config.LICENSE_REVALIDATE_DAYS
        if not due:
            return None
        inst = str(self._get("license_instance_id") or "")
        try:
            resp = self.client.validate(key, inst or None)
        except LicenseNetworkError as e:
            msg = f"[licencia] revalidación pospuesta (sin red): {e}"
            self.on_log(msg)
            return msg
        lk = resp.get("license_key") or {}
        status = str(lk.get("status") or "")
        if resp.get("valid") and status in ("active", ""):
            self.settings.set("license_last_validated", _iso(self._now()))
            msg = "[licencia] revalidada OK"
        else:
            err = error_message_es(resp.get("error") or (f"estado {status}" if status else None))
            self.settings.set("license_status", "invalid")
            self.settings.set("license_message", err)
            msg = f"[licencia] ya no es válida: {err}"
        self.on_log(msg)
        return msg
