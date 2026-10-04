# Fase 2 — Enforzar intención en generación y validación

## Objetivo

Integrar `IntentResolution` del punto 1 en el pipeline generativo para que las
acciones permitidas dependan de cada componente de la consulta y el validador
rechace respuestas del modelo que excedan ese ámbito.

## Diseño aprobado

- `ContextSnapshot` conserva la `IntentResolution` completa, derivada de la
  pregunta y de la hora de creación del trabajo, guardada en `created_at` por
  el backend. El worker convierte ese instante a Madrid y vuelve a resolver;
  no confía en una intención serializada/transportada como permiso.
- El contexto público y el prompt exponen intención/componentes y fechas de
  observación y consejo sin volver a mezclarlas en un único ámbito.
- Cada decisión estructurada lleva `component_index`; toda decisión con ámbito
  temporal lleva su fecha explícita (nula solo en aclaraciones sin fecha). En
  consultas mixtas se emite una decisión por componente y fecha que
  requiera respuesta. El resolver valida índice, clase de acción e intervalo de
  fecha contra ese componente: lo informativo contra `observed_dates`; la
  prescripción contra `advice_dates`. `keep_plan` solo corresponde a una
  consulta de plan con fecha de consejo, nunca a una consulta histórica.
- `generation_schema(snapshot)` limita acciones según cada componente. En
  análisis retrospectivo no permite decisiones prescriptivas ni `keep_plan`;
  un cambio explícito puede producir únicamente una propuesta y solo si la
  autorización independiente del backend ya está concedida.
- `resolve_generation` repite las restricciones después de validar el JSON,
  incluso si el modelo ignora el esquema, y devuelve `INTENT_MISMATCH` con una
  pista de reparación restringida al mismo ámbito.
- El análisis puro conserva `change_proposal=None`. Una clasificación
  `REQUEST_CHANGE` nunca concede autoridad backend por sí sola.
- `REQUEST_CHANGE` sin autorización backend produce una respuesta fija y segura
  `CHANGE_NOT_AUTHORIZED`, sin llamar al modelo ni crear propuesta.
- El pipeline y el worker enrutan por intención, no por coincidencias léxicas
  independientes ni por presencia de sesiones en el plan.

## Fechas

Las fechas `observed_dates` y `advice_dates` permanecen separadas en el
snapshot. Fechas pasadas pueden ser objetivo de análisis/consulta retrospectiva,
pero no de prescripción. Consultas mixtas conservan ambos conjuntos; cada
componente usa solo sus fechas.

Se eliminará la vista agregada `target_dates` del snapshot tras migrar todos sus
lectores: `coach_generation_context.generation_schema`,
`coach_generation_resolver` y `coach_generation_renderer`. No queda propiedad
de compatibilidad que pueda volver a mezclar los ámbitos.

## Aclaraciones

`INVALID_DATE`, `CONTRADICTORY_OPERATION`, `MISSING_ADVICE_DATE`,
`NO_SCOPE`, `CONFLICTING_SCOPE` y `CHANGE_NOT_AUTHORIZED` usan plantillas fijas
sin invocar Ollama. `UNSUPPORTED_PARAPHRASE` es distinto: se permite que Ollama
responda dentro de un componente sin resolver, con solo `information_only` o
`ask_user`; no se habilitan plan, prescripción ni propuesta.

El límite de generación actual no cambia en esta tarea. El siguiente paso verbal
no vinculante que pueda surgir del análisis no es una decisión de plan; Fase 3
definirá su representación y validación.

## Fuera de alcance

No se implementan todavía la construcción de hechos del punto 3, conclusiones
verificables, renderer nuevo, unificación de entradas, fallback compartido ni
pruebas E15 de persistencia/autorización end-to-end (corresponden a tareas
posteriores). Esta tarea sí asegura que intención no sustituya el permiso
backend ya existente.

## Interruptor y verificación

La aplicación de restricciones nuevas queda bajo `COACH_INTENT_ENFORCEMENT`,
apagado por defecto. Los tests fuerzan el modo encendido. No se habilita por
defecto hasta evaluar los casos E01–E17 y aprobar explícitamente ese cambio.
Con el flag apagado se conserva exactamente el esquema y validación actuales;
`component_index` será opcional en el modelo compatible y requerido por el
esquema/resolver solo en modo enforcement.

Pruebas de contrato, esquema, resolución y pipeline: análisis puro rechaza una
respuesta `keep_plan` inyectada; consulta del plan mantiene `keep_plan`; las
fechas de análisis y consejo no se cruzan; una propuesta sigue dependiendo del
permiso backend; una intención manipulada sin permiso nunca autoriza propuesta.
La verificación de que ninguna ruta persiste cambios del plan sin autorización
es una tarea nombrada de integración posterior: Fase 2, Tarea 5, prueba E15.
