# Reestructuración del proyecto: datos diarios y entrenador único

Fecha: 3 de octubre de 2026.

Estado: propuesta de trabajo para revisión. Este documento describe el destino y
la secuencia de cambios; no implica que estén implementados ni desplegados.

## 1. Objetivo

El proyecto empezó como un análisis de entrenamientos Garmin para preparar una
maratón. Ahora incluye carrera, bicicleta, fuerza, varias fuentes de datos,
analítica específica y un entrenador local con Ollama. La organización y la
experiencia de uso deben reflejar ese alcance.

Queremos recoger diariamente los entrenamientos y el bienestar, conservar un
historial coherente y ofrecer una única opinión del entrenador. Una respuesta
útil debe explicar qué ha ocurrido, cómo encaja en el plan y qué conviene hacer
después, indicando los datos y las limitaciones que sostienen esa valoración.

La maratón sigue siendo el objetivo deportivo de referencia. Bici, fuerza y
recuperación forman parte de la interpretación conjunta, sin desaparecer detrás
de los datos de carrera.

## 2. Fuentes y responsabilidades

| Fuente | Papel previsto |
| --- | --- |
| Garmin Connect: Instinct y Edge 530 | Entrenamientos registrados con Garmin y referencias deportivas disponibles. |
| Strava: CMF by Nothing | Entrenamientos del CMF publicados en Strava. Conservar proveedor y dispositivo cuando se conozca. |
| Zepp: Amazfit Helio Strap | Fuente principal de bienestar diario, al ser la pulsera de uso continuo. |
| Registro manual | Series, pesos, repeticiones y esfuerzo de fuerza; molestias y notas relevantes. |
| Perfil y pruebas aplicadas | Objetivos y referencias personales confirmadas. Las pruebas pendientes no sustituyen valores confirmados. |
| Analítica Python y Wattwise | Cálculos y comparaciones para el entrenador, con sus unidades, fechas y limitaciones. |

Zepp ya importa también actividades. Conservaremos las existentes; decidir si
continúa como fuente secundaria de nuevos entrenamientos queda pendiente de
confirmación. No se eliminará historial por cambiar la política de fuentes.

La preferencia de fuente se definirá por tipo de dato. Una métrica ausente de
Zepp podrá usar una alternativa Garmin compatible, identificándola. No se
intercambiarán puntuaciones de proveedores con significados distintos.

## 3. Diagnóstico inicial del código

Estos hallazgos proceden de una revisión del repositorio. Todavía falta verificar
qué versiones ejecutan Railway y el Mac, los horarios efectivos, los registros
de ejecución y la frescura real de cada proveedor.

| Hallazgo | Evidencia | Consecuencia |
| --- | --- | --- |
| Ollama selecciona decisiones, pero no redacta una interpretación final. | `coach_generation_pipeline.py` prohíbe prosa libre; el resolver utiliza un catálogo de frases. | Respuestas como «Actividad registrada» sustituyen explicaciones útiles. |
| Hay distintas vías de respuesta deportiva. | `apps/bot/app/main.py` resuelve directamente `/feedback`, `/proximo`, `/semana` y otros, mientras `/coach` crea un trabajo de IA. | Las consultas pueden seguir criterios diferentes. |
| Consultar `/plan` construye y guarda un plan. | El enrutador llama a `build_week_plan` y `save_training_plan`. | Consultar y modificar el plan no están separados con claridad. |
| La procedencia Strava se pierde en el contexto validado. | `coach_generation_context.py` no admite `strava` entre sus fuentes y las actividades usan Garmin como alternativa. | El entrenador puede atribuir a Garmin datos de Strava. |
| La mejora del análisis diario es descriptiva y condicional. | `coach_generation_renderer.py` calcula observaciones para respuestas de análisis con decisiones informativas. | No resuelve por sí sola la interpretación de recuperación y cumplimiento del plan. |
| Hay responsabilidades concentradas y documentación desfasada. | `coach.py` supera 3.500 líneas; el README afirma una unificación que el enrutador no refleja. | Es difícil localizar la lógica vigente y prever los efectos de un cambio. |

No podemos concluir a partir de estos hallazgos que la sincronización diaria
esté fallando. Debemos distinguir fallos de recogida, pérdida de información al
construir el contexto y limitaciones al producir la respuesta.

## 4. Enfoque de la reestructuración

Haremos una migración gradual por responsabilidades. Aprovecharemos los
conectores, cálculos y validaciones existentes que sean correctos, sustituyendo
los caminos duplicados cuando su reemplazo esté comprobado.

