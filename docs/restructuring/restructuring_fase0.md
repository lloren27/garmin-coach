# Fase 0: plan de implementación (auditoría y referencia inicial)

Fecha: 3 de octubre de 2026. Estado: borrador para revisión.

## 1. Objetivo

Obtener un diagnóstico verificable de cómo viaja hoy un dato desde el proveedor hasta la respuesta del entrenador, y dejar un conjunto de casos reproducibles con el que medir cada fase posterior.

**Foco del proyecto (propuesta de frase):** el sistema recoge mis datos cada día y me da una única opinión fundamentada sobre lo que hice y lo que toca después.

**Salida de la fase:**

1. Informe de auditoría con hallazgos separados en _código_ y _operación_, priorizados.
2. Conjunto de evaluación (E01–E13) con rúbrica y comprobaciones automáticas.
3. Lista de no-objetivos y decisiones pendientes con valor por defecto.

## 2. Reglas de la fase

- Solo lectura sobre producción. No se despliega, no se cambia el esquema, no se envían mensajes de prueba por Telegram.
- Los cambios de código se limitan a pruebas y a utilidades de trazado que no alteren el comportamiento.
- Nada de credenciales ni datos personales innecesarios en los casos (se anonimizan o se sintetizan).
- Cada hallazgo se etiqueta: **verificado** (reproducido), **probable** (visto en código, sin reproducir) o **sin comprobar**.

## 3. Pasos

### 0.1. Congelar la referencia

- Anotar commit y rama del repositorio, versión efectiva en Railway y versión efectiva en el Mac (incluidos worker y modelo de Ollama con su etiqueta exacta).
- Registrar si difieren y en qué archivos.
- _Hecho cuando:_ hay una tabla «componente / dónde corre / versión / coincide con el repositorio».

### 0.2. Inventario

- Comandos de Telegram: cada uno, a qué función llega y si pasa por `/coach` (IA) o se resuelve directo en `apps/bot/app/main.py`.
- Generadores de opinión y de plan: `coach_generation_pipeline.py`, `coach_generation_context.py`, `coach_generation_renderer.py`, `coach.py`, `sync.py`, `ai_worker.py` y los que aparezcan al buscar `build_week_plan` y `save_training_plan`.
- Contratos duplicados entre bot y worker.
- Código y README que se contradicen.
- _Hecho cuando:_ tabla «elemento / archivo / quién lo llama / duplica a / ¿escribe estado?». Marcar en especial lo que escribe al consultar.

### 0.3. Trazar una consulta completa

Tomar el caso E01 y seguirlo con registros temporales (sin tocar lógica):

1. Qué filas existen en la base para ese día (por proveedor).
2. Qué entra al contexto validado y qué se descarta (procedencia incluida).
3. Qué decisiones devuelve Ollama.
4. Qué frase final produce el renderizador y por qué.

- _Hecho cuando:_ un documento de una página con los cuatro puntos y la primera pérdida de información identificada (¿recogida, contexto o redacción?).

### 0.4. Estado real de la recogida

- Horarios efectivos de ejecución en el Mac (programación real, no la prevista).
- Para cada proveedor (Garmin, Strava, Zepp): último éxito, huecos de los últimos 30 días, retrasos habituales en sueño y actividades.
- Qué ocurre hoy cuando el Mac duerme y al despertar.
- _Hecho cuando:_ tabla de frescura por proveedor y lista de días sin cobertura. Con esto se responde a la pregunta abierta: ¿falla la recogida o solo se pierde información después?

### 0.5. Muestra de historial para pruebas

- Extraer una ventana pequeña (por ejemplo 2–3 semanas) y anonimizarla.
- Localizar casos reales de duplicados Garmin/Strava, sesiones CMF solo en Strava y días con sueño tardío.
- Escribir la regla de coincidencia candidata (tolerancia de inicio, duración, distancia y deporte) y qué se considera ambiguo. Se prueba aquí contra los datos reales, sin implementarla aún.
- _Hecho cuando:_ archivo de datos de ejemplo versionable y regla candidata documentada.

### 0.6. Conjunto de evaluación

Ver sección 4. Se construye en paralelo a 0.3–0.5 y se cierra aquí.

### 0.7. Informe y cierre

- Lista priorizada de fallos con etiqueta de certeza.
- Decisiones pendientes con propuesta por defecto (sección 6).
- Plan de la Fase 1 con archivos afectados, pruebas y orden de cambios.

## 4. Conjunto de evaluación

### Formato de cada caso (un archivo por caso)

- `entrada`: actividades, bienestar, plan, perfil y estado de fuentes en el formato del contexto.
- `pregunta`: texto de la consulta.
- `debe`: comportamientos obligatorios.
- `no_debe`: comportamientos prohibidos.
- `comprobaciones`: reglas automáticas (por ejemplo, «toda cifra del texto existe en la entrada»).

### Casos

