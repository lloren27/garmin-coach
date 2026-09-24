# Coach Validated Decisions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar respuestas del coach a partir de decisiones validadas y datos autorizados, eliminando la generación independiente de prescripciones en el texto.

**Architecture:** Contrato interno versionado y discriminado por acción; instantánea del contexto con catálogo de evidencias y sesiones; resolución y texto deterministas. `ai_worker` orquesta una generación y como máximo una reparación. Un adaptador conserva `CoachStructuredResponse` y el flujo de propuestas del backend.

**Tech Stack:** Python existente, Pydantic v2, dataclasses, unittest, httpx y Ollama. Sin nuevas dependencias.

**Spec:** [2026-09-23-coach-validated-decisions-design.md](../specs/2026-09-23-coach-validated-decisions-design.md)

## Global Constraints

- `schema_version: Literal["1"]` y `context_snapshot_id` obligatorio.
- Instante de referencia en Europe/Madrid e instantánea inmutable durante ambos intentos.
- Un único reintento. Una propuesta sin permiso o `CONTEXT_SNAPSHOT_MISMATCH` es fatal.
- P0 determinista: no `answer` libre ni paráfrasis por IA.
- No modificar modelo, sincronizaciones, umbrales de entrenamiento ni política de aprobación.
- Mantener contrato público, trabajos históricos, voz, idempotencia y validación independiente del backend.
- Logs sin preguntas, notas, hechos de salud, contexto, salida íntegra o traceback de Pydantic.
- Catálogo pequeño, sin conclusiones que necesiten nuevos umbrales.

## Review Focus

- Cambio de día entre intentos: conservar la fecha de la instantánea, no recalcular mañana. Prueba en tarea 2.
- Dos sesiones el mismo día e IDs duplicados: resolver por identidad, nunca por posición; rechazar duplicados del contexto. Prueba en tarea 2.
- Títulos o notas con cifras e instrucciones contradictorias: no incorporarlos como prosa prescriptiva. Prueba en tarea 3.
- Semana extensa que supera el límite: preservar sesiones y condiciones, reducir explicación opcional; si aun así no cabe, fallo controlado. Prueba en tarea 3.
- Propuesta no autorizada junto a un defecto estructural: no conceder un reintento por haber encontrado antes el error de estructura. Prueba en tarea 4.

## Preparación y convenciones

Ejecución recomendada: nativa, secuencial, porque contratos, resolución y renderizador comparten interfaces. Antes de implementar, aplicar `using-git-worktrees`, `test-driven-development` y la guía de ejecución. El script programado usa el checkout local: aislar el desarrollo evita que el worker ejecute una implementación incompleta.

Conservar los documentos actualmente sin seguimiento al preparar el aislamiento. No reiniciar el worker ni desplegar como parte de las pruebas. Ejecutar cada caso nuevo primero en rojo y después en verde; confirmar cada bloque con su diff y pruebas antes del siguiente.

Desde `apps/sync-local`, comando unitario base:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_coach_generation*.py' -v
```

En un worktree usar los intérpretes absolutos del checkout original con `PYTHONPATH` apuntando a los paquetes del worktree, sin copiar `.env` ni enlazar archivos de datos de producción.

## Tarea 1: Contratos internos e incidencias tipadas

**Files:** crear `apps/sync-local/garmin_sync/coach_generation_contracts.py`, `coach_validation.py` y `apps/sync-local/tests/test_coach_generation_contracts.py`.

**Interfaces:**

```python
class CoachGenerationResponse(BaseModel):
    schema_version: Literal['1']
    context_snapshot_id: str
    response_type: ResponseType
    decisions: list[GenerationDecision]
    conclusions: list[Conclusion]
    evidence_refs: list[str]
    change_proposal: GenerationChangeProposal | None = None

def normalize_generation(payload: dict) -> tuple[dict, list[ValidationIssue]]: ...
def parse_generation(content: str) -> CoachGenerationResponse: ...
class CoachValidationError(ValueError):
    issues: tuple[ValidationIssue, ...]
```

Los tipos de la interfaz se definen en esta tarea: `GenerationDecision` es la unión por `action`; `Conclusion` contiene código y referencias; `GenerationChangeProposal` conserva operaciones y valores propuestos actuales pero sustituye prosa y evidencias libres por códigos y referencias. `ValidationIssue` y `RepairHint` tienen los campos de la especificación. No se modifica el contrato público para forzarlo a cumplir las reglas nuevas.

- [ ] Escribir casos de JSON inválido, extra fields, versión, normalización y unión discriminada. Ejemplo de prueba:

```python
def test_rest_rejects_training_intensity(self):
    for value in ('easy', 'threshold', 'unknown'):
        with self.subTest(value=value), self.assertRaises(ValidationError):
            RestDecision(action='rest', intensity=value, evidence_refs=[])

