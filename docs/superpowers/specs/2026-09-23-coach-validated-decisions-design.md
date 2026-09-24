# Decisiones del coach validadas antes de redactar

Fecha: 2026-09-23. Estado: propuesta revisada con las correcciones del usuario; sin cambios de ejecución.

## Objetivo y alcance

Aplicar las recomendaciones aportadas por el usuario: contratos por acción, una única fuente de verdad para las sesiones del plan, evidencias identificables, normalización conservadora, errores estructurados, un reintento y texto compuesto después de validar. Mantener las reglas de autorización de cambios del plan y las respuestas de reserva.

Éxito significa que una duración, intensidad o fecha prescrita en el texto procede de la decisión resuelta y validada; una sesión mantenida procede del plan vigente; las evidencias citadas existen en el contexto de esa consulta; una contradicción nunca se corrige silenciosamente.

## Hallazgos en el código actual

- `apps/bot/app/ai_contracts.py` contiene el contrato compartido. `CoachStructuredResponse` lo consume también `pending_changes.py`; sustituirlo directamente rompería compatibilidad con el backend y respuestas anteriores.
- `ai_worker.call_ollama` solicita conjuntamente `answer` y `decisions`. Ya hace un único reintento, pero solo comunica el mensaje del error.
- `_planned_decisions` ya reconstruye desde Python las sesiones de mañana. `_validate_question_target` aún exige que el texto del modelo repita las duraciones correctas.
- La regla de descanso existe desde el 15 de septiembre. El esquema actual permite construir combinaciones que posteriormente rechaza la validación de negocio.
- Las fuentes permitidas ya se calculan y se pasan al modelo, pero se identifican por categorías, no por registros concretos.
- Las propuestas de modificación están sujetas a permisos y a una revisión del plan en el backend. Esta autoridad se conserva.

## Enfoque elegido

Introducir un contrato de generación interno, separado del contrato persistido, y un renderizador determinista en español. Mantener una llamada de generación y, como máximo, una llamada de reparación.

En P0 la composición final es exclusivamente determinista, aunque el estilo inicial resulte más rígido. Una posible paráfrasis de estilo queda fuera de este alcance. Si se incorpora en el futuro, partirá del texto canónico y deberá comprobar que conserva sus hechos e instrucciones, sin añadir ni alterar números, fechas o intensidades; no bastará con comprobar que no aparecen cifras nuevas.

Alternativas consideradas: reforzar únicamente el prompt deja duplicadas las cifras; una segunda llamada para redactar incrementa latencia y vuelve a permitir contradicciones. El texto determinista reduce flexibilidad expresiva, pero garantiza el origen de los datos prescritos. Las consultas de análisis también se componen a partir de hechos referenciados, conclusiones tipadas y limitaciones; no se reutiliza un `answer` libre sin validar.

## Flujo

1. Capturar contexto, fecha de referencia en Europe/Madrid, plan y permisos una sola vez por consulta, y asignar un `context_snapshot_id` generado por Python.
2. Construir un catálogo de evidencias y sesiones autorizadas.
3. Solicitar decisiones tipadas, referencias y conclusiones estructuradas; no solicitar texto final.
4. Normalizar únicamente equivalencias enumeradas e inequívocas.
5. Validar estructura, versión, identidad de la instantánea, referencias y permisos; resolver sesiones del plan; validar reglas de dominio sobre el resultado resuelto.
6. Si existe un error reparable, enviar la salida rechazada y errores estructurados en un único intento de corrección. Repetir todas las validaciones sobre la nueva salida.
7. Componer texto desde el resultado válido y convertirlo al contrato existente para completar el trabajo.
8. Si falla el segundo intento o hay un error no reparable, usar la respuesta de reserva existente. Nunca publicar una propuesta procedente de una salida rechazada.

La resolución precede a las comprobaciones que necesitan datos del plan. El modelo no puede elegir `source=training_plan`; esa atribución la añade Python.

## Contratos y resolución

`CoachGenerationResponse` exige `schema_version: Literal["1"]` y `context_snapshot_id: str`. Python proporciona ambos al modelo y exige sus valores exactos en el esquema de la consulta y en la validación posterior. La versión identifica el contrato interno y sus instrucciones; no se añade obligatoriamente al contrato público ni se migran respuestas históricas. Una versión no soportada produce `UNSUPPORTED_SCHEMA_VERSION` en fase `structure`, reparable una sola vez con el valor esperado.

