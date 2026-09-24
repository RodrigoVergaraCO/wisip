# Wisip — Manual técnico completo (español)

> Documento de referencia detallado. Para una visión general, empieza por el [README](../README.es.md).

**Wisip** (antes "Local Voice Typer") es una app de escritorio para Windows que **escucha el micrófono, transcribe localmente con [faster-whisper](https://github.com/SYSTRAN/faster-whisper) en español, y pega el texto en el input activo** (ChatGPT, WhatsApp Web, VS Code, Notion, etc.).

- 100 % local. Sin API keys, sin internet (salvo la descarga inicial del modelo), sin coste mensual.
- **Funciona en modo usuario (sin administrador)** para apps normales (Chrome, ChatGPT, WhatsApp Web, Notion, VS Code, etc.). Ver ["¿Por qué a veces necesita administrador?"](#por-qué-a-veces-necesita-administrador).
- Puede **iniciarse automáticamente con Windows** (opcional, sin admin). Ver ["Inicio automático con Windows"](#inicio-automático-con-windows).
- Hotkey global por defecto: **`|`** (la tecla antes del `1` en teclado ES-LA). Push-to-talk: mantén para grabar, suelta para transcribir y pegar. Cambiable desde la app (botón 👆).
- Icono en la bandeja de Windows. La X de la ventana **oculta**, no cierra.
- Diccionario de reemplazos editable (`replacements.json`) para corregir términos técnicos.
- Historial de las últimas 10 transcripciones con botones Copiar / Pegar / Limpiar.
- Beeps de feedback al iniciar / detener / error.
- Modo `paste` (auto-paste) o `copy_only` (sólo copia al portapapeles).
- Persistencia de configuración en `app_settings.json`.
- Empaquetable como `.exe` con PyInstaller.

---

## Requisitos

- Windows 10 / 11
- Python 3.10 – 3.12 (recomendado 3.11)
- Micrófono funcional

> Los modelos de Whisper se descargan a `~/.cache/huggingface/` la primera vez que los seleccionas. Tamaño: `tiny` ≈ 75 MB, `base` ≈ 145 MB, `small` ≈ 480 MB.

## Instalación

```powershell
cd local-voice-typer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea la activación del venv:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## Ejecutar

```powershell
python main.py
```

> **No necesitas administrador** para apps normales. El hook global de `keyboard` y el pegado funcionan en modo usuario contra Chrome, ChatGPT, VS Code, etc. Solo necesitarías administrador para pegar/controlar ventanas que **a su vez** corran elevadas (ver ["¿Por qué a veces necesita administrador?"](#por-qué-a-veces-necesita-administrador)). Si el hotkey no registra, la app te lo dice en los logs y puedes cambiar el atajo con el botón 👆.

## Cómo usar

1. Lanza la app. Espera a que en logs aparezca `modelo 'base' listo`.
2. **Haz clic en el input destino** (ej. el campo de ChatGPT en Chrome).
3. Presiona **`Ctrl + Win + Espacio`** → la app pasa a *Grabando…* y suena un beep.
4. Habla en español.
5. Presiona **`Ctrl + Win + Espacio`** otra vez → *Transcribiendo… → Pegando… → Inactivo*. Suena otro beep.
6. El texto aparece dentro del input.

## Tray (bandeja de Windows)

- Hacer clic en la X de la ventana **oculta** la app a la bandeja, no la cierra. El hotkey global sigue funcionando.
- Click izquierdo en el ícono de la bandeja: muestra la ventana.
- Click derecho: menú con **Mostrar ventana**, **Ocultar ventana**, **Salir**.
- Sólo **Salir** termina la app de verdad.

## Configuración (`app_settings.json`)

Se crea automáticamente en:

```
%APPDATA%\local-voice-typer\app_settings.json
```

Para abrirlo rápido:

```powershell
notepad "$env:APPDATA\local-voice-typer\app_settings.json"
```

Llaves disponibles:

| Llave | Tipo | Default | Para qué |
|---|---|---|---|
| `model` | string | `"small"` | `tiny`, `base`, `small`, `medium` o `large-v3-turbo`. En CPU: `small`. Con GPU NVIDIA: **`large-v3-turbo`** (máxima calidad y además más rápido que `small` — la app migra sola la primera vez que detecta GPU). |
| `language` | string | `"es"` | Idioma para Whisper. `"es"` recomendado (estable). `"auto"` solo si dictas frases muy densas en inglés. `task` siempre es `transcribe` (nunca traduce). |
| `hotkey` | string | `"|"` | Atajo global (push-to-talk). Ejemplos: `"ctrl+windows+space"`, `"ctrl+alt+space"`, `"f9"`. Cambiable desde la app (botón 👆). |
| `paste_mode` | string | `"paste"` | `"paste"` = copia y pega. `"copy_only"` = sólo copia. |
| `paste_delay_ms` | int | `200` | Pausa (ms) entre copiar al portapapeles y enviar Ctrl+V. Súbelo si alguna app "se come" el pegado por ir muy rápido. Rango 0–5000. |
| `beep_enabled` | bool | `true` | Beeps de inicio / fin / error. |
| `auto_paste_enabled` | bool | `true` | Kill switch del auto-paste. Si `false`, fuerza `copy_only`. |
| `replacements_enabled` | bool | `true` | Aplica `replacements.json` después de transcribir. |
| `start_minimized` | bool | `false` | Si `true`, arranca oculto en la bandeja. Cambiable desde la app. |
| `start_with_windows` | bool | `false` | Si `true`, Wisip se inicia al iniciar sesión en Windows (HKCU Run, sin admin). Cambiable desde la app. |
| `last_window_geometry` | string | `""` | Lo gestiona la app sola. |
| `mixed_language_mode` | bool | `true` | **Modo mixto real (rev3)**: activa `multilingual=True` en faster-whisper → el idioma se re-detecta **por segmento** (cada pausa). Una frase completa en inglés queda en inglés; la siguiente en español queda en español. Los términos EN sueltos dentro de frases ES los cubren el prompt v8 + `hotwords`. Apágalo solo si dictas español 100% puro. |
| `hotwords` | string | términos EN comunes | Vocabulario que se inyecta en **cada ventana** de audio (el prompt inicial solo condiciona la primera). Ideal para términos EN que Whisper te traduce (`workers`, `deploy`, `build`…). Separado por comas. Vacío = desactivado. **Mantenlo corto**: comparte el presupuesto de ~224 tokens con el prompt inicial (si se pasan, el arranque del dictado sale duplicado). |
| `debug_segments` | bool | `false` | Loguea cada segmento devuelto por faster-whisper (`start`, `end`, `text`, `avg_logprob`, `no_speech_prob`). Útil para diagnosticar cortes raros. Hace los logs muy ruidosos. |
| `debug_replacements` | bool | `true` | Loguea qué reemplazos y normalizaciones de URL/email se aplicaron (`[replacements] aplicados`, `[url/email]`). Ponlo en `false` para logs limpios. |
| `performance_profile` | string | `"quality_current"` | Perfil de rendimiento: `"quality_current"` (CPU int8, idéntico a hoy), `"fast_safe"` (device auto + batched), `"max_speed"` (GPU + batched grande), `"perf_custom"` (usa `device`/`compute_type` crudos). Ver "Velocidad, GPU y perfiles". |
| `device` | string | `"auto"` | `"auto"` (GPU NVIDIA si funciona, si no CPU), `"cpu"` o `"cuda"`. Solo aplica con perfil `perf_custom`; los otros perfiles lo fijan ellos. |
| `compute_type` | string | `"int8"` | Precisión de cómputo: `"auto"` (float16 en GPU / int8 en CPU), `"int8"`, `"int8_float16"`, `"float16"`, `"float32"`. |
| `batched` | bool | `false` | Usa `BatchedInferencePipeline` (más rápido en audio largo, misma calidad). Lo activan los perfiles fast_safe/max_speed. |
| `batch_size` | int | `8` | Tamaño de lote para batched (8 normal, 16 máxima velocidad). |
| `cpu_threads` | int | `0` | Hilos de CPU para CTranslate2. `0` = todos. |
| `num_workers` | int | `1` | Workers paralelos de CTranslate2. |
| `enable_gpu_if_available` | bool | `true` | Si `false`, nunca usa GPU aunque haya. |
| `incremental_transcription_enabled` | bool | `true` | **Transcripción incremental**: transcribe en segundo plano MIENTRAS hablas, cortando solo en silencios. Al soltar el hotkey la espera final es ~1-2s sin importar cuánto dictaste. Ver "Transcripción incremental". |
| `tech_mode` | bool | `false` | Activa reemplazos agresivos `"punto"→"."`, `"coma"→","`, `"dos puntos"→":"`, etc. **a TODO el texto**. Sirve solo si dictas comandos/código todo el día; rompe dictado natural. Off por defecto. |
| `initial_prompt_enabled` | bool | `true` | Envía un prompt inicial a Whisper para anclar términos técnicos. |
| `initial_prompt` | string | bilingüe | Texto del prompt. Ver sección "Recuadro de prompt inicial". |
| `quality_profile` | string | `"balanced"` | `"fast"`, `"balanced"`, `"accurate"`, `"accurate_gpu"` (large-v3-turbo, recomendado con NVIDIA) o `"custom"`. Setea modelo + beam + best_of + compute_type. |

Casi todo se puede cambiar también desde la UI: modelo, modo, beep, reemplazos, **hotkey** (botón 👆), **Iniciar con Windows** e **Iniciar minimizada**. `paste_delay_ms` se cambia editando el JSON (y reiniciando la app).

## Reemplazos (`replacements.json`)

Sirve para corregir términos técnicos que Whisper castellaniza.

Se crea automáticamente en:

```
%APPDATA%\local-voice-typer\replacements.json
```

Ejemplo:

```json
{
  "chat yipiti": "ChatGPT",
  "chat gpt": "ChatGPT",
  "gipi ti": "GPT",
  "yason": "JSON",
  "jason": "JSON",
  "n eight n": "n8n",
  "n 8 n": "n8n",
  "mongo de ve": "MongoDB",
  "mongo db": "MongoDB",
  "guasa": "WhatsApp",
  "wasap": "WhatsApp"
}
```

- **Case-insensitive**: `"chat yipiti"` matchea `"Chat Yipiti"` y `"CHAT YIPITI"`.
- Tolerante a espacios extra.
- Usa límites de palabra para no destrozar términos dentro de otros.
- Las claves más largas se aplican antes que las cortas.
- Si editas el archivo mientras la app corre, reinicia para recargarlo.
- Cuando se aplican reemplazos, aparece en logs: `[replacements] aplicados: 'chat yipiti'→'ChatGPT'` (si `debug_replacements: true`).

## Correcciones personales (`personal_replacements.json`)

Correcciones de **nombres propios y marca** (lo tuyo) separadas de los reemplazos generales. Se crea automáticamente en:

```
%APPDATA%\local-voice-typer\personal_replacements.json
```

Ejemplo (defaults):

```json
{
  "juanperez": "juanperez",
  "juan perez": "juanperez",
  "jodmail": "hotmail",
  "wism": "Wisip",
  "wisin": "Wisip",
  "wisp": "Wisip"
}
```

- Mismas reglas que `replacements.json` (case-insensitive, límites de palabra, más-largo-primero).
- Se aplican **antes** del parser de URLs/emails, para que un nombre o host mal oído se corrija antes de rearmar el correo (ej. `juanperez arroba jodmail punto com` → `juanperez@hotmail.com`).
- **No** pongas aquí símbolos (`arroba`, `punto`, `slash`): esos los maneja el parser de URLs.
- Edita el archivo y reinicia la app para recargarlo. Añade tus propios nombres, apodos o términos personales.

## Dictar URLs, emails y símbolos

La app reconstruye URLs, emails y rutas **solo cuando detecta un patrón claro** (TLD conocido como `.com`/`.ai`/`.co`/`.io`/etc., o el token `arroba`). Frases como "voy al **punto** importante" se quedan intactas.

| Lo que dictas | Resultado |
|---|---|
| `juanperez arroba hotmail punto com` | `juanperez@hotmail.com` |
| `w w w punto wisip punto ai slash dashboard` | `www.wisip.ai/dashboard` |
| `api punto wisip punto co slash v1 slash users` | `api.wisip.co/v1/users` |
| `app punto wisip punto com punto co` | `app.wisip.com.co` |
| `endpoint slash api slash users` | `endpoint /api/users` |

Además hay un **parser de formas degradadas** (`normalize_urls_and_emails`) que actúa **solo si el texto ya contiene señales de URL/email** (`@`, `.com`, `.ai`, `.co`, `wisip`, etc.) y arregla lo que el modelo deforma:

| Lo que transcribe el modelo | Resultado |
|---|---|
| `juanperezarroba.hotmail.com` (arroba fusionado) | `juanperez@hotmail.com` |
| `wisip.ai-dashboard` (slash oído como guion) | `wisip.ai/dashboard` |
| `ap.Wisip.cov-v1-users` (api/co/slashes degradados) | `api.wisip.co/v1/users` |

> El parser **no toca guiones de frases normales** (`cliente-servidor`, `micro-servicios` quedan intactos) ni convierte `punto`/`guion`/`dos puntos` globalmente. La reconstrucción de URLs muy degradadas es heurística: si una sale rara, dicta el símbolo más marcado o usa un modelo mayor (`medium`).

Otros símbolos que sí se reemplazan siempre (son inambiguos en español):

- `arroba` → `@`
- `slash` / `barra inclinada` / `diagonal` → `/`
- `backslash` / `barra invertida` → `\`
- `pipe` / `pleca` → `|`
- `hash` / `numeral` / `hashtag` → `#`
- `ampersand` / `and symbol` → `&`
- `dólar` / `signo pesos` → `$`
- `asterisco` → `*`, `porcentaje` → `%`, `igual` → `=`
- `abrir/cerrar paréntesis` → `(` `)`
- `abrir/cerrar corchete` → `[` `]`
- `abrir/cerrar llave` → `{` `}`
- `menor que` / `mayor que` → `<` `>`
- `guion bajo` / `underscore` → `_`

**`punto`, `coma`, `dos puntos`, `guion`, `más`, `menos`, `espacio`** NO se reemplazan globalmente porque romperían dictado natural. Si dictas comandos/código todo el día y quieres ese comportamiento agresivo, activa `tech_mode: true` en `app_settings.json`.

Números de puerto comunes ya están como reemplazos: `tres mil` → `3000`, `cinco mil` → `5000`, `ocho mil` → `8000`, `nueve mil` → `9000`. Añade más en `replacements.json` si los usas. Un parser general de números en español queda fuera de scope por ahora.

## Recuadro de prompt inicial

El textbox **"Prompt inicial"** en la ventana es el `initial_prompt` que se envía a faster-whisper en cada transcripción.

- Whisper lo usa como **contexto previo**: las palabras del prompt se reconocen mejor en lo que dictas. Si pones `ChatGPT, n8n, MongoDB`, ya no salen como "chat yipi ti".
- También sesga el idioma. El prompt por defecto (v7) está **redactado como si fuera transcripción previa en español** con el vocabulario técnico embebido — ancla el idioma en ES y a la vez enseña los términos EN.
- **No** es una instrucción tipo "sé conciso" ni "no traduzcas". Whisper **no obedece comandos** — un prompt estilo instrucción no hace nada y a veces se filtra al texto. Solo sirve como vocabulario / ancla de idioma (por eso el v7 dejó de usar instrucciones).
- Reglas prácticas:
  - Mantenlo corto (Whisper lo trunca a ~200 tokens).
  - Mete términos que dictas seguido y que el modelo te suele dañar.
  - Si dictas solo en español puro, puedes simplificarlo para que el sesgo sea más ES (apaga también `mixed_language_mode`).
  - Apagar el checkbox "Activo" → no se manda nada al modelo.

## Idioma mixto (ES + términos EN)

Switch en la ventana llamado **"IDIOMA MIXTO (ES + TÉRMINOS EN)"**. Por defecto **activo**.

**Cuándo importa**: tienes el idioma puesto en `Español` pero dictas frases como *"crea un webhook para Shopify que conecte con MongoDB y haga fetch a la API"*. Sin tratamiento especial Whisper queda bloqueado en español y puede:

- Cortar la frase en cuanto encuentra una palabra inglesa.
- Devolver la palabra inglesa romanizada (ej. `wevjub` en vez de `webhook`).
- Generar segmentos truncos por baja probabilidad.

**Cómo lo arregla** (rev3): el switch activa **`multilingual=True`** de faster-whisper: el idioma se **re-detecta por segmento** (en cada pausa del habla). Así:

- *"Necesito configurar los workers del backend"* → segmento ES → español, con `workers` en inglés (lo anclan el prompt v8 + `hotwords`).
- *"Now I need to create a new endpoint for the dashboard"* → segmento EN → **se queda en inglés**, no se traduce.

Tres capas trabajan juntas:

1. **`multilingual` por segmento** → frases completas en EN se quedan en EN.
2. **Prompt v8 demostrativo** → el prompt es un texto de ejemplo que *muestra* el estilo (ES con términos EN tal cual + una frase EN completa); Whisper imita el estilo del contexto.
3. **`hotwords`** → vocabulario EN inyectado en cada ventana para que `workers`/`deploy`/`build` no se castellanicen.

Ya **no** se fuerza `language=None` global (rev1: eso hacía que un dictado entero se tradujera al inglés si la primera ventana parecía EN).

Si Whisper te transcribe en inglés cuando tú hablaste español, asegúrate de que el idioma del selector esté en **Español** (no en Auto). Si una palabra concreta (ej. `wisip`, `arroba`, `Hotmail`) no la oye bien, agrégala al **Prompt inicial** — Whisper la reconocerá mejor en transcripciones siguientes.

## Historial

- Panel "Historial (últimas 10)" en la ventana.
- Selecciona una línea y usa **Copiar** (sólo portapapeles) o **Pegar** (Ctrl+V en la ventana activa).
- **Limpiar** vacía el historial.
- Se persiste en `%APPDATA%\local-voice-typer\history.json`.

## Modo `paste` vs `copy_only`

Cambia desde el OptionMenu **Modo** en la ventana:

- **`paste`**: tras transcribir → copia al clipboard → simula `Ctrl+V` en la ventana activa.
- **`copy_only`**: tras transcribir → sólo copia al clipboard. Tú haces el `Ctrl+V` cuando quieras.

Útil cuando estás trabajando en una app donde `Ctrl+V` hace algo distinto o quieres pegar más tarde.

## Inicio automático con Windows

Wisip puede abrirse sola cada vez que inicias sesión en Windows. **No requiere administrador.**

### Cómo activarlo

1. Abre Wisip.
2. En la pestaña **Transcribe**, activa el switch **"INICIAR CON WINDOWS"**.
3. (Opcional) Activa también **"INICIAR MINIMIZADA (AL TRAY)"** para que arranque oculta en la bandeja, sin robar el foco. El hotkey sigue activo aunque la ventana esté oculta.

### Cómo desactivarlo

Apaga el switch **"INICIAR CON WINDOWS"**. La entrada se borra del registro inmediatamente.

### Dónde se registra

En el registro de Windows, **por usuario** (no requiere admin):

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
    Valor: "Wisip"  →  ruta al ejecutable
```

- Empaquetada (`.exe`): el valor apunta a `...\Wisip.exe`.
- En desarrollo (`python main.py`): apunta a `pythonw.exe` + `main.py` del venv. **El autostart se recomienda con el `.exe`** (la ruta del venv puede cambiar). Si mueves o reinstalas el `.exe`, Wisip reescribe la ruta correcta la próxima vez que abre con el switch activo.

### Verificar / revertir manualmente

```powershell
# Ver si está registrado
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Wisip

# Borrar la entrada a mano (equivale a apagar el switch)
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Wisip /f
```

> Usamos **HKCU Run** (no HKLM, no carpeta Startup) a propósito: es escribible por el usuario, no pide UAC, y es un único valor fácil de crear, leer y borrar.

## ¿Por qué a veces necesita administrador?

Resumen: **para uso normal, NO necesita administrador.**

- **Apps normales** (Chrome, ChatGPT, WhatsApp Web, Notion, VS Code normal, etc.): el hotkey global y el pegado (Ctrl+V) funcionan perfectamente **sin admin**. Este es el caso del 99 % del tiempo.
- **Apps ejecutadas como administrador**: Windows aplica **UIPI** (User Interface Privilege Isolation). Un proceso **no elevado** (como Wisip en modo usuario) **no puede enviar teclas ni controlar** ventanas que corren **elevadas**. Esto es una protección del sistema operativo, no un fallo de Wisip.
- **Solución cuando te topas con esto**:
  1. Lo más simple: **no ejecutes la app destino como administrador** (ábrela normal). Chrome, ChatGPT y WhatsApp Web casi nunca necesitan admin.
  2. Si de verdad necesitas pegar en una app elevada (ej. un editor abierto como admin), ejecuta **Wisip también como administrador**. Solo en ese caso.

> Wisip ya **no** se compila con elevación forzada (`--uac-admin`), así que no pide UAC en cada arranque. Si alguna vez el pegado falla, el texto **siempre queda en el portapapeles** como respaldo: puedes pegarlo a mano con Ctrl+V.

## Branding e iconos

El icono oficial es `icon.png` en la raíz del proyecto (waveform lima sobre fondo claro). En tiempo de ejecución la app:

1. Setea `AppUserModelID = "com.wisip.app"` en `main.py` **antes** de crear cualquier ventana Tk → la barra de tareas de Windows agrupa la app como "Wisip" en lugar de "Python".
2. Aplica `iconbitmap` con `assets/icon.ico` y `iconphoto` con `icon.png` → icono correcto en título, alt-tab y vista previa.
3. El tray icon (esquina inferior derecha) usa el mismo `icon.png`.

### Generar `assets/icon.ico` desde `icon.png`

```powershell
python EXE\make_ico.py
```

Esto crea `assets\icon.ico` con tamaños 16/24/32/48/64/128/256. Solo se regenera si `icon.png` cambió.

## Construir `Wisip.exe` con PyInstaller

```powershell
EXE\build.bat
```

El script orquesta:

1. Activa el venv (`.\.venv`).
2. Instala/actualiza dependencias + PyInstaller.
3. Regenera `assets\icon.ico` si hace falta.
4. Limpia builds previos en `EXE\build\` y `EXE\Wisip\`.
5. Ejecuta PyInstaller con `EXE\Wisip.spec` en modo `--onedir`, `--windowed` (**sin** `--uac-admin`), con `--icon=assets\icon.ico`.

Resultado: **`EXE\Wisip\Wisip.exe`** + carpeta `_internal\` con dependencias.

**Notas importantes del empaquetado:**

- El build usa `--onedir`. **No uses `--onefile`** con `faster-whisper` / `ctranslate2`: el arranque se vuelve muy lento (descomprime DLLs nativas cada vez) y algunos antivirus lo bloquean.
- El primer arranque del `.exe` **descargará el modelo de Whisper** (no va embebido — pesaría cientos de MB y complicaría redistribución).
- El `.exe` **ya NO se construye con `--uac-admin`** (`uac_admin=False` en `Wisip.spec`). Wisip corre en **modo usuario** y no pide UAC al arrancar. El hook global de `keyboard` y el pegado funcionan sin admin contra apps normales. Si cambias el spec a `uac_admin=True` volverás a pedir admin en cada arranque (no recomendado). Ver ["¿Por qué a veces necesita administrador?"](#por-qué-a-veces-necesita-administrador).
- Si tu antivirus marca el `.exe`, es un falso positivo común con PyInstaller. Solución: firmar el binario o añadir excepción.

## Crear el instalador con Inno Setup

Requiere [Inno Setup 6](https://jrsoftware.org/isdl.php) instalado. **El instalador de Inno Setup no agrega `iscc.exe` al PATH**, así que tienes 3 opciones:

```powershell
# Opción A (recomendada): wrapper que lo encuentra solo
EXE\build_installer.bat

# Opción B: llamar al .exe con ruta completa
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" EXE\installer.iss

# Opción C: agregarlo al PATH una vez (PowerShell como Admin) y luego usar `iscc`
$inno = "C:\Program Files (x86)\Inno Setup 6"
[Environment]::SetEnvironmentVariable("Path",
    [Environment]::GetEnvironmentVariable("Path","Machine") + ";$inno", "Machine")
# (cerrar y abrir PowerShell nuevo)
iscc EXE\installer.iss
```

Resultado: **`EXE\installer\Wisip-Setup-1.0.0.exe`** — un instalador ~ que:

- Se llama "Wisip" en el wizard (español/inglés).
- Instala en `C:\Program Files\Wisip\`. El **instalador** pide admin una vez (para escribir en Program Files), pero **la app arranca en modo usuario** — no pide UAC al usarla.
- Crea acceso directo en Menú Inicio (siempre) y en Escritorio (opcional, checkbox).
- Usa el icono lima en `add/remove programs`, atajos y el .exe del instalador.
- Registra uninstaller en "Programas y características".

Para actualizar versión: edita `MyAppVersion` en `EXE\installer.iss`. **No cambies `AppId`** (es la clave que permite a Windows reconocer la app instalada para reemplazarla).

## Caché de iconos de Windows

A veces Windows sigue mostrando el icono viejo aunque el `.exe` nuevo ya tenga el correcto. Esto es por la **caché de iconos** del shell. Si lo ves:

1. **Desancla** la app de la barra de tareas, **borra el acceso directo** del escritorio y del menú inicio.
2. Reinicia el explorer:

   ```powershell
   taskkill /f /im explorer.exe
   start explorer.exe
   ```

3. (Si persiste) Borra la caché de iconos del usuario:

   ```powershell
   ie4uinit.exe -ClearIconCache
   ```

   O, más bruto:

   ```powershell
   taskkill /f /im explorer.exe
   del /a "%LOCALAPPDATA%\IconCache.db"
   del /a /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db"
   start explorer.exe
   ```

4. Vuelve a anclar la app o crear el acceso directo desde el `.exe` nuevo.

Si construiste un instalador y reinstalaste, conviene además **desinstalar la versión previa** primero para evitar que Windows reuse el icono antiguo desde un atajo viejo.

## Verificar que el icono quedó bien

1. `EXE\Wisip\Wisip.exe` en el Explorador → debe mostrar la **W lima** como ícono del archivo.
2. Doble click → la ventana de Wisip abre con la **W lima** en su esquina (chrome custom) y en la barra de tareas debajo.
3. `Alt + Tab` → el thumbnail de Wisip muestra la **W lima** y el nombre "Wisip".
4. Click derecho sobre el ícono de la taskbar → menú dice "Wisip" (no "python").
5. Tras instalar con `Wisip-Setup-1.0.0.exe`: menú inicio → buscar "Wisip" → resultado con la **W lima**.

## Velocidad, GPU y perfiles de rendimiento

Wisip transcribe **localmente**. La velocidad depende del modelo, del backend (CPU vs GPU) y de si se usa *batched inference* (paraleliza el audio largo). **Nada de esto baja la calidad**: se mantienen el modelo, `beam_size` y el prompt.

### Perfiles de rendimiento (selector "RENDIMIENTO" en la UI)

| Perfil | Qué hace | Cuándo |
|---|---|---|
| **Calidad actual** (default) | CPU `int8` secuencial. **Idéntico a antes.** | Máxima seguridad / reversibilidad. |
| **Rápido seguro** | `device=auto` (GPU `float16` si hay, si no CPU) + **batched**. Mismos parámetros → misma calidad, más rápido en audio largo. | Uso diario recomendado. |
| **Máxima velocidad local** | GPU `float16` + batched con lote grande. | Si tienes NVIDIA y dictas textos largos. |

Se guarda en `app_settings.json` como `performance_profile`. Para volver al comportamiento previo: elige **Calidad actual**.

### ¿Estoy usando CPU o GPU?

- En la UI, bajo el selector de modelo: **`Backend: CPU int8`** o **`Backend: CUDA float16`**.
- En los logs (lanza `python main.py` desde terminal): `[whisper] modelo 'small' listo · backend=CUDA float16`.

### Cómo activar GPU

Solo **NVIDIA**. CTranslate2 no acelera con AMD, Intel ni Apple (esos usan CPU siempre).

1. Instala el runtime CUDA 12 en tu entorno:
   ```powershell
   pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12
   ```
2. En la UI, elige el perfil **Rápido seguro** o **Máxima velocidad local** (device `auto`).
3. Verás `Backend: CUDA float16`. Wisip añade solas las DLLs de esos paquetes al PATH.

> **Distribuir la app:** `EXE/Wisip.spec` detecta solo si el venv tiene los paquetes `nvidia-*`: si están, produce un **build GPU** (empaqueta las DLLs CUDA en `_internal/nvidia/`, ~1.9 GB extra); si no, produce el **build CPU universal** liviano de siempre. Para el build CPU basta compilar desde un venv sin esos paquetes.

### Si CUDA falla

No pasa nada: con `device=auto` (o `cuda`), Wisip hace un **warmup** real al cargar; si CUDA falla (DLLs cuBLAS/cuDNN ausentes, poca VRAM, incompatibilidad) **cae a CPU automáticamente** y lo dice en el log:

```
[whisper] ⚠ CUDA falló (DLLs cuBLAS/cuDNN, VRAM o incompatibilidad). Cayendo a CPU int8.
```

La app **no se rompe**. Si quieres forzar CPU, usa el perfil **Calidad actual** o `"device": "cpu"`.

### Cómo interpretar el ratio

Cada transcripción loguea una línea de benchmark:

```
[bench] audio=42.3s · transcripcion=8.5s · replacements=12ms · ratio=0.20x · modelo=small · backend=CUDA float16 · beam=5 · batched=on
```

- **ratio = tiempo_transcripción / segundos_de_audio**. Más bajo = más rápido.
- `0.20x` → 42 s de audio se transcriben en ~8.5 s. `1.0x` = tiempo real. `>1.0x` = más lento que el audio (CPU + modelo grande).
- Objetivo práctico: `< 0.5x`. GPU suele dar `0.1–0.3x`; CPU `small` ronda `0.4–0.9x` según el equipo.

### Comparar antes/después

1. Pon `"debug_segments": false` para logs limpios.
2. Graba el **mismo** audio (usa `tests/manual_transcription_test.md`) con perfil **Calidad actual**, anota el `[bench]`.
3. Cambia a **Rápido seguro** (o **Máxima velocidad**) y repite.
4. Compara `transcripcion` y `ratio`. Verifica que el **texto** sea equivalente (la calidad no debe cambiar).

### Configuración recomendada para máxima velocidad

```json
{ "performance_profile": "max_speed", "model": "small",
  "device": "auto", "compute_type": "auto", "batched": true, "batch_size": 16 }
```

Con NVIDIA usa `float16` en GPU; sin NVIDIA, batched en CPU. Para uso diario, `"performance_profile": "fast_safe"`.

### Transcripción incremental (IMPLEMENTADA)

Wisip **transcribe mientras hablas** (`app/incremental.py`). Mientras grabas, un worker en segundo plano va transcribiendo los tramos ya dichos; al soltar el hotkey solo queda pendiente el último tramo, así que **la espera final es de ~1-2 segundos aunque hayas dictado 5 minutos**.

- Los cortes se hacen **solo en silencios** (pausa ≥ ~0.45s tras al menos 6s de tramo). Nunca corta a mitad de palabra → **no hay solape ni deduplicación ni riesgo de duplicados**.
- Si hablas sin pausas, no corta: ese tramo se transcribe completo al final (igual que antes).
- Si el dictado es corto (< 6s), se comporta exactamente como el modo clásico.
- Se desactiva con `"incremental_transcription_enabled": false` (vuelve al modo "todo al final").
- En logs verás `[incremental] tramo #N cerrado en silencio (...)` y al final una línea con `tramos=… espera_final=…s`.

```json
{ "incremental_transcription_enabled": true }
```

## Recomendación de modelos

| Modelo | Velocidad | Calidad ES | Cuándo usarlo |
|---|---|---|---|
| `tiny` | Muy rápido | Aceptable | Para hardware modesto o dictado simple. |
| `base` | Rápido | Buena | Liviano. Se queda corto con términos técnicos (faster-whisper, CustomTkinter…). |
| `small` | Más lento | **Muy buena** | **Default recomendado en CPU.** Mejor equilibrio para dictado técnico bilingüe sin GPU. |
| `medium` | Lento (CPU) | Excelente | Máxima calidad en CPU. ~1.5 GB. Perfil **Preciso (CPU)** en la UI. |
| `large-v3-turbo` | **Rapidísimo en GPU** (lento en CPU) | **La mejor** | **Default recomendado con GPU NVIDIA.** Calidad de `large-v3` con decoder recortado: en una RTX 3060 transcribe 30s de audio en <1s — más rápido Y más preciso que `small`. ~1.6 GB. Perfil **Preciso GPU**. La app migra sola a este perfil la primera vez que detecta GPU. |

## Precisión y dictado técnico

Esta sección resume cómo sacar la mejor transcripción para términos técnicos, emails, URLs y mezcla español/inglés.

### Configuración recomendada para precisión máxima

```json
{
  "model": "small",
  "language": "es",
  "beam_size": 5,
  "best_of": 5,
  "temperature": 0.0,
  "vad_filter": true,
  "condition_on_previous_text": false,
  "mixed_language_mode": true,
  "initial_prompt_enabled": true,
  "debug_segments": true,
  "debug_replacements": true
}
```

> Para **calidad aún mayor** cambia el perfil a **Preciso** en la UI (usa `medium`). Más lento en CPU, pero el mejor reconocimiento de términos. `task` siempre es `transcribe` (nunca traduce). Todo es local; no se usan APIs externas.

### Configuración recomendada para uso diario

```json
{
  "model": "small",
  "language": "es",
  "beam_size": 5,
  "best_of": 5,
  "vad_filter": true,
  "mixed_language_mode": true,
  "initial_prompt_enabled": true,
  "debug_segments": false,
  "debug_replacements": false
}
```

Igual que la de precisión pero con `debug_segments`/`debug_replacements` en `false` (logs limpios). Si tu equipo es modesto y `small` va lento, baja a `base` (perderás algo de calidad en términos técnicos).

### Editar correcciones personales y validar

- **`personal_replacements.json`** (en `%APPDATA%\local-voice-typer\`): añade tus nombres propios / marca. Reinicia la app tras editar.
- **Validar sin grabar**: `python scripts\check_replacements.py`.
- **Guía de prueba manual**: `tests/manual_transcription_test.md`.
- **Activar logs de reemplazos**: `"debug_replacements": true` → verás `[replacements] aplicados` y `[url/email]` en la consola.

### Probar `small` vs `medium`

- Desde la **UI**: dropdown **PERFIL** → `Balanceado` (small) o `Preciso` (medium); o el dropdown **MODELO** directamente.
- Desde `app_settings.json`: pon `"model": "small"` o `"model": "medium"` y reinicia.
- La primera vez que uses `medium` se descarga (~1.5 GB) a `~/.cache/huggingface/`.

### Activar logs de diagnóstico (`debug_segments`)

Pon `"debug_segments": true` en `app_settings.json` (o ya viene activo con la config de precisión). En los logs (consola) verás, por cada transcripción:

- `[whisper] params: model=… idioma=… task=transcribe beam_size=… best_of=… vad_filter=… cond_prev=… prompt=… mixed=…`
- `[whisper] audio_duracion=…s`
- `[whisper] idioma_detectado=… prob=… solicitado=… duracion=…s segs=… vacios=…`
- `[whisper] transcrito en …s (RT ratio=…x)`
- Y por cada segmento: `[whisper.seg #N] start=…s end=…s avg_logprob=… no_speech_prob=… text=…`

Para verlos, lanza la app desde una terminal: `python main.py`.

### Validar los reemplazos sin grabar voz

```powershell
python scripts\check_replacements.py
```

Corre frases de prueba por el pipeline de reemplazos e imprime entrada → salida + qué se aplicó. Incluye casos que **deben mejorar** (términos, emails, URLs, VAD) y casos que **NO deben romperse** (español/inglés normal). Útil tras editar `replacements.json`.

### Pruebas manuales (dictado)

Léelas en voz alta y verifica el resultado:

| Lo que dictas | Resultado esperado |
|---|---|
| "creando una app en Python que usa Whisper, faster-whisper, sounddevice, CustomTkinter, pyautogui, pyperclip y un hotkey global" | Esos términos bien escritos |
| "mi correo es juanperez arroba hotmail punto com" | `juanperez@hotmail.com` |
| "una URL como wisip punto ai slash dashboard" | `wisip.ai/dashboard` |
| "api punto wisip punto co slash v1 slash users" | `api.wisip.co/v1/users` |
| "el problema viene del VAD o del initial prompt" | reconoce `VAD` e `initial prompt` |
| "I need a new endpoint for the user dashboard, pero la autenticación sigue bien" | frase completa, sin cortarse |

> Si una palabra concreta sigue saliendo mal: agrégala al **Prompt inicial** (para que el modelo la reconozca) y/o como entrada en `replacements.json` (para corregirla después). Recuerda: `punto`, `coma`, `guion` y `dos puntos` **no** se reemplazan globalmente (romperían español); solo dentro de URLs/emails o con `tech_mode`.

## Errores comunes

| Síntoma | Solución |
|---|---|
| El hotkey no responde | Revisa los logs: si dice "No se pudo registrar el hotkey", otra app ocupa esa tecla. Cámbiala con el botón 👆. Solo para controlar apps **elevadas** necesitarías ejecutar Wisip como administrador. |
| `Ctrl+V` no pega en alguna app | Esa app corre **como Administrador** y Wisip no (UIPI de Windows bloquea el envío de teclas). Solución: cierra esa app y ábrela normal, o ejecuta Wisip como Administrador. Para Chrome/ChatGPT/WhatsApp normales no hace falta. El texto siempre queda en el portapapeles como respaldo. |
| `No default input device` | Configura un micrófono por defecto en *Windows → Sonido*. |
| Transcripción vacía | El VAD descartó audio muy corto o bajo. Habla 1+ segundos, sube el volumen del micro. |
| Tarda mucho en cargar el modelo | La primera vez se descarga. Quedará cacheado. |
| Choca con otro atajo del sistema | Cambia `"hotkey"` en `app_settings.json` (ej. `"ctrl+alt+v"`, `"f9"`, `"ctrl+alt+space"`). Reinicia la app. |
| `cudnn_*.dll not found` | Faltan las libs CUDA de pip: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 nvidia-cuda-runtime-cu12`. Mientras tanto la app cae sola a CPU (no se rompe). |
| El `.exe` no abre | Suele faltar Visual C++ Redistributable. Instala el de Microsoft. |
| El tray icon no aparece | Reinicia Windows Explorer (`taskkill /f /im explorer.exe && start explorer.exe`). |

## Estructura

```
local-voice-typer/
├── README.md
├── requirements.txt
├── main.py                # entrypoint (setea AppUserModelID antes de Tk)
├── icon.png               # icono fuente
├── logo.png               # wordmark del header
├── assets/
│   └── icon.ico           # generado por EXE/make_ico.py
├── EXE/                   # pipeline de empaquetado/instalador
│   ├── make_ico.py        # PNG → ICO multi-resolución
│   ├── Wisip.spec         # spec de PyInstaller
│   ├── build.bat          # orquesta el build
│   ├── installer.iss      # script Inno Setup
│   └── README-build.md    # pasos rápidos del pipeline
├── scripts/
│   └── check_replacements.py  # valida el pipeline de reemplazos sin grabar voz
└── app/
    ├── __init__.py
    ├── autostart.py       # inicio con Windows (HKCU Run)
    ├── config.py          # constantes y rutas (soporta modo frozen)
    ├── settings.py        # app_settings.json
    ├── replacements.py    # replacements.json + categorías + pre/post processors
    ├── history.py         # history.json
    ├── beeps.py           # winsound async
    ├── audio_recorder.py  # sounddevice → numpy float32 (+ chunk_sink en vivo)
    ├── incremental.py     # transcripción incremental mientras grabas (cortes en silencios)
    ├── transcriber.py     # faster-whisper local (es / transcribe) + guardas anti-alucinación
    ├── typer.py           # pyperclip + Ctrl+V con guardia de modificadores
    ├── hotkeys.py         # hook global keyboard, rebindable
    ├── tray.py            # pystray + Pillow (usa icon.png)
    ├── floating_bar.py    # barra flotante de estado
    └── ui.py              # CustomTkinter, tabs, icono ventana
└── tests/
    └── manual_transcription_test.md  # guía de prueba manual de precisión
```

Configs y datos en runtime:

```
%APPDATA%\local-voice-typer\
├── app_settings.json
├── replacements.json
├── personal_replacements.json   # correcciones de nombres propios / marca
└── history.json
```
