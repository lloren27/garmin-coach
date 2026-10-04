# Fase 2 — Contrato de intención en generación Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que contrato, esquema, resolver y pipeline respeten `IntentResolution` por componente sin ampliar la autoridad para cambiar el plan.

**Architecture:** `build_snapshot` vuelve a resolver intención desde pregunta + `created_at` del trabajo (hora de encolado), nunca desde una intención transportada. Cada decisión estructurada declara `component_index` y fecha; esquema y `resolve_generation` restringen acciones y fechas por componente. El flag de enforcement queda apagado por defecto hasta evaluación E01–E17; no se cambian presupuestos de generación.

**Tech Stack:** Python, Pydantic, `unittest`.

**Spec:** [Diseño aprobado](../specs/2026-10-04-fase2-intent-contract-design.md); requisitos base en [Fase 2 v1](../../restructuring/restructuring_fase2_v1.md), sección 3 y Tarea 2.

## Global Constraints

- No análisis puro puede producir prescripción, conservar sesión como decisión ni propuesta de cambio.
- Las fechas observadas y de consejo permanecen separadas; nunca se prescribe en fecha pasada.
- `request_change` no equivale a permiso backend; el backend sigue exigiendo su autorización actual.
- Los errores de validación no incluyen ni registran la pregunta o respuesta cruda.
- Las respuestas del modelo se vuelven a validar tras el esquema estructurado.
- Cada decisión declara componente y fecha; las prescripciones solo usan fechas de consejo y el análisis fechas observadas.
- Los trabajos conservan la semántica temporal usando `created_at` del backend. El worker vuelve a resolver pregunta + hora; ninguna intención transportada concede permiso.
- Se elimina `target_dates` y se migran todos sus lectores; no se agrega el ámbito mixto.
- `CLARIFY` fijo no invoca el modelo; `UNSUPPORTED_PARAPHRASE` puede invocarlo con permisos solo informativos/aclarativos.
- Se mantienen los límites actuales de generación.
- Con enforcement apagado, el contrato y comportamiento actuales siguen intactos; `component_index` solo es requerido con enforcement activo.

## Review Focus

- Análisis con sesiones de plan presentes no debe activar `keep_plan`; fixture explícito en pruebas de esquema y resolver.
- Respuesta manipulada que ignora JSON Schema no debe eludir la intención; cubrir en resolución.
- `qué tocaba ayer` no admite `keep_plan`; timestamp UTC y trabajo procesado al día siguiente conservan las fechas; cubrir en contexto/pipeline.
- `REQUEST_CHANGE` sin autorización da `CHANGE_NOT_AUTHORIZED` fijo, sin modelo/propuesta; cubrir en pipeline.
- Trabajos pendientes resuelven desde pregunta + hora de encolado `created_at`; no se confía en intención serializada.

## File Structure

- Modify `apps/sync-local/garmin_sync/coach_generation_context.py`: intención y fechas en `ContextSnapshot`, contexto público y esquema.
- Modify `apps/sync-local/garmin_sync/coach_generation_contracts.py`: `component_index` y fecha en decisiones tipadas.
- Modify `apps/sync-local/garmin_sync/coach_generation_resolver.py`: validación autoritativa de acción y fechas.
- Modify `apps/sync-local/garmin_sync/coach_validation.py` and `coach_intent.py`: códigos estables `INTENT_MISMATCH`, `CHANGE_NOT_AUTHORIZED` and fixed safe template, with bounded repair hint.
- Modify `apps/sync-local/garmin_sync/coach_generation_pipeline.py`, `ai_worker.py` and `apps/bot/app/main.py` only if passing trusted enqueue time needs changing the job envelope; prefer existing `created_at`, without API version changes.
- Extend `test_coach_generation_context.py`, `test_coach_generation_contracts.py`, `test_coach_generation_pipeline.py` and existing resolver tests.

### Task 1: Carry intent and separated date scopes in the snapshot

**Interfaces:** `ContextSnapshot.intent: IntentResolution`; `ContextSnapshot.now` comes from backend job `created_at`. `build_snapshot(question, compact, *, now)` invokes `resolve_intent(question, now=now)`. Remove `target_dates` and migrate schema, resolver and renderer to component scopes.

- [x] Add tests proving `analiza hoy y dime qué hacer mañana` yields both scopes; `qué tocaba ayer` retains observed date; 22:30 UTC resolves to next Madrid date; and an enqueued 23:50 job processed after midnight uses enqueue time.
- [x] Run focused context tests and confirm the new assertions fail for the missing fields/behavior.
- [x] Add immutable intent; remove `target_dates`; serialize only fixed enum values, ISO dates, selectors and clarification codes. Never trust transported intent.
- [x] Run focused context tests from `apps/sync-local`; confirm pass.

### Task 2: Restrict schema and authoritative resolution by intent

**Interfaces:** decisions carry optional `component_index: int` and explicit optional `date` in the compatibility contract; enforcement schema requires index and requires a date for temporal scopes. Stable code `INTENT_MISMATCH`; schema limits actions per component and resolver enforces component, action and date after parsing. With flag off, current schema/validation behavior is unchanged.

- [x] Add failing tests: analysis with plan sessions present excludes `keep_plan` and prescriptions; forged `keep_plan` raises `INTENT_MISMATCH`; future plan query allows `keep_plan`, while `qué tocaba ayer` allows information only.
- [x] Add failing date-scope tests: analysis yesterday is accepted but prescription yesterday rejected; mixed today/tomorrow yields separately indexed decisions and cross-component dates are rejected.
- [x] Implement the validation code and bounded repair hints; enforce intent before producing resolved decisions/proposals.
- [x] Add fixed `CHANGE_NOT_AUTHORIZED` response and prove `REQUEST_CHANGE` without backend permission never invokes the model or returns a proposal; existing proposal source authorization is retained.
- [x] Run focused context/resolver/contract tests and confirm pass.

### Task 3: Route generation and clarification through intent

- [x] Add `COACH_INTENT_ENFORCEMENT=off` by default, enabled in feature tests; verify legacy schema/prompt while off and scoped mixed/unresolved cases under the flag.
- [x] Separate fixed clarification (no model call) from `UNSUPPORTED_PARAPHRASE` (model, only `information_only`/`ask_user`); preserve current `num_predict` budgets.
- [x] Verify bounded repairs, component/date scope enforcement, and privacy-safe diagnostics.
- [ ] Evaluate E01–E17 under the flag; keep default off pending approved results. Run focused and full sync-local suites; record unrelated dependency failures distinctly. Full discovery reached 160 tests but 9 modules cannot import because `garminconnect` is unavailable; backend suites additionally require `fastapi`.

In compatibility mode the schema omits the requirement for `component_index` and all new intent restrictions; feature-mode tests assert the field is required and validated. `process_job` passes the backend job's `created_at` to `call_ollama` as `now`; missing or malformed enqueue time fails closed and never falls back to worker wall-clock time.

### Named follow-up: E15 authorization/persistence integration

Fase 2, Tarea 5 owns an explicit integration test proving no `REQUEST_CHANGE` path persists a plan mutation without the authorized proposal/approval flow. This plan does not claim that persistence proof.

## Commit boundaries

- Task 1: `feat: carry coach intent in generation snapshot`
- Task 2: `feat: enforce coach intent in generation resolver`
- Task 3: `feat: route coach generation by resolved intent`

Run tests with `cd apps/sync-local && .venv/bin/python -m unittest ...`. The `.venv` is currently absent: create it with `python3 -m venv .venv` and install only `requirements.txt` into that environment; if dependencies cannot be obtained, report the blocker and do not switch interpreters.
