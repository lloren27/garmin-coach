# Fase 4 — evidencia del entregable 2a

**Estado:** implementación local completada y suites verificadas. No desplegado ni observado en producción.

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

Este entregable todavía no está desplegado. Antes de desplegarlo, el entregable 1 debe estar desplegado y `/estado` debe haberse verificado. El orden previsto es API y luego worker; pausar el worker es opcional. Después se observarán el acuse único, una respuesta normal sin nota y la voz en operación normal.

No se generarán trabajos ni mensajes artificiales en producción para probar tardanza. Si no ocurre una respuesta tardía de forma natural, se registrará como **no observado en producción**, cubierta por las pruebas locales. El entregable 2b no debe comenzar hasta que el despliegue y la observación de 2a queden registrados y revisables.
