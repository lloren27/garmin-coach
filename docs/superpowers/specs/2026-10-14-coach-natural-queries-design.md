# Diseño: consultas naturales con filtros de actividad

## Objetivo

Evitar aclaraciones genéricas para consultas deportivas concretas que el bot ya puede responder con hechos sincronizados. La resolución debe mantener el alcance de fecha, deporte y métrica que expresó la persona, y pedir una aclaración precisa cuando los datos no permitan seleccionarlos con seguridad.

## Alcance aprobado

Las cinco consultas reportadas son criterios de aceptación:

1. «¿Cuál es el entrenamiento para mañana, día 14 de octubre?» resuelve una consulta de plan para el 14 de octubre de 2026 cuando el reloj local indica 13 de octubre de 2026. La fecha relativa y la fecha escrita deben coincidir; si entran en conflicto, se pide aclaración.
2. «Analiza mi última sesión de bici» selecciona la actividad de ciclismo más reciente entre todas las actividades disponibles, ordenando por hora local de inicio. Si falta una hora fiable para distinguir candidatas, se pide elegir entre ellas; no se elige por fecha o por orden accidental del JSON.
3. «La actividad de ciclismo del día 10 de octubre» y «Analízame las actividades de ciclismo del día 10 de octubre» limitan la observación a actividades de ciclismo del 10 de octubre de 2026.
4. «¿Me puedes decir mis pulsaciones máximas en la actividad de carrera de hoy?» responde con `max_hr` por cada actividad de carrera de hoy que lo tenga. Si hay más de una, las presenta por separado; no calcula un máximo agregado. La respuesta informa el dato y su fuente; no infiere zona, intensidad ni valoración del esfuerzo.

## Diseño

Se amplía el contrato determinista de intención para representar el deporte opcional y el foco métrico opcional de cada componente, además de fecha e intención. Las expresiones españolas `bici`, `bicicleta` y `ciclismo` se normalizan a `cycling`; `carrera` y `correr` a `running`. El selector de actividad más reciente queda limitado por el deporte cuando la pregunta lo indica.

El contexto de evidencias conservará la hora de inicio fiable de cada actividad. La selección para consultas por fecha aplicará el deporte antes de construir hallazgos. Para «última actividad», primero filtrará por deporte y después ordenará por hora de inicio; si el orden no puede determinarse con fiabilidad, devolverá una aclaración que permita escoger candidatas. Consultas de una métrica devolverán solo el valor factual solicitado y sus metadatos de fuente/fecha.

Las consultas sobre el plan reconocerán preguntas naturales de «qué entrenamiento/sesión hay para [fecha]» como `CONSULT_PLAN`. La resolución seguirá siendo local y determinista; el generador no decidirá fechas, deporte ni métrica. La transcripción de audio reutiliza el mismo punto de entrada. Las pruebas de voz usarán transcripciones conocidas; diagnosticar una transcripción concreta de producción queda condicionado a que el texto guardado en el trabajo esté disponible.

## Seguridad y límites

- No se suman deportes ni escalas de carga diferentes.
- No se deducen valores ausentes ni se interpreta `max_hr` como zona o intensidad.
- El selector de «última» no usa el orden de entrada como sustituto de una hora fiable.
- Cuando no haya actividad o métrica con el ámbito solicitado, la respuesta lo dirá explícitamente y no sustituirá datos de otro deporte.
- El cambio no modifica rutas ni interruptores de alias, no cambia la configuración de Railway y no se despliega a producción.

## Verificación

- Añadir primero casos de regresión para las cinco consultas y comprobar que fallan en el resolutor actual.
- Añadir casos negativos para fecha relativa/expresa discordante, timestamps ausentes/ingenuos, empate entre actividades y métrica ausente.
- Verificar el contenido factual renderizado con fixtures sintéticos de varias actividades, deportes, timestamps y pulsos máximos; verificar referencias de evidencia.
- Ejecutar las pruebas focales del worker y luego su suite completa. Ejecutar la suite del bot para comprobar que el cambio del contrato compartido no altera el enrutamiento ni la ayuda.
- Mantener apagados `COACH_ALIAS_ROUTING_ENABLED` y cualquier aviso de demora durante toda esta tarea.

## Criterio de aceptación

Cada frase admitida se resuelve con su intención, fecha, deporte y métrica esperados; la respuesta solo contiene evidencias del ámbito pedido. Los casos incompletos o ambiguos reciben una aclaración concreta. La suite del worker y la del bot pasan. El cambio queda en una rama local, sin push, merge ni despliegue.
