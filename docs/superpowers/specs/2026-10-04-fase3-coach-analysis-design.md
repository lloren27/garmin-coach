# Fase 3 — Análisis fundamentado y respuesta unificada

## Estado y propósito

**Estado:** diseño aprobado en conversación; entregable 1 autorizado y concretado
en `docs/restructuring/fase3_evaluacion/README.md`.

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
2. Una selección de referencia por reglas puras constituye la línea base. Ollama
   solo se conserva para análisis si demuestra una mejora consistente al
   seleccionar hallazgos relevantes para preguntas distintas sobre los mismos
   hechos, en evaluación ciega, sin bajar fidelidad, procedencia o prudencia;
   si no aporta mejora demostrable, el análisis se sirve sin modelo.
3. Si se usa Ollama, selecciona hallazgos de un conjunto tipado y permitido para
   esos hechos. No redacta prosa libre de análisis.
4. Python valida referencias, alcance, precondiciones y límites, y genera el
   texto final desde plantillas/códigos conocidos.
5. El siguiente paso de un análisis es informativo y no vinculante: puede pedir
   una confirmación o el dato que falta; no crea una sesión, una dosis ni una
   modificación del plan. «Qué conviene hacer después» pertenece al componente
   de consejo de la consulta, no al seguimiento del análisis.
6. Si Ollama pierde o empata, el selector determinista es la ruta principal de
   análisis: no hay reserva de modelo ni etiqueta de degradación. Solo si Ollama
   supera la evaluación y se integra, esa misma ruta actúa como reserva ante sus
   fallos, usando los mismos hechos, conclusiones permitidas y renderer. En ese
   caso el origen de reserva queda identificado.
7. La Fase 2 conserva su interruptor `COACH_INTENT_ENFORCEMENT`. La nueva ruta
   completa de Fase 3 tiene un interruptor independiente,
   `COACH_ANALYSIS_V3_ENABLED`, apagado por defecto. Mientras permanezca apagado,
   la ruta anterior sigue atendiendo producción; fusionar código no cambia por
   sí mismo el comportamiento servido. Evaluar o fusionar no autoriza activación.
8. Se reutiliza el contrato público/persistido existente siempre que pueda
   expresar la respuesta final; el contrato de selección de hallazgos es
   interno y versionado. No se introduce una migración de base por defecto.

## Alcance

### Incluido

- Construcción pura de hechos de análisis desde el snapshot validado.
- Comparación prudente entre actividad realizada y plan, con estado explícito
  de correspondencia.
- Interruptor independiente y apagado por defecto para enrutar a la nueva
  implementación de análisis; preservar la ruta anterior como opción de vuelta.
- Selección de hallazgos, límites y seguimiento desde códigos permitidos,
  con referencias a hechos, comparada con un selector determinista de referencia.
- Renderer Python que enlaza observación, conclusión y limitación sin una
  segunda prescripción.
- Consultas mixtas: hallazgos retrospectivos y decisiones futuras conservan
  `component_index` y fecha de Fase 2 y no se cruzan.
- Servicio común para las entradas que ya crean trabajos: texto libre, `/coach`
  y voz transcrita. Los alias locales se simulan exclusivamente en el arnés V3.
- Respuesta determinista coherente con intención y hechos. La integración de
  Ollama, su reparación y reserva se construyen solo si supera la evaluación.
- Evaluación de los fixtures E01–E17 (incluidos E15a y E15b), selección
  determinista de referencia por caso y comparación con las salidas del modelo.
  Incluye consultas distintas sobre los mismos hechos y un caso mixto de análisis
  más consejo. El caso R01 es adicional y no sustituye E01.
- Pruebas de integración E15 de autorización y persistencia, en almacenamiento
  aislado; incluir PostgreSQL aislado cuando el entorno de pruebas esté
  disponible.

### Fuera de alcance

