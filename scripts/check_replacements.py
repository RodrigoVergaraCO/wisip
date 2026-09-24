"""Valida el pipeline de reemplazos sin grabar voz.

Corre frases de prueba por Replacements.apply() e imprime entrada → salida y
qué reemplazos se aplicaron. Útil para verificar que:
  - los términos técnicos y nombres propios se corrigen,
  - emails/URLs se rearman,
  - el español/inglés normal NO se rompe.

Uso (desde la raíz del proyecto, con el venv activo):
    python scripts\\check_replacements.py
"""

import sys
from pathlib import Path

# La consola de Windows suele ser cp1252 y no imprime '→'. Forzamos UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Permite ejecutar el script directamente (añade la raíz del proyecto al path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.replacements import Replacements  # noqa: E402


# (entrada, fragmento_esperado_en_salida | None). None = solo informativo.
CASES = [
    # --- deben mejorar (fase 1) ---
    ("Estoy creando una aplicación en Python que usa Whisper, fast raja whisper, "
     "sound device, custom tkinter, pi outlook guy, piper clip y un hotcake global.",
     "faster-whisper"),
    ("Mi correo es juanperez arroba hotmail punto com.",
     "juanperez@hotmail.com"),
    ("Mi correo es juanperez arroba jodmail punto com.",
     "juanperez@hotmail.com"),
    ("También puedo dictar una URL como wisip punto ai slash dashboard.",
     "wisip.ai/dashboard"),
    ("api punto wisip punto co slash v1 slash users",
     "api.wisip.co/v1/users"),
    ("w w w punto wisip punto ai slash dashboard",
     "www.wisip.ai/dashboard"),
    ("quiero revisar el modelo, el micrófono, el idioma, del bad, del initial prompt "
     "y de los reemplazos.",
     "VAD"),
    ("el problema viene del v a d o de los segmentos de wisper.",
     "VAD"),
    # --- deben mejorar (fase 2: degradados por el modelo) ---
    ("estoy en Python con custom thinker, pyautogui y pyperclip.", "CustomTkinter"),
    ("React next.js y note.js", "Node.js"),
    ("que Wism no se corte cuando diga inglés.", "Wisip"),
    ("Mi correo puede ser juanperezarroba.hotmail.com.",
     "juanperez@hotmail.com"),
    ("una URL como wisip.ai-dashboard", "wisip.ai/dashboard"),
    ("ap.Wisip.cov-v1-users", "api.wisip.co/v1/users"),
    # --- deben mejorar (fase 3: registro 2026-08-03, confirmados por el usuario) ---
    ("El 99.9% de estas mincoins van a ir a cero, igual que las MIMCOINS "
     "y las meme toins.", "memecoins"),
    ("Se genera en el archivo PC de verdad con todas las capas.", "archivo PSD"),
    ("Algo como una mejor Wii UX que salga en la mitad.", "UI UX"),
    ("Lo que vamos a aleatoriezar es la posición uno.", "aleatorizar"),
    ("Quiero ver el pnln de los trades cerrados.", "PNL"),
    ("Eso puede ser un rookpool de esos de cripto.", "rug pull"),
    ("Puedes scrapear wallets de leaders boards públicos.", "leaderboards"),
    ("Kimmy va a manejar su effort en Extra High.", "Kimi"),
    ("Necesito la apik para conectar el servicio.", "API key"),
    ("Copia el AppKey en el panel de configuración.", "API key"),
    ("Abre el ScreenenViewer para revisar la sesión.", "ScreenViewer"),
    # --- registro 2026-09-23 (marcas en minúscula, garbles inambiguos) ---
    ("La app de amazon me manda el código al gmail.", "app de Amazon"),
    ("La app de amazon me manda el código al gmail.", "al Gmail"),
    ("Voy a subirlo a github y a youtube.", "GitHub"),
    ("Voy a subirlo a github y a youtube.", "YouTube"),
    ("El emulador bluestack no arranca con play protect.", "BlueStacks"),
    ("El emulador bluestack no arranca con play protect.", "Play Protect"),
    ("La cuenta fue apelada chitosamente.", "exitosamente"),
    ("Hay que premir el botón de confirmar.", "oprimir"),
    ("Ese workhook no debería salir.", "webhook"),
    ("Lo hice con un agente de antropik.", "Anthropic"),
    ("Necesito la apikey del panel.", "API key"),
    # Los correos/hosts van enmascarados: el diccionario NO los toca.
    ("Escríbeme a juan@gmail.com o entra a amazon.com.", "juan@gmail.com"),
    ("Escríbeme a juan@gmail.com o entra a amazon.com.", "amazon.com"),
    # --- NO deben romperse (español/inglés normal) ---
    ("Mi PC nuevo corre el modelo sin problema.", None),
    ("Vamos directo al punto importante de la reunión.", None),
    ("Hay dos puntos clave en el guion de la película.", None),
    ("The submit button is bad and the payload is wrong.", None),
    ("La firma auténtica se valida en el backend.", None),
    ("Tengo una arquitectura cliente-servidor con micro-servicios.", None),
    ("La sección actual del documento tiene dos puntos pendientes.", None),
]


def main():
    r = Replacements(on_log=lambda m: None)
    ok = 0
    for text, expected in CASES:
        out, applied = r.apply(text)
        status = ""
        if expected is not None:
            passed = expected in out
            ok += int(passed)
            status = "  [OK]" if passed else f"  [FALTA: {expected!r}]"
        print("IN :", text)
        print("OUT:", out + status)
        if applied:
            print("    aplicados:", applied)
        print("-" * 80)
    total = sum(1 for _, e in CASES if e is not None)
    print(f"\nCasos con expectativa cumplidos: {ok}/{total}")
    print("Revisa manualmente los casos 'NO deben romperse' (expected=None):")
    print("  - 'Mi PC nuevo' debe quedar igual (solo 'archivo PC' se vuelve PSD).")
    print("  - 'punto importante' debe seguir siendo texto normal (no '.importante').")
    print("  - 'dos puntos' y 'guion' NO deben volverse ':' ni '-' (salvo tech_mode).")
    print("  - 'button is bad' NO debe volverse 'VAD' (no hay contexto técnico).")
    print("  - 'auténtica se' debe quedarse igual (no 'autenticación').")
    if ok < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
