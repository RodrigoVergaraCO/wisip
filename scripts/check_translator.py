# -*- coding: utf-8 -*-
"""Valida la traducción local (app/translator.py) y los atajos múltiples
(app/hotkeys.MultiHotkeyManager) sin hardware ni red.

- split/join de oraciones y párrafos, idioma igual → sin cambios,
  paquete ausente → error claro, instalación desde un zip local.
- MultiHotkeyManager con eventos simulados: el chord más largo gana
  (Ctrl+Win+Shift no dispara el de dictar), supresión, release, cambio de
  chord sin soltar (Ctrl+Win → +Shift), tecla fantasma anti-menú Inicio,
  y chords personalizados con tecla normal (Ctrl+Win+Espacio).
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
    def __init__(self, name, kind, scan=None):
        self.name = name
        self.event_type = kind
        self.scan_code = scan


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
    import time
    masked = []
    orig_mask = hk._mask_win_key
    hk._mask_win_key = lambda: masked.append(1)
    fired = []
    m = hk.MultiHotkeyManager(
        on_press=lambda n: fired.append(("press", n)), on_release=lambda n: fired.append(("release", n)),
        on_switch=lambda a, b: fired.append(("switch", a, b)),
        hotkeys={"dictate": tr.config.DEFAULT_HOTKEY, "translate": tr.config.DEFAULT_HOTKEY_TRANSLATE},
    )
    check("defaults sin Espacio", "space" not in tr.config.DEFAULT_HOTKEY and "space" not in tr.config.DEFAULT_HOTKEY_TRANSLATE)
    m._keys = {n: hk._normalize_keys(v) for n, v in m._hotkeys.items()}
    def press(*names):
        return [m._on_event(_Ev(n, hk.keyboard.KEY_DOWN)) for n in names]
    def release(*names):
        return [m._on_event(_Ev(n, hk.keyboard.KEY_UP)) for n in names]
    try:
        # 1) Ctrl+Win dispara dictar; la tecla que completa el chord se suprime.
        r = press("ctrl", "windows"); time.sleep(0.05)
        check("Ctrl+Win dispara dictar", fired == [("press", "dictate")], str(fired))
        check("ctrl pasa, windows (completa el chord) se suprime", r == [True, False], str(r))
        check("tecla fantasma inyectada (chord con Win)", masked == [1], str(masked))
        # 2) Añadir Shift sin soltar → cambio a traducir, sin release ni press nuevo.
        r = press("shift"); time.sleep(0.05)
        check("añadir Shift cambia a traducir sin soltar", fired == [("press", "dictate"), ("switch", "dictate", "translate")], str(fired))
        check("shift del chord activo se suprime", r == [False], str(r))
        # 3) Soltar cualquier tecla del chord activo termina.
        release("shift"); time.sleep(0.05)
        check("soltar shift → release de traducir", fired[-1] == ("release", "translate"), str(fired))
        release("windows", "ctrl"); time.sleep(0.05)
        check("soltar el resto no dispara nada más", fired[-1] == ("release", "translate") and len(fired) == 3, str(fired))
        # 4) Orden libre: Shift primero → dispara SOLO traducir.
        fired.clear(); masked.clear()
        press("shift", "windows", "ctrl"); time.sleep(0.05)
        check("Shift+Win+Ctrl (orden libre) dispara SOLO traducir", fired == [("press", "translate")], str(fired))
        release("ctrl", "windows", "shift"); time.sleep(0.05)
        check("release de traducir", fired[-1] == ("release", "translate"))
        check("tecla ajena pasa", m._on_event(_Ev("a", hk.keyboard.KEY_DOWN)) is True)
        # 5) Chords personalizados con tecla normal siguen funcionando.
        fired.clear(); masked.clear()
        m.rebind("dictate", "ctrl+windows+space"); m.rebind("translate", "ctrl+windows+shift+space")
        m._keys = {n: hk._normalize_keys(v) for n, v in m._hotkeys.items()}
        press("ctrl", "windows", "shift"); r = press("space"); time.sleep(0.05)
        check("Ctrl+Win+Shift+Espacio dispara SOLO traducir", fired == [("press", "translate")], str(fired))
        check("la barra se suprime", r == [False])
        release("space", "shift", "windows", "ctrl"); time.sleep(0.05)
        fired.clear()
        press("ctrl", "windows", "space"); time.sleep(0.05)
        check("Ctrl+Win+Espacio dispara dictar", fired == [("press", "dictate")], str(fired))
        release("space", "windows", "ctrl"); time.sleep(0.05)
        check("release de dictar", fired[-1] == ("release", "dictate"))
        # 6) Chord sin Win/Alt no inyecta tecla fantasma; stop deja _fired en None.
        masked.clear(); fired.clear()
        m.rebind("translate", "f9"); m._keys = {n: hk._normalize_keys(v) for n, v in m._hotkeys.items()}
        press("f9"); time.sleep(0.05); release("f9"); time.sleep(0.05)
        check("F9 dispara y no inyecta fantasma", fired == [("press", "translate"), ("release", "translate")] and masked == [], str((fired, masked)))
        check("rebind cambia el chord", m.current_for("translate") == "f9" and m.current == "ctrl+windows+space")
        m.stop(); check("stop deja el chord activo en None", m._fired is None)
        # 7) Windows en español: la librería nombra las teclas "windows izquierda",
        #    "mayusculas"… El gestor reconoce los modificadores por SCAN CODE.
        m.rebind("dictate", "ctrl+windows"); m.rebind("translate", "ctrl+windows+shift")
        m._keys = {n: hk._normalize_keys(v) for n, v in m._hotkeys.items()}
        fired.clear(); masked.clear()
        r = [m._on_event(_Ev("ctrl", hk.keyboard.KEY_DOWN, scan=29)),
             m._on_event(_Ev("windows izquierda", hk.keyboard.KEY_DOWN, scan=91)),
             m._on_event(_Ev("mayusculas", hk.keyboard.KEY_DOWN, scan=42))]; time.sleep(0.05)
        check("teclas físicas con nombre en español disparan (scan code)",
              fired == [("press", "dictate"), ("switch", "dictate", "translate")] and r == [True, False, False], str((fired, r)))
        m._on_event(_Ev("mayusculas", hk.keyboard.KEY_UP, scan=42)); time.sleep(0.05)
        check("soltar 'mayusculas' (scan 42) libera", fired[-1] == ("release", "translate"), str(fired))
        m._on_event(_Ev("windows izquierda", hk.keyboard.KEY_UP, scan=91)); m._on_event(_Ev("ctrl", hk.keyboard.KEY_UP, scan=29))
        fired.clear()
        press("windows derecha", "ctrl"); time.sleep(0.05)   # sin scan code: alias por nombre
        check("alias 'windows derecha' sin scan code", fired == [("press", "dictate")], str(fired))
        release("ctrl", "windows derecha"); time.sleep(0.05)
        check("canonical_hotkey('ctrl+mayusculas+windows izquierda') == 'ctrl+shift+windows'",
              hk.canonical_hotkey("ctrl+mayusculas+windows izquierda") == "ctrl+shift+windows", hk.canonical_hotkey("ctrl+mayusculas+windows izquierda"))
        check("canonical_hotkey('Mayús+Bloq Mayús') == 'shift+capslock'",
              hk.canonical_hotkey("Mayús+Bloq Mayús") == "shift+capslock", hk.canonical_hotkey("Mayús+Bloq Mayús"))
        check("canonical_hotkey('|') == '|'", hk.canonical_hotkey("|") == "|")
        m.stop()
    finally:
        hk._mask_win_key = orig_mask

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