- Cambiar el enrutamiento real de `/feedback`, `/semana` y `/proximo`: siguen
  respondiendo en Railway mediante su lógica actual, con ambos valores del flag
  del worker y aunque el Mac esté dormido. Su migración requiere una decisión
  posterior explícita sobre disponibilidad y dependencia del Mac.
- Diagnóstico médico/fisiológico o inferencia de zonas a partir de métricas
  insuficientes.
- Que el modelo escriba libremente la explicación o seleccione hechos/números
  nuevos.
- Que un análisis puro recomiende una nueva dosis, cree una sesión o cambie el
  plan.
- Medición de mejora contra las respuestas Ollama anteriores de Fase 0: aquella
  línea base no se considera comparable al nuevo contrato tipado; se conserva
  como evidencia histórica cualitativa, no como benchmark directo.
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
- `candidate`: coincidencia plausible según fecha, deporte y magnitudes
  compatibles;
- `ambiguous_multiple`: varias parejas posibles;
- `implausible_single`: pareja única con una magnitud comparable fuera de banda;
- `insufficient_data`: no puede evaluarse la relación por datos insuficientes;
- `none`: no hay candidato.

El análisis nunca crea ni persiste un vínculo. Una comparación con estado
`candidate` se redacta condicionalmente; no se afirma que la actividad complete
o incumpla una sesión concreta.

Un vínculo confirmado prevalece sobre la banda. Sin él, se cuentan primero las
parejas compatibles por fecha local y deporte, sin elegir por su razón. Varias
parejas producen `ambiguous_multiple`; ninguna, `none` si la cobertura es
suficiente o `insufficient_data` en caso contrario. Con una pareja única, la
ausencia de dimensiones positivas comparables produce `insufficient_data`.
Para `candidate`, todas las dimensiones comparables deben tener razón
`observado / referencia` entre `0,5` y `2,0`. Fuera de banda en alguna dimensión
produce `implausible_single`; no se compensa una discrepancia con otra métrica.
En rangos se usa el límite inferior por debajo, el superior por encima y razón
1 dentro del rango.

| Estado | Hallazgo permitido y resultado |
| --- | --- |
| `confirmed` | Comparación dimensional sustentada en el vínculo. |
| `candidate` | `PLAN_MATCH_UNCONFIRMED` y comparación condicional. |
| `ambiguous_multiple` | `PLAN_MATCH_AMBIGUOUS`: enumerar opciones y pedir cuál corresponde; no elegir pareja ni emitir discrepancia de magnitud. |
| `implausible_single` | `PLAN_ACTIVITY_MAGNITUDE_MISMATCH`: mostrar valores de esa pareja, diferencia grande y posible identidad distinta; pedir confirmación, sin porcentajes ni cumplimiento. |
| `insufficient_data` | `PLAN_MATCH_INSUFFICIENT_DATA`: identificar el dato necesario, sin comparación. |
| `none` | `NO_PLAN_FOR_SCOPE`, cuando la cobertura confirma ausencia de sesión compatible. |

La discrepancia exige una pareja única y una magnitud fuera de banda. Se cubre
con pruebas de calentamiento corto (incluido 12 min contra 35–45 min), E01, R01
y un fixture estilo E04 con varias actividades del mismo día. Los límites son
provisionales; no se amplían para convertir a posteriori un caso ambiguo en
candidato.

Reglas de cálculo iniciales:

- Cada comparación declara dimensión y unidad: duración contra duración,
  distancia contra distancia y carga solo contra una métrica de carga compatible.
  No existe el hallazgo genérico `VOLUME_*` si puede ocultar qué magnitud se
  compara.
- En un objetivo escalar positivo, la diferencia es `observado - objetivo` y el
  porcentaje se calcula respecto al objetivo. Para el rango cerrado
  `[mínimo,máximo]`, dentro del rango no hay desviación; por debajo se compara
  con el mínimo y por encima con el máximo más cercano. Ejemplo: 105 min frente
  a 35–45 min = 60 min y 133,3 % por encima del límite superior (45 min), no
  frente al mínimo ni al punto medio. Las cifras se derivan en Python.
