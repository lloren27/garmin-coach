# Fase 4, entregable 3 — adaptador de alias con requisito V3 — Plan de implementación

> **Para agentes de implementación:** Habilidad requerida: `superpowers:executing-plans` (ejecución nativa o por subagentes, a elegir tras revisar este plan). Trabajar en la rama local `codex/fase4-3`, creada desde `main` en `d716acf57eb16f569425d8079b7e08ec0e1ff967`, que ya contiene 1, 2a y 2b desplegados. Mantener los cambios locales; esta rama no se publica ni se fusiona en este entregable. Completar las tareas en orden y marcar las casillas.

**Goal:** Implementar una migración reversible de `/hoy`, `/ultima` y `/feedback` desde las respuestas deportivas locales a trabajos del coach V3, sin activar automáticamente el cambio ni perder las rutas actuales de respaldo.

**Architecture:** La API conserva los handlers locales y añade un adaptador de allowlist, controlado por `COACH_ALIAS_ROUTING_ENABLED` (apagado por defecto, separado de `COACH_ANALYSIS_V3_ENABLED`). El adaptador conserva argumentos y calcula solo el ámbito factual predeterminado; no duplica ni importa `coach_intent`. Los trabajos migrados incluyen un requisito explícito y versionado de motor V3 en el documento persistido. El worker del Mac entiende y verifica el requisito antes de generar; si no puede cumplirlo, no llama a Ollama ni a otra ruta antigua y devuelve un fallo de incompatibilidad que la API presenta con la vista factual existente. Las vistas y alias no migrados permanecen deterministas. La activación productiva de V3, alias y avisos, y la retirada de ramas locales quedan fuera de esta implementación y coordinadas con fase 5.

