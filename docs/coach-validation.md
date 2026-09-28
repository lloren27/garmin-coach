# Validación del flujo común del coach

Estado (28-09-2026): flujo interno v1 de decisiones validadas implementado en
`codex/coach-validated-decisions`, pendiente de integración en `main`.

## Validación del flujo v1

El worker solicita decisiones estructuradas, no un `answer` libre. Python captura
una instantánea inmutable, valida referencias y permisos, resuelve las sesiones
del plan y compone el texto español. El contrato público de trabajos y propuestas
se conserva. Una salida reparable permite una única corrección; una violación de
autoridad o identidad del contexto pasa directamente a la respuesta de reserva.

- Suite del worker: 138 pruebas, todas pasan.
- Suite del bot: 79 pruebas, sin fallos; 5 pruebas de PostgreSQL omitidas porque
  no se configuró una base aislada `P03_TEST_DATABASE_URL`.
- La prueba histórica de actividades Zepp usaba una fecha fija como «hoy»;
  ahora su actividad sintética utiliza la fecha de referencia del módulo.
- Revisión independiente: corregidas pérdida de check-ins textuales, sesiones
  sin minutos, opcionalidad, ritmo con prosa y prioridad de errores de autoridad.
- Ollama local `garmin-coach:9b`, cuatro consultas con datos exclusivamente
  sintéticos: mantener plan (27,9 s), descanso (18,2 s), análisis (18,0 s) y
  aclaración sin datos (11,4 s). Todas pasaron en una sola llamada. Son tiempos
  de una ejecución local, no un compromiso de latencia.

Las primeras ejecuciones reales detectaron referencias inventadas y decisiones
vacías. Se añadieron enumeraciones de referencias e IDs en el esquema de cada
instantánea y al menos una acción obligatoria. Las reglas de conclusiones se
explicitan en el prompt y se verifican nuevamente en Python.

Reproducción, desde `apps/sync-local`, con el intérprete del entorno local y
`PYTHONPATH=.`:

```sh
python -m unittest discover -s tests
python tests/manual_coach_generation_smoke.py
```

El segundo comando solo accede a Ollama en `127.0.0.1:11434`; no importa el worker,
no carga credenciales ni llama al backend, Telegram o servicios de sincronización.

## Límites de P0

- El catálogo de conclusiones es pequeño y puede producir respuestas más rígidas.
  No hay paráfrasis por IA ni nuevos umbrales de salud o entrenamiento.
- La evidencia acredita que un hecho existe, no demuestra la corrección de toda
  inferencia del modelo. La respuesta de reserva permanece disponible.
- Se mantiene el límite público de siete decisiones por respuesta. Una consulta
  que no quepa debe pedir concreción o terminar en reserva, nunca omitir sesiones
  manteniendo la apariencia de un plan completo.
- Los bloques de intervalos que solo existen como descripción libre en el plan
  no se reconstruyen: el texto conserva los objetivos tipados y exige consultar
  los bloques y condiciones del plan. Las sesiones opcionales siguen indicadas
  como opcionales, también en la decisión auditable.
- PostgreSQL real, entrega real de Telegram y nueva síntesis real de voz no se
  ejecutaron en esta verificación. Sus rutas existentes están cubiertas por las
  suites unitarias correspondientes.
- No se ha integrado, desplegado ni reiniciado el servicio activo.

Los eventos `coach_validation_failure` identifican trabajo, intento, versión,
instantánea, fase, código y ruta; no contienen la pregunta, la salida rechazada
ni hechos personales. `coach_validation_repaired` confirma la reparación.
`coach_fallback` conserva la distinción entre respuesta del modelo y reserva.

## Histórico anterior al flujo v1

Las cifras y observaciones siguientes corresponden al flujo anterior de texto
libre; no describen la configuración o rendimiento del flujo v1.

## Comprobaciones completadas

- 56 pruebas automatizadas: enrutamiento, contexto, operaciones de registro, respuestas de texto y voz, indicador de procesamiento, fallos de Ollama/Piper, fechas, puntuación y lectura de unidades.
- Prueba real de Ollama con datos ficticios y `garmin-coach:9b`: el flujo anterior de dos pasadas tardó 128,9 segundos. La generación única optimizada tardó 38,7 segundos con el mismo caso, una reducción aproximada del 70 %.
- Piper generó correctamente un archivo de audio de 14 segundos. Esto verifica la síntesis, no una evaluación perceptiva de la calidad de la voz.
- Comprobación de solo lectura del contexto del backend: 25 actividades y 28 sincronizaciones que abarcan dos días, además de perfil, recuperación y Wattwise. Los resúmenes semanales aportan la evolución más larga. El contexto compacto medido ocupó unos 35.500 caracteres.
- No se han enviado mensajes de prueba a Telegram ni desplegado el backend.

## Calidad observada

Qwen 3.5 de 2B produjo respuestas completas y bien puntuadas, pero cometió errores de interpretación incluso con dos etapas. En la prueba, invirtió la relación entre carga y drenaje de Body Battery (12 frente a 62) y llamó «relación de horas» a una relación de carga de 1,52.

El modelo local de 9B interpretó correctamente esas cifras en la prueba repetida: 62 de drenaje frente a 12 de recarga, dos actividades que sumaban 2 horas y 48 minutos y la advertencia de que los datos tenían cuatro días. Dio una recomendación condicional de descanso o 30 a 40 minutos muy suaves. La respuesta ocupó unas 120 palabras. La antigüedad se sigue calculando en Python y se indica sin depender del modelo.

Las pruebas automatizadas validan el funcionamiento del código y este caso conocido comprueba una respuesta real, pero ninguna prueba aislada garantiza la exactitud de todas las recomendaciones futuras.

## Configuración validada

El flujo usa una sola generación con todo el contexto compacto, temperatura 0,2 y razonamiento nativo desactivado. Las preguntas normales disponen de 900 tokens y los planes semanales de 1.400. Esto evita procesar dos veces las mismas lecturas y permite que los planes sigan cubriendo los siete días.