- Los códigos son dimensionales, por ejemplo `DURATION_BELOW_PLAN_RANGE`,
  `DURATION_WITHIN_PLAN_RANGE`, `DURATION_ABOVE_PLAN_RANGE`, `DISTANCE_BELOW_PLAN`,
  `DISTANCE_AT_PLAN`, `DISTANCE_ABOVE_PLAN`. No se deduce distancia prevista a
  partir de una duración ni a la inversa.
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

- comparación dimensional: los códigos de duración/distancia definidos arriba;
- relación: `PLAN_MATCH_UNCONFIRMED`, `NO_PLAN_FOR_SCOPE`, `PLAN_MATCH_AMBIGUOUS`,
  `PLAN_MATCH_INSUFFICIENT_DATA`;
- discrepancia de magnitud sin vínculo confirmado:
  `PLAN_ACTIVITY_MAGNITUDE_MISMATCH` (solo presenta magnitudes lado a lado,
  expresa incertidumbre de identidad y pide confirmación; no calcula
  cumplimiento ni porcentaje respecto al plan);
- comparabilidad/cobertura: `PACE_BLOCKS_NOT_COMPARABLE`,
  `INTENSITY_NOT_ASSESSABLE`, `HISTORY_INSUFFICIENT`, `ACTIVITY_NOT_RECORDED`,
  `DATA_COVERAGE_INCOMPLETE`, `MULTISPORT_COMPONENTS_SEPARATE`.
- bienestar/síntomas: `WELLNESS_OBSERVATION_AVAILABLE`,
  `WELLNESS_BASELINE_UNAVAILABLE`, `WELLNESS_TREND_NOT_ASSESSABLE`,
  `SYMPTOM_REPORTED`, `SYMPTOM_CONTEXT_INSUFFICIENT`,
  `SESSION_SAFETY_NOT_ASSESSABLE`.

No todos los códigos se exponen al modelo para cada petición. Python calcula el
conjunto admisible a partir de `AnalysisFacts`; el modelo solo puede elegir y
ordenar dentro de ese conjunto. Cada hallazgo exige las referencias y
precondiciones definidas para su código. Se rechazan referencias desconocidas,
hechos de otro componente/fecha, hallazgos incompatibles con la certeza o
selecciones vacías cuando haya una conclusión relevante disponible.

El siguiente paso usa una lista acotada, por ejemplo
`CONFIRM_PLAN_MATCH`, `PROVIDE_MISSING_CONTEXT`, `REVIEW_HISTORY_WINDOW` o
`CLARIFY_SYMPTOM_CONTEXT`. Solo solicita confirmación/contexto, como cuándo se
presenta una molestia o qué baseline personal usar; no recomienda tratamiento,
intensidad, duración, distancia, ritmo ni modificación del plan. El consejo
deportivo solicitado se gestiona como otro componente de intención, con sus
permisos y validaciones de Fase 2. Si no hace falta pregunta, el seguimiento
puede omitirse.

Para síntomas, el renderer reconoce el dato de forma neutral, sin minimizarlo ni
diagnosticarlo. No añade por defecto consejo clínico ni la plantilla «si persiste
o empeora, consulta a un profesional»: esa recomendación fija queda excluida en
esta fase. Solo puede pedir contexto registrado/faltante y nunca valorar la
seguridad médica de una sesión.

Cuando hay una molestia registrada y se pregunta si realizar una sesión, es
obligatorio el código de limitación `SESSION_SAFETY_NOT_ASSESSABLE`, vinculado
al síntoma y al componente de consejo. Su plantilla expresa «No puedo valorar
si es seguro hacerla». Se acompaña de la pregunta de contexto pertinente; no
diagnostica, recomienda tratamiento ni avala la sesión. El selector o el modelo
no pueden omitir esta limitación obligatoria.

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

