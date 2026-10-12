# Fase 4, entregable 2a: acuse y respuestas tardías — Plan de implementación

> **Para agentes de implementación:** Habilidad requerida: `superpowers:executing-plans` (o `superpowers:subagent-driven-development` si se delega). Ejecutar tarea por tarea; marcar las casillas al completarlas.

**Objetivo:** Actualizar el único acuse de las consultas de entrenamiento en cola y añadir una nota clara cuando una respuesta llegue tarde, conservando el reloj original y sin cambiar el esquema.

**Arquitectura:** La API presenta las respuestas de texto y el worker presenta audio/voz. Ambos conservarán sus canales de entrega actuales: Telegram recibe la voz antes de confirmar el trabajo. Los dos motores usarán un único conjunto JSON de casos temporales compartido en sus pruebas. Para evitar respuestas con versiones incompatibles durante el despliegue o la reversión, se detiene y drena el worker antes de cambiar solo una de las dos aplicaciones; las consultas permanecen en cola hasta que API y worker estén alineados. El acuse existente se reemplaza en el punto común de encolado; no se envía un segundo mensaje de procesamiento.

**Tecnologías:** Python, FastAPI, `datetime`/`zoneinfo`, `unittest`, httpx, Telegram Bot API.

**Especificación:** `docs/superpowers/specs/2026-10-11-fase4-experiencia-design.md`, decisiones “Respuestas tardías” y entregables 2a/2b.

## Alcance y prerrequisitos

Este plan cubre exclusivamente 2a. El entregable 1 debe estar desplegado y `/estado` verificado antes del despliegue, ya que el acuse nuevo remite a ese comando. 2a debe desplegarse y observarse antes de empezar 2b. No incluye migración, campos nuevos, barrido de pendientes, avisos automáticos, vistas factuales del respaldo, cambios de alias, activación de V3 ni alteración de recomendaciones.

## Restricciones globales

- Acuse de texto: «Consulta recibida; te respondo en cuanto esté lista. Puedes consultar /estado».
- Voz conserva «Audio recibido» e indica que la consulta queda en cola para transcripción y análisis.
- Sustituir el acuse existente; no añadir un segundo mensaje. Retirar toda promesa de 40–70 segundos.
- Aplica a las consultas de entrenamiento encoladas de texto libre, `/coach`, `/ajustar`, voz/audio y alias que ya terminen en cola. Excluye `source_kind=lab_test`, rutas síncronas, menús y registros deterministas.
- Nota si la espera es **6 horas o más**, o si cambió la fecha local de `Europe/Madrid` y han pasado **más de 30 minutos**. El cambio de fecha con espera de 30 minutos exactos o menor no basta.
- Texto fijo de la nota: «Respuesta tardía a tu consulta del {fecha y hora}. Se refiere al contexto temporal de esa consulta; no es una recomendación actualizada para hoy. Si todavía la necesitas, vuelve a preguntar».
- Mostrar fechas absolutas resueltas por el worker tal como ya aparecen en la respuesta. Evaluar la antigüedad al entregar; no re-resolver «hoy/mañana», reencolar ni aplicar cambios de plan por antigüedad.
- Fecha `created_at` ausente o inválida: indicar «fecha de consulta no disponible; vigencia temporal no confirmada», sin inventar una hora ni afirmar una antigüedad concreta. Aceptar cadenas ISO-8601 con zona y objetos `datetime` conscientes; rechazar valores ingenuos.
- Una marca de creación que esté hasta 120 segundos en el futuro respecto al reloj de entrega se considera edad cero (deriva pequeña entre Railway y Mac), nunca negativa ni «no confirmada». Más de 120 segundos en el futuro se trata como marca no fiable.
- No alterar la respuesta estructurada, su validación, la respuesta almacenada, las autorizaciones ni los flujos de propuesta/caducidad.
- Sin cambios de esquema ni nuevos campos persistidos. Funciona para almacenamiento JSON y PostgreSQL.
- Orden de publicación: primero el lector/presentador compatible de la API; después el worker que produce los envíos de voz compatibles.