def test_keep_plan_cannot_regenerate_duration(self):
    with self.assertRaises(ValidationError):
        KeepPlanDecision(action='keep_plan', session_id='s1',
                         evidence_refs=[], duration_min=30)
```

- [ ] Ejecutar el archivo de pruebas y comprobar que falla por la funcionalidad aún ausente.
- [ ] Implementar variantes para las ocho acciones existentes. `rest` tiene intensidad predeterminada `rest`; objetivos nulos y distancia nula/cero; `keep_plan` solo ID y fundamento; las acciones informativas no admiten objetivos. Las variantes activas usan límites de duración y formato de ritmo compatibles con los validadores existentes.
- [ ] Implementar fases y severidades cerradas, traducción de errores sin `input`, y normalización por campo con lista cerrada (`REST` a `rest`, espacios y alias inequívocos). Nunca normalizar intensidad desconocida a una supuesta.
- [ ] Implementar catálogo inicial: `PLAN_SESSION`, `RECOVERY_RECOMMENDATION`, `OBSERVED_ACTIVITY`, `OBSERVED_WELLNESS`, `DATA_STALE`, `DATA_MISSING`, `NEEDS_CLARIFICATION`, `CHANGE_REQUESTED`, `ANALYSIS_LIMITED`. Cada código exige la referencia o condición correspondiente; no implica carga aceptable ni diagnóstico.
- [ ] Ejecutar los casos hasta verde; revisar el JSON Schema producido, incluidas las restricciones de cada variante; guardar el bloque en un commit.

## Tarea 2: Instantánea, evidencias y resolución del plan

**Files:** crear `apps/sync-local/garmin_sync/coach_generation_context.py`, `coach_generation_resolver.py` y `apps/sync-local/tests/test_coach_generation_context.py`.

**Interfaces:**

```python
def build_snapshot(question: str, compact: dict, *, now: datetime) -> ContextSnapshot: ...
def generation_schema(snapshot: ContextSnapshot) -> dict: ...
def resolve_generation(response: CoachGenerationResponse,
                       snapshot: ContextSnapshot) -> ResolvedGeneration: ...
```

`ContextSnapshot` encapsula ID opaco, fecha, versión, catálogo de `EvidenceRecord`, sesiones por ID, ámbito de consulta y permisos. `EvidenceRecord` contiene ID, fuente real, fecha y hechos tipados. `ResolvedGeneration` contiene decisiones públicas resueltas, conclusiones comprobadas, evidencias y propuesta adaptada, todavía sin `answer`. Estos tipos se definen en los módulos de esta tarea; la inmutabilidad debe cubrir estructuras anidadas, no solo el atributo de una dataclass.

- [ ] Crear una instantánea sintética con dos sesiones de mañana (carrera 40–50 minutos y bicicleta con potencia), check-in ausente y bienestar Zepp. Añadir pruebas de contexto vacío, IDs duplicados, sesión cancelada, referencias inexistentes y selección ambigua.
- [ ] Añadir pruebas de identidad y cambio de día:

```python
def test_snapshot_detaches_nested_context(self):
    compact = {'extra_context': {'training_plan': {'sessions': []}}}
    snapshot = build_snapshot('mañana', compact, now=self.now)
    compact['extra_context']['training_plan']['sessions'].append({'id': 'foreign'})
    self.assertNotIn('foreign', snapshot.sessions)

def test_wrong_snapshot_is_fatal(self):
    response = self.valid_response.model_copy(update={'context_snapshot_id': 'other'})
    with self.assertRaises(CoachValidationError) as caught:
        resolve_generation(response, self.snapshot)
    self.assertEqual(caught.exception.issues[0].code, 'CONTEXT_SNAPSHOT_MISMATCH')
    self.assertEqual(caught.exception.issues[0].severity, 'fatal')
