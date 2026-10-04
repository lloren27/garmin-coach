# Revisión manual de Ollama

Fecha de revisión: 2026-10-04  
Modelo: `garmin-coach:9b`  
Muestra: 18 ejecuciones (6 casos, 3 repeticiones por caso)

## Rúbrica

Cada salida válida se puntúa en cuatro dimensiones de 0 a 2:

- **Fidelidad (F):** responde a la pregunta y usa el ámbito temporal/deportivo correcto.
- **Procedencia (P):** conserva las fuentes y no atribuye datos a otro proveedor.
- **Utilidad (U):** convierte los datos en una valoración o siguiente paso concreto.
- **Prudencia (R):** evita diagnósticos, umbrales inventados y cambios no autorizados.

Las salidas rechazadas por el validador se marcan como **N/A**: el rechazo es un
resultado positivo del contrato estructurado, pero no permite valorar la respuesta
final del coach.

## Resultados por ejecución

| Ejecución | Estado | F | P | U | R | Valoración manual |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| E01-1 | válida | 1 | 2 | 0 | 2 | Enumera plan y métricas, pero no compara la sesión real con el plan ni explica el resultado. |
| E01-2 | válida | 1 | 2 | 0 | 2 | Idéntica carencia que E01-1. |
| E01-3 | válida | 1 | 2 | 1 | 1 | Propone descanso sin justificarlo con la sesión de 20 km ni con una condición del plan. |
| E07-1 | válida | 1 | 2 | 0 | 2 | Dice que faltan datos, pero no distingue ausencia de actividad de ausencia de datos ni indica qué falta. |
| E07-2 | válida | 1 | 2 | 0 | 2 | Misma respuesta genérica que E07-1. |
| E07-3 | válida | 1 | 2 | 0 | 2 | Misma respuesta genérica; el orden de las fuentes cambia, no el contenido. |
| E08-1 | válida | 1 | 2 | 1 | 2 | Cálculo de ritmo y trazabilidad correctos; no responde cómo encaja con el plan. |
| E08-2 | válida | 1 | 2 | 1 | 2 | Idéntica limitación que E08-1. |
| E08-3 | válida | 1 | 2 | 1 | 2 | Idéntica limitación que E08-1. |
| E09-1 | válida | 1 | 2 | 0 | 2 | Lista carrera, bici y fuerza, pero no integra la carga ni sus implicaciones para el día siguiente. |
| E09-2 | rechazada | N/A | N/A | N/A | N/A | Falla dos veces la validación de fecha de la recomendación (`PLAN_DATE_MISMATCH`). |
| E09-3 | válida | 1 | 2 | 0 | 2 | Misma falta de valoración conjunta que E09-1. |
| E10-1 | rechazada | N/A | N/A | N/A | N/A | Falla dos veces `INVALID_PACE_FORMAT`; la reparación repite un ritmo no permitido. |
| E10-2 | rechazada | N/A | N/A | N/A | N/A | Mismo rechazo estructural que E10-1. |
| E10-3 | rechazada | N/A | N/A | N/A | N/A | Mismo rechazo estructural que E10-1. |
| E13-1 | válida | 1 | 2 | 0 | 2 | No reconoce que no hay histórico personal suficiente para comparar evolución. |
| E13-2 | válida | 1 | 2 | 0 | 2 | Idéntica carencia que E13-1. |
| E13-3 | válida | 1 | 2 | 0 | 2 | Idéntica carencia que E13-1. |

## Resultado

De las 18 ejecuciones, 14 llegaron a una salida válida y 4 fueron rechazadas por
el contrato estructurado. Ninguna de las seis familias de caso cumple por completo
su condición funcional principal: E01, E08, E09 y E13 describen datos sin producir
la valoración solicitada; E07 responde de forma demasiado genérica; y E10 no llega
a una decisión válida.

La parte positiva es que las 14 salidas válidas conservan los números comprobados,
las fechas observadas y las atribuciones explícitas de Garmin, Zepp y plan. Además,
los cuatro rechazos impiden que una decisión inválida se entregue como si fuera
válida. Esto demuestra control estructural y de procedencia, pero no demuestra que
el coach esté ofreciendo todavía una opinión útil para entrenar.

La revisión es una evaluación de comportamiento del sistema, no una recomendación
médica ni una validación fisiológica de los entrenamientos.