## Archivos previstos

- Modificar `apps/bot/app/coach.py`: textos de los acuses de texto y voz.
- Modificar `apps/bot/app/main.py`: componer la nota al entregar respuestas de texto, usando `created_at` del documento devuelto por `complete_ai_job`.
- Crear `apps/bot/app/response_timing.py`: función pura de clasificación/formato de antigüedad, con `now` inyectable y zona local explícita.
- Modificar `apps/sync-local/garmin_sync/ai_worker.py`: componer la misma nota en el texto visible de voz y en la alternativa textual antes de enviar/completar, manteniendo intacto `payload["answer"]` como contenido canónico.
- Crear `tests/fixtures/late_response_cases.json`: único conjunto de timestamps, offsets, zonas, deriva de reloj y resultado esperado, cargado por ambas suites.
- Modificar `apps/bot/tests/test_coach_routing.py` y añadir `apps/bot/tests/test_late_response.py` para los formatos de acuse y límites temporales.
- Modificar `apps/bot/tests/test_ai_job_completion.py` para entrega de texto y conservación del payload canónico.
- Modificar `apps/sync-local/tests/test_ai_response_flow.py` para voz tardía, voz a tiempo y alternativa textual.
- Ampliar la prueba PostgreSQL del entregable 1 (o añadir `apps/bot/tests/test_late_response_store.py`) para verificar el tipo real de `created_at` que devuelve `complete_ai_job` en backend JSON y en PostgreSQL desechable.
- Crear `docs/restructuring/fase4_evaluacion/entregable2a.md` con resultados observados de suite y despliegue/observación cuando estos ocurran; el plan no autoriza desplegar.

## Enfoque de revisión

- Medianoche con espera de segundos: no añade nota (caso 23:55 → 00:00:20).
- Cambio de fecha con espera de más de 30 minutos: sí añade nota; con exactamente 30 minutos: no.
- Exactamente 6 horas y varios días: sí añade nota; el contexto original y fechas absolutas no cambian.
- Deriva de reloj de 120 segundos: edad cero; con 121 segundos futuros, vigencia no confirmada.
- Fecha inválida, ingenua o ausente: no convertirla silenciosamente a UTC; usar la advertencia de vigencia no confirmada.
- API nueva/worker antiguo, API antigua/worker nuevo y reversión: no procesar consultas mientras las versiones estén desalineadas; comprobar con pruebas de flujo que el pause/drain conserva trabajos en cola y que tras alinear versiones cada respuesta lleva cero o una nota, nunca dos.
- Voz: usar una versión hablada breve de la nota: «Respuesta tardía. Consulta del {fecha y hora}; la recomendación corresponde a ese momento». El texto visible conserva la nota completa. El caption de Telegram se limita a 1.024 caracteres; si nota completa más respuesta no caben, usar en el caption solo la nota breve y conservar en el mensaje de texto de respaldo existente la respuesta íntegra con una sola nota completa. La respuesta completa nunca se trunca en audio ni en texto y no se repite la nota completa en caption y texto de respaldo.

---

### Tarea 1: contrato temporal puro para la nota

**Archivos:** Crear `apps/bot/app/response_timing.py`; crear `apps/bot/tests/test_late_response.py`.

**Interfaces:** Producir `late_response_prefix(created_at: object, *, now: datetime) -> str | None` y `format_late_delivery(answer: str, created_at: object, *, now: datetime) -> str`. `now` debe incluir zona; si no la incluye, fallar explícitamente en tests/código de llamada. Aceptar `created_at` como ISO-8601 con zona (`Z` u offset) o como `datetime` con zona; rechazar `datetime` ingenuo y cadenas sin offset. Zona de comparación de fecha: `ZoneInfo("Europe/Madrid")`; duración real calculada entre instantes conscientes.

