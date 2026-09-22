# Zepp / Helio Wellness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest daily Helio Strap data through Zepp, resolve it with Garmin under explicit per-metric rules, and expose a traceable wellness view without changing Garmin-owned activities.

**Architecture:** The local sync owns provider calls, normalization, deterministic resolution, and the payload. Garmin and Zepp each produce normalized per-date wellness records for the same lookback; a pure resolver builds every history entry once and aliases today's entry to `wellness.effective`. Railway persists raw per-provider daily records with date/source upserts and reconstructs the latest payload; only after this contract is proven will bot formatting and Ollama consume the effective view.

**Tech Stack:** Python 3, `dataclasses`, `unittest`, `httpx`, `python-dotenv`, FastAPI, PostgreSQL via psycopg, Zepp-export installed from its Git repository.

**Spec:** [2026-09-22-zepp-helio-wellness-design.md](../specs/2026-09-22-zepp-helio-wellness-design.md)

## Global Constraints

- Zepp credentials stay only on the Mac: never log, persist, or post `ZEPP_TOKEN`.
- `ZEPP_SYNC_LOOKBACK_DAYS=2` means three local wellness dates: today and the prior two dates.
- Garmin remains the only source of `summary.activities`, training summaries, and sport physiology reference.
- `wellness.schema_version` is exactly `2`; `wellness.timezone` is the configured local IANA zone.
- `wellness.effective` is the exact object resolved for `wellness.history[today].effective`; no independent second resolver call is allowed.
- Sleep is a single valid session from one provider, assigned to the local date on which it ends; ISO-8601 timestamps retain offsets.
- Metrics with provider-specific algorithms (`stress`, ATL, CTL, TSB, TRIMP, sport load and Zepp VO2max) are never silently substituted by another provider.
- A date increments `days_received` when its provider query succeeds, even when optional observations are absent.

## Review Focus

- A Zepp response with `resting_hr=0` must fall back to valid Garmin rather than appear as a real resting HR. Covered in Task 2.
- A zero-step day is valid and must remain Zepp-owned rather than trigger Garmin fallback. Covered in Task 2.
- The same cross-midnight sleep returned for adjacent queried dates must exist only once under the date it ends. Covered in Task 1.
- A missing VO2max observation on a rest day must not make the provider date fail or erase a prior Zepp observation. Covered in Task 1.
- A partial Zepp lookback with one whole date failed must report `partial`, 3 requested and 2 received without exposing the token. Covered in Task 3.

---

## File Structure

- Create `apps/sync-local/garmin_sync/wellness_models.py`: immutable normalized contracts, provider statuses and per-date results.
- Create `apps/sync-local/garmin_sync/zepp_provider.py`: isolated Zepp client adapter and error classification.
- Create `apps/sync-local/garmin_sync/wellness_resolver.py`: source policy, validators and atomic daily resolution.
- Create `apps/sync-local/tests/test_wellness_models.py`: model/date/sleep normalization tests.
- Create `apps/sync-local/tests/test_zepp_provider.py`: provider call, optional metric and failure classification tests.
- Create `apps/sync-local/tests/test_wellness_resolver.py`: precedence, validation and provenance tests.
- Modify `apps/sync-local/garmin_sync/sync.py`: historical Garmin wellness collection, Zepp normalization, payload construction and one-pass history resolution.
- Modify `apps/sync-local/requirements.txt`: install `zepp-export` in the local sync environment.
- Modify `.env.example` and `README.md`: local-only Zepp variables, refresh guidance and sync behavior.
- Modify `apps/bot/app/store.py`: file and PostgreSQL daily-wellness upsert/read paths.
- Create `apps/bot/tests/test_wellness_persistence.py`: source/date upsert coverage.
- Modify `apps/bot/tests/test_daily_week_coach.py`: effective wellness formatter coverage.
- Modify `apps/bot/app/coach.py`: consume effective wellness with source labels while preserving legacy Garmin payload compatibility.
- Modify `apps/sync-local/garmin_sync/ai_worker.py` and `apps/sync-local/tests/test_ai_*`: send source-labelled effective wellness to Ollama after bot consumers are stable.