La instantánea es una copia inmutable del contexto autorizado para esa ejecución: datos, catálogo, plan, fecha de referencia y permisos. Su identificador es opaco, sin datos personales, se genera en Python y se conserva durante el reintento. No lo calcula el modelo ni se reutiliza para un contexto distinto. Una discrepancia produce `CONTEXT_SNAPSHOT_MISMATCH`, fase `reference`, severidad `fatal`, sin reparación. Que el identificador coincida no sustituye las comprobaciones de pertenencia de cada referencia ni la validación vigente de permisos y revisión del plan en el backend.

El nuevo contrato de generación usa una unión discriminada por `action`, con `extra=forbid` y variantes explícitas para las acciones actuales. No se introduce `modify` como sustituto incompatible de `modify_session`.

- `rest`: intensidad limitada a `rest` o `recovery`; ritmo y potencia solo nulos, distancia nula o cero. El descanso no prescribe minutos de entrenamiento. Si se propone movilidad, debe representarse como actividad de recuperación, no esconderse dentro de descanso.
- `keep_plan`: requiere `session_id` de una sesión del plan actual y referencias de fundamento. No admite duplicar fecha, duración, deporte, intensidad ni objetivos. Python copia estos campos, incluida potencia cuando exista, y verifica que la sesión pertenece al ámbito temporal solicitado y sigue planificada.
- Las acciones de actividad conservan los campos y límites aplicables, con verificaciones de duración, deporte, intensidad y formato de ritmo. No se inventan nuevos valores de tipo de sesión.
- `ask_user` e `information_only` no prescriben objetivos de entrenamiento. Usan códigos de información ausente o de conclusión y referencias a hechos.
- `modify_session` es una recomendación, no una escritura del plan. `change_proposal` sigue sujeto a los permisos actuales y a la validación independiente del backend.

La selección de sesiones de hoy, mañana, próxima sesión o semana se obtiene del contexto autorizado y del enrutamiento existente. Si no se puede identificar una sesión sin ambigüedad, se solicita precisión; no se escoge la primera por conveniencia. Una sesión sin identificador utilizable no se ofrece como destino de `keep_plan`.

El resultado interno resuelto se adapta a `CoachStructuredResponse` para preservar la API y la lectura de trabajos anteriores. No se reinterpretan ni migran registros históricos. Los nuevos contratos internos pueden evolucionar sin cambiar el formato de propuestas pendientes.

## Evidencias y explicación

Crear `available_evidence` desde los datos realmente incluidos en el contexto: actividades, sesiones, perfil, check-ins, medidas efectivas de bienestar, pruebas aplicadas, fuerza y Wattwise. Cada entrada contiene identificador, tipo, fecha si existe y hechos con unidades. Usar IDs originales cuando existan; si faltan, identificadores deterministas dentro de la instantánea de la consulta. No fabricar fechas ni presentar estos IDs locales como identificadores persistidos.

Las medidas efectivas conservan su proveedor Garmin o Zepp; no se atribuye todo el bienestar a Garmin. Un objeto vacío, un proveedor no disponible o una medida ausente no constituyen evidencia.

El modelo selecciona `evidence_refs`; Python comprueba pertenencia y obtiene los hechos que se mostrarán. Esto acredita la existencia del registro, no demuestra por sí solo la corrección de una conclusión: los códigos de conclusión que impliquen comparaciones o umbrales deben verificarse contra cálculos existentes. No introducir nuevos umbrales clínicos ni inferencias médicas.

Los motivos, avisos y preguntas se expresan mediante un catálogo finito de códigos y parámetros tipados, con textos españoles en Python. El catálogo debe cubrir las rutas actuales de análisis, recuperación, sesión, semana e información. Un código no soportado se rechaza; no hay vía alternativa de prosa libre que reintroduzca una prescripción contradictoria. Los nombres o notas de fuentes se tratan como datos y no como instrucciones.

