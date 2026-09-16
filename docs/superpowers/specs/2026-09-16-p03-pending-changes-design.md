# P0.3 — Propuestas persistidas de cambio del plan

Fecha: 2026-09-16

Estado: especificación del diseño aprobado en conversación, incluidos los
requisitos de negaciones, vinculación al plan al crear el trabajo e idempotencia.
El contrato concreto de la implementación se documenta en
`docs/p03-pending-changes.md`.

## 1. Objetivo y frontera obligatoria

Una petición explícita de ajuste puede producir una propuesta estructurada,
validada por Python y persistida como `pending_change`. El flujo termina ahí.

Ollama propone una intención. Pydantic valida su estructura. El dominio decide
si es coherente. El repositorio de propuestas almacena el resultado.

Ningún camino de esta funcionalidad modifica `planned_sessions`. No se incorpora
`PlanChangeService`, aplicación de deltas, aprobación, rechazo por usuario,
autoaprobación, botones, endpoints de aprobación, notificaciones nuevas ni
replanificación automática. La futura capa de dominio que aplique cambios queda
fuera de P0.3.

## 2. Situación comprobada en el repositorio

- `apps/bot/app/store.py` persiste `training_plans` y `planned_sessions` mediante
  SQL explícito con psycopg; existe también almacenamiento por fichero.
- No hay SQLAlchemy, Alembic ni una entidad de usuario separada. Se conserva
  `owner_id`, con la convención actual de propietario derivado de Telegram.
- `ensure_schema` contiene el DDL idempotente. Los identificadores son UUID
  representados como texto y los timestamps de persistencia usan UTC.
- Los planes nuevos reciben un UUID nuevo; el anterior pasa a `superseded`.
  Todavía no existe `revision`.
- `create_ai_job` no fija un plan. Actualmente `/ai/jobs/next` carga el plan activo.
- P0.2 valida `CoachStructuredResponse` en el worker local; el endpoint de
  finalización recibe `structured_output` pero necesita validación tipada de nuevo.
- `_ai_intents` considera fatiga, sueño y dolor como `adjust`. Ese clasificador
  de contexto no sirve como autorización para crear propuestas.
- `/ajustar` devuelve actualmente una respuesta determinista. Las notas de voz
  se transcriben en el worker después de crear el trabajo.
- Los tests utilizan `unittest`. El contenedor copia únicamente la aplicación
  del bot; cualquier contrato compartido debe incluirse en ambos entornos.

## 3. Autorización explícita

Python calcula `interaction_mode` y `requested_change_proposal` a partir de la petición
del usuario, antes de generar con Ollama. Estos campos son metadatos del trabajo,
no campos que el modelo pueda decidir o sobrescribir.

`requested_change_proposal = interaction_mode == PLAN_CHANGE and bound_plan_exists`

El permiso efectivo enviado al worker se llama `change_proposal_allowed_now`.
El backend lo calcula al recoger el trabajo y lo conserva internamente como
`proposal_execution_allowed`. El worker no recibe los flags internos de auditoría.
Las menciones posteriores a `allow_change_proposal` expresan el concepto de permiso;
no existe un segundo flag con ese nombre en el protocolo implementado.

| Mensaje | Modo | Puede proponer con plan activo |
| --- | --- | --- |
| ¿Qué entrenamiento tengo mañana? | READ | No |
| ¿Cómo ves mi carga esta semana? | ANALYZE | No |
| Estoy muy cansado | ANALYZE | No |
| He dormido fatal, ¿qué opinas? | ANALYZE | No |
| Estoy cansado, ajusta mañana | PLAN_CHANGE | Sí |
| /ajustar mañana | PLAN_CHANGE | Sí |
| Reorganízame la semana porque el jueves no puedo | PLAN_CHANGE | Sí |
| No me ajustes el plan | READ / ANALYZE | No |
| No cambies mañana | READ / ANALYZE | No |
| Sí, ajústalo | PLAN_CHANGE | Sí |
| Sí | READ / ANALYZE | No |

El detector reconoce solicitudes directas, preguntas que solicitan una acción y
comandos explícitos. No basta con encontrar una palabra como «ajustar»: debe
excluir negaciones, citas de órdenes y preguntas meramente informativas. La
negación se relaciona con la acción: «el jueves no puedo» no niega «reorganízame».
Ante ambigüedad se mantiene `allow_change_proposal=false`.

«Sí, ajústalo» autoriza proponer, pero no identifica por sí solo una sesión. Si
el contexto no permite resolver el objetivo, se pide concreción sin inventar una
referencia ni persistir una propuesta. No se añade memoria conversacional en P0.3.

