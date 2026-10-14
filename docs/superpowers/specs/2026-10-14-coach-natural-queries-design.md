# Diseño: consultas naturales con filtros de actividad

## Objetivo

Evitar aclaraciones genéricas para consultas deportivas concretas que el bot ya puede responder con hechos sincronizados. La resolución debe mantener el alcance de fecha, deporte y métrica que expresó la persona, y pedir una aclaración precisa cuando los datos no permitan seleccionarlos con seguridad.

## Alcance aprobado

Las cinco consultas reportadas son criterios de aceptación:

1. «¿Cuál es el entrenamiento para mañana, día 14 de octubre?» resuelve una consulta de plan para el 14 de octubre de 2026 cuando el reloj local indica 13 de octubre de 2026. La fecha relativa y la fecha escrita deben coincidir; si entran en conflicto, se pide aclaración.
2. «Analiza mi última sesión de bici» selecciona la actividad de ciclismo más reciente del historial sincronizado de los últimos **120 días**. Ordena por instante absoluto UTC cuando los inicios tienen desfase fiable; el día visible se asigna con la fecha local de inicio. Si el inicio solo tiene hora local sin zona, solo compara registros que comparten ese contexto horario; ante contextos distintos o empate sin desempate fiable, pregunta cuál elegir. Si la cobertura de 120 días está confirmada y no hay ciclismo, responde «No hay ciclismo en los últimos 120 días»; con cobertura parcial, informa el intervalo realmente cubierto y dice que no encuentra ciclismo en esos datos.
3. «La actividad de ciclismo del día 10 de octubre» y «Analízame las actividades de ciclismo del día 10 de octubre» limitan la observación a actividades de ciclismo del 10 de octubre de 2026. El sintagma sin verbo solo se acepta si incluye un sustantivo de actividad y un deporte reconocible junto con la fecha. Si hay varias actividades ese día, se analizan por separado, sin combinarlas.
4. «¿Me puedes decir mis pulsaciones máximas en la actividad de carrera de hoy?» responde con `max_hr` por cada actividad de carrera de hoy que lo tenga. Si hay más de una, las presenta por separado; no calcula un máximo agregado. La respuesta informa el dato y su fuente; no infiere zona, intensidad ni valoración del esfuerzo. La única métrica de actividad admitida inicialmente es `max_hr`; «pulso medio» u otra métrica no admitida recibe una aclaración que indica que por ahora solo está disponible el pulso máximo registrado.

## Diseño

Se amplía el contrato determinista de intención para representar el deporte opcional y el foco métrico opcional de cada componente, además de fecha e intención. La búsqueda de «última» usa como límite superior los 120 días que el sincronizador solicita a los proveedores (`START_DATE = hoy - 120 días`); no afirma ser el último entrenamiento de toda la vida. Si la fuente no acredita cobertura completa de ese intervalo, la respuesta debe indicar la cobertura real y no afirmar que no hubo actividad fuera del periodo consultado.

### Normalización de deporte

Las formas del texto se normalizan antes de resolver: `bici`, `bicicleta`, `ciclismo`, `salida en bici`, `ruta en bici`, `rodillo`, `ciclismo indoor` y `bici estática` → `cycling`; `correr`, `running`, `rodaje`, `actividad de carrera` y `carrera a pie` → `running`; `nadar`, `natación` y `sesión de natación` → `swimming`; `fuerza` y `sesión de fuerza` → `strength`. La palabra aislada `carrera` no basta: «la carrera de Málaga» describe una competición/evento y no una actividad, por lo que se pide aclaración o se conserva la intención de evento según el contexto, nunca se filtra automáticamente como running.

Los adaptadores normalizan las variantes del proveedor a los mismos deportes. La tabla es el contrato cerrado inicial; los valores desconocidos se conservan en los datos como `other`, pero no cuentan como coincidencia positiva con un deporte solicitado:

