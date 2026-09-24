# Zepp Activity Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import recent Zepp activities as a provenance-labelled fallback for missing Garmin activities and expose `/sync zepp` to request an immediate local import.

**Architecture:** `ZeppActivityProvider` owns the undocumented Zepp history endpoint and returns compact provider-normalized records. A pure merge layer joins them with Garmin-normalized records and only removes a Zepp record when it can prove the two describe the same session; summaries keep consuming one chronological common activity list. Telegram stores an explicit requested-sync mode, while the Mac publishes one complete payload.

**Tech Stack:** Python 3.13, `requests`, `httpx`, `unittest`, FastAPI, Telegram webhook routing, existing Garmin sync and running-load analytics.

**Spec:** [2026-09-24-zepp-activity-import-design.md](../specs/2026-09-24-zepp-activity-import-design.md)

## Global Constraints

- Use `ZEPP_TOKEN`, `ZEPP_USER_ID` and `ZEPP_BASE_URL` only on the Mac; never log, persist or POST credentials to Railway.
- The Zepp activity client sends `appPlatform: web` and `appname: com.xiaomi.hm.health`, not the iOS header profile used by unrelated endpoints.
- `ZEPP_ACTIVITY_SYNC_LOOKBACK_DAYS=3` includes today plus the preceding two local dates in `GARMIN_COACH_TIMEZONE`.
- Keep Zepp `exercise_load` only as `provider_exercise_load`; never populate or sum Garmin `training_load` with it.
- Garmin wins only after all duplicate criteria in the spec are met; an uncertain match preserves both activities.
- Zepp-only activities join common summaries and estimated TRIMP when profile inputs permit it, but never Wattwise, Garmin power, Garmin Training Effect or Garmin FIT-file flows.
- `/sync zepp` is a complete local sync requested with `mode: "zepp_activities"`; `/sync` remains `mode: "full"`.

## Review Focus

- A valid response with an empty `data.summary` must publish `ok` and no activities rather than fail Garmin sync. Task 1 covers it.
- A same-sport run whose starts are eleven minutes apart must not be discarded. Task 2 covers it.
- A time-overlapping run whose distances differ by more than 10% must be preserved twice. Task 2 covers it.
- A Zepp activity missing average HR must count in duration/distance but not receive invented TRIMP. Task 2 covers it.
- `/sync zepp extra` must be rejected, not silently converted into a full sync. Task 3 covers it.

---

## File Structure

- Create `apps/sync-local/garmin_sync/zepp_activity_provider.py`: Zepp web-header client, statuses, timestamp/unit validation and raw-to-common normalization.
- Create `apps/sync-local/garmin_sync/activity_merge.py`: pure source-aware deduplication and ordering of normalized activities.
- Create `apps/sync-local/tests/test_zepp_activity_provider.py`: provider request, normalization, validation and redaction tests.
- Create `apps/sync-local/tests/test_activity_merge.py`: exact duplicate and safe non-duplicate merge tests.
- Modify `apps/sync-local/garmin_sync/sync.py`: source/timestamp fields for Garmin activities, Zepp collection/merge, normalized-summary entry point and activity-provider status.
- Modify `apps/sync-local/tests/test_zepp_sync_payload.py`: fallback, duplicate and Garmin-regression payload tests.
- Modify `apps/bot/app/store.py`, `apps/bot/app/main.py`, `apps/bot/app/coach.py`, and `apps/sync-local/garmin_sync/requested_sync.py`: requested-sync mode, validation and response text.
- Create `apps/bot/tests/test_sync_request.py`; modify `apps/bot/tests/test_coach_routing.py`, `apps/bot/tests/test_daily_week_coach.py`, `apps/sync-local/tests/test_ai_checkin_context.py`, `.env.example`, and `README.md`.

### Task 1: Add the isolated Zepp activity provider

**Files:**
- Create: `apps/sync-local/garmin_sync/zepp_activity_provider.py`
- Create: `apps/sync-local/tests/test_zepp_activity_provider.py`
- Modify: `.env.example`

