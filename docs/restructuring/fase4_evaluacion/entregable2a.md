# Fase 4 — evidencia del entregable 2a

**Estado:** implementación desplegada en producción según confirmación del usuario; suites verificadas. La conducta todavía no está observada/registrada.

## Alcance implementado

- El acuse de consultas encoladas informa que la consulta fue recibida y remite a `/estado`; sustituye el acuse anterior en el punto común de encolado, sin enviar un mensaje adicional. Se conserva el acuse específico de pruebas de laboratorio.
- Las respuestas de texto reciben una nota si la espera alcanza seis horas, o si cruza la fecha local de `Europe/Madrid` y supera 30 minutos. Las fechas ausentes, inválidas o sin zona horaria reciben la nota genérica de vigencia no confirmada. Una deriva futura de hasta 120 segundos se trata como edad cero; una deriva mayor queda como no fiable.
- El worker conserva la respuesta canónica en `payload["answer"]` y presenta la nota solo en la entrega de voz o en su propio mensaje de respaldo. El aviso hablado es breve y el texto/caption mantiene la nota completa. El caption se limita a 1.000 caracteres; ante desbordamiento, el worker envía la respuesta completa por texto. La respuesta canónica se limita a 3.500 caracteres para dejarla, junto con la nota, dentro de los 4.096 caracteres de Telegram.
- La matriz temporal compartida está en `tests/fixtures/late_response_cases.json` (13 casos; resultados `on_time`, `late` y `unreliable`) y la cargan las suites del bot y del worker.
- No se cambió el esquema, no se añadieron barridos ni avisos espontáneos, y no se modificaron rutas deportivas, alias ni salida estructurada.

## Verificación local

Se ejecutaron las suites completas con estos comandos:

```sh
cd apps/bot && .venv/bin/python -m unittest discover -s tests -v
cd apps/sync-local && .venv/bin/python -m unittest discover -s tests -v
```

Resultados:

- Bot: 130 tests, todos OK, sin omisiones.
- Worker: 292 tests, todos OK.
- `git diff --check a741af0..HEAD`: OK.
- Pruebas de integración de finalización de trabajos ejecutadas contra backend JSON y PostgreSQL desechable: ambos devuelven `created_at` como timestamp ISO con zona en el documento; PostgreSQL lo conserva como JSONB y la columna de control es `timestamp with time zone`.
- El fixture compartido verifica el umbral de seis horas, el cambio de fecha con tolerancia de 30 minutos, marcas temporales inválidas y deriva de reloj de 120/121 segundos.
- Las pruebas de Telegram confirman una petición de texto íntegra cerca del límite y que una respuesta canónica de 3.500 caracteres más la nota no excede 4.096. La prueba de voz confirma caption dentro del límite, y entrega del texto completo por el worker cuando hace falta.
- La prueba complementaria modela API antigua/nueva × worker antiguo/nuevo: se permite cero notas durante el desfase, nunca dos; en versión nueva/nueva la nota se presenta una vez cuando corresponde. La invariante principal es que el worker no escribe la nota en `payload["answer"]`.

La instancia PostgreSQL de prueba fue desechable, PostgreSQL 16.15, con base y usuario dedicados (`f4_2a_test`/`f4_test`) y puerto publicado solo en loopback (`127.0.0.1:52841`). No se usó la base de producción ni se alteraron otros contenedores.

## Despliegue y observación

El usuario confirmó el despliegue en producción. Railway confirma que el servicio `garmin-coach` en el entorno `production` está en `SUCCESS` con el commit `a7df9ea` (deployment `9bebcaf5-a1e2-451f-b863-a0da2fdd19d3`, 2026-10-12 21:24 UTC). El despliegue del worker local no se verifica mediante Railway. Antes del despliegue, el entregable 1 debía estar desplegado y `/estado` verificado. El orden previsto es API y luego worker; pausar el worker es opcional.

### Observación reportada tras el despliegue

El usuario probó `/estado`, una pregunta por voz y `/coach analiza mi entrenamiento de hoy`:

- `/estado` respondió con señales de sincronización y cola. Indicó 0 pendientes y 0 en ejecución, además de que no había consultas pendientes. La hora del pendiente más antiguo quedó como no disponible/no fiable; la última finalización correcta y el último fallo mostrados eran históricos. El propio comando aclaró que estas señales no confirman disponibilidad actual del Mac.
- La consulta por voz recibió un solo acuse (“Audio recibido… Consulta recibida…”) y una respuesta de voz aproximadamente tres minutos después, sin nota de tardanza.
- `/coach` recibió un solo acuse y contestó aproximadamente tres minutos después, sin nota de tardanza. La respuesta describió la sesión del 12/10/2026 (1:57:04, 22,01 km, ritmo calculado 5:19 min/km, FC media 141 y máxima 169) y aclaró que esos valores por sí solos no bastan para valorar esfuerzo sin zonas o sensaciones. No ofreció valoración personalizada.

Esto confirma el acuse único y entregas normales de texto/voz sin aviso de tardanza. El texto observado coincide con el renderer factual ya existente y su limitación explícita. El reporte no permite establecer el valor efectivo de `COACH_ANALYSIS_V3_ENABLED` en el worker en ese momento ni distinguir si la prosa vino de la ruta legacy normal o de su reserva; esa valoración personalizada pertenece al alcance de Fase 3 y sigue dependiendo de que esa ruta esté activada y evaluada.

No se reportó ninguna respuesta tardía natural: **no observada en producción**, cubierta por las pruebas locales. No se generarán trabajos ni mensajes artificiales en producción para probar tardanza. El despliegue y las observaciones normales de 2a quedan registrados; cualquier evaluación adicional de la respuesta personalizada se tramita en el alcance de Fase 3. El entregable 2b no debe comenzar hasta que las observaciones requeridas para 2a y sus condiciones de secuencia estén revisadas.