| Proveedor | Tipos/valores de entrada | Deporte normalizado |
|---|---|---|
| Garmin | `running`, `trail_running`, `track_running`, `treadmill_running`, `run` | `running` |
| Garmin | `cycling`, `road_biking`, `mountain_biking`, `gravel_cycling`, `indoor_cycling`, `virtual_ride`, `bike`, `cycling_virtual` | `cycling` |
| Garmin | `lap_swimming`, `open_water_swimming`, `swimming`, `pool_swimming` | `swimming` |
| Garmin | `strength_training`, `strength` | `strength` |
| Strava | `Run`, `TrailRun`, `VirtualRun` | `running` |
| Strava | `Ride`, `VirtualRide`, `EBikeRide`, `MountainBikeRide`, `GravelRide`, `Handcycle`, `Velomobile`, `RoadBiking`, `MountainBiking`, `IndoorCycling`, `VirtualCycling`, `cycling` | `cycling` |
| Strava | `Swim`, `OpenWaterSwim`, `PoolSwim` | `swimming` |
| Strava | `WeightTraining`, `Crossfit` | `strength` |
| Zepp | `sport_mode=7` (valor presente en fixture de carrera); título (solo fallback) con palabra completa `run`, `running`, `correr`, `treadmill`, `rodaje` o frase completa `carrera a pie` | `running` |
| Zepp | `sport_mode`/`type` solo cuando el código esté respaldado por fixture o contrato del proveedor; título (solo fallback) con palabra completa `bike`, `biking`, `ride`, `cycling`, `ciclismo`, `bici` o `rodillo` | `cycling` |
| Zepp | `sport_mode`/`type` solo cuando el código esté respaldado por fixture o contrato del proveedor; título (solo fallback) con palabra completa `swim`, `swimming`, `natación` o `nadar` | `swimming` |
| Zepp | `type=52` (código estructurado cubierto por fixture) | `strength` |
| Garmin | `multisport`, `triathlon`, `duathlon`, `brick` en el tipo estructurado | `multisport` |

En Zepp se consulta primero el código estructurado (`sport_mode` y `type`) con una tabla explícita de códigos confirmados; si contradice el título, prevalece el código. El código conocido de fuerza `type=52` sigue normalizado a `strength`; `sport_mode=7` se conserva como caso de running respaldado por la fixture existente. No hay en las fixtures actuales un código numérico confirmado de ciclismo o natación: no se inventa uno. Los códigos no reconocidos prueban como último recurso el título mediante coincidencia de palabra completa, nunca por subcadena; `ride` no casa con «bridge» y `run` no casa con «prune». Si no hay coincidencia, el deporte es `other`. Los tipos editables desconocidos no se adivinan.

La bici de interior, bicicleta estática, rodillo y ciclismo virtual cuentan como `cycling` para seleccionar la última actividad; el tipo original permanece visible en la evidencia para distinguirlos cuando sea relevante. Las pruebas incluirán muestras de Strava de tipos distintos a `Ride` para impedir que queden fuera del filtro.

Las actividades cuyo tipo estructurado de Garmin sea multideporte se normalizan como `multisport`, no como `other`, y este cambio no las divide en segmentos. Si una actividad `multisport` es más reciente que la última actividad de ciclismo conocida dentro de la ventana, la consulta «última sesión de bici» explica que el registro multideporte podría incluir ciclismo y pregunta si se analiza; no afirma cuál fue la última salida ni lo omite en silencio. Si no hay segmento deportivo explícito, no se infiere que ese multideporte incluya bici.

### Orden, procedencia y métrica

El contexto de evidencias conserva dos datos separados: `started_at_utc` (instante absoluto derivado solo de una marca con zona/desfase explícito o de un epoch) y `local_date` (día civil local de la actividad según el proveedor). Para Garmin, la fuente absoluta es `startTimeGMT` y el día local es `startTimeLocal`; para Strava, `start_date` y `start_date_local`; para Zepp, el epoch convertido a la zona horaria configurada. No se fabrica un instante UTC pegando `Europe/Madrid` a una hora ingenua. Las consultas por día usan `local_date`; «última» ordena por `started_at_utc` siempre que sea fiable. Un inicio sin zona solo se compara dentro del mismo contexto horario declarado (misma zona/contexto del proveedor); entre contextos distintos o desconocidos, pregunta cuál elegir. No se usa el orden de entrada ni el ID como sustituto de la hora.

La métrica se renderiza mediante un hallazgo factual determinista nuevo (inicialmente `ACTIVITY_METRIC_VALUE`) con referencia al hecho de actividad y al origen, y pasa por la misma validación de referencias, ámbito y selección que los demás hallazgos. El conjunto permitido es cerrado: `{max_hr}`. La respuesta no expone una métrica solo porque exista en el payload. `None`, cero, valores no finitos y valores fuera de 30–250 lpm se consideran ausentes. Para «pulso medio» se responde con una aclaración concreta indicando que la consulta de actividad disponible actualmente es el pulso máximo (`max_hr`), sin sustituirlo por otro valor.