Mover archivos sin cambiar los flujos dejaría intactos los problemas actuales.
Una reescritura completa obligaría a reconstruir integraciones que ya funcionan.
Por eso cada fase tendrá una mejora observable, pruebas de aceptación y una
forma de volver a la versión anterior.

Mantendremos inicialmente la distribución actual: credenciales, sincronización,
Ollama y servicios locales en el Mac; API, persistencia y Telegram en Railway.
La disponibilidad seguirá dependiendo de que el Mac esté despierto. La recogida
diaria tendrá recuperación de días pendientes al volver a estar disponible;
garantizar ejecución con el Mac apagado requeriría otra decisión de infraestructura.

## 5. Arquitectura de destino

```text
Garmin / Strava / Zepp / registros manuales
                     |
                     v
       Recogida y estado por proveedor
                     |
                     v
    Normalización, procedencia y deduplicación
                     |
                     v
      Historial común + perfil + plan vigente
                     |
                     v
     Analítica de carrera, bici, fuerza y bienestar
                     |
                     v
       Contexto único para el entrenador
                     |
                     v
        Interpretación Ollama + validación
                     |
                     v
             Respuesta Telegram
```

### 5.1. Recogida diaria

- Separar los adaptadores Garmin, Strava y Zepp del proceso que coordina la recogida.
- Registrar por proveedor último intento, último éxito, periodo cubierto y error.
- Mantener la recogida de los demás proveedores cuando uno falle.
- Reconsultar días recientes para incorporar sueño o actividades publicados con retraso.
- Permitir repetir una sincronización sin duplicar actividades ni registros diarios.
- Distinguir «sin actividad», «sin datos», «datos antiguos» y «error del proveedor».
- Mantener `/sync` como solicitud de actualización completa; los modos antiguos podrán ser alias.

### 5.2. Historial común

Cada actividad conservará identificador interno, identificadores externos,
proveedor, dispositivo si existe, deporte, inicio, zona horaria, duración y
métricas disponibles. Las mediciones de bienestar conservarán fecha observada,
fecha de recogida, unidad, fuente y validez.

La deduplicación debe reconocer una actividad Garmin replicada en Strava sin
descartar dos sesiones distintas. La selección del registro principal conservará
la relación con los originales. Las coincidencias ambiguas permanecerán visibles.

El contexto se construirá para el periodo consultado. No dependerá únicamente de
un número fijo de actividades recientes o de instantáneas de sincronización que
pueden representar varias veces el mismo día.

### 5.3. Analítica y relación con el plan

Python seguirá calculando duraciones, ritmos, agregados y métricas deportivas.
Wattwise aportará sus resultados cuando esté disponible. Ollama interpretará
estos resultados sin recalcular cifras ni inventar referencias personales.

La comparación incluirá todas las sesiones pertinentes de carrera, bici y fuerza,
el bienestar disponible, las molestias y las referencias personales. No sumaremos
directamente TRIMP, TSS y carga muscular como si fueran la misma unidad.

Se distinguirán sesiones planificadas, realizadas, pendientes y sustituidas. Una
coincidencia de fecha no bastará para marcar un entrenamiento como completado:
se comprobarán deporte y correspondencia; ante ambigüedad se pedirá aclaración.

### 5.4. Entrenador único

Texto, voz y comandos deportivos consultarán el mismo servicio de entrenamiento.
Los cálculos tendrán un único origen y el entrenador recibirá una instantánea
coherente con actividades, bienestar, historial, plan, perfil y estado de fuentes.

La respuesta deberá contener, según la pregunta:

1. Una valoración principal comprensible.
2. Las evidencias relevantes que la explican, sin volcar todas las métricas.
3. Una recomendación concreta o una aclaración necesaria.
4. Las limitaciones que cambien la interpretación.

El contrato del modelo se ampliará para admitir una explicación fundamentada
junto a decisiones estructuradas y referencias a evidencias. La validación
mantendrá control sobre fuentes, fechas, cifras, sesiones y permisos; también
comprobará contradicciones entre explicación y decisión. Validar referencias no
demuestra por sí solo que una interpretación deportiva sea correcta: harán falta
casos de evaluación y revisión de la calidad de las respuestas.

Conservaremos una reparación acotada y una respuesta de reserva identificada
cuando la salida no sea válida. El número de llamadas al modelo y sus límites se
decidirán con pruebas de calidad y latencia; no añadiremos otra llamada por defecto.

Consultar un plan no lo regenerará. Recomendar un cambio, registrar una propuesta
y aplicar una modificación serán operaciones distintas. Una explicación del
modelo nunca equivaldrá a una modificación silenciosa del plan persistido.

