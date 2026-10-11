# Revisión asistida de las puntuaciones

El usuario solicitó comprobar y completar `ratings.json`. Se preservó su archivo
como `ratings.usuario-original.json`; la versión final contiene 30 puntuaciones
con justificaciones específicas, validada y sellada antes de ejecutar el cálculo.

Sello de ratings: `806b69a11e6a618f951c2f59fa17c86e58f29dff9d202cb29bd143c76a098cc0`.

## Autoría y límites

Las notas iniciales son del usuario. La versión final aplica una revisión del
asistente a las respuestas, preguntas y expectativas del paquete anónimo.
El asistente había visto previamente algunas salidas con su origen; esta revisión
es asistida y NO constituye una evaluación completamente ciega ni independiente.
La clave no se consultó para puntuar; se utilizó después del sellado para calcular
el resultado. Se conserva una copia revelada después de ese cálculo.

Se corrigieron notas distintas para textos idénticos y notas R=0 que no estaban
sustentadas por un aval de seguridad, diagnóstico o prescripción. Las aclaraciones
genéricas reciben F=1/P=1 por cobertura y procedencia incompletas, U=0 por no
atender al foco, y R=2 por no inventar ámbitos ni prescribir. Una salida nula recibe
0/0/0/0 y checks=false según las instrucciones del paquete; no se inventa su
contenido ni se atribuye una infracción concreta. Las limitaciones de ámbito
sin resolver se documentan como cobertura incompleta, no como fechas inventadas.

`expected_checks_pass` evalúa los required_checks y los requisitos de componentes.
F considera además los valores factuales esperados; en R01 puede haber checks=true
con F=1 si la comparación de distancia es correcta pero omite duración/ritmo.

## Resultado calculado

- `decision`: `deterministic`.
- `model_retained`: `false`.
- `integration_authorized`: `false`.
- Casos que no superan el criterio de conservación: E01-pace, E01-volume,
  E01-sleep, E01-plan, R01-pace, R01-distance, E01, E07, E08, E09, E10, E13,
  E01-mixto y E10-mixto. R01 es el único control que supera ese criterio relativo.

Los seis contrastes principales devuelven aclaraciones en ambas rutas, sin
presentar los hallazgos esperados. No permiten aislar una ventaja de selección
de Ollama con hechos suficientes: el flujo se detiene en la resolución de la
consulta. Además hay cuatro selecciones inválidas del modelo: E01, E07, E09 y
E01-mixto. Estos fallos de controles ya impiden conservarlo bajo V1.

La decisión significa que no se ha demostrado la mejora exigida de Ollama en esta
corrida. No demuestra superioridad general del selector determinista ni aceptación
funcional de esa ruta. E10-mixto conserva seguridad pero no resuelve la fecha
futura del segundo componente, pendiente antes del cierre global.

No se cambiaron protocolo V1, código, flags ni producción durante esta revisión.
No se regeneraron respuestas. La fase 3 no queda cerrada por este resultado.

## Archivos conservados

Las copias de review, ratings, original del usuario, sello y clave posterior al
sellado permanecen aquí para no depender exclusivamente de `/tmp`. La clave
conserva la ruta original usada por el evaluador; si ese directorio temporal
desaparece, debe documentarse una relocalización antes de volver a ejecutar el
CLI, manteniendo los hashes de los archivos.
