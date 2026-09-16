# P0.3: propuestas persistidas

P0.3 termina al crear una propuesta `PENDING` o `INVALID`. No aplica deltas ni
modifica `planned_sessions`. No incorpora aprobaciones, rechazos por usuario,
transiciones de estado ni notificaciones específicas de propuestas.

## Autorización y contexto del worker

Python reconoce una lista conservadora de peticiones explícitas. `/ajustar mañana`,
«Estoy cansado, ajusta mañana» y «Reorganízame la semana porque el jueves no puedo»
pueden autorizar una propuesta. Fatiga, consultas informativas, negaciones,
órdenes citadas y frases ambiguas no la autorizan.

Al crear el trabajo se guardan:

- `owner_id`, `plan_id` y `plan_revision`, obtenidos del backend.
- `interaction_mode`: `PLAN_CHANGE` para una petición explícita; `ANALYZE` agrupa
  lectura y análisis en esta implementación.
- `requested_change_proposal`: autorización original; requiere petición y plan.

Al recogerlo, el backend lee ese mismo plan y comprueba propietario, estado y
revisión. El worker recibe un único permiso efectivo:

```json
{
  "job": {"id": "job-id", "plan_id": "original-plan", "plan_revision": 1},
  "context": {
    "change_proposal_allowed_now": false,
    "training_plan": {"id": "original-plan", "revision": 1, "status": "superseded"},
    "proposal_evidence_sources": ["backend", "training_plan"]
  }
}
```

El ejemplo abrevia los demás campos. Los flags de auditoría no se incluyen en
`job` enviado al worker. El backend guarda `proposal_execution_allowed` y las
fuentes suministradas para verificar la respuesta. La autorización original se
conserva, aunque el permiso efectivo sea falso.

Si el plan cambia después de recoger el trabajo, una propuesta autorizada y
estructuralmente válida se conserva como `INVALID`, vinculada al plan y revisión
originales. Si ya estaba obsoleto al recogerlo, el worker no puede generar una
propuesta; el backend rechaza cualquier intento. Nunca sustituye la vinculación
por el nuevo plan activo.

Las notas de voz sin una petición explícita en el texto/caption original tienen
el permiso deshabilitado. La transcripción no eleva permisos. Tampoco lo hacen
trabajos antiguos sin metadatos de autorización. «Sí, ajústalo» autoriza solicitar
una propuesta, pero no añade memoria conversacional: si falta identificar la
sesión, el coach debe pedir concreción.

## Contrato y operaciones

`apps/bot/app/ai_contracts.py` es la definición compartida por backend y worker.
El módulo `garmin_sync.ai_contracts` la reexporta desde el checkout; el contenedor
del bot ya incluye la definición al copiar `apps/bot/app`. El worker requiere
mantener ambos directorios del repositorio, como su integración previa con el coach.

`CoachStructuredResponse.change_proposal` es opcional. Incluye `reason`,
`confidence` finita entre 0 y 1, `evidence` y de 1 a 14 deltas. Los campos extra,
operaciones desconocidas y coerciones de números en los deltas se rechazan.
Los campos opcionales `null` significan ausentes, no «borrar el valor».

Cada delta identifica una sesión existente. Solo se admite un delta por sesión,
incluso cuando dos operaciones parezcan compatibles.

| Operación | Valores |
| --- | --- |
| `RESCHEDULE` | `date`, dentro del plan y no anterior a hoy en Europe/Madrid |
| `ADJUST_DURATION` | `duration_min`, y opcional `duration_max`; se valida el rango resultante |
| `ADJUST_INTENSITY` | Uno o más de `intensity`, `target_pace`, `target_power_w` |
| `REPLACE_SESSION` | `sport`, `session_type`, `duration_min`, `duration_max`, `intensity`; opcionales fecha y objetivos |
| `CANCEL_SESSION` | Valores vacíos |

`REPLACE_SESSION` transforma la misma identidad. No crea una sesión nueva.
Representa una dosis completa basada en tiempo: sustituye los objetivos anteriores
y no hereda distancia ni objetivos de ritmo/potencia omitidos. La fecha se conserva
si no se propone otra. El resto de la identidad y posición de la sesión se conserva.
Esta semántica se valida sobre una copia en memoria; no hay código de aplicación.

