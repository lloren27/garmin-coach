# Fase 0: plan de implementación v2 (auditoría y referencia inicial)

Fecha: 3 de octubre de 2026. Estado: borrador para revisión. Sustituye a la v1.

**Cambios respecto a la v1:** aislamiento explícito de las pruebas, casos definidos por capa, regla de cifras con trazabilidad, traza desde el proveedor, tres estados de cobertura, referencia reproducible ampliada, valores por defecto retirados, criterio de cierre más exigente y cuatro escenarios nuevos. Esta revisión concreta además la inspección de producción en lectura, la autorización de propuestas, los casos de interfaz, las repeticiones y los resultados no evaluables.

## 1. Objetivo

Obtener un diagnóstico verificable de cómo viaja un dato desde el proveedor hasta la respuesta del entrenador y dejar una referencia reproducible para medir las fases siguientes.

**Foco del proyecto (propuesta):** el sistema recoge mis datos cada día y me da una única opinión fundamentada sobre lo que hice y lo que toca después.

**Salida:** informe de auditoría (código y operación por separado), conjunto de evaluación con línea base, y lista de limitaciones del propio diagnóstico.

**Principio:** esta fase mide fallos, no los arregla. Termina aunque los casos fallen.

## 2. Reglas y aislamiento (imprescindible)

- No se despliega, no se cambia el esquema y no se envían mensajes de prueba por Telegram.
- La configuración existente (horarios, frecuencia, fuentes) no se toca durante la auditoría.
- **En producción solo se permiten inspecciones y exportaciones de lectura** para verificar versiones, configuración, registros y cobertura. Las pruebas y reproducciones se ejecutan exclusivamente en el entorno aislado. No se ejecutan el worker ni la sincronización normales: pueden completar trabajos, enviar respuestas o publicar datos.
- Entorno de prueba: reproducción local con datos exportados y anonimizados, almacenamiento temporal, y dobles de prueba para Telegram, proveedores y cualquier escritura o envío externo.
- Las llamadas reales a Ollama solo existen dentro del evaluador.
- Sin credenciales ni datos personales innecesarios en los casos.
- Cada hallazgo lleva etiqueta: **verificado** (reproducido), **probable** (visto en código) o **sin comprobar**.

## 3. Pasos

Etiquetas: **\[I\]** obligatorio para cerrar la fase; **\[T\]** con tope de tiempo, fijado antes de empezar. Si el tope se agota, lo no observado se documenta como limitación, sin atribuir un fallo al producto. El aislamiento de 0.3 debe verificarse antes de ejecutar cualquier prueba o reproducción.

### 0.1. Congelar la referencia \[I\]

- Commit y rama; versión efectiva en Railway y en el Mac; diferencias respecto al repositorio.
- Configuración efectiva sin secretos, identificador exacto del modelo (no solo la etiqueta), parámetros de generación, versión del prompt y del contrato.
- Fecha y zona horaria fijadas para ejecutar los casos (E01 debe seguir representando el 3 de octubre aunque se ejecute semanas después) y huella de los datos de cada caso.

### 0.2. Inventario \[I\]

- Comandos de Telegram: destino de cada uno y si pasa por `/coach` o se resuelve directo en `apps/bot/app/main.py`.
- Generadores de opinión y de plan (`coach_generation_pipeline.py`, `coach_generation_context.py`, `coach_generation_renderer.py`, `coach.py`, `sync.py`, `ai_worker.py` y los que aparezcan al buscar `build_week_plan` y `save_training_plan`).
- Contratos duplicados entre bot y worker; código y README que se contradicen.
- Tabla: elemento / archivo / quién lo llama / duplica a / ¿escribe estado? Marcar lo que escribe al consultar.

### 0.3. Aislamiento y entorno de prueba \[I\]

Montar el entorno descrito en la sección 2 y comprobar que ninguna prueba puede enviar mensajes ni escribir estado de la aplicación fuera del almacenamiento temporal. El evaluador podrá guardar únicamente los resultados saneados en la carpeta de entregables definida en 0.7.