```

`self.valid_response` será una respuesta v1 `information_only` con el ID de `self.snapshot`; `self.now` una fecha fija con zona Madrid. La prueba de cambio de día resuelve dos veces sobre esa instantánea mientras el reloj externo cruza medianoche y exige la misma fecha objetivo.

- [ ] Ejecutar en rojo y construir el catálogo desde campos concretos de `compact_context`: actividades, wellness efectivo, perfil, pruebas aplicadas, fuerza, check-ins, Wattwise y cálculos del backend. No catalogar contenedores vacíos o estados no disponibles. Preservar proveedor y fecha real; las referencias de registros sin ID solo valen dentro de la instantánea.
- [ ] Resolver `keep_plan` por ID y copiar deporte, tipo, fecha, duración mínima/máxima, distancia, intensidad, ritmo y potencia. Rechazar duplicados, cancelaciones, ámbitos incompatibles y ausencia de identidad. No reutilizar una fecha deducida por el modelo como autoridad.
- [ ] Obtener ámbitos hoy/mañana/próxima sesión/semana a partir del enrutamiento existente y la fecha capturada. Ante ambigüedad, producir necesidad de aclaración, nunca escoger por posición.
- [ ] Validar evidencia y conclusiones contra la instantánea. Comprobar permisos antes de adaptar propuestas; conservar sus operaciones y la posterior comprobación del backend. Mapear proveedor Zepp a la representación pública compatible sin atribuirlo a Garmin (por ejemplo, fuente `backend` con hecho explícitamente atribuido a Zepp).
- [ ] Ejecutar todas las pruebas de tarea 1 y 2 en verde y guardar el bloque en un commit.

## Tarea 3: Texto canónico y adaptación pública

**Files:** crear `apps/sync-local/garmin_sync/coach_generation_renderer.py` y `apps/sync-local/tests/test_coach_generation_renderer.py`.

**Interfaces:**

```python
def render_generation(result: ResolvedGeneration, snapshot: ContextSnapshot,
                      *, max_chars: int) -> CoachStructuredResponse: ...
```

- [ ] Escribir pruebas de descanso, carrera, bici, fuerza, recuperación, análisis sin actividad, pregunta de aclaración y semana. Comprobar igualdad de intervalos y unidades con los datos resueltos.

```python
def test_render_uses_resolved_duration(self):
    wire = render_generation(self.resolved_run, self.snapshot, max_chars=3200)
    self.assertIn('40 a 50 minutos', wire.answer)
    self.assertNotIn('30 minutos', wire.answer)
    self.assertEqual(wire.decisions[0].duration_max_min, 50)
```

`self.resolved_run` procede de resolver `keep_plan` sobre la sesión de carrera de la tarea 2; el título sintético del plan contiene «haz 30 minutos», y debe quedar fuera del texto prescriptivo.

- [ ] Ejecutar en rojo y crear plantillas españolas a partir de acciones, intensidades, hechos y códigos tipados. No reutilizar descripciones o títulos libres como instrucciones. Diferenciar recomendación de cambio aplicado y propuesta pendiente.
- [ ] Añadir avisos de antigüedad una sola vez, usando la fecha capturada. Mostrar análisis de hechos disponibles sin forzar una actividad ni inventar valoraciones.
- [ ] Construir el contrato público con motivos y evidencias generados en Python. Verificar que `CoachStructuredResponse.model_validate` acepta el resultado y que la evidencia no cambia de proveedor al adaptar.
- [ ] Implementar presupuesto de longitud por bloques: instrucciones y condiciones obligatorias primero, explicación opcional después. Si lo obligatorio excede el máximo, emitir una incidencia fatal de rendering y pasar a reserva; nunca truncar una sesión.
- [ ] Probar texto largo, varias sesiones, títulos maliciosos y redondeo que pueda cambiar objetivos; ejecutar tareas 1–3 en verde y guardar un commit.

## Tarea 4: Orquestación, reparación y observabilidad

**Files:** modificar `apps/sync-local/garmin_sync/ai_worker.py`; crear `apps/sync-local/garmin_sync/coach_generation_pipeline.py`, `apps/sync-local/tests/test_coach_generation_pipeline.py`; adaptar `test_ai_response_flow.py` y `test_change_proposal_flow.py` al contrato interno.

**Interfaces:**

```python
def generate_validated(question: str, compact: dict, *, generate: Callable,
                       job_id: str | None = None) -> CoachStructuredResponse: ...
```

`generate` recibe los mismos argumentos de generación que `ollama_generate`; el worker conserva `CoachRunResult`. Añadir `job_id` opcional a `call_ollama` y pasarlo desde `process_job`, actualizando los dobles de pruebas que actualmente admiten solo dos argumentos.

- [ ] Escribir dobles de Ollama que lean el ID real de la instantánea del prompt y devuelvan: éxito, error reparable y éxito, dos errores, versión errónea, snapshot erróneo y propuesta no autorizada combinada con intensidad inválida.

```python
def test_fatal_does_not_retry(self):
    generate = Mock(return_value=self.unauthorized_reply)
    with self.assertRaises(CoachValidationError):
        generate_validated('analiza hoy', self.compact, generate=generate, job_id='j1')
    self.assertEqual(generate.call_count, 1)
