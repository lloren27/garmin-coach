# Fase 3 — Análisis fundamentado y respuesta unificada

## Estado y propósito

**Estado:** diseño aprobado en conversación; pendiente de revisión del documento.

**Objetivo:** convertir el contexto y la intención ya resueltos en valoraciones
útiles, verificables y prudentes. Cada análisis debe explicar qué se observa,
qué significa dentro de los límites de los datos y qué información falta o cuál
es el siguiente paso no vinculante. Texto, voz y reserva deben conservar la
misma intención y los mismos hechos.

La Fase 1 estableció procedencia, identidad, deduplicación y cobertura de los
datos. La Fase 2 incorporó resolución temporal y de intención, límites por
componente y validación autoritativa en el worker. La Fase 3 consume esas
garantías: no crea una segunda implementación de procedencia ni confía en la
clasificación de intención como autorización.

## Decisiones de diseño

1. Python construye los hechos y calcula las comparaciones. Ollama no inventa
   números, correspondencias, unidades ni fuentes.
2. Ollama selecciona hallazgos de un conjunto tipado y permitido para esos
   hechos. No redacta prosa libre de análisis.
3. Python valida referencias, alcance, precondiciones y límites, y genera el
   texto final desde plantillas/códigos conocidos.
4. El siguiente paso de un análisis es informativo y no vinculante: puede pedir
   una confirmación o el dato que falta; no crea una sesión, una dosis ni una
   modificación del plan.
5. La reserva usa los mismos hechos, conclusiones permitidas y renderer. No
   deriva a una recomendación fija ajena a la pregunta y se identifica como
   reserva cuando corresponde.
6. La aplicación de restricciones de intención continúa bajo
   `COACH_INTENT_ENFORCEMENT`, apagado por defecto. Evaluar la Fase 3 no activa
   automáticamente el flag ni autoriza un despliegue.
7. Se reutiliza el contrato público/persistido existente siempre que pueda
   expresar la respuesta final; el contrato de selección de hallazgos es
   interno y versionado. No se introduce una migración de base por defecto.

## Alcance

### Incluido

- Construcción pura de hechos de análisis desde el snapshot validado.
- Comparación prudente entre actividad realizada y plan, con estado explícito
  de correspondencia.
- Selección de hallazgos, límites y seguimiento desde códigos permitidos,
  con referencias a hechos.
- Renderer Python que enlaza observación, conclusión y limitación sin una
  segunda prescripción.
- Consultas mixtas: hallazgos retrospectivos y decisiones futuras conservan
  `component_index` y fecha de Fase 2 y no se cruzan.
- Un único servicio de respuesta para texto libre, `/coach`, alias de consulta
  ya existentes y voz transcrita. La transcripción entra como texto al mismo
  pipeline; no se añade una ruta de razonamiento paralela.
- Reserva coherente con intención, hechos y decisiones permitidas, más pruebas
  de fallos de Ollama, JSON inválido, reparación agotada y datos insuficientes.
- Evaluación de los fixtures E01–E17 (incluidos E15a y E15b), repetición del
  subconjunto de modelo local ya definido y un caso real saneado.
- Pruebas de integración E15 de autorización y persistencia, en almacenamiento
  aislado; incluir PostgreSQL aislado cuando el entorno de pruebas esté
  disponible.

### Fuera de alcance

- Diagnóstico médico/fisiológico o inferencia de zonas a partir de métricas
  insuficientes.
- Que el modelo escriba libremente la explicación o seleccione hechos/números
  nuevos.
- Que un análisis puro recomiende una nueva dosis, cree una sesión o cambie el
  plan.
- Cambios de almacenamiento o migraciones, salvo que la revisión demuestre que
  el contrato actual no basta y se apruebe una propuesta compatible separada.
- Rediseñar `/help`, menús o el resto de la experiencia de comandos (Fase 4).
- Refactor general de módulos o despliegue en producción. El despliegue exige
  autorización operativa independiente.

## Arquitectura propuesta

### 1. Hechos deterministas

Crear un módulo puro, propuesto como
`apps/sync-local/garmin_sync/coach_analysis.py`, con un contrato inmutable
`AnalysisFacts`. Cada hecho contiene un identificador local al snapshot, código,
valor y unidad tipados, fecha, referencias de procedencia y estado de cobertura/
frescura relevante. Los hechos derivados incluyen fórmula/unidades y referencias
a sus operandos. No se hacen llamadas de red ni escrituras desde este módulo.

La correspondencia actividad-plan es una de:

- `confirmed`: vínculo persistido o confirmación explícita suficiente;
- `candidate`: coincidencia plausible, por ejemplo fecha y deporte compatibles;
- `ambiguous`: más de una correspondencia plausible o datos insuficientes;
- `none`: no hay candidato.

El análisis nunca crea ni persiste un vínculo. Una comparación con estado
`candidate` se redacta condicionalmente; no se afirma que la actividad complete
o incumpla una sesión concreta.

