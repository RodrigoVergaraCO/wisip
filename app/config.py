import glob
import os
import sys
import sysconfig
from pathlib import Path

# Silencia el warning de huggingface_hub sobre symlinks en Windows (cosmético).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# IMPORTANTE: os.add_dll_directory devuelve un handle que, al ser recolectado
# por el GC, QUITA el directorio del path de búsqueda de DLLs. Hay que mantener
# vivos esos handles durante toda la vida del proceso, o cuBLAS/cuDNN "desaparecen"
# justo cuando faster-whisper intenta cargarlos en GPU.
_CUDA_DLL_COOKIES: list = []
# Directorios <lib>/bin registrados (para saber si las DLLs CUDA existen de
# verdad: `get_cuda_device_count()` responde con solo el driver instalado).
CUDA_DLL_DIRS: list = []

# ─── Paquete de aceleración NVIDIA descargable ──────────────────────────
# Desde la 2.7.0 el instalador NO lleva las DLLs CUDA (1,9 GB). Si hay una
# GPU NVIDIA, la app ofrece descargarlas una vez a esta carpeta (misma
# estructura que los wheels de PyPI: <lib>/bin/*.dll) y las carga desde ahí.
GPU_PACK_DIR = Path(
    os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
) / "Wisip" / "cuda"
GPU_PACK_MANIFEST = GPU_PACK_DIR / "pack.json"
# Cambiar si se actualiza ctranslate2 a otra serie de CUDA/cuDNN: invalida el
# paquete instalado y se vuelve a ofrecer la descarga.
GPU_PACK_VERSION = "cu12.9-cudnn9.23-ct2-4.8"
# Wheels oficiales de NVIDIA en PyPI (mismas versiones que el venv de
# desarrollo, probadas con ctranslate2 4.8.0). Solo se extraen los .dll de
# <lib>/bin; el sha256 es el publicado por PyPI y se verifica al descargar
# el archivo completo (modo sin rangos) — en modo por rangos se verifica el
# CRC32 de cada DLL contra la tabla central del zip.
NVIDIA_WHEELS = (
    {"name": "nvidia-cuda-runtime-cu12", "version": "12.9.79", "lib": "cuda_runtime",
     "sha256": "8e018af8fa02363876860388bd10ccb89eb9ab8fb0aa749aaf58430a9f7c4891"},
    {"name": "nvidia-cublas-cu12", "version": "12.9.2.10", "lib": "cublas",
     "sha256": "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"},
    {"name": "nvidia-cudnn-cu12", "version": "9.23.2.1", "lib": "cudnn",
     "sha256": "549d6eb120cdd89429997243cd2cad1e864aac3a2f887a93f17836ce72d83873"},
    {"name": "nvidia-cuda-nvrtc-cu12", "version": "12.9.86", "lib": "cuda_nvrtc",
     "sha256": "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349"},
)
# DLLs que faster-whisper/CTranslate2 NO usan (verificado cargando el modelo
# en GPU sin ellas, 2026-09-23). Se omiten para ahorrar descarga y disco.
# Se conservan nvrtc y los "engines" de cuDNN: son el compilador/kernels de
# respaldo para GPUs donde no hay kernel precompilado.
GPU_PACK_EXCLUDE_DLLS = ("cudnn_adv64", "nvblas")
# Tamaño aproximado de la descarga (para el mensaje al usuario).
GPU_PACK_DOWNLOAD_MB = 1200
# ─── Licencias (2.9.0): Lemon Squeezy License API ──────────────────────
# Endpoints públicos (no requieren API key). Cambiable en pruebas con la
# variable de entorno WISIP_LICENSE_API.
LICENSE_API_BASE = "https://api.lemonsqueezy.com/v1/licenses"
TRIAL_DAYS = 30                    # prueba gratuita desde el primer arranque
LICENSE_REVALIDATE_DAYS = 30       # cada cuánto se consulta /validate
LICENSE_OFFLINE_GRACE_DAYS = 90    # sin poder validar más de esto → bloquea
# Página de compra (ponerla cuando exista la tienda; hasta entonces el botón
# lleva al repositorio).
BUY_URL = "https://github.com/acropolifamily-web/wisip#license"

# Tamaño aproximado de cada modelo (descarga inicial).
MODEL_DOWNLOAD_MB = {
    "tiny": 75, "base": 145, "small": 480, "medium": 1500,
    "large-v3-turbo": 1600, "large-v3": 3100,
}


def register_cuda_dir(root) -> int:
    """Añade <root>/*/bin al buscador de DLLs (en caliente, p.ej. tras
    descargar el paquete NVIDIA). Devuelve cuántos directorios añadió."""
    n = 0
    if sys.platform != "win32":
        return 0
    for bindir in glob.glob(os.path.join(str(root), "*", "bin")):
        if not os.path.isdir(bindir):
            continue
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        try:
            _CUDA_DLL_COOKIES.append(os.add_dll_directory(bindir))
            CUDA_DLL_DIRS.append(bindir)
            n += 1
        except Exception:
            pass
    return n


_CUDA_REQUIRED_DLLS = ("cublas64_12.dll", "cudnn64_9.dll", "cudart64_12.dll")