### Task 1: P1 — Define normalized wellness contracts and Zepp provider

**Files:**
- Create: `apps/sync-local/garmin_sync/wellness_models.py`
- Create: `apps/sync-local/garmin_sync/zepp_provider.py`
- Create: `apps/sync-local/tests/test_wellness_models.py`
- Create: `apps/sync-local/tests/test_zepp_provider.py`
- Modify: `apps/sync-local/requirements.txt`
- Modify: `.env.example`

**Interfaces:**
- Produces `ProviderStatus`, `ProviderDayResult`, `NormalizedWellness`, `NormalizedSleep`, and `ZeppProvider` for Tasks 2 and 3.
- `ZeppProvider.fetch_days(dates: list[date]) -> tuple[dict[str, ProviderDayResult], dict[str, Any]]` returns an ISO-date-keyed result map and the redacted provider status.
- `NormalizedWellness.to_dict() -> dict[str, Any]` returns only JSON-native values.

- [ ] **Step 1: Write the failing model tests**

```python
def test_sleep_is_keyed_to_its_local_end_date_and_deduplicated() -> None:
    sleep = NormalizedSleep(
        start="2026-09-21T23:41:00+02:00",
        end="2026-09-22T07:09:00+02:00",
        total_minutes=448,
    )
    wellness = NormalizedWellness(sleep=sleep)
    assert wellness.wellness_date("Europe/Madrid") == "2026-09-22"


def test_zepp_vo2max_is_an_observation_not_a_daily_required_value() -> None:
    wellness = NormalizedWellness(vo2max_observations=[])
    assert wellness.to_dict()["vo2max_observations"] == []
```

- [ ] **Step 2: Run the model tests to verify they fail**

Run: `cd apps/sync-local && python -m unittest tests.test_wellness_models -v`

Expected: FAIL because `garmin_sync.wellness_models` does not exist.

- [ ] **Step 3: Implement the minimal JSON-safe models**

```python
class ProviderStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    DISABLED = "disabled"
    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    INVALID_DATA = "invalid_data"


@dataclass(frozen=True)
class ProviderDayResult:
    date: str
    status: Literal["ok", "error"]
    data: NormalizedWellness | None = None
    error_kind: str | None = None
```

Normalize a sleep session by parsing its offset-aware end timestamp, deriving its `wellness_date` in the supplied `ZoneInfo`, and deduplicating provider sessions by explicit id or `(start, end)`. Represent stress as an aggregate with `avg`, `min`, `max`, `sample_count`, `coverage_minutes`, optional zones and source. Represent Zepp VO2max as a list of `{value, unit, source, observed_at}` observations.

- [ ] **Step 4: Run the model tests to verify they pass**

Run: `cd apps/sync-local && python -m unittest tests.test_wellness_models -v`

Expected: PASS; the date is `2026-09-22`, duplicate sessions collapse and an empty VO2max list is valid.

- [ ] **Step 5: Write failing Zepp provider tests**

```python
def test_fetch_days_marks_rest_day_ok_when_vo2max_is_absent() -> None:
    provider = ZeppProvider(token="secret", user_id="42", base_url="https://example.test")
    provider._client = FakeZeppClient(sleep=VALID_SLEEP, steps=VALID_STEPS, vo2max=[])
    days, status = provider.fetch_days([date(2026, 9, 22)])
    assert days["2026-09-22"].status == "ok"
    assert status["days_received"] == 1


def test_auth_failure_is_redacted_and_does_not_include_token() -> None:
    provider = ZeppProvider(token="secret-token", user_id="42")
    provider._client = RaisingZeppClient(ZeppAuthError("expired secret-token"))
    _days, status = provider.fetch_days([date(2026, 9, 22)])
    assert status["status"] == "auth_error"
    assert "secret-token" not in repr(status)
```

- [ ] **Step 6: Run provider tests to verify they fail**

Run: `cd apps/sync-local && python -m unittest tests.test_zepp_provider -v`

Expected: FAIL because `ZeppProvider` does not exist.

- [ ] **Step 7: Implement the isolated Zepp adapter and local configuration**