El flujo base usa hechos, selector determinista y renderer. Los pasos de Ollama
y reparación siguientes son condicionales a que gane la evaluación; el arnés
experimental solo genera y valida una selección por pregunta, sin reparación.

1. Los canales que ya enfilan trabajos normalizan texto/transcripción a una petición de coach
   sin perder `created_at` ni el texto de consulta necesario para resolver
   intención.
2. El worker vuelve a resolver intención y construye el snapshot por componente.
3. Para componentes analíticos construye `AnalysisFacts` una vez.
4. El selector determinista recibe pregunta y hechos. Si Ollama ha superado la
   evaluación y se ha integrado, recibe el mismo foco, hechos y esquema de selección
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
8. La selección de ruta consulta `COACH_ANALYSIS_V3_ENABLED`. Si está apagado,
   usa el pipeline anterior sin cambios; si está encendido, entra al flujo
   nuevo. El fallback dentro de V3 no sale a la ruta antigua. El flag de
   enforcement de Fase 2 es ortogonal y ambos estados quedan registrados de
   forma segura en la evaluación.

El worker del Mac obtiene `COACH_ANALYSIS_V3_ENABLED` del entorno al arrancar,
después de cargar el `.env` del proyecto mediante el mecanismo existente. Una
variable heredada del proceso/LaunchAgent tiene precedencia sobre `.env`.
El valor validado queda fijo durante la vida del proceso y determina la ruta de
sus trabajos; no se relee el fichero por trabajo. Para volver a legacy hay que
poner el valor efectivo en `off` y arrancar un nuevo proceso del worker. Editar
`.env` no cambia un proceso ya vivo; si el valor procede del LaunchAgent, se
actualiza y recarga su configuración antes del nuevo arranque. El agente actual
programa invocaciones periódicas: la siguiente invocación nueva recoge el cambio,
pero no modifica un trabajo en curso. La verificación de vuelta atrás comprueba
la ruta efectiva al arrancar ese proceso nuevo.

El bot conserva su enrutamiento actual: los
alias locales no crean trabajos y no consultan este flag. El worker legacy no
ejecuta ni replica la lógica local de esos alias. La simulación de alias para
E14 vive solo en el arnés de pruebas y no registra handlers de producción.

La configuración del único worker es autoritativa para los trabajos recibidos;
un valor de ruta enviado por el productor no la sustituye. Un flag ausente o
inválido selecciona legacy, con un código de configuración seguro. No se promete
detectar discrepancias entre réplicas: no existe ese mecanismo en este alcance.
Se registra la ruta efectiva sin pregunta. Para cambios de contrato se actualiza
primero cada lector compatible y luego su productor: worker antes del bot para
peticiones nuevas, y API/bot antes del worker para respuestas nuevas. Los alias
locales se mantienen hasta una migración posterior acordada.

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
- Para cada E01–E17 (E15a/b incluidos), fijar antes de ejecutar códigos
  esperados/admisibles/prohibidos, referencias y cálculos dimensionales
  esperados, limitaciones y seguimiento esperado. Correr primero el selector
  determinista puro y guardar su resultado como línea base reproducible.
- Evaluar la ruta con `COACH_INTENT_ENFORCEMENT=on` y repetir como control con
  el flag apagado. La ruta con flag encendido verifica las barreras candidatas;
  no significa activarlo en producción. Al acabar, dejarlo apagado por defecto
  y documentar la configuración efectiva.
- Evaluar producción simulada con `COACH_ANALYSIS_V3_ENABLED=off` y ruta nueva
  con `on`, manteniendo la ruta anterior disponible y probando vuelta atrás. En
  cada estado, correr con enforcement de Fase 2 encendido y apagado. Al cerrar,
  ambos flags quedan apagados por defecto; no activar en producción.
