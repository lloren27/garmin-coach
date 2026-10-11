# Fase 4: experiencia simple y entrenador único

Fecha: 11 de octubre de 2026. Revisión 2, tras revisión del usuario.
Estado: diseño revisado para revisión; sin implementación ni activación en producción.

## Base y objetivo

La fase 4 simplifica la experiencia sin prometer capacidades que el entrenador todavía no tiene. El cierre de fase 3 está guardado en `5e4880f`, con código, pruebas y evidencias. El primer borrador de fase 4 ya estaba en el historial; no se reescribe. Los cambios posteriores parten de esta base limpia y separada.

Se han repetido 288 pruebas del worker y 30 del arnés con el entorno virtual del proyecto, todas correctas. No se ha repetido en esta revisión la suite PostgreSQL del bot ni se certifica producción. E14 sigue pendiente.

## Decisión 1: espera con respaldo de datos

Se elige conservar una vista determinista de datos como respaldo. Las recomendaciones de los alias migrados dependen del worker del Mac; las vistas de datos, el plan guardado, el estado y los registros siguen disponibles desde Railway. Esta dependencia es un cambio explícito frente a las respuestas locales instantáneas actuales.

- Acuse inmediato tras persistir el trabajo: «Consulta en cola. El entrenador responderá cuando el procesamiento local esté disponible. Puedes consultar /estado». Si guardar falla, no se anuncia que está en cola.
- A los 120 segundos sin respuesta final, un único aviso por trabajo: «Tu consulta sigue pendiente. Estos son los últimos datos disponibles; no son una valoración del entrenador», acompañado de una vista factual pertinente o de la ausencia explícita de datos. El umbral es configurable y no promete un plazo de respuesta.
- El trabajo sigue pendiente: mostrar datos no lo completa, cancela ni crea otro trabajo. Al terminar se entrega la respuesta final por el flujo existente. Un fallo definitivo se comunica como fallo.
- El aviso se despacha desde el bot/API en Railway, nunca desde el worker cuya ausencia se intenta explicar. Se incorpora un barrido periódico de trabajos vencidos al ciclo de vida de la API, con marca persistente y reclamación atómica para evitar avisos concurrentes. No basta un temporizador en memoria por consulta. Tras reiniciar, se recuperan avisos vencidos aún pendientes.
- Se comprueba otra vez el estado antes de enviar el aviso para minimizar la carrera con la finalización. Telegram no ofrece entrega exactamente una vez: se documentará la ventana residual entre envío y persistencia, sin prometer una garantía absoluta.

El respaldo presenta fechas, procedencia, actividades y métricas registradas, y plan persistido cuando corresponda. No incluye puntuaciones de riesgo inventadas, recomendaciones, conclusiones de recuperación ni prescripciones. No reutiliza íntegramente los antiguos formateadores deportivos: varios contienen opinión.

## Decisión 2: activación reversible y gradual

Se añade `COACH_ALIAS_ROUTING_ENABLED`, apagado por defecto, independiente de `COACH_ANALYSIS_V3_ENABLED`. Apagado conserva las rutas actuales. Encendido solo permite migrar una lista explícita de alias que hayan superado su evaluación; no convierte todos los comandos a la vez.

La activación requiere V3 activo y evaluado en el worker real, capacidad comprobada por alias, avisos de demora y respaldo operativos. Copiar la variable V3 al bot no demuestra qué motor ejecuta el Mac. Los trabajos de alias migrados deben exigir V3 mediante metadatos de compatibilidad; el worker valida ese requisito antes de procesar y no los deriva silenciosamente a Ollama antiguo. Si no cumple, se informa incompatibilidad y se ofrece la vista factual. Desplegar primero un worker que entienda este requisito es condición de activación.

La reversión consiste en apagar el interruptor del adaptador y reiniciar/recargar la configuración de la API según el despliegue. Los nuevos mensajes recuperan la ruta anterior; los trabajos ya encolados mantienen su requisito de motor y no se duplican. No requiere `git revert`.

No se elimina ninguna rama local hasta tener V3 activo, evaluación aceptada de los alias afectados y comprobación de reversión. Mientras se necesite volver a esas ramas, se conservan. Su retirada será un entregable condicionado, posiblemente posterior al despliegue de fase 5. Este documento no declara completada esa retirada.

## Capacidades por alias

Inspección de `coach_findings.py` y sondeo real de `resolve_intent`, con reloj 2026-10-11 12:00 Europe/Madrid. Las preguntas siguientes son candidatas evaluadas por el resolutor, no un catálogo ya conectado. Resolver `analyze_day` no demuestra que existan hallazgos adecuados ni filtros por deporte. «Semana» resolvió del 5 al 11 de octubre; los selectores de última actividad/día necesitan la instantánea para concretar fechas.