La extracción del foco métrico también es determinista: «pulsaciones máximas», «pulso máximo» y «FC máxima» con un ámbito de actividad fechado o de última actividad se convierten en `max_hr`. «Pulso medio» y métricas no admitidas reciben `UNSUPPORTED_METRIC`; expresiones teóricas como «mi pulso máximo teórico» no seleccionan datos de actividad. Las aclaraciones de esta ampliación usan códigos fijos y plantillas que no repiten la pregunta: `UNSUPPORTED_METRIC`, `INCOMPARABLE_ACTIVITY_TIME`, `MULTISPORT_ACTIVITY_CONFIRMATION`, `PLAN_SESSION_SPORT_UNKNOWN` y `RACE_EVENT_AMBIGUOUS`.

Cuando la misma actividad está deduplicada entre Garmin, Zepp o Strava y los valores `max_hr` difieren, se muestran todos los valores positivos con sus fuentes y se identifica que las fuentes discrepan; no se elige silenciosamente el valor del registro principal ni se promedian. Para ello, el snapshot debe conservar el valor de la métrica por cada registro de origen y el hallazgo debe referenciar los hechos de todos ellos. Valores cero o nulos de cualquiera de los orígenes se omiten; si todos faltan, se indica que no hay pulso máximo registrado.

### Distinciones de intención y fechas

«Mi última sesión de bici» y «la sesión de ciclismo que hice ayer» significan actividad realizada. «¿Qué sesión tengo mañana?» y «¿qué entrenamiento está planificado para mañana?» significan plan. La presencia de `mi`/`hice` más un selector pasado o de última sesión inclina a actividad; `tengo`, `hay`, `planificado` más fecha futura inclina a plan. Si las señales son mixtas, se aclara.

Si «¿qué sesión de bici tengo mañana?» resuelve a `CONSULT_PLAN` con deporte `cycling`, se filtran las sesiones del día a ese deporte cuando el campo normalizado `sport` está disponible. Las sesiones con otro deporte no se presentan como respuesta. Si existen sesiones sin deporte, se indica que el plan no las clasifica y se pide confirmación antes de atribuirles ciclismo; si no hay sesiones compatibles y el plan cubre la fecha, se responde que no hay sesión de bici planificada. El deporte nunca se ignora sin avisar.

Invariantes del contrato: `sport` solo puede acompañar `ANALYZE_ACTIVITY`, `ANALYZE_DAY` o `CONSULT_PLAN`; `metric` solo puede acompañar `ANALYZE_ACTIVITY` con selector `BY_DATE` o `LATEST_ACTIVITY`; la métrica requiere por tanto un ámbito de actividad y no puede combinarse con intención de plan, recomendación, cambio, aclaración o selector `LATEST_TRAINING_DAY`. Los valores de deporte y métrica deben pertenecer a sus conjuntos admitidos; una combinación inválida falla en construcción/validación del contrato antes de producir hallazgos.

Una frase nominal factual sin verbo se admite solo con sustantivo de actividad + deporte + fecha (por ejemplo, «la actividad de ciclismo del 10 de octubre»). Si ese día hay varias actividades del deporte pedido, se devuelve un hallazgo separado para cada una; no se fusionan métricas, duraciones ni cargas.

Para un día del mes sin mes explícito, una consulta sobre actividad usa el mes local actual; si el día indicado aún no ha ocurrido, pide aclarar la fecha en vez de consultar el futuro como si fuera pasado. Una consulta de plan usa la próxima ocurrencia futura de ese día. «Día 14» con «mañana» y la fecha completa se aceptan si coinciden; si el plan no contiene sesión ese día, se responde expresamente que no hay sesión planificada en esa fecha, sin completar el plan por inferencia.

Las consultas sobre el plan reconocerán preguntas naturales de «qué entrenamiento/sesión hay para [fecha]» como `CONSULT_PLAN`. La resolución seguirá siendo local y determinista; el generador no decidirá fechas, deporte ni métrica. La transcripción de audio reutiliza el mismo punto de entrada. Las pruebas de voz usarán transcripciones conocidas; diagnosticar una transcripción concreta de producción queda condicionado a que el texto guardado en el trabajo esté disponible.