### 0.4. Traza completa de E01 \[T\]

Cuando haya evidencia disponible, seguir el recorrido entero:

respuesta del proveedor → normalización → deduplicación → payload enviado → persistencia → contexto → modelo → respuesta.

Si faltan registros históricos de un tramo, ese tramo queda como **no observable** y no se le atribuye causa. Resultado: la primera pérdida de información localizada, o la lista de tramos no observables.

### 0.5. Cobertura de la recogida \[T\]

- Horarios efectivos de ejecución en el Mac y comportamiento al dormir y despertar.
- Por proveedor, tres estados: **cobertura confirmada**, **ausencia confirmada** y **cobertura desconocida**. La falta de registros no acredita fallo del proveedor ni día sin actividad.
- Distinguir fecha del dato y fecha de recogida: una sincronización reciente puede traer mediciones antiguas.

### 0.6. Muestra de historial \[T\]

- Ventana pequeña anonimizada con duplicados Garmin/Strava, sesiones CMF solo en Strava, sueño tardío y días cercanos a medianoche.
- Regla de coincidencia candidata (inicio, duración, distancia, deporte) y definición de «ambiguo», probada sobre datos reales sin implementarla.

### 0.7. Conjunto de evaluación y línea base \[I\]

Sección 4. Reproducir la versión actual del sistema en el entorno aislado y registrar un resultado para todos los casos y variantes: texto cuando corresponda, estado observado, puntuación aplicable, reparaciones, respuestas de reserva y latencia.

- Ejecutar una vez los casos deterministas, incluidos los que utilizan un doble del modelo.
- Ejecutar tres veces cada caso o variante que llame realmente a Ollama, conservando los resultados individuales; no ocultar fallos mediante una media.
- Registrar como `no evaluable` lo que no pueda comprobarse, con el motivo y la evidencia o capacidad necesaria para evaluarlo.
- Guardar los entregables en `docs/restructuring/fase0_resultados/`: `README.md` con instrucciones y comandos de reproducción, `referencia.json` con versiones y configuración saneada, `casos/` con entradas anonimizadas o sintéticas, `ejecuciones/` con resultados por caso y repetición, e `informe.md` con inventario, traza, cobertura, hallazgos y limitaciones. No versionar exportaciones sin sanear ni credenciales.

### 0.8. Informe de cierre

Hallazgos priorizados con evidencia y etiqueta, limitaciones de la auditoría, y plan de la Fase 1 con archivos afectados, pruebas y orden.

## 4. Conjunto de evaluación

### Formato de caso (un archivo por caso)

- `capa`: ingesta, persistencia, contexto, entrenador o interfaz/orquestación.
- `estado_inicial`: datos y plan de partida.
- `operaciones`: pasos a reproducir (sincronizar, consultar, repetir consulta, etc.).
- `estado_final_esperado`: lo que debe quedar en cada capa.
- `pregunta` (capas entrenador e interfaz/orquestación, o consultas reproducidas en persistencia), `debe`, `no_debe`, `comprobaciones`.
- `modo_modelo`: no aplica, doble determinista u Ollama real.
- `resultado`: `cumple`, `incumple` o `no evaluable`, con motivo y referencias a la evidencia de la ejecución.

Los casos del entrenador pueden partir directamente del contexto. Los de ingesta y persistencia reproducen los pasos anteriores.

### Casos

