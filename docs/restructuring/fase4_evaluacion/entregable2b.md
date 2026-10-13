# Fase 4 — evidencia del entregable 2b

**Estado:** implementado y verificado en local, en la rama `fase4-2b`. No desplegado ni activado en producción. `COACH_DELAY_NOTICE_SECONDS` no está configurado en Railway según la lectura de configuración disponible; el valor por defecto mantiene el barrido apagado.

## Cambios incluidos

- Migración aditiva e idempotente que agrega cuatro columnas anulables y una restricción no negativa a `coach_ai_jobs`; no reescribe los documentos JSONB ni elimina datos.
- Reclamación PostgreSQL atómica de un trabajo cada vez, concesión de 120 segundos y máximo de tres intentos. Cada trabajo se prepara, envía y confirma antes de reclamar el siguiente. Un evento de parada se consulta antes de cada reclamación.
- Resumen factual genérico de datos recientes y vigencia de sincronización. No usa texto libre del trabajo, no incluye identificadores internos ni produce recomendaciones.
- El envío es opcional y está apagado por defecto. La configuración inválida se registra y deja el barrido apagado sin tumbar la API. La API sigue respondiendo mientras el barrido síncrono opera en un hilo, con un límite total de 15 segundos para Telegram.
- El texto canónico `payload["answer"]` no recibe la nota de demora. La matriz complementaria modela API antigua/nueva y worker antiguo/nuevo; durante transiciones se acepta cero notas y la invariante principal evita dos.

## Evidencia de prueba

La copia de seguridad de producción usada exclusivamente para la restauración aislada tuvo SHA-256 `ebb6fa4995f381e9c40255b68b89e9eb32fd5acf1b6be84194c5ef945b2ec61`. Se restauró en un contenedor PostgreSQL desechable propio, `codex-f4-2b-pg-20261013`, imagen PostgreSQL 17 (`sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`), versión `170011`, base `garmin_coach_f4_2b_test`, puerto publicado solo en `127.0.0.1:55439`.

Antes de la migración, la copia restaurada tenía 53 trabajos, 0 cambios pendientes y 0 trabajos pendientes. Se añadió un único trabajo sintético pendiente con identidad `synthetic-f4-2b-pending` y MD5 de documento `4b85779f528a028395b3951cd640e36e`. La migración se ejecutó dos veces y las pruebas comprobaron columnas, tipos y restricción; preservó los recuentos, relaciones, documentos y estados existentes. El artefacto de evidencia no conserva contenido de consultas, respuestas ni métricas de entrenamiento.

- Bot: 160 tests, todos OK, sin omisiones, contra el PostgreSQL restaurado.
- Worker: 292 tests, todos OK.
- Se verificaron lecturas y escrituras antiguas sobre el esquema migrado, columnas anulables, apagado por defecto, inicio con esquema ausente o base inaccesible, envío acotado, máximo de intentos, concurrencia, lote lento, respuesta webhook mientras el barrido está bloqueado y parada antes de nuevas reclamaciones.
- La prueba de Telegram simula fases individuales por debajo de 15 segundos cuya suma excede el plazo total; la operación se cancela al alcanzar el plazo global.
- `git diff --check`: OK.

La matriz antigua/nueva es una simulación de presentadores y flujos, no una ejecución simultánea de dos versiones desplegadas. No se generaron mensajes de Telegram en producción. No hubo DDL, cambios de configuración, push ni despliegue en producción.

## Runbook de futura publicación

1. Confirmar aprobación para desplegar y obtener una copia de seguridad nueva de producción. Guardar su identidad y hash; no inspeccionar ni copiar contenido de entrenamiento a la evidencia.
2. Restaurar la copia en una instancia aislada y verificar recuentos y relaciones antes de migrar. Mantener el productor apagado.
3. Aplicar `apps/bot/migrations/20261012_add_delay_notice_columns.sql` en producción mediante el procedimiento de cambio aprobado.
4. Verificar las cuatro columnas, sus tipos, la restricción `coach_ai_jobs_delay_notice_attempts_nonnegative` y los recuentos de trabajos. Confirmar que los trabajos existentes conservan datos y estado.
5. Desplegar la API compatible con el esquema, con `COACH_DELAY_NOTICE_SECONDS` vacío o en `0`. Confirmar salud de la API y operación normal; ante fallo, dejar el barrido apagado y revertir el código manteniendo las columnas.
6. Observar trabajos normales y medir recogida, ejecución y entrega del motor realmente activo. Recalibrar `COACH_DELAY_NOTICE_SECONDS` usando esas medidas antes de considerar activar avisos.
7. Solo en un cambio posterior, tras autorización y observación suficiente, activar el barrido con un umbral explícito dentro del rango admitido. Confirmar que la configuración y el esquema son válidos, observar el primer comportamiento natural y apagar con valor vacío/`0` si hay anomalías.
8. En cualquier reversión, apagar la configuración y volver al código compatible anterior. Conservar las columnas y sus valores; no ejecutar `DROP` como parte del rollback.

## Estado de publicación y límites

La rama local `fase4-2b` parte de `main` en `7cacfecad291d9343911f6f2629b6849d5c6b676`, que ya contiene los entregables 1 y 2a desplegados y observados. Railway identifica `lloren27/garmin-coach` y la rama `main` como origen del servicio de producción. La conexión de fuente indica despliegue al recibir pushes; no se pudo verificar visualmente el interruptor específico del panel, así que se ha tratado cualquier push como despliegue. El trabajo permanece local y sin publicar.

Los 150 segundos son solo una referencia inicial, no una latencia calibrada. Se deben medir recogida, ejecución y entrega con el motor activo antes de activar el aviso. El comportamiento de avisos tardíos queda **no observado en producción** y cubierto por pruebas locales; no se fabricarán trabajos de prueba ni mensajes espontáneos para validarlo.