**Interfaces:**
- Produces `ZeppActivityProvider(token, user_id, base_url=None, timezone_name="Europe/Madrid")`.
- Produces `fetch_activities(start_day: date, end_day: date) -> tuple[list[dict[str, Any]], dict[str, Any]]`.
- Each emitted activity has `id`, `source`, `source_activity_id`, `date`, `started_at`, `name`, `sport`, `type`, `km`, `duration_s`, `hours`; optional common metrics are emitted only if valid.

- [ ] **Step 1: Write the failing provider and normalization tests**

```python
RAW_RUN = {
    "trackid": "track-42", "source": "run.watch.helio.zepp.com",
    "sport_title": "Correr al aire libre", "sport_mode": 7,
    "end_time": "1790002518", "run_time": "2518", "dis": "8020",
    "avg_pace": "312", "avg_heart_rate": "151", "max_heart_rate": 174,
    "calorie": "613", "altitude_ascend": 88, "exercise_load": 92,
}

def test_fetch_activities_uses_web_headers_and_normalizes_a_run() -> None:
    provider = ZeppActivityProvider("secret", "42", "https://example.test", "Europe/Madrid")
    provider._get = fake_history_response({"code": 1, "data": {"summary": [RAW_RUN]}})
    activities, status = provider.fetch_activities(date(2026, 9, 24), date(2026, 9, 24))
    assert activities[0]["id"] == "zepp:run.watch.helio.zepp.com:track-42"
    assert activities[0]["source"] == "zepp"
    assert activities[0]["km"] == 8.02
    assert activities[0]["duration_s"] == 2518
    assert activities[0]["provider_exercise_load"] == {"value": 92, "source": "zepp"}
    assert status["status"] == "ok"
    assert provider.last_headers == {"apptoken": "secret", "appPlatform": "web", "appname": "com.xiaomi.hm.health"}

def test_empty_zepp_history_is_a_success_with_no_activities() -> None:
    provider = ZeppActivityProvider("secret", "42")
    provider._get = fake_history_response({"code": 1, "data": {"summary": []}})
    activities, status = provider.fetch_activities(date(2026, 9, 24), date(2026, 9, 24))
    assert activities == []
    assert status == {"status": "ok", "records_received": 0}
```

Add separate tests for missing credentials (`disabled` without a request), 401 (`auth_error` without token leakage), malformed payload (`invalid_data`), invalid duration/distance (record skipped), and seconds/milliseconds/ISO timestamps converted to the configured timezone.

