# Consultas naturales del coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver consultas naturales de actividad y plan con filtros seguros de deporte, fecha y pulso máximo, evitando falsos positivos y selecciones de actividad ambiguas.

**Architecture:** El worker amplía `coach_intent` con filtros tipados e invariantes; normaliza deporte en texto y en adaptadores; conserva instante UTC, día local y procedencia por proveedor en el snapshot; y añade un hallazgo factual para `max_hr`. El contrato y la misma batería E14 se prueban desde las suites del worker y del bot; no se añaden servicios ni se modifica el enrutamiento de producción.

**Tech Stack:** Python 3, dataclasses/enums, `unittest`, fixtures JSON compartidas, suite existente de `garmin_sync` y bot.

**Spec:** `docs/superpowers/specs/2026-10-14-coach-natural-queries-design.md`

**Rama de trabajo:** `codex/coach-natural-queries`, creada desde `main` en `58f0804da0097b714bb6078d47b6a1410d60e25c`. Cada tarea termina en un commit local separado antes de empezar la siguiente; no se empuja ni despliega.

**Rama de trabajo:** `codex/coach-natural-queries`, creada desde `main` en `58f0804da0097b714bb6078d47b6a1410d60e25c`. Cada tarea termina en un commit local separado antes de empezar la siguiente; no se empuja ni despliega.

## Global Constraints

- Mantener la consulta «última» dentro de la ventana desde hoy menos 120 días hasta hoy, e informar cobertura incompleta.
- Ordenar actividades por `started_at_utc`; usar `local_date` para consultas por fecha; nunca fabricar UTC a partir de una hora ingenua.
- Normalizar bici interior, rodillo y ciclismo virtual a `cycling`; dejar tipos desconocidos como `other`.
- Zepp prioriza códigos estructurados confirmados; el título es solo fallback por palabra completa. No inventar códigos numéricos ausentes de fixtures o contrato.
- No inferir que una actividad multideporte contiene ciclismo ni dividirla sin segmentos tipados; si puede afectar «última bici», pedir confirmación.
- `sport` solo acompaña `ANALYZE_ACTIVITY`, `ANALYZE_DAY` o `CONSULT_PLAN`; `metric` solo acompaña `ANALYZE_ACTIVITY` con selector `BY_DATE` o `LATEST_ACTIVITY`.
- El conjunto cerrado de deportes consultables es `{running, cycling, swimming, strength}`; walking/mobility quedan fuera hasta tener reglas textuales y tipos de proveedor confirmados. La única métrica de actividad es `{max_hr}`.
- Las discrepancias de `max_hr` entre proveedores se presentan con todos los valores positivos y sus fuentes; no se promedian ni se ocultan.
- Para un plan con deporte pedido, filtrar sesiones etiquetadas con ese deporte; sesiones sin deporte requieren aclaración antes de atribuirlas.
- No cambiar interruptores, alias de producción, variables Railway, persistencia ni despliegues.

## Review Focus

- Un filtro/métrica incompatible con la intención se rechaza al construir el contrato, antes de análisis o renderizado.
- Las palabras `ride`/`run` dentro de otras palabras no deben clasificar títulos Zepp editables.
- Un tipo Strava diferente de `Ride` debe seguir apareciendo en resultados del deporte normalizado.
- Una actividad multideporte más reciente que la última bici conocida no debe desaparecer de la respuesta ni convertirse en ciclismo por suposición.
- Sin timestamps comparables o cobertura completa, no afirmar cuál fue la última actividad ni que no existe ninguna.
- Una consulta de plan con deporte no debe mostrar una sesión de otra disciplina ni silenciar que el plan carece de deporte.
- Un pulso teórico o medio no debe activar el hallazgo factual de pulso máximo.

## Mapa de archivos