def cuda_dlls_present() -> bool:
    """True si las DLLs CUDA que necesita CTranslate2 están en alguno de los
    directorios registrados. OJO: `ctranslate2.get_cuda_device_count()` da 1
    con solo el driver NVIDIA instalado, aunque falten cuBLAS/cuDNN (entonces
    la carga del modelo en GPU falla y se cae a CPU)."""
    found = set()
    for d in CUDA_DLL_DIRS:
        try:
            for f in os.listdir(d):
                if f.lower() in _CUDA_REQUIRED_DLLS:
                    found.add(f.lower())
        except Exception:
            continue
    return all(x in found for x in _CUDA_REQUIRED_DLLS)


def _setup_cuda_dll_path() -> bool:
    """Pone en el PATH de búsqueda de Windows las DLLs CUDA instaladas vía pip
    (nvidia-cublas-cu12 / nvidia-cudnn-cu12 / nvidia-cuda-runtime-cu12), que
    viven en site-packages/nvidia/*/bin pero NO están en el PATH por defecto.

    Debe correr ANTES de importar faster_whisper/ctranslate2. Es no-op si esas
    libs no están instaladas (build CPU): en ese caso device='auto' usará CPU.

    Devuelve True si encontró al menos un directorio de DLLs CUDA.
    """
    if sys.platform != "win32":
        return False
    found = False
    try:
        candidates = []
        # site-packages estándar + el del .exe empaquetado.
        try:
            candidates.append(os.path.join(sysconfig.get_paths()["purelib"], "nvidia"))
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            # PyInstaller --onedir deja los datas en _internal (= _MEIPASS).
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(os.path.join(meipass, "nvidia"))
            candidates.append(os.path.join(os.path.dirname(sys.executable), "nvidia"))
        # Paquete NVIDIA descargado desde la app (2.7.0+). Va al final: si el
        # build o el venv ya traen DLLs, esas mandan.
        candidates.append(str(GPU_PACK_DIR))
        for nv in candidates:
            for bindir in glob.glob(os.path.join(nv, "*", "bin")):
                if not os.path.isdir(bindir):
                    continue
                os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
                try:
                    # Guardamos el cookie para que el directorio NO se quite cuando
                    # el GC corra (esa era la causa de 'cublas64_12.dll not found').
                    _CUDA_DLL_COOKIES.append(os.add_dll_directory(bindir))
                    CUDA_DLL_DIRS.append(bindir)
                except Exception:
                    pass
                found = True
    except Exception:
        pass
    return found


# Ejecutar en import, antes de que transcriber.py importe faster_whisper.
CUDA_DLLS_ON_PATH = _setup_cuda_dll_path()

# Nombre interno (queda igual para no romper %APPDATA%\local-voice-typer\).
# El branding visible en ventana / taskbar / instalador es "Wisip".
APP_NAME = "Local Voice Typer"
APP_DIR_NAME = "local-voice-typer"
APP_BRAND = "Wisip"

# AppUserModelID: identifica el proceso en la barra de tareas de Windows. Se
# setea desde main.py ANTES de crear la ventana Tk para que la taskbar agrupe
# como Wisip (con icono propio) y no como "Python".
APP_USER_MODEL_ID = "com.wisip.app"


