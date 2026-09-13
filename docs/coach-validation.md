# Validación del flujo común del coach

Estado: cambios locales preparados; calidad del consejo generativo pendiente de validar antes del despliegue.

## Comprobaciones completadas

- 54 pruebas automatizadas: enrutamiento, contexto, operaciones de registro, respuestas de texto y voz, fallos de Ollama/Piper, fechas, puntuación y lectura de unidades.
- Prueba real de Ollama con datos ficticios: el flujo de informe de evidencias y redacción terminó en 27 segundos en un Mac M2 de 16 GB. El tiempo depende del contexto y del modelo.
- Piper generó correctamente un archivo de audio de 14 segundos. Esto verifica la síntesis, no una evaluación perceptiva de la calidad de la voz.
- Comprobación de solo lectura del contexto del backend: 25 actividades y 28 sincronizaciones que abarcan dos días, además de perfil, recuperación y Wattwise. Los resúmenes semanales aportan la evolución más larga. El contexto compacto medido ocupó unos 35.500 caracteres.
- No se han enviado mensajes de prueba a Telegram ni desplegado el backend.

## Limitación detectada

Qwen 3.5 de 2B produjo respuestas completas y bien puntuadas, pero cometió errores de interpretación incluso con dos etapas. En la prueba, invirtió la relación entre carga y drenaje de Body Battery (12 frente a 62) y llamó «relación de horas» a una relación de carga de 1,52. Las pruebas automatizadas validan el funcionamiento del código; no demuestran exactitud de las recomendaciones del modelo.

Su modo de razonamiento nativo también agotó el presupuesto de generación sin dar una respuesta completa. Por ello está desactivado por defecto y se usa un informe previo seguido de redacción. La antigüedad de los datos se calcula en Python y se indica en la respuesta sin depender del modelo.

## Validación pendiente

Se ha intentado descargar `qwen3.5:9b` para repetir la evaluación. El servidor de archivos de Ollama devuelve tiempos de espera de conexión. El modelo configurado no se ha cambiado.

Cuando la descarga esté disponible:

```bash
ollama pull qwen3.5:9b
```

Probar el flujo con `OLLAMA_MODEL=qwen3.5:9b`, comparando las respuestas con datos conocidos y verificando cifras, fechas, relaciones entre métricas y recomendaciones condicionadas a la recuperación. Confirmar tiempo y consumo de memoria antes de guardar el modelo en `.env` y desplegar Railway.
