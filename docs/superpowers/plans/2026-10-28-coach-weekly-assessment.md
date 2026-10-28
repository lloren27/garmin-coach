# Coach Weekly Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que las preguntas evaluativas de `/coach` expliquen lo previsto y lo realizado durante la semana de calendario y el efecto verificable sobre las sesiones restantes, sin modificar el plan.

**Architecture:** El bot ofrece al trabajo una lectura acotada de planes históricos para la semana resuelta por el worker. V3 construye una instantánea con planes, actividades y cobertura; calcula relaciones diarias y una conclusión semanal con hallazgos tipados. El renderizador determinista conserva fechas, fuentes e incertidumbre. Esta es la etapa A de la spec: la tabla de inferencias deportivas queda fuera de las respuestas hasta su validación en la etapa B.

**Tech Stack:** Python, FastAPI, PostgreSQL/psycopg con respaldo de fichero, `unittest`, worker local V3.

**Spec:** `docs/superpowers/specs/2026-10-28-coach-weekly-assessment-design.md`.

## Global Constraints

- Semana = lunes a domingo en `Europe/Madrid`, fijada por la fecha de creación del trabajo; no cambia si el Mac procesa tarde.
- No atribuir a un día un plan creado después de la actividad ni usar solo el plan activo para fechas anteriores.
- No llamar «cumplida», «ajustada», «sustituida» u «omitida» a una relación inferida sin vínculo o confirmación fiable.
- No sumar escalas de carrera, ciclismo y fuerza ni inferir recuperación personal sin línea base validada.
- `/coach` de valoración no crea ni aplica propuestas; las consultas de plan o métricas y los alias conservan sus rutas.
- Primera entrega: hechos de la tabla entre deportes y efecto sobre la estructura de la semana; conclusiones fisiológicas entre deportes quedan deshabilitadas hasta revisión deportiva documentada.
- Ante «¿fue eficiente?», responder con diferencias frente al plan y efecto estructural sobre la semana; no dar un veredicto de eficiencia fisiológica en esta etapa.
- Una marca `updated_at` posterior no invalida un vínculo `completed_activity_id` válido. La certeza de la relación y la del contenido histórico del objetivo se evalúan por separado.
- No introducir servicios ni dependencias nuevas. Conservar contrato y permisos de `pending_changes` y E14.

## Review Focus

1. Consulta del martes entregada el miércoles: conserva la semana y la fecha que correspondían al trabajo; cubrir en Task 2 y Task 3.
2. Plan nuevo que cruza dos semanas y otro plan `superseded` que cubre el lunes: cada día usa su plan verificable; cubrir en Task 1 y Task 4.
3. Plan creado después de una actividad del mismo día, sin hora comparable: no afirmar adherencia retrospectiva; cubrir en Task 4.
4. Dos actividades y dos sesiones el mismo día: no elegir parejas arbitrarias ni perder una actividad; cubrir en Task 4.
5. Strava o Zepp fallan durante el periodo: «sin datos suficientes», nunca «sin actividad registrada»; cubrir en Task 3 y Task 4.

## Mapa de archivos

| Archivo | Responsabilidad |
| --- | --- |
| `apps/bot/app/store.py` | Leer planes y sesiones históricos por semana y trabajo, con propietario derivado del trabajo. |
| `apps/bot/app/main.py` | Endpoint autenticado de lectura de planes para un trabajo ya creado. |
| `apps/sync-local/garmin_sync/coach_intent.py` | Resolver el ámbito semanal de preguntas evaluativas sin alterar `resolve_intent` ni E14. |
| `apps/sync-local/garmin_sync/ai_worker.py` | Solicitar planes de la semana resuelta y trasladarlos al contexto compacto de V3. |
| `apps/sync-local/garmin_sync/coach_generation_context.py` | Validar y congelar planes históricos, actividades y estado de proveedores. |
| `apps/sync-local/garmin_sync/coach_weekly_assessment.py` | Relacionar conjuntos diarios y construir hallazgos semanales puros. |
| `apps/sync-local/garmin_sync/coach_deterministic.py` | Enrutar solo la nueva intención al renderizado semanal; otras respuestas siguen intactas. |
| `apps/sync-local/garmin_sync/coach_findings.py` | Reutilizar formato y evidencia sin alterar el selector congelado V2. |
| `tests/fixtures/coach_weekly_assessment_cases.json` | Corpus nuevo, independiente de E14. |