| Id  | Situación                                                                                                                                    | Debe                                                                                                                                                                        | No debe                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| E01 | Caso del 3 de octubre: 35–45 min suaves previstos; actividad Garmin de 20,02 km en 1 h 45 min 04 s; sueño, pulso en reposo y estrés de Zepp. | Señalar la diferencia de duración, comprobar la correspondencia con la sesión, contrastar el bienestar con el historial si existe, dar siguiente paso o pedir lo que falta. | Declararla cumplida por la fecha, dar la sesión por pendiente, afirmar buena recuperación por un solo dato. |
| E02 | Mismo entrenamiento en Garmin y Strava.                                                                                                      | Contarlo una vez y conservar ambos orígenes.                                                                                                                                | Duplicar carga.                                                                                             |
| E03 | Sesión CMF solo en Strava.                                                                                                                   | Incluirla y atribuirla a Strava.                                                                                                                                            | Atribuirla a Garmin.                                                                                        |
| E04 | Dos sesiones distintas del mismo deporte el mismo día.                                                                                       | Mantenerlas separadas.                                                                                                                                                      | Fusionarlas por coincidencia de fecha.                                                                      |
| E05 | Sueño de Zepp publicado con retraso.                                                                                                         | Actualizar el día correspondiente al reconsultar.                                                                                                                           | Duplicar el registro.                                                                                       |
| E06 | Un proveedor falla o tiene datos antiguos.                                                                                                   | Usar el resto y decir qué falta y su antigüedad.                                                                                                                            | Presentar datos viejos como actuales.                                                                       |
| E07 | Sesión prevista sin actividad registrada.                                                                                                    | Distinguir «sin actividad» de «sin datos».                                                                                                                                  | Asumir que no entrenó.                                                                                      |
| E08 | Actividad sin sesión prevista.                                                                                                               | Tratarla como sesión no planificada.                                                                                                                                        | Forzarla a encajar en una sesión del plan.                                                                  |
| E09 | Carrera, bici y fuerza en la misma semana.                                                                                                   | Valorar el conjunto con cada escala por separado.                                                                                                                           | Sumar TRIMP, TSS y carga muscular.                                                                          |
| E10 | Molestia registrada y sesión de calidad prevista.                                                                                            | Tener en cuenta la molestia en la recomendación.                                                                                                                            | Ignorarla o minimizarla.                                                                                    |
| E11 | Consultar el plan varias veces.                                                                                                              | Devolver el mismo plan.                                                                                                                                                     | Crear versiones o modificar sesiones.                                                                       |
| E12 | El modelo produce explicación y decisión contradictorias.                                                                                    | Reparar dentro del límite o dar respuesta de reserva identificada.                                                                                                          | Enviar la contradicción.                                                                                    |
| E13 | No hay historial personal suficiente para comparar bienestar.                                                                                | Decir que no hay base de comparación.                                                                                                                                       | Inventar una referencia personal.                                                                           |

### Rúbrica de calidad (revisión manual, 0 / 1 / 2 por criterio)

1. **Fidelidad:** cada afirmación se apoya en la entrada.
2. **Procedencia:** atribuye bien las fuentes.
3. **Utilidad:** incluye valoración, evidencias, recomendación o aclaración, y limitaciones.
4. **Escalas:** no mezcla unidades incompatibles.
5. **Prudencia:** reconoce lo que no puede concluir.

### Comprobaciones automáticas

- Toda cifra, fecha y duración del texto existe en la entrada (con tolerancia de formato).
- El JSON es válido y la decisión no contradice la explicación.
- No se menciona un proveedor ausente en la entrada.
- Latencia total por consulta, registrada para cada ejecución.

### Línea base

Ejecutar los 13 casos contra el sistema actual y guardar resultados (texto, puntuación, latencia). Esa tabla es la referencia que cada fase debe mejorar.

## 5. Orden de trabajo

1. 0.1 y 0.2 (rápidos, desbloquean todo lo demás).
2. 0.3 sobre E01 (primer resultado útil: dónde se pierde la información).
3. 0.4 y 0.5 en paralelo.
4. 0.6 y la línea base.
5. 0.7 informe y plan de la Fase 1.

Criterio para pasar a la Fase 1: la primera pérdida de información del caso E01 está localizada y la línea base está guardada.

## 6. Decisiones pendientes con valor por defecto

| Decisión                            | Valor por defecto propuesto                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| ¿Zepp sigue importando actividades? | Sí, como fuente secundaria, con deduplicación y conservando las existentes.                      |
| Historial conservado                | Guardar todo el historial crudo; analizar una ventana de 90 días salvo que la pregunta pida más. |
| Horario de recogida                 | Una pasada diaria por la mañana más una reconsulta de días recientes por la tarde.               |
| Resumen automático diario           | No por ahora. Recoger no implica enviar.                                                         |
| Ajustes del plan                    | Proponer, confirmar por Telegram y solo entonces aplicar.                                        |

Cada valor se aplica si no se decide otra cosa antes de empezar la fase que lo necesite.

## 7. No-objetivos de esta fase

- Cambiar el comportamiento del entrenador.
- Añadir fuentes, comandos o llamadas al modelo.
- Mover archivos o refactorizar `coach.py`, `sync.py` o `ai_worker.py`.
- Garantizar ejecución con el Mac apagado.
- Desplegar o enviar mensajes de prueba.
