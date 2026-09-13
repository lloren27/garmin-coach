# Validación del flujo común del coach

Estado: modelo local `garmin-coach:9b` validado con el flujo de respuesta rápida.

## Comprobaciones completadas

- 55 pruebas automatizadas: enrutamiento, contexto, operaciones de registro, respuestas de texto y voz, fallos de Ollama/Piper, fechas, puntuación y lectura de unidades.
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
