# Fase 2 — Resolución de intención y fechas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolver de forma segura el ámbito temporal y los permisos de una consulta del coach, ofreciendo solo una pista de intención cuando las palabras no sean concluyentes.

**Architecture:** `coach_intent.py` será un módulo puro. Resolverá fechas con `datetime.date` y `Europe/Madrid`, detectará solicitudes de cambio solo con verbo y objeto explícitos, y devolverá componentes ordenados. Análisis y consejo se clasificarán como pistas deterministas cuando haya señales suficientes; si no, el componente será `clarify` y el entrenador recibirá un cauce de reserva. Una solicitud de cambio solo autoriza generar una propuesta, nunca aplicarla.

**Tech Stack:** Python 3.13, dataclasses, enums, `datetime`/`zoneinfo`, `unittest`.

**Spec:** [restructuring_fase2_v1.md](../../restructuring/restructuring_fase2_v1.md), sección 3 y Tarea 1, refinada por la revisión de alcance de esta tarea.

## Global Constraints

- La API es `resolve_intent(question: str, *, now: datetime) -> IntentResolution`.
- `now` debe tener zona horaria; un `datetime` ingenuo lanza `ValueError` antes de analizar el texto.
- Todas las fechas públicas son `datetime.date`; solo los adaptadores formatean ISO.
- La fecha local se calcula convirtiendo primero `now` a `Europe/Madrid`; «ayer» y «mañana» operan sobre esa fecha, no sobre intervalos de 24 horas.
- La semana comienza el lunes y «esta/próxima/semana pasada» usa semanas calendario de lunes a domingo. En análisis, «esta semana» solo incluye fechas hasta hoy; en plan/consejo incluye hoy hasta el domingo; una consulta del plan cubre la semana completa.
- `request_change` requiere verbo explícito y objeto explícito; la salida es siempre propuesta, nunca mutación aplicada.
- Las palabras clave son pistas, no una garantía de comprensión semántica. Paráfrasis no reconocidas producen `clarify`/intención no resuelta y pasan al cauce de reserva.
- No se guardan preguntas, métricas personales ni respuestas crudas en logs ordinarios.

## Precedencia de intención

| Señal | Resultado |
|---|---|
| Verbo de cambio + objeto concreto (`cambia la sesión`, `modifica el plan`) | `request_change` |
| Negación explícita del cambio (`no cambies/modifiques el plan`) + análisis o consulta | se elimina la señal de cambio; conserva el componente no mutativo |
| Verbo de análisis retrospectivo + ámbito temporal/selector | `analyze_day` o `analyze_activity` |
| Objeto de plan (`qué toca`, `sesión prevista`, `plan`) con fecha futura o sin verbo de análisis | `consult_plan` |
| Acción futura (`qué hacer`, `siguiente sesión`, `cómo entreno`) sin objeto de plan explícito | `recommend_next` si existe fecha de consejo; si no, `clarify` |
| Análisis y cambio en la misma consulta | `mixed` con componentes separados; no es contradicción |
| Afirmar y negar la misma operación en una cláusula (`cambia y no cambies la sesión`) | `clarify` con código de contradicción |
| Paráfrasis sin señal reconocible (`¿cómo fue lo del domingo?`) | `clarify`/pista no resuelta; nunca `request_change` |

## Clause and date-scope semantics

- Split at `y` only when the following text begins a recognized intent verb/phrase (`dime`, `analiza`, `consulta`, `cambia`, etc.). A conjunction between date expressions does not split: «analiza ayer y hoy» is one analysis component with two observed dates.
- Negation applies only inside its clause and never propagates across a recognized clause boundary. A date belongs only to the clause containing it; clauses do not borrow dates from neighbors.
- `primary_intent` is derived: one component returns its intent; more than one distinct intent returns `MIXED`; repeated components with the same intent retain that intent.
- Date ownership: retrospective analysis dates go to `observed_dates`; future `CONSULT_PLAN` and `REQUEST_CHANGE` dates go to `advice_dates`; past plan questions such as «qué tocaba ayer» use `observed_dates`; recommendations use `advice_dates`.
- On Sunday 2026-10-04, bare «el domingo» in a retrospective analysis means today (the most recent occurrence including today); «domingo pasado» means 2026-09-27, and «próximo domingo» means 2026-10-11.