Reglas de cálculo iniciales:

- Distancia y duración comparables producen diferencia absoluta y porcentaje
  respecto al objetivo positivo; las cifras se derivan en Python.
- Los rangos se conservan como rangos. No se sustituye un rango por su punto
  medio.
- Ritmo/velocidad derivados declaran la duración usada y su posible inclusión de
  pausas. Un ritmo medio no demuestra cumplimiento de bloques de ritmo.
- Carrera, ciclismo y fuerza se presentan por separado. No se suman km ni cargas
  de escalas incompatibles para fabricar un total.
- Carga, zonas e intensidad solo se interpretan cuando existen datos y
  referencias personales compatibles; dos medidas aisladas de pulso no bastan.
- “Sin actividad registrada” solo se afirma si la cobertura permite distinguirlo
  de “sin datos”, error del proveedor o sincronización incompleta.
- El histórico insuficiente, antigüedad, ausencia de objetivos y falta de
  granularidad se representan como desconocidos/limitaciones, no como cero.

### 2. Selección tipada de hallazgos

Crear un contrato interno versionado, propuesto como `AnalysisSelection`, con:

- `schema_version`;
- hallazgos ordenados (`code`, `fact_refs`, `certainty`);
- códigos de limitación;
- un código opcional de seguimiento no prescriptivo;
- `component_index` y fecha cuando el hallazgo pertenece a un componente con
  ámbito temporal.

Catálogo inicial propuesto (la implementación puede ajustar nombres antes del
plan, sin ampliar el significado):

- volumen: `VOLUME_BELOW_PLAN`, `VOLUME_WITHIN_PLAN`, `VOLUME_ABOVE_PLAN`;
- relación: `PLAN_MATCH_UNCONFIRMED`, `NO_PLAN_FOR_SCOPE`, `PLAN_MATCH_AMBIGUOUS`;
- comparabilidad/cobertura: `PACE_BLOCKS_NOT_COMPARABLE`,
  `INTENSITY_NOT_ASSESSABLE`, `HISTORY_INSUFFICIENT`, `ACTIVITY_NOT_RECORDED`,
  `DATA_COVERAGE_INCOMPLETE`, `MULTISPORT_COMPONENTS_SEPARATE`.

No todos los códigos se exponen al modelo para cada petición. Python calcula el
conjunto admisible a partir de `AnalysisFacts`; el modelo solo puede elegir y
ordenar dentro de ese conjunto. Cada hallazgo exige las referencias y
precondiciones definidas para su código. Se rechazan referencias desconocidas,
hechos de otro componente/fecha, hallazgos incompatibles con la certeza o
selecciones vacías cuando haya una conclusión relevante disponible.

El siguiente paso usa una lista acotada, por ejemplo
`CONFIRM_PLAN_MATCH`, `PROVIDE_MISSING_CONTEXT` o `REVIEW_HISTORY_WINDOW`. Estos
códigos no contienen intensidad, duración, distancia, ritmo ni instrucción para
modificar un plan. Si no hace falta pregunta, puede omitirse.

### 3. Renderizado y consultas mixtas

El renderer produce una respuesta breve en este orden, omitiendo secciones no
justificadas:

1. observaciones relevantes con unidades y procedencia;
2. comparación calculada y conclusión tipada;
3. condición/limitación necesaria para no sobreafirmar;
4. seguimiento informativo o dato que falta.

Las decisiones de consejo o plan siguen el contrato estructurado de Fase 2;
no se convierten en hallazgos ni se reescriben como prosa libre del modelo. En
una consulta mixta cada salida conserva su componente y fecha. La salida externa
mantiene `CoachStructuredResponse` salvo que la implementación demuestre una
carencia concreta; cualquier ampliación requiere compatibilidad de lector antes
de cambiar productor/worker.

### 4. Flujo unificado y reserva

1. Los canales de entrada normalizan texto/transcripción a una petición de coach
   sin perder `created_at` ni el texto de consulta necesario para resolver
   intención.
2. El worker vuelve a resolver intención y construye el snapshot por componente.
3. Para componentes analíticos construye `AnalysisFacts` una vez.
4. Ollama recibe únicamente contexto/factos relevantes y el esquema de selección
   permitido. Se permite como máximo una reparación, con los mismos hechos,
   fecha e intención; los logs contienen códigos/rutas seguros, nunca pregunta,
   respuesta cruda ni métricas privadas.
5. Python vuelve a validar autoridad, referencias, fechas, códigos y
   precondiciones; renderiza una única respuesta.
6. Si Ollama falla o agota la reparación, el fallback determinista usa el mismo
   snapshot y renderer. Para datos insuficientes responde con la limitación o
   pregunta concreta; no inventa una recomendación de entrenamiento. El origen
   fallback queda distinguible en metadatos existentes.
7. Voz sintetiza el texto final común; la síntesis o entrega fallida no dispara
   un segundo análisis ni altera el plan.

