# Fase 4 — evidencia del entregable 2b

**Estado al cerrar 2b:** implementado y verificado en local. **Actualización de producción, 2026-10-13:** Railway desplegó `main` en el servicio `garmin-coach` con el commit `d716acf` (deployment `6ddc5ccd-9e66-460b-bc4c-7d5a2d7e79d3`, 08:54 UTC) y luego el commit `58f0804da0097b714bb6078d47b6a1410d60e25c` (deployment `c8804358-91c8-4072-ad8d-6ae89ab42b8f`, 19:19:40 UTC); ambos deployments terminaron en `SUCCESS`. La migración manual se aplicó por túnel a las 22:16:53 CEST y la captura de la consulta que verificó el esquema se registró a las 22:19:53 CEST, después de ambos deployments. La consulta confirmó las cuatro columnas y la restricción; PostgreSQL de producción es 18.6. `COACH_DELAY_NOTICE_SECONDS` continúa sin valor activo y el barrido sigue apagado. `c8804358` es el prefijo del ID de deployment; el prefijo del commit desplegado es `58f0804`.

## Cambios incluidos

- Migración aditiva e idempotente que agrega cuatro columnas anulables y una restricción no negativa a `coach_ai_jobs`; no reescribe los documentos JSONB ni elimina datos.
- Reclamación PostgreSQL atómica de un trabajo cada vez, concesión de 120 segundos y máximo de tres intentos. Cada trabajo se prepara, envía y confirma antes de reclamar el siguiente. Un evento de parada se consulta antes de cada reclamación.
- Resumen factual genérico de actividades y mediciones recientes de bienestar (fecha, fuente y valores permitidos), además de la vigencia de sincronización. No usa texto libre del trabajo, no incluye identificadores internos ni produce recomendaciones.
- El envío es opcional y está apagado por defecto. La configuración inválida se registra y deja el barrido apagado sin tumbar la API. La API sigue respondiendo mientras el barrido síncrono opera en un hilo, con un límite total de 15 segundos para Telegram y límites PostgreSQL de 5 segundos de conexión, 10 segundos por consulta y 5 segundos por espera de bloqueo. El cierre señala la parada y espera a que termine la operación en curso antes de cerrar.
- El texto canónico `payload["answer"]` no recibe la nota de demora. La matriz complementaria modela API antigua/nueva y worker antiguo/nuevo; durante transiciones se acepta cero notas y la invariante principal evita dos.

## Evidencia de prueba

El backup anterior, usado en la primera restauración aislada, tenía 53 trabajos y SHA-256 `ebb6fa4995f381e9c40255b68b89e9eb32fd5acf1b6be84194c5ef945b2ec61`; no es el dump previo al DDL de producción. El dump correcto, creado el 2026-10-13 a las 22:06 CEST, mide 2.096.815 bytes, contiene 61 trabajos (60 `completed`, 1 `failed`) y tiene SHA-256 `c921afa6931678f97a889984998edc35cfb6c385d228fe395bd4beaf737d2e34`. Este dump se restauró de forma aislada en PostgreSQL 18.6; también se validó la migración con PostgreSQL 17 (`170011`, imagen `sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`). Los puertos de prueba se publicaron solo en loopback. La ejecución final previa usó la base `garmin_coach_f4_merge_test`.

En la validación del dump de 61 trabajos, los recuentos fueron 60 `completed` y 1 `failed`. En la restauración de ensayo se añadió un trabajo sintético `pending` (`synthetic-f4-2b-pending`, MD5 de documento `4b85779f528a028395b3951cd640e36e`) antes de migrar. La migración se ejecutó dos veces y las pruebas comprobaron columnas, tipos y restricción; preservó recuentos, relaciones, documentos y estados existentes. La evidencia no contiene preguntas, respuestas ni métricas de entrenamiento.