```

`self.compact` tiene permiso de propuesta falso; `self.unauthorized_reply` usa JSON con una propuesta no nula. La comprobación de autoridad debe ocurrir tras parsear el objeto y antes de que otros errores estructurales puedan ocultarla. No es posible analizar autoridad dentro de JSON ilegible: ese caso es parsing reparable.

- [ ] Ejecutar en rojo. Construir prompt v1 con contrato, identidad, catálogo y reglas explícitas de descanso, evidencias y propuestas. El esquema acota fuentes/sesiones e ID/version, pero Python vuelve a validarlos siempre.
- [ ] Sustituir el flujo conjunto `answer`/decisiones por parsear, normalizar, validar, resolver y renderizar. Evitar pasar el texto canónico por funciones que puedan volver a recortar instrucciones.
- [ ] Reparar una sola vez: conservar instantánea; enviar salida rechazada como datos y pistas específicas (`allowed_values`, `allowed_refs`, `expected_value`, `rule`); revalidar todo. Cualquier fatal prevalece sobre otras incidencias. Fallos internos de contexto/renderizado no se mandan a Ollama.
- [ ] Emitir eventos por intento con código, ruta, fase, versión y snapshot del worker. Limitar valores a metadatos permitidos. Sustituir el volcado de `str(exc)` en errores de generación por causas saneadas; comprobar que datos personales sintéticos no aparecen en logs, incluso en parsing y errores de transporte.
- [ ] Mantener el fallback y `output_source`, finalización idempotente y texto idéntico para voz. Retirar validadores de texto libre y rutas obsoletas solo después de trasladar sus garantías a pruebas nuevas; mantener tests del contrato público histórico.
- [ ] Ejecutar tareas 1–4 y suites de respuesta/propuestas en verde; guardar un commit.

## Tarea 5: Compatibilidad, prueba local y documentación

**Files:** modificar `docs/coach-validation.md`; ampliar `apps/bot/tests/test_pending_changes.py`, `test_ai_job_completion.py` y pruebas del worker si se detecta un caso no cubierto; crear `apps/sync-local/tests/manual_coach_generation_smoke.py`.

- [ ] Ejecutar todas las suites unitarias del worker y bot:

```sh
# Desde apps/sync-local
.venv/bin/python -m unittest discover -s tests -v
# Desde apps/bot
.venv/bin/python -m unittest discover -s tests -v
```

- [ ] Verificar aceptación del adaptador por el backend con propuestas autorizadas, prohibidas, duplicadas y revisión obsoleta. Conservar la prueba de no marcar failed tras perder el acuse de completado. Las pruebas con base de datos externa deben usar una instancia de pruebas; si no está disponible, informar el alcance no ejecutado.
- [ ] Crear comprobación manual que importe únicamente los módulos nuevos, construya contexto sintético y llame al endpoint local de Ollama con `httpx`. No invocar `process_job`, APIs del backend o Telegram. Casos: descanso, sesión planificada, análisis e incertidumbre. Medir llamadas/latencia y verificar el contrato final; el resultado del modelo nunca sustituye las aserciones.

```python
wire = generate_validated(question, synthetic_compact, generate=local_ollama)
CoachStructuredResponse.model_validate(wire.model_dump(mode='json'))
assert local_ollama.calls <= 2
assert wire.answer
```

`local_ollama` es un adaptador HTTP con contador que solo permite `127.0.0.1`/`localhost`; `synthetic_compact` contiene únicamente fixtures sintéticos definidos en el script. Para cada caso se comprueban además acción, fechas y objetivos esperados, o reserva explícita si el modelo agota el intento; un fallo real se investiga y se reporta, no se da la prueba por superada.

- [ ] Ejecutar esa comprobación con `garmin-coach:9b` y confirmar aceptación real del esquema discriminado. Si el servidor no está disponible, documentar el bloqueo y no afirmar validación real del modelo.
- [ ] Actualizar `docs/coach-validation.md` con arquitectura, cobertura comprobada, límites del catálogo, logs y limitaciones observadas. No conservar cifras antiguas de latencia como resultados de este cambio.
- [ ] Revisar diff, ejecutar `git diff --check`, comprobar ausencia de credenciales y realizar revisión final de requisitos. Usar `verification-before-completion` antes de declarar éxito. Integrar mediante la guía de finalización de rama; no activar el worker sobre código parcial.

## Revisión del plan

Cada sección del diseño está asignada a una tarea: contratos/normalización/incidencias a 1; instantánea/referencias/autoridad/resolución a 2; texto y compatibilidad a 3; repair/logs/fallback a 4; regresión y Ollama real a 5. Las cinco condiciones de Review Focus tienen pruebas asignadas. La ejecución no incluye despliegue ni alteración de planes reales.
