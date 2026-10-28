# Valoración semanal fundamentada de `/coach`

Fecha: 28 de octubre de 2026. Estado: diseño para revisión; no implementado.

## Intención y resultado esperado

El usuario quiere que `/coach` explique cómo encaja el entrenamiento realizado en
el **conjunto de la semana**, incluso cuando no coincide con la sesión prevista.
La semana se entiende como lunes a domingo en `Europe/Madrid`; cada día es una
unidad de comparación. La respuesta debe distinguir lo previsto de lo realizado,
explicar las diferencias y señalar cómo podrían afectar a las sesiones que
quedan, con datos y límites visibles. No cambia el plan automáticamente.

El caso de referencia es una carrera fácil prevista y actividades de ciclismo y
fuerza registradas ese día. La respuesta debe reconocer las tres piezas y la
diferencia, sin declarar que la carrera se completó ni que el cambio fue una
sustitución deliberada. Otro caso real de borde es un plan generado el 28/10:
no puede presentarse como el plan que regía un entrenamiento del 27/10.

## Estado de partida

- El worker V3 recibe un plan con sesiones estructuradas y actividades, pero
  `coach_analysis.py` busca correspondencias del mismo día y deporte. Si no las
  encuentra, el catálogo puede limitarse a datos y pedir un plan.
- `planned_sessions` almacena fecha, deporte, tipo, estado y opcionalidad; su
  documento contiene objetivos como duración e intensidad. Los planes antiguos
  pasan a `superseded` y se conservan en PostgreSQL. El contexto del trabajo
  expone hoy un solo plan, ligado al trabajo; no ofrece una selección histórica
  de planes por cada día de la semana.
- V3 no tiene una línea base personal de bienestar validada. Las mediciones
  aisladas no autorizan un juicio de recuperación. E14 continúa siendo una
  evaluación distinta de equivalencia de alias, todavía parcial.

## Objetivos, exclusiones y límites

1. Producir una valoración semanal comprensible: conclusión, diferencias por
   día, efecto plausible sobre lo que queda de semana y siguiente paso útil.
2. Separar adherencia al plan de adecuación al bienestar y de eficiencia
   fisiológica. La primera entra en esta entrega; la segunda solo si se
   establece una línea base personal fiable; la tercera queda para una
   evaluación posterior de tendencias comparables del mismo deporte.
3. Conservar procedencia, fechas, estado de sincronización e incertidumbre de
   cada conclusión. Nunca sumar TRIMP, TSS y carga muscular como si fueran la
   misma escala.
4. Mantener consulta, propuesta y aplicación como operaciones distintas.
   `/coach` puede señalar una posible necesidad de revisar el plan; no crea ni
   aplica cambios y no usa la conversación como autorización implícita.

Quedan fuera: replanificación automática, juicios médicos o de seguridad,
pronósticos de rendimiento, validación de planes nuevos y migración de alias.
La ausencia de datos suficientes debe producir un límite explícito, no una
valoración tranquilizadora ni una carga inventada.

## Qué consultas activan esta valoración

Las preguntas evaluativas de `/coach`, texto libre y voz —por ejemplo «¿qué
opinas de mi entrenamiento de hoy?», «analiza mi entrenamiento de hoy» y
«¿cómo afecta lo que hice a esta semana?»— activan una valoración con ámbito
semanal. La activación usa la pregunta y el origen persistido del trabajo:
un alias migrado que envía una frase canónica conserva su intención y resultado
E14, aunque el texto coincida con «analiza mi entrenamiento de hoy».
El resolutor debe reconocer las paráfrasis humanas sin confundirlas con una
solicitud de cambio. Las preguntas que solo piden consultar el plan o una
métrica conservan su respuesta factual. Los alias deportivos no cambian de
ruta en esta entrega. Una pregunta sin fecha ni referencia temporal suficiente
pide aclaración; no elige una semana en silencio.

## Enfoques considerados

**A. Comparación semanal con hechos y reglas tipadas (elegido para el diseño).**
Python selecciona las versiones de plan pertinentes, relaciona los conjuntos
diarios de sesiones y actividades, calcula diferencias verificables y emite
hallazgos con evidencia y límites. Un renderizador construye la respuesta.
Permite auditar por qué se llegó a cada conclusión; requiere definir y revisar
las reglas de relación diaria. Las inferencias de cobertura entre deportes se
reservan para una etapa posterior con revisión deportiva propia.

**B. Redacción o priorización mediante Ollama sobre los mismos hallazgos.**
Puede aportar fluidez ante combinaciones poco habituales, pero añade latencia y
riesgo de afirmaciones no sustentadas. Solo se considerará después de una
comparación ciega con A y con validación de hechos, relaciones, límites y
permisos. No sustituye el cálculo ni decide correspondencias.

