# Prueba manual de transcripción — Wisip

Guía para medir la precisión de Wisip de forma reproducible. Todo es local; no
se usan APIs externas.

## 1. Texto de prueba (léelo en voz alta, hablando normal)

> Esta es una prueba completa de transcripción para Wisip. Voy a hablar rápido,
> pero quiero que la aplicación capture todo con buena precisión. Necesito que
> reconozca español, inglés y palabras técnicas dentro de la misma frase. Por
> ejemplo, estoy creando una aplicación de escritorio en Python que usa Whisper,
> faster-whisper, sounddevice, CustomTkinter, pyautogui, pyperclip y un hotkey
> global para pegar texto directamente en ChatGPT.
>
> También quiero probar términos como API, webhook, endpoint, backend, frontend,
> dashboard, login, JSON, MongoDB, Docker, Coolify, VPS, n8n, Shopify, WhatsApp,
> Rappi, SaaS, JavaScript, TypeScript, React, Next.js y Node.js. La idea es que
> Wisip no se corte cuando diga palabras en inglés dentro de una frase en español.
>
> Mi correo puede ser juanperez arroba hotmail punto com. También puedo
> dictar una URL como wisip punto ai slash dashboard o api punto wisip punto co
> slash v1 slash users.
>
> Necesito crear un webhook para Shopify que reciba una orden nueva, guarde la
> información en MongoDB, llame a una API externa, actualice el dashboard del
> restaurante y luego envíe un mensaje por WhatsApp usando Wasender. Después
> quiero que n8n procese el evento, valide los datos, cree un JSON limpio y lo
> mande al backend de mi SaaS.
>
> I need to create a new endpoint for the user dashboard. Pero quiero que la
> autenticación siga funcionando bien sin romper el login ni la sesión actual.
>
> Si se equivoca, quiero revisar si el problema viene del micrófono, del modelo,
> del idioma, del VAD, del initial prompt, de los reemplazos o de cómo se
> concatenan los segmentos de Whisper.

## 2. Frases objetivo (deben salir así)

1. `…Python que usa Whisper, faster-whisper, sounddevice, CustomTkinter, pyautogui, pyperclip y un hotkey global…`
2. `…la idea es que Wisip no se corte…`
3. `Mi correo puede ser juanperez@hotmail.com.`
4. `…una URL como wisip.ai/dashboard…`
5. `api.wisip.co/v1/users`
6. `…lo mande al backend de mi SaaS.`
7. `…React, Next.js y Node.js.`
8. `…del VAD, del initial prompt…`
9. `…sin romper el login ni la sesión actual.`

## 3. Checklist de errores frecuentes

- [ ] Librerías Python bien escritas (faster-whisper, sounddevice, CustomTkinter, pyautogui, pyperclip).
- [ ] `Wisip` (no "Wism", "Wisin", "Wisp").
- [ ] `Whisper` (no "Wisper").
- [ ] `Node.js` / `Next.js` (no "note.js" / "next.js").
- [ ] Email reconstruido: `juanperez@hotmail.com`.
- [ ] URLs: `wisip.ai/dashboard`, `api.wisip.co/v1/users` (slashes, no guiones).
- [ ] `VAD` reconocido (no "bad") en contexto técnico.
- [ ] `SaaS`, `sesión`, `autenticación` correctos.
- [ ] La frase mixta inglés/español no se corta.

## 4. Cómo probar con distintos modelos

- **base**: `"model": "base"` en `app_settings.json` (o dropdown MODELO). Rápido; menor precisión técnica.
- **small** (recomendado): `"model": "small"` o perfil **Balanceado**.
- **medium** (máxima calidad): `"model": "medium"` o perfil **Preciso**. Primera vez descarga ~1.5 GB; lento en CPU.

Reinicia la app tras editar el JSON. Lanza desde terminal (`python main.py`) para ver los logs.

## 5. Medir precisión aproximada

Cuenta errores por categoría sobre el texto transcrito:

| Categoría | Cómo contar | Meta |
|---|---|---|
| Texto normal (español) | Palabras mal vs total | > 98 % correcto |
| Términos técnicos | De la lista de §3, cuántos bien | ≥ 9/10 |
| Email / URL | Casos de §2 (3,4,5) que quedan exactos | 3/3 |
| Mezcla inglés/español | ¿La frase mixta queda completa y sin traducir? | Sí |

Precisión global ≈ `palabras_correctas / palabras_totales`. Para términos
técnicos y URLs, mide por aciertos de la checklist, no por palabra.

## 6. Validar el postprocesado sin grabar

```powershell
python scripts\check_replacements.py
```

Corre frases por el pipeline de reemplazos/parser e indica qué mejora y qué
NO debe romperse. Útil tras editar `replacements.json` o `personal_replacements.json`.

## 7. Si algo sale mal

- Palabra técnica mal oída → agrégala al **Prompt inicial** y/o a `replacements.json`.
- Nombre propio mal oído → agrégalo a `personal_replacements.json`.
- URL/email raro → revisa los logs `[url/email]` (con `debug_replacements: true`).
- Frase que se corta → revisa los logs `[whisper.seg …]` (con `debug_segments: true`).
- Calidad insuficiente en general → sube a `medium`.
