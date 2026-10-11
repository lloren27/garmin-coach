# Verificación del entregable 6

Actualizado: 2026-10-10. Verificación local completada; la aceptación global de equivalencia de alias E14 continúa pendiente de la fase 4.

## Correcciones verificadas

Las seis preguntas comparativas de V2 incluyen una fecha explícita y llegan al análisis focalizado. V1 permanece sellada: sus preguntas sin fecha siguen pidiendo aclaración. E10-mixto resuelve «mañana» con el reloj del trabajo y mantiene la reserva de seguridad.

La respuesta conserva detalles cuando falta el plan, separa deportes, solicita datos ante cobertura incompleta y muestra síntomas registrados. Las sesiones canceladas, completadas o con actividad vinculada no se presentan como previstas. Esta última regresión se reprodujo con tres variantes antes de corregirla; después pasan las tres y la suite completa.

## Evidencia del 10 de octubre

| Verificación | Resultado |
| --- | --- |
| Worker: unittest discover desde apps/sync-local | 288 pruebas, todas pasan |
| Arnés de Fase 3: test_*.py | 30 pruebas, todas pasan |
| Bot con PostgreSQL desechable | 92 pruebas, todas pasan; ninguna omitida |
| 20 casos de respuesta con las seis preguntas V2 | Hallazgos requeridos presentes, prohibidos ausentes, respuesta no vacía y decisiones de solo lectura |
| Auditoría E02/E03/E04/E06/E11/E15a/E15b/E17 | Cumplen |
| Ampliadas E05/E16/contexto/texto y voz con fallback | Cumplen |

Las comprobaciones automáticas de los 20 casos no sustituyen una nueva puntuación humana de cada criterio semántico. La revisión anterior de Ollama es asistida y no debe presentarse como independiente.

Resultados detallados en:

- ../fase0_resultados/ejecuciones/2026-10-10-fase3-final/
- ../fase0_resultados/ejecuciones/2026-10-10-fase3-cierre/

La suite del bot usó PostgreSQL 16 desechable en el puerto 55439 y dependencias temporales. Se detuvo y eliminó el contenedor al terminar. No se accedió a persistencia de producción.

## Casos parciales

- **E05/E16:** el auditor histórico solo cubre parte y marca no evaluable; las ampliadas verifican reconsulta tardía de sueño y cambio horario. Se conservan ambos niveles de evidencia.
- **E12:** el auditor histórico comprueba rechazo estructural, no detección semántica de contradicciones. Integrar reparación del selector Ollama es condicional a retenerlo, condición que no se cumple. La reserva del worker ante fallo del modelo sí se comprobó con texto y voz transcrita.
- **E14:** texto y /coach entran en cola; voz usa el mismo worker tras transcripción simulada. /feedback sigue local. Su compatibilidad pasa, pero **el criterio histórico de equivalencia de todos los alias sigue incumplido**. Se restauró el criterio original del auditor; el resultado del 9 de octubre con criterio modificado queda superado por el del 10 de octubre. La unificación pertenece a fase 4.
- **E15a/b:** autorización y persistencia verificadas en ficheros y PostgreSQL; consultar no autoriza cambios y una propuesta explícita no modifica por sí sola el plan.

Voz usa transcripción y transporte simulados: no certifica precisión de Whisper, síntesis ni entrega real de Telegram. Esa comprobación operativa permanece para despliegue.

## Decisión y revisión

La corrida fase3-e4-20261009-run2 no justifica incorporar Ollama al nuevo análisis. Se mantiene la ruta determinista como candidata sin activación en producción. No se ha repetido Ollama con V2 ni se afirma superioridad general del selector.

La revisión final por otro agente detectó el estado de sesión incorrecto, ya corregido. Queda un detalle menor de trazabilidad: el hallazgo de distancia con correspondencia improbable puede mostrar duración sin incluir su referencia individual en fact_refs; conserva la referencia a la actividad.

Puede continuarse con fase 4 conservando E14 como trabajo explícito. Este informe no declara el plan global ni la integración de producción al 100 %.