Los tipos de sustitución se limitan a los soportados por el dominio:

- Running: `easy`, `easy_run`, `easy_progressions`, `aerobic`, `long_run`, `quality`, `recovery`.
- Cycling: `easy`, `recovery`, `aerobic`.
- Strength: `full_body_a`, `full_body_b`.
- Recovery: `rest`, `rest_mobility`.
- Mobility: `rest_mobility`.

Sustituir por descanso utiliza `sport=recovery`, `session_type=rest`, duración
0–0 e intensidad `rest`, sin objetivos de entrenamiento. Para otros entrenamientos
la duración mínima debe ser positiva. Las sesiones originales basadas en distancia
pueden reprogramarse sin inventarles una duración.

## Validación y almacenamiento

El worker valida el esquema y el permiso efectivo; conserva reparación/fallback
de P0.2. Railway vuelve a validar Pydantic antes de persistir. El servicio
`create_pending_change` consulta autorización y contexto del trabajo almacenado;
ningún identificador o flag de permisos del modelo sustituye esos datos.

Un error estructural devuelve HTTP 400 y un diagnóstico acotado en logs, sin fila
de propuesta. Una propuesta no autorizada también se rechaza. Una propuesta
autorizada que falla el dominio se guarda como `INVALID` con errores estructurados.

El repositorio solo expone lectura de plan, búsqueda de propuesta e inserción.
`pending_changes` usa las convenciones existentes: columnas para identidad,
propietario, plan, revisión, trabajo y estado; `document` JSONB contiene el payload
normalizado, origen, errores y timestamps. Motivo, confianza y evidencias están
dentro del payload. `source_job_id` es UNIQUE y tiene FK; el plan también tiene FK.
No se inventa una tabla de usuarios para `owner_id`.

Una fila por trabajo: repetir el mismo payload normalizado devuelve la propuesta
original, incluso si el plan cambió después. Un payload distinto devuelve HTTP 409.
En PostgreSQL la inserción y finalización del trabajo comparten transacción y
bloqueo de fila. En ficheros hay bloqueo entre procesos/hilos y reemplazos atómicos;
un fallo entre guardar propuesta y completar trabajo se recupera al reintentar.
El almacenamiento local conserva planes y trabajos para no perder referencias.

El worker reintenta hasta tres veces con el mismo payload ante errores de transporte
o HTTP 5xx. Si agota los intentos, no sobrescribe el trabajo como fallido: podría
haberse perdido la confirmación de una transacción ya guardada. Un trabajo aún
en ejecución vuelve a ser elegible tras el timeout existente. Las propuestas ya
persistidas nunca se sobrescriben por una nueva generación.

## Esquema y despliegue

`ensure_schema` incorpora `training_plans.revision`, entero positivo con valor
inicial 1, y crea `pending_changes`. La actualización es transaccional e idempotente;
las peticiones normales evitan DDL una vez instalado P0.3. No se introduce Alembic.
Los planes regenerados mantienen el mecanismo actual: nuevo UUID y revisión 1.

Desplegar backend y actualizar el checkout del worker juntos. La definición
compartida evita divergencias de contrato. Este desarrollo no modifica Railway;
los cambios de esquema se ejecutarán al desplegar la versión y usar el almacén.

## Pruebas

Desde la raíz del repositorio:

```sh
PYTHONPATH=apps/bot apps/bot/.venv/bin/python -m unittest discover -s apps/bot/tests
PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests
```

Para la integración PostgreSQL, proporcionar `P03_TEST_DATABASE_URL` apuntando
exclusivamente a una base desechable y ejecutar la suite del bot. Sin esa variable,
se omiten los tests PostgreSQL. Incluyen datos ficticios, concurrencia, rollback,
FK/UNIQUE, revisión obsoleta y migración desde el esquema anterior en un namespace
temporal. Las pruebas comparan `planned_sessions` antes y después del flujo.
