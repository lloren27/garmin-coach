# Fase 4, entregable 3 — evidencia E14

**Estado:** V3 está activado en el worker local del Mac y se ha observado en respuestas de producción. E14 sigue parcial y la puerta de migración de alias no se supera; el enrutamiento de alias continúa apagado. `/ultima` queda excluido del allowlist de migración y conserva su ruta local hasta resolver la selección de una actividad concreta cuando hay varias en el día más reciente.

## Evidencia local

- Fixture compartido: `tests/fixtures/coach_alias_e14_cases.json`, reloj fijo `Europe/Madrid` y contexto sintético `E01`.
- La resolución de las tres frases canónicas coincide con la intención, selector y fechas especificadas. Los casos con argumentos se conservan como texto original y el worker pide aclaración. Las paráfrasis se evalúan aparte: «última salida» sigue sin resolverse; es una limitación del texto libre, no de las frases canónicas.
- En la instantánea de una sola actividad, las tres respuestas usan hechos respaldados y no autorizan cambios. Esa instantánea por sí sola no distingue suficientemente los alias.
- Se añadió una prueba con dos deportes y dos sesiones previstas el mismo día. `/hoy` y `/feedback` mantienen los deportes separados, no suman escalas de carga distintas, explicitan que la correspondencia con el plan necesita confirmación y no proponen cambios.
- En esa misma instantánea, `/ultima` resuelve `analyze_activity/latest_activity`, pero el análisis no conserva la hora de inicio necesaria para escoger entre las actividades del día. Por seguridad descarta el ámbito y devuelve una aclaración genérica sin evidencia. No inventa cuál fue la última actividad, pero tampoco ofrece todavía el análisis concreto esperado por E14. El caso queda **no aprobado** para migración.
- La prueba con fixtures no usa datos de producción. Después sí se ejercitó V3 con consultas reales del usuario; no se fabricaron mensajes ni trabajos de prueba.

## Activación y observación de V3 en producción

- La Fase 3 había dejado la activación de `COACH_ANALYSIS_V3_ENABLED` pendiente de una autorización aparte. El 13/10/2026, después de comprobar `/estado` con origen de respuesta antiguo, el usuario autorizó explícitamente: «Ok vamos a habilitar y verificar V3».
- El `.env` del Mac contiene ahora `COACH_ANALYSIS_V3_ENABLED=1`. La hora exacta en que se editó la variable no quedó registrada; la primera evidencia observable es una respuesta completada el 13/10/2026 a las 19:53 CEST con origen `V3 determinista`. `/estado` volvió a mostrar ese origen a las 22:17 CEST.
- Una consulta `/coach` real produjo una respuesta factual y el worker completó el trabajo con `output_source=deterministic`. Esto prueba ejecución real de V3 sobre el contexto de producción, no la calidad general de sus respuestas.
- Las consultas naturales de prueba reportadas después muestran límites del resolutor: varias terminan en aclaración genérica. En audio se recibió voz sintetizada con esa misma aclaración; la entrega TTS funcionó, pero la transcripción de esos audios no se ha verificado.
- `COACH_ALIAS_ROUTING_ENABLED` sigue apagado en Railway. La evidencia de V3 activo no habilita por sí sola los alias ni supera E14.

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
- `COACH_ANALYSIS_V3_ENABLED=1` está configurado en el `.env` local del Mac por la autorización del usuario registrada arriba. En Railway, `COACH_ALIAS_ROUTING_ENABLED` permanece sin configurar y, por tanto, apagado por defecto. No se cambió la configuración de alias.
- El despliegue del worker compatible acreditó el arranque del proceso periódico; las consultas reales completadas más tarde y el campo de `/estado` acreditan además ejecución V3. El plist anterior quedó respaldado en `/private/tmp/fase4-3-ai-worker-plist-before.plist` para revertir el LaunchAgent si hiciera falta.