- [ ] **Step 2: Run the new tests and verify they fail because the provider does not exist**

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_zepp_activity_provider -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'garmin_sync.zepp_activity_provider'`.

- [ ] **Step 3: Implement the provider and minimal normalizer**

```python
class ZeppActivityProvider:
    WEB_HEADERS = {"appPlatform": "web", "appname": "com.xiaomi.hm.health"}

    def fetch_activities(self, start_day: date, end_day: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self._token or not self._user_id:
            return [], {"status": "disabled", "records_received": 0}
        try:
            records = _history_records(self._get("/v1/sport/run/history.json", {"userid": self._user_id}))
        except Exception as exc:
            return [], self._error_status(exc)
        rows = [row for row in (_normalize_record(record, self._timezone) for record in records) if row]
        rows = [row for row in rows if start_day <= date.fromisoformat(row["date"]) <= end_day]
        return sorted(rows, key=lambda row: (row["started_at"], row["id"])), {"status": "ok", "records_received": len(rows)}
```

Implement `_get()` through `requests.get` with `apptoken`, the exact web headers and 30-second timeout, never logging raw responses. `_history_records()` accepts only `{code: 1, data: {summary: list}}`. Parse `end_time` as ISO, Unix seconds or Unix milliseconds; derive `started_at` by subtracting positive `run_time` seconds. Convert `dis` metres to kilometres and build pace from distance/duration. Titles containing `run`, `correr` or `running` map to `running`; unknown titles map to `other`. Store `exercise_load` only as `provider_exercise_load`. Add `ZEPP_ACTIVITY_SYNC_LOOKBACK_DAYS=3` and its comment to `.env.example`.

- [ ] **Step 4: Run the provider tests and verify they pass**

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_zepp_activity_provider -v`

Expected: PASS; headers, safe empty history, conversions, date filtering and status redaction are proven.

- [ ] **Step 5: Commit the provider deliverable**

```bash
git add apps/sync-local/garmin_sync/zepp_activity_provider.py apps/sync-local/tests/test_zepp_activity_provider.py .env.example && git commit -m "feat: add Zepp activity provider"
```

### Task 2: Merge Zepp and Garmin activities without double counting

**Files:**
- Create: `apps/sync-local/garmin_sync/activity_merge.py`
- Create: `apps/sync-local/tests/test_activity_merge.py`
- Modify: `apps/sync-local/garmin_sync/sync.py:108-187,854-875`
- Modify: `apps/sync-local/tests/test_zepp_sync_payload.py`

**Interfaces:**
- Consumes normalized records from Task 1 and the Garmin-normalized dictionaries produced by `normalize_activities()`.
- Produces `merge_activities(garmin: list[dict[str, Any]], zepp: list[dict[str, Any]]) -> list[dict[str, Any]]`.
- Produces `summarize_normalized(activities: list[dict[str, Any]], profile: dict[str, Any] | None = None) -> dict[str, Any]`; `summarize(raw_activities, profile)` retains raw-Garmin compatibility.

- [ ] **Step 1: Write failing merge and summary tests**

```python
def test_matching_garmin_and_zepp_run_keeps_garmin_only() -> None:
    merged = merge_activities(
        [activity("garmin-1", "garmin", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
        [activity("zepp:run:42", "zepp", "2026-09-24T07:27:00+02:00", 8.10, 2500)],
    )
    assert [item["id"] for item in merged] == ["garmin-1"]

def test_zepp_run_enters_common_summary_when_garmin_is_absent() -> None:
    summary = summarize_normalized(
        [activity("zepp:run:42", "zepp", "2026-09-24T07:25:00+02:00", 8.02, 2518, avg_hr=151)],
        {"profile": {"max_hr": 190, "resting_hr": 50, "sex": "hombre"}},
    )
    assert summary["today"]["km"] == 8.0
    assert summary["activities"][0]["source"] == "zepp"
    assert summary["running_load"]["latest"]["source"] == "trimp_estimado"
```

Add tests that preserve an eleven-minute-apart run, preserve a same-time run with distance difference greater than 10%, retain two independent Zepp ids, and retain a Zepp run with no HR but no `running_load`.

- [ ] **Step 2: Run merge tests and verify they fail because the merge layer does not exist**

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_activity_merge -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'garmin_sync.activity_merge'`.

- [ ] **Step 3: Implement pure duplicate detection and make summary consume normalized records**

```python
def merge_activities(garmin: list[dict[str, Any]], zepp: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_garmin = _unique_by_id(garmin)
    kept_zepp = [item for item in _unique_by_id(zepp) if not any(_is_duplicate(g, item) for g in unique_garmin)]
    return sorted(unique_garmin + kept_zepp, key=lambda item: (item.get("started_at", item["date"]), item["id"]))

def _is_duplicate(garmin: dict[str, Any], zepp: dict[str, Any]) -> bool:
    return (
        garmin.get("sport") == zepp.get("sport")
        and _start_difference_seconds(garmin, zepp) < 600
        and _overlap_fraction(garmin, zepp) >= 0.70
        and _distance_matches_when_available(garmin, zepp)
    )
```

Add `source: "garmin"` and offset-aware `started_at` to `compact_activity()` from the Garmin local-or-GMT start field, preserving all existing fields. Move the current body of `summarize()` to `summarize_normalized()`; retain `summarize()` as `summarize_normalized(normalize_activities(...), profile)`. Do not set `training_load` from Zepp; existing running analytics uses Banister TRIMP only when profile inputs permit it.

- [ ] **Step 4: Run merge, payload and analytics tests**

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_activity_merge tests.test_zepp_sync_payload tests.test_running_analytics -v`

Expected: PASS; a missing Garmin record enters summaries, Garmin wins only a proven duplicate, uncertain records remain, and existing Garmin summaries are unchanged.

- [ ] **Step 5: Write the failing payload wiring test**

```python
def test_build_payload_merges_a_zepp_only_run_and_publishes_status() -> None:
    with patched_garmin_and_zepp_activity_provider(zepp_activities=[ZEPPRUN]):
        payload = sync.build_payload()
    assert payload["summary"]["activities"][-1]["source"] == "zepp"
    assert payload["activity_provider_status"]["zepp"]["status"] == "ok"
```

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_zepp_sync_payload.ZeppSyncPayloadTests.test_build_payload_merges_a_zepp_only_run_and_publishes_status -v`

Expected: FAIL because `build_payload()` has not collected `ZeppActivityProvider` results.

- [ ] **Step 6: Implement payload wiring and re-run focused integration tests**

Instantiate `ZeppActivityProvider` in `build_payload()` with current Zepp credentials and athlete timezone. Calculate the configured lookback window, fetch Zepp records, normalize Garmin records, merge both lists, call `summarize_normalized()`, and publish `activity_provider_status: {"zepp": status}`. Continue building wellness and physiology exactly as before; do not turn Zepp wellness movement segments into activities.

Run: `cd apps/sync-local && .venv/bin/python -m unittest tests.test_zepp_sync_payload tests.test_activity_merge tests.test_zepp_activity_provider -v`

Expected: PASS; the provider is isolated and Garmin still owns any duplicate activity.

- [ ] **Step 7: Commit the activity merge deliverable**

```bash
git add apps/sync-local/garmin_sync/activity_merge.py apps/sync-local/garmin_sync/sync.py apps/sync-local/tests/test_activity_merge.py apps/sync-local/tests/test_zepp_sync_payload.py && git commit -m "feat: merge Zepp activity fallback into sync"
```

### Task 3: Request an explicit Zepp activity sync from Telegram

**Files:**
- Modify: `apps/bot/app/store.py:327-370`
- Modify: `apps/bot/app/main.py:101-115,419-490`
- Modify: `apps/bot/app/coach.py:129-140`
- Modify: `apps/sync-local/garmin_sync/requested_sync.py:50-80`
- Create: `apps/bot/tests/test_sync_request.py`
- Create: `apps/sync-local/tests/test_requested_sync.py`
- Modify: `apps/bot/tests/test_coach_routing.py`

**Interfaces:**
- `save_sync_request(requested_by: str | None = None, mode: Literal["full", "zepp_activities"] = "full") -> dict[str, Any]`.
- `POST /sync/request` validates `payload["mode"]` from those values.
- Telegram `/sync` maps no argument to `full` and exact `zepp` to `zepp_activities`.
- `requested_sync.main()` calls existing `run_full_sync()` for either mode and completes after payload publication.

- [ ] **Step 1: Write failing backend and Telegram routing tests**

```python
def test_sync_zepp_command_persists_activity_mode() -> None:
    response = client.post("/telegram/webhook", json=telegram_update("/sync zepp"))
    assert "actividades Zepp" in response.json()["text"]
    assert load_sync_request()["mode"] == "zepp_activities"

def test_sync_command_rejects_extra_arguments() -> None:
    response = client.post("/telegram/webhook", json=telegram_update("/sync zepp ahora"))
    assert "Uso: /sync o /sync zepp" in response.json()["text"]

def test_requested_zepp_sync_runs_full_local_sync_and_completes_request() -> None:
    request = {"status": "pending", "mode": "zepp_activities"}
    with patched_request_state(request) as run_full_sync:
        assert requested_sync.main() == 0
    run_full_sync.assert_called_once_with()
```

Add API tests that accept `full` and `zepp_activities`, reject another mode with HTTP 400, and preserve mode after successful and failed completion.

- [ ] **Step 2: Run routing tests and verify they fail because mode is unsupported**

Run: `cd apps/bot && python -m unittest tests.test_sync_request tests.test_coach_routing -v`

Expected: FAIL because `save_sync_request()` has no mode, `/sync zepp` is not validated and feedback lacks the Zepp label.

- [ ] **Step 3: Implement mode persistence, validation and feedback**

```python
VALID_SYNC_MODES = {"full", "zepp_activities"}

def save_sync_request(requested_by: str | None = None, mode: str = "full") -> dict[str, Any]:
    if mode not in VALID_SYNC_MODES:
        raise ValueError("invalid sync mode")
    return {"requested_at": datetime.now(timezone.utc).isoformat(), "requested_by": requested_by, "mode": mode, "status": "pending"}
```

In Telegram routing accept no argument or the case-insensitive exact token `zepp`; reply `Uso: /sync o /sync zepp` for any other argument. Extend `format_sync_requested()` with `Modo: actividades Zepp recientes` only for `zepp_activities`. Convert invalid API modes into HTTP 400. In `requested_sync.py`, read mode only for its status message, call `run_full_sync()` once and preserve existing completion semantics.

- [ ] **Step 4: Run bot and local requested-sync tests**

Run: `cd apps/bot && python -m unittest tests.test_sync_request tests.test_coach_routing -v && cd ../sync-local && .venv/bin/python -m unittest tests.test_requested_sync -v`

Expected: PASS; `/sync` is backward-compatible, `/sync zepp` is explicit, and the watcher never performs a partial or repeated sync.

- [ ] **Step 5: Commit the requested-sync deliverable**

```bash
git add apps/bot/app/store.py apps/bot/app/main.py apps/bot/app/coach.py apps/sync-local/garmin_sync/requested_sync.py apps/bot/tests/test_sync_request.py apps/bot/tests/test_coach_routing.py apps/sync-local/tests/test_requested_sync.py && git commit -m "feat: request Zepp activity sync from Telegram"
```

### Task 4: Surface Zepp provenance, document operation, and verify end to end

**Files:**
- Modify: `apps/bot/app/coach.py:630-660,1181-1255`
- Modify: `apps/bot/tests/test_daily_week_coach.py`
- Modify: `apps/sync-local/garmin_sync/ai_worker.py:1215-1250`
- Modify: `apps/sync-local/tests/test_ai_checkin_context.py`
- Modify: `README.md:64-100,321-405`

**Interfaces:**
- `format_today()`, `format_latest()` and `format_feedback()` show `[Zepp]` for Zepp activities; Garmin messages remain unchanged.
- `compact_context()` preserves `source`, `source_activity_id` and common fields in `recent_activities`, without raw provider payloads.

- [ ] **Step 1: Write failing user-visible and AI-context tests**

```python
def test_latest_zepp_activity_is_labelled_and_keeps_common_metrics() -> None:
    answer = format_latest(sync_with_zepp_run())
    assert "[Zepp]" in answer
    assert "Distancia: 8.02 km" in answer
    assert "Pulso medio:" in answer
    assert "Training effect:" not in answer

def test_ai_context_keeps_zepp_provenance_without_raw_history_payload() -> None:
    activities = compact_context(context_with_zepp_run())["extra_context"]["recent_activities"]
    assert activities[0]["source"] == "zepp"
    assert activities[0]["source_activity_id"] == "track-42"
    assert "originSummary" not in activities[0]
```

Add a test that Garmin activity text has no Zepp suffix and Zepp activity output never fabricates power or Wattwise data.

- [ ] **Step 2: Run presentation tests and verify they fail before source rendering is added**

Run: `cd apps/bot && python -m unittest tests.test_daily_week_coach -v && cd ../sync-local && .venv/bin/python -m unittest tests.test_ai_checkin_context -v`

Expected: FAIL because activity formatters do not render source provenance.

- [ ] **Step 3: Implement provenance rendering and concise AI context**

```python
def _activity_source_suffix(activity: dict[str, Any]) -> str:
    return " [Zepp]" if activity.get("source") == "zepp" else ""
```

Append the helper only to activity labels and activity-derived load lines in the three formatters. Do not alter effective-wellness labels. Keep `recent_activities` as compact common dictionaries; never append raw Zepp response data. Document `ZEPP_ACTIVITY_SYNC_LOOKBACK_DAYS=3`, `/sync zepp`, and the requirement that the mobile app must publish the workout to Zepp Cloud first.

- [ ] **Step 4: Run the complete verification suite**

Run: `cd apps/sync-local && .venv/bin/python -m unittest discover -s tests -v && cd ../bot && python -m unittest discover -s tests -v`

Expected: PASS with all local-sync and bot tests green. Run `git diff --check` and inspect the staged diff to confirm it contains no `.env` values, token, user id, raw routes or raw Zepp records.

- [ ] **Step 5: Commit user-facing work**

```bash
git add apps/bot/app/coach.py apps/bot/tests/test_daily_week_coach.py apps/sync-local/garmin_sync/ai_worker.py apps/sync-local/tests/test_ai_checkin_context.py README.md && git commit -m "feat: label Zepp activities in coaching"
```
