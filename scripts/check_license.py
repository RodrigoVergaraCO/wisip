# -*- coding: utf-8 -*-
"""Valida el sistema de licencias (app/license.py) SIN red ni cuenta real:
levanta un servidor HTTP local que imita la License API de Lemon Squeezy
(activate / validate / deactivate, con límite de activaciones) y recorre
prueba gratuita → activación → revalidación → sin red → desactivación.

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_license.py
"""

import datetime as dt
import http.server
import json
import sys
import threading
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import config  # noqa: E402
from app import license as lic  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


# ─── Servidor que imita a Lemon Squeezy ────────────────────────────────

class _DB:
    keys = {"AAAA-1111": {"limit": 1, "instances": {}, "status": "active", "next_id": 1},
            "BBBB-2222": {"limit": 1, "instances": {}, "status": "disabled", "next_id": 1}}
    down = False
    calls = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        _DB.calls.append((self.path, form))
        if _DB.down:
            self._send(503, {"error": "down"})
            return
        key = form.get("license_key", "")
        rec = _DB.keys.get(key)
        meta = {"customer_email": "cliente@correo.com", "product_name": "Wisip"}
        if self.path.endswith("/activate"):
            if not rec:
                self._send(404, {"activated": False, "error": "license_key not found"}); return
            if rec["status"] != "active":
                self._send(400, {"activated": False, "error": "This license key is disabled"}); return
            if len(rec["instances"]) >= rec["limit"]:
                self._send(400, {"activated": False, "error": "This license key has reached its activation limit"}); return
            iid = f"inst-{rec['next_id']}"; rec["next_id"] += 1
            rec["instances"][iid] = form.get("instance_name", "")
            self._send(200, {"activated": True, "error": None,
                             "license_key": {"status": "active", "activation_limit": rec["limit"],
                                             "activation_usage": len(rec["instances"])},
                             "instance": {"id": iid, "name": rec["instances"][iid]}, "meta": meta})
        elif self.path.endswith("/validate"):
            if not rec:
                self._send(404, {"valid": False, "error": "license_key not found"}); return
            iid = form.get("instance_id")
            if iid and iid not in rec["instances"]:
                self._send(404, {"valid": False, "error": "instance not found",
                                 "license_key": {"status": rec["status"]}}); return
            ok = rec["status"] == "active"
            self._send(200 if ok else 400, {"valid": ok, "error": None if ok else "This license key is disabled",
                                            "license_key": {"status": rec["status"], "activation_limit": rec["limit"],
                                                            "activation_usage": len(rec["instances"])}, "meta": meta})
        elif self.path.endswith("/deactivate"):
            iid = form.get("instance_id")
            if not rec or iid not in rec["instances"]:
                self._send(404, {"deactivated": False, "error": "instance not found"}); return
            del rec["instances"][iid]
            self._send(200, {"deactivated": True, "error": None,
                             "license_key": {"status": "inactive"}, "meta": meta})
        else:
            self._send(404, {"error": "unknown"})


class _Settings:
    def __init__(self):
        self.d = {}

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        self.d[k] = v

    def all(self):
        return dict(self.d)


