# Fase 4 — entregable 1

## Tarea 0

Base de ejecución: e9acdb0. Docker 29.8.2 disponible; imagen postgres:16 existente.
Contenedor exclusivo: garmin-coach-f4-e1-test, id 0c40f534bf710774ddc6e6b77744e8b064d887fdd863aa2ae62e74775b83d22e.
Enlace verificado: 127.0.0.1:64392. Base f4_e1_test, usuario f4_test, PostgreSQL 16.15.
No se usó producción ni se modificó el contenedor Wattwise existente.

Suite base: desde apps/bot, con P03_TEST_DATABASE_URL dirigido únicamente a la base anterior,
`.venv/bin/python -m unittest discover -s tests -v`: 92 pruebas correctas, ninguna omitida.
El sandbox bloqueó inicialmente el socket Docker; la ejecución autorizada con permisos ampliados funcionó.
Advertencia preexistente: deprecación Starlette del TestClient de httpx.

El entorno virtual existente se reutiliza por su ruta absoluta desde el worktree. No se instalan dependencias.
La instancia permanecerá solo durante esta ejecución; si la sesión se interrumpe, comprobar id y etiqueta codex.task antes de recuperarla o eliminarla.