```python
class ZeppProvider:
    def fetch_days(self, dates: list[date]) -> tuple[dict[str, ProviderDayResult], dict[str, Any]]:
        results = {day.isoformat(): self._fetch_day(day) for day in dates}
        received = sum(item.status == "ok" for item in results.values())
        return results, self._status_for(results, len(dates), received)
```

Import `ZeppClient`, `ZeppAuthError` and `ZeppAPIError` only in this module; map authentication, network, API and malformed response failures to the specified redacted statuses. A missing token or user id returns `disabled` without creating a client. Add the pinned VCS dependency `zepp-export @ git+https://github.com/EvanCooke/zepp-export.git` to the local requirements and add blank `ZEPP_TOKEN`, `ZEPP_USER_ID`, `ZEPP_BASE_URL` and `ZEPP_SYNC_LOOKBACK_DAYS=2` entries to `.env.example`.

- [ ] **Step 8: Run Task 1 tests to verify they pass**

Run: `cd apps/sync-local && python -m unittest tests.test_wellness_models tests.test_zepp_provider -v`

Expected: PASS, including redaction and an optional-VO2max rest day.

- [ ] **Step 9: Commit Task 1**

```bash
git add apps/sync-local/garmin_sync/wellness_models.py apps/sync-local/garmin_sync/zepp_provider.py apps/sync-local/tests/test_wellness_models.py apps/sync-local/tests/test_zepp_provider.py apps/sync-local/requirements.txt .env.example
git commit -m "feat: add Zepp wellness provider contracts"
```

### Task 2: P2 — Resolve per-date wellness deterministically

**Files:**
- Create: `apps/sync-local/garmin_sync/wellness_resolver.py`
- Create: `apps/sync-local/tests/test_wellness_resolver.py`

**Interfaces:**
- Consumes `NormalizedWellness` from Task 1 and Garmin normalized dictionaries from Task 3.
- Produces `resolve_wellness(garmin: dict[str, Any], zepp: dict[str, Any], wellness_date: str) -> dict[str, Any]`.
- Exposes `EFFECTIVE_SOURCE_POLICY` and `is_valid_metric(name: str, candidate: Any) -> bool` for direct tests.

- [ ] **Step 1: Write failing precedence and validator tests**

```python
def test_invalid_zepp_resting_hr_falls_back_to_valid_garmin() -> None:
    resolved = resolve_wellness(
        garmin={"resting_hr": {"value": 48, "unit": "bpm"}},
        zepp={"resting_hr": {"value": 0, "unit": "bpm"}},
        wellness_date="2026-09-22",
    )
    assert resolved["resting_hr"] == {"value": 48, "unit": "bpm", "source": "garmin"}


def test_zero_zepp_steps_are_valid() -> None:
    resolved = resolve_wellness({}, {"steps": {"value": 0, "unit": "steps"}}, "2026-09-22")
    assert resolved["steps"]["source"] == "zepp"


def test_sleep_is_selected_as_one_complete_provider_block() -> None:
    resolved = resolve_wellness(GARMIN_SLEEP, ZEPP_COMPLETE_SLEEP, "2026-09-22")
    assert resolved["sleep"]["source"] == "zepp"
    assert resolved["sleep"]["deep_minutes"] == 82
    assert "garmin_deep_minutes" not in resolved["sleep"]
```

- [ ] **Step 2: Run resolver tests to verify they fail**

Run: `cd apps/sync-local && python -m unittest tests.test_wellness_resolver -v`

Expected: FAIL because `wellness_resolver` does not exist.

- [ ] **Step 3: Implement explicit policy and resolver**

```python
EFFECTIVE_SOURCE_POLICY = {
    "sleep": ("zepp", "garmin"), "resting_hr": ("zepp", "garmin"),
    "steps": ("zepp", "garmin"), "stress": ("zepp",),
    "atl": ("zepp",), "ctl": ("zepp",), "tsb": ("zepp",),
    "trimp": ("zepp",), "sport_load": ("zepp",), "vo2max": ("garmin",),
}

def resolve_wellness(garmin, zepp, wellness_date):
    providers = {"garmin": garmin or {}, "zepp": zepp or {}}
    return {metric: _with_source(metric, providers, wellness_date)
            for metric in EFFECTIVE_SOURCE_POLICY}
```