**Tech Stack:** Python 3, FastAPI, almacenamiento JSON/PostgreSQL existente, worker `garmin_sync`, `unittest`/pytest según suite. Sin servicio nuevo ni dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-11-fase4-experiencia-design.md`, decisión 2, capacidades por alias, traducción y contexto, entregables 3–4 y criterio E14.

## Global Constraints

- `COACH_ALIAS_ROUTING_ENABLED` apagado o ausente conserva exactamente los handlers locales vigentes. Un valor inválido no activa el adaptador; registrar claramente la configuración inválida sin impedir que la API inicie.
- El interruptor solo controla el allowlist probado `/hoy`, `/ultima`, `/feedback`. No implica ni activa `COACH_ANALYSIS_V3_ENABLED`, los avisos 2b, ni otros alias. Ninguna variable copiada a Railway demuestra el estado del worker.
- Antes de habilitar el adaptador en cualquier entorno compartido, desplegar y verificar primero el worker que respeta el requisito V3. Antes de activación productiva también deben estar acreditados V3 real evaluado, E14 por alias, avisos operativos y rollback; coordinarlo con fase 5. Este plan no toca variables ni hace despliegues.
- Prerrequisito productivo pendiente de evidencia: comprobar mediante el runbook de 2b que las cuatro columnas de aviso y su restricción existen en PostgreSQL de producción, que se preservaron los trabajos existentes y que `COACH_DELAY_NOTICE_SECONDS` está vacío/0. La ausencia de esa variable deja el barrido apagado por defecto, pero no demuestra la migración de esquema; no activar avisos ni alias hasta registrar verificación de las cuatro columnas.
- Mantener una ruta anterior efectiva para revertir: apagar el interruptor devuelve entradas nuevas a los handlers locales; los trabajos ya encolados conservan `required_engine=v3`, no se duplican ni se degradan a Ollama. No borrar ni retirar esas ramas en este entregable.
- El contrato persistido debe tolerar documentos antiguos sin metadato. Elegir una única clave (`required_engine`, valores actuales `v3` o ausente), documentarla y probar lectura/escritura en JSON y PostgreSQL; no guardar otro alias de compatibilidad redundante.
- Para `/hoy`, `/ultima`, `/feedback` sin argumentos, fijar el ámbito factual `today`, `latest_activity` y `latest_training_day`, respectivamente, con reloj `Europe/Madrid`. Con argumentos, enviar al worker el texto original completo del usuario tal cual (incluidos alias y argumentos), sin añadir frase canónica; el worker resuelve o pide aclaración, y aviso/fallback usa `latest_available`. La API no interpreta argumentos ni fechas.
- Los tres alias se aprueban con sus preguntas canónicas exactas: intención, selector, fechas, hechos, límites, utilidad y ausencia de permisos de escritura. Las paráfrasis humanas son una evaluación separada del resolutor de texto libre: si fallan, se registran como limitación y trabajo futuro de `coach_intent`; ese fallo por sí solo no bloquea alias canónicos ni amplía esta fase. No relajar ni alterar el auditor E14; reportar equivalencia parcial y limitaciones por separado.
- No ampliar V3 con opiniones sobre carga, fatiga, tendencia, potencia o balance semanal en esta fase. Otros alias mantienen su vista determinista actual; `/ajustar`, `/plan`, `/plan_semana`, registros, voz libre y `/coach` no cambian de ruta por este interruptor.
- Las consultas migradas siguen usando el acuse único y los avisos ya implementados en 2a/2b. Un alias no crea otro mensaje de “procesando”. Fallback y avisos muestran fechas/fuentes/antigüedad, sin incorporarse como una opinión adicional al contexto del coach.
- Ejecutar persistencia únicamente contra PostgreSQL desechable. No usar datos reales de entrenamiento en evidencia; registrar solo identidades, recuentos, resultados y versiones.

## Review Focus

- Interruptor ausente/apagado e inválido: respuesta local anterior idéntica; activo: solo tres alias elegibles crean un trabajo con requisito V3.
- Worker antiguo/nuevo simulado y requisito ausente/V3/desconocido: nunca degradar silenciosamente un trabajo que exige V3; un contrato desconocido se rechaza de forma segura.
- Un fallo de compatibilidad se explica al usuario con vista factual y no deja la consulta sin respuesta ni genera opinión del motor antiguo.
- Paráfrasis humanas y texto generado por alias resuelven intención, selector y fechas esperados con una misma instantánea/reloj; fechas explícitas, cambio de día en Madrid, argumentos contradictorios y ambigüedad no se descartan.
- El ámbito de respaldo solo afecta a la vista factual; no cambia la pregunta, el contexto del coach ni el resultado estructurado.
- Apagar el interruptor permite rollback inmediato para consultas nuevas y no reencola, duplica ni altera trabajos pendientes.
- `/estado` presenta el `output_source` permitido del último trabajo completado de ese chat, sin pregunta/respuesta ni datos de otros chats; el runbook exige observar `deterministic` (V3) en un trabajo real antes de habilitar alias.
- Ayuda y `/help comandos` describen el modo activo y no anuncian migraciones apagadas.

## Tareas

### Tarea 0: fijar el contrato y establecer pruebas rojas del estado actual

**Files:** Crear/actualizar `apps/bot/tests/test_coach_alias_adapter.py`, `apps/sync-local/tests/test_coach_alias_compatibility.py`, y los casos E14 compartidos bajo `tests/fixtures/` si no existe ya un fixture adecuado.

- [ ] Leer el enrutamiento actual de `apps/bot/app/main.py`, las frases en `apps/bot/app/coach.py`, la vista factual en `apps/bot/app/experience.py`, el contrato de trabajos en `apps/bot/app/store.py` y el flujo de `process_job`/`call_coach` en `apps/sync-local/garmin_sync/ai_worker.py`.
- [ ] Añadir pruebas de caracterización para cada ruta local actual, incluidas entradas con argumentos, y para el comportamiento de V3 apagado/encendido del worker. Confirmar los nombres reales de las suites y comandos del repo; no cambiar producción para hacer pasar estas pruebas.
- [ ] Crear una matriz compartida versionada de casos E14 con las tres frases canónicas como gate de aprobación de alias. Incluir además las paráfrasis «¿Cómo fue mi entreno de hoy?», «Dame tu opinión sobre la última salida» y «¿Qué tal el último día que entrené?» como evaluación diagnóstica separada de texto libre. Incluir fecha fija, instantánea sintética, intención/selector/fechas esperadas, evidencia requerida, límite de conclusión y respuesta/clarificación aceptable.
- [ ] Incluir fechas explícitas, variación del reloj local de Madrid, casos con argumentos (`/hoy ayer`, `/ultima mañana`, `/feedback 3 de octubre`), negación, ambigüedad, ausencia de actividad, varios deportes y datos insuficientes. Para comandos con argumentos, afirmar que se envía el texto original sin anexar la frase canónica. Cargar el fixture con ruta relativa al archivo de test en ambas suites.
- [ ] Ejecutar pruebas de caracterización y confirmar que las nuevas pruebas de adaptador/compatibilidad fallan por ausencia de implementación, no por importaciones o fixtures inválidos.

### Tarea 1: construir el adaptador allowlisted y controlar su interruptor

**Files:** Crear `apps/bot/app/coach_alias_adapter.py`; actualizar `apps/bot/app/config.py`, `apps/bot/app/main.py`, `apps/bot/app/experience.py`; actualizar pruebas de API y ayuda.

- [ ] Escribir primero tests para normalización de comandos Telegram (mayúsculas y sufijo `@bot`), conservación de argumentos, allowlist exacto, interruptor apagado/activo/inválido y reloj inyectable en `Europe/Madrid`.
- [ ] Implementar configuración independiente `COACH_ALIAS_ROUTING_ENABLED`, apagada por defecto; valor inválido se registra al iniciar y queda apagado sin tumbar la API.
- [ ] Implementar función pura de adaptación que devuelva alias, pregunta y scope sin leer base, resolver intención ni crear datos. Sin argumento usar las frases candidatas exactas de la especificación: `/hoy` → «Analiza mi entrenamiento de hoy.»; `/ultima` → «Analiza mi última actividad.»; `/feedback` → «Analiza mi último día de entrenamiento.» y scopes `today`, `latest_activity`, `latest_training_day`. Con argumentos, enviar el texto original completo (`/hoy ayer`, `/ultima mañana`, `/feedback 3 de octubre`) sin añadir frase canónica; usar scope `latest_available` para aviso/fallback y dejar al worker resolver o aclarar.
- [ ] Integrar el adaptador antes de los handlers deterministas únicamente para los tres comandos permitidos y solo con el interruptor activo. Con interruptor apagado, preservar salida y consultas a datos actuales idénticas a las de caracterización.
- [ ] Añadir el requisito V3 al documento de trabajo únicamente para una ruta adaptada elegible. No cambiar forma ni contenido de trabajos de `/coach`, voz, `/ajustar` u otras rutas.
- [ ] Probar que no hay escritura de registros, cambios de plan, cambios de perfil ni autorización de propuesta a partir de texto generado por el adaptador.

### Tarea 2: persistir el ámbito factual y presentar incompatibilidad con respaldo

**Files:** Actualizar `apps/bot/app/store.py`, `apps/bot/app/queue_status.py`, `apps/bot/app/main.py`, `apps/bot/app/experience.py`, migración/compatibilidad de trabajos en ambos backends y sus tests PostgreSQL/archivo.

- [ ] Test-first: comprobar creación y round-trip de `required_engine` y `factual_scope` en JSON y PostgreSQL desechable; documentos antiguos sin ambos campos siguen legibles y los escritores no los borran al completar/reclamar.
- [ ] Añadir metadatos opcionales al contrato persistido. `required_engine` es el único requisito de motor; guardar `factual_scope` para los alias migrados incluso si llevan argumentos (en ese caso `latest_available`). Sin argumentos persiste `today`, `latest_activity` o `latest_training_day`, según corresponda.
- [ ] Ajustar el barrido de avisos de 2b para leer `factual_scope` del documento del trabajo y generar su respaldo con el mismo ámbito. Si falta/no es válido, usar `latest_available`. Es dato documental JSONB; no añadir columnas ni ampliar el conjunto de funciones que accede a las cuatro columnas de coordinación.
- [ ] En el endpoint de finalización, mapear un código estable de incompatibilidad del worker a un mensaje seguro y una vista factual fechada adecuada. No convertir el trabajo fallido en respuesta V3 ni volver a encolarlo. Reutilizar el formateador factual existente, que permanece fuera del contexto de generación.
- [ ] Extender `/estado` para mostrar el `output_source` del último trabajo completado del mismo chat, con una etiqueta explícita para `deterministic` como respuesta V3. No traer texto de consulta/respuesta ni leer trabajos de otros chats. Mantener el agregado SQL acotado (subconsulta ordenada con límite) y la lectura JSON actual. Añadir tests de privacidad, trabajos antiguos sin origen y aislamiento de chats.
- [ ] Probar los tres scopes y `latest_available`, incluidos aviso demorado y fallo de incompatibilidad con el mismo scope, datos ausentes/frescos, sincronización desconocida, fecha de observación y fuente, autorización de chat y que el texto original de consulta no se expone en el fallback.
- [ ] Probar que el trabajo encolado antes de rollback se procesa solo bajo su requisito V3, sin duplicación y sin ejecución por Ollama.

### Tarea 3: hacer cumplir el requisito en el worker y verificar la matriz de versiones

**Files:** Actualizar `apps/sync-local/garmin_sync/ai_worker.py` y pruebas de compatibilidad del worker; actualizar pruebas de finalización en `apps/bot/tests/`.

- [ ] Test-first: `required_engine` ausente mantiene compatibilidad histórica; `v3` solo se ejecuta con V3 habilitado; motor V3 deshabilitado devuelve incompatibilidad explícita antes de contexto/modelo; valores desconocidos se rechazan con error seguro. Afirmar que una incompatibilidad no llama a la ruta antigua de Ollama ni a su fallback generativo.
- [ ] En `process_job`, validar el requisito antes de descarga/transcripción/contexto cuando aplique. Para trabajos que exigen V3, no pasar por la ruta antigua de Ollama ni por su fallback generativo; completar con un código de error estable que la API entienda. No prohibir Ollama si una futura etapa interna permitida de V3 lo usa para seleccionar hallazgos; registrar esa etapa sin confundirla con `output_source`.
- [ ] Probar API nueva/worker nuevo, API nueva/worker antiguo modelado, API antigua/worker nuevo y marcha atrás API tras activar: cero notas/avisos duplicados y cero trabajos procesados silenciosamente con motor incorrecto. La matriz es complementaria; la aserción principal es que una ruta que requiere V3 nunca invoca Ollama y que solo hay una finalización por job id.
- [ ] Probar que versión API vieja ignora de forma segura metadatos nuevos al leer documentos; versión de worker que no reconoce el contrato nunca se considera apta para activación. Registrar que la matriz de versiones se modela con presentadores/workers de compatibilidad en test, no levantando checkouts antiguos.
- [ ] Confirmar orden de despliegue en el runbook: worker compatible primero y verificado; API con adaptador apagado después; activación de alias solo al cumplir prerrequisitos de fase 5.

### Tarea 4: superar E14 por capacidad y conectar la experiencia final

**Files:** Actualizar `apps/bot/app/coach_alias_adapter.py`, ayuda en `apps/bot/app/experience.py`, pruebas E14 del bot/worker y `docs/restructuring/fase4_evaluacion/entregable3.md`.

- [ ] Ejecutar cada frase canónica de alias con la misma instantánea y reloj. Comparar intención, selector, fechas resueltas, hechos estructurados, límites y utilidad; no comparar solo el texto generado contra sí mismo. Ejecutar aparte las paráfrasis humanas por texto, `/coach` y transcripción de voz simulada para caracterizar el resolutor; una paráfrasis fallida se documenta, pero no bloquea alias canónicos.
- [ ] Para cada alias, verificar las salidas y hallazgos disponibles de la especificación: `/hoy` análisis del día con límites de recuperación/recomendación; `/ultima` análisis de actividad y comparación con plan sin inferir cumplimiento ambiguo; `/feedback` último día de entrenamiento, deportes separados, bienestar y síntomas. Identificar toda falta de soporte como resultado no aprobado, no simular una recomendación.
- [ ] Si una frase canónica de alias no satisface E14, dejar ese alias fuera del allowlist productivo y documentar limitación/clarificación. Si falla una paráfrasis, registrar la limitación del resolutor como trabajo futuro sin bloquear los alias canónicos ni ampliar `coach_intent` en esta entrega.
- [ ] Actualizar `/help`, `/start` y `/help comandos` para que expliquen los tres alias y su comportamiento según el modo activo, sin anunciar un alias migrado antes de la activación. Verificar el router para cada comando de ayuda listado.
- [ ] Confirmar que `/semana`, `/proximo`, `/fatiga`, `/carga`, `/tendencia`, `/salud`, `/running`, `/bici`, `/potencia`, `/wattwise`, `/malaga`, `/ajustar`, `/plan` y registro conservan su flujo descrito por la especificación; vistas factuales no invocan modelo ni contienen valoración antigua presentada como nueva.
- [ ] Registrar evidencia de E14 parcial esperado: solo alias que superaron las pruebas cuentan como migrados; resto como vista factual o candidato retenido. Mantener criterio global histórico de equivalencia incumplido.

### Tarea 5: regresiones, rollback y cierre local

**Files:** Revisar cambios de `apps/bot/`, `apps/sync-local/`, y evidencia `docs/restructuring/fase4_evaluacion/entregable3.md`; actualizar runbook de despliegue de 2b si existe uno consolidado.

- [ ] Ejecutar suites focalizadas del adaptador, contratos de trabajo, endpoint de finalización, vistas factuales, intención/selector y worker; después suites completas del bot (incluida PostgreSQL desechable sin omisiones) y worker, además de regresiones fase 3 y E15a/b.
- [ ] Añadir pruebas de apagado del interruptor con consultas entrantes, jobs ya encolados, configuración inválida, ausencia de V3, worker incompatible, timeout/fallo del worker y consulta con argumentos. `/estado` continúa mostrando cola y avisos existentes sin texto privado.
- [ ] Ejecutar `git diff --check`, revisar que no se haya alterado el criterio E14 para obtener aprobación, no haya borrado de rutas locales, no cambien variables de producción ni se realicen despliegues.
- [ ] Escribir un runbook operativo con orden de despliegue worker compatible → API con adaptador apagado → comprobar en `/estado` un trabajo real con `output_source=deterministic` → verificar migración 2b (cuatro columnas y restricción, trabajos preservados, avisos vacíos/0) → evidencia de E14 y avisos → recalibración de latencia → activación gradual explícita → comprobación → rollback por interruptor. La verificación de esquema debe provenir de una consulta de solo lectura o evidencia operativa autorizada; la integración Railway consultada no ofrece acceso SQL. Si no se puede confirmar, prerrequisito pendiente. Documentar que 4-3 no activa ni despliega producción.
- [ ] Evidencia solo con versiones/SHA, configuración enmascarada, identidades de base/fixtures y recuentos. No incluir preguntas, respuestas ni datos de entrenamiento restaurados.
- [ ] Commit local por tarea completada en `codex/fase4-3`, con mensajes claros. No hacer push, merge a `main`, cambiar variables de Railway ni retirar las rutas locales.

## Autorrevisión

El plan mantiene apagado el cambio en producción, cubre el contrato de compatibilidad API/worker, la selección factual compartida por aviso/fallback, la señal de origen para `/estado` y rollback sin duplicar trabajos. La aprobación E14 se mide con las frases canónicas de los tres alias; las paráfrasis se evalúan y reportan aparte como limitaciones del resolutor si fallan. La consulta Railway confirmó que `COACH_DELAY_NOTICE_SECONDS` no está definida, por lo que se aplica el valor apagado por defecto, pero no permite consultar PostgreSQL. La evidencia 2b aún dice que la migración no se aplicó en producción; las cuatro columnas quedan como prerrequisito sin verificar. La activación productiva y la retirada de rutas locales quedan fuera de 4-3 y requieren evidencia y coordinación con fase 5.