| Intent and temporal relation | Date field |
|---|---|
| `ANALYZE_ACTIVITY` / `ANALYZE_DAY`, explicit or relative past/current date | `observed_dates` |
| `CONSULT_PLAN`, future/current date | `advice_dates` |
| `CONSULT_PLAN`, past date («qué tocaba ayer») | `observed_dates` |
| `REQUEST_CHANGE`, future/current target date | `advice_dates` |
| `RECOMMEND_NEXT`, requested future date | `advice_dates` |
| Latest-activity selector | selector only; explicit date tuples empty |

## Visible signal table

Keep signal patterns in a named, reviewable table in `coach_intent.py`, separate from the clause/date mechanics. Include recognized retrospective, plan, recommendation and explicit change patterns, each with examples and precedence. A general `retrospective expression + date => analysis hint` rule recognizes forms such as «qué tal me salió ayer»; unsupported wording such as «¿cómo fue lo del domingo?» remains available to the clarification path unless the general retrospective pattern applies.

## Date semantics

- «hoy», «ayer» y «mañana» son fechas locales de Madrid.
- «esta semana» es el lunes-domingo que contiene la fecha local, incluyendo días futuros en el ámbito solicitado; la cobertura real decidirá qué días tienen datos.
- «semana pasada» es el lunes-domingo anterior; «próxima semana» es el lunes-domingo siguiente.
- Un día de semana sin modificador se interpreta retrospectivamente como la ocurrencia más reciente en una consulta de análisis y prospectivamente como la próxima ocurrencia en plan/consejo. «pasado» exige una ocurrencia anterior; «próximo» exige una posterior.
- «el 3 de octubre» usa el año de `now` si no se especifica año. `DD/MM/YYYY` y `YYYY-MM-DD` son explícitos; fechas imposibles producen aclaración.
- Para un cruce DST, se convierte el instante a Madrid antes de calcular la fecha: `2026-10-03 22:30 UTC` es `2026-10-04` local; el 25 de octubre se trata como una fecha civil, no como 24 horas.

## File Structure

- Create: `apps/sync-local/garmin_sync/coach_intent.py` — enums/dataclasses y resolución pura de intención, permisos y fechas.
- Create: `apps/sync-local/tests/test_coach_intent.py` — pruebas deterministas por ciclo.

### Task 1: Define the typed contract and conservative change permission

**Files:**
- Create: `apps/sync-local/garmin_sync/coach_intent.py`
- Create: `apps/sync-local/tests/test_coach_intent.py`

**Interfaces:**
- `CoachIntent`: `ANALYZE_ACTIVITY`, `ANALYZE_DAY`, `CONSULT_PLAN`, `RECOMMEND_NEXT`, `REQUEST_CHANGE`, `MIXED`, `CLARIFY`.
- `DateSelector`: `BY_DATE`, `LATEST_ACTIVITY`, `LATEST_TRAINING_DAY`.
- `ClarificationCode`: fixed codes including `NO_SCOPE`, `CONTRADICTORY_OPERATION`, `UNSUPPORTED_PARAPHRASE`, `INVALID_DATE`, `MISSING_ADVICE_DATE`, `PAST_CHANGE_DATE`.
- `IntentComponent`: frozen dataclass with `intent`, `selector`, `observed_dates: tuple[date, ...]`, `advice_dates: tuple[date, ...]`, `clarification_code: ClarificationCode | None`; its fixed `clarification_template_key` is derived from that code.
- `IntentResolution`: frozen dataclass with ordered `components`; `primary_intent`, `selector`, `observed_dates`, `advice_dates` and `change_requested` are read-only properties calculated from components. One component yields its intent; several distinct intents yield `MIXED`. `change_requested` is true only for an explicit `REQUEST_CHANGE` component.
- `IntentComponent` validates at construction: `CLARIFY` iff a `ClarificationCode` exists, and `LATEST_ACTIVITY`/`LATEST_TRAINING_DAY` require empty date tuples.

- [ ] **Step 1: Write failing tests for the contract and permission boundary**

  Instantiate components directly and assert that they store `date` objects, resolution-level date/selector/intent properties are derived, a single component cannot report `MIXED`, `CLARIFY` iff a code exists, and a latest selector cannot carry explicit dates. Do not add `proposal_only` as an always-true field; authorization enforcement is an integration invariant for the later E15 test.

