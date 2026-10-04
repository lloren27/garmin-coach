# Inventario del flujo actual

Generado a partir del AST de `apps/bot/app/main.py`; la columna de escritura indica llamadas potenciales, no efectos de todas las variantes.

| Entrada | Línea | Destino | IA | Posibles escrituras |
| --- | --- | --- | --- | --- |
| /start / /help | 427 | format_help | No | Ninguna directa |
| /plan_semana / /plan | 430 | build_week_plan, format_training_plan, load_checkins, save_training_plan | No | save_training_plan |
| /hoy | 453 | format_today | No | Ninguna directa |
| /semana | 455 | format_week, load_checkins | No | Ninguna directa |
| /ultima | 457 | format_latest | No | Ninguna directa |
| /proximo | 459 | format_next, load_checkins | No | Ninguna directa |
| /fatiga | 461 | format_fatigue, load_wattwise | No | Ninguna directa |
| /salud | 463 | format_health | No | Ninguna directa |
| /carga | 465 | format_load, load_wattwise | No | Ninguna directa |
| /running / /correr / /carga_running | 467 | format_running | No | Ninguna directa |
| /tendencia | 469 | format_trend, load_sync_history | No | Ninguna directa |
| /feedback | 471 | format_feedback, load_checkins, load_wattwise | No | Ninguna directa |
| /ajustar | 473 | create_ai_job, format_ai_queued | Sí | create_ai_job |
| /bici | 476 | format_bike, load_wattwise | No | Ninguna directa |
| /potencia / /wattwise | 478 | format_wattwise, load_wattwise | No | Ninguna directa |
| /malaga | 480 | format_malaga | No | Ninguna directa |
| /coach | 482 | create_ai_job, format_ai_help, format_ai_queued | Sí | create_ai_job |
| /sync | 487 | format_sync_requested, save_sync_request | No | save_sync_request |
| /perfil | 498 | any, format_profile, format_profile_help, format_profile_saved, merge_profile, parse_profile, save_profile | No | save_profile |
| /prueba_esfuerzo | 507 | format_lab_test_help | No | Ninguna directa |
| /pruebas | 509 | format_lab_tests, load_lab_tests | No | Ninguna directa |
| /ver_prueba | 511 | format_lab_test, load_lab_tests, load_pending_lab_test | No | Ninguna directa |
| /zonas | 513 | format_zones, load_lab_tests, load_pending_lab_test | No | Ninguna directa |
| /aplicar_prueba | 515 | dict, find_lab_test_for_apply, format_lab_test_applied, mark_lab_test_applied, merge_profile, save_profile, str | No | mark_lab_test_applied, save_profile |
| /corregir_prueba | 527 | format_lab_test_corrected, format_lab_test_correction_help, parse_lab_test_correction, split_optional_lab_test_id, update_lab_test | No | update_lab_test |
| /descartar_prueba | 536 | discard_lab_test, format_lab_test_discarded | No | discard_lab_test |
| /checkin | 540 | format_checkin_help, format_checkin_saved, parse_checkin, save_checkin | No | save_checkin |
| /fuerza | 545 | handle_strength_command, load_strength_state, save_strength_state | No | handle_strength_command, save_strength_state |
| /status | 556 | format_status | No | Ninguna directa |
| /syncinfo | 558 | format_syncinfo, load_sync_request | No | Ninguna directa |
| / | 560 | create_ai_job, format_ai_queued | Sí | create_ai_job |

Texto libre: crea trabajo IA. Voz: el webhook crea trabajo con audio_file_id; la transcripción se realiza en el Mac. Adjuntos PDF/DOCX: trabajo de prueba deportiva, no consulta deportiva ordinaria.

## Generadores y contratos

| Elemento | Quién lo llama | Responsabilidad / solapamiento | Estado |
| --- | --- | --- | --- |
| `sync.recommend_next_workout` | `build_payload` | Sugerencia calculada a partir de carga/calendario; otro origen de recomendación | Se publica en snapshot |
| `coach.format_feedback`, `format_next`, `format_week`, `format_adjust` | Enrutador / `build_ai_brief` según función | Valoraciones y recomendaciones deterministas que conviven con Ollama | Depende de la función |
| `coach.build_week_plan` | `/plan`, `/plan_semana` | Genera plan; el enrutador lo guarda incluso al consultar | Escribe vía `save_training_plan` |
| `ai_worker.compact_context` | `call_ollama` | Reduce actividades, historial, bienestar y plan antes de validar | Sin persistencia propia |
| `coach_generation_context.build_snapshot` | `generate_validated` | Filtra hechos, fechas, fuentes y permisos | Instantánea inmutable |
| `coach_generation_pipeline` | `ai_worker.call_ollama` | Modelo + reparación acotada | Sin I/O salvo callback |
| `coach_generation_resolver` / `renderer` | Pipeline | Resuelve decisiones y produce frases canónicas | Sin persistencia |
| `ai_worker._validate_ollama_response` | Ruta antigua / pruebas | Valida contrato con answer; no es el pipeline que usa call_ollama hoy | Duplicación de rutas a revisar |
| `app.ai_contracts` / `garmin_sync.ai_contracts` | Bot / worker | Dos copias del contrato público | Hashes en referencia.json |
| `coach_generation_contracts` | Pipeline | Contrato interno distinto, sin answer libre | No debe confundirse con duplicación accidental |
| `store` / repositorios de propuestas | API y enrutador | Ficheros o PostgreSQL; permisos y revisiones | Persistencia |

## Contradicciones con documentación

- README: afirma un único flujo para comandos deportivos; E14 demuestra que `/feedback` no crea trabajo IA. Las pruebas existentes incluso exigen respuestas directas para estos comandos.
- README: describe explicación en prosa de Ollama; el pipeline vigente prohíbe `answer` y el renderer compone el texto.
- `docs/coach-validation.md`: indica implementación pendiente de integración; el checkout main auditado contiene el pipeline. No se ha atestiguado el commit activo de Railway.

## Lecturas con efectos potenciales

- `GET /ai/jobs/next` reclama un trabajo y prepara permisos: no usar para inspección.
- `GET /status` y `/history` llaman loaders PostgreSQL que ejecutan `ensure_schema`. La función sale tras un SELECT cuando detecta la migración; en otros estados puede ejecutar DDL. Sin conocer el esquema remoto no se ha llamado a estas rutas.