Las respuestas locales antiguas de los alias no se usan como fuente de verdad
para esta valoración: siguen disponibles por compatibilidad mientras E14 y la
transición de Fase 4 se evalúan por separado.

## Ámbito temporal y plan aplicable

- Para «esta semana» o «hoy», el ámbito es el lunes–domingo que contiene la
  fecha local de creación del trabajo. Una fecha explícita válida selecciona
  la semana que la contiene. Las actividades futuras no se tratan como hechas.
  La fecha de la consulta queda fija si el Mac procesa el trabajo más tarde.
- El plan de siete días de `/plan nuevo` es una **ventana móvil** y puede
  cruzar dos semanas de calendario. Para cada día se buscan planes de ese
  usuario cuyo intervalo incluye la fecha; se consideran también los
  `superseded`, no solo el activo. La creación posterior al día no convierte
  un entrenamiento pasado en planificado.
- Si dos planes cubren el mismo día, se usa la versión cuya vigencia anterior
  a la actividad o al día se puede demostrar. Si el plan se creó el mismo día
  y no hay horas fiables para ordenar plan y actividad, o si una revisión
  posterior impide reconstruir el contenido anterior, se presenta la relación
  como indeterminada. Para sesiones futuras se usa la versión más reciente
  conocida al crear el trabajo. El contexto debe conservar ID, revisión,
  fechas de creación y actualización de cada sesión seleccionada. Hoy el código
  inserta sesiones y conserva planes anteriores al crear otro; `/ajustar` solo
  genera una propuesta y no modifica esas sesiones. No hay un historial de
  contenidos anteriores si una sesión llegara a editarse. La inspección del
  código actual solo encuentra inserciones en `planned_sessions`: ni el estado
  ni `completed_activity_id` se actualizan después de crearla. Antes de la
  comparación se repetirá el inventario de escrituras. El `updated_at` del
  plan cambia también al pasar a `superseded` y no prueba una edición de
  objetivos. Si en el futuro el `updated_at` de sesión incluye cambios de
  estado o vínculo, hará falta distinguir las revisiones del contenido de esos
  cambios. Un vínculo válido sigue confirmando la relación con la actividad;
  si el contenido de la sesión pudo cambiar después y no hay instantánea
  anterior, se limita solo la comparación con el objetivo histórico.
- Un día sin plan aplicable se identifica como «sin plan verificable para esa
  fecha»; no equivale a sesión omitida. La conclusión semanal distingue días
  cubiertos, sin plan y con cobertura incierta. No se extrapolan sesiones de
  una semana ni de un plan a otra fecha.

## Relación diaria entre previsto y realizado

La comparación es de **conjuntos diarios**, con sesiones opcionales, descanso,
dobles sesiones y varias fuentes de actividades. Se deduplican registros que
representan la misma actividad antes de evaluar. Una relación explícita y
válida entre `completed_activity_id` y sesión es más fuerte que la similitud;
si hay varias correspondencias plausibles, no se fuerza un emparejamiento.
El vínculo actividad–sesión y la validez histórica del objetivo son atributos
separados: un cambio posterior del estado de la sesión no borra un vínculo
confirmado, y un vínculo confirmado no demuestra que las metas actuales fueran
las previstas antes del entrenamiento.

| Estado informativo | Condición mínima | Lo que no afirma |
| --- | --- | --- |
| Compatible con lo previsto | Deporte y tipo verificables, magnitudes comparables dentro de una tolerancia definida; relación sin confirmar. | Que esa actividad completó la sesión. |
| Compatible con ajustes | Mismo deporte, diferencias verificables de volumen o intensidad; relación sin confirmar. | Que el ajuste fue deliberado o adecuado. |
| Otro deporte el mismo día | Consta otra actividad y no hay una actividad registrada del deporte previsto con cobertura suficiente. | Que hubo sustitución o equivalencia de estímulo. |
| Actividad añadida | Actividad registrada sin sesión prevista correspondiente en un día con plan conocido. | Que la actividad sea contraproducente. |
| Sin actividad registrada | La cobertura del día y proveedores pertinentes es suficiente y no consta actividad relacionada. | Que la sesión fue omitida deliberadamente. |
| Sin datos suficientes | Fuente incompleta, desactualizada, ambigüedad o ausencia de magnitudes comparables. | Cumplimiento, omisión o efecto. |

