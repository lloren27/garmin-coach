# Perfil de datos para la valoración semanal — Task 3A

Fecha: 13/11/2026. Código examinado: `fc9e295` (Task 3).

Estado: Task 3A completada. Revisión de código, plantillas y todos los planes persistidos disponibles en PostgreSQL de producción al consultar el 13/11/2026.

## Fuente y alcance

Se ejecutó `_planned_week_sessions` para los siete días de una semana en cada rama: `descarga`, `controlada` y `normal` (construcción). Se usaron parámetros sintéticos de 17 km y 5:06/km. El análisis inicial invocó la rama por defecto con la etiqueta `construccion`; la lectura de `_weekly_plan_mode` confirma que su nombre operativo es `normal`. Ambas etiquetas recorren la misma rama, sin condiciones adicionales.

Son 24 posiciones de plantilla, no 24 sesiones guardadas ni una estimación de su frecuencia en producción. Se contó presencia de `duration_min` y `duration_max`; los 19 pares presentes son numéricos, positivos y ordenados. No se consultaron datos personales para este recuento.

## Cobertura de duración

| Modo | Sesiones | Obligatorias | Opcionales | Ambos límites | Solo uno | Ninguno |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| descarga | 7 | 6 | 1 | 5 (71,4 %) | 0 | 2 (28,6 %) |
| controlada | 8 | 7 | 1 | 7 (87,5 %) | 0 | 1 (12,5 %) |
| normal | 9 | 8 | 1 | 7 (77,8 %) | 0 | 2 (22,2 %) |
| Total | 24 | 21 | 3 | 19 (79,2 %) | 0 | 5 (20,8 %) |

| Deporte / tipo | Obligatorias | Opcionales | Ambos | Uno | Ninguno |
| --- | ---: | ---: | ---: | ---: | ---: |
| cycling / recovery | 0 | 2 | 2 | 0 | 0 |
| cycling / easy | 0 | 1 | 1 | 0 | 0 |
| recovery / rest_mobility | 3 | 0 | 3 | 0 | 0 |
| recovery / rest | 1 | 0 | 0 | 0 | 1 |
| running / easy | 5 | 0 | 5 | 0 | 0 |
| running / easy_progressions | 3 | 0 | 3 | 0 | 0 |
| running / aerobic | 2 | 0 | 2 | 0 | 0 |
| running / long_run | 3 | 0 | 0 | 0 | 3 |
| running / quality | 1 | 0 | 0 | 0 | 1 |
| strength / full_body_a | 2 | 0 | 2 | 0 | 0 |
| strength / full_body_b | 1 | 0 | 1 | 0 | 0 |

Los cinco huecos son tres tiradas largas con distancia escalar, una sesión de calidad con intervalos descritos en texto y un descanso sin objetivo temporal. Las sesiones de descanso/movilidad tienen duración, pero esa duración no convierte otra actividad en equivalente al descanso. Dos pares son exactos: fuerza A de controlada (35–35 min) y bici opcional de normal (30–30 min); no añadir tolerancias sin validarlas.

## Escrituras y certeza histórica

- `apps/bot/app/store.py`: `save_training_plan` asigna las marcas iniciales; `save_training_plan_postgres` inserta planes y sesiones. Al sustituir el plan, actualiza `training_plans.status` y `training_plans.updated_at`, no las sesiones anteriores.
- `save_training_plan_file` conserva las sesiones anteriores y añade las nuevas; cambia estado y fecha del plan sustituido.
- `apps/bot/app/proposal_repository.py` lee planes y sesiones e inserta propuestas en `pending_changes`. No aplica cambios a `planned_sessions`.
- La búsqueda en fuentes Python y SQL del repositorio no encontró una escritura de estado, vínculo o contenido sobre sesiones existentes. En PostgreSQL se comprobaron cero triggers de usuario sobre `planned_sessions`, cero sesiones con `created_at != updated_at` y cero vínculos `completed_activity_id`. Estas observaciones describen el estado actual; no constituyen un historial de cambios manuales.

Para Task 4, evaluar por separado el vínculo con la actividad y la certeza del objetivo histórico. Un `completed_activity_id` válido conserva su valor aunque `updated_at` sea posterior. El `updated_at` del plan por `superseded` no prueba un cambio de sesión. Sin historial ni prueba del tipo de escritura, una fecha posterior de sesión solo permite declarar incertidumbre, no afirmar qué contenido cambió. Repetir el inventario si aparecen nuevas escrituras antes de implementar la comparación.

