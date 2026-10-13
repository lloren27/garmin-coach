# Fase 4, entregable 2b — migración, vistas factuales y avisos — Plan de implementación

> **Para agentes de implementación:** Habilidad requerida: `superpowers:executing-plans` (ejecución nativa en esta sesión, sobre la rama local `fase4-2b`, excepción a la preferencia anterior por `main` para mantenerla desplegable). La rama parte del `main` local en `7cacfecad291d9343911f6f2629b6849d5c6b676`, que contiene los entregables 1 y 2a ya desplegados y observados en producción. Completar cada tarea en orden y marcar las casillas.

**Goal:** Añadir estado persistente compatible para avisos demorados, presentar un respaldo factual fechado y enviar como máximo tres avisos por trabajo mediante un barrido PostgreSQL apagado por defecto.

**Architecture:** La API Railway es la única que reclama y envía avisos. El código de 2b y sus commits quedan en la rama local `fase4-2b`; no se publica ni se empuja a GitHub hasta revisar el runbook y autorizar el despliegue. PostgreSQL mantiene las marcas de concesión y contador en columnas aditivas de `coach_ai_jobs`; las respuestas y trabajos existentes siguen usando su documento JSONB sin contenido de aviso. Solo tres operaciones de store leen/escriben los valores de esas columnas; la comprobación de arranque inspecciona únicamente el catálogo de PostgreSQL. Un formateador puro genera la vista factual genérica a partir de datos existentes, con parámetro `scope`, sin invocar el resolutor deportivo ni emitir opiniones. Un ciclo de vida de FastAPI lanza el barrido en un hilo solo cuando la configuración es válida/positiva y el esquema está listo. El barrido reclama un trabajo, lo procesa y confirma o deja caducar su concesión antes de reclamar el siguiente; el lease de 120 s no se consume mientras espera detrás de otros envíos.