El clasificador contextual existente puede seguir ayudando al análisis; nunca
otorga esta autorización. `/ajustar` debe entrar en el flujo de trabajo de IA
autorizado. Las consultas informativas conservan su comportamiento de lectura.

Para voz sin una petición textual explícita disponible al crear el trabajo,
P0.3 conserva análisis y respuesta, con propuestas deshabilitadas. La transcripción
local no eleva permisos del trabajo. Autorizar a partir de voz requeriría una
validación adicional del backend antes de generar, fuera de esta integración
mínima. Esta limitación debe documentarse en la entrega.

## 4. Vinculación del trabajo al plan

Al crear el trabajo se guardan `owner_id`, `interaction_mode`,
`allow_change_proposal`, `plan_id` y `plan_revision`, obtenidos por el backend.
Si no hay plan activo, las referencias son nulas y la autorización es falsa.
Los trabajos antiguos sin estos campos no permiten propuestas.

El contexto del worker se carga por el `plan_id` fijado, nunca sustituyéndolo
por el plan activo actual. Antes de generar, el backend comprueba identidad,
propietario, revisión y vigencia. Si ya no coinciden, deshabilita propuestas para
esa ejecución; el worker no recibe un plan distinto como si fuera el original.

Al volver una respuesta, la validación usa otra vez el trabajo almacenado y su
plan fijado. Una respuesta tardía sobre un plan sustituido o con revisión distinta
produce `INVALID` si su propuesta es estructuralmente válida y estaba autorizada.
Se conserva la referencia original: jamás se reasigna al nuevo plan.

La lectura de vinculación y creación del trabajo debe ser coherente. En PostgreSQL
se realiza en una transacción; la lectura del plan se coordina con su sustitución.
No se necesita guardar una copia completa del plan ni construir un historial de
versiones en P0.3. Si desaparece una referencia requerida por integridad de la
base de datos, se devuelve un error controlado y no se sustituye por otra.

## 5. Revisión mínima

Añadir `training_plans.revision`, entero positivo `NOT NULL DEFAULT 1`. Los planes
existentes y nuevos comienzan en `1`. El almacenamiento por fichero y las lecturas
exponen la misma semántica, incluyendo compatibilidad con registros antiguos.

Cada propuesta copia `job.plan_revision` a `base_plan_revision`, no la revisión
que casualmente tenga el plan al recibir la respuesta. La revisión no procede
del LLM. Regenerar el plan continúa creando un UUID nuevo.

P0.3 no incrementa revisiones porque no modifica sesiones. Una futura operación
que cambie contenido del plan deberá incrementar su revisión de forma atómica.

## 6. Contrato estructurado

Extender `CoachStructuredResponse` con `change_proposal`, opcional. Con autorización
falsa, el esquema enviado a Ollama impide una propuesta no nula y la validación
Python la rechaza igualmente. Con autorización verdadera, una propuesta sigue
siendo opcional: el modelo puede pedir información o concluir que no hace falta.

`StructuredChangeProposal` contiene:

- `reason`: texto obligatorio no vacío, con longitud acotada.
- `confidence`: número finito entre 0 y 1; rechazar booleanos y cadenas numéricas.
- `evidence`: lista acotada de evidencias tipadas, reutilizando las fuentes de P0.2.
- `changes`: lista no vacía y acotada de deltas.

Cada delta contiene `operation`, `session_id`, `proposed_values` y `reason`.
`operation` es un Enum cerrado con las cinco operaciones aprobadas. `session_id`
es obligatorio para todas ellas. Se rechazan campos inesperados y coerciones
numéricas que oculten tipos incorrectos. Fechas ISO se convierten a fechas.

`proposed_values` es un modelo tipado con campos permitidos, nunca un diccionario
arbitrario. Se conservan los nombres del plan: `date`, `sport`, `session_type`,
`duration_min`, `duration_max`, `intensity` y objetivos que ya soporte el sistema.
No admite identidad, propietario, estado, revisión, SQL ni indicadores de aprobación.

| Operación | Semántica que valida el dominio |
| --- | --- |
| RESCHEDULE | Fecha requerida; únicamente cambia la fecha propuesta |
| ADJUST_DURATION | Duración requerida; rango resultante coherente |
| ADJUST_INTENSITY | Intensidad u objetivos permitidos; coherentes con el deporte |
| REPLACE_SESSION | Misma identidad; dosis completa con sport, session_type, duration_min, duration_max e intensity; fecha y objetivos opcionales |
| CANCEL_SESSION | `proposed_values` vacío; no cancela realmente la sesión |

