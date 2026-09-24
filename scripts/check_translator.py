# -*- coding: utf-8 -*-
"""Valida la traducción local (app/translator.py) y los atajos múltiples
(app/hotkeys.MultiHotkeyManager) sin hardware ni red.

- split/join de oraciones y párrafos, idioma igual → sin cambios,
  paquete ausente → error claro, instalación desde un zip local.
- MultiHotkeyManager con eventos simulados: el chord más largo gana
  (Ctrl+Win+Shift+Espacio no dispara el de dictar), supresión, release.
- Si los paquetes reales están instalados en %LOCALAPPDATA%\\Wisip\\models,
  traduce una frase de verdad en cada sentido (se salta si no están).

Uso (desde la raíz del proyecto, con el venv):
    python scripts/check_translator.py
"""

import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import hotkeys as hk  # noqa: E402
from app import translator as tr  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


class _Ev:
    def __init__(self, name, kind):
        self.name = name
        self.event_type = kind


def main():
    print("── Oraciones ──")
    items = tr.split_sentences("Hola. ¿Cómo estás? Bien.\n\nSegundo párrafo, sin punto final")
    check("split por oración y párrafo", [s for _, s in items] == ["Hola.", "¿Cómo estás?", "Bien.", "Segundo párrafo, sin punto final"]
          and [i for i, _ in items] == [0, 0, 0, 2], str(items))
    check("join reconstruye párrafos", tr.join_sentences(items, ["Hi.", "How are you?", "Fine.", "Second paragraph"]) == "Hi. How are you? Fine.\nSecond paragraph")
    check("texto vacío", tr.split_sentences("") == [] and tr.join_sentences([], []) == "")
    check("URL con punto no se parte", [s for _, s in tr.split_sentences("Entra a wisip.ai/dashboard hoy.")] == ["Entra a wisip.ai/dashboard hoy."])

    print("── Translator sin modelo ──")
    t = tr.Translator(on_log=lambda m: None)
    check("mismo idioma → sin cambios", t.translate("Hola mundo", "es", "es") == "Hola mundo")
    check("vacío → vacío", t.translate("", "es", "en") == "")
    try:
        t.translate("hola", "fr", "en"); check("par no soportado → error", False)
    except tr.TranslationError:
        check("par no soportado → error", True)
    orig_dir = tr.MT_DIR
    tmp = Path(tempfile.mkdtemp(prefix="wisip_mt_"))
    tr.MT_DIR = tmp
    try:
        check("paquete ausente detectado", not tr.pack_installed("es-en"))
        try:
            t.translate("hola", "es", "en"); check("paquete ausente → error", False)
        except tr.TranslationError as e:
            check("paquete ausente → error", "no instalado" in str(e))
        # instalación desde zip local (archivos en subcarpeta)
        z = tmp / "fake-es-en.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in ("model.bin", "source.spm", "target.spm", "config.json"):
                zf.writestr(f"opus-mt-es-en-ct2-int8/{f}", b"x")
        import app.setup_assets as sa
        orig_dl = sa.download_file
        sa.download_file = lambda url, dest, size, *a, **k: shutil.copy(z, dest)
        orig_packs = tr.config.MT_PACKS
        tr.config.MT_PACKS = {"es-en": {"url": "http://x/y.zip", "size": 0, "sha256": None}}
        try:
            d = tr.ensure_pack("es-en", on_log=lambda m: None)
            check("zip con subcarpeta → carpeta plana instalada", tr.pack_installed("es-en") and (d / "model.bin").is_file() and not (tmp / "opus-mt-es-en.partial").exists())
        finally:
            sa.download_file = orig_dl
            tr.config.MT_PACKS = orig_packs
    finally:
        tr.MT_DIR = orig_dir
        shutil.rmtree(tmp, ignore_errors=True)

    print("── MultiHotkeyManager (eventos simulados) ──")
    fired = []
    m = hk.MultiHotkeyManager(
        on_press=lambda n: fired.append(("press", n)), on_release=lambda n: fired.append(("release", n)),
        hotkeys={"dictate": "ctrl+windows+space", "translate": "ctrl+windows+shift+space"},
    )
    m._keys = {n: hk._normalize_keys(v) for n, v in m._hotkeys.items()}
    def press(*names):
        return [m._on_event(_Ev(n, hk.keyboard.KEY_DOWN)) for n in names]
    def release(*names):
        return [m._on_event(_Ev(n, hk.keyboard.KEY_UP)) for n in names]
    import time
    press("ctrl", "windows", "shift"); r = press("space"); time.sleep(0.05)
    check("Ctrl+Win+Shift+Espacio dispara SOLO traducir", fired == [("press", "translate")], str(fired))
    check("la tecla del chord se suprime", r == [False])
    release("space", "shift", "windows", "ctrl"); time.sleep(0.05)
    check("soltar dispara release de traducir", fired[-1] == ("release", "translate"))
    fired.clear()
    press("ctrl", "windows", "space"); time.sleep(0.05)
    check("Ctrl+Win+Espacio dispara dictar", fired == [("press", "dictate")], str(fired))
    press("shift"); time.sleep(0.05)
    check("añadir shift después NO re-dispara", fired == [("press", "dictate")], str(fired))
    release("space", "windows", "ctrl", "shift"); time.sleep(0.05)
    check("release de dictar", fired[-1] == ("release", "dictate"))
    check("tecla ajena pasa", m._on_event(_Ev("a", hk.keyboard.KEY_DOWN)) is True)
    m.rebind("translate", "f9"); check("rebind cambia el chord", m.current_for("translate") == "f9" and m.current == "ctrl+windows+space")

    print("── Traducción real (si hay paquetes) ──")
    if tr.pack_installed("es-en") and tr.pack_installed("en-es"):
        t = tr.Translator(on_log=print)
        en = t.translate("Hola Andrea, te confirmo la reunión del jueves a las diez.", "es", "en")
        print("   es→en:", en)
        check("es→en menciona Thursday", "thursday" in en.lower() and "meeting" in en.lower(), en)
        es = t.translate("Please send me the report before Friday. Thanks!", "en", "es")
        print("   en→es:", es)
        check("en→es menciona viernes", "viernes" in es.lower(), es)
        mixed = t.translate("Primera frase.\nSegunda frase en otro párrafo.", "es", "en")
        check("párrafos conservados", mixed.count("\n") == 1, mixed)
    else:
        print("   (paquetes no instalados: se omite)")

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} checks fallaron: {FAILS}")
        sys.exit(1)
    print("✓ Todos los checks de traducción y atajos pasaron.")


if __name__ == "__main__":
    main()