- El selector determinista de referencia también consume la pregunta y usa un
  mapa explícito y auditable de palabras/frases a familias de hallazgos (p. ej.,
  ritmo, volumen, sueño); su orden por defecto y fallback quedan fijados. Así
  representa una baseline honesta, no una lista que ignora el foco. Añadir pares
  pregunta-hechos: E01 (a) «¿qué tal el ritmo?» / «¿cumplí el volumen?»; E01
  (b) «¿cómo dormí?» / «¿qué diferencia hubo con el plan?»; R01 (c) «¿qué tal
  el ritmo?» / «¿qué diferencia de distancia hubo frente al plan?». Añadir
  además los casos mixtos E01 y E10 descritos abajo. Fijar relevancia esperada
  por pregunta y mantener idénticos hechos dentro de cada par.
- Antes de generar o puntuar, congelar en una versión identificada el mapa de
  palabras clave, prioridades, fallback, preguntas, hechos, expectativas,
  presupuesto de salida y rúbrica. Ambos selectores reciben la misma pregunta,
  hechos y límites de salida. Cualquier ajuste posterior abre una nueva corrida
  versionada; no modifica retrospectivamente el criterio de la anterior.
- Obtener, por pregunta, una salida del selector determinista y una de Ollama.
  Etiquetarlas con identificadores aleatorios, mezclarlas y ocultar el origen a
  quienes puntúan. Mantener la clave de correspondencia separada hasta cerrar
  las puntuaciones. Ollama se conserva solo si gana al selector en relevancia
  pregunta-hallazgo en todos los miembros de al menos tres pares, que abarquen
  al menos dos fixtures distintos, sin perder el resultado esperado ni bajar
  fidelidad, procedencia o prudencia. Un empate lo gana el selector determinista;
  los errores del modelo en el arnés cuentan como fallos, sin reparación ni
  sustitución oculta por la salida determinista. Si no supera el umbral, el
  análisis opera sin modelo. La muestra pequeña y el hecho de que las mismas
  personas redactan fixtures, expectativas y puntuaciones se declaran como
  limitaciones: la revisión ciega no elimina ese sesgo ni demuestra independencia
  estadística.
  La temperatura 0 no se repite por defecto; repeticiones solo para una pregunta
  operativa explícita. Guardar huellas/configuración, reparaciones, latencia,
  flags, origen y rúbricas anonimizadas; no datos privados ni preguntas crudas.
- Usar la revisión de Fase 0 como referencia cualitativa histórica: documentó
  18 salidas de `garmin-coach:9b`, 14 válidas y ninguna familia de caso que
  cumpliera completamente su objetivo funcional. No afirmar una comparación
  numérica «antes/después» porque el contrato y la rúbrica de esa etapa no son
  equivalentes; el benchmark causal de esta fase es Ollama frente al selector
  determinista bajo las mismas preguntas/hechos.
- Un error crítico de hechos, fecha, permiso, correspondencia o persistencia
  suspende el caso y no se compensa con promedios. Cada salida debe aportar
  conclusión útil o limitación/pregunta concreta según lo permitan los hechos.
- Medir latencia y tasa de fallback; informar p50/p95 si el tamaño de muestra lo
  permite. No se fija SLO numérico en esta fase: cualquier objetivo operativo
  debe aprobarse con una línea base real.

### Barreras duras

- Toda cifra/conclusión final se remonta a hechos y fuentes del snapshot; nunca
  se presentan inferencias candidatas como correspondencia confirmada.
- Análisis puro no emite prescripción ni decisión de plan. Consultas mixtas no
  intercambian fechas, acciones ni referencias entre componentes.
- El caso mixto debe satisfacer expectativas analíticas y de consejo: la parte
  «qué hago mañana» se evalúa como calidad de recomendación estructurada de Fase
  2 en esta fase, además de verificar que permanece separada del análisis. No
  se cierra Fase 3 si ese consejo no cumple su fixture esperado.