Pydantic comprueba tipos, campos, enums y límites estructurales. El dominio
comprueba combinaciones por operación y coherencia del resultado hipotético.

`REPLACE_SESSION` no crea sesiones. Define una transformación completa de la dosis:
no hereda distancia ni objetivos omitidos, y conserva la fecha si no se indica otra.
Los tipos admitidos y la representación de descanso se detallan en la documentación
de implementación. Un único delta por sesión sigue siendo obligatorio.

El contrato debe tener una única definición compartida por worker y backend,
incluida explícitamente en sus rutas de ejecución y empaquetado. No se trasladan
dependencias de Garmin, voz ni acceso a datos al paquete de contratos.

Las decisiones informativas de P0.2 no se convierten automáticamente en deltas.
La respuesta distingue el plan vigente de lo propuesto y no afirma que un cambio
se haya aplicado. Se conservan las garantías actuales sobre sesiones de mañana.

## 7. Validación de dominio

`PendingChangeValidator` recibe la propuesta tipada, contexto autorizado del
trabajo, vista de solo lectura del plan y sesiones, fuentes disponibles y reloj.
Devuelve errores estructurados con código, índice de delta y campo afectado.
No escribe datos ni recibe métodos para guardar sesiones.

Comprueba como mínimo:

1. Plan y revisión coinciden con la vinculación del trabajo; el plan sigue vigente.
2. Cada sesión existe y pertenece al propietario y plan fijados.
3. La sesión sigue en estado modificable; rechazar sesiones completadas,
   canceladas, con `completed_activity_id` o ya pasadas.
4. Una reprogramación no va al pasado, usando la fecha local Europe/Madrid con
   reloj inyectable; se respetan los límites temporales del plan.
5. Los campos propuestos están permitidos para la operación, tienen sentido
   para el deporte y dejan rangos de duración coherentes con los valores actuales.
6. No hay referencias inventadas, operaciones duplicadas o contradictorias sobre
   una misma sesión. Para P0.3 se admite un solo delta por sesión.
7. Las fuentes citadas están disponibles en el contexto de generación. Esto no
   convierte una afirmación del modelo en un hecho clínico verificado.

Para comprobar valores resultantes se construyen copias o vistas inmutables.
Nunca se alteran los diccionarios compartidos de sesiones. Se reutilizan las
lecturas y reglas existentes que sean aplicables, sin reutilizar sus escrituras.

## 8. Servicio y doble validación

Flujo de una respuesta con propuesta:

1. Python autoriza el trabajo y fija plan y revisión.
2. El worker suministra a Ollama contexto y esquema restringidos.
3. Pydantic local valida la salida; se conservan reparación y fallback de P0.2.
4. El backend recibe la respuesta y carga el trabajo almacenado.
5. Pydantic vuelve a validar la estructura en el backend.
6. Se verifica la autorización guardada, sin confiar en flags del payload.
7. El validador de dominio determina `PENDING` o `INVALID`.
8. El repositorio inserta la propuesta de forma idempotente.

`create_pending_change(...)` centraliza parsing, autorización, dominio y
persistencia. La finalización del trabajo delega en este servicio. El controlador
solo traduce resultados al protocolo HTTP. El worker no tiene credenciales de
PostgreSQL ni acceso al repositorio de propuestas o sesiones.

JSON mal formado o error Pydantic: error controlado y registro diagnóstico
acotado, sin `pending_change`. No registrar indiscriminadamente datos sensibles.
No devolver éxito de propuesta ni dejar excepciones de validación sin tratar.

Propuesta con autorización falsa: rechazarla sin crear `PENDING` ni `INVALID`.
Propuesta autorizada, estructuralmente válida y con errores de dominio: conservar
`INVALID` y sus errores. Respuesta sin propuesta o fallback determinista: no crear
ninguna fila. Un error de persistencia debe permitir reintentar; no se oculta como
si la propuesta estuviera guardada.

## 9. Persistencia e idempotencia

Tabla `pending_changes` y equivalente independiente por fichero:

| Campo | Contenido |
| --- | --- |
| id | UUID como texto |
| owner_id | Propietario obtenido del trabajo |
| training_plan_id | FK al plan fijado |
| base_plan_revision | Revisión positiva fijada al crear el trabajo |
| source_job_id | FK al trabajo de IA, UNIQUE |
| status | PENDING o INVALID al crear |
| source | ollama, asignado por Python |
| proposal_payload | JSON normalizado completo |
| validation_errors | Lista de errores estructurados; vacía si es válido |
| created_at | Timestamp UTC |
| expires_at | Nullable, sin política de expiración automática en P0.3 |