Implement validators: resting HR is 20–250, steps is numeric and non-negative, sleep has a positive total and internally consistent phases, VO2max is positive, TRIMP is non-negative, and ATL/CTL/TSB are numeric. Do not add a fallback for a single-source metric. Retain source, unit and observed timestamp when supplied. Omit invalid/unavailable metrics rather than inventing a null effective value.

- [ ] **Step 4: Add the non-equivalence and incomplete-sleep tests**

```python
def test_zepp_stress_does_not_fall_back_to_garmin() -> None:
    resolved = resolve_wellness({"stress": {"avg": 22}}, {}, "2026-09-22")
    assert "stress" not in resolved


def test_partial_zepp_sleep_uses_complete_garmin_sleep() -> None:
    resolved = resolve_wellness(GARMIN_COMPLETE_SLEEP, {"sleep": {"total_minutes": 420}}, "2026-09-22")
    assert resolved["sleep"]["source"] == "garmin"
```

- [ ] **Step 5: Run Task 2 tests to verify they pass**

Run: `cd apps/sync-local && python -m unittest tests.test_wellness_resolver -v`

Expected: PASS; zero steps stay Zepp-owned, invalid RHR falls back, and no phases are mixed.

- [ ] **Step 6: Commit Task 2**

```bash
git add apps/sync-local/garmin_sync/wellness_resolver.py apps/sync-local/tests/test_wellness_resolver.py
git commit -m "feat: resolve wellness by source policy"
```

### Task 3: P3 — Build the local historical wellness payload

**Files:**
- Modify: `apps/sync-local/garmin_sync/sync.py`
- Create: `apps/sync-local/tests/test_zepp_sync_payload.py`

**Interfaces:**
- Consumes `ZeppProvider.fetch_days`, `NormalizedWellness.to_dict`, and `resolve_wellness` from Tasks 1–2.
- Produces `collect_wellness_history(client, dates, zepp_provider, timezone_name) -> dict[str, Any]`, adds its return value as `payload["wellness"]`, and adds test-only helper `build_payload_with(client, zepp_provider)` in `test_zepp_sync_payload.py` that patches the sync module's dependencies and calls `build_payload()`.
- The current `compact_wellness(client)` becomes a date-parameterized Garmin normalizer and must not fetch Zepp data.

- [ ] **Step 1: Write the failing one-pass resolution test**

```python
def test_today_effective_is_the_same_object_as_resolved_history_today() -> None:
    wellness = collect_wellness_history(FakeGarmin(), DATES, FakeZeppProvider(), "Europe/Madrid")
    assert wellness["effective"] is wellness["history"]["2026-09-22"]["effective"]
    assert wellness["schema_version"] == 2
    assert wellness["timezone"] == "Europe/Madrid"


def test_historical_garmin_sleep_falls_back_for_same_date() -> None:
    wellness = collect_wellness_history(FakeGarmin(sleeps={"2026-09-21": GARMIN_SLEEP}), DATES, NoZeppSleep(), "Europe/Madrid")
    assert wellness["history"]["2026-09-21"]["effective"]["sleep"]["source"] == "garmin"
```

- [ ] **Step 2: Run the payload test to verify it fails**

Run: `cd apps/sync-local && python -m unittest tests.test_zepp_sync_payload -v`

Expected: FAIL because `collect_wellness_history` does not exist.

- [ ] **Step 3: Implement historical collection without altering activities**

```python
def collect_wellness_history(client, dates, zepp_provider, timezone_name):
    garmin_days = {day.isoformat(): compact_garmin_wellness(client, day) for day in dates}
    zepp_days, provider_status = zepp_provider.fetch_days(dates)
    history = {key: {"effective": resolve_wellness(garmin_days[key], _data(zepp_days[key]), key)}
               for key in garmin_days}
    today = dates[-1].isoformat()
    return {"schema_version": 2, "timezone": timezone_name, "garmin": garmin_days,
            "zepp": _serialize_days(zepp_days), "history": history,
            "effective": history[today]["effective"], "provider_status": {"zepp": provider_status}}
```