- Bot: 165 tests, todos OK, sin omisiones, contra el PostgreSQL restaurado.
- Worker: 292 tests, todos OK.
- Se verificaron lecturas y escrituras antiguas sobre el esquema migrado, columnas anulables, apagado por defecto, inicio con esquema ausente o base inaccesible, envío acotado, máximo de intentos, concurrencia, lote lento, respuesta webhook mientras el barrido está bloqueado y parada antes de nuevas reclamaciones. Una prueba adicional mantiene un bloqueo PostgreSQL durante una reclamación, señala la parada y verifica que la operación termina al aplicar el `lock_timeout`.
- Se verificó que las mediciones de bienestar con datos disponibles se muestran con fecha y fuente aunque el estado actual del proveedor sea de error; valores fuera de rango y fuentes no permitidas se omiten.
- La prueba de Telegram simula fases individuales por debajo de 15 segundos cuya suma excede el plazo total; la operación se cancela al alcanzar el plazo global.
- `git diff --check`: OK.

La matriz antigua/nueva es una simulación de presentadores y flujos, no una ejecución simultánea de dos versiones desplegadas. No se fabricaron trabajos ni mensajes de Telegram para probar avisos en producción. El deployment de código por sí solo no prueba que el DDL manual se aplicara; la consulta de producción a las 22:19:53 CEST sí confirmó las cuatro columnas y la restricción.

## Runbook de producción y estado

1. **Copia de producción — ejecutado.** Dump previo al DDL creado el 13/10/2026 a las 22:06 CEST; 2.096.815 bytes, 61 trabajos, SHA-256 `c921afa6931678f97a889984998edc35cfb6c385d228fe395bd4beaf737d2e34`. El hash antiguo `ebb6…` corresponde a otra copia de 53 trabajos.
2. **Restauración y comprobación aisladas — ejecutado.** Dumps restaurados sin conexión a producción en PostgreSQL 17 y 18.6. Se verificaron recuentos; en el ensayo se añadió antes de migrar un trabajo sintético pendiente. No se expuso contenido de consultas.
3. **Aplicar DDL en producción — ejecutado.** `20261012_add_delay_notice_columns.sql` aplicado por túnel el 13/10/2026; la captura de la salida `ALTER TABLE`/`DO` se registró a las 22:16:53 CEST. Fue después de los deployments de las 08:54 y 19:19:40 UTC.
4. **Verificar esquema y conservación — ejecutado.** Consulta de producción capturada a las 22:19:53 CEST: cuatro columnas con sus tipos esperados y la restricción `coach_ai_jobs_delay_notice_attempts_nonnegative`; la captura de recuentos a las 22:23:55 CEST mostró 60 `completed`, 1 `failed`. Servidor PostgreSQL 18.6.
6. **Medir por tipo y recalibrar — parcial; pendiente.** Para el motor V3 determinista hay tres trabajos de texto completados el 13/10: latencias `created_at`→`completed_at` con mediana 14,6 s y máximo observado 55,2 s (`n=3`). El análisis agregado del dump encontró 11 trabajos de voz históricos (ninguno con `output_source=deterministic`) y un `/ajustar` histórico con `output_source=deterministic_fallback`; no representan el motor actual. Antes de configurar un único umbral se recogerán al menos tres trabajos recientes de cada clase (texto V3, voz V3 y `/ajustar`) y se medirá espera de recogida, procesamiento —incluidas transcripción y síntesis cuando correspondan— y entrega. `90 s` es una referencia candidata basada solo en texto, no está configurada ni aprobada para voz o `/ajustar`.
7. **Activación del barrido — pendiente.** Requiere terminar el paso 6, fijar un umbral que cubra la clase más lenta con margen, verificar las cuatro columnas y recibir autorización explícita. Observar la primera entrega natural; apagar con valor vacío/`0` si se detecta un problema.

**Reversión:** poner `COACH_DELAY_NOTICE_SECONDS` en vacío/`0` y volver a una API compatible si hace falta. Conservar las columnas y sus valores; no ejecutar `DROP`.

## Estado de publicación y límites

El auto-despliegue desde `main` queda **confirmado en la práctica**: merges/pushes a `main` produjeron deployments de Railway, incluido el deployment `c8804358` (commit `58f0804`) a las 19:19:40 UTC. No hace falta inferirlo a partir de una inspección visual del panel. El repositorio de producción es `lloren27/garmin-coach`.

Los 90 segundos son solo una referencia candidata apoyada por tres muestras de texto V3; no están configurados. La recogida/entrega de voz y `/ajustar` aún no tienen muestras suficientes del motor activo. Los avisos tardíos continúan **no observados en producción**; se cubren con pruebas locales y no se fabricarán trabajos ni mensajes espontáneos.
