# Prueba manual — correos, URLs y símbolos (Wisip)

Valida el **postprocesador dedicado** (`app/postprocessor.py`) que corre después
de los reemplazos y antes de pegar. Todo es local; no usa APIs externas.

## Cómo correrlo sin grabar

```powershell
python scripts/check_normalizer.py
```

Corre la **cadena completa** (igual que la app):
`texto → Replacements.apply() → normalize_emails_urls_symbols()`
e imprime entrada → salida marcando los casos que mejoran y los que NO deben romperse.

## Cómo correrlo con voz real

Dicta cada frase con el hotkey y verifica el texto pegado. Los logs muestran el
detalle si pones en `app_settings.json`: `"debug_normalizer": true`.

## Configuración relevante (`app_settings.json`)

| Clave | Default | Qué hace |
|---|---|---|
| `normalize_emails_urls` | `true` | Interruptor maestro del normalizador. `false` lo desactiva. |
| `debug_normalizer` | `false` | Loguea texto antes/después y reglas aplicadas. |
| `technical_symbol_mode` | `false` | Convierte "arroba" suelta en prosa a `@` (agresivo). |
| `email_as_markdown` | `false` | Envuelve correos en `[correo](mailto:correo)`. |

## Alias de correo (opcional, por usuario)

El archivo `%APPDATA%\local-voice-typer\personal_emails.json` (se crea vacío)
permite mapear formas mal oídas de TU nombre a TU correo. **No hay datos
personales en el código** (la app es pública). Ejemplo:

```json
{
  "personal_emails": { "main": "tu_correo@dominio.com" },
  "email_aliases": ["tunombre", "tu nombre", "tu nombre mal oido"]
}
```

## Casos de prueba

### Correos — deben funcionar
| # | Dictado / transcrito | Resultado esperado |
|---|---|---|
| 1 | "Mi correo es juanperez arroba hotmail punto com." | `juanperez@hotmail.com` |
| 2 | "Mi correo es juan perez arroba hotmail punto com." | `juanperez@hotmail.com` |
| 3 | "Mi correo puede ser erejuanperez-hotmail.com." | `juanperez@hotmail.com` |
| 4 | "El email es juanperez @ hotmail . com." | `juanperez@hotmail.com` |
| 5 | "Escríbeme a juanperez@ hotmail.com." | `juanperez@hotmail.com` |
| 6 | "Mi correo es juanperez @hotmail .com." | `juanperez@hotmail.com` |

> Los casos 1-6 que canonizan a `juanperez@hotmail.com` dependen de tus
> alias en `personal_emails.json`. La regla **genérica** funciona para cualquiera:

| # | Transcrito | Resultado esperado (sin configurar nada) |
|---|---|---|
| 7 | "Mi correo es soporte-gmail.com." | `soporte@gmail.com` |
| 8 | "Escríbeme a ventas arroba outlook punto com." | `ventas@outlook.com` |

Proveedores reconocidos para el guion→@: **hotmail.com, gmail.com, outlook.com,
yahoo.com, icloud.com**.

### URLs — deben seguir funcionando
| # | Transcrito | Resultado esperado |
|---|---|---|
| 9 | "Abre wisip punto ai slash dashboard." | `wisip.ai/dashboard` |
| 10 | "La URL es api punto wisip punto co slash v1 slash users." | `api.wisip.co/v1/users` |
| 11 | "También puedo dictar api.wisip.cov-v1-users." | `api.wisip.co/v1/users` |
| 12 | "Una URL como wisip.ai-dashboard." | `wisip.ai/dashboard` |

### NO deben romperse (texto normal)
| # | Frase | Debe quedar igual |
|---|---|---|
| 13 | "Esto es una frase normal con guion medio y no debería cambiarse." | sin `@`, sin cambios |
| 14 | "Tengo una arquitectura cliente-servidor con micro-servicios." | guiones intactos |
| 15 | "Vamos directo al punto importante. Es la reunión de hoy." | NO `importante.es` (no se pega el inicio de frase) |

## Criterios de éxito (estado actual)

Verificado con `scripts/check_normalizer.py`: **18/18 casos correctos**.

1. ✅ `erejuanperez-hotmail.com` → `juanperez@hotmail.com` (con alias).
2. ✅ `juanperez arroba hotmail punto com` → `juanperez@hotmail.com`.
3. ✅ `api punto wisip punto co slash v1 slash users` → `api.wisip.co/v1/users`.
4. ✅ `wisip punto ai slash dashboard` → `wisip.ai/dashboard`.
5. ✅ No se dañan frases normales con guiones (ni puntos de fin de frase).
6. ✅ No se tocó el modelo, ni grabación, ni hotkeys, ni el pegado.
7. ✅ Se desactiva con `normalize_emails_urls: false`.
