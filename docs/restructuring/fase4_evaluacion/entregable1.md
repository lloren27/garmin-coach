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

## Entregable 1 — comprobaciones de experiencia

Implementación en la rama `codex/fase4-experiencia`. `/help`, `/start`, `/registro`
y `/estado` son rutas de lectura. La vista de cola usa agregados SQL para PostgreSQL
y recorre el JSON para archivos; la proyección no incluye contenido ni otros chats.
La lectura PostgreSQL no ejecuta DDL. `HELP_COMMANDS` alimenta `/help comandos` y
una prueba prueba cada entrada en el enrutador.

Comandos verificados (desde apps/bot, intérprete del venv del checkout original):

- `.venv/bin/python -m unittest discover -s tests -p 'test_experience*.py'`: 21 OK,
  con `P03_TEST_DATABASE_URL` apuntando al contenedor desechable.
- `.venv/bin/python -m unittest discover -s tests -v`: 113 OK, sin omisiones PostgreSQL.
- Desde apps/sync-local: `.venv/bin/python -m unittest discover -s tests`: 288 OK.
- Suite base anterior a cambios: bot 92 OK, sin omisiones PostgreSQL.

Los estados sintéticos cubren tabla no disponible, proveedor parcial/sin
configurar y recuento ausente, fechas inválidas/antiguas/extremas, horarios de
Madrid, autorización por usuario y aislamiento del chat de grupo. La consulta
PostgreSQL devuelve una fila agregada incluso con 10.009 trabajos sintéticos. La respuesta no enumera trabajos.
Starlette muestra una advertencia preexistente deprecando el uso de httpx con
TestClient. Logs de validación de contratos son esperados por pruebas existentes.

No se ejecutó ninguna prueba contra datos o infraestructura de producción. No se
probaron aún el barrido, avisos, migración de esquema, nota tardía ni alias V3;
son entregables posteriores. El modo de archivos no ofrece agregación acotada y
lee su JSON completo. Una cola PostgreSQL sin tablas se muestra no disponible. La revisión independiente
reprodujo y llevó a corregir dos casos: offsets que excedían años representables
y proveedores `ok` sin recuento. Las pruebas nuevas pasan. La revisión final
completa mediante agente no estuvo disponible por límite de uso; se hizo una
revisión propia final del diff, por lo que la independencia restante es menor.