- [ ] Añadir pruebas de la función pura: mismo día y menos de 6 h devuelve respuesta sin prefijo; exactamente 6 h añade prefijo; 23:55→00:00:20 no añade; 23:55→00:25 no añade; 23:55→00:25:01 añade; días diferentes tras 31 min añaden; espera de dos días añade.
- [ ] Añadir pruebas de fechas `Z`, offset equivalente, `datetime` consciente, `created_at` ingenuo, malformado, `None`, y `now` ingenuo. Una fecha hasta 120 segundos futura devuelve edad cero/no tardía; fecha más de 120 segundos futura es no fiable. Para falta/fecha inválida, usar la indicación genérica de vigencia no confirmada y nunca producir edad negativa.
- [ ] Añadir pruebas parametrizadas que carguen `tests/fixtures/late_response_cases.json`, sin copiar la matriz en ninguno de los dos paquetes.
- [ ] Crear el fixture JSON con claves `id`, `created_at`, `now` y `late`; incluir al menos: 23:55→00:00:20 (`false`), cambio de fecha tras 30:00 exactos (`false`), cambio de fecha tras 30:01 (`true`), 6:00:00 (`true`), 120 segundos futuro (`false`), 121 segundos futuro (caso separado `unreliable`) y espera de dos días (`true`). Ambas suites leen esos mismos valores y verifican el resultado de su clasificador.
- [ ] Ejecutar `cd apps/bot && .venv/bin/python -m unittest tests.test_late_response -v`. Confirmar que falla por módulo/función ausente o aserciones de comportamiento.
- [ ] Implementar la función pura. Formatear `created_at` en `Europe/Madrid` con fecha y hora absolutas; el helper solo añade nota de presentación, nunca modifica `answer` recibido. Aplicar tolerancia máxima de 120 segundos hacia el futuro como edad cero.
- [ ] Repetir `cd apps/bot && .venv/bin/python -m unittest tests.test_late_response -v`; todos los casos deben pasar.
- [ ] Commit: `feat: define late response timing contract`.

### Tarea 2: acuse único al encolar

**Archivos:** Modificar `apps/bot/app/coach.py`; modificar/añadir pruebas en `apps/bot/tests/test_coach_routing.py`.

**Interfaces:** Conservar `format_ai_queued(document: dict[str, Any]) -> str` y `format_voice_queued(document: dict[str, Any]) -> str`; solo cambia el texto. El webhook existente sigue enviando exactamente una respuesta.

- [ ] Probar que `format_ai_queued({})` es exactamente «Consulta recibida; te respondo en cuanto esté lista. Puedes consultar /estado» y no incluye duración prometida ni «escribiendo» como mensaje adicional.
- [ ] Probar que `format_voice_queued` conserva «Audio recibido» y duración si existe, anuncia cola para transcripción y análisis, remite a `/estado` y no promete 40–70 segundos.
- [ ] Probar la ruta de webhook para consulta en texto y voz/audio: una llamada a `send_telegram_message` con un acuse; comprobar que `create_ai_job` ocurrió antes del envío. Mantener intacta la rama de documentos `lab_test` y cubrirla como control de exclusión.
- [ ] Ejecutar `cd apps/bot && .venv/bin/python -m unittest tests.test_coach_routing -v`; confirmar fallo inicial por copia/respuesta vigente antes de editar los formatters.
- [ ] Actualizar formatters sin añadir llamadas de envío ni cambiar las rutas deterministas/síncronas. Conservar variaciones reales necesarias (por ejemplo duración de audio), con la frase acordada como contenido común.
- [ ] Ejecutar el test focalizado y los tests de webhook/routing relevantes; todos pasan y `lab_test` conserva su acuse específico.
- [ ] Commit: `feat: update queued training acknowledgements`.

### Tarea 3: nota en respuestas de texto de la API

**Archivos:** Modificar `apps/bot/app/main.py`; ampliar `apps/bot/tests/test_ai_job_completion.py`.

**Interfaces:** Consumir `document["created_at"]` que ya se devuelve de `complete_ai_job`. Añadir `now` inyectable solo a una función pura o a un helper interno para tests; no cambiar la ruta pública ni el esquema del trabajo.

