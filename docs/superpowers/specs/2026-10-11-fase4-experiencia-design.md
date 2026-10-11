# Fase 4: experiencia simple y entrenador único

Fecha: 11 de octubre de 2026. Revisión 3, tras segunda revisión del usuario.
Estado: diseño revisado para revisión; sin implementación ni activación en producción.

## Base y objetivo

La fase 4 simplifica la experiencia sin prometer capacidades que el entrenador todavía no tiene. El cierre de fase 3 está guardado en `5e4880f`, con código, pruebas y evidencias. El primer borrador de fase 4 ya estaba en el historial; no se reescribe. Los cambios posteriores parten de esta base limpia y separada.

Se han repetido 288 pruebas del worker y 30 del arnés con el entorno virtual del proyecto, todas correctas. No se ha repetido en esta revisión la suite PostgreSQL del bot ni se certifica producción. El resultado esperado de fase 4 es **E14 parcial**: tres alias de análisis migrados y el resto de alias deportivos como vistas de datos; `/ajustar` conserva su flujo específico. El criterio histórico global permanece incumplido y no se modifica para presentar un aprobado completo. La evidencia distinguirá implementación comprobada de activación en producción.

## Decisión 1: espera con respaldo de datos

Se elige conservar una vista determinista de datos como respaldo. Las recomendaciones de los alias migrados dependen del worker del Mac; las vistas de datos, el plan guardado, el estado y los registros siguen disponibles desde Railway. Esta dependencia es un cambio explícito frente a las respuestas locales instantáneas actuales.

- Acuse inmediato tras persistir el trabajo: «Consulta en cola. El entrenador responderá cuando el procesamiento local esté disponible. Puedes consultar /estado». Si guardar falla, no se anuncia que está en cola.
- A los **150 segundos** sin respuesta final, un único aviso por trabajo durante operación normal: «Tu consulta sigue pendiente. Datos de la sincronización del {fecha y hora}, hace {antigüedad}; no son una valoración del entrenador», acompañado de una vista factual pertinente o de la ausencia explícita de datos. Si no consta la fecha de sincronización, se indica «antigüedad no conocida». Se distingue esa fecha de las fechas de las actividades y mediciones, que también se muestran. El umbral es configurable y no promete un plazo de respuesta.
- El trabajo sigue pendiente: mostrar datos no lo completa, cancela ni crea otro trabajo. Al terminar se entrega la respuesta final por el flujo existente. Un fallo definitivo se comunica como fallo.
- El aviso se despacha desde el bot/API en Railway, nunca desde el worker cuya ausencia se intenta explicar. Se incorpora, exclusivamente con PostgreSQL, un barrido periódico de trabajos vencidos al ciclo de vida de la API, con marca persistente y reclamación atómica para evitar avisos concurrentes. No basta un temporizador en memoria por consulta. Tras reiniciar, se recuperan avisos vencidos aún pendientes.
- Se comprueba otra vez el estado antes de enviar el aviso para minimizar la carrera con la finalización. Telegram no ofrece entrega exactamente una vez: se documentará la ventana residual entre envío y persistencia, sin prometer una garantía absoluta.

### Cálculo del umbral y límites de la evidencia

La auditoría de fase 0 (`docs/restructuring/fase0_resultados/informe.md`) registra ejecución del worker cada 60 s. Es el presupuesto de espera por sondeo, no una distribución medida de recogida ni un límite bajo cola acumulada. En `docs/restructuring/fase3_evaluacion/ejecuciones/fase3-e4-20261009-run2/results.json`, los 15 valores `model.latency_seconds` dan p95 = **44,1279 s**, calculado por rango más próximo: valor ordenado en posición `ceil(0,95 × 15) = 15`. El temporizador del arnés incluye el procesamiento del experimento, no toda la entrega en Telegram.

Valor inicial: `30 × ceil((60 + 44,1279 + 30) / 30) = 150 s`. Los 30 s adicionales son margen de diseño para transporte y variación, no una medición. La muestra es pequeña y corresponde al experimento de Ollama, no al motor determinista V3 ni a toda la ruta antigua. Antes de activar se medirá recogida, ejecución y entrega del motor real; si no cubre su p95 observado más margen, se recalibra. Una demora no se describe como avería ni como prueba de que el Mac duerme.

### Migración aditiva de avisos

Los avisos automáticos requieren PostgreSQL. El backend de ficheros mantiene lectura de estado, acuse y consulta explícita de datos, pero no ejecuta el barrido ni activa la migración de alias que exige avisos. Un guardado JSON no proporciona reclamación atómica entre procesos; añadir bloqueo de ficheros queda fuera de este alcance.

Se añaden al esquema de trabajos campos opcionales y anulables `delay_notified_at`, `delay_notice_claimed_at` y `delay_notice_claim_token`. La reclamación PostgreSQL es condicional y atómica; el token identifica al propietario y una concesión caducable permite recuperar trabajos tras un reinicio. La finalización del aviso solo la puede registrar quien conserva la concesión. Se preservan los campos al actualizar el resto del trabajo. La ubicación física de estos campos (columnas o documento JSONB) se fija en el plan técnico; en ambos casos se trata como migración de contrato y se prueba su compatibilidad, sin asumir que JSONB exime de migración.

Antes de modificar el esquema: copia no destructiva, restauración en PostgreSQL aislado y verificación de conteos, identificadores, relaciones, revisiones y trabajos pendientes. Orden: migración aditiva, lector compatible con campos ausentes/nulos, después productor de los nuevos valores. No se reinician estados ni se descartan trabajos pendientes. La reversión desactiva el productor/barrido y conserva datos compatibles; se prueba que los lectores y escritores compatibles no borran marcas nuevas. No se usan trabajos reales ni mensajes al usuario para probarlo.

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