class _Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)

    def now(self):
        return self.t

    def advance(self, days):
        self.t += dt.timedelta(days=days)


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1/licenses"
    logs = []
    try:
        clock = _Clock()
        st = _Settings()
        lm = lic.LicenseManager(st, on_log=logs.append, client=lic.LemonSqueezyClient(base), now_fn=clock.now)

        print("── Utilidades ──")
        check("machine_id estable y corto", lic.machine_id() == lic.machine_id() and len(lic.machine_id()) == 16)
        check("instance_name incluye huella", lic.machine_id()[:8] in lic.instance_name())
        check("mask_key", lic.mask_key("AAAA-1111-CCCC-3333") == "AAAA" + "•" * 11 + "3333")
        check("error_message_es límite", "otro equipo" in lic.error_message_es("This license key has reached its activation limit"))

        print("\n── Prueba gratuita ──")
        s = lm.status()
        check("primer arranque → prueba de 30 días", s["state"] == lic.STATE_TRIAL and s["days_left"] == config.TRIAL_DAYS, str(s))
        check("trial_started guardado", bool(st.get("trial_started")))
        check("permite dictar", lm.allows_dictation())
        clock.advance(29)
        check("día 29 → 1 día restante", lm.status()["days_left"] == 1 and lm.allows_dictation())
        clock.advance(2)
        s = lm.status()
        check("día 31 → prueba terminada, bloquea", s["state"] == lic.STATE_TRIAL_EXPIRED and not lm.allows_dictation())

        print("\n── Activación ──")
        ok, msg = lm.activate("")
        check("clave vacía → mensaje", not ok and "Escribe" in msg)
        ok, msg = lm.activate("ZZZZ-0000")
        check("clave inexistente → mensaje claro", not ok and "no existe" in msg, msg)
        ok, msg = lm.activate("BBBB-2222")
        check("clave deshabilitada → mensaje", not ok and "desactivada" in msg, msg)
        ok, msg = lm.activate("AAAA-1111")
        s = lm.status()
        check("activación OK", ok and s["state"] == lic.STATE_LICENSED, msg)
        check("instancia y correo guardados", st.get("license_instance_id") == "inst-1" and st.get("license_email") == "cliente@correo.com")
        check("permite dictar con licencia", lm.allows_dictation())
        # Segundo equipo con la misma clave → límite.
        st2 = _Settings()
        lm2 = lic.LicenseManager(st2, on_log=logs.append, client=lic.LemonSqueezyClient(base), now_fn=clock.now)
        ok2, msg2 = lm2.activate("AAAA-1111")
        check("segundo equipo → límite de activaciones", not ok2 and "otro equipo" in msg2, msg2)

        print("\n── Revalidación ──")
        n0 = len(_DB.calls)
        check("no revalida antes de tiempo", lm.revalidate_if_due() is None and len(_DB.calls) == n0)
        clock.advance(config.LICENSE_REVALIDATE_DAYS)
        r = lm.revalidate_if_due()
        check("revalida al cumplir el plazo", r is not None and "OK" in r and _DB.calls[-1][0].endswith("/validate"), str(r))
        _DB.down = True
        clock.advance(config.LICENSE_REVALIDATE_DAYS)
        r = lm.revalidate_if_due()
        check("sin red → pospone y sigue con licencia", "sin red" in (r or "") and lm.status()["state"] == lic.STATE_LICENSED)
        clock.advance(config.LICENSE_OFFLINE_GRACE_DAYS)
        s = lm.status()
        check("sin verificar más allá de la gracia → bloquea con aviso", s["state"] == lic.STATE_INVALID and "internet" in s["message"] and not lm.allows_dictation(), str(s))
        _DB.down = False
        r = lm.revalidate_if_due()
        check("vuelve la red → revalida y desbloquea", "OK" in (r or "") and lm.allows_dictation())
        # El vendedor deshabilita la clave.
        _DB.keys["AAAA-1111"]["status"] = "disabled"
        r = lm.revalidate_if_due(force=True)
        s = lm.status()
        check("clave deshabilitada en servidor → inválida", s["state"] == lic.STATE_INVALID and not lm.allows_dictation(), str(s))
        _DB.keys["AAAA-1111"]["status"] = "active"
        ok, msg = lm.activate("AAAA-1111")
        check("reactivar con la misma instancia libre falla por límite (sigue ocupada)", not ok, msg)

        print("\n── Desactivación ──")
        st.set("license_status", "active")  # simula estado sano
        ok, msg = lm.deactivate()
        check("desactiva en servidor y limpia local", ok and st.get("license_key") == "" and _DB.calls[-1][0].endswith("/deactivate"), msg)
        check("tras desactivar: prueba ya terminada → bloquea", lm.status()["state"] == lic.STATE_TRIAL_EXPIRED)
        ok2, msg2 = lm2.activate("AAAA-1111")
        check("otro equipo ya puede activar", ok2, msg2)
        ok, msg = lm.deactivate()
        check("desactivar sin licencia → mensaje", not ok and "ninguna" in msg)
        # Instancia borrada en el servidor → desactivar local igual limpia.
        st.set("license_key", "AAAA-1111"); st.set("license_instance_id", "inst-999"); st.set("license_status", "active")
        ok, msg = lm.deactivate()
        check("instancia inexistente en servidor → libera igual", ok and st.get("license_key") == "")
        _DB.down = True
        st.set("license_key", "AAAA-1111"); st.set("license_instance_id", "inst-2"); st.set("license_status", "active")
        ok, msg = lm.deactivate()
        check("desactivar sin red → no libera y avisa", not ok and "internet" in msg and st.get("license_key") == "AAAA-1111")
        _DB.down = False
    finally:
        srv.shutdown()

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de licencias pasaron.")


if __name__ == "__main__":
    main()