| Alias | Pregunta canónica candidata | Resolución observada | Hallazgos disponibles y carencias | Respuesta prevista / decisión |
| --- | --- | --- | --- | --- |
| `/hoy` | Analiza mi entrenamiento de hoy. | `analyze_day`, 11/10 | Comparación sesión/actividad, ritmo medio, bienestar y síntomas; no recomendación general para el resto del día | Candidato: análisis del día con límites y aclaraciones. |
| `/ultima` | Analiza mi última actividad. | `analyze_activity`, `latest_activity` | Comparación duración/distancia y correspondencia con plan | Candidato: explicar comparación sin dar sesión por cumplida si es ambigua. |
| `/feedback` | Analiza mi último día de entrenamiento. | `analyze_day`, `latest_training_day` | Actividades, comparación, separación de deportes, bienestar y síntomas | Candidato: análisis del último día, sin prescripción no soportada. |
| `/salud` | Analiza mi recuperación hoy. | `analyze_day`, 11/10 | `WELLNESS_OBSERVATION_AVAILABLE`, ausencia de referencia y tendencia no evaluable | Vista factual: sueño, reposo y estrés; no afirmar recuperación. |
| `/fatiga` | Valora mi fatiga hoy. | `analyze_day`, 11/10 | No hay hallazgo de fatiga acumulada validado | Vista factual, sin calificación de fatiga ni recomendación. |
| `/carga` | Analiza mi carga esta semana. | `analyze_day`, 5–11/10 | Separación de deportes; sin valoración agregada de carga | Vista de métricas disponibles por deporte y escala, sin suma entre escalas. |
| `/tendencia` | Analiza mi tendencia esta semana. | `analyze_day`, 5–11/10 | `WELLNESS_TREND_NOT_ASSESSABLE`; sin modelo de tendencia validado | Serie de datos fechados, sin conclusión de evolución. |
| `/semana` | Analiza mi entrenamiento esta semana. | `analyze_day`, 5–11/10 | Comparaciones diarias no equivalen a balance semanal ni planificación | Vista de actividades de la semana y plan vigente; sin balance prescriptivo. |
| `/proximo` | Recomienda mi próximo entrenamiento mañana. | `clarify`, `UNSUPPORTED_PARAPHRASE` | Sin prescripción general validada de duración/intensidad | Próxima sesión guardada o ausencia de plan; se comunica que no es recomendación recalculada. No se adopta mañana como fecha implícita. |
| `/running`, `/correr`, `/carga_running` | Analiza mi running esta semana. | `analyze_day`, 5–11/10 | Sin hallazgos de evolución/ACWR validados ni filtro garantizado por esta frase | Vista de carrera y métricas existentes con unidades, sin interpretación de riesgo. |
| `/bici` | Analiza mi ciclismo esta semana. | `analyze_day`, 5–11/10 | Sin evaluación ciclista específica validada | Vista factual de ciclismo. |
| `/potencia`, `/wattwise` | Analiza mi potencia en bici hoy. | `analyze_day`, 11/10 | El catálogo inspeccionado no interpreta FTP/TSS/IF/VI | Vista Wattwise con fechas y métricas disponibles, sin recomendación. |
| `/malaga` | Valora mi preparación para la maratón de Málaga hoy. | `analyze_day`, 11/10 | Sin hallazgos específicos de preparación para objetivo | Vista del objetivo confirmado y plan vigente; sin pronóstico de preparación. |
| `/ajustar` | `/ajustar mañana` (entrada actual conservada) | `clarify`, `UNSUPPORTED_PARAPHRASE` en sondeo directo | Contrato de autorización existe; esto no acredita propuestas V3 útiles | Fuera del adaptador inicial. Mantener compatibilidad y evaluar normalización e intención antes de migrarlo. Nunca aplicar implícitamente. |

Solo `/hoy`, `/ultima` y `/feedback` son candidatos iniciales, todavía sujetos a evaluación de salida completa. Los demás alias pasan a vistas factuales únicamente cuando esas vistas estén probadas y la transición se active de forma explícita; con el interruptor apagado se conserva el comportamiento actual. Se documenta la pérdida deliberada de recomendaciones antiguas. No se amplía el catálogo deportivo de V3 de forma implícita para completar esta fase.

`/plan` y `/plan_semana` mantienen lectura directa, y la variante `nuevo` creación explícita. No se reutiliza íntegramente `COACH_QUESTIONS`: contiene significados de plan obsoletos. Los comandos de registro conservan sus validaciones y escrituras.

## Traducción y contexto

El adaptador normaliza mayúsculas y sufijos Telegram, conserva argumentos y no obtiene autorización de modificación del texto que él mismo genera. Una fecha explícita sustituye el ámbito predeterminado. Conflictos o ámbitos no soportados requieren aclaración, sin descartarlos silenciosamente.