| Id  | Capa         | Situación                                                                                                                           | Debe                                                                                                                                                                        | No debe                                                                                                                                                               |
| --- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E01 | Entrenador   | 3 de octubre: 35–45 min suaves previstos; actividad Garmin de 20,02 km en 1 h 45 min 04 s; sueño, pulso en reposo y estrés de Zepp. | Señalar la diferencia de duración, comprobar la correspondencia con la sesión, contrastar el bienestar con el historial si existe, dar siguiente paso o pedir lo que falta. | Declararla cumplida por la fecha, dar la sesión por pendiente sin comprobar correspondencia (podría ser otra actividad), afirmar buena recuperación por un solo dato. |
| E02 | Ingesta      | Mismo entrenamiento en Garmin y Strava.                                                                                             | Contarlo una vez y conservar ambos orígenes.                                                                                                                                | Duplicar carga.                                                                                                                                                       |
| E03 | Contexto     | Sesión CMF solo en Strava.                                                                                                          | Incluirla atribuida a Strava.                                                                                                                                               | Atribuirla a Garmin.                                                                                                                                                  |
| E04 | Ingesta      | Dos sesiones distintas del mismo deporte el mismo día.                                                                              | Mantenerlas separadas.                                                                                                                                                      | Fusionarlas por fecha.                                                                                                                                                |
| E05 | Ingesta      | Sueño de Zepp publicado con retraso.                                                                                                | Actualizar el día correspondiente en la siguiente recogida.                                                                                                                 | Duplicar el registro.                                                                                                                                                 |
| E06 | Contexto     | Un proveedor falla o tiene datos antiguos.                                                                                          | Usar el resto y señalar qué falta y su antigüedad.                                                                                                                          | Presentar datos viejos como actuales.                                                                                                                                 |
| E07 | Entrenador   | Sesión prevista sin actividad registrada.                                                                                           | Distinguir «sin actividad» de «sin datos».                                                                                                                                  | Asumir que no entrenó.                                                                                                                                                |
| E08 | Entrenador   | Actividad sin sesión prevista.                                                                                                      | Tratarla como no planificada.                                                                                                                                               | Forzarla a encajar en el plan.                                                                                                                                        |
| E09 | Entrenador   | Carrera, bici y fuerza en la misma semana.                                                                                          | Valorar el conjunto con cada escala por separado.                                                                                                                           | Sumar TRIMP, TSS y carga muscular.                                                                                                                                    |
| E10 | Entrenador   | Molestia registrada y sesión de calidad prevista.                                                                                   | Tenerla en cuenta en la recomendación.                                                                                                                                      | Ignorarla o minimizarla.                                                                                                                                              |
| E11 | Persistencia | Consultar el plan varias veces.                                                                                                     | Mismo identificador de plan, misma revisión y mismas sesiones.                                                                                                              | Crear versiones o modificar sesiones. El texto puede variar.                                                                                                          |
| E12 | Entrenador | Se inyecta una explicación contradictoria con la decisión mediante un doble determinista del modelo. | Reparar dentro del límite o dar reserva identificada; probar reparación válida y contradicción persistente. | Enviar la contradicción o depender de que Ollama la genere por azar. |
| E13 | Entrenador   | Sin historial personal suficiente para comparar bienestar.                                                                          | Decir que no hay base de comparación.                                                                                                                                       | Inventar una referencia personal.                                                                                                                                     |
| E14 | Interfaz/orquestación | La misma pregunta por texto, voz y comando antiguo, con transcripción controlada y entregas interceptadas. | Verificar el enrutamiento al mismo servicio y contexto; recomendación coherente. | Criterios distintos según la vía o envíos reales. |
| E15a | Persistencia | Consulta informativa en la que el entrenador recomienda cambiar una sesión, sin solicitud explícita de ajuste. | Mantener la recomendación como respuesta informativa. | Persistir una propuesta o modificar el plan sin autorización. |
| E15b | Persistencia | Solicitud explícita de ajuste con plan y permisos válidos. | Registrar la propuesta validada como pendiente, conservando intacto el plan. | Aplicar la propuesta automáticamente o tratar la recomendación como autorización. |
| E16 | Ingesta      | Datos cerca de medianoche y en el cambio horario (en Europa, el 25 de octubre de 2026).                                             | Asignar cada dato a la fecha correcta, sin duplicados ni huecos.                                                                                                            | Desplazar el sueño o una actividad al día equivocado.                                                                                                                 |
| E17 | Contexto     | Wattwise no disponible.                                                                                                             | Responder con el resto y declarar la limitación.                                                                                                                            | Inventar métricas de Wattwise ni callar su ausencia.                                                                                                                  |