Solo `/hoy`, `/ultima` y `/feedback` son candidatos iniciales, todavía sujetos a evaluación de salida completa. Los demás alias pasan a vistas factuales únicamente cuando esas vistas estén probadas y la transición se active de forma explícita; con el interruptor apagado se conserva el comportamiento actual. Se documenta la **retirada temporal** de las valoraciones antiguas, especialmente fatiga, carga, tendencia, balance semanal y potencia. Es una reducción funcional consciente: se conservan los datos útiles para preparar la maratón, pero no se sustituye una valoración por una afirmación sin soporte. Recuperar estas capacidades exige ampliar y evaluar el catálogo, no solo reconocer nuevas frases. No se amplía el catálogo deportivo de V3 de forma implícita para completar esta fase.

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

1. **Simplificación visible de solo lectura:** ayuda reducida, `/registro` textual y `/estado` con señales de cola, sin depender del interruptor del adaptador ni de V3. Se prueban con ambos backends; la ayuda describe el comportamiento vigente. Incluye la base de fase 3 y la matriz de capacidades. Puede entregarse antes de activar cualquier migración deportiva.
2. **Persistencia y experiencia de espera:** prerrequisito antes de implementar este entregable: disponer de PostgreSQL desechable y repetir la suite completa del bot, incluidas las pruebas de persistencia sin omisiones. Después, ensayo de copia/restauración, migración aditiva, lectores compatibles, productores, vistas factuales fechadas y avisos con reclamación atómica. Se vuelve a ejecutar la suite tras el cambio. No se difiere la verificación PostgreSQL al cierre.
3. **Adaptador apagado por defecto:** tres candidatos, requisito V3, evaluación semántica y reversión comprobada. Activación solo con capacidad y latencia verificadas, avisos operativos y coordinación API/worker. Transición explícita del resto de alias deportivos a vistas de datos.
4. **Cierre con E14 parcial esperado:** evidencia separada de los tres alias migrados, vistas sin opinión y capacidades retiradas temporalmente. Si la activación de producción sigue pendiente, se declara por separado; ni siquiera el estado parcial se da por probado sin sus pruebas. Retirada de duplicados condicionada a conservar una reversión efectiva.

### Criterios obligatorios del aviso

- Cero avisos antes del umbral y cero avisos para trabajos finalizados a tiempo. Se reproduce el presupuesto de recogida de 60 s más p95 medido y el perfil de latencia del motor que se activará.
- **Exactamente un aviso por trabajo demorado en operación normal**, aunque haya varios barridos o procesos concurrentes. Esta prueba es criterio de aceptación del entregable 2 y condición de activación del 3.
- Recuperación de concesiones caducadas y de avisos pendientes tras reinicio; prueba de carrera con finalización. Se mantiene documentado el límite de entrega exactamente una vez de Telegram ante caída entre envío y confirmación persistida.
- El respaldo incluye hasta qué sincronización llega, su antigüedad y fechas/fuentes de las observaciones. Datos ausentes o fecha desconocida se expresan sin inventarlos.
- Copia restaurada, migración y lectores compatibles conservan trabajos pendientes e históricos. Los tests de PostgreSQL no se omiten por falta de infraestructura.

### Continuación del catálogo

La hoja de ruta incorpora una ampliación posterior y explícita para recuperar valoraciones de carga y tendencia, fatiga, balance semanal y potencia. Primero se definen ventanas comparables, cobertura mínima y referencias personales; después hechos y hallazgos por deporte, límites y evaluación de utilidad con preguntas humanas de preparación de maratón. No se suman escalas incompatibles. Cada capacidad se reincorpora solo con evidencia, y entonces se amplía E14. Esta ampliación requiere su propio diseño y no se considera implementada por documentarla.

### E14: equivalencia semántica, no solo traducción

Se conserva el criterio histórico del auditor. Conectar un alias y comparar con la misma frase generada es solo una prueba del adaptador. La aceptación exige por cada candidato:

- Aserciones independientes de intención, selector, fechas concretas, hechos, limitaciones, decisiones y ausencia de permisos de escritura.
- Paráfrasis humanas no generadas por el adaptador: «¿Cómo fue mi entreno de hoy?», «Dame tu opinión sobre la última salida» y «¿Qué tal el último día que entrené?». Son casos por verificar, no afirmaciones de soporte actual. Si fallan, el alias no se activa hasta resolver o declarar la limitación.
- Fechas explícitas, cambio de día en Madrid, negaciones, preguntas ambiguas y argumentos que contradicen el ámbito predeterminado.
- Misma pregunta humana por texto, `/coach` y voz con transcripción simulada; misma instantánea y reloj. Se comprueba la salida estructurada y su utilidad, no solo la creación del trabajo.
- Los alias retenidos como datos no se cuentan como equivalentes a análisis. El resultado de fase 4 se informa como E14 parcial, con equivalencia global histórica incumplida; no se cambia el auditor para obtener un aprobado.

Se prueban ambas posiciones del interruptor, V3 apagado/incompatible, trabajos previos a reversión, ausencia de worker, aviso único durante operación normal y carreras con finalización. La integración de avisos verifica recuperación tras reinicio y reclamación concurrente. Se comprueba que las vistas no llaman al modelo ni producen recomendaciones.

Se ejecutan las suites afectadas, las regresiones de fase 3 y E15a/b; persistencia solo en PostgreSQL desechable. Voz simulada no certifica Whisper ni Telegram real. Activación y evaluación en producción requieren evidencia propia y permanecen coordinadas con la fase 5.