**Tech Stack:** Python 3, FastAPI lifespan, PostgreSQL/psycopg 3, httpx, `unittest`, Telegram Bot API. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-11-fase4-experiencia-design.md`, decisiones 1 y entregable 2b. Prerrequisito observado: `docs/restructuring/fase4_evaluacion/entregable2a.md`.

## Global Constraints

- `COACH_DELAY_NOTICE_SECONDS` está vacío/0 por defecto. Valores negativos, no enteros o mayores de 604800 (7 días) registran un error claro y dejan el barrido desactivado; nunca impiden iniciar la API.
- El aviso se limita a trabajos PostgreSQL en `pending` o `running`, nunca `lab_test`; el modo archivo no reclama ni envía avisos.
- Concesión PostgreSQL de 120 segundos; cada reclamación individual consume un intento; máximo 3 intentos por trabajo. Reclamar de uno en uno y enviar/confirmar antes de la siguiente reclamación; lote máximo de 20 trabajos por ciclo, sin leases simultáneos.
- Envío con plazo total de 15 segundos, sin reintento HTTP interno; confirmar `delay_notified_at` después de respuesta HTTP satisfactoria y JSON `ok=true`.
- Antes de enviar, comprobar que el token sigue siendo propio, que quedan al menos 15 segundos de concesión y que el trabajo continúa abierto.
- En operación normal se exige exactamente un aviso por trabajo demorado. Aceptar cero durante transiciones de versión y hasta dos duplicados ante fallos de confirmación, acotados por tres intentos.
- El aviso incluye la fecha y antigüedad de la última sincronización y una vista factual pertinente; para texto libre, `/coach`, voz, `/ajustar` y alias con argumentos usa «Últimos datos disponibles».
- En 2b el aviso usa solo el resumen genérico `scope="latest_available"`. El formateador es puro y recibe `scope`; la selección fija de `/hoy`, `/ultima` y `/feedback` no se cablea ni persiste hasta el entregable 3. No copiar `coach_intent` al bot ni reutilizar formateadores que incluyan opinión.
- No cambiar recomendaciones, respuestas estructuradas, procesamiento del worker, alias, V3 ni mensajes de producción durante esta implementación. En 2b solo se cablea el resumen factual genérico; la persistencia de un ámbito de alias queda para el contrato de 3.
- Migración aditiva: restaurar el backup real en PostgreSQL aislado antes de alterar esquema; no ejecutar DDL en Railway/producción. Mantener todos los commits locales y no empujar a GitHub hasta tener revisado el runbook. Railway muestra `lloren27/garmin-coach`, branch `main`, como fuente; el conector indica despliegue al recibir pushes. La configuración consultada no expone el toggle explícito del panel, que no se pudo verificar visualmente. Se asume auto-deploy por prudencia.

## Review Focus

- Filas antiguas y pendientes con columnas nulas sobreviven a migración y escritores posteriores: prueba de backup restaurado, conteos, relaciones, documentos y trabajo pendiente.
- Dos o más procesos no reclaman el mismo trabajo en operación normal: prueba concurrente PostgreSQL que verifica exactamente un envío aceptado.
- Caída después de enviar o antes de confirmar no crea reintentos ilimitados: pruebas de leases caducados y máximo tres intentos.
- Una finalización que compite con el barrido no produce un aviso tardío ni modifica el trabajo: prueba de carrera con `completed`/`failed`.
- Configuración 0, almacenamiento JSON, datos faltantes, fechas/fuentes antiguas o Telegram no confirmando no activan envíos ni fabrican vigencia: pruebas negativas con transporte simulado y fixtures.

---

### Tarea 0: PostgreSQL aislado y restauración real del backup

**Files:** Crear evidencia temporal bajo `.superpowers/sdd/2026-10-12-fase4-entregable2b/`; no modificar datos ni configuración de producción ni imprimir contenido del dump restaurado.

**Interfaces:** Reutilizar `backup-audit/garmin-coach-production.dump` (SHA-256 registrado en `docs/restructuring/fase1_progreso.md`); ejecutar las pruebas del bot con `P03_TEST_DATABASE_URL` exclusivamente hacia la instancia de esta tarea.

- [x] Confirmar que el backup existe y su SHA-256 es `ebb6fa4995f381e9c40255b68b89e9eb32fd5acf1b6be84194c5ef945b2ec61`.
- [x] Solicitar acceso local al runtime de contenedores si el sandbox no permite su socket. Crear un PostgreSQL desechable dedicado, ligado a loopback, verificar identidad, puerto, base y versión antes de conectar.
- [x] Restaurar el backup en una base vacía de ese contenedor. No reutilizar contenedores ajenos y no conectar a `DATABASE_URL` de producción.
- [x] Verificar solo conteos e identidades de recursos: el backup conocido contiene 53 trabajos y 0 cambios pendientes. No mostrar preguntas, respuestas ni valores de entrenamiento restaurados en terminal/logs/evidencia. Si los conteos reales difieren, registrarlos sin contenido y detener operaciones destructivas.
- [x] Insertar un trabajo sintético `pending` después de restaurar y antes de migrar; etiquetarlo claramente y limitar toda comparación a conteos, estado, IDs sintéticos y hashes de documentos, sin volcar documentos reales.
- [x] Ejecutar la suite completa actual del bot con `P03_TEST_DATABASE_URL` y cero omisiones; guardar salida y baseline.
- [x] No continuar a tareas de esquema si restauración, aislamiento o suite de referencia no quedan demostrados.

### Tarea 1: migración aditiva y compatibilidad de lectores

**Files:** Crear `apps/bot/migrations/20261012_add_delay_notice_columns.sql`; crear/expandir `apps/bot/tests/test_delay_notice_migration.py`; actualizar `docs/restructuring/fase4_evaluacion/entregable2b.md` al finalizar.

**Interfaces:** Añadir columnas anulables `delay_notified_at timestamptz`, `delay_notice_claimed_at timestamptz`, `delay_notice_claim_token text` y `delay_notice_attempts integer` a `coach_ai_jobs`. Restringir el contador con `CHECK (delay_notice_attempts IS NULL OR delay_notice_attempts >= 0)`; `NULL` equivale a cero. No inicializar ni reescribir documentos JSONB. El runtime toca valores de estas columnas exclusivamente en `claim_next_delay_notice_job`, `prepare_delay_notice_send` y `mark_delay_notice_sent`; la sonda inicial consulta solo `information_schema`/catálogo para verificar que existan.

- [x] Escribir pruebas que apliquen la migración dos veces, comprueben columnas/tipos/constraint, y comparen antes/después los conteos, IDs sintéticos, relaciones y un trabajo sintético `pending` insertado antes del DDL. Confirmar que las columnas nuevas quedan `NULL` en las filas viejas. No imprimir ni guardar contenido de consultas, respuestas o entrenamientos reales.
- [x] Ejecutar las pruebas con el PostgreSQL restaurado y observar fallo por migración ausente.
- [x] Implementar SQL idempotente solo para cuatro columnas/constraint; no añadir índices sin demostrar necesidad ni modificar columnas de contenido.
- [x] Añadir un test de compatibilidad: `complete_ai_job_postgres`, `claim_next_ai_job_postgres` y lecturas existentes preservan las marcas de aviso mientras actualizan el documento. Modelar un documento previo que carece de las nuevas claves.
- [x] Mantener el lector tolerante a columnas `NULL`/ausentes en el contrato de dominio. El productor de trabajos no empieza a poblar marcas hasta que el lector y la migración están aplicados.
- [x] Ejecutar focalizada y suite completa bot con PostgreSQL restaurado; ningún test PostgreSQL omitido.
- [ ] Commit local en `fase4-2b`: `feat: add delay notice schema migration`; no hacer push.

### Tarea 2: operaciones PostgreSQL atómicas de aviso

**Files:** Modificar `apps/bot/app/store.py`; crear o ampliar `apps/bot/tests/test_delay_notice_store.py`.

**Interfaces:**
- `claim_next_delay_notice_job(*, threshold_seconds: int) -> DelayNoticeClaim | None` usa el reloj PostgreSQL y reclama como máximo un trabajo elegible; incrementa el contador al reclamar y devuelve `job_id`, `chat_id`, `source_kind`, `created_at`, `claimed_at`, `claim_token` y datos mínimos para preparar el aviso. No hay una lista de claims preasignados.
- `prepare_delay_notice_send(job_id: str, claim_token: str) -> DelayNoticeClaim | None` confirma token propio, trabajo todavía `pending`/`running`, no notificado, con intento consumido y ≥15 s de concesión restante.
- `mark_delay_notice_sent(job_id: str, claim_token: str) -> bool` escribe `delay_notified_at` y limpia la concesión solo si el propietario conserva el token y el trabajo sigue abierto.

- [x] Añadir pruebas RED de selección por umbral exacto, exclusión de `completed`/`failed`/`lab_test`, contador nulo como cero, y tope de tres reclamaciones aun después de caducar el lease.
- [x] Añadir prueba concurrente con varias conexiones/procesos: una fila no se reclama por dos emisores a la vez; usar `FOR UPDATE SKIP LOCKED` y un `UPDATE ... WHERE` condicional dentro de transacción, con `now()` de PostgreSQL.
- [x] Añadir pruebas del token: token antiguo no puede preparar ni confirmar; concesión con menos de 15 s se abandona; un trabajo completado después de reclamar no recibe confirmación.
- [x] Ejecutar RED en el PostgreSQL restaurado; implementar únicamente las tres operaciones y tipos mínimos necesarios.
- [x] Probar caída posterior a reclamar: intento permanece consumido, lease caduca, máximo tres; campo de notificado permanece nulo hasta confirmación HTTP exitosa. Probar además que una concesión expirada antes del envío consume el intento conforme a la regla de fallo explícita; el barrido jamás puede crear esta situación por haber reclamado un lote de leases.
- [x] Repetir suite focalizada y `test_pending_changes_postgres.py`, `test_experience_store.py`; verificar que los updates de trabajo no borran columnas nuevas.

### Tarea 3: vista factual para avisos

**Files:** Añadir formateador puro en `apps/bot/app/experience.py` (o módulo puro importado por ella); ampliar `apps/bot/tests/test_experience_status.py` y crear `apps/bot/tests/test_delay_notice_view.py` si queda más claro.

**Interfaces:** `format_factual_view(sync: dict | None, *, scope: str, now: datetime) -> str` es puro; `format_delay_notice(job: DelayNoticeClaim, sync: dict | None, *, now: datetime) -> str` añade el acuse de demora. En 2b el barrido siempre llama con `scope="latest_available"`; no persiste ni infiere alias. La función acepta `scope` para que el entregable 3 aporte ámbitos explícitos después. La hora y antigüedad visibles se basan en `payload.generated_at`/fecha de última sincronización disponible; actividad y mediciones retienen fechas/fuentes. No se afirma que la sincronización responde a la pregunta.

- [x] Escribir fixtures para texto libre, `/coach`, voz, `/ajustar` y cualquier trabajo sin metadato de alias; todos presentan `scope="latest_available"`. No probar ámbitos fijos por alias ni añadir metadato persistido en 2b; estos pertenecen al contrato del entregable 3.
- [x] Cubrir sincronización válida/antigua/faltante, actividad ausente, varias fuentes, datos wellness ausentes y respuesta máxima menor de 4096 caracteres.
- [x] Afirmar que no se llama a `resolve_intent`, LLM, `format_feedback`, `format_fatigue`, `format_week` ni renderers que incluyan valoración/recomendación. No exponer ID/chat, pregunta/transcripción, secretos, ni datos de otros chats.
- [x] Ejecutar pruebas RED. Implementar un resumen factual breve con fechas absolutas y etiquetas de fuente; datos faltantes se expresan como ausencia/no disponible.
- [x] Ejecutar suite focalizada; inspeccionar muestras para confirmar que no incorporan opinión ni cambian la respuesta canónica del trabajo.
- [ ] Commit local en `fase4-2b`: `feat: render factual delayed query context`; no hacer push.

### Tarea 4: configuración, emisor y ciclo de vida del barrido

**Files:** Modificar `apps/bot/app/main.py`, `apps/bot/app/config.py`; añadir `apps/bot/app/delay_notices.py` y `apps/bot/tests/test_delay_notice_sweeper.py`.

**Interfaces:** `parse_delay_notice_seconds(raw: str | None) -> int | None` devuelve `None` para apagado o configuración inválida; `send_delay_notice(chat_id: str, text: str, *, total_timeout_seconds: float = 15) -> bool`; `run_delay_notice_sweep_once(stop_event: threading.Event | None = None) -> int`. Poll interno cada 15 s, máximo 20 trabajos completados por ciclo y umbral `COACH_DELAY_NOTICE_SECONDS`; reclamar, preparar, enviar y confirmar uno por vez antes de reclamar el próximo. Comprobar `stop_event` antes de cada reclamación, además de antes de empezar el ciclo. No crear tarea async si está vacío/0, la base no es PostgreSQL o la sonda no encuentra todas las columnas.

- [x] Pruebas RED: vacío/0 no crea/ejecuta barrido; positivo válido inicia; negativo, no entero y >604800 quedan apagados sin impedir el arranque; backend JSON jamás envía avisos. `parse_delay_notice_seconds` permanece puro: en el punto de arranque se distingue raw vacío/0 (apagado silencioso) de valor mal formado/fuera de rango (log de error claro y apagado). Probar ambos logs.
- [x] Probar la sonda al inicio cuando la configuración válida sea positiva: si faltan columnas, registrar un error que nombre las columnas ausentes y arrancar la API con barrido desactivado; con umbral vacío/0 no consultar el catálogo ni las columnas de aviso.
- [x] Probar que el inicio de aplicación crea una única tarea por proceso y el cierre la detiene limpiamente. La tarea async debe invocar `await asyncio.to_thread(run_delay_notice_sweep_once, stop_event)` para que Psycopg y HTTPX no bloqueen el event loop; instrumentar un webhook concurrente y comprobar que responde durante un barrido lento. La llamada a HTTPX usa un bucle privado en el hilo y `asyncio.wait_for` para aplicar el plazo total. Al cerrar, señalar el `threading.Event` antes de esperar la tarea; no confiar en cancelar el wrapper async, porque eso no detiene el hilo. Testear que, si se señala la parada tras procesar un trabajo, el hilo no reclama el siguiente ni consume otro intento. Testear el ciclo directamente sin `sleep` arbitrario.
- [x] Simular Telegram con HTTPX y plazo total cancelable de 15 s aunque los chunks lleguen cada <15 s; test de goteo con cada chunk por debajo del plazo pero suma superior al límite, abortando al deadline. Sin reintento interno. `delay_notified_at` solo se guarda si HTTP es 2xx y JSON `ok=true`. Probar error HTTP, error JSON, timeout, excepción de red y caída después de aceptación antes de persistir.
- [x] Implementar config vacía por defecto, máximo 604800 s; valores inválidos registran un error claro y dejan barrido apagado, manteniendo la API arriba. Inicializar lifespan FastAPI con barrido solo para PostgreSQL y umbral positivo. La sonda de columnas usa `asyncio.to_thread`; si falla/missing, dejar barrido apagado. Cierre cooperativo con señal de hilo.
- [x] Ejecutar un ciclo: reclamar, releer y verificar lease ≥15 s inmediatamente antes de enviar, renderizar respaldo, enviar y confirmar; si hay error dejar que lease expire, sin consumir intentos extra por reintento del cliente.
- [x] Probar concurrencia con dos barridos simultáneos y varios trabajos: exactamente un aviso aceptado por trabajo en operación normal, ningún cuarto intento en fallos; carrera con finalización queda sin envío si se ve antes del envío. Añadir prueba de lote con al menos 20 trabajos y transporte lento virtual: las reclamaciones son secuenciales, ningún intento se gasta sin empezar su propio envío y ningún trabajo se abandona por falta de lease causada por avisos anteriores. Las llamadas de Psycopg y el envío HTTP ocurren en el hilo de `to_thread`.
- [x] Verificar que `sendChatAction`, el acuse, `/estado` y el flujo de finalización siguen como antes; el barrido no inicia trabajos ni modifica status/answer/structured output.
- [x] Repetir pruebas focalizadas y suite completa bot con backup restaurado; ninguna omisión PostgreSQL.
- [ ] Commit local en `fase4-2b`: `feat: send opt-in delayed job notices`; no hacer push.

### Tarea 5: regresión, compatibilidad y evidencia

**Files:** Crear/actualizar `docs/restructuring/fase4_evaluacion/entregable2b.md`; documentar variables en el archivo existente de despliegue si corresponde; no alterar el README fuera de lo necesario.

- [x] Probar API vieja contra esquema nuevo: lecturas/escrituras existentes, pendientes, respuesta y relaciones intactos; confirmar que la API nueva tolera marcas `NULL`. Modelar versiones sin abrir mensajes reales a usuarios.
- [x] Probar que el productor solo escribe después de tener columnas y lector; reversión deja los campos nuevos y datos intactos mientras el barrido/config se apagan.
- [x] Ejecutar suite completa del bot con dump restaurado y PostgreSQL desechable, cero omisiones; suite completa del worker para asegurar que su contrato no cambia.
- [x] Ejecutar `git diff --check`; revisar migración estrictamente aditiva y que no se altera producción ni el job payload canónico.
- [x] Crear el runbook de futura salida, incluyendo copia/restore aislado, migración, comprobación, despliegue apagado, medición real, recalibración, activación posterior autorizada y rollback que conserva columnas/datos. Este plan no aplica DDL ni despliega.
- [x] Registrar en evidencia solo SHA del backup, identidades de contenedores/DB/schema sintético y recuentos; nunca contenido real de preguntas, respuestas ni métricas de entrenamiento. Añadir resultados de suites, criterios de latencia/fallos, matriz de versiones y configuración por defecto. El barrido **no se activa ni despliega en producción en esta tarea**.
- [x] Detener/eliminar únicamente el contenedor desechable propio; confirmar estado limpio del repositorio.
- [x] Commit local en `fase4-2b`: `docs: record phase 4 deliverable 2b verification`; no hacer push antes de revisar el runbook y recibir autorización de despliegue.

## Autorrevisión

Cobertura de especificación: migración y backup en tarea 0–1; reclamación atómica, leases y límite de intentos en tarea 2; selección factual y fechas en tarea 3; transporte, timeout, barrido apagado por defecto y ciclo de vida en tarea 4; compatibilidad, reversión, regresiones y límites de producción en tarea 5. Quedan explícitamente fuera la activación del aviso, la activación de alias/V3, la valoración personalizada, los mensajes de prueba de producción y cualquier cambio al worker.

Decisión de implementación que se debe validar en revisión: guardar los cuatro campos de coordinación como columnas anulables en PostgreSQL y no duplicarlos en JSONB; permite reclamación condicional sin reescribir documentos antiguos. La migración es idempotente y separada de `ensure_schema`, cuyo camino común evita DDL después del esquema P0.3. Solo tres operaciones del store acceden a los valores de las columnas; el arranque inspecciona metadatos únicamente si se pide activar el barrido. Railway muestra `lloren27/garmin-coach` en `main` como fuente del servicio de producción, y la integración de Railway define esa conexión GitHub como despliegue al recibir pushes; el ajuste específico del panel no aparece en la configuración consultable y queda sin verificación visual. Por seguridad, se trabajará en la rama local `fase4-2b` sin push y se tratará cualquier publicación de `main` como despliegue a producción. Solo se considerará publicar la rama o fusionarla tras revisar el runbook, y el barrido continuará apagado hasta una autorización posterior. La configuración inválida se diferencia del apagado normal en el inicio: el código de arranque conserva el valor crudo, registra el error si no representa apagado ni un entero admitido y deja el barrido desactivado, pero la API sigue arriba.