## Task 1: Lectura histórica acotada de planes

**Files:** Modify `apps/bot/app/store.py`, `apps/bot/app/main.py`; test `apps/bot/tests/test_weekly_plan_context.py`.

**Interfaces:** Produce `load_week_plans_for_job(job_id: str, monday: date) -> dict`, con `week_start`, `week_end`, `owner_id` y `plans` ordenados por `created_at,id`; cada plan lleva `id`, `revision`, `start_date`, `end_date`, `created_at` y sus sesiones con `created_at` y `updated_at` propios. Expone `GET /ai/jobs/{job_id}/week-plans?week_start=YYYY-MM-DD`, protegido por `X-Sync-Secret`; el servidor deriva el propietario del trabajo, valida que `week_start` es lunes y no acepta `owner_id` del cliente. Para un trabajo inexistente devuelve HTTP 404 con `detail.code="job_not_found"`, distinto del 404 genérico de FastAPI para una ruta ausente. No altera el `training_plan` actual usado por propuestas.

- [ ] **Step 1: Escribir pruebas fallidas** para fichero y PostgreSQL desechable: dos planes que se solapan y uno `superseded` aparecen si intersectan la semana; una sesión devuelve sus marcas de creación y actualización; un plan de otro propietario no aparece; un ID de trabajo inexistente devuelve 404 con `detail.code="job_not_found"`; falta de secreto devuelve 401/403; fecha que no es lunes devuelve 422.
- [ ] **Step 2: Ejecutar** `cd apps/bot && python -m unittest tests.test_weekly_plan_context -v`; esperar fallo por función/ruta ausente.
- [ ] **Step 3: Implementar** la lectura en `store.py` y la ruta en `main.py`; filtrar por `start_date <= domingo`, `end_date >= lunes` y `created_at <= job.created_at`. Mantener `superseded`; ordenar sesiones por `date,sequence,id`; no escribir estado ni exponer datos de otro propietario.
- [ ] **Step 4: Repetir** el comando de Task 1; esperar todas sus pruebas correctas.
- [ ] **Step 5: Commit** `feat: expose historical plans for coach week`.

## Task 2: Activación evaluativa y fechas estables

**Files:** Modify `apps/sync-local/garmin_sync/coach_intent.py`; test `apps/sync-local/tests/test_coach_weekly_intent.py`.

**Interfaces:** Añade `WeekAssessmentScope(monday: date, sunday: date, reference_day: date)` y `resolve_week_assessment(question: str, *, now: datetime, factual_scope: str | None) -> WeekAssessmentScope | None`. Para «hoy», «esta semana» o fecha explícita, devuelve el lunes–domingo que contiene el día de referencia. `factual_scope` no nulo desactiva esta ruta para los alias migrados. El reloj `now` es siempre `job.created_at` convertido a Madrid. `resolve_intent` y sus resultados E14 siguen intactos; no se activa para solicitudes de cambio ni consultas puras de plan o métricas.

- [ ] **Step 1: Escribir pruebas fallidas** para «¿qué opinas de mi entrenamiento de hoy?», «analiza mi entrenamiento de hoy», «¿fue eficiente mi entrenamiento de bici hoy?» y «¿cómo afecta lo que hice a esta semana?»; comprobar lunes/domingo exactos. Añadir controles para «¿qué toca mañana?», «pulso máximo de hoy», frase sin fecha, fecha histórica explícita, trabajo procesado tras medianoche y frase canónica de `/hoy` con `factual_scope='today'`. Esta última no activa valoración y `resolve_intent` conserva `analyze_day`.
- [ ] **Step 2: Ejecutar** `cd apps/sync-local && python -m unittest tests.test_coach_weekly_intent -v`; esperar fallo de reconocimiento/interfaz.
- [ ] **Step 3: Implementar** señales acotadas y `resolve_week_assessment` usando `resolve_dates` para fechas, sin cambiar las ramas de `CONSULT_PLAN`, `ANALYZE_ACTIVITY` métrica ni `REQUEST_CHANGE` de `resolve_intent`.
- [ ] **Step 4: Repetir** el comando de Task 2; esperar todas sus pruebas correctas.
- [ ] **Step 5: Commit** `feat: resolve weekly coach assessments`.