def _resource_dir() -> Path:
    """Carpeta raíz donde están los recursos (icon.png, logo.png, assets/).

    En desarrollo: la raíz del proyecto (parent de la carpeta `app/`).
    Empacado con PyInstaller (`--onedir`): la carpeta `_MEIPASS` que el
    bootloader crea al arrancar.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# Asset paths
PROJECT_ROOT = _resource_dir()
LOGO_PATH = PROJECT_ROOT / "logo.png"
ICON_PATH = PROJECT_ROOT / "icon.png"
ASSETS_DIR = PROJECT_ROOT / "assets"
ICO_PATH = ASSETS_DIR / "icon.ico"

# Whisper defaults (se usan cuando app_settings.json no existe todavía)
# small: mejor equilibrio en CPU. large-v3-turbo: calidad de large-v3 con
# decodificación ~6x más rápida; en GPU NVIDIA es a la vez el más preciso y
# más rápido que small (el Controller migra a él automáticamente si hay GPU,
# ver _autotune_perf_profile en main.py).
DEFAULT_MODEL = "small"
GPU_RECOMMENDED_MODEL = "large-v3-turbo"
AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]
MODEL_HINTS = {
    "tiny":   "muy rápido, calidad básica",
    "base":   "rápido y decente",
    "small":  "mejor calidad en CPU",
    "medium": "mucha mejor calidad, pesado en CPU",
    "large-v3-turbo": "máxima calidad · requiere GPU NVIDIA (rapidísimo ahí)",
}
LANGUAGE = "es"
TASK = "transcribe"

# Opciones de idioma para la UI.
# "auto" → faster-whisper detecta el idioma (language=None).
LANGUAGE_LABEL_ES = "Español"
LANGUAGE_LABEL_EN = "Inglés"
LANGUAGE_LABEL_AUTO = "Auto"
LANGUAGE_LABELS = [LANGUAGE_LABEL_ES, LANGUAGE_LABEL_EN, LANGUAGE_LABEL_AUTO]
LANGUAGE_LABEL_TO_CODE = {
    LANGUAGE_LABEL_ES: "es",
    LANGUAGE_LABEL_EN: "en",
    LANGUAGE_LABEL_AUTO: "auto",
}
LANGUAGE_CODE_TO_LABEL = {v: k for k, v in LANGUAGE_LABEL_TO_CODE.items()}
LANGUAGE_CODES = ["es", "en", "auto"]
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# ─── Rendimiento: device / compute / batching ───────────────────────────
# device: "auto" (intenta CUDA con warmup → fallback CPU), "cpu" o "cuda".
DEFAULT_DEVICE = "auto"
VALID_DEVICES = ["auto", "cpu", "cuda"]
# compute_type: además de los existentes, "auto" → float16 en GPU / int8 en CPU.
DEFAULT_CPU_THREADS = 0          # 0 = CTranslate2 decide (usa todos los núcleos)
DEFAULT_NUM_WORKERS = 1
DEFAULT_ENABLE_GPU_IF_AVAILABLE = True
# Compute recomendado por device cuando compute_type="auto".
GPU_COMPUTE_DEFAULT = "float16"          # máxima calidad/velocidad en GPU
GPU_COMPUTE_LOW_VRAM = "int8_float16"    # alternativa si falta VRAM
CPU_COMPUTE_DEFAULT = "int8"

# Batched inference (faster-whisper). Mismos parámetros (beam/best_of/prompt) →
# misma calidad, más rápido en audio largo. Opt-in por perfil de rendimiento.
DEFAULT_BATCHED = False
DEFAULT_BATCH_SIZE = 8
MAX_SPEED_BATCH_SIZE = 16

# Transcripción incremental por chunks (IMPLEMENTADA, app/incremental.py):
# mientras grabas, un worker transcribe en segundo plano los tramos ya
# hablados, cortando SOLO en silencios (nunca a mitad de palabra, por eso no
# hay solape ni deduplicación). Al soltar la tecla solo queda el último tramo
# → la espera final es de ~1-2s sin importar cuánto dictaste.
DEFAULT_INCREMENTAL_TRANSCRIPTION = True
# Un tramo se cierra cuando acumula al menos MIN_CHUNK segundos Y termina en
# un silencio de SILENCE_SECONDS. CHUNK_SECONDS actúa de tope duro: si no hay
# silencio en mucho rato, no se corta (se espera al siguiente silencio).
INCREMENTAL_MIN_CHUNK_SECONDS = 6.0
INCREMENTAL_SILENCE_SECONDS = 0.45
# RMS (sobre float32 [-1,1]) por debajo del cual un bloque se considera
# silencio. Voz típica ronda 0.01–0.1; ruido de fondo de micro ~0.001–0.005.
INCREMENTAL_SILENCE_RMS = 0.006
DEFAULT_CHUNK_SECONDS = 15
DEFAULT_CHUNK_OVERLAP_SECONDS = 1.0

# ─── Perfiles de rendimiento ────────────────────────────────────────────
# Distintos de los perfiles de CALIDAD (que tocan modelo/beam). Estos solo
# tocan device/compute/batching, sin bajar la precisión.
PERF_PROFILE_QUALITY = "quality_current"   # idéntico a hoy (cpu int8 secuencial)
PERF_PROFILE_FAST_SAFE = "fast_safe"       # device auto + batched (calidad equivalente)
PERF_PROFILE_MAX_SPEED = "max_speed"       # GPU float16 + batched + batch grande
PERF_PROFILE_CUSTOM = "perf_custom"        # usa device/compute_type crudos de settings

PERF_PROFILES = {
    PERF_PROFILE_QUALITY:   {"device": "cpu",  "compute_type": "int8", "batched": False, "batch_size": DEFAULT_BATCH_SIZE},
    PERF_PROFILE_FAST_SAFE: {"device": "auto", "compute_type": "auto", "batched": True,  "batch_size": DEFAULT_BATCH_SIZE},
    PERF_PROFILE_MAX_SPEED: {"device": "auto", "compute_type": "auto", "batched": True,  "batch_size": MAX_SPEED_BATCH_SIZE},
}
PERF_PROFILE_LABELS = {
    PERF_PROFILE_QUALITY:   "Calidad actual",
    PERF_PROFILE_FAST_SAFE: "Rápido seguro",
    PERF_PROFILE_MAX_SPEED: "Máxima velocidad local",
    PERF_PROFILE_CUSTOM:    "Personalizado",
}
PERF_PROFILE_LABEL_TO_KEY = {v: k for k, v in PERF_PROFILE_LABELS.items()}
PERF_PROFILE_DESCRIPTIONS = {
    PERF_PROFILE_QUALITY:   "CPU int8 secuencial · idéntico a hoy (cero cambios)",
    PERF_PROFILE_FAST_SAFE: "GPU si hay (float16) o CPU · batched · misma calidad, más rápido",
    PERF_PROFILE_MAX_SPEED: "GPU float16 + batched grande · máxima velocidad local",
    PERF_PROFILE_CUSTOM:    "Usa device/compute_type del app_settings.json",
}
PERF_PROFILE_KEYS = list(PERF_PROFILES.keys()) + [PERF_PROFILE_CUSTOM]
# Default = "Rápido seguro": usa GPU (float16) si hay y cae a CPU (int8 batched)
# si no, con calidad equivalente. En equipos con GPU NVIDIA esto baja la latencia
# de ~4s a ~0.3s por frase. Para instalaciones ya existentes, el Controller migra
# una sola vez desde el antiguo default (ver _autotune_perf_profile en main.py).
DEFAULT_PERF_PROFILE = PERF_PROFILE_FAST_SAFE


def resolve_compute_for_device(device: str, compute_type: str) -> str:
    """Resuelve compute_type='auto' según el device real."""
    if compute_type and compute_type != "auto":
        return compute_type
    return GPU_COMPUTE_DEFAULT if device == "cuda" else CPU_COMPUTE_DEFAULT
# beam_size: 5 es el default de Whisper. Mejor calidad, ~2x más lento que
# greedy (beam_size=1). Greedy producía sílabas sueltas ("y y y") en audio
# con volumen bajo — no vale la pena el ahorro de tiempo.
BEAM_SIZE = 5

# Defaults avanzados de Whisper, configurables desde app_settings.json.
DEFAULT_BEAM_SIZE = 5
DEFAULT_BEST_OF = 5
DEFAULT_TEMPERATURE = 0.0
DEFAULT_VAD_FILTER = True
DEFAULT_CONDITION_ON_PREVIOUS_TEXT = False
DEFAULT_INITIAL_PROMPT_ENABLED = True
# Prompts anteriores. Se conservan para detectar usuarios que aún tienen un
# default antiguo guardado y migrarlos al nuevo.
OLD_DEFAULT_INITIAL_PROMPT = (
    "Transcripción de dictado técnico en español e inglés. "
    "Términos frecuentes: ChatGPT, GPT, Claude, n8n, JSON, MongoDB, Python, "
    "JavaScript, React, API, webhook, VPS, Docker, Coolify, Wasender, "
    "Shopify, Rappi, WhatsApp."
)
# Prompt anterior bilingüe (sin anchors para wisip/email providers/símbolos).
MID_DEFAULT_INITIAL_PROMPT = (
    "Transcripción de dictado técnico en español e inglés. El usuario suele "
    "mezclar español con palabras técnicas en inglés. No traduzcas. Transcribe "
    "literalmente. Términos frecuentes: ChatGPT, GPT, Claude, Whisper, Python, "
    "JavaScript, TypeScript, React, Next.js, Node.js, API, webhook, fetch, "
    "endpoint, JSON, MongoDB, Docker, Coolify, VPS, n8n, Shopify, WhatsApp, "
    "Rappi, SaaS, dashboard, login, backend, frontend, database."
)
# Prompt anterior v3 (se conserva para migrar usuarios que lo tengan guardado
# al nuevo v4, que añade faster-whisper/sounddevice/CustomTkinter/pyautogui/
# pyperclip/VAD/payload/Wasender, etc.).
V3_DEFAULT_INITIAL_PROMPT = (
    "Dictado técnico ES/EN. NO TRADUZCAS. Transcribe literalmente en el "
    "idioma original; mantén términos en inglés tal como suenan. Marca, sitio "
    "y producto: Wisip, wisip.ai, wisip.com.co. Términos: ChatGPT, GPT, "
    "Claude, Whisper, Python, JavaScript, TypeScript, React, Next.js, Node.js, "
    "npm, API, endpoint, webhook, fetch, users, JSON, MongoDB, Docker, "
    "Coolify, VPS, n8n, Shopify, WhatsApp, Rappi, SaaS, dashboard, login, "
    "backend, frontend, database. Símbolos hablados: arroba, punto, slash, "
    "guion. Proveedores de email: Hotmail, Gmail, Outlook, Yahoo, iCloud, "
    "ProtonMail."
)
# Prompt v4 (se conserva para migrar al v5, que añade ejemplos de correos/URLs
# y ancla palabras homófonas frecuentes como "sesión"/"autenticación").
V4_DEFAULT_INITIAL_PROMPT = (
    "Transcripción de dictado técnico en español e inglés. El usuario habla "
    "rápido y mezcla español con palabras técnicas en inglés. No traduzcas. "
    "Transcribe literalmente todo lo dicho. Mantén correctamente escritos "
    "estos términos: Wisip, ChatGPT, GPT, Claude, Whisper, faster-whisper, "
    "sounddevice, CustomTkinter, pyautogui, pyperclip, Python, JavaScript, "
    "TypeScript, React, Next.js, Node.js, npm, API, webhook, endpoint, fetch, "
    "payload, dashboard, login, backend, frontend, JSON, MongoDB, Docker, "
    "Coolify, VPS, VAD, n8n, Shopify, WhatsApp, Wasender, Rappi, SaaS. "
    "Sitio: wisip.ai, wisip.com.co. Símbolos hablados: arroba, punto, slash, "
    "guion. Proveedores de email: Hotmail, Gmail, Outlook, Yahoo, iCloud, "
    "ProtonMail."
)
# Prompt v5 (contenía un correo personal de ejemplo). Se conserva SOLO para
# migrar a quienes lo tengan guardado al v6 genérico (sin PII).
V5_DEFAULT_INITIAL_PROMPT = (
    "Transcripción de dictado técnico en español e inglés. El usuario habla "
    "rápido y mezcla español con términos técnicos en inglés. No traduzcas. "
    "Transcribe literalmente. Mantén correctamente escritos estos términos: "
    "Wisip, ChatGPT, GPT, Claude, Whisper, faster-whisper, sounddevice, "
    "CustomTkinter, pyautogui, pyperclip, Python, JavaScript, TypeScript, "
    "React, Next.js, Node.js, API, webhook, endpoint, fetch, payload, "
    "dashboard, login, backend, frontend, JSON, MongoDB, Docker, Coolify, "
    "VPS, VAD, n8n, Shopify, WhatsApp, Wasender, Rappi, SaaS. El usuario puede "
    "dictar correos, dominios y rutas como usuario@dominio.com, "
    "wisip.ai/dashboard y api.wisip.co/v1/users. Palabras frecuentes: sesión, "
    "autenticación."
)
# Prompt v6 (anterior): contenía instrucciones ("No traduzcas...") que Whisper
# NO obedece — el initial_prompt solo funciona como contexto/vocabulario, y el
# estilo instrucción a veces se filtraba al output y sesgaba a EN. Se conserva
# para migrar a quienes lo tengan guardado al v7.
V6_DEFAULT_INITIAL_PROMPT = (
    "Transcripción de dictado técnico en español e inglés. El usuario habla "
    "rápido y mezcla español con términos técnicos en inglés. No traduzcas. "
    "Transcribe literalmente. Mantén correctamente escritos estos términos: "
    "Wisip, ChatGPT, GPT, Claude, Whisper, faster-whisper, sounddevice, "
    "CustomTkinter, pyautogui, pyperclip, Python, JavaScript, TypeScript, "
    "React, Next.js, Node.js, API, webhook, endpoint, fetch, payload, "
    "dashboard, login, backend, frontend, JSON, MongoDB, Docker, Coolify, "
    "VPS, VAD, n8n, Shopify, WhatsApp, Wasender, Rappi, SaaS. El usuario puede "
    "dictar correos, dominios y rutas como usuario@dominio.com, "
    "ejemplo.com/dashboard y api.ejemplo.com/v1/users. Palabras frecuentes: "
    "sesión, autenticación."
)
# Prompt v7 (anterior): estilo transcripción pero como LISTADO de términos.
# Se conserva para migrar al v8, que además DEMUESTRA el code-switching
# (términos EN dentro de frases ES se quedan en inglés).
V7_DEFAULT_INITIAL_PROMPT = (
    "Estoy dictando en español sobre Wisip, mi app de dictado hecha con "
    "Whisper, faster-whisper, sounddevice, CustomTkinter, pyautogui y "
    "pyperclip. Trabajo con Python, JavaScript, TypeScript, React, Next.js, "
    "Node.js, JSON, MongoDB, Docker, Coolify, VPS, VAD, n8n, Shopify, "
    "WhatsApp, Wasender, Rappi y ChatGPT. El backend expone una API con "
    "endpoints, webhooks, fetch, payload, login, dashboard, sesión y "
    "autenticación. Mi correo es usuario@dominio.com y el sitio es "
    "wisip.ai/dashboard, también api.ejemplo.com/v1/users."
)
# Prompt v8 (anterior). Su cola "Palabras frecuentes: ..." era un encabezado
# de lista y Whisper lo RECITABA dentro del dictado (eco del prompt: "Palabras
# frecuentes." apareció 6 veces en el registro real, incluso tejido a mitad de
# frase). Se conserva para migrar al v9.
V8_DEFAULT_INITIAL_PROMPT = (
    "Ayer hice el deploy de los workers en el backend y el build quedó "
    "listo; luego commit, push y un pull request a la branch main con las "
    "features del release. Sometimes I dictate a whole sentence in English "
    "and it stays in English. Reviso los endpoints de la API, el webhook, "
    "el payload JSON y el fetch del frontend con Docker, MongoDB, Coolify, "
    "n8n, Shopify, WhatsApp, Wasender, Rappi, ChatGPT, Whisper y Wisip. Mi "
    "correo es usuario@dominio.com y el sitio es wisip.ai/dashboard. "
    "Palabras frecuentes: login, sesión, autenticación, token."
)
# Prompt v9 (actual): TRANSCRIPCIÓN PREVIA que DEMUESTRA el estilo deseado:
# español con términos de programación en inglés escritos tal cual (Whisper
# imita el estilo del contexto, no obedece instrucciones). Incluye además una
# frase completa en inglés como ancla del modo mixto. TODO el prompt son
# frases naturales: un listado con encabezado invita al eco; una frase no.
# IMPORTANTE: prompt + hotwords COMPARTEN el presupuesto de ~224 tokens del
# contexto de Whisper. Si la suma se pasa, el recorte desestabiliza el primer
# segmento (duplicaba el arranque del dictado). Mantén ambos cortos.
DEFAULT_INITIAL_PROMPT = (
    "Ayer hice el deploy de los workers en el backend y el build quedó "
    "listo; luego commit, push y un pull request a la branch main con las "
    "features del release. Sometimes I dictate a whole sentence in English "
    "and it stays in English. Reviso los endpoints de la API, el webhook, "
    "el payload JSON y el fetch del frontend con Docker, MongoDB, Coolify, "
    "n8n, Shopify, WhatsApp, Wasender, Rappi, ChatGPT, Whisper y Wisip. Mi "
    "correo es usuario@dominio.com y el sitio es wisip.ai/dashboard, donde "
    "manejo login, sesión y token de autenticación."
)

# Hotwords: vocabulario que faster-whisper inyecta en CADA ventana de audio
# (el initial_prompt solo condiciona la primera ventana de cada transcripción).
# Ideal para términos EN que deben quedarse en inglés dentro de frases ES.
# Editable en app_settings.json ("hotwords"); vacío = desactivado.
# CORTO a propósito: comparte presupuesto de tokens con el initial_prompt.
# Hotwords v1 (anterior). Se conserva para migrar instalaciones que lo tengan
# guardado al v2, que añade nombres de productos IA que Whisper malinterpreta
# (Seedance salía como "Zidane"; kie.ai no se reconocía).
V1_DEFAULT_HOTWORDS = (
    "workers, deploy, build, commit, push, branch, merge, release, feature, "
    "endpoint, webhook, payload, fetch, frontend, backend, token"
)
DEFAULT_HOTWORDS = (
    "workers, deploy, build, commit, push, branch, merge, release, feature, "
    "endpoint, webhook, payload, fetch, frontend, backend, token, Seedance, "
    "kie.ai"
)

# Modo idioma mixto (rev3): activa `multilingual=True` en faster-whisper →
# el idioma se RE-DETECTA POR SEGMENTO (cada pausa). Una frase completa en
# inglés se transcribe en inglés; la siguiente en español, en español. Ya no
# fuerza language=None global (rev1: eso traducía TODO el dictado cuando la
# primera ventana parecía EN). El idioma pedido ('es') sigue siendo la base;
# los términos EN sueltos dentro de frases ES los cubren el prompt v8 +
# hotwords.
DEFAULT_MIXED_LANGUAGE_MODE = True

# ─── Guardas anti-alucinación ───────────────────────────────────────────
# Whisper alucina texto en silencios/ruido (créditos de subtítulos, saludos de
# YouTube). Se descartan segmentos que (a) coinciden EXACTO (normalizado) con
# frases fantasma conocidas, o (b) tienen no_speech_prob alto con logprob bajo.
HALLUCINATION_NO_SPEECH_MAX = 0.85        # descarta si no_speech_prob supera esto
HALLUCINATION_NO_SPEECH_SOFT = 0.60       # umbral suave…
HALLUCINATION_LOGPROB_MIN = -1.0          # …combinado con avg_logprob bajo
# Caso real 2026-07-21: el usuario se alejó del micro sin soltar el hotkey y
# los tramos finales (voz lejana + ruido) produjeron "S.A.Dashboard. Jajaja.
# Jajaja..." con avg_logprob ≤ -1.0 pero no_speech = 0.0 (el VAD recortó el
# silencio y el decoder inventó sobre lo que quedó). De ahí estas dos guardas:
HALLUCINATION_LAUGH_LOGPROB = -0.5        # risa sola + confianza baja = ruido
HALLUCINATION_SHORT_LOGPROB = -1.0        # segmento corto con confianza ínfima
HALLUCINATION_SHORT_MAX_WORDS = 3
# Si la frase anterior quedó ABIERTA (sin . ! ? …), un segmento corto es
# probablemente su continuación, no ruido: se exige un umbral mucho más bajo.
# Caso real 2026-07-24: "...para generar imágenes" + "blancas." (logprob -1.15)
# era habla real y la guarda plana de -1.0 la descartó (confirmado a oído por
# el usuario, 2026-08-03).
HALLUCINATION_SHORT_LOGPROB_OPEN = -1.5
# Fórmulas de despedida como COLA fantasma (registro 2026-07/08: "Muchas
# gracias." y "Chao." colados al final del dictado; Whisper "cierra el video"
# al ver ruido tras la última frase). Solo se descartan si el segmento es
# EXACTAMENTE la fórmula Y la confianza es baja: dictadas de verdad ("Muchas
# gracias." clara al micro) promedian avg_logprob ≥ -0.4 y PASAN.
HALLUCINATION_CLOSING_LOGPROB = -0.5
CLOSING_PHRASES = {
    "muchas gracias",
    "muchas gracias.",
    "gracias",
    "gracias a todos",
    "muchas gracias a todos",
    "chao",
    "chau",
    "adiós",
    "hasta luego",
    "hasta pronto",
    "nos vemos",
    "un saludo",
    "saludos",
    "buenas noches",
    "bye",
    "thank you",
    "thanks",
    "see you",
}
HALLUCINATION_PHRASES = {
    # créditos de subtítulos (las más frecuentes en el dataset ES de Whisper)
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulado por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "subtítulos creados por la comunidad de amara.org",
    "subtítulos en español de amara.org",
    "subtitulos realizados por la comunidad de amara.org",
    "para más información visita www.alimmenta.com",
    "www.mooji.org",
    # despedidas fantasma de YouTube
    "¡gracias por ver el vídeo!",
    "¡gracias por ver el video!",
    "gracias por ver el vídeo",
    "gracias por ver el video",
    # variante con cola de cortesía (caso real 2026-08-20: "Gracias por ver el
    # video, por favor." con logprob -0.885 se coló porque la coma interna
    # impedía el match exacto)
    "gracias por ver el vídeo, por favor",
    "gracias por ver el video, por favor",
    "¡gracias por ver!",
    "gracias por ver",
    "¡suscríbete al canal!",
    "suscríbete al canal",
    "¡suscríbete!",
    "no olvides suscribirte",
    "gracias por su atención",
    "¡hasta la próxima!",
    "nos vemos en el próximo vídeo",
    "nos vemos en el próximo video",
    "thank you for watching",
    "thanks for watching",
}

# Log por-segmento (start/end/text/avg_logprob/no_speech_prob). Por defecto off
# porque hace los logs ruidosos; útil para diagnosticar cortes raros.
DEFAULT_DEBUG_SEGMENTS = False

# Log de los reemplazos aplicados ([replacements] aplicados / parser URL/email).
# On por defecto en esta fase para que sea fácil ver qué corrige el pipeline.
DEFAULT_DEBUG_REPLACEMENTS = True

# Modo técnico: habilita reemplazos agresivos de "punto"/"coma"/"dos puntos"/etc.
# Por defecto off para no romper dictado natural. Si lo activas, "punto" se
# vuelve "." en TODO el texto (útil si dictas comandos/código todo el día).
DEFAULT_TECH_MODE = False

# ─── Postprocesador de correos/URLs/símbolos (app/postprocessor.py) ────────
# Normalizador dedicado que corre DESPUÉS de los reemplazos y ANTES de pegar.
DEFAULT_NORMALIZE_EMAILS_URLS = True     # interruptor maestro del normalizador
DEFAULT_DEBUG_NORMALIZER = False         # loguea antes/después/reglas aplicadas
# Arroba agresiva: convierte "arroba" suelta en prosa a "@". Off por defecto
# para no romper frases explicativas ("convierte arroba en @").
DEFAULT_TECHNICAL_SYMBOL_MODE = False
# Envolver correos en enlace markdown [correo](mailto:correo). Off: texto plano,
# universal para pegar en cualquier app.
DEFAULT_EMAIL_AS_MARKDOWN = False

# Perfiles de calidad: setean varios parámetros a la vez.
QUALITY_PROFILE_FAST = "fast"
QUALITY_PROFILE_BALANCED = "balanced"
QUALITY_PROFILE_ACCURATE = "accurate"
QUALITY_PROFILE_ACCURATE_GPU = "accurate_gpu"
QUALITY_PROFILE_CUSTOM = "custom"

QUALITY_PROFILES = {
    QUALITY_PROFILE_FAST: {
        "model": "base",
        "beam_size": 1,
        "best_of": 1,
        "temperature": 0.0,
        "vad_filter": True,
        "compute_type": "int8",
    },
    QUALITY_PROFILE_BALANCED: {
        "model": "small",
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0.0,
        "vad_filter": True,
        "compute_type": "int8",
    },
    QUALITY_PROFILE_ACCURATE: {
        "model": "medium",
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0.0,
        "vad_filter": True,
        "compute_type": "int8",
    },
    # Preciso GPU: large-v3-turbo con compute "auto" (float16 en GPU). En una
    # NVIDIA es a la vez el MÁS preciso y más rápido que small. Si no hay GPU
    # cae a CPU int8 (funciona, pero lento — mejor usar Balanceado ahí).
    QUALITY_PROFILE_ACCURATE_GPU: {
        "model": GPU_RECOMMENDED_MODEL,
        "beam_size": 5,
        "best_of": 5,
        "temperature": 0.0,
        "vad_filter": True,
        "compute_type": "auto",
    },
}
QUALITY_PROFILE_LABELS = {
    QUALITY_PROFILE_FAST: "Rápido",
    QUALITY_PROFILE_BALANCED: "Balanceado",
    QUALITY_PROFILE_ACCURATE: "Preciso (CPU)",
    QUALITY_PROFILE_ACCURATE_GPU: "Preciso GPU",
    QUALITY_PROFILE_CUSTOM: "Personalizado",
}
QUALITY_PROFILE_LABEL_TO_KEY = {v: k for k, v in QUALITY_PROFILE_LABELS.items()}
QUALITY_PROFILE_DESCRIPTIONS = {
    QUALITY_PROFILE_FAST:     "base · greedy · más rápido, calidad básica",
    QUALITY_PROFILE_BALANCED: "small · beam=5 · buena calidad / velocidad",
    QUALITY_PROFILE_ACCURATE: "medium · beam=5 · máxima calidad en CPU (~1.5GB, lento)",
    QUALITY_PROFILE_ACCURATE_GPU: "large-v3-turbo · beam=5 · máxima calidad, rapidísimo con NVIDIA",
    QUALITY_PROFILE_CUSTOM:   "Configuración manual",
}
QUALITY_PROFILE_KEYS = list(QUALITY_PROFILES.keys()) + [QUALITY_PROFILE_CUSTOM]
DEFAULT_QUALITY_PROFILE = QUALITY_PROFILE_BALANCED

VALID_COMPUTE_TYPES = ["auto", "int8", "int8_float16", "float16", "float32", "bfloat16", "int8_bfloat16"]

# Audio
SAMPLE_RATE = 16000
CHANNELS = 1

# Hotkey por defecto: la tecla "|" (la que está antes del 1 en teclado ES-LA).
# Mantén esa tecla para grabar, suéltala para transcribir y pegar.
# Si quieres desactivarlo temporalmente para usar la tecla normalmente, hay
# un switch "Atajo activo" en la ventana principal de la app.
# Para cambiar el hotkey: edita "hotkey" en %APPDATA%\local-voice-typer\app_settings.json
# (ej. "f9", "f10", "pause", "capslock", "ctrl+shift+space").
# Ctrl + Win + Espacio: existe en todos los teclados y es el mismo atajo que
# usa Wispr Flow en Windows (antes "|", que falta en muchos teclados). Las
# instalaciones existentes conservan su tecla guardada.
DEFAULT_HOTKEY = "ctrl+windows+space"

# Modos de pegado
PASTE_MODE_PASTE = "paste"
PASTE_MODE_COPY_ONLY = "copy_only"
PASTE_MODES = [PASTE_MODE_PASTE, PASTE_MODE_COPY_ONLY]

# Paste timings
PASTE_DELAY = 0.15
PASTE_MODIFIER_WAIT_TIMEOUT = 0.5  # max segundos a esperar a que se suelten ctrl/alt/win físicos
# Pausa configurable (ms) entre copiar al portapapeles y enviar Ctrl+V.
# Se persiste como "paste_delay_ms" en app_settings.json. Se valida a este rango.
DEFAULT_PASTE_DELAY_MS = 200
PASTE_DELAY_MS_MIN = 0
PASTE_DELAY_MS_MAX = 5000

# Inicio automático con Windows.
# Usamos HKCU\...\Run (no HKLM): no requiere admin y es escribible por el usuario.
# El valor se llama "Wisip". Lo gestiona app/autostart.py.
DEFAULT_START_WITH_WINDOWS = False
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "Wisip"

# Historial
HISTORY_MAX = 10

# Registro de dictados (ciclo de mejora): guarda CADA dictado en un JSONL
# mensual (logs/dictados-YYYY-MM.jsonl) con texto crudo/final, segmentos
# descartados y confianza. Analizable con scripts/analyze_logs.py para
# convertir errores recurrentes en reemplazos/blacklist/hotwords.
DEFAULT_DICTATION_LOG_ENABLED = True
# Audio de respaldo: "off" (nunca), "sospechosos" (solo dictados con descartes
# o limpiezas — permite verificar qué se dijo realmente), "todos".
DICTATION_LOG_AUDIO_MODES = ("off", "sospechosos", "todos")
DEFAULT_DICTATION_LOG_AUDIO = "sospechosos"
# Tope de disco para los WAV (se borran los más viejos al superarlo).
DICTATION_LOG_AUDIO_MAX_MB = 500
# Quitar los puntos suspensivos que Whisper inserta en las pausas del hablante.
DEFAULT_STRIP_ELLIPSIS = True

# Beeps (Hz, ms)
BEEP_START = (880, 80)
BEEP_STOP = (660, 80)
BEEP_ERROR = (300, 200)


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


APP_DATA_DIR = _appdata_dir()
SETTINGS_PATH = APP_DATA_DIR / "app_settings.json"
REPLACEMENTS_PATH = APP_DATA_DIR / "replacements.json"
# Correcciones personales (nombres propios, marca) separadas de las generales.
PERSONAL_REPLACEMENTS_PATH = APP_DATA_DIR / "personal_replacements.json"
# Alias de correos personales (opcional, por usuario). Se crea VACÍO; no
# contiene PII en el código distribuido. Lo usa app/postprocessor.py.
PERSONAL_EMAILS_PATH = APP_DATA_DIR / "personal_emails.json"
HISTORY_PATH = APP_DATA_DIR / "history.json"
# Registro de dictados: JSONL mensuales + audio de respaldo (WAV 16kHz mono).
DICTATION_LOGS_DIR = APP_DATA_DIR / "logs"
DICTATION_LOG_AUDIO_DIR = DICTATION_LOGS_DIR / "audio"
# Errores y log de la app a archivo: el .exe corre con console=False, así que
# sin esto los fallos "desaparecen" (ver app/error_log.py).
ERROR_LOG_PATH = DICTATION_LOGS_DIR / "wisip-errors.log"
APP_LOG_PATH = DICTATION_LOGS_DIR / "wisip.log"

# Temp
TEMP_DIR = Path(os.environ.get("TEMP", str(Path.home()))) / "local_voice_typer"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