- [ ] Añadir test de endpoint con `complete_ai_job` devolviendo un trabajo con fecha válida y `send_telegram_message` parcheado. A tiempo: enviar el `answer` idéntico. A las 6 h: enviar respuesta con prefijo. El argumento `answer` pasado a `complete_ai_job` y el objeto guardado simulado siguen siendo el texto canónico sin prefijo.
- [ ] Añadir test de fecha de creación ausente/ingenua: la respuesta informa vigencia no confirmada, no una fecha inventada. Añadir control de `status=failed`: conserva el aviso de fallo existente, sin nota tardía pegada como si hubiera respuesta.
- [ ] Añadir prueba de integración con el PostgreSQL desechable aislado y con backend JSON: crear y completar un trabajo real en cada backend, comprobar el tipo y representación de `created_at` que devuelve realmente `complete_ai_job`, y pasar ese valor al formateador. En PostgreSQL también verificar que la columna `timestamptz` no sustituye ni cambia el tipo del timestamp del documento JSONB. No simular el tipo real solo con un diccionario en el test de endpoint.
- [ ] Ejecutar tests focalizados de `test_ai_job_completion.py`; confirmar fallo antes de cambiar endpoint.
- [ ] En la rama `completed` con `answer`, obtener la forma visible de `format_late_delivery` desde la fecha persistida y hora actual. Ejecutar validación estructurada sobre el texto original antes del guardado, y enviar únicamente la forma visible. No mutar el documento, respuesta, transcript ni structured output persistidos.
- [ ] Asegurar que `_completion_replayed` sigue impidiendo una segunda entrega de texto y que `notify_telegram=False` sigue suprimiendo el envío cuando se usa el flujo de voz.
- [ ] Ejecutar `cd apps/bot && .venv/bin/python -m unittest tests.test_ai_job_completion -v` y `cd apps/bot && .venv/bin/python -m unittest tests.test_late_response -v`; todos pasan.
- [ ] Commit: `feat: annotate delayed text responses`.

### Tarea 4: nota equivalente en voz y fallback

**Archivos:** Modificar `apps/sync-local/garmin_sync/ai_worker.py`; ampliar `apps/sync-local/tests/test_ai_response_flow.py`.

**Interfaces:** Consumir `job["created_at"]` que ya acompaña los trabajos reclamados. Producir texto visible de voz/fallback sin cambiar `payload["answer"]`, `structured_output` ni `output_source`.