- [ ] **Step 2: Run the focused tests and verify the missing contract fails**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent -v`

  Expected: FAIL because `garmin_sync.coach_intent` and its public types do not exist.

- [ ] **Step 3: Implement only the frozen enums/dataclasses and derived properties**

  Do not add text parsing in this cycle. Ensure `IntentResolution` cannot receive duplicate source-of-truth fields and `IntentComponent` rejects the invalid combinations above.

- [ ] **Step 4: Run the focused tests and verify they pass**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent -v`

- [ ] **Step 5: Commit cycle 1**

  ```bash
  git add apps/sync-local/garmin_sync/coach_intent.py apps/sync-local/tests/test_coach_intent.py
  git commit -m "feat: define conservative coach intent contract"
  ```

### Task 2: Add deterministic civil-date resolution

**Files:**
- Modify: `apps/sync-local/garmin_sync/coach_intent.py`
- Modify: `apps/sync-local/tests/test_coach_intent.py`

**Interfaces:**
- Add `DateResolutionScope` (`OBSERVED`, `ADVICE`, `PLAN`) and `resolve_dates(text: str, *, now: datetime, scope: DateResolutionScope) -> tuple[date, ...]` as the pure date parser; the next cycle wires it into `resolve_intent`.
- Add `InvalidDateError(ValueError)` for impossible explicit dates; `resolve_intent` will translate it to `ClarificationCode.INVALID_DATE` in the classification cycle.

- [ ] **Step 1: Write failing date tests**

  Cover `hoy`, `ayer`, `mañana` as a date versus `esta mañana`/`por la mañana` as time-of-day (no next-day date), ISO dates, `04/10/2026`, `el 3 de octubre`, `el domingo`, `el domingo` on Sunday 2026-10-04 (same day), `el domingo pasado`, `el próximo domingo`, `el martes pasado`, `esta semana`, `semana pasada`, `próxima semana`, invalid dates, Madrid midnight conversion from UTC, and 25 October 2026 DST civil-date behavior. For month/day without year, analysis selects the most recent occurrence including today; plan/advice selects the next occurrence strictly after today. Assert exact `date` tuples and no silent correction.

- [ ] **Step 2: Run date tests and verify they fail**

  Run: `cd apps/sync-local && python3 -m unittest tests.test_coach_intent.DateResolutionTests -v`

  Expected: FAIL because the pure date parser does not exist.

- [ ] **Step 3: Implement date parsing using local civil dates**

  Reject naive `now`; convert aware instants to `ZoneInfo("Europe/Madrid")`. Parse month names and weekday names in Spanish, use Monday as week start, preserve unique chronological `date` values, and return `INVALID_DATE` instead of guessing when a supplied date is impossible. Distinguish `mañana` as a date only when it is not part of `esta mañana`/`por la mañana`. For an unmodified weekday in retrospective analysis, choose the most recent occurrence including today; `pasado` is strictly earlier and `próximo` strictly later. Apply clause intent to choose the year for a month/day without year. For «esta semana», analysis returns Monday through `min(today, Sunday)`, recommendations return `today..Sunday`, and plan consultation returns Monday..Sunday.

- [ ] **Step 4: Run date tests and verify they pass**

  Run: `cd apps/sync-local && python3 -m unittest tests.test_coach_intent.DateResolutionTests -v`

- [ ] **Step 5: Commit cycle 2**

  ```bash
  git add apps/sync-local/garmin_sync/coach_intent.py apps/sync-local/tests/test_coach_intent.py
  git commit -m "feat: resolve coach dates in Madrid civil time"
  ```

### Task 3: Add intent hints, precedence, mixed components and negation

**Files:**
- Modify: `apps/sync-local/garmin_sync/coach_intent.py`
- Modify: `apps/sync-local/tests/test_coach_intent.py`

**Interfaces:**
- `resolve_intent` returns ordered components; each component owns its own selector and date scopes.

- [ ] **Step 1: Write failing classification tests**

  Cover analysis (`analiza mi entrenamiento de hoy`, `qué tal me salió ayer`), latest selectors, plan (`qué toca mañana`), past plan (`qué tocaba ayer`), advice (`dime qué hacer mañana`), no-date advice (`dime qué hacer` → `MISSING_ADVICE_DATE`), explicit change proposals, `analiza hoy y dime qué hacer mañana`, `analiza y cambia el plan`, `no cambies el plan, analiza hoy`, `no analices, dime qué toca`, and retrospective `¿cómo fue lo del domingo?` → `ANALYZE_DAY` under the general retrospective-expression-plus-date rule. Use `la sesión morada del domingo` as an unsupported phrase → `CLARIFY`/`UNSUPPORTED_PARAPHRASE`. Add non-mutating negatives: `¿debería cambiar la sesión de mañana?`, `cambiar de ritmo`, and `cambiar de zapatillas` never produce `REQUEST_CHANGE`. Assert `analiza hoy` has exactly one component; `analiza ayer y hoy` has one analysis component and both observed dates; `no analices, dime qué toca` applies negation only to the first clause; mixed clauses do not borrow dates from one another. Assert plan beats generic advice for `qué toca`, and future advice dates are never copied into observed dates.

