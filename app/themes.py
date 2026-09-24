# -*- coding: utf-8 -*-
"""Sistema de paletas de la UI de Wisip.

Cada paleta define TODOS los tokens de color que usa `app/ui.py`. El usuario
elige la paleta en el dropdown TEMA (se guarda en settings como `ui_theme`)
y la UI se reconstruye en vivo con los colores nuevos.

Regla de contraste aprendida (bug "el tab Transcribe no se ve"): CTkTabview
comparte UN solo text_color entre tabs seleccionados y no seleccionados, así
que el tab activo NO puede usar el acento brillante de fondo (texto claro
sobre lima/naranja claro = ilegible). Por eso cada paleta trae un
ACCENT_CONTAINER: versión oscura del acento para resaltar el tab activo y
los hovers de dropdown manteniendo legible el texto claro.
"""

# Tokens que toda paleta debe definir (ui.py los usa como globals).
TOKENS = (
    "BG_BASE", "BG_SURFACE", "BG_SURFACE_LOW", "BG_INPUT",
    "BG_SURFACE_HIGH", "BG_SURFACE_HIGHEST", "BORDER",
    "TEXT", "TEXT_VARIANT", "TEXT_MUTED",
    "PRIMARY", "PRIMARY_BTN", "PRIMARY_BTN_HOVER", "PRIMARY_BTN_TEXT",
    "ACCENT_CONTAINER", "ACCENT_CONTAINER_HOVER",
    "SECONDARY", "WARN", "ERROR", "ERROR_CONTAINER",
)

PALETTES = {
    # ── Negro cálido + naranja (default) ──
    "carbon_naranja": {
        "label": "Carbón + Naranja",
        "BG_BASE": "#0a0a0a",
        "BG_SURFACE": "#151515",
        "BG_SURFACE_LOW": "#101010",
        "BG_INPUT": "#050505",
        "BG_SURFACE_HIGH": "#1e1e1e",
        "BG_SURFACE_HIGHEST": "#2a2a2a",
        "BORDER": "#2a2a2a",
        "TEXT": "#f5f1ea",
        "TEXT_VARIANT": "#b8b0a4",
        "TEXT_MUTED": "#7d766c",
        "PRIMARY": "#ffb340",           # acentos de texto
        "PRIMARY_BTN": "#ff9f0a",       # botón principal
        "PRIMARY_BTN_HOVER": "#e08900",
        "PRIMARY_BTN_TEXT": "#141414",
        "ACCENT_CONTAINER": "#4a2d00",
        "ACCENT_CONTAINER_HOVER": "#5c3a00",
        "SECONDARY": "#ffd08a",
        "WARN": "#ffd60a",
        "ERROR": "#ff6b5e",
        "ERROR_CONTAINER": "#5c1f18",
    },
    # ── La paleta original del logo (lime sobre slate) ──
    "wisip_lima": {
        "label": "Wisip (Lima)",
        "BG_BASE": "#0b1326",
        "BG_SURFACE": "#171f33",
        "BG_SURFACE_LOW": "#131b2e",
        "BG_INPUT": "#060e20",
        "BG_SURFACE_HIGH": "#222a3d",
        "BG_SURFACE_HIGHEST": "#2d3449",
        "BORDER": "#2d3449",
        "TEXT": "#dae2fd",
        "TEXT_VARIANT": "#b8c2da",
        "TEXT_MUTED": "#7a8499",
        "PRIMARY": "#d4ff5a",
        "PRIMARY_BTN": "#c5ff3d",
        "PRIMARY_BTN_HOVER": "#a9e028",
        "PRIMARY_BTN_TEXT": "#0b1326",
        "ACCENT_CONTAINER": "#364a00",
        "ACCENT_CONTAINER_HOVER": "#42551a",
        "SECONDARY": "#46eaed",
        "WARN": "#f39c12",
        "ERROR": "#ffb4ab",
        "ERROR_CONTAINER": "#5c2a24",
    },
    # ── Grises puros + azul ──
    "grafito_azul": {
        "label": "Grafito + Azul",
        "BG_BASE": "#0d0d0f",
        "BG_SURFACE": "#17171a",
        "BG_SURFACE_LOW": "#121215",
        "BG_INPUT": "#070709",
        "BG_SURFACE_HIGH": "#202024",
        "BG_SURFACE_HIGHEST": "#2c2c31",
        "BORDER": "#2c2c31",
        "TEXT": "#f0f0f5",
        "TEXT_VARIANT": "#aeaeb8",
        "TEXT_MUTED": "#75757f",
        "PRIMARY": "#6db8ff",
        "PRIMARY_BTN": "#0a84ff",
        "PRIMARY_BTN_HOVER": "#0060c0",
        "PRIMARY_BTN_TEXT": "#ffffff",
        "ACCENT_CONTAINER": "#10325a",
        "ACCENT_CONTAINER_HOVER": "#143e70",
        "SECONDARY": "#64d2ff",
        "WARN": "#ffd60a",
        "ERROR": "#ff6b5e",
        "ERROR_CONTAINER": "#5c1f18",
    },
    # ── Negro + morado ──
    "negro_morado": {
        "label": "Negro + Morado",
        "BG_BASE": "#0b090e",
        "BG_SURFACE": "#161219",
        "BG_SURFACE_LOW": "#110e14",
        "BG_INPUT": "#060409",
        "BG_SURFACE_HIGH": "#1f1a24",
        "BG_SURFACE_HIGHEST": "#2b2432",
        "BORDER": "#2b2432",
        "TEXT": "#f2ecf7",
        "TEXT_VARIANT": "#b3aabd",
        "TEXT_MUTED": "#78707f",
        "PRIMARY": "#d7a8ff",
        "PRIMARY_BTN": "#bf5af2",
        "PRIMARY_BTN_HOVER": "#a844e0",
        "PRIMARY_BTN_TEXT": "#1c0b26",
        "ACCENT_CONTAINER": "#3a1f52",
        "ACCENT_CONTAINER_HOVER": "#472763",
        "SECONDARY": "#cfa9ff",
        "WARN": "#ffd60a",
        "ERROR": "#ff6b5e",
        "ERROR_CONTAINER": "#5c1f18",
    },
}

DEFAULT_THEME = "carbon_naranja"

THEME_KEYS = list(PALETTES.keys())
THEME_LABELS = {k: p["label"] for k, p in PALETTES.items()}
LABEL_TO_KEY = {p["label"]: k for k, p in PALETTES.items()}


def get_palette(key: str) -> dict:
    """Devuelve la paleta pedida (o la default si la clave no existe)."""
    return PALETTES.get(key, PALETTES[DEFAULT_THEME])
