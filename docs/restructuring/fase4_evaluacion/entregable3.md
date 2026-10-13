# Fase 4, entregable 3 — evidencia E14

**Estado:** E14 parcial; la puerta de activación no se supera. El enrutamiento de alias sigue apagado. `/ultima` queda excluido del allowlist de migración y conserva su ruta local hasta resolver la selección de una actividad concreta cuando hay varias en el día más reciente.

## Evidencia local

- Fixture compartido: `tests/fixtures/coach_alias_e14_cases.json`, reloj fijo `Europe/Madrid` y contexto sintético `E01`.
- La resolución de las tres frases canónicas coincide con la intención, selector y fechas especificadas. Los casos con argumentos se conservan como texto original y el worker pide aclaración. Las paráfrasis se evalúan aparte: «última salida» sigue sin resolverse; es una limitación del texto libre, no de las frases canónicas.
- En la instantánea de una sola actividad, las tres respuestas usan hechos respaldados y no autorizan cambios. Esa instantánea por sí sola no distingue suficientemente los alias.
- Se añadió una prueba con dos deportes y dos sesiones previstas el mismo día. `/hoy` y `/feedback` mantienen los deportes separados, no suman escalas de carga distintas, explicitan que la correspondencia con el plan necesita confirmación y no proponen cambios.
- En esa misma instantánea, `/ultima` resuelve `analyze_activity/latest_activity`, pero el análisis no conserva la hora de inicio necesaria para escoger entre las actividades del día. Por seguridad descarta el ámbito y devuelve una aclaración genérica sin evidencia. No inventa cuál fue la última actividad, pero tampoco ofrece todavía el análisis concreto esperado por E14. El caso queda **no aprobado** para migración.
- No se probaron datos de producción, no se activó el interruptor y no se enviaron mensajes a usuarios.

## Verificación

- Worker: `cd apps/sync-local && /private/tmp/garmin-coach-fase4-3-venv/bin/python -m unittest tests.test_coach_alias_e14 -v` — 5 pruebas correctas, incluida la caracterización multideporte y la limitación de `/ultima`.
- Bot: `cd apps/bot && /private/tmp/garmin-coach-fase4-3-venv/bin/python -m unittest tests.test_coach_alias_e14 -v` — 7 pruebas correctas; comprueba que `/ultima` sigue en la ruta local incluso con el interruptor activo.
- Suites completas de bot/worker pendientes de la verificación integral del entregable 3.
- Resultado funcional: `/hoy` y `/feedback` tienen evidencia local favorable, todavía condicionada a la suite integral y al resto de las puertas de fase 5. El adaptador ya excluye `/ultima`, y una prueba verifica que no se encola por V3; su ruta local sigue disponible. E14 histórico sigue siendo parcial y no se afirma equivalencia global.

## Siguiente criterio para `/ultima`

El worker debe conservar una referencia temporal suficiente para identificar de forma determinista la actividad más reciente, o pedir una aclaración específica que enumere las candidatas de manera útil y permita elegir una. Después se debe repetir E14 con actividades de varios deportes en el mismo día y comprobar hechos, comparación con plan, límites y ausencia de permisos de escritura. Hasta entonces, la API conserva su ruta local para `/ultima` cuando se active el adaptador de los alias que sí superen sus puertas.

## Despliegue del worker compatible

- El 13/10/2026 se actualizó únicamente el LaunchAgent `com.lloren27.garmin-coach.ai-worker` para ejecutar `scripts/run_ai_worker.sh` desde la rama local `codex/fase4-3`. La sincronización Garmin y su watcher siguen apuntando al checkout habitual; Railway no se desplegó.
- El runner admite una raíz de proyecto, un intérprete Python y un `.env` separados. El LaunchAgent usa el código fuente del worktree, el entorno virtual ya instalado del checkout principal y el `.env` existente; no copia credenciales al worktree.
- El worker informó código de salida 0 tanto al arrancar como en el siguiente intervalo de 60 segundos. En ambas ejecuciones procesó cero trabajos; no se fabricaron consultas ni mensajes de prueba.
- `COACH_ANALYSIS_V3_ENABLED` permanece desactivado en el `.env` local. En Railway, `COACH_ALIAS_ROUTING_ENABLED` no está configurada para el servicio de producción, así que se conserva el valor por defecto desactivado. No se modificó ninguna de estas variables.
- Este despliegue acredita que el proceso periódico arranca con el código de la rama y el contrato compatible; no acredita una ejecución V3 real ni autoriza activar alias. El plist anterior quedó respaldado en `/private/tmp/fase4-3-ai-worker-plist-before.plist` para revertir el LaunchAgent si hiciera falta.