- [ ] **Step 2: Run classification tests and verify they fail**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent.IntentClassificationTests -v`

  Expected: FAIL because only the contract/date skeleton exists.

- [ ] **Step 3: Implement conservative signal classification**

  Match normalized signals only as hints, using the visible signal table. Split on `y` only if the following clause begins with a recognized intent verb/phrase. Resolve each clause independently; do not propagate negation or dates. A general retrospective expression plus a recognized date yields an analysis hint. Require an imperative/request verb plus explicit plan/session object for `REQUEST_CHANGE`; questions asking whether one should change something are advice, and objects such as pace/shoes are not plan objects. Apply date ownership and precedence above. Unknown or underspecified analysis/advice is `CLARIFY`, never an inferred change.

- [ ] **Step 4: Run classification tests and verify they pass**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent.IntentClassificationTests -v`

- [ ] **Step 5: Commit cycle 3**

  ```bash
  git add apps/sync-local/garmin_sync/coach_intent.py apps/sync-local/tests/test_coach_intent.py
  git commit -m "feat: classify coach intent conservatively"
  ```

### Task 4: Add fixed clarification codes and regression verification

**Files:**
- Modify: `apps/sync-local/garmin_sync/coach_intent.py`
- Modify: `apps/sync-local/tests/test_coach_intent.py`

- [ ] **Step 1: Write failing clarification/privacy tests**

  Assert every clarification has a fixed `ClarificationCode`, never embeds the original question, and provides a stable template key/message selected from the code. Cover unsupported paraphrase, invalid date, no scope, missing advice date and contradictory operation. Assert no parser path logs or returns raw question text in diagnostic fields.

- [ ] **Step 2: Run clarification tests and verify they fail**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent.ClarificationTests -v`

  Expected: FAIL until fixed codes/templates are wired into all clarification paths.

- [ ] **Step 3: Implement code-to-template mapping and complete the resolver**

  Keep `clarification_code` machine-readable and map it to a fixed, non-sensitive prompt at the presentation boundary. Do not persist or interpolate the original question. The applying backend remains responsible for enforcing authorization before any plan persistence; integration verification is assigned to the later E15 coverage in Fase 2.

  Run a handwritten, non-log regression corpus through the resolver: all 17 evaluation case prompts (question text only, with fixtures checked for privacy before copying) plus about 20 authored phrases representative of normal Spanish use. Record per-class outcomes and the `clarify` rate in test output or a checked-in test summary; this corpus guides coverage and does not loosen the conservative change-permission rule. Add a clear regression that «analiza hoy» resolves to one component. The later Fase 2 integration plan owns the E15 backend authorization proof that no `REQUEST_CHANGE` path can persist a plan without the authorized proposal/approval flow.

- [ ] **Step 4: Run the focused and full worker suites**

  Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_coach_intent -v`

  Then run: `cd apps/sync-local && .venv/bin/python -m unittest discover -s tests -v`

  Expected: all new and existing tests pass.

- [ ] **Step 5: Commit cycle 4**

  ```bash
  git add apps/sync-local/garmin_sync/coach_intent.py apps/sync-local/tests/test_coach_intent.py
  git commit -m "feat: add safe clarification outcomes for coach intent"
  ```

## Self-Review Checklist

- The plan separates deterministic date/permission guarantees from heuristic intent hints.
- Future integration can hand `CLARIFY` to the coach without treating it as permission to change a plan.
- The only mutation-adjacent result is a proposal request with explicit verb and object.
- Public dates are `datetime.date`, and resolution-level aggregate values are derived properties.
- Clause segmentation, per-clause negation, and per-clause dates have explicit semantics and regression cases.
- Spanish natural-language date forms, week semantics, DST boundaries and time-of-day ambiguity are tested.
- The work is split into four red-green-commit cycles, each independently reviewable.