## Decisiones para Task 4

Los tipos de carrera `easy`, `easy_progressions`, `aerobic`, ciclismo `easy`, `recovery` y fuerza `full_body_a`, `full_body_b` tienen rango temporal en estas plantillas. Son candidatos a comparar únicamente duración cuando el deporte y el tipo de actividad sean verificables, el objetivo histórico sea fiable y los límites y duración real sean válidos. La compatibilidad temporal no demuestra cumplimiento de progresivos, intensidad ni trabajo muscular.

`long_run`, `quality`, `rest` y `rest_mobility` requieren tratamiento específico. Mostrar distancia o duración disponible y el límite «sin criterio de compatibilidad validado» cuando corresponda. No convertir kilómetros o texto de intervalos a minutos, sumar cargas entre deportes ni tratar una sesión opcional no realizada como incumplimiento. Un solo límite, si aparece en planes guardados, tampoco permite aplicar la regla de rango completo.

## Perfil de planes persistidos

Consulta del 13/11/2026 a PostgreSQL de producción desde el servicio `garmin-coach` mediante Railway SSH. Conexión con `default_transaction_read_only=on`, comprobada con `SHOW transaction_read_only` (resultado `on`), y `statement_timeout=10000`. Solo SELECT; se devolvieron agregados sin IDs, propietarios ni textos privados. No se abrió un puerto público.

Se examinó la totalidad disponible: **4 planes (1 activo y 3 sustituidos), 34 sesiones**. Incluye planes históricos; no representa 34 actividades realizadas ni una muestra independiente de hábitos deportivos.

| Deporte / tipo | Obligatorias | Opcionales | Ambos límites | Solo uno | Ninguno |
| --- | ---: | ---: | ---: | ---: | ---: |
| cycling / easy | 0 | 2 | 2 | 0 | 0 |
| cycling / recovery | 0 | 2 | 2 | 0 | 0 |
| recovery / rest_mobility | 4 | 0 | 4 | 0 | 0 |
| running / aerobic | 4 | 0 | 4 | 0 | 0 |
| running / easy | 4 | 0 | 4 | 0 | 0 |
| running / easy_progressions | 6 | 0 | 6 | 0 | 0 |
| running / long_run | 4 | 0 | 0 | 0 | 4 |
| running / quality | 2 | 0 | 0 | 0 | 2 |
| strength / full_body_a | 4 | 0 | 4 | 0 | 0 |
| strength / full_body_b | 2 | 0 | 2 | 0 | 0 |
| Total | 30 | 4 | 28 | 0 | 6 |

**28/34 (82,4 %) tienen ambos límites; 6/34 (17,6 %) ninguno; 0/34 un único límite.** Los 28 rangos son numéricos, finitos, positivos y ordenados. La ausencia incluye claves inexistentes o valores nulos. Los seis huecos son cuatro tiradas con distancia y dos sesiones de calidad con descripción. No hay sesiones `rest` en esta muestra; ese hueco sigue cubierto por la plantilla y el caso sintético.

Las 30 sesiones obligatorias incluyen 24 con rango (80 %) y 6 sin él (20 %). Las 4 opcionales tienen ambos límites (100 %). Las cuatro sesiones de descanso/movilidad con rango siguen excluidas de la comparación deportiva por duración. Por tanto, hay **24/34 (70,6 %) candidatos estructurales** a esa comparación; aún deben verificarse tipo, deporte, métricas reales y objetivo histórico según Task 4.

La muestra confirma los huecos previstos y mantiene las decisiones anteriores. No aporta evidencia para validar equivalencias entre deportes, tolerancias de distancia, cumplimiento de intervalos o cambios históricos de contenido. Revalidar las escrituras si cambia el código antes de Task 4.

## Corpus y comprobaciones

`tests/fixtures/coach_weekly_assessment_cases.json` inicia el corpus con tres ejemplos sintéticos: tirada por distancia, intervalos solo en texto y descanso sin duración. Son requisitos de evaluación para Tasks 4–6; aún no constituyen pruebas ejecutadas del comparador.

Validación realizada: generación y recuento de las 24 posiciones, revisión de las escrituras, perfil READ ONLY de los 4 planes y 34 sesiones persistidos y validación sintáctica del JSON del corpus. No se cambiaron código de producción ni planes; no se repitieron suites funcionales para este cambio documental.