- [ ] Cargar `tests/fixtures/late_response_cases.json` desde la suite del worker y ejecutar exactamente los mismos casos que `apps/bot/tests/test_late_response.py`; el test debe fallar si cambia el umbral de cualquiera de las dos aplicaciones. Añadir la tolerancia futura de 120/121 segundos.
- [ ] Reutilizar `job_created_at(job)` desde `garmin_sync.coach_job_time` para parsear/validar el timestamp. Capturar su `ValueError` y presentar la nota genérica de vigencia no confirmada; no añadir otro analizador ISO al worker. Añadir un `now` inyectable al formateador local para los tests, sin alterar la API de producción del worker.
- [ ] Para voz válida, comprobar que Piper recibe la versión hablada breve de la nota seguida de la respuesta íntegra, que el caption/transcripción no sustituye el contexto original y que el payload de completion conserva respuesta canónica y salida estructurada sin prefijo.
- [ ] Probar respuesta cuya nota completa más respuesta supera 1.024 caracteres: audio sintetizado con respuesta completa, caption bajo el máximo, y entrega del mensaje de texto completo conforme al fallback existente con la nota completa. En ese caso el caption solo lleva la nota breve y un texto de indicación de que la respuesta completa está en el audio/mensaje; no truncar la respuesta para hacerle espacio al prefijo. Verificar también que no se excede el límite real de 1.024 caracteres del caption de Telegram y que la nota completa no se repite en el caption y el mensaje de respaldo.
- [ ] Usar la locución breve fijada: «Respuesta tardía. Consulta del {fecha y hora}; la recomendación corresponde a ese momento». Mantener el prefijo completo aprobado en el texto de respuesta.
- [ ] Para caída de Piper o voz deshabilitada, comprobar que el worker completa con modo texto y la API envía la forma visible tardía exactamente una vez; no insertar dos notas.
- [ ] Añadir prueba de coordinación de versiones para API nueva/antigua × worker nuevo/antiguo. En las dos combinaciones desalineadas, el worker queda detenido/drenado y ningún trabajo se entrega; el trabajo permanece pendiente y al reanudarse con versiones alineadas se produce una respuesta con exactamente una nota completa en el canal textual (y como máximo una versión breve adicional en la locución). Tras reversión, API y worker vuelven juntos a la versión previa; la regla de esa versión alineada aplica. No aceptar como estado operativo ejecutar un worker antiguo mientras la API nueva habilita procesamiento, ya que el worker antiguo no puede incluir la nota en la voz que envía antes de llamar a la API.
- [ ] Ejecutar `cd apps/sync-local && .venv/bin/python -m unittest tests.test_ai_response_flow -v`; confirmar fallo en los casos tardíos antes de modificar worker.
- [ ] Implementar la misma fórmula temporal contra `job_created_at(job)` y `Europe/Madrid`; recorrer `tests/fixtures/late_response_cases.json` y afirmar para cada registro el valor `late`/`unreliable` esperado. Añadir prefijo solo al texto que oye/ve la persona, manteniendo el payload de negocio intacto.
- [ ] Repetir tests de `test_ai_response_flow.py` y los focalizados de la API; deben pasar. Verificar que el indicador `sendChatAction` continúa siendo solo indicador y no genera un mensaje adicional.
- [ ] Commit: `feat: annotate delayed voice responses`.

### Tarea 5: regresión, verificación y evidencia de 2a

**Archivos:** Crear `docs/restructuring/fase4_evaluacion/entregable2a.md` después de ejecutar la verificación.

- [ ] Ejecutar suite completa del bot: `cd apps/bot && .venv/bin/python -m unittest discover -s tests -v`. PostgreSQL debe ejecutarse con la instancia desechable aislada establecida en el entregable 1; ninguna prueba PostgreSQL se omite.
- [ ] Ejecutar suite completa del worker: `cd apps/sync-local && .venv/bin/python -m unittest discover -s tests -v`.
- [ ] Ejecutar `git diff --check`; revisar cambios para confirmar ausencia de migraciones, nuevos campos, barrido, mensajes espontáneos, rutas deportivas modificadas y alteraciones de la salida estructurada.
- [ ] Crear evidencia con comandos y resultados reales, cantidad de tests, matriz de tiempos, canales texto/voz, y estado de configuración/identidad PostgreSQL de pruebas. No afirmar despliegue ni observación en producción desde pruebas locales.
- [ ] Antes del despliegue, comprobar como prerrequisito que el entregable 1 está desplegado y `/estado` se verificó. Detener/drenar el worker, desplegar primero la API y luego el worker, y reanudarlo solo con ambas versiones alineadas. Observar acuse único, respuesta normal sin prefijo y voz en operación normal. Un caso tardío solo se registra si ocurre naturalmente; no fabricar trabajos ni enviar mensajes de prueba en producción. Si no ocurre, consignar «no observado en producción», cubierto por pruebas locales. Registrar versiones y observaciones; no comenzar 2b hasta dejar esta evidencia revisable.
- [ ] Commit: `docs: record phase 4 deliverable 2a verification`.

## Autorrevisión

La especificación asigna a 2a acuse, nota de entrega, ambos backends, bordes de 30 minutos/6 horas, voz/texto, despliegue API antes que worker y observación antes de 2b. Las tareas cubren también el tipo real de `created_at`, la tolerancia de reloj, la matriz común en JSON, compatibilidad operativa durante despliegues/reversiones y el límite del caption. Se preserva la validación del contenido canónico y el canal de voz previo a la confirmación. No quedan tareas de 2b dentro de este plan.