Para P0 el catálogo será deliberadamente pequeño: motivos y conclusiones necesarios para los casos existentes y sus pruebas, sin intentar representar todo el lenguaje natural. Incluir una conclusión requiere un caso real, datos que permitan validarla y una plantilla verificable. Cuando el análisis solicitado exceda ese catálogo, se comunican los hechos disponibles y la limitación, o se usa la respuesta de reserva; no se inventa una conclusión. Códigos como `TOTAL_LOAD_ACCEPTABLE` no se incorporan sin un cálculo existente que los respalde. Las ampliaciones posteriores se harán conforme aparezcan necesidades concretas.

Las evidencias de `change_proposal` se seleccionan igualmente del catálogo y se convierten al formato que espera el backend, comprobando además `proposal_evidence_sources`. No se elimina evidencia inválida silenciosamente.

## Normalización, errores y reparación

Normalización con lista cerrada, por campo: espacios y capitalización de enumerados y alias demostrablemente equivalentes. No aplicar traducciones generales ni convertir `unknown` en una intensidad supuesta. No reinterpretar `rest + threshold` como descanso válido.

Cada `ValidationIssue` incluye `code: ValidationCode`, `phase: ValidationPhase`, `path`, `severity: ValidationSeverity`, `received` y `repair_hint: RepairHint | None`. Los códigos, fases y severidades son enumerados cerrados. Códigos mínimos: `REST_INVALID_INTENSITY`, `REST_INVALID_TARGET`, `INVALID_PACE_FORMAT`, `UNKNOWN_EVIDENCE_REF`, `UNKNOWN_PLAN_SESSION`, `PLAN_DATE_MISMATCH`, `INVALID_DURATION_RANGE`, `UNAUTHORIZED_CHANGE_PROPOSAL`, `INVALID_STRUCTURED_OUTPUT`, `UNSUPPORTED_EXPLANATION_CODE`, `UNSUPPORTED_SCHEMA_VERSION` y `CONTEXT_SNAPSHOT_MISMATCH`.

`ValidationPhase` distingue `parsing`, `structure`, `reference`, `resolution`, `domain`, `authorization` y `rendering`. La fase indica dónde se detecta el fallo, no atribuye automáticamente su causa al modelo. JSON ilegible pertenece a `parsing`; combinaciones rechazadas por la unión discriminada, a `structure`; referencias inexistentes, a `reference`; problemas al recuperar una sesión, a `resolution`; incoherencias del resultado resuelto, a `domain`; propuestas sin permiso, a `authorization`; fallos al componer el texto, a `rendering`. Un error interno de resolución o renderizado no se envía al modelo para que arregle código o datos del sistema.

Severidades: `normalizable` para equivalencias autorizadas; `retry_required` para estructura o contradicciones corregibles; `fatal` para fallos del contexto o violaciones de autoridad que no deben delegarse al modelo. Una referencia desconocida requiere reparación; una propuesta sin permiso no se puede legitimar mediante un reintento.

La reparación recibe el JSON rechazado como datos delimitados y una lista de incidencias, sin traceback de Pydantic. Pide conservar campos válidos salvo dependencia necesaria, respetar el contexto y no inventar evidencias. El resultado completo vuelve a validarse; no se confía en la afirmación del modelo de haber corregido el error.

`RepairHint` contiene campos tipados opcionales `rule`, `allowed_values`, `allowed_refs` y `expected_value`, según el código. Python los construye a partir del validador y de la instantánea actual, nunca de instrucciones de la salida rechazada. Para `REST_INVALID_INTENSITY` incluye `allowed_values=["rest", "recovery"]` y la regla de descanso; para `UNKNOWN_EVIDENCE_REF`, los `allowed_refs` del catálogo autorizado; para una fecha incorrecta, la fecha esperada. Se aporta la información pertinente al fallo conservando la misma instantánea y las restricciones originales, sin refrescar ni ampliar permisos o fuentes durante el reintento. No se recorta una lista de referencias permitidas de forma que cambie su significado.

Si una respuesta contiene varias incidencias, cualquier `fatal` impide el reintento. Las incidencias reparables se envían juntas en el único intento disponible. Las incidencias fatales no llevan pistas que sugieran conseguir permisos o sustituir la identidad del contexto.

## Registros