Build `dates` as `today - timedelta(days=lookback)` through today in chronological order. Parameterize Garmin wellness calls by each day and preserve their existing compact shape inside `wellness.garmin[date]`. Keep `summary`, activity collection, Wattwise and physiology untouched. Do not make Zepp movement segments activities.

- [ ] **Step 4: Add failure-status and deduplication tests**

```python
def test_one_provider_day_failure_is_partial_not_a_failed_sync() -> None:
    wellness = collect_wellness_history(FakeGarmin(), DATES, OneDayFailsProvider(), "Europe/Madrid")
    status = wellness["provider_status"]["zepp"]
    assert status["status"] == "partial"
    assert (status["days_requested"], status["days_received"]) == (3, 2)


def test_zepp_motion_never_enters_summary_activities() -> None:
    payload = build_payload_with(FakeGarmin(), FakeZeppProviderWithMotion())
    assert all(activity["id"] != "zepp-motion-1" for activity in payload["summary"]["activities"])
```

- [ ] **Step 5: Run Task 3 tests to verify they pass**

Run: `cd apps/sync-local && python -m unittest tests.test_zepp_sync_payload tests.test_sync_running_recommendation -v`

Expected: PASS; today aliases history, each date can fall back to Garmin, and activities remain Garmin-only.

- [ ] **Step 6: Commit Task 3**

```bash
git add apps/sync-local/garmin_sync/sync.py apps/sync-local/tests/test_zepp_sync_payload.py
git commit -m "feat: sync historical Garmin and Zepp wellness"
```

### Task 4: P4 — Persist daily source records with upsert semantics

**Files:**
- Modify: `apps/bot/app/store.py`
- Create: `apps/bot/tests/test_wellness_persistence.py`
- Modify: `apps/bot/app/main.py`

**Interfaces:**
- Consumes sync payload `wellness.garmin[date]`, `wellness.zepp[date]`, `wellness.history[date]` from Task 3.
- Produces `upsert_wellness_days(payload: dict[str, Any], owner_id: str = "default") -> None` and `load_wellness_history(limit: int) -> dict[str, Any]`.
- `save_sync()` invokes the upsert before recording the latest complete sync document.

- [ ] **Step 1: Write failing file-store and Postgres contract tests**

```python
def test_second_sync_updates_same_date_and_source_without_duplicate(tmp_path) -> None:
    store.DATA_DIR = tmp_path
    store.upsert_wellness_days(PAYLOAD_WITH_ZEPP_SCORE_78)
    store.upsert_wellness_days(PAYLOAD_WITH_ZEPP_SCORE_82)
    rows = store.load_wellness_history(3)
    assert rows["2026-09-22"]["zepp"]["sleep"]["score"] == 82
    assert len(rows["2026-09-22"]["sources"]) == 2


def test_postgres_schema_has_one_row_per_owner_date_source() -> None:
    assert "unique (owner_id, wellness_date, source)" in store.WELLNESS_DAILY_DDL.lower()
```

- [ ] **Step 2: Run persistence tests to verify they fail**

Run: `cd apps/bot && python -m unittest tests.test_wellness_persistence -v`

Expected: FAIL because the daily wellness APIs and schema constant do not exist.

- [ ] **Step 3: Implement storage with matching file and PostgreSQL behavior**

```sql
create table if not exists wellness_daily (
  owner_id text not null,
  wellness_date date not null,
  source text not null,
  document jsonb not null,
  updated_at timestamptz not null,
  primary key (owner_id, wellness_date, source)
)
```

For PostgreSQL use `insert ... on conflict (owner_id, wellness_date, source) do update set document = excluded.document, updated_at = excluded.updated_at`. For the file store, use a single JSON object keyed by owner/date/source and replace that key atomically. Store only redacted normalized wellness data. Upsert both raw source records and the resolved history entry, then ensure a fresh `load_wellness_history()` returns one record per source/date.