## Task 3: Contexto semanal verificable

**Files:** Modify `apps/sync-local/garmin_sync/ai_worker.py`, `apps/sync-local/garmin_sync/coach_generation_context.py`; test `apps/sync-local/tests/test_coach_weekly_context.py`.

**Interfaces:** Produce `fetch_week_plans(job_id: str, monday: date) -> dict` en `ai_worker.py`, usando el endpoint de Task 1 solo cuando Task 2 devuelve `WeekAssessmentScope` con `now=job.created_at` y `factual_scope=job.factual_scope`. `compact_context` pasa `extra_context.week_plans`, `extra_context.week_scope` y el propietario de `job.chat_id`; `build_snapshot` valida IDs, propietario, fechas, revisión y sesiones con sus marcas temporales, y congela ambos como `ContextSnapshot.week_plans` y `ContextSnapshot.week_scope`. Conserva `type` como `EvidenceRecord.activity_type` cuando la actividad lo aporta. Ante 404/405 del endpoint, primero distinguir `detail.code="job_not_found"` (error real) y consultar `GET /openapi.json`: solo si el esquema confirma que falta el método GET de la ruta se marca `week_context_status=unavailable` y se usa la respuesta factual limitada al día de Task 5. Si la ruta consta o el esquema no se puede consultar, el trabajo falla explícitamente. No pasar una lista vacía de planes como si estuviera verificada. Un 401/403 o un contexto contradictorio sigue siendo error, no ausencia de plan.

- [ ] **Step 1: Escribir pruebas fallidas** con dos planes cruzando semana, plan de otro propietario, IDs duplicados, sesión fuera del intervalo, marcas temporales ausentes o incoherentes, proveedor con error, proveedor sin ventana de cobertura y consulta procesada al día siguiente. Comprobar que consultas no evaluativas y alias migrados no llaman al endpoint. Cubrir 404 tipado `job_not_found`, 404/405 con ruta presente en OpenAPI, esquema inaccesible y 401/403 como errores; solo 404/405 con ruta GET ausente activa el modo factual limitado.
- [ ] **Step 2: Ejecutar** `cd apps/sync-local && python -m unittest tests.test_coach_weekly_context -v`; esperar fallo por campo/interfaz ausente.
- [ ] **Step 3: Implementar** lectura HTTP y validación del nuevo contexto, conservando `training_plan` singular para cambios autorizados. Exponer en la instantánea el `created_at` de planes, instantes de actividad y cobertura por proveedor/fecha; no usar `status=active` como filtro histórico.
- [ ] **Step 4: Repetir** el comando de Task 3; esperar todas sus pruebas correctas.
- [ ] **Step 5: Commit** `feat: carry verified weekly plan context`.

## Task 3A: Perfil de datos antes de la comparación

**Files:** Create `docs/restructuring/fase4_evaluacion/valoracion_semanal.md` with a read-only data profile; do not change plan generation in this task.

Inspección estática inicial (28/10/2026): de 24 plantillas de sesión en `_planned_week_sessions`, 19 incluyen ambos límites de duración y 5 no: tres tiradas largas con objetivo de distancia, una sesión de calidad descrita en texto y un descanso. Este recuento de plantillas no mide la frecuencia real en planes guardados.

Inventario inicial de escrituras: `store.py` inserta `planned_sessions`; `proposal_repository.py` solo las lee. No hay un `UPDATE` de estado o `completed_activity_id` en el código actual. Revalidar el inventario justo antes de Task 4 y, si aparece una escritura que cambie solo estado o vínculo, separar la marca de revisión del contenido antes de usar `updated_at` para reconstrucción histórica.

- [ ] **Step 1: Revalidar las escrituras** de `planned_sessions` y después inspeccionar los tres modos de `_planned_week_sessions` y una muestra de planes guardados mediante lectura de solo consulta. Contar sesiones obligatorias y opcionales por `sport` y `session_type`, con ambos límites `duration_min`/`duration_max`, solo uno o ninguno; distinguir descanso, objetivos de distancia e intervalos descritos solo en texto. No registrar datos personales en el informe.
- [ ] **Step 2: Registrar** recuentos, porcentaje y tamaño de muestra en `valoracion_semanal.md`, indicando si se dispuso de PostgreSQL o solo de los planes generados. Confirmar la frecuencia de los huecos detectados en datos guardados antes de Task 4.
- [ ] **Step 3: Decidir** a partir del perfil qué tipos admiten etiqueta de compatibilidad por duración. Para los demás, mostrar la magnitud disponible y el límite «sin criterio de compatibilidad validado»; no convertir una distancia escalar o texto de intervalos en una tolerancia improvisada. Incluir al menos un caso representativo de cada hueco en el corpus.