### 5.5. Telegram y ayuda

La entrada habitual será escribir o enviar voz al entrenador. Propuesta inicial:

| Comando | Función |
| --- | --- |
| `/coach` | Consultar al entrenador; equivalente a preguntar en lenguaje natural. |
| `/plan` | Consultar el plan vigente. Crear o modificar tendrá una intención explícita diferenciada. |
| `/sync` | Solicitar actualización de las fuentes. |
| `/estado` | Ver frescura por proveedor, errores y disponibilidad del procesamiento local. |
| `/registro` | Acceder a fuerza, molestias, perfil y pruebas mediante opciones guiadas. |
| `/help` | Mostrar estas entradas y ejemplos breves. |

Los comandos existentes se mantendrán temporalmente como alias o accesos
compatibles. Las consultas deportivas pasarán por el entrenador único. Las
operaciones de registro seguirán siendo deterministas y no necesitarán Ollama
para guardar correctamente los datos.

## 6. Organización del código

Los nombres y ubicaciones definitivos se fijarán en el plan técnico, respetando
el empaquetado del Mac y de Railway. Los límites de responsabilidad serán:

| Área | Responsabilidad |
| --- | --- |
| Proveedores | Autenticación local, consultas y adaptación de datos externos. |
| Ingesta | Coordinación, reintentos, normalización y deduplicación. |
| Dominio | Actividades, bienestar, perfil, sesiones y contratos compartidos. |
| Persistencia | Historial, versiones del plan, trabajos y propuestas. |
| Analítica | Cálculos deportivos y comparaciones verificables. |
| Entrenador | Construcción de contexto, generación, validación y respuesta. |
| Interfaces | Telegram y API; traducen solicitudes sin mantener otro criterio deportivo. |

La extracción de `coach.py`, `sync.py` y `ai_worker.py` se hará alrededor de esos
límites. Se revisará también la duplicación de contratos entre bot y worker para
que ambas partes usen versiones compatibles.

## 7. Fases y entregables

### Fase 0 — Auditoría y referencia inicial

- Comprobar versiones activas en Mac y Railway y contrastarlas con el repositorio.
- Trazar una consulta completa: datos recogidos, contexto, salida del modelo y texto final.
- Revisar programación, estado por proveedor e historial realmente disponible.
- Inventariar comandos, generadores de planes, analíticas y contratos duplicados.
- Preparar casos reproducibles sin credenciales ni datos personales innecesarios.

Salida: diagnóstico verificable y lista priorizada de fallos, separando código y operación.

### Fase 1 — Datos coherentes de extremo a extremo

- Corregir la procedencia Strava en contexto, contratos y presentación.
- Definir y probar normalización, identidades y política de selección de fuentes.
- Asegurar deduplicación, actualización de días anteriores y fallos parciales.
- Exponer frescura y estado de cada proveedor.

Salida: una misma actividad y medición conservan su identidad desde la recogida
hasta el contexto del entrenador.

### Fase 2 — Contexto deportivo y plan coherentes

- Construir el contexto por fechas y pregunta, incluyendo historial pertinente.
- Vincular sesiones realizadas y planificadas con tratamiento de ambigüedades.
- Integrar analíticas de carrera, bici y fuerza sin mezclar sus escalas.
- Separar consulta, creación, propuesta de ajuste y aplicación del plan.

Salida: el entrenador distingue lo previsto de lo realizado y conoce la calidad
y antigüedad de la información que utiliza.

### Fase 3 — Interpretación útil y única

- Evolucionar el contrato de Ollama para admitir valoración fundamentada.
- Validar consistencia entre hechos, explicación y decisiones.
- Unificar consultas deportivas, texto y voz en el mismo servicio.
- Evaluar respuestas con el modelo local, midiendo calidad, errores y latencia.

Salida: respuestas que explican una conclusión y sus implicaciones, con una
reserva explícita cuando no es posible responder de forma fundamentada.

### Fase 4 — Simplificación de la experiencia

- Reducir `/help` y añadir accesos guiados a operaciones de registro.
- Convertir comandos antiguos en alias compatibles y documentar su transición.
- Eliminar generadores de opinión paralelos una vez sustituidos y comprobados.

Salida: el usuario puede preguntar al entrenador sin elegir entre varias vías de análisis.

### Fase 5 — Consolidación y despliegue

