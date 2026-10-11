# Fase 4: experiencia simple y entrenador único

Fecha: 11 de octubre de 2026.
Estado: diseño para revisión. El enfoque gradual está aprobado; este documento no implica implementación ni despliegue.

## Objetivo y punto de partida

El usuario debe poder preguntar por texto, voz o un comando antiguo sin elegir entre criterios deportivos diferentes. La fase 4 simplifica la ayuda, conserva los registros deterministas y cierra E14 mediante equivalencia verificable de rutas y resultados.

El cierre de fase 3 del 10 de octubre permite continuar, pero mantiene E14 pendiente. `route_message` responde localmente a numerosos comandos deportivos; texto, voz, `/coach` y `/ajustar` llegan a la cola. `COACH_QUESTIONS` existe, pero contiene entradas de plan cuyo significado ya no coincide con el contrato vigente. No se reutilizará íntegramente sin revisar cada intención.

Además, `build_ai_brief` consume funciones que también generan respuestas locales. Suprimir las ramas del enrutador no permite borrar automáticamente esas funciones. El worker selecciona el análisis V3 mediante `COACH_ANALYSIS_V3_ENABLED`; la fase 3 no certificó su activación en producción.

El árbol de trabajo contiene cambios y evidencias del cierre de fase 3 sin commit. Se preservarán y se usarán como base de las verificaciones; los cambios de fase 4 se identificarán por separado.

## Decisión y alternativas

Se adopta la migración gradual aprobada: unificar alias, introducir ayuda y accesos guiados, y retirar opiniones duplicadas después de verificar sus sustitutos. Cambiar solo la ayuda dejaría E14 abierto. Sustituir todas las rutas y eliminar sus dependencias a la vez dificultaría localizar regresiones.

La arquitectura de despliegue sigue siendo bot/API en Railway y worker en el Mac. Esta fase no añade un servicio ni una segunda interpretación de reserva en el bot.

## 1. Entrada común al entrenador

Un adaptador de comandos del bot convierte los alias deportivos en consultas canónicas antes de crear el trabajo. El worker sigue siendo el punto común de interpretación, validación y respuesta. El adaptador no calcula recomendaciones.

| Entrada | Comportamiento |
| --- | --- |
| Texto libre, `/coach pregunta` | Consulta al servicio común. `/coach` solo muestra ejemplos. |
| Voz o audio | Trascripción y procesamiento por el mismo servicio; conserva su modalidad de respuesta. |
| `/hoy`, `/semana`, `/ultima`, `/proximo`, `/fatiga`, `/salud`, `/carga`, `/tendencia`, `/feedback`, `/bici`, `/malaga` | Alias de consulta con intención y periodo definidos. |
| `/running`, `/correr`, `/carga_running` | Misma consulta centrada en carrera. |
| `/potencia`, `/wattwise` | Misma consulta centrada en potencia ciclista. |
| `/ajustar` y sus argumentos | Solicitud explícita de propuesta según las validaciones de fase 2; nunca aplicación implícita. |
| `/plan`, `/plan_semana` | Lectura directa del plan vigente. |
| `/plan nuevo`, `/plan_semana nuevo` | Creación explícita por el flujo existente. |

Los argumentos se conservan y se identifican como información del usuario. Una fecha o periodo explícito sustituye el periodo predeterminado del alias, evitando preguntas contradictorias como «hoy» y «ayer» en la misma consulta. Sin argumentos, `/feedback` se refiere al último día con entrenamiento y `/ultima` a la última actividad y sus sesiones del día. `/semana` consulta la semana y el plan vigente, sin crear uno.

La normalización admite mayúsculas y sufijos Telegram como `/feedback@MiBot`. Los alias de consulta no adquieren permiso de modificación por incluir una frase imperativa en el texto canónico. `/ajustar` conserva la detección de negaciones y los controles existentes. Una petición ambigua recibe la aclaración del servicio común.

Las consultas comparten construcción de contexto, reloj del trabajo, fuentes, plan e historial. La equivalencia se mide con datos y reloj fijados; no exige respuestas idénticas entre trabajos procesados con datos distintos. Si el Mac no procesa el trabajo, la consulta permanece en el flujo de cola existente y el bot no inventa una respuesta deportiva local.

## 2. Ayuda y registros

`/start` y `/help` presentan seis entradas: `/coach`, `/plan`, `/sync`, `/estado`, `/registro` y `/help`, con ejemplos breves de texto y voz. Se comunica que los comandos anteriores siguen funcionando; `/help comandos` ofrece la lista de compatibilidad y sus significados actualizados.

`/registro` ofrece un menú textual de comandos utilizables en Telegram. Los subcomandos `/registro fuerza`, `/registro molestias`, `/registro perfil` y `/registro pruebas` muestran instrucciones y ejemplos de las operaciones existentes. Esta primera versión no necesita botones, callbacks ni estado de conversación persistente.

Abrir un menú o una ayuda no escribe datos. Guardar sigue requiriendo los comandos explícitos existentes: `/fuerza`, `/checkin`, `/perfil` y los de pruebas de esfuerzo. Las pruebas pendientes mantienen su flujo de revisión y aplicación. Un subcomando desconocido muestra las opciones válidas sin crear un trabajo de análisis.