«Cumplida», «ajustada», «sustituida» y «omitida» solo se usan cuando la relación
pertinente está confirmada por vínculo fiable o confirmación del usuario. Una
sesión opcional sin actividad no se presenta como incumplimiento. Una actividad
en un día de descanso se describe como diferencia respecto al descanso, sin
inferir por sí sola un perjuicio. Las tolerancias deben depender de la métrica,
el tipo de sesión y la calidad de la medición; no se deducen bloques de
intervalos a partir de un ritmo medio.

## Cobertura entre deportes e impacto semanal

La entrega se divide en etapas. **Etapa A**: comparación factual de cada día
con el plan verificable y efecto sobre la estructura de la semana; describe
qué se hizo, qué estaba previsto y qué sesiones siguen, sin declarar que un
deporte cubrió el estímulo de otro. **Etapa B**: activar conclusiones
cualitativas entre deportes solo para reglas de cobertura con datos mínimos,
umbrales y revisión deportiva documentada. **Etapa C**: estudiar bienestar
respecto a una línea base personal y eficiencia fisiológica mediante
tendencias comparables. Las etapas B y C no están incluidas en el plan técnico
de la primera entrega.

Una tabla versionada y revisable puede describir **solapamientos y diferencias
de estímulo**, nunca equivalencias automáticas. Cada regla necesita deporte y
tipo previstos, deporte y tipo realizados, intensidad/volumen verificables,
efecto cualitativo permitido, evidencia requerida y condiciones que bloquean
la conclusión. Si faltan esos datos, se describe la diferencia sin atribuir
una cobertura fisiológica. La tabla se revisa con casos de entrenamiento antes
de habilitar conclusiones de ese tipo.

Tabla inicial de cobertura **propuesta, aún no validada para respuestas**:

| Previsto → realizado | Hecho que puede mostrarse | Conclusión condicionada a revisión deportiva | Conclusión prohibida |
| --- | --- | --- | --- |
| Carrera fácil → ciclismo fácil | Distancia/tiempo de carrera previstos; tiempo, fuente e intensidad registrada en bici. | Posible trabajo aeróbico de modalidad distinta, si el esfuerzo de ambos se puede caracterizar. | Que la bici completó los kilómetros o el estímulo específico de carrera. |
| Tirada larga → ciclismo | Duración/distancia prevista frente a la actividad de bici y sesiones de carrera restantes. | Puede haber trabajo aeróbico, pero la especificidad de la tirada de carrera no queda demostrada. | Que la tirada larga quedó cubierta o que deba recuperarse íntegra otro día. |
| Calidad de carrera → ciclismo o fuerza | Sesión de calidad prevista y deporte realmente registrado. | Ninguna equivalencia de calidad sin objetivos y bloques verificables. | Que el ritmo o los intervalos previstos se cumplieron. |
| Carrera fácil → fuerza | Carga de fuerza registrada, grupo muscular cuando conste y carrera prevista. | Posible conflicto temporal con la próxima sesión de carrera solo si la regla y las fechas lo sustentan. | Que la fuerza sustituyó el rodaje o causará fatiga concreta. |
| Fuerza → carrera o bici | Sesión de fuerza prevista y actividad registrada. | Diferencia de modalidad; no se infiere estímulo muscular equivalente. | Que la fuerza se completó. |
| Descanso → cualquier actividad | Descanso previsto y actividad realizada. | Desviación respecto al descanso; revisar su posición en la semana. | Que la actividad fue dañina o que exige cancelar la próxima sesión. |

La primera versión puede describir siempre los hechos de la segunda columna.
Las inferencias de la tercera columna quedan deshabilitadas hasta definir
umbrales, datos mínimos y revisión deportiva de cada regla. Los pares no
incluidos solo reciben una descripción factual y una limitación explícita.
En las tiradas largas que solo fijan distancia, la etapa A puede mostrar los
kilómetros previstos y realizados, pero no asigna una etiqueta de
compatibilidad basada en duración ni inventa una tolerancia de distancia. El
límite se formula como «sin criterio de compatibilidad validado».

La valoración semanal considera los días transcurridos y las sesiones futuras
de la misma semana de calendario. Presenta por separado carrera, ciclismo y
fuerza; puede señalar conflictos concretos y sustentados, como una sesión de
fuerza de piernas registrada antes de una tirada larga prevista, pero no
calcula una «carga total» entre escalas ni pronostica fatiga individual. Un
conflicto posible se redacta como posibilidad y lleva fecha de ambas sesiones.
La agregación semanal no se obtiene sumando etiquetas diarias: también revisa
el orden, las sesiones restantes, los días sin plan y la cobertura de datos.