Emitir `coach_validation_failure` con ID del trabajo, intento 1/2, versión interna esperada, identificador opaco de la instantánea, fase tipada, código y ruta. Registrar valores de enumerados y referencias acotadas; no registrar preguntas, notas, hechos de salud, respuestas completas ni el contexto. Los errores de Pydantic se transforman sin volcar su `input` o traceback. La decisión rechazada y las pistas detalladas se usan en la reparación local, no se vuelcan íntegramente al log. Los metadatos de versión e instantánea proceden del worker, no de valores arbitrarios devueltos por el modelo.

Mantener `coach_fallback` y añadir una causa estable. Registrar también normalizaciones y reparación satisfactoria con campos acotados. `completed` continúa indicando finalización, mientras `output_source` distingue Ollama de la respuesta de reserva.

## Composición final y compatibilidad

El renderizador usa solo decisiones resueltas y hechos autorizados. Conserva fechas, intervalos completos, unidades, múltiples sesiones por día y distinción entre recomendación y plan persistido. Añade los avisos existentes sobre antigüedad sin duplicarlos. No recorta una sesión o condición necesaria para cumplir el límite de longitud: reduce explicación opcional antes de perder instrucciones esenciales.

Las consultas sin prescripción deben seguir ofreciendo análisis útil mediante conclusiones tipadas y hechos, sin forzar una actividad. La voz se genera a partir del mismo texto validado. Se mantienen finalización idempotente y comprobación de propuestas en el backend.

## Componentes y pruebas de aceptación

Separar contratos de generación, catálogo/resolución, incidencias y renderizado en módulos pequeños dentro de `apps/sync-local/garmin_sync`; `ai_worker.py` coordina. Reutilizar el contrato compartido de salida y sus validadores de propuestas.

Pruebas requeridas antes de implementar cada comportamiento:

- Versión `1` obligatoria; versión ausente o no soportada produce una incidencia estructurada, y solo se acepta después de una reparación válida.
- La instantánea se mantiene en ambos intentos; un ID distinto causa reserva sin reintento, aunque todas las referencias individuales existan. El ID correcto tampoco permite una referencia ajena al catálogo.
- El esquema discrimina por acción y rechaza descanso con tempo, ritmo, vatios o distancia positiva; una intensidad omitida en descanso tiene un valor válido documentado.
- Solo se normalizan alias permitidos, sin ocultar contradicciones.
- `keep_plan` no acepta campos prescritos por el modelo; resuelve exactamente todos los datos de la sesión correcta, incluso dos sesiones el mismo día y potencia de ciclismo.
- Sesión inexistente, cancelada, fuera de fecha o ambigua nunca se resuelve como válida.
- Referencias ausentes, antiguas o de otra consulta no se aceptan; los hechos mostrados proceden del catálogo actual.
- El texto final contiene las cifras, fechas e intensidades resueltas sin cifras alternativas generadas libremente. Cubrir descanso, actividad, semana, análisis y falta de datos.
- La reparación recibe la salida rechazada y errores estructurados, corrige una vez y se revalida; dos fallos llevan a reserva. Una generación válida necesita una sola llamada.
- Las fases distinguen errores de JSON, estructura, referencias, resolución, dominio, autorización y renderizado. Los fallos internos y las violaciones de autoridad no disparan reparación del modelo.
- Cada incidencia reparable recibe la pista apropiada al código desde la misma instantánea; una incidencia fatal prevalece sobre otras reparables.
- El catálogo inicial cubre los casos existentes con cálculos disponibles; una conclusión no soportada no produce prosa libre ni nuevos umbrales. P0 no hace llamadas para parafrasear el texto final.
- Los logs distinguen intentos y códigos sin filtrar texto personal o datos de salud.
- Propuestas autorizadas, no autorizadas, duplicadas y pendientes mantienen sus reglas; completado, Telegram y voz siguen funcionando con el contrato anterior.
- Ejecutar las suites existentes del worker y del bot. Hacer una comprobación local con Ollama y datos sintéticos para confirmar que acepta el esquema discriminado, sin publicar mensajes ni modificar planes reales.

## Límites

El esquema reduce combinaciones permitidas, pero no garantiza obediencia del modelo ni calidad de todas sus inferencias. Las referencias garantizan existencia, no veracidad de cualquier interpretación. Se conservan validación de negocio y reserva. No se cambian modelo, integraciones de sincronización, umbrales de entrenamiento ni política de aprobación de planes.