El permiso de propuesta/aplicación permanece en backend. Una intención
`REQUEST_CHANGE` no otorga permiso. E15a debe completar una respuesta informativa
sin propuesta ni mutación cuando no hay solicitud explícita; E15b puede crear
una propuesta `PENDING` solo con autorización válida y mantener el plan sin
cambios hasta el flujo de aprobación existente. No se considera aprobada una
propuesta solo por estar bien clasificada.

## Evaluación y criterios de aceptación

### Cobertura reproducible

- Ejecutar el evaluador determinista sobre todos los fixtures disponibles E01–E17
  (E15a/E15b como subcasos), respetando la diferencia entre `cumple`,
  `incumple` y `no evaluable`. No convertir cobertura parcial de un caso en
  aprobación completa.
- Ejecutar E01, E07, E08, E09, E10 y E13 tres veces cada uno con el Ollama local,
  y el caso real saneado tres veces (21 salidas). Guardar hashes/estado del
  fixture, modelo, presupuesto, reparaciones, latencia, origen final y resultado
  de revisión; no guardar datos reales identificables ni sobrescribir corridas
  previas.
- Revisar cada salida con la rúbrica existente de fidelidad, procedencia,
  utilidad y prudencia (0–2). Un error crítico de hechos, fecha, permiso,
  correspondencia o persistencia suspende el caso y no se compensa con el
  promedio de otros casos. Cada ejecución debe tener una conclusión útil cuando
  los hechos la permiten, o una limitación/pregunta concreta cuando no.
- Medir latencia y tasa de fallback; informar p50/p95 si el tamaño de muestra lo
  permite. No se fija SLO numérico en esta fase: cualquier objetivo operativo
  debe aprobarse con una línea base real.

### Barreras duras

- Toda cifra/conclusión final se remonta a hechos y fuentes del snapshot; nunca
  se presentan inferencias candidatas como correspondencia confirmada.
- Análisis puro no emite prescripción ni decisión de plan. Consultas mixtas no
  intercambian fechas, acciones ni referencias entre componentes.
- No se confunde falta de datos con ausencia de actividad; ni se deduce
  intensidad, recuperación o cumplimiento de bloques sin soporte suficiente.
- Un JSON inválido, una reparación agotada o un timeout no se entrega como salida
  válida del modelo ni activa un fallback prescriptivo ajeno a la pregunta.
- E15a/E15b demuestran, en almacenamiento aislado, que no hay mutación no
  autorizada y que la propuesta autorizada sigue pendiente hasta aprobación.
- Suites de bot y worker pasan; E14 demuestra que texto, comando/alias acordado y
  voz transcrita llegan al mismo contrato/intención. PostgreSQL se prueba en una
  instancia desechable aislada cuando esté disponible; si no, se declara
  explícitamente no evaluado.
- El enforcement permanece apagado por defecto después de la evaluación.
  Cualquier activación, despliegue o cambio de entorno requiere una decisión y
  autorización separadas.

## Entregables y secuencia propuesta

1. **Caracterización y barreras:** fixtures/contratos de evaluación actualizados;
   prueba E15 de autorización/persistencia; caracterización de rutas E14.
2. **Hechos:** `AnalysisFacts` y cálculos puros con procedencia, cobertura,
   correspondencia y pruebas de unidades/fechas.
3. **Hallazgos:** catálogo y precondiciones, contrato de selección tipada,
   generación restringida, validación y reparación acotada.
4. **Respuesta común:** renderer determinista, comportamiento mixto, fallback
   con los mismos hechos y equivalencia de texto/voz.
5. **Evaluación y decisión de activación:** corridas E01–E17/E15, 21 revisiones
   del modelo, informe, regresiones de bot/worker, compatibilidad y propuesta de
   activación separada (sin activar por defecto).

Cada entregable se implementa con ciclo rojo-verde y pruebas aisladas antes de
continuar. La evaluación no se usa para relajar límites de autoridad.

## Ejemplo de aceptación: E01

Con una actividad registrada de 11,01 km y 3353 s frente a una sesión prevista
de 17 km, el sistema calcula duración `55:53`, ritmo aproximado `5:05 min/km`,
diferencia `−5,99 km` y `−35,2 %` respecto a 17 km. Si el vínculo actividad-plan
solo es candidato, debe expresarlo condicionalmente: “si esta actividad
corresponde a la sesión prevista”. El ritmo global no prueba los bloques de
ritmo; FC media/máxima sin referencias personales no determina la intensidad.
La respuesta debe concluir que el volumen registrado es menor bajo esa
correspondencia condicional y pedir confirmación o contexto útil, sin declarar
incumplimiento ni recomendar una dosis no fundamentada.

## Revisión pendiente

Esta especificación recoge la dirección aprobada en conversación, pero aún debe
revisarse por la persona usuaria. No autoriza implementación, creación de un plan
detallado, activación del flag ni despliegue. Tras la aprobación explícita del
documento se preparará el plan de implementación de Fase 3 en un paso separado.
