# Fase 4, entregable 1: ayuda, registro y estado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. La alternativa es superpowers:subagent-driven-development si el usuario elige delegación.

**Goal:** Ofrecer ayuda breve, navegación textual de registros y un estado útil de proveedores y cola, sin modificar datos ni el enrutamiento deportivo.

**Architecture:** La presentación vive en un módulo pequeño del bot, con funciones puras. Un lector de cola devuelve una proyección mínima filtrada por chat desde JSON o PostgreSQL; la presentación calcula tiempos con un reloj explícito. `main.route_message` conecta esas funciones antes de las rutas actuales, que se conservan.

**Tech Stack:** Python del entorno `apps/bot/.venv`, unittest, FastAPI, psycopg 3, PostgreSQL 16 desechable. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-11-fase4-experiencia-design.md`, revisión 5. Este plan implementa exclusivamente el entregable 1.

## Global Constraints

- Europe/Madrid para fechas visibles; funciones puras reciben `now` consciente de zona.
- Ayuda, `/registro` y `/estado` no crean trabajos, registros ni cambios de esquema y no dependen de interruptores.
- No añadir avisos, temporizadores, reintentos, notas tardías ni campos nuevos en este entregable; pertenecen al 2.
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

La proyección `QueueJobView` es un `TypedDict` en `store.py`, con `status: str`, `created_at: str | None`, `claimed_at: str | None`, `completed_at: str | None`. No lleva texto, respuesta, errores, identificadores de chat ni contenido de audio/documentos. El lector incluye todos los tipos de trabajos del chat (también ingestión documental), porque `/estado` informa de toda su cola. Usa la columna de estado PostgreSQL como autoridad y las fechas persistidas; el filtro por `document->>'chat_id'` se aplica en SQL, no tras recuperar documentos de otros chats.

`QueueSnapshot` es otro `TypedDict`: `available: bool`, `jobs: list[QueueJobView]`. `available=False` significa que no se puede leer; una cola válida vacía produce `available=True, jobs=[]`. No se trunca silenciosamente el historial que determina conteos o último éxito.

## Tarea 1: lectura de cola de solo lectura y aislada por chat

**Files:** `app/store.py`, `tests/test_experience_store.py` dentro de `apps/bot`.

**Interfaces:** produce `load_queue_snapshot(chat_id: str) -> QueueSnapshot`. Consume `DATABASE_URL`, `AI_JOBS_FILE` y el esquema existente `coach_ai_jobs`. No invoca `ensure_schema`, `claim_next_ai_job` ni funciones de guardado.

- [ ] Escribir pruebas JSON con dos chats, estados pending/running/completed/failed, fechas ausentes y contenido privado; comprobar igualdad exacta de proyección, filtrado y fichero sin cambios. Chat vacío devuelve snapshot no disponible sin abrir almacenamiento. Fichero inexistente es cola vacía; JSON malformado o estructura distinta de lista es no disponible. Registros no-dict se ignoran; registros propios sin estado se proyectan como `unknown`.
- [ ] Ejecutar desde `apps/bot`: `.venv/bin/python -m unittest discover -s tests -p 'test_experience_store.py' -v`. Debe fallar por ausencia de la función nueva, no por dependencias del entorno.
- [ ] Implementar el lector y tipos. Para PostgreSQL usar transacción de solo lectura y SELECT parametrizado, proyectando únicamente estado/fechas de documentos del chat solicitado. Tabla ausente o error de lectura devuelve no disponible; registrar solo un código operativo seguro. No capturar errores de programación como cola vacía.
- [ ] Añadir integración con `P03_TEST_DATABASE_URL`, siguiendo los tests existentes: preparar esquema y datos sintéticos desde setup; después leer mediante una conexión de solo lectura. Comprobar igualdad con backend JSON, ausencia de writes/DDL y ninguna reclamación del trabajo. Verificar tabla ausente en un esquema de prueba separado. No tocar datos fuera de la base desechable.
- [ ] Repetir pruebas con PostgreSQL desechable; todas correctas y ninguna omitida. Comparar estados/documentos antes y después. Si PostgreSQL no está disponible, no declarar cerrada esta tarea.
- [ ] Commit focalizado: `feat: add read-only chat queue snapshot`.

## Tarea 2: ayuda breve y registro textual

**Files:** `app/experience.py`, `app/coach.py`, `app/main.py`, `tests/test_experience_help.py`.

**Interfaces:** produce `format_help(*, detailed: bool = False) -> str` y `format_registration_help(topic: str = '') -> str` en `experience.py`. Conserva `coach.format_help() -> str` delegando a la versión breve.

- [ ] Escribir pruebas de `/help`, `/start`, `/help comandos`, `/registro` y temas `fuerza`, `molestias`, `perfil`, `pruebas`, además de mayúsculas, `/registro@MiBot` y argumentos desconocidos. Parchear creadores/guardadores y `create_ai_job` para que cualquier llamada falle. Verificar que no hacen lecturas de perfil/sync para mostrar ayuda estática.
- [ ] Ejecutar `.venv/bin/python -m unittest discover -s tests -p 'test_experience_help.py' -v` y confirmar fallo por comportamiento nuevo ausente.
- [ ] Implementar ayuda breve con seis entradas `/coach`, `/plan`, `/sync`, `/estado`, `/registro`, `/help`; incluir ejemplos de texto y voz y acceso `/help comandos`. Ayuda detallada inventaría comandos actuales, distingue consulta de plan de creación y describe alias deportivos como respuestas locales vigentes. No anuncia alias migrados ni respaldo automático. Argumentos desconocidos muestran «Uso: /help o /help comandos»; `/start` siempre muestra bienvenida breve.
- [ ] Implementar guía textual sin ejecutar comandos: fuerza usa ejemplos existentes `/fuerza iniciar A`, `/fuerza add sentadilla 60kg 8/8 rir2`, `/fuerza fin`; molestias remite a `/checkin`; perfil a `/perfil`; pruebas a `/prueba_esfuerzo`, `/pruebas`, `/aplicar_prueba`, `/corregir_prueba`, `/descartar_prueba`. No añadir botones ni estados conversacionales. Tema desconocido vuelve a opciones válidas. Reutilizar sintaxis de las ayudas existentes, sin introducir otro parser de registro.
- [ ] En `route_message`, extraer comando/argumentos como actualmente y resolver menús estáticos antes de `load_sync()`/`load_profile()`. No alterar el resto de ramas. Verificar que `/help comandos` funciona con whitespace y sufijos, que los ejemplos de escritura son instrucciones y no se ejecutan.
- [ ] Repetir pruebas nuevas y `test_coach_routing.py`: todas correctas; `/feedback`, `/semana`, `/proximo` siguen locales y `/plan` no escribe.
- [ ] Commit: `feat: simplify help and add registration guide`.

## Tarea 3: estado factual de proveedores y cola

**Files:** `app/experience.py`, `app/main.py`, `tests/test_experience_status.py`.

**Interfaces:** consume `load_queue_snapshot(chat_id: str) -> QueueSnapshot`; produce `format_operational_status(sync: dict | None, sync_request: dict | None, queue: QueueSnapshot, *, now: datetime) -> str`. Consume los campos ya persistidos por proveedor, no el catálogo del worker. La ruta usa el chat recibido, o user_id como respaldo si existe; sin ambos nunca utiliza un chat genérico para leer trabajos.

- [ ] Escribir pruebas de formato con reloj fijo: dos pendientes, uno en ejecución, último éxito y fallo diferentes. Afirmar conteos, fecha/antigüedad del pendiente más viejo, fecha de recogida de ejecución más antigua y fechas separadas de éxito/fallo. Estado desconocido no se cuenta como éxito. Campos de fecha ausentes/invalidos/sin zona/futuros se muestran como no fiables; los conteos permanecen correctos y nunca aparece antigüedad negativa.
- [ ] Añadir pruebas de cola vacía frente a no disponible y de fecha Madrid cerca de medianoche y durante el cambio horario del 25/10/2026. Verificar hora visible y diferencia de tiempo real calculada en UTC; no comparar datetimes locales ingenuos.
- [ ] Añadir fixtures de `payload.activity_provider_status`, `payload.wellness.provider_status` y estado de petición de sync. Para Garmin/Strava/Zepp distinguir ámbito actividades/bienestar y mostrar status, último intento/éxito y periodo cuando existen. `ok` con `records_received=0`: «sin actividad» en actividades y «sin datos» en bienestar. `partial`: «datos parciales»; `disabled`/`not_configured`: «sin configurar»; errores conocidos: «error del proveedor»; campos desconocidos/ausentes: «estado no disponible». Éxito de día anterior en Madrid se etiqueta «datos de un día anterior», sin inventar otra regla deportiva de frescura. Último éxito puede mostrarse junto a fallo actual.
- [ ] Ejecutar `.venv/bin/python -m unittest discover -s tests -p 'test_experience_status.py' -v` y confirmar fallo por función/ruta ausente.
- [ ] Implementar presentación pura. Mostrar generación y recepción separadas; nunca sustituir fecha de datos por recepción. Mostrar códigos seguros de estado, no `error`/`last_error` arbitrarios, URLs, trazas ni datos privados. Ausencia total produce información explícita, no excepción. La vista es compacta y no enumera trabajos ni actividades: conteos, señales y fechas bastan. Comprobar menos de 4096 caracteres con fixture máximo previsto.
- [ ] Conectar `/estado` antes de cargar perfil o datos deportivos innecesarios: cargar sync, petición de sync y snapshot del chat. Capturar fallos operativos de lectura para mostrar sección no disponible; no reparar almacenamiento. Argumentos no vacíos devuelven «Uso: /estado». Dejar `/status` y `/syncinfo` intactos. Aclarar que la última finalización es histórica y no demuestra disponibilidad actual del Mac.
- [ ] Añadir prueba de ruta con guardadores y reclamadores prohibidos y datos de otro chat ausentes; repetir las pruebas de tareas 1–3. Probar entrada sin chat ni usuario: no consultar cola ajena.
- [ ] Commit: `feat: expose provider and queue status`.

## Tarea 4: documentación y verificación del entregable

**Files:** `README.md` y, como evidencia nueva, `docs/restructuring/fase4_evaluacion/entregable1.md`.

**Interfaces:** ninguna nueva; documenta las rutas ya implementadas.

- [ ] Actualizar sección Telegram del README con ayuda breve, ejemplos de `/registro` y lectura de `/estado`. Indicar que los alias deportivos mantienen sus rutas actuales y los avisos siguen sin implementarse en este entregable. No reescribir documentación ajena al alcance.
- [ ] Disponer de PostgreSQL 16 desechable antes de validar integración. Usar exclusivamente `P03_TEST_DATABASE_URL` apuntando a esa instancia local; comprobar identidad/aislamiento antes de ejecutar. No usar la URL del servicio real. Iniciar y eliminar solo recursos creados para esta verificación, conforme al procedimiento de fase 3.
- [ ] Desde `apps/bot`, ejecutar `.venv/bin/python -m unittest discover -s tests -v` con la variable de prueba: todo correcto y ninguna omisión PostgreSQL. Los tests existentes de autorización y lectura del plan deben pasar. No afirmar el antiguo total 92 como total esperado: las nuevas pruebas lo aumentan.
- [ ] Desde `apps/sync-local`, ejecutar `.venv/bin/python -m unittest discover -s tests` una vez para confirmar que la interfaz conservada no rompe la base. Ejecutar `git diff --check` y revisar que no hay código de avisos, campos de migración, resolutor duplicado ni cambios de enrutamiento deportivo.
- [ ] Guardar informe breve con comandos, resultados reales, configuración aislada, ejemplos sintéticos de ayuda/estado y límites. Verificar explícitamente las cinco clases de Review Focus. Ninguna captura ni respuesta contiene consultas de usuarios reales.
- [ ] Commit: `docs: document phase 4 read-only experience and validation`.

## Autorrevisión del plan y entrega

Cobertura: tareas 1 y 3 cubren estado y aislamiento; tarea 2 cubre ayuda/registro y compatibilidad; tarea 4 verifica persistencia y regresiones. Los avisos acotados, notas tardías, migraciones, activación de alias y ampliación del catálogo están asignados a entregables posteriores y no se ejecutan aquí. Tipos y firmas anteriores son los únicos contratos nuevos de este plan.

Recomendación de ejecución: implementar en esta sesión, en orden 1–4, porque las tareas comparten contratos pequeños y el alcance es de solo lectura. El usuario revisa este plan y elige ejecución en esta sesión o con subagentes antes de comenzar código. La revisión de rama al terminar comprobará el diff, pruebas y límites del alcance.