- En `E01-mixto` y `E10-mixto`, el componente de consejo no puede convertir una
  correspondencia ambigua o un síntoma registrado en autorización para aumentar
  carga ni confirmar una sesión. En ambos fixtures el único desenlace de consejo
  aceptado es pedir confirmación/contexto pertinente; `keep_plan`, cualquier
  prescripción, propuesta de cambio y mutación están prohibidos. Conservar el
  plan almacenado no implica recomendar ejecutarlo. Estas restricciones se
  validan en el backend y en la respuesta renderizada, también en reserva;
  se prueban inyectando `keep_plan` y prescripciones para verificar su rechazo.
- No se confunde falta de datos con ausencia de actividad; ni se deduce
  intensidad, recuperación o cumplimiento de bloques sin soporte suficiente.
- Un JSON inválido, una reparación agotada o un timeout no se entrega como salida
  válida del modelo ni activa un fallback prescriptivo ajeno a la pregunta.
- E15a/E15b demuestran, en almacenamiento aislado, que no hay mutación no
  autorizada y que la propuesta autorizada sigue pendiente hasta aprobación.
- Todos los fixtures E01–E17 tienen resultados esperados registrados y revisión
  completa; las suites de bot y worker pasan. PostgreSQL se prueba en una
  instancia desechable aislada si está disponible; si no, se declara
  explícitamente `no evaluado`.
- E14 verifica equivalencia de las entradas ya enfiladas y alias simulados en
  V3. Además prueba que `/feedback`, `/semana` y `/proximo` reales mantienen su
  respuesta local y no crean trabajos con el worker indisponible y con cualquier
  valor del flag. La unificación real de esos alias queda pendiente: E14 tiene
  cobertura parcial y no se declara aprobado globalmente al cerrar esta fase.
- El enforcement permanece apagado por defecto después de la evaluación.
- `COACH_ANALYSIS_V3_ENABLED` permanece apagado después de evaluar; la ruta
  anterior sigue siendo la ruta efectiva hasta autorización explícita posterior.
  Cualquier activación, despliegue o cambio de entorno requiere una decisión y
  autorización separadas.

## Entregables y secuencia propuesta

1. **Caracterización y protocolo:** congelar fixtures, preguntas, expectativas,
   mapa del selector y rúbrica; pruebas E15 y caracterización E14 con su alcance
   parcial declarado. Fijar resultados obligatorios de ambos casos mixtos.
2. **Hechos:** `AnalysisFacts` y cálculos puros con procedencia, cobertura,
   correspondencia y pruebas de unidades/fechas.
3. **Ruta determinista:** catálogo y precondiciones, contrato tipado y validación
   común, selector que atiende al foco y renderer; consejo mixto y equivalencia
   de texto/voz bajo el flag V3. Los alias locales permanecen en el bot.
4. **Experimento mínimo:** arnés Ollama de una selección por pregunta, validación
   común y renderizado idéntico; sin reparación ni integración de generación en
   producción. Ejecutar la comparación ciega con el protocolo congelado.
5. **Decisión sobre Ollama:** si pierde o empata, cerrar el análisis con la ruta
   determinista. Solo si supera el umbral, construir la generación integrada,
   reparación acotada y reserva, y verificar errores/timeout/JSON inválido y
   reparación agotada antes del cierre. Esta decisión no activa V3.
6. **Cierre:** resultados E01–E17/E15, limitación E14 explícita, ambos casos mixtos,
   pruebas de flags y ruta anterior, suites bot/worker, PostgreSQL aislado o
   `no evaluado`, e informe. Ambos flags quedan apagados; la activación y la
   migración de alias requieren decisiones posteriores.

Cada entregable se implementa con ciclo rojo-verde y pruebas aisladas antes de
continuar. La evaluación no se usa para relajar límites de autoridad.

## Ejemplos de aceptación

### E01 (fixture original de Fase 0)