- `apps/sync-local/garmin_sync/coach_intent.py`: filtros tipados, invariantes, extracción de deporte/métrica e interpretación de intención/fechas.
- `apps/sync-local/garmin_sync/sync.py`, `strava_activity_provider.py`, `zepp_activity_provider.py`, `activity_merge.py`: normalización por proveedor, multideporte, instante/día local y conservación de valores de origen.
- `apps/sync-local/garmin_sync/coach_generation_context.py`: snapshot inmutable con `started_at_utc`, `local_date`, contexto horario y métricas por origen.
- `apps/sync-local/garmin_sync/coach_analysis.py`: selección temporal, cobertura, ámbito por deporte y sesiones del plan.
- `apps/sync-local/garmin_sync/coach_findings.py`, `coach_generation_renderer.py`: hallazgo validado/renderizado para `max_hr` y aclaraciones factuales.
- `apps/sync-local/tests/test_coach_intent.py`, `test_coach_analysis.py`, `test_coach_generation_context.py`, `test_coach_generation_renderer.py`, `test_strava_activity_provider.py`, `test_zepp_activity_provider.py`, `test_activity_merge.py`: pruebas por componente.
- `tests/fixtures/coach_alias_e14_cases.json`, `apps/sync-local/tests/test_coach_alias_e14.py`, `apps/bot/tests/test_coach_alias_e14.py`: corpus de regresión compartido y compatibilidad con alias.

## Tareas

### Tarea 1: filtros tipados e invariantes del contrato

**Interfaces:** Añadir `SportFilter` (`running`, `cycling`, `swimming`, `strength`) y `ActivityMetric` (`max_hr`) en `coach_intent.py`. Añadir al final de `IntentComponent` los campos opcionales `sport: SportFilter | None = None` y `metric: ActivityMetric | None = None`, para no alterar llamadas posicionales existentes. Incluir ambos campos en `ContextSnapshot.public_context()`. Añadir extracción determinista de `pulsaciones máximas`, `pulso máximo` y `FC máxima`; «pulso medio» y métrica no admitida usan `UNSUPPORTED_METRIC`, y una mención teórica no activa una consulta.

- [ ] Escribir pruebas `test_sport_filter_only_allows_activity_day_or_plan_intents`, `test_metric_requires_dated_or_latest_activity_scope`, extracción de `max_hr`, aclaración de `pulso medio`, negativo teórico y códigos/plantillas; añadir serialización de filtros en `test_coach_generation_context.py`. Cubrir `CONSULT_PLAN + metric`, `RECOMMEND_NEXT + sport`, `LATEST_TRAINING_DAY + metric` y valores desconocidos.
- [ ] Ejecutar las pruebas nuevas antes de la implementación y confirmar fallos por contrato/campos ausentes, no por importación:
  ```bash
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_intent.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_generation_context.py' -v
  ```
- [ ] Implementar los enums, campos y validaciones en `IntentComponent.__post_init__`; emitir los filtros tipados en la vista pública del snapshot.
- [ ] Ejecutar `PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_intent*.py' -v` y verificar que las pruebas antiguas y nuevas pasan.
- [ ] Confirmar que los cinco códigos nuevos (`UNSUPPORTED_METRIC`, `INCOMPARABLE_ACTIVITY_TIME`, `MULTISPORT_ACTIVITY_CONFIRMATION`, `PLAN_SESSION_SPORT_UNKNOWN`, `RACE_EVENT_AMBIGUOUS`) tienen plantilla fija que no refleja texto de usuario.
- [ ] Commit local: `feat: add typed natural-query contract`.

### Tarea 2: normalización de texto y proveedores

**Interfaces:** El parser devuelve deporte normalizado en `IntentComponent.sport`; los adaptadores devuelven `sport` normalizado y mantienen el valor original en `type`. Tipos no reconocidos se conservan como `other`.

- [ ] Añadir pruebas de frases `salida en bici`, `ruta en bici`, `rodaje`, `running`, natación y `actividad de carrera`; exigir que `la carrera de Málaga` no normalice a running y que `¿qué bici me recomiendas?` y `mi pulso máximo teórico` no se conviertan en consulta de actividad/métrica.
- [ ] Añadir pruebas del mapa Strava para `RoadBiking`, `MountainBikeRide`, `IndoorCycling`, `VirtualRide`, `TrailRun`, `OpenWaterSwim` y `PoolSwim`; exigir que el filtro incluya todos los tipos normalizados aunque el nombre no sea `Ride`.
- [ ] Ejecutar esos tests antes de tocar adaptadores y confirmar que fallan por reglas de normalización ausentes.
- [ ] En Garmin, normalizar los tipos estructurados de carrera, bici, natación y `multisport`/triatlón; no inferir disciplina desde nombres de competición.
- [ ] En Zepp, consultar primero `sport_mode`/`type` usando solo códigos confirmados por fixtures/contrato (`sport_mode=7` running; `type=52` strength); probar títulos fallback con palabras completas y confirmar que `bridge` y `prune` quedan `other`. No añadir códigos numéricos especulativos.
- [ ] Añadir un test donde un código estructurado conocido contradiga el título Zepp y afirmar que prevalece el código; añadir otro donde un código desconocido usa fallback por palabra completa.
- [ ] Añadir pruebas de interior/rodillo/virtual → `cycling`, y de actividad Garmin multideporte → `multisport`; la normalización no divide segmentos.
- [ ] Ejecutar focalmente las suites del parser y los tres adaptadores:
  ```bash
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_intent.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_strava_activity_provider.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_zepp_activity_provider.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_activity_merge.py' -v
  ```