«Sin actividad registrada» requiere cobertura comprobada de todos los
proveedores configurados que puedan aportar actividades para ese día; un
proveedor con error, ventana temporal insuficiente o fecha de sincronización
desconocida impide esa conclusión. La frescura se evalúa respecto al día
consultado y al periodo cubierto por cada proveedor, no mediante un único
umbral de horas para toda la semana. Si el sistema no puede demostrar esa
cobertura, usa «sin datos suficientes». La implementación debe exponer el
estado por proveedor y fecha necesario para aplicar esta regla.

## Bienestar, respuesta y permisos

Hasta validar una línea base propia, V3 muestra sueño, pulso en reposo y otras
señales disponibles con fuente y fecha, y declara que no puede calificar la
recuperación respecto al patrón personal. La futura línea base deberá definir
ventana, cobertura mínima por señal, tratamiento de datos atrasados y criterio
de validación. Las molestias registradas se comunican como contexto y límite;
no se convierten en diagnóstico ni en autorización para una sesión.

La respuesta al usuario contiene, en este orden: (1) conclusión semanal
acotada, (2) diferencias importantes de los días relevantes, (3) implicación
para las sesiones que quedan, (4) siguiente paso o aclaración específica y
(5) límites que cambian la interpretación. Cada afirmación enlaza internamente
con IDs de plan, sesión y actividad o con el estado de cobertura; el texto
expone fechas y fuentes útiles sin volcar todas las métricas. Si una revisión
parece razonable, se puede invitar a solicitarla mediante el flujo existente,
sin tratar esa invitación como una propuesta ya creada.

Ante «¿fue eficiente mi entrenamiento?», la etapa A responderá con la
comparación respecto a lo planificado, las diferencias, los límites y las
sesiones restantes. No emitirá un veredicto de eficiencia fisiológica. Si el
endpoint de planes semanales no está disponible por un despliegue anterior,
la respuesta se limitará a hechos comprobables de las actividades del día y
avisará expresamente que no se pudo verificar el plan semanal; no reutilizará
el plan activo como si fuera el plan histórico. El endpoint nuevo devolverá
`job_not_found` para un trabajo inexistente. Ante un 404/405 sin ese código,
el worker comprobará en el esquema OpenAPI si la ruta GET está ausente; solo
entonces degradará. Si la ruta figura, el esquema no puede consultarse, falla
la autenticación o el contexto es incoherente, se tratará como error.

## Evaluación y aceptación

La valoración semanal tiene un corpus propio; **no redefine E14**. Incluye:
carrera prevista con bici y fuerza realizadas; día sin plan; descanso con
actividad; doble sesión; actividad compatible; relación no confirmada;
sincronización incompleta frente a ausencia comprobada; plan anterior que cubre
un día; plan creado después de una actividad; planes solapados; semana que
cruza dos planes; sesión vinculada cuya marca de actualización es posterior a
la actividad; contenido modificado sin instantánea anterior; objetivo sin
ambos límites de duración; endpoint ausente frente a trabajo inexistente;
bienestar ausente, atrasado o sin línea base; y consultas procesadas tras
cambiar la fecha local.

Cada caso registra plan y actividades esperados, clasificación permitida,
afirmaciones prohibidas, evidencia necesaria y utilidad de la respuesta. La
evaluación revisa exactitud de fechas y fuentes, ausencia de relaciones
inventadas, separación de escalas, cautela ante recuperación y efecto semanal
comprensible. Los ejemplos reales aportados por el usuario se reproducen en
fixtures sintéticos o anonimizados. Se compara A con B solo si B se incorpora;
una mejora de fluidez no compensa errores de atribución o permisos.

El diseño se considera listo para implementación cuando la tabla de relaciones
diarias esté definida con ejemplos y límites, y quede identificada la fuente
de versiones históricas de plan. Antes de implementar la compatibilidad por
duración se medirá cuántas sesiones no tienen ambos límites de duración,
separadas por deporte y tipo, en planes generados y guardados. La implementación
de la etapa A se acepta cuando los casos del corpus muestran una conclusión
semanal útil y sustentada, incluyendo un resultado honesto cuando faltan datos.
La tabla de cobertura entre deportes necesita su propia validación antes de la
etapa B.

## Decisiones de esta especificación y pendientes

Fijado por el usuario: semana de calendario lunes–domingo, comparación por día
con efecto en el resto de esa semana, lectura sin cambio automático de plan.
Propuesto aquí: selección conservadora de plan histórico por fecha, seis
estados informativos diarios, activación solo para preguntas evaluativas,
catálogo tipado, cobertura conservadora de proveedores y evaluación
independiente de E14. Pendiente de validar: conclusiones deportivas y umbrales
de la tabla de cobertura, tolerancias por sesión y disponibilidad de
revisiones históricas de plan. Si estas últimas no pueden reconstruirse, la
respuesta debe decirlo; no reconstruye una versión a partir del plan vigente.