## 3. Estado operativo

`/estado` muestra la información disponible de frescura y errores por proveedor y ámbito, la última sincronización y su petición pendiente. Distingue datos ausentes, ausencia de actividad, información antigua, fallo y proveedor sin configurar, siguiendo la semántica de fase 1.

Las fechas se presentan en Europe/Madrid y la fecha de recepción no sustituye la fecha de los datos. Se muestran errores resumidos y seguros, sin trazas ni credenciales. Si no existe evidencia fiable de disponibilidad del worker, se indica «disponibilidad no confirmada»; una sincronización reciente no demuestra que el Mac esté despierto ahora. No se añade un heartbeat en esta fase.

`/status` y `/syncinfo` conservan sus lecturas compatibles y remiten a `/estado` para la vista conjunta. Los modos `/sync zepp` y `/sync cmf` siguen siendo compatibles. La ayuda describe la dependencia del procesamiento local sin prometer una latencia fija no medida.

## 4. Retirada de opiniones duplicadas

Primero se eliminan las ramas de respuesta deportiva directa del enrutador. Después se inventarían las referencias a sus formateadores, a `format_natural_coach`, a `build_ai_brief` y a las reservas del worker.

Se conservan los cálculos, datos y formatos transaccionales utilizados. Los resúmenes que alimentan contexto deben contener hechos y analítica, sin introducir otra recomendación prescriptiva. Una función solo se elimina tras sustituir sus consumidores y comprobar la regresión correspondiente.

La ruta antigua del worker asociada al interruptor V3 se mantiene mientras sea necesaria para compatibilidad y reversión. Debe figurar explícitamente como ruta de compatibilidad, con sus consumidores y condición de retirada. No se declarará eliminada toda opinión paralela si queda alguna activa o necesaria. La activación en producción y la retirada definitiva de compatibilidad dependen de la validación y despliegue de fase 5.

## Entregables y orden

1. Adaptador de alias y pruebas de equivalencia E14, preservando las intenciones del plan.
2. Ayuda reducida, registro guiado y estado operativo de solo lectura.
3. Sustitución de consumidores de opiniones locales, retirada comprobada y tabla de compatibilidad en documentación.
4. Informe de cierre con evidencia, código conservado por compatibilidad y límites operativos.

Los módulos nuevos se limitarán a la traducción de comandos y presentación de ayuda/estado cuando facilite su prueba. No se hará una reorganización general de `coach.py` ni del worker.

## Criterios de aceptación y verificación

- Para cada alias deportivo, el bot crea exactamente un trabajo y no ejecuta el formateador deportivo local. Se comprueban argumentos, fechas, sufijos y comandos desconocidos.
- E14 compara un alias, su pregunta canónica por texto, `/coach` y voz con transcripción simulada sobre la misma instantánea y reloj. Deben coincidir intención, periodo, hechos relevantes, decisiones y permisos. En V3 se verifica la salida estructurada; en la ruta de compatibilidad se verifica el mismo punto de entrada sin exigir igualdad literal de prosa.
- La prueba cubre todos los alias y sus grupos, no solo `/feedback`. Ningún alias anuncia soporte que el resolver no pueda interpretar: antes de conectarlo se verifica su pregunta y, si procede, se ajusta su traducción o el reconocimiento compartido con regresiones.
- Consultar `/plan` no crea versiones; `/plan nuevo` conserva la creación explícita. Consultar, proponer y aplicar siguen separados. Se mantienen las regresiones E15a/b y las negaciones de `/ajustar`.
- La ayuda, el estado y los menús funcionan sin worker y sin persistir cambios. Los registros conservan sus validaciones y escrituras explícitas.
- `/estado` se prueba con fuentes válidas, tardías, parciales, fallidas y ausentes; no atribuye datos Strava a Garmin ni afirma disponibilidad sin evidencia.
- El contexto conserva actividades, bienestar, fuerza, perfil, pruebas aplicadas, plan y procedencia al retirar formateadores. No reaparecen recomendaciones locales como fallback del bot.
- Se ejecutan las suites afectadas de bot y worker, las regresiones del cierre de fase 3 y la auditoría E14 con su criterio original. Las pruebas de persistencia usan PostgreSQL desechable.

La voz simulada no certifica Whisper, síntesis ni entrega real de Telegram. Los resultados locales no certifican producción. Las pruebas se ejecutarán durante la implementación; este diseño no afirma resultados nuevos.

## Compatibilidad y reversión

La documentación relacionará cada comando antiguo con su destino, indicará que las consultas deportivas ahora esperan al worker y conservará la sintaxis de registro. No se fija una fecha de eliminación de alias.

La implementación se dividirá por entregable para permitir revertir ayuda o enrutamiento sin modificar historial ni registros. La configuración del motor no cambia como efecto lateral de unificar alias. La fase 5 coordinará API, worker y activación; la fase 4 debe dejar explícita la configuración bajo la que se obtuvo cada evidencia.