- [ ] **Step 4: Add sync endpoint integration test**

```python
def test_sync_endpoint_persists_three_wellness_dates(client) -> None:
    response = client.post("/sync", json=THREE_DAY_PAYLOAD, headers=SYNC_HEADERS)
    assert response.status_code == 200
    assert set(store.load_wellness_history(3)) == {"2026-09-20", "2026-09-21", "2026-09-22"}
```

- [ ] **Step 5: Run Task 4 tests to verify they pass**

Run: `cd apps/bot && python -m unittest tests.test_wellness_persistence -v`

Expected: PASS; later Zepp consolidation replaces the same stored source-day and endpoint storage preserves all three dates.

- [ ] **Step 6: Commit Task 4**

```bash
git add apps/bot/app/store.py apps/bot/app/main.py apps/bot/tests/test_wellness_persistence.py
git commit -m "feat: upsert daily wellness sources"
```

### Task 5: P5 — Migrate bot output and Ollama context to effective wellness

**Files:**
- Modify: `apps/bot/app/coach.py`
- Modify: `apps/bot/tests/test_daily_week_coach.py`
- Modify: `apps/sync-local/garmin_sync/ai_worker.py`
- Modify: `apps/sync-local/tests/test_ai_checkin_context.py`

**Interfaces:**
- Consumes `payload["wellness"]["effective"]` from Task 3 and falls back to the legacy Garmin wellness shape when `schema_version != 2`.
- Produces source-labelled health strings and a source-labelled effective wellness fragment in `build_ai_brief()`.

- [ ] **Step 1: Write failing formatter tests for source and compatibility**

```python
def test_today_labels_effective_zepp_health_but_keeps_garmin_activities() -> None:
    answer = format_today(ZEPPCENTRIC_SYNC)
    assert "Sueño: 7 h 28 min [Zepp]" in answer
    assert "FC reposo: 47 bpm [Zepp]" in answer
    assert "Actividades: 1" in answer


def test_legacy_garmin_wellness_payload_still_formats() -> None:
    answer = format_health(LEGACY_GARMIN_SYNC)
    assert "Salud y recuperacion Garmin" in answer
```

- [ ] **Step 2: Run formatter tests to verify they fail**

Run: `cd apps/bot && python -m unittest tests.test_daily_week_coach -v`

Expected: FAIL because effective source labels are not yet rendered.

- [ ] **Step 3: Implement a single effective-view adapter and formatters**

```python
def _effective_wellness(payload: dict[str, Any]) -> dict[str, Any] | None:
    wellness = payload.get("wellness") or {}
    if wellness.get("schema_version") == 2:
        return wellness.get("effective") or {}
    return None
```

Map metric wrappers to the existing display helpers without losing `source`. Keep Garmin-only values such as readiness and body battery in their legacy locations until a new effective policy explicitly adds them. Make `/today` and `/health` use the adapter first and the legacy path second, so historical stored payloads remain readable.

- [ ] **Step 4: Write the failing AI-context test**

```python
def test_ai_brief_includes_source_labelled_effective_wellness() -> None:
    brief = build_ai_brief("¿entreno hoy?", ZEPPCENTRIC_SYNC, {}, [], [], None, None, None, None)
    assert "Sueño: 448 min [Zepp]" in brief
    assert "VO2max: 52 [Garmin]" in brief
```

- [ ] **Step 5: Run AI-context test to verify it fails**

Run: `cd apps/bot && python -m unittest tests.test_daily_week_coach -v`

Expected: FAIL because the brief still reads the legacy wellness path.

- [ ] **Step 6: Implement AI context after formatters are stable**

```python
def _wellness_brief_lines(payload: dict[str, Any]) -> list[str]:
    effective = _effective_wellness(payload)
    if effective is None:
        return _legacy_wellness_brief_lines(payload)
    return [_format_effective_metric(name, metric) for name, metric in effective.items()]
```

Call this helper only from the backend `build_ai_brief()` path imported by the local worker. Do not send raw minute-level data, raw Zepp responses, provider error text or credentials to Ollama.

- [ ] **Step 7: Run Task 5 tests to verify they pass**