Se conserva el fixture original: actividad Garmin de 20,02 km en 6304 s
(1:45:04) y plan de carrera suave de 35–45 minutos. Sin vínculo persistido o
confirmación explícita, la relación esperada es `implausible_single`: la razón 105,07/45
es aprox. 2,33, fuera de la banda candidata 0,5–2,0. Emite
`PLAN_ACTIVITY_MAGNITUDE_MISMATCH`, mostrando «1:45:04 registrados frente a
35–45 min previstos», explicando que la diferencia es grande, que quizá no sea
la misma sesión y pidiendo confirmación. No calcula porcentaje de cumplimiento
ni declara incumplimiento. Con vínculo confirmado, sí compara duración y queda
60:04 sobre el límite superior (aprox. 133,5 % sobre 45 min). No existe objetivo
de distancia para comparar. Ritmo global y FC sin referencias compatibles no
demuestran cumplimiento de bloques ni intensidad. El bienestar se puede
describir con procedencia, pero sin histórico no se afirma tendencia ni que esté
«mejor recuperado». El seguimiento del análisis solo solicita confirmación o
contexto.

### R01 (fixture adicional, no sustituto de E01)

El ejemplo de 11,01 km y 3353 s frente a 17 km se conserva como R01. La duración
derivada es 55:53 y el ritmo aproximado 5:05 min/km. Si hay pareja única y
compatible, la razón 11,01/17≈0,65 permite `candidate` bajo la banda inicial; la
comparación de distancia es condicional: −5,99 km (−35,2 % respecto de 17 km).
El ritmo global no prueba bloques. Se pide
confirmación/contexto, sin declarar incumplimiento ni recomendar una dosis.

### E10 y E13 (prudencia con síntomas y bienestar)

E10 reconoce la molestia registrada en el gemelo derecho sin minimizarla ni
diagnosticarla, y no afirma que la sesión de umbral prevista sea adecuada.
Puede pedir contexto breve mediante seguimiento informativo. E13 describe las
mediciones disponibles, pero al faltar baseline no las compara con «lo
habitual» ni concluye recuperación.

### E01-mixto y E10-mixto (análisis y consejo)

En `E01-mixto`, con los mismos hechos y reloj de E01 y «Valora lo que he hecho hoy
frente al plan y dime qué hago mañana», el análisis emite la discrepancia de
`implausible_single`. El componente de consejo de mañana pide confirmar si la
actividad larga corresponde a la sesión prevista; ese es el único desenlace
aceptado mientras no haya confirmación. No emite `keep_plan`, dosis, propuesta
ni mutación. No presupone que el fixture contenga una sesión para mañana.

En `E10-mixto`, se añade «¿hago la sesión de umbral?» a los hechos de E10 con la
molestia de gemelo registrada. La salida reconoce el síntoma y no confirma
automáticamente la sesión de umbral ni declara que sea segura. Incluye
`SESSION_SAFETY_NOT_ASSESSABLE` con «No puedo valorar si es seguro hacerla»;
omitir esa limitación hace fallar el caso. El consejo
estructurado debe pedir contexto sobre si la molestia continúa y cuándo aparece.
`keep_plan`, confirmar la sesión de umbral y cualquier prescripción están
prohibidos, también si el modelo los devuelve. No diagnostica ni da tratamiento;
el plan almacenado permanece intacto sin que ello se presente como un aval para
ejecutarlo. Ambos casos mixtos se revisan como resultados obligatorios, no solo
como pruebas de separación de componentes.

## Ejecución por entregables

La persona usuaria aprobó ejecutar por entregables, comenzando por congelar
fixtures, expectativas, mapa y rúbrica. El entregable 1 se documenta en su plan
y protocolo V1; no se han generado respuestas. Los entregables siguientes se
ejecutarán en ese orden, respetando la decisión condicional sobre Ollama.
La aprobación del diseño no activa flags ni autoriza despliegue o migración
de alias.