- [ ] Commit local: `feat: normalize sports in natural queries`.

### Tarea 3: timestamps, cobertura y selección de «última»

**Interfaces:** Los adaptadores y snapshot conservan `started_at_utc: str | None`, `local_date: str | None` y `time_context: str | None`. Garmin usa `startTimeGMT`/`startTimeLocal`; Strava `start_date`/`start_date_local`; Zepp epoch/zona configurada. El snapshot mantiene compatibility `date` solo si equivale exactamente a `local_date`.

- [ ] Añadir pruebas de orden UTC con offsets distintos y cruce de día local; probar horas ingenuas del mismo contexto, contextos distintos/desconocidos, timestamp ausente y empate.
- [ ] Añadir casos de selección por deporte dentro de la ventana desde `hoy - 120 días` hasta hoy; cubrir cobertura completa vacía, cobertura parcial y actividad fuera de la ventana.
- [ ] Añadir una fixture antigua sin `started_at_utc`, `local_date` ni `time_context`; demostrar que «última» se aclara sin excepción ni desempate por orden de entrada. Verificar que la siguiente sincronización completa reescribe el registro normalizado con los nuevos campos. Estos campos son adiciones al contenido sincronizado; API y bot deben ignorarlos sin error y seguir leyendo documentos antiguos. Si la sincronización no reescribe esos registros, definir un backfill antes de habilitar consultas «última».
- [ ] Añadir un caso donde un `multisport` más reciente que la bici conocida genera la aclaración acordada y no una respuesta afirmando que la bici anterior fue la última.
- [ ] Ejecutar los tests nuevos y confirmar que fallan por falta de campos/selector o política de cobertura, no por fixtures inválidos.
- [ ] Implementar los campos en los normalizadores, `activity_merge.py` y `EvidenceRecord`; Garmin toma UTC de `startTimeGMT` (nunca de `startTimeLocal`), Strava preserva `start_date` y `start_date_local`, y Zepp toma UTC de epoch/ISO con zona. Una marca Zepp ingenua solo conserva día/contexto local, no se convierte a UTC.
- [ ] Implementar selección por deporte y `started_at_utc` en `coach_analysis.py`. Responder ausencia en 120 días solo cuando la cobertura del intervalo esté confirmada; de lo contrario, comunicar el periodo real disponible.
- [ ] Ejecutar las suites focales:
  ```bash
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_analysis.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_generation_context.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_activity_merge.py' -v
  ```
- [ ] Commit local: `feat: order recent activities by reliable timestamps`.

### Tarea 4: intención actividad/plan y filtro de sesiones planificadas

- [ ] Añadir pares de pruebas: `mi última sesión de bici` vs `qué sesión tengo mañana`; `la sesión que hice ayer` vs `la sesión planificada para mañana`; y consulta nominal con actividad + deporte + fecha.
- [ ] Añadir prueba con varias actividades del deporte en una fecha y afirmar que se presentan como resultados separados, nunca como una sesión compuesta.
- [ ] Probar día del mes sin mes: análisis usa el mes actual solo si la fecha ya ocurrió, si no aclara; plan elige la próxima ocurrencia futura. Probar además conflicto entre «mañana» y fecha explícita y día sin sesión en el plan.
- [ ] Ejecutar las pruebas de intención y plan nuevas, confirmar el fallo esperado en la resolución actual.
- [ ] Actualizar `coach_intent.py` para asignar a `CONSULT_PLAN` preguntas futuras aunque incluyan deporte; conservar las reglas explícitas para actividad realizada y plan.
- [ ] Actualizar `coach_analysis.py` para filtrar por `sport` en sesiones del plan. Si una sesión carece de deporte, producir hallazgo de aclaración; si plan cubierto no tiene sesión del deporte, decirlo sin inventar.
- [ ] Probar que las sesiones de otros deportes no aparecen como respuesta a la pregunta filtrada y que una sesión sin deporte nunca se etiqueta como ciclismo.
- [ ] Ejecutar las suites focales:
  ```bash
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_intent.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_analysis.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_deterministic.py' -v
  ```