## Task 4: Relación diaria sin emparejamientos inventados

**Files:** Create `apps/sync-local/garmin_sync/coach_weekly_assessment.py`; test `apps/sync-local/tests/test_coach_weekly_assessment.py`.

**Interfaces:** Define `DayPlanSelection(day: date, plan_id: str | None, status: str, limitations: tuple[str,...])`, `DailyRelation(day: date, status: str, link_status: str, historical_target_status: str, session_ids: tuple[str,...], activity_ids: tuple[str,...], evidence_refs: tuple[str,...], limitations: tuple[str,...])`, `select_day_plan(plans: tuple, day: date, activity_times: tuple[datetime,...], as_of: datetime) -> DayPlanSelection` y `compare_day(day: date, selection: DayPlanSelection, sessions: tuple, activities: tuple, provider_status: Mapping) -> tuple[DailyRelation,...]`. Usa los planes de Task 3 y las métricas tipadas existentes. Solo marca compatibilidad cuando deporte y tipo son verificables y la duración entra en el rango `duration_min`–`duration_max`; distancia escalar e intensidad sin regla validada se muestran como magnitud factual con límite de comparación, no como cumplimiento ni diferencia de duración demostrada. Las relaciones confirmadas siguen requiriendo `completed_activity_id` válido o confirmación explícita. Un vínculo válido sigue confirmando la actividad aun si la sesión se actualizó después; solo la comparación con el objetivo histórico se limita cuando consta un cambio de contenido posterior sin instantánea anterior. Si el inventario de Task 3A demuestra que `updated_at` también cambia por estado o vínculo, no usarlo como prueba de cambio de contenido hasta disponer de una marca específica o historial. El `updated_at` del plan por `superseded` tampoco activa este límite.

- [ ] **Step 1: Escribir pruebas fallidas** con los casos: carrera prevista y bici+fuerza; doble sesión; sesión opcional; descanso con actividad; vínculo explícito; sesión vinculada con `updated_at` posterior por cambio de estado (conserva vínculo confirmado); dos parejas posibles; plan creado después de actividad; contenido de sesión modificado después de la actividad sin historial (objetivo histórico incierto); plan solo marcado `superseded`; actividad del mismo día sin hora fiable; proveedor fallido frente a ausencia comprobada; duración dentro/fuera del rango y objetivos sin ambos límites según Task 3A.
- [ ] **Step 2: Ejecutar** `cd apps/sync-local && python -m unittest tests.test_coach_weekly_assessment -v`; esperar fallo por módulo/tipos ausentes.
- [ ] **Step 3: Implementar** selección temporal y comparación de conjuntos según los estados informativos de la spec. Reutilizar reglas de cobertura de `coach_analysis` donde proceda; no inferir que otra modalidad sustituye la prevista. Si falta vínculo, magnitud o cobertura, añadir límite específico.
- [ ] **Step 4: Repetir** el comando de Task 4; esperar todas sus pruebas correctas.
- [ ] **Step 5: Commit** `feat: compare planned and recorded training days`.

## Task 5: Hallazgos y respuesta de semana completa

**Files:** Modify `apps/sync-local/garmin_sync/coach_weekly_assessment.py`, `apps/sync-local/garmin_sync/coach_deterministic.py`; test `apps/sync-local/tests/test_coach_weekly_response.py`.

**Interfaces:** Produce `assess_week(snapshot: ContextSnapshot) -> WeekAssessment` con fechas lunes/domingo, relaciones diarias, sesiones futuras, límites y referencias de evidencia. Produce `render_week_assessment(assessment: WeekAssessment, *, max_chars: int) -> CoachStructuredResponse`. `deterministic_response` llama esta ruta solo si `snapshot.week_scope` está presente; conserva el selector V2 y el renderizador actual para todas las demás consultas. Para `week_context_status=unavailable`, usa un renderizado factual acotado a las actividades del día de referencia y añade «No he podido verificar el plan de esta semana». No usa `training_plan` activo para comparar fechas anteriores, no da juicio de eficiencia y no llama al fallback prescriptivo legado.

