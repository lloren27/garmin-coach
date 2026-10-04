# Cómo reproducir la auditoría

Los artefactos del 3 de octubre se conservan en `ejecuciones/`. Las repeticiones
del 4 de octubre viven en subcarpetas fechadas. Una nueva ejecución requiere un
nombre distinto y se niega a sobrescribir resultados existentes.

Ejecutar desde la raíz del repositorio con el Python instalado del worker:

```sh
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/evaluar.py --run=mi-fecha-determinista
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/pruebas_ampliadas.py --run=mi-fecha-ampliadas
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/evaluar.py --ollama --run=mi-fecha-ollama
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/ejecutar_suite.py bot --run=mi-fecha-suites
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/ejecutar_suite.py worker --run=mi-fecha-suites
```

Los entornos del bot y worker deben estar instalados. El evaluador reutiliza las
dependencias exclusivas del bot desde su entorno; no instala ni cambia paquetes.
Las pruebas del producto usan ficheros temporales. Los casos nuevos fijan el
tiempo en `2026-10-03T22:00:00+02:00`; las suites históricas mantienen sus relojes
originales y pueden mostrar pruebas frágiles dependientes del día actual.

## Ollama

`--ollama` requiere acceso a `127.0.0.1:11434` y al modelo `garmin-coach:9b`.
Ejecuta E01, E07, E08, E09, E10 y E13 tres veces cada uno. Usa el generador real
del worker y su selección de presupuesto (900 o 1.400 tokens), con una fecha
fija en el pipeline. Guarda peticiones y respuestas sintéticas, validaciones,
reparaciones y tiempos. No reclama trabajos del backend ni envía mensajes.

En un entorno restringido, se debe obtener el permiso de conexión local antes
de ejecutar las pruebas. Un `ConnectError` no demuestra que Ollama esté caído.
La comparación del 4 de octubre usa los valores predeterminados del código,
coincidentes con la configuración local saneada; no atestigua el entorno de un
proceso ya arrancado. El digest del modelo queda en
`ejecuciones/2026-10-04-servicios.json`.

Una salida válida aún requiere revisión manual con la rúbrica del plan. Los
resultados crudos no se reescriben tras puntuar: la evaluación se registra por
separado. `comprobar_respuestas.py` resume las 18 ejecuciones del 4 de octubre y
comprueba cifras/conversiones; no decide si el consejo es útil o correcto.

## PostgreSQL aislado

El 4 de octubre se reutilizó la imagen local `postgres:17-alpine` para crear
`garmin-audit-fase0-20261004`, base `garmin_audit`, datos en tmpfs, sin volumen
persistente y con puerto aleatorio ligado a `127.0.0.1`. El puerto asignado fue
53982. Se ejecutó:

```sh
apps/sync-local/.venv/bin/python -B docs/restructuring/fase0_resultados/ejecutar_suite.py bot --run=2026-10-04-suites --audit-db-port=53982
```

El contenedor ya está detenido y fue eliminado por `--rm`; sus datos eran
exclusivamente sintéticos. Para repetir hay que crear otro contenedor temporal,
usar su puerto y retirarlo al terminar. No reutilizar ese número sin comprobar
el destino. El evaluador construye exclusivamente la URL local de `garmin_audit`,
sin aceptar una URL de producción.

## Límites

- La guardia Python impide los accesos del evaluador conocido; no es un sandbox
  contra código nativo malicioso. Se registran los intentos bloqueados.
- `/health` se consulta en lectura. No se llama a `/ai/jobs/next`, que reclama
  trabajos, ni a loaders que podrían preparar el esquema remoto.
- Los casos E05 y E16 básicos solo cubren subcomprobaciones; los resultados
  ampliados cubren la reconsulta Zepp y el sueño durante el cambio horario.
- No ejecutar `preparar_casos.py` ni `inspeccionar.py` para repetir mediciones:
  recrean la referencia inicial. Usar las entradas existentes y un nombre nuevo.
