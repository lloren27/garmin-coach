# Fase 4, entregable 1: ayuda, registro y estado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. La alternativa es superpowers:subagent-driven-development si el usuario elige delegación.

**Goal:** Ofrecer ayuda breve, navegación textual de registros y un estado útil de proveedores y cola, sin modificar datos ni el enrutamiento deportivo.

**Architecture:** La presentación vive en un módulo pequeño del bot, con funciones puras. Un lector de cola devuelve agregados filtrados por chat, calculados en SQL para PostgreSQL y sobre el fichero completo para JSON; la presentación calcula tiempos con un reloj explícito. `main.route_message` conecta esas funciones antes de las rutas actuales, que se conservan.

**Tech Stack:** Python del entorno `apps/bot/.venv`, unittest, FastAPI, psycopg 3, PostgreSQL 16 desechable. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-11-fase4-experiencia-design.md`, revisión 6. Este plan implementa exclusivamente el entregable 1.

## Global Constraints

- Europe/Madrid para fechas visibles; funciones puras reciben `now` consciente de zona.
- Ayuda, `/registro` y `/estado` no crean trabajos, registros ni cambios de esquema y no dependen de interruptores.
- No añadir avisos, temporizadores, reintentos, notas tardías ni campos nuevos en este entregable; pertenecen a 2a/2b.
- No conectar alias al worker, eliminar opiniones locales ni cambiar V3; pertenecen al 3 y a la retirada condicionada.
- No copiar/importar el resolutor del Mac al bot. Estado de proveedores presenta hechos operativos, no interpretación deportiva.
- Mantener `/status`, `/syncinfo`, `/plan`, `/plan nuevo` y todos los comandos existentes.
- Los trabajos de otros chats y el texto de las consultas nunca llegan a la vista de estado.
- El objetivo global de fase 4 es E14 parcial; este entregable no lo alcanza ni activa producción.
- Base: cierre fase 3 `5e4880f`. Antes de ejecutar, comprobar cambios existentes y crear aislamiento según using-git-worktrees; no descartar trabajo del usuario.

## Review Focus

1. Chat ajeno o chat ausente: no exponer trabajos; prueba en tarea 1.
2. Base sin tabla, JSON ilegible o cola inaccesible: mostrar estado desconocido, no «cero pendientes» ni reparar/escribir desde una lectura; tareas 1 y 3.
3. Medianoche, cambio horario y fechas sin zona/futuras: no inventar frescura ni antigüedad negativa; tarea 3.
4. Mayúsculas, sufijos Telegram y argumentos no válidos en menús: ayuda útil sin escrituras ni cola; tarea 2.
5. Estado sin datos y proveedores parciales/fallidos: preservar fuentes y último éxito, sin volcar errores privados ni inferir que el Mac duerme; tarea 3.

## Archivos y contratos

- Crear `apps/bot/app/experience.py`: ayuda, guía de registro y formato de estado; ninguna persistencia, red ni importación del worker.
- Modificar `apps/bot/app/store.py`: lector mínimo de cola compatible con ambos backends.
- Modificar `apps/bot/app/main.py`: rutas de solo lectura y reloj para estado.
- Modificar `apps/bot/app/coach.py`: conservar `format_help()` como envoltorio del nuevo formato breve para no romper importaciones; no mover el resto de formateadores.
- Crear `apps/bot/tests/test_experience_store.py`, `test_experience_help.py`, `test_experience_status.py`.
- Modificar `README.md`: sección de uso vigente, sin prometer migraciones futuras.

`QueueSnapshot` es un `TypedDict` en `store.py` con `available: bool`, `counts: dict[str, int]` (pending/running/completed/failed/unknown), `oldest_pending_at: str | None`, `oldest_running_claimed_at: str | None`, `last_completed_at: str | None`, `last_failed_at: str | None` y `invalid_date_counts: dict[str, int]` con esas cuatro claves temporales. Las fechas válidas de salida se normalizan a ISO UTC. Si hay fechas no fiables en un grupo, se muestra su número y el extremo como «entre fechas disponibles», sin afirmar que es el extremo absoluto. Cola válida vacía tiene conteos cero; no disponible tiene `available=False` y nunca se representa como cero pendientes confirmado.

Incluye todos los tipos de trabajo del chat, también documentos. No devuelve listas de trabajos, texto, respuestas, errores ni otros chats. PostgreSQL calcula conteos y extremos en SQL, filtrando `document->>'chat_id'` con parámetro, y devuelve una sola fila agregada. No se permite descargar el historial para agregar en Python. JSON mantiene lectura completa y agregación local con el mismo resultado. La columna `status` y `created_at` tipada son autoridad en PostgreSQL; `claimed_at`/`completed_at` proceden del documento.

## Tarea 0: preparar y comprobar PostgreSQL aislado

**Files:** evidencia en `docs/restructuring/fase4_evaluacion/entregable1.md`; sin código de producto.

- [ ] Antes de tarea 1, comprobar disponibilidad del runtime de contenedores y del entorno virtual del bot. Crear una instancia PostgreSQL 16 desechable, ligada exclusivamente a loopback y con nombre/puerto libres dedicados a esta ejecución. No reutilizar contenedores o bases del usuario.
- [ ] Establecer `P03_TEST_DATABASE_URL` únicamente para esa instancia; verificar host, puerto, nombre de base, versión e identidad del contenedor. Registrar identificador del recurso creado sin credenciales. No cargar `DATABASE_URL` de producción ni ejecutar la suite si no se demuestra aislamiento.
- [ ] Ejecutar la suite base del bot desde `apps/bot`: `.venv/bin/python -m unittest discover -s tests -v`, con la variable de prueba y sin omisiones PostgreSQL. Registrar fallos previos y resolverlos antes de atribuir resultados a este entregable. Si no puede iniciarse la instancia, comunicar el bloqueo; no desplazar esta preparación al final.
- [ ] Mantener la instancia para tareas 1–4. Al terminar o interrumpir definitivamente, detener y eliminar solo los recursos creados para esta ejecución. Documentar el procedimiento de recuperación del entorno si la sesión se interrumpe.

## Tarea 1: lectura de cola de solo lectura y aislada por chat

**Files:** `app/store.py`, `tests/test_experience_store.py` dentro de `apps/bot`.

**Interfaces:** produce `load_queue_snapshot(chat_id: str, *, now: datetime) -> QueueSnapshot`. Consume `DATABASE_URL`, `AI_JOBS_FILE` y el esquema existente `coach_ai_jobs`. No invoca `ensure_schema`, `claim_next_ai_job` ni funciones de guardado.

- [ ] Leer primero los escritores `create_ai_job`, `claim_next_ai_job`, `complete_ai_job` y sus variantes PostgreSQL y el DDL de `coach_ai_jobs`. La inspección actual confirma `datetime.now(timezone.utc).isoformat()` para las tres fechas del documento y `created_at` tipada `timestamptz`; no hay evidencia de producción de fechas ingenuas. Fijar pruebas de roundtrip reales de ambos escritores (creación, recogida y finalización) que exijan zona UTC. Aceptar también `Z` y offsets ISO explícitos; no asignar UTC implícitamente a fechas sin zona. Si el código al ejecutar difiere, documentar y probar el formato constatado antes de decidir compatibilidad.
- [ ] Escribir pruebas JSON con dos chats, cinco estados, fechas UTC/offset/Z equivalentes, fecha sin zona, inválida y futura respecto de `now`. Comprobar conteos, mínimos/máximos válidos, contadores de fechas no fiables y fichero sin cambios. Chat vacío devuelve no disponible sin abrir almacenamiento. Fichero inexistente es cola vacía; JSON malformado o estructura distinta de lista es no disponible. Registros no-dict se ignoran; estados propios no reconocidos cuentan como `unknown`.
- [ ] Ejecutar desde `apps/bot`: `.venv/bin/python -m unittest discover -s tests -p 'test_experience_store.py' -v`. Debe fallar por ausencia del nuevo contrato, no por falta de infraestructura.
- [ ] Implementar tipos y lector. Para PostgreSQL, transacción de solo lectura y SELECT agregado parametrizado: conteos por estado, mínimo de creación pending, mínimo de recogida running y máximos de finalización completed/failed. Usar `CASE` antes del cast para las fechas JSON: formato ISO con zona explícita y validación con `pg_input_is_valid` de PostgreSQL 16; fecha futura se excluye del extremo y se cuenta como no fiable. No comparar cadenas ISO lexicográficamente. El parámetro `now` es el mismo usado por presentación. No devolver filas individuales ni ejecutar DDL, guardados o reclamaciones. Tabla ausente/error operativo produce no disponible; no ocultar errores de programación como cola vacía.
- [ ] Integrar con la instancia de tarea 0: preparar fixtures en setup y leer en transacción de solo lectura. Probar igualdad de agregados JSON/PostgreSQL, aislamiento por chat y tabla ausente en esquema separado. Poblar 10.000 trabajos sintéticos, incluido el pendiente más antiguo y el último éxito; verificar conteos completos, extremos y contrato de una fila sin lista histórica. Comprobar que el SQL ejecutado es agregado, no `SELECT document` para todo el chat.
- [ ] Repetir pruebas de tarea 1 con PostgreSQL: todas correctas y ninguna omitida. Comparar estados/documentos antes y después. Verificar que lectores no llaman a `ensure_schema` ni alteran archivos.
- [ ] Commit focalizado: `feat: add read-only chat queue snapshot`.

## Tarea 2: ayuda breve y registro textual

**Files:** `app/experience.py`, `app/coach.py`, `app/main.py`, `tests/test_experience_help.py`.

**Interfaces:** produce `format_help(*, detailed: bool = False) -> str` y `format_registration_help(topic: str = '') -> str` en `experience.py`. Conserva `coach.format_help() -> str` delegando a la versión breve. Produce `HELP_COMMANDS: tuple[tuple[str, str], ...]` en `experience.py`: cada par es invocación anunciada y descripción vigente; la ayuda detallada se genera desde esta constante. Dependencia unidireccional `coach.py -> experience.py`; `experience.py` no importa `coach.py` ni `main.py`, y cualquier importación de tipos de store se limita a `TYPE_CHECKING`.

- [ ] Escribir pruebas de `/help`, `/start`, `/help comandos`, `/registro` y temas `fuerza`, `molestias`, `perfil`, `pruebas`, además de mayúsculas, `/registro@MiBot` y argumentos desconocidos. Parchear creadores/guardadores y `create_ai_job` para que cualquier llamada falle. Verificar que no hacen lecturas de perfil/sync para mostrar ayuda estática.
- [ ] Ejecutar `.venv/bin/python -m unittest discover -s tests -p 'test_experience_help.py' -v` y confirmar fallo por comportamiento nuevo ausente.
- [ ] Implementar ayuda breve con seis entradas `/coach`, `/plan`, `/sync`, `/estado`, `/registro`, `/help`; incluir ejemplos de texto y voz y acceso `/help comandos`. Ayuda detallada inventaría comandos actuales, distingue consulta de plan de creación y describe alias deportivos como respuestas locales vigentes. No anuncia alias migrados ni respaldo automático. Argumentos desconocidos muestran «Uso: /help o /help comandos»; `/start` siempre muestra bienvenida breve.
- [ ] Implementar guía textual sin ejecutar comandos: fuerza usa ejemplos existentes `/fuerza iniciar A`, `/fuerza add sentadilla 60kg 8/8 rir2`, `/fuerza fin`; molestias remite a `/checkin`; perfil a `/perfil`; pruebas a `/prueba_esfuerzo`, `/pruebas`, `/aplicar_prueba`, `/corregir_prueba`, `/descartar_prueba`. No añadir botones ni estados conversacionales. Tema desconocido vuelve a opciones válidas. Reutilizar sintaxis de las ayudas existentes, sin introducir otro parser de registro.
- [ ] En `route_message`, extraer comando/argumentos como actualmente y resolver menús estáticos antes de `load_sync()`/`load_profile()`. No alterar el resto de ramas. Verificar que `/help comandos` funciona con whitespace y sufijos, que los ejemplos de escritura son instrucciones y no se ejecutan.
- [ ] Añadir test parametrizado de cada invocación de `HELP_COMMANDS`: pasarla al enrutador real con almacenamiento/cola simulados (incluidas operaciones de escritura) y afirmar que no devuelve el fallback exacto «Te leo. Usa /help para ver los comandos disponibles.». Incluir control con `/comando_inexistente` que sí devuelve ese fallback. Verificar el significado vigente de entradas clave `/plan`, `/plan nuevo`, `/feedback` y `/coach`; la mera aceptación no certifica la descripción. Probar importación en proceso limpio de `app.experience`, `app.coach` y `app.main` para descartar ciclos.
- [ ] Repetir pruebas nuevas y `test_coach_routing.py`: todas correctas; `/feedback`, `/semana`, `/proximo` siguen locales y `/plan` no escribe.
- [ ] Commit: `feat: simplify help and add registration guide`.

## Tarea 3: estado factual de proveedores y cola

**Files:** `app/experience.py`, `app/main.py`, `tests/test_experience_status.py`.

**Interfaces:** consume `load_queue_snapshot(chat_id: str, *, now: datetime) -> QueueSnapshot`; produce `format_operational_status(sync: dict | None, sync_request: dict | None, queue: QueueSnapshot, *, now: datetime) -> str`. Consume los campos ya persistidos por proveedor, no el catálogo del worker. La ruta usa exclusivamente el `chat_id` recibido. Sin chat devuelve cola no disponible y no llama al lector: nunca sustituye por `user_id` ni por un identificador genérico. La entrada pública pasa primero por el control de autorización existente del webhook: el código actual autoriza por `telegram_allowed_user_id`, no por una lista de chats; se conserva esa política sin afirmar una autorización de grupos que hoy no existe. El filtrado por chat del lector es adicional, no reemplaza la autorización.

- [ ] Escribir pruebas de formato con reloj fijo: dos pendientes, uno en ejecución, último éxito y fallo diferentes. Afirmar conteos, fecha/antigüedad del pendiente más viejo, fecha de recogida de ejecución más antigua y fechas separadas de éxito/fallo. Estado desconocido no se cuenta como éxito. Las fechas no fiables según el contrato comprobado en tarea 1 se presentan con los contadores correspondientes; los conteos permanecen correctos y nunca aparece antigüedad negativa.
- [ ] Añadir pruebas de cola vacía frente a no disponible y de fecha Madrid cerca de medianoche y durante el cambio horario del 25/10/2026. Verificar hora visible y diferencia de tiempo real calculada en UTC; no comparar datetimes locales ingenuos.
- [ ] Añadir fixtures de `payload.activity_provider_status`, `payload.wellness.provider_status` y estado de petición de sync. Para Garmin/Strava/Zepp distinguir ámbito actividades/bienestar y mostrar status, último intento/éxito y periodo cuando existen. `ok` con `records_received=0`: «sin actividad» en actividades y «sin datos» en bienestar. `partial`: «datos parciales»; `disabled`/`not_configured`: «sin configurar»; errores conocidos: «error del proveedor»; campos desconocidos/ausentes: «estado no disponible». Éxito de día anterior en Madrid se etiqueta «datos de un día anterior», sin inventar otra regla deportiva de frescura. Último éxito puede mostrarse junto a fallo actual.
- [ ] Ejecutar `.venv/bin/python -m unittest discover -s tests -p 'test_experience_status.py' -v` y confirmar fallo por función/ruta ausente.
- [ ] Implementar presentación pura. Mostrar generación y recepción separadas; nunca sustituir fecha de datos por recepción. Mostrar códigos seguros de estado, no `error`/`last_error` arbitrarios, URLs, trazas ni datos privados. Ausencia total produce información explícita, no excepción. La vista es compacta y no enumera trabajos ni actividades: conteos, señales y fechas bastan. Comprobar menos de 4096 caracteres con fixture máximo previsto.
- [ ] Conectar `/estado` antes de cargar perfil o datos deportivos innecesarios: cargar sync, petición de sync y snapshot del chat. Capturar fallos operativos de lectura para mostrar sección no disponible; no reparar almacenamiento. Argumentos no vacíos devuelven «Uso: /estado». Dejar `/status` y `/syncinfo` intactos. Aclarar que la última finalización es histórica y no demuestra disponibilidad actual del Mac.
- [ ] Añadir prueba de ruta con guardadores y reclamadores prohibidos y datos de otro chat ausentes; repetir las pruebas de tareas 1–3. Probar entrada sin chat aunque exista `user_id`: cola no disponible y lector no invocado. Probar el webhook con usuario no autorizado y `/estado`, prohibiendo cualquier llamada a lectores, enrutador y envío; devuelve el mismo rechazo silencioso actual. Probar usuario autorizado en grupo: se consulta exactamente el id negativo del grupo, nunca el id del usuario. Probar mensaje sin chat en el webhook: se ignora antes de leer. No rebajar la configuración de autorización en estos tests.
- [ ] Commit: `feat: expose provider and queue status`.

## Tarea 4: documentación y verificación del entregable

**Files:** `README.md` y, como evidencia nueva, `docs/restructuring/fase4_evaluacion/entregable1.md`.

**Interfaces:** ninguna nueva; documenta las rutas ya implementadas.

- [ ] Actualizar sección Telegram del README con ayuda breve, ejemplos de `/registro` y lectura de `/estado`. Indicar que los alias deportivos mantienen sus rutas actuales y los avisos siguen sin implementarse en este entregable. No reescribir documentación ajena al alcance.
- [ ] Revalidar identidad y aislamiento de la instancia creada en tarea 0 antes de la suite final; no crear otra ni cambiar a una URL de producción. Si hubo reinicio de infraestructura, repetir tarea 0.
- [ ] Desde `apps/bot`, ejecutar `.venv/bin/python -m unittest discover -s tests -v` con la variable de prueba: todo correcto y ninguna omisión PostgreSQL. Los tests existentes de autorización y lectura del plan deben pasar. No afirmar el antiguo total 92 como total esperado: las nuevas pruebas lo aumentan.
- [ ] Desde `apps/sync-local`, ejecutar `.venv/bin/python -m unittest discover -s tests` una vez para confirmar que la interfaz conservada no rompe la base. Ejecutar `git diff --check` y revisar que no hay código de avisos, campos de migración, resolutor duplicado ni cambios de enrutamiento deportivo.
- [ ] Guardar informe breve con comandos, resultados reales, configuración aislada, ejemplos sintéticos de ayuda/estado y límites. Verificar explícitamente las cinco clases de Review Focus. Ninguna captura ni respuesta contiene consultas de usuarios reales.
- [ ] Commit: `docs: document phase 4 read-only experience and validation`.

## Autorrevisión del plan y entrega

Cobertura: tareas 1 y 3 cubren estado y aislamiento; tarea 2 cubre ayuda/registro y compatibilidad; tarea 4 verifica persistencia y regresiones. Los avisos acotados, notas tardías, migraciones, activación de alias y ampliación del catálogo están asignados a entregables posteriores y no se ejecutan aquí. Tipos y firmas anteriores son los únicos contratos nuevos de este plan.

Recomendación de ejecución: implementar en esta sesión, en orden 0–4, porque las tareas comparten contratos pequeños y el alcance es de solo lectura. El usuario revisa este plan y elige ejecución en esta sesión o con subagentes antes de comenzar código. La revisión de rama al terminar comprobará el diff, pruebas y límites del alcance.