- [ ] **Step 1: Escribir pruebas fallidas**: semana 26/10–01/11 con plan nuevo 28/10–03/11 y actividad del 27/10 sin plan aplicable; dos deportes el mismo día; sesiones futuras conservadas; limitación por bienestar sin línea base; pregunta por «eficiencia» sin veredicto fisiológico; respuesta con conclusión, diferencia, efecto estructural, próximo paso y límite. Añadir caso de API anterior con 404/405: respuesta factual del día y aviso visible de plan semanal no verificable, sin fingir comparación. Asegurar que no suma cargas, no prescribe cambio y no borra una molestia por presupuesto de caracteres.
- [ ] **Step 2: Ejecutar** `cd apps/sync-local && python -m unittest tests.test_coach_weekly_response -v`; esperar fallo por funciones ausentes.
- [ ] **Step 3: Implementar** agregación por fechas y deporte, selección de máximo tres diferencias relevantes con todas las limitaciones obligatorias y renderizado con evidencias. El «efecto» inicial puede afirmar que queda una sesión planificada sin relación confirmada y señalar proximidad de sesiones con fechas; no afirma equivalencia fisiológica ni fatiga individual. Si el texto excede `max_chars`, devolver reserva explícita, no truncar una conclusión crítica.
- [ ] **Step 4: Repetir** el comando de Task 5; esperar todas sus pruebas correctas.
- [ ] **Step 5: Commit** `feat: explain weekly plan deviations`.

## Task 6: Corpus, compatibilidad y documentación operativa

**Files:** Create `tests/fixtures/coach_weekly_assessment_cases.json`; modify `apps/sync-local/tests/test_coach_weekly_response.py`, `apps/bot/tests/test_weekly_plan_context.py`, `README.md`, `docs/restructuring/fase4_evaluacion/valoracion_semanal.md`.

**Interfaces:** El corpus identifica por caso pregunta, fecha de creación del trabajo, planes, actividades, estado de proveedores, conclusión permitida, afirmaciones prohibidas y referencias esperadas. E14 y las rutas de alias se conservan sin cambios. El documento operativo separa evidencia local de activación real.

- [ ] **Step 1: Añadir fixtures y pruebas** para los casos de la spec, incluidos planes solapados, semana cruzada, retraso de procesamiento y datos incompletos. Una prueba de bot verifica que `/plan`, `/plan nuevo`, `/feedback` y `/ajustar` mantienen sus flujos; una de worker verifica que consultas factuales, solicitudes de cambio y alias migrados no activan `week_scope`.
- [ ] **Step 2: Ejecutar** `cd apps/sync-local && python -m unittest tests.test_coach_weekly_response tests.test_coach_alias_e14 -v` y `cd apps/bot && python -m unittest tests.test_weekly_plan_context tests.test_coach_routing -v`; registrar los resultados de los casos nuevos antes de cualquier ajuste de integración.
- [ ] **Step 3: Completar** integración y documentación del flujo, con nota explícita de que las inferencias de la tercera columna de la tabla entre deportes siguen deshabilitadas. No activar flags ni desplegar por el mero hecho de pasar pruebas.
- [ ] **Step 4: Repetir** ambos comandos y las suites existentes completas de worker y bot, incluida la variante PostgreSQL desechable; exigir cero fallos y documentar los saltos si el entorno no permite ejecutarlas. Revisar `git diff --check`.
- [ ] **Step 5: Commit** `test: evaluate weekly coach assessment`.

## Entrega y trabajo posterior

Este plan entrega la comparación semanal estructural con hechos verificables y límites explícitos. La validación de la tabla deportiva, la línea base personal de bienestar, las conclusiones fisiológicas entre deportes y una posible redacción con Ollama requieren diseño/evaluación propios antes de activarse. El despliegue coordina API y worker compatibles; primero API con endpoint de lectura, después worker V3, y se observa una consulta real del usuario antes de declarar producción verificada. No se migra ningún alias ni se cambian permisos de plan.