- Extraer módulos por responsabilidad y retirar código sin uso confirmado.
- Actualizar README, configuración y documentación operativa.
- Aplicar migraciones compatibles y verificar persistencia con una base aislada.
- Desplegar versiones compatibles de API y worker y comprobar el flujo completo.

Salida: sistema mantenible, documentación acorde al comportamiento y procedimiento
de recuperación probado. La reorganización de archivos acompañará las fases
anteriores cuando facilite sus cambios; no se concentrará toda al final.

## 8. Criterios de aceptación

| Caso | Resultado esperado |
| --- | --- |
| Garmin y Strava contienen el mismo entrenamiento. | Se contabiliza una vez y se conserva la procedencia de los registros relacionados. |
| Solo Strava contiene una sesión CMF. | Aparece en historial, analítica y contexto sin atribuirla a Garmin. |
| Zepp publica el sueño con retraso. | La siguiente recogida actualiza la fecha correspondiente sin duplicarla. |
| Un proveedor falla. | Se conservan los datos válidos de los demás y se identifica la información pendiente. |
| El Mac ha estado dormido. | Se recupera la recogida pendiente al despertar y se informa de la antigüedad mientras tanto. |
| Hay carrera, bici y fuerza en el periodo. | Se consideran las sesiones relevantes sin sumar escalas incompatibles. |
| Se consulta el plan varias veces. | La consulta no crea versiones ni cambia sesiones. |
| Se pregunta lo mismo por texto, voz o un alias. | Se utiliza el mismo contexto y servicio; la recomendación es coherente aunque cambie la redacción. |
| Ollama falla o produce una contradicción. | La respuesta se repara dentro del límite o se ofrece una reserva identificada. |
| Se propone cambiar una sesión. | La propuesta no se aplica sin el flujo de autorización previsto. |

### Caso de referencia del 3 de octubre de 2026

El ejemplo comunicado contiene una sesión prevista de 35–45 minutos suaves y una
actividad Garmin de 20,02 km y 6.304 segundos, equivalentes a 1 h 45 min 04 s.
También incluye datos Zepp de sueño, pulso en reposo y estrés.

La respuesta aceptable debe:

- Detectar y explicar la diferencia entre duración prevista y registrada.
- Comprobar si la actividad corresponde a esa sesión antes de declararla cumplida.
- Interpretar el bienestar respecto al historial personal cuando exista.
- No afirmar buena recuperación únicamente por una puntuación o un pulso aislado.
- No presentar la sesión prevista como pendiente sin revisar la actividad realizada.
- Explicar la recomendación siguiente o qué información falta para concretarla.

Este caso es una prueba del comportamiento del software, no una prescripción
deportiva redactada a partir de datos incompletos.

## 9. Validación y migración

Cada fase tendrá pruebas de sus contratos y regresiones observadas. Los conectores
usarán respuestas de ejemplo; la persistencia se comprobará en una base aislada.
Las pruebas con Ollama se ejecutarán con casos controlados y revisarán utilidad,
fidelidad a las fuentes, coherencia y tiempos, además de validez del JSON.

Antes de cambiar esquemas se preparará una copia de seguridad y se verificará su
restauración. Las migraciones serán inicialmente aditivas; conservaremos datos e
identificadores antiguos hasta completar la transición. Durante el cambio de
contratos se verificará compatibilidad entre API y worker, incluidos trabajos
pendientes y propuestas vinculadas a versiones anteriores del plan.

La comparación temporal entre el flujo anterior y el nuevo no enviará respuestas
duplicadas ni aplicará dos veces cambios de plan. El despliegue tendrá una ruta
de vuelta a la versión anterior compatible con los datos migrados.

La validación local y la verificación en producción se documentarán por separado.
Este documento no autoriza mensajes de prueba al usuario ni despliegues: esas
acciones se concretarán en la fase correspondiente.

## 10. Decisiones pendientes y siguiente paso

Quedan por acordar antes de las fases que dependan de ellas:

- Si Zepp seguirá importando actividades nuevas además de bienestar.
- La ventana mínima de historial necesaria y la política de conservación.
- Los horarios preferidos de recogida y si se desea un resumen automático diario;
  recoger datos diariamente no implica enviar mensajes diarios.
- La presentación definitiva de `/registro` y la transición de comandos antiguos.
- El flujo de aceptación y aplicación de ajustes del plan.

El siguiente paso es revisar este documento, cerrar las decisiones que bloqueen
la primera fase y redactar su plan de implementación con archivos afectados,
pruebas y orden de cambios. La prioridad inicial será comprobar el recorrido
completo de los datos y corregir su coherencia antes de ampliar la interpretación
del entrenador.