Compatibilidad con registros existentes: los registros ya sincronizados no contienen necesariamente `started_at_utc`, `local_date` ni `time_context`. Ante ellos, la selección de «última» devuelve una aclaración segura: no lanza excepción ni usa el orden de entrada como sustituto. Hay que verificar si la siguiente sincronización completa vuelve a normalizar y escribir esos campos; si no reescribe registros antiguos, se prepara un backfill antes de habilitar consultas «última». Son adiciones al contenido sincronizado, y los lectores de API/bot deben ignorar claves desconocidas y seguir leyendo documentos antiguos. No se altera el esquema persistido.

## Seguridad y límites

- No se suman deportes ni escalas de carga diferentes.
- No se deducen valores ausentes ni se interpreta `max_hr` como zona o intensidad.
- El selector de «última» no usa el orden de entrada como sustituto de una hora fiable.
- La ventana de selección de «última» es de 120 días; la respuesta comunica ese límite y no presenta cobertura parcial como ausencia total.
- «Carrera» sin una construcción explícita de actividad no se convierte automáticamente en `running`.
- Un desacuerdo de `max_hr` entre proveedores para la misma actividad se expone con ambas fuentes; no se promedia ni se oculta.
- Cuando no haya actividad o métrica con el ámbito solicitado, la respuesta lo dirá explícitamente y no sustituirá datos de otro deporte.
- El cambio no modifica rutas ni interruptores de alias, no cambia la configuración de Railway y no se despliega a producción.

## Verificación

- Añadir primero casos de regresión para las cinco consultas y comprobar que fallan en el resolutor actual. Mantener exactamente los casos canónicos de alias `/hoy`, `/ultima` y `/feedback` del fixture E14 y comprobar que su resolución no cambia. Añadir las paráfrasis E14 con expectativas explícitas: «¿Cómo fue mi entreno de hoy?» → analizar el día; «Dame tu opinión sobre la última salida» → analizar la última actividad; «¿Qué tal el último día que entrené?» → analizar el último día de entrenamiento.
- Añadir casos positivos de sinónimos textuales y valores de tipo de Garmin, Strava y Zepp, incluyendo `RoadBiking`, `MountainBikeRide`, `IndoorCycling`, `VirtualRide`, `TrailRun` y tipos de natación; comprobar que no se pierden actividades de Strava por el nombre del tipo. Añadir negativos «la carrera de Málaga», «¿qué bici me recomiendas?» y «mi pulso máximo teórico».
- Probar las invariantes del contrato: deporte solo en intenciones de actividad/día/plan, métrica solo en actividad con fecha o última actividad, y rechazo de filtros/métricas no admitidos antes de generar hallazgos.
- Cubrir timestamps con offsets distintos que se ordenan por instante UTC, cambio de día local, fechas ingenuas en un mismo/diferente contexto, timestamps ausentes y empates. Verificar la ventana de 120 días, el mensaje explícito fuera de ventana y que la cobertura parcial no se convierte en afirmación de ausencia.
- Probar pares de intención: «mi última sesión de bici» frente a «¿qué sesión tengo mañana?»; «la sesión que hice ayer» frente a «la sesión planificada para mañana». Probar frase nominal actividad + deporte + fecha, carrera como evento negativo, múltiples actividades del día separadas y «día 14» según análisis/plan, incluido el caso sin sesión planificada.
- Verificar el hallazgo `ACTIVITY_METRIC_VALUE`, evidencia y fuente con `max_hr` positivo, y que cero/nulo son ausentes. Si la actividad duplicada ofrece valores distintos por Garmin y Strava, comprobar que ambos se presentan con procedencia; comprobar también acuerdo, ausencia en uno y ausencia en ambos. «Pulso medio» debe pedir aclaración y mencionar la métrica disponible.
- Ejecutar las pruebas focales del worker y luego su suite completa. Ejecutar la suite del bot para comprobar que el cambio del contrato compartido no altera el enrutamiento ni la ayuda.
- Mantener apagados `COACH_ALIAS_ROUTING_ENABLED` y cualquier aviso de demora durante toda esta tarea.

## Criterio de aceptación

Cada frase admitida se resuelve con su intención, fecha, deporte y métrica esperados; la respuesta solo contiene evidencias del ámbito pedido. Los casos incompletos o ambiguos reciben una aclaración concreta. La suite del worker y la del bot pasan. El cambio queda en una rama local, sin push, merge ni despliegue.