### Comprobación de cifras

Cada cifra del texto debe proceder de **un dato identificado, una conversión o un cálculo reproducible**, con tolerancias explícitas (por ejemplo, 6.304 s → 105 min). Una cifra sin origen reproducible es un fallo. Ausencia de contradicción entre explicación y decisión: reglas concretas por caso más revisión manual; validar el JSON no basta.

### Otras comprobaciones automáticas

- No atribuir mediciones a un proveedor sin evidencia. Sí se permite explicar su ausencia o falta de disponibilidad cuando conste en el estado de fuentes.
- Latencia total por consulta.
- Número de reparaciones y de respuestas de reserva.

### Rúbrica manual (0 / 1 / 2)

Fidelidad, procedencia, utilidad (valoración, evidencias, recomendación o aclaración, limitaciones), escalas no mezcladas y prudencia ante lo que no se puede concluir.

### Interpretación de los resultados

- `cumple`: las comprobaciones aplicables se han ejecutado y satisfacen lo esperado.
- `incumple`: hay evidencia reproducible de una desviación del producto, incluida una capacidad requerida ausente que pueda demostrarse.
- `no evaluable`: faltan acceso, evidencia histórica o medios del evaluador para comprobar el comportamiento. Debe indicarse qué falta; no cuenta como aprobado ni como fallo demostrado del producto.

Si el contrato actual no permite representar un escenario, se documentará esa limitación y qué parte sí se ha podido comprobar. Un rechazo por esquema en E12, por ejemplo, no demuestra detección semántica de contradicciones. No se modificará el producto para forzar la evaluación. Un error del evaluador tampoco se contabilizará como fallo del producto.

## 5. Criterio de cierre

La Fase 0 termina cuando se cumplen **todos**:

1. Inventario completo (0.2).
2. Entorno aislado verificado (0.3).
3. Traza de E01 hecha o con tramos no observables documentados (0.4).
4. Cobertura por proveedor en tres estados (0.5).
5. Línea base de todos los casos y variantes guardada, con tres repeticiones para los que llamen realmente a Ollama y resultados `no evaluable` justificados cuando proceda (0.7).
6. Hallazgos priorizados con evidencia y limitaciones explícitas (0.8).
7. Referencia congelada e instrucciones de reproducción guardadas; cualquier versión o dato inaccesible queda identificado como limitación (0.1 y 0.7).

No exige que los casos pasen. Los casos no evaluables deben figurar en el cierre con su motivo e impacto sobre las conclusiones; nunca se presentarán como capacidades verificadas.

## 6. Propuestas para fases posteriores (no se aplican en la Fase 0)

| Tema                | Propuesta, a decidir con evidencia                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Zepp y actividades  | Fuente secundaria con deduplicación, conservando las existentes.                                                    |
| Historial           | Definir qué se guarda, dónde, cuánto tiempo y con qué volumen antes de decidir «todo el crudo». Son datos de salud. |
| Ventana de análisis | 90 días como punto de partida, sin enviarlos íntegros al modelo.                                                    |
| Horario de recogida | Decidir tras ver la frecuencia actual real; no reducirla.                                                           |
| Resumen diario      | No por ahora; recoger no implica enviar.                                                                            |
| Ajustes del plan    | Proponer, confirmar y solo entonces aplicar.                                                                        |

## 7. No-objetivos

- Cambiar el comportamiento del entrenador.
- Añadir fuentes, comandos o llamadas al modelo al flujo del producto. Las llamadas de evaluación aisladas descritas en 0.7 sí forman parte de esta fase.
- Mover archivos o refactorizar `coach.py`, `sync.py` o `ai_worker.py`.
- Garantizar ejecución con el Mac apagado.
- Desplegar o enviar mensajes de prueba.