`reason`, `confidence` y `evidence` se conservan dentro de `proposal_payload`;
no se duplican. El resultado de validación se deriva de estado y errores.
No se necesitan timestamps de aprobación, rechazo o aplicación todavía.

Enum de estado preparado para `PENDING`, `APPROVED`, `REJECTED`, `APPLIED`,
`EXPIRED`, `SUPERSEDED`, `INVALID`, sin implementar transiciones. `source=ollama`
identifica al generador; el origen autorizado es siempre una petición del usuario.
No se habilita `SYSTEM_SUGGESTED`.

Una restricción UNIQUE sobre `source_job_id` garantiza una propuesta por trabajo
incluso con peticiones concurrentes. Un reintento devuelve la fila ya creada sin
revalidarla ni cambiar su estado. Un payload normalizado diferente para un trabajo
que ya tiene propuesta devuelve conflicto controlado y conserva la primera fila.

La comprobación de reintento precede a una nueva validación de dominio: que el
plan haya cambiado después no convierte un reintento en una segunda propuesta.
La inserción y finalización asociada del trabajo se coordinan transaccionalmente;
el endpoint no marca completado un trabajo cuya propuesta no pudo persistirse.
La transacción escribe trabajos y propuestas, nunca sesiones.

El adaptador de ficheros usa almacenamiento separado del plan, exclusión mutua
para comprobar e insertar, y reemplazo atómico del fichero. Debe permitir recuperar
un reintento tras fallo entre guardar propuesta y finalizar trabajo. La retención
de planes y trabajos no elimina referencias todavía usadas por propuestas.

El DDL sigue `ensure_schema`: añadir revisión mediante actualización idempotente
del esquema y crear la nueva tabla con FK, CHECK y UNIQUE correspondientes.
No introducir Alembic en este paso. Índices limitados a identidad e idempotencia;
se añadirán índices de consulta cuando haya un consumidor que los necesite.

## 10. Pruebas y criterios de aceptación

Usar `unittest` con fixtures aisladas, reloj fijo y sin requerir Ollama real.

- Todos los ejemplos de intención anteriores, negaciones, citas, ambigüedad,
  ausencia de plan y metadatos antiguos; palabras de fatiga no autorizan cambios.
- Contrato válido, JSON inválido, operación desconocida, campos inesperados,
  confianza fuera de rango/no finita, tipos incorrectos y `session_id` ausente.
- Validación local y backend; un worker manipulado no evita la segunda frontera.
- Propuesta válida genera un único `PENDING`; fallo estructural no genera fila;
  fallo de dominio genera `INVALID` con errores útiles.
- Sesión inexistente, completada, de otro usuario o plan, fecha pasada,
  operación incoherente, fuentes inexistentes y deltas contradictorios.
- Crear trabajo sobre plan A y sustituirlo por B antes de la respuesta: nunca
  validar ni persistir la propuesta como perteneciente a B.
- Cambio de revisión entre creación, entrega al worker y finalización.
- Completar dos veces, incluido reintento concurrente: una sola propuesta.
  Payload diferente: conflicto sin sobrescritura.
- Falla la persistencia: no declarar éxito; un reintento no duplica registros.
- Comparar todas las sesiones antes y después, para propuestas válidas e inválidas,
  incluyendo fichero, registros persistidos y objetos en memoria.
- Verificar que el repositorio de propuestas carece de operaciones de escritura
  sobre planes/sesiones; comprobar el SQL ejecutado por este flujo.
- PostgreSQL: pruebas de integración con base aislada para UNIQUE concurrente,
  rollback, FK y repetición del DDL. Los dobles de base de datos no sustituyen
  estas garantías; si no hay instancia disponible se informa expresamente.
- Ejecutar las suites existentes del bot y worker para comprobar compatibilidad
  con P0.2, routing y respuestas sobre el plan persistido.

Resultado aceptable: una petición explícita autorizada puede crear una propuesta
auditable e idempotente; ninguna prueba ni camino nuevo aplica sus deltas al plan.

## 11. Entrega prevista

La implementación posterior incluirá contratos compartidos, detector de intención,
vinculación de trabajos, lecturas por identidad de plan, revisión mínima, validador,
servicio, repositorio, DDL, integración del worker/backend y tests. También actualizará
la documentación operativa y explicará las comprobaciones ejecutadas y cualquier
limitación de validación de PostgreSQL o voz. No incluye despliegue ni cambios de
datos en Railway durante el desarrollo local.