- [ ] Commit local: `feat: distinguish activity and plan queries`.

### Tarea 5: hallazgo factual `max_hr` con procedencia

El selector determinista comparte el mapa de familias de `coach_selector_v1.json`. Añadir `ACTIVITY_METRIC_VALUE` al mapa correspondiente y actualizar de forma coordinada el nombre/`protocol_version` del selector y `AnalysisSelection.schema_version`, para que el nuevo código de hallazgo quede dentro de un contrato versionado y no como una ampliación implícita.

- [ ] Añadir pruebas para el código `ACTIVITY_METRIC_VALUE`, referencias de hecho válidas, fecha/deporte correctos y renderizado con fuente; incluir múltiples actividades del día como hallazgos independientes.
- [ ] Añadir pruebas de `0`, `None`, no finito, menor de 30 y mayor de 250 lpm como valores ausentes; probar que `avg_hr` no sustituye a `max_hr` y que la petición de pulso medio aclara que solo está disponible `max_hr`.
- [ ] Extender el snapshot con métricas por registro de origen para actividades deduplicadas; probar empate, discrepancia Garmin/Strava, valor faltante en una fuente y faltante en todas.
- [ ] Ejecutar los tests nuevos y confirmar que fallan por hallazgo/procedencia ausentes antes de implementar el renderizado.
- [ ] Implementar el hallazgo determinista con referencias a todos los hechos positivos y renderizar todos los valores discrepantes con su fuente; no promediar ni elegir silenciosamente un proveedor.
- [ ] Ejecutar las suites focales:
  ```bash
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_analysis.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_deterministic.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_coach_generation_renderer.py' -v
  PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -p 'test_activity_merge.py' -v
  ```
- [ ] Commit local: `feat: report activity max heart rate with sources`.

### Tarea 6: corpus E14 y regresión integral

- [ ] Mantener sin cambios los casos canónicos `/hoy`, `/ultima` y `/feedback` de `tests/fixtures/coach_alias_e14_cases.json`; añadir las expectativas E14 de entreno de hoy, última salida y último día entrenado.
- [ ] Añadir al fixture los negativos de carrera-evento, recomendación de bici, pulso teórico, fechas discordantes, contexto horario incomparable, datos insuficientes y sesiones de plan sin deporte. Usar ruta relativa a cada archivo de test en ambas suites.
- [ ] Actualizar `apps/sync-local/tests/test_coach_alias_e14.py` y `apps/bot/tests/test_coach_alias_e14.py` para cargar el mismo JSON y verificar intent/selector/fechas/alcance, sin cambiar qué alias están activados.
- [ ] Comprobar que una transcripción de voz conocida y el mismo texto escrito llegan al mismo resolver y producen intención, filtros y fechas idénticos; no probar ni cambiar el servicio de reconocimiento de voz.
- [ ] Ejecutar `PYTHONPATH=apps/sync-local apps/sync-local/.venv/bin/python -m unittest discover -s apps/sync-local/tests -v` y `cd apps/bot && .venv/bin/python -m unittest discover -s tests -v`.
- [ ] Revisar `git diff --check`, confirmar que no cambiaron variables/interruptores ni se tocó producción, y resumir cualquier paráfrasis E14 que siga sin resolver como limitación observada.
- [ ] Commit local: `test: cover natural coach queries and E14 regressions`.

## Criterio final

Los seis grupos de tareas pasan; las consultas aceptadas devuelven solo evidencias del deporte, fecha, métrica y fuente correspondientes; ambigüedades reciben aclaraciones concretas. El trabajo permanece en la rama local `codex/coach-natural-queries`, sin push, merge, cambio de configuración ni despliegue.