Run: `cd apps/bot && python -m unittest tests.test_daily_week_coach -v && cd ../sync-local && python -m unittest tests.test_ai_checkin_context -v`

Expected: PASS; source labels appear for v2 payloads, legacy payloads remain readable, and AI receives only compact resolved wellness.

- [ ] **Step 8: Commit Task 5**

```bash
git add apps/bot/app/coach.py apps/bot/tests/test_daily_week_coach.py apps/sync-local/garmin_sync/ai_worker.py apps/sync-local/tests/test_ai_checkin_context.py
git commit -m "feat: expose effective wellness to coaching"
```

### Task 6: P6 — Document, verify and exercise full sync behavior

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `apps/sync-local/tests/test_zepp_sync_payload.py`
- Modify: `apps/bot/tests/test_wellness_persistence.py`

**Interfaces:**
- Consumes all completed Tasks 1–5.
- Produces a documented local setup and the final full-suite evidence.

- [ ] **Step 1: Write the failing end-to-end scenario test**

```python
def test_end_to_end_auth_error_keeps_garmin_activity_and_allowed_fallbacks() -> None:
    payload = build_payload_with(FakeGarmin(), AuthErrorZeppProvider())
    assert payload["wellness"]["provider_status"]["zepp"]["status"] == "auth_error"
    assert payload["summary"]["activities"] == EXPECTED_GARMIN_ACTIVITIES
    assert payload["wellness"]["effective"]["sleep"]["source"] == "garmin"
```

- [ ] **Step 2: Run the end-to-end test to verify it fails**

Run: `cd apps/sync-local && python -m unittest tests.test_zepp_sync_payload.ZeppSyncPayloadTests.test_end_to_end_auth_error_keeps_garmin_activity_and_allowed_fallbacks -v`

Expected: FAIL until the complete sync and resolver paths compose correctly.

- [ ] **Step 3: Add setup and operational documentation**

Document that the user installs the local sync dependencies, puts the three Zepp values only in the root `.env`, refreshes an expired `ZEPP_TOKEN` from the Zepp account, and runs `scripts/run_sync.sh`. State that a Zepp failure leaves Garmin activities and permitted Garmin fallbacks working, while `stress` and Zepp-only load metrics remain absent rather than being substituted.

- [ ] **Step 4: Run targeted end-to-end scenarios to verify they pass**

Run: `cd apps/sync-local && python -m unittest tests.test_zepp_sync_payload tests.test_wellness_models tests.test_zepp_provider tests.test_wellness_resolver -v`

Expected: PASS for Zepp OK, partial, disabled/auth error, historical Garmin fallback, atomic sleep and no Zepp activities.

- [ ] **Step 5: Run both project suites**

Run: `cd apps/sync-local && python -m unittest discover -s tests -v && cd ../bot && python -m unittest discover -s tests -v`

Expected: PASS. Record any existing failure by exact test name and do not claim a clean suite if one remains.

- [ ] **Step 6: Commit Task 6**

```bash
git add README.md .env.example apps/sync-local/tests/test_zepp_sync_payload.py apps/bot/tests/test_wellness_persistence.py
git commit -m "docs: document Zepp Helio wellness sync"
```

## Plan Self-Review

- **Spec coverage:** Tasks 1–3 cover isolation, normalization, shared lookback, timezone, sleep semantics, status and the one-pass effective alias. Task 4 covers date/source upserts in both stores. Task 5 covers source-aware Telegram and Ollama. Task 6 exercises supported healthy and degraded paths and documents local configuration.
- **Placeholder scan:** No deferred implementation markers or generic test instructions remain; every task includes an interface, a failing test, a command, an implementation direction and a commit.
- **Type consistency:** Task 1 produces ISO-date keyed `ProviderDayResult`; Task 3 serializes them and passes raw normalized dictionaries to Task 2's `resolve_wellness`; Task 4 consumes the resulting v2 payload; Task 5 only reads the v2 `effective` view through one adapter.
- **Review focus coverage:** The five listed high-risk input classes are tested respectively in Tasks 2, 2, 1, 1 and 3.