Texto, `/coach`, voz transcrita y alias migrados usan el servicio común y la misma construcción de contexto. Las comparaciones de aceptación fijan reloj e instantánea. El respaldo factual no se incorpora como otra opinión al contexto del entrenador.

`build_ai_brief` depende de formateadores locales: se inventarían sus consumidores y se separan hechos de recomendaciones antes de cualquier eliminación. Se preservan cálculos, fuentes, perfil, pruebas aplicadas, plan e historial. Las rutas de compatibilidad retenidas se enumeran en el cierre.

## Ayuda, registros y estado

`/help` y `/start` muestran `/coach`, `/plan`, `/sync`, `/estado`, `/registro` y `/help`, con ejemplos. `/help comandos` distingue claramente alias de análisis, vistas de datos y operaciones de registro. La ayuda debe reflejar el modo activo, sin anunciar migraciones aún apagadas.

`/registro` ofrece opciones textuales de fuerza, molestias, perfil y pruebas; sus subcomandos muestran instrucciones y ejemplos. Abrir una ayuda nunca escribe datos ni encola una consulta. Los comandos existentes siguen siendo las operaciones explícitas de guardado.

`/estado` combina estado por proveedor y ámbito con señales de cola ya persistidas:

- Número de trabajos pendientes y en ejecución del chat autorizado.
- Hora de creación y antigüedad del pendiente más antiguo; si no hay pendientes, lo indica.
- Última finalización correcta y último fallo del chat, diferenciados. Un fallo no se presenta como trabajo respondido correctamente.
- Hora de recogida del trabajo en curso, cuando exista; indica demora observada sin afirmar que el Mac está dormido.

Se emplean `created_at`, `claimed_at`, `completed_at` y `status` tanto en almacenamiento de ficheros como PostgreSQL. No se expone texto de consultas ni actividad de otros chats. Si no hay historial se dice explícitamente. La fecha del último éxito es evidencia histórica, no prueba de disponibilidad actual.

La vista conserva frescura, último intento/éxito y errores seguros por fuente, distingue ausencia de actividad de ausencia de datos y usa Europe/Madrid. `/status`, `/syncinfo` y modos antiguos de `/sync` siguen compatibles. No se añade heartbeat ni servicio externo.

## Entregables y aceptación

1. Base de fase 3 guardada; matriz de capacidades y pruebas de intención/fechas con preguntas canónicas y humanas.
2. Vistas factuales, estado de cola, acuse y aviso de demora persistente; pruebas con worker ausente y reinicios.
3. Adaptador apagado por defecto, lista de candidatos, requisito V3 y reversión probada. Activación solo tras evaluación y coordinación API/worker.
4. Ayuda y registros coherentes con el modo activo; documentación de la transición.
5. Retirada condicionada de duplicados e informe de lo conservado, sin declarar cumplidos criterios pendientes.

### E14: equivalencia semántica, no solo traducción

Se conserva el criterio histórico del auditor. Conectar un alias y comparar con la misma frase generada es solo una prueba del adaptador. La aceptación exige por cada candidato:

- Aserciones independientes de intención, selector, fechas concretas, hechos, limitaciones, decisiones y ausencia de permisos de escritura.
- Paráfrasis humanas no generadas por el adaptador: «¿Cómo fue mi entreno de hoy?», «Dame tu opinión sobre la última salida» y «¿Qué tal el último día que entrené?». Son casos por verificar, no afirmaciones de soporte actual. Si fallan, el alias no se activa hasta resolver o declarar la limitación.
- Fechas explícitas, cambio de día en Madrid, negaciones, preguntas ambiguas y argumentos que contradicen el ámbito predeterminado.
- Misma pregunta humana por texto, `/coach` y voz con transcripción simulada; misma instantánea y reloj. Se comprueba la salida estructurada y su utilidad, no solo la creación del trabajo.
- Los alias retenidos como datos no se cuentan como equivalentes a análisis. Si el criterio histórico exige equivalencia para todos, E14 se informa parcial/incumplido hasta resolver o aprobar explícitamente el nuevo alcance; no se cambia el auditor para obtener un aprobado.

Se prueban ambas posiciones del interruptor, V3 apagado/incompatible, trabajos previos a reversión, ausencia de worker, aviso único durante operación normal y carreras con finalización. La integración de avisos verifica recuperación tras reinicio y reclamación concurrente. Se comprueba que las vistas no llaman al modelo ni producen recomendaciones.

Se ejecutan las suites afectadas, las regresiones de fase 3 y E15a/b; persistencia solo en PostgreSQL desechable. Voz simulada no certifica Whisper ni Telegram real. Activación y evaluación en producción requieren evidencia propia y permanecen coordinadas con la fase 5.
