# Reporte del bot de UI — Wisip

- Acciones probadas: **68**  ·  OK: **68**  ·  Con error: **0**

## Fase A — Widgets de la UI

| Estado | Acción |
|---|---|
| ✅ | IDIOMA = Español |
| ✅ | IDIOMA = Inglés |
| ✅ | IDIOMA = Auto |
| ✅ | MODO = paste |
| ✅ | MODO = copy_only |
| ✅ | PERFIL = Rápido |
| ✅ | PERFIL = Balanceado |
| ✅ | PERFIL = Preciso |
| ✅ | PERFIL = Personalizado |
| ✅ | MODELO = tiny |
| ✅ | MODELO = base |
| ✅ | MODELO = small |
| ✅ | MODELO = medium |
| ✅ | RENDIMIENTO = Calidad actual |
| ✅ | RENDIMIENTO = Rápido seguro |
| ✅ | RENDIMIENTO = Máxima velocidad local |
| ✅ | RENDIMIENTO = Personalizado |
| ✅ | BEEP toggle |
| ✅ | REEMPLAZOS toggle |
| ✅ | ATAJO ACTIVO toggle |
| ✅ | IDIOMA MIXTO toggle |
| ✅ | INICIAR CON WINDOWS toggle |
| ✅ | INICIAR MINIMIZADA toggle |
| ✅ | PROMPT INICIAL activo toggle |
| ✅ | GUARDAR PROMPT |
| ✅ | Botón principal (toggle) |
| ✅ | Botón 👆 (rebind) |
| ✅ | Chrome minimizar |
| ✅ | Chrome cerrar (X) |
| ✅ | invoke() botón principal |
| ✅ | invoke() botón rebind |
| ✅ | invoke() botón minimizar |
| ✅ | Tab Historial |
| ✅ | Tab Transcribe |
| ✅ | Historial COPIAR/PEGAR/LIMPIAR |
| ✅ | set_status/backend/elapsed/transcription/button |
| ✅ | callbacks invocados: ['beep', 'close', 'h_clear', 'h_copy', 'h_paste', 'hotkey', 'ip_save', 'ip_toggle', 'language', 'mixed', 'model', 'paste_mode', 'perf', 'quality', 'rebind', 'replacements', 'start_min', 'start_win', 'toggle'] |

## Fase B — Handlers del Controller

| Estado | Acción |
|---|---|
| ✅ | Construcción del Controller |
| ✅ | _on_language_change('en') |
| ✅ | _on_language_change('es') |
| ✅ | _on_paste_mode_change(copy_only) |
| ✅ | _on_paste_mode_change(paste) |
| ✅ | _on_beep_toggle(False/True) |
| ✅ | _on_replacements_toggle |
| ✅ | _on_mixed_language_toggle |
| ✅ | _on_initial_prompt_toggle |
| ✅ | _on_initial_prompt_save |
| ✅ | _on_hotkey_toggle |
| ✅ | _on_start_with_windows_toggle |
| ✅ | _on_start_minimized_toggle |
| ✅ | _on_history_copy |
| ✅ | _on_history_paste |
| ✅ | _on_history_clear |
| ✅ | _tray_show |
| ✅ | _tray_hide |
| ✅ | _on_hotkey_rebind_request |
| ✅ | _on_quality_profile_change(fast) |
| ✅ | _on_quality_profile_change(balanced) |
| ✅ | _on_quality_profile_change(accurate) |
| ✅ | _on_model_change(tiny) |
| ✅ | _on_model_change(base) |
| ✅ | _on_model_change(small) |
| ✅ | _on_model_change(medium) |
| ✅ | _on_perf_profile_change(quality_current) |
| ✅ | _on_perf_profile_change(fast_safe) |
| ✅ | _on_perf_profile_change(max_speed) |
| ✅ | _on_perf_profile_change(perf_custom) |
| ✅ | Ciclo grabar→transcribir→pegar (botón) |
