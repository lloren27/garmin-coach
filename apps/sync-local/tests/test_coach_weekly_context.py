"""Verified week plans carried from the bot API to an immutable V3 snapshot."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from unittest.mock import patch
import unittest

import httpx

from garmin_sync import ai_worker as worker
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_validation import CoachValidationError


JOB_TIME = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
MONDAY = date(2026, 10, 26)
SCOPE = {"monday": "2026-10-26", "sunday": "2026-11-01", "reference_day": "2026-10-28"}


def week_payload():
    return {
        "week_start": "2026-10-26", "week_end": "2026-11-01", "owner_id": "alice",
        "plans": [
            {
                "id": "old", "owner_id": "alice", "revision": 1, "status": "superseded",
                "start_date": "2026-10-26", "end_date": "2026-11-01",
                "created_at": "2026-10-25T08:00:00+00:00", "updated_at": "2026-10-28T14:00:00+00:00",
                "sessions": [{
                    "id": "run", "training_plan_id": "old", "owner_id": "alice",
                    "date": "2026-10-27", "sequence": 0, "sport": "running", "session_type": "easy",
                    "duration_min": 40, "duration_max": 50, "status": "planned", "optional": False,
                    "created_at": "2026-10-25T08:00:00+00:00", "updated_at": "2026-10-25T08:00:00+00:00",
                }],
            },
            {
                "id": "new", "owner_id": "alice", "revision": 2, "status": "active",
                "start_date": "2026-10-28", "end_date": "2026-11-03",
                "created_at": "2026-10-28T10:00:00+00:00", "updated_at": "2026-10-28T10:00:00+00:00",
                "sessions": [{
                    "id": "bike", "training_plan_id": "new", "owner_id": "alice",
                    "date": "2026-11-02", "sequence": 0, "sport": "cycling", "session_type": "easy",
                    "status": "planned", "optional": True,
                    "created_at": "2026-10-28T10:00:00+00:00", "updated_at": "2026-10-28T10:00:00+00:00",
                }],
            },
        ],
    }


def weekly_compact(payload=None, *, status="available"):
    return {"extra_context": {
        "week_scope": deepcopy(SCOPE), "week_owner_id": "alice",
        "week_context_status": status,
        "week_plans": deepcopy(payload) if payload is not None else None,
        "recent_activities": [{
            "id": "ride-1", "source": "strava", "sport": "cycling", "type": "Ride",
            "date": "2026-10-27", "local_date": "2026-10-27",
            "started_at_utc": "2026-10-27T07:00:00Z", "started_at": "2026-10-27T08:00:00+01:00",
            "time_context": "Europe/Madrid", "duration_s": 3600,
        }],
        "activity_provider_status": {
            "garmin": {"status": "ok", "records_received": 1,
                       "period_start": "2026-10-26", "period_end": "2026-11-01",
                       "last_success_at": "2026-10-28T11:00:00Z"},
            "strava": {"status": "network_error", "records_received": None,
                       "period_start": None, "period_end": None,
                       "failed_dates": ["2026-10-27"]},
            "zepp": {"status": "ok", "records_received": 0,
                     "last_success_at": "2026-10-28T11:00:00Z"},
        },
    }}


def http_error(status, body=None):
    request = httpx.Request("GET", "https://api.example/ai/jobs/job-1/week-plans")
    response = httpx.Response(status, json=body or {}, request=request)
    return httpx.HTTPStatusError("API error", request=request, response=response)


class FetchWeekPlansTests(unittest.TestCase):
    def test_fetches_only_job_scoped_week_endpoint(self):
        payload = week_payload()
        with patch.object(worker, "get_json", return_value=payload) as get:
            self.assertEqual(worker.fetch_week_plans("job-1", MONDAY), payload)
        get.assert_called_once_with("/ai/jobs/job-1/week-plans?week_start=2026-10-26")

    def test_typed_missing_job_and_auth_errors_are_not_rollback(self):
        for error in (http_error(404, {"detail": {"code": "job_not_found"}}),
                      http_error(401), http_error(403)):
            with self.subTest(status=error.response.status_code), patch.object(worker, "get_json", side_effect=error) as get:
                with self.assertRaises(httpx.HTTPStatusError):
                    worker.fetch_week_plans("job-1", MONDAY)
                self.assertEqual(get.call_count, 1)

    def test_404_or_405_degrades_only_when_openapi_confirms_route_absent(self):
        schema_without_route = {"paths": {"/ai/jobs/{job_id}": {"get": {}}}}
        for status in (404, 405):
            with self.subTest(status=status), patch.object(worker, "get_json",
                    side_effect=[http_error(status), schema_without_route]) as get:
                self.assertEqual(worker.fetch_week_plans("job-1", MONDAY),
                                 {"week_context_status": "unavailable"})
                self.assertEqual(get.call_args_list[1].args[0], "/openapi.json")

    def test_route_present_or_openapi_unreachable_preserves_original_error(self):
        schema_with_route = {"paths": {"/ai/jobs/{job_id}/week-plans": {"get": {}}}}
        malformed_route = {"paths": {"/ai/jobs/{job_id}/week-plans": None}}
        for schema in (schema_with_route, malformed_route, httpx.ConnectError("offline"), {"paths": None}):
            with self.subTest(schema=schema), patch.object(worker, "get_json",
                    side_effect=[http_error(404), schema]):
                with self.assertRaises(httpx.HTTPStatusError):
                    worker.fetch_week_plans("job-1", MONDAY)


class WeeklyContextTests(unittest.TestCase):
    def test_process_job_attaches_week_context_before_v3_generation(self):
        job = {"id": "job-1", "chat_id": "alice", "text": "Analiza mi entrenamiento de hoy",
               "created_at": JOB_TIME.isoformat()}
        result = worker.CoachRunResult("Respuesta", None, "deterministic")
        with patch.object(worker, "COACH_ANALYSIS_V3_ENABLED", True), \
             patch.object(worker, "enrich_context_for_question", return_value={}), \
             patch.object(worker, "fetch_wattwise_context", return_value=None), \
             patch.object(worker, "fetch_week_plans", return_value=week_payload()) as fetch, \
             patch.object(worker, "call_coach", return_value=result) as call, \
             patch.object(worker, "complete_coach_job"), \
             patch.object(worker, "start_telegram_processing_indicator", return_value=None), \
             patch.object(worker, "stop_telegram_processing_indicator"), \
             patch.object(worker, "late_response_details", return_value=("on_time", None, None)):
            worker.process_job(job, {})
        fetch.assert_called_once_with("job-1", MONDAY)
        self.assertEqual(call.call_args.args[1]["week_scope"], SCOPE)
        self.assertEqual(call.call_args.kwargs["now"], JOB_TIME)

    def test_evaluative_job_uses_creation_week_and_owner_and_compacts_context(self):
        job = {"id": "job-1", "chat_id": "alice", "created_at": JOB_TIME.isoformat()}
        with patch.object(worker, "fetch_week_plans", return_value=week_payload()) as fetch:
            context = worker.add_week_assessment_context(
                "Analiza mi entrenamiento de hoy", job, {"training_plan": {"id": "active"}},
            )
        fetch.assert_called_once_with("job-1", MONDAY)
        self.assertEqual(context["week_scope"], SCOPE)
        self.assertEqual(context["week_owner_id"], "alice")
        self.assertEqual(context["week_context_status"], "available")
        compact = worker.compact_context(context, now=JOB_TIME)
        self.assertEqual(compact["extra_context"]["week_plans"], week_payload())
        self.assertEqual(compact["extra_context"]["week_scope"], SCOPE)
        self.assertEqual(compact["extra_context"]["training_plan"]["id"], "active")

    def test_sunday_job_processed_after_midnight_keeps_sunday_week(self):
        sunday_job = {"id": "job-1", "chat_id": "alice",
                      "created_at": "2026-11-01T22:30:00+00:00"}
        with patch.object(worker, "fetch_week_plans", return_value=worker.WEEK_PLANS_UNAVAILABLE) as fetch:
            context = worker.add_week_assessment_context("Analiza mi entrenamiento de hoy", sunday_job, {})
        fetch.assert_called_once_with("job-1", MONDAY)
        self.assertEqual(context["week_scope"]["reference_day"], "2026-11-01")
        self.assertEqual(context["week_context_status"], "unavailable")
        self.assertIsNone(context["week_plans"])

    def test_unavailable_marker_in_success_body_does_not_forge_rollback(self):
        job = {"id": "job-1", "chat_id": "alice", "created_at": JOB_TIME.isoformat()}
        with patch.object(worker, "fetch_week_plans", return_value={"week_context_status": "unavailable"}):
            context = worker.add_week_assessment_context("Analiza mi entrenamiento de hoy", job, {})
        self.assertEqual(context["week_context_status"], "available")
        with self.assertRaises(CoachValidationError):
            build_snapshot("Analiza mi entrenamiento de hoy", worker.compact_context(context, now=JOB_TIME), now=JOB_TIME)

    def test_factual_alias_plan_metric_and_change_do_not_fetch_week(self):
        job = {"id": "job-1", "chat_id": "alice", "created_at": JOB_TIME.isoformat()}
        for question, factual_scope in (
            ("Analiza mi entrenamiento de hoy", "today"),
            ("¿Qué toca mañana?", None),
            ("Analiza el pulso máximo de mi entrenamiento de hoy", None),
            ("Cambia mi entrenamiento de hoy", None),
        ):
            with self.subTest(question=question), patch.object(worker, "fetch_week_plans") as fetch:
                unchanged = worker.add_week_assessment_context(
                    question, {**job, "factual_scope": factual_scope}, {"marker": 1},
                )
                self.assertEqual(unchanged, {"marker": 1})
                fetch.assert_not_called()

    def test_snapshot_validates_and_freezes_two_plans_activity_type_and_provider_coverage(self):
        compact = weekly_compact(week_payload())
        snapshot = build_snapshot("Analiza mi entrenamiento de hoy", compact, now=JOB_TIME)
        self.assertEqual([plan["id"] for plan in snapshot.week_plans], ["old", "new"])
        self.assertEqual(snapshot.week_scope.reference_day.isoformat(), "2026-10-28")
        self.assertEqual(snapshot.week_context_status, "available")
        self.assertEqual(snapshot.evidence["activity:ride-1"].activity_type, "Ride")
        self.assertEqual(snapshot.evidence["activity:ride-1"].started_at_utc, "2026-10-27T07:00:00Z")
        self.assertEqual(snapshot.provider_status["garmin.activities"]["period_start"], "2026-10-26")
        self.assertEqual(snapshot.provider_status["strava.activities"]["state"], "provider_error")
        self.assertIsNone(snapshot.provider_status["strava.activities"]["period_start"])
        self.assertIsNone(snapshot.provider_status["zepp.activities"]["period_start"])
        self.assertEqual(snapshot.provider_status["zepp.activities"]["records_received"], 0)
        compact["extra_context"]["week_plans"]["plans"][0]["sessions"][0]["date"] = "2026-10-29"
        self.assertEqual(snapshot.week_plans[0]["sessions"][0]["date"], "2026-10-27")
        with self.assertRaises(TypeError):
            snapshot.week_plans[0]["sessions"][0]["date"] = "2026-10-29"

    def test_verified_empty_plans_differs_from_unavailable_endpoint(self):
        verified = weekly_compact({**week_payload(), "plans": []})
        missing = weekly_compact(status="unavailable")
        self.assertEqual(build_snapshot("Analiza mi entrenamiento de hoy", verified, now=JOB_TIME).week_plans, ())
        unavailable = build_snapshot("Analiza mi entrenamiento de hoy", missing, now=JOB_TIME)
        self.assertIsNone(unavailable.week_plans)
        self.assertEqual(unavailable.week_context_status, "unavailable")

    def test_weekly_snapshot_retains_activity_with_type_and_date_but_no_numeric_metrics(self):
        compact = weekly_compact(week_payload())
        compact["extra_context"]["recent_activities"] = [{
            "id": "ride-without-metrics", "source": "strava", "sport": "cycling",
            "type": "Ride", "local_date": "2026-10-27",
            "started_at_utc": "2026-10-27T07:00:00Z",
        }]
        snapshot = build_snapshot("Analiza mi entrenamiento de hoy", compact, now=JOB_TIME)
        activity = snapshot.evidence["activity:ride-without-metrics"]
        self.assertEqual(activity.activity_type, "Ride")
        self.assertEqual(activity.facts, {})

    def test_rejects_foreign_duplicate_out_of_interval_or_incoherent_plan_context(self):
        mutations = (
            lambda p: p.update(owner_id="bob"),
            lambda p: p.update(week_start="2026-10-19"),
            lambda p: p["plans"][0].update(owner_id="bob"),
            lambda p: p["plans"][1].update(id="old"),
            lambda p: p["plans"][0].update(revision=0),
            lambda p: p["plans"][0].update(created_at="2026-10-29T08:00:00Z"),
            lambda p: p["plans"][0].update(updated_at="2026-10-24T08:00:00Z"),
            lambda p: p["plans"][0].pop("created_at"),
            lambda p: p["plans"][0]["sessions"][0].update(owner_id="bob"),
            lambda p: p["plans"][0]["sessions"][0].update(date="2026-11-02"),
            lambda p: p["plans"][0]["sessions"][0].update(created_at="2026-10-29T08:00:00Z"),
            lambda p: p["plans"][0]["sessions"][0].pop("updated_at"),
            lambda p: p["plans"][1]["sessions"][0].update(id="run"),
        )
        for mutate in mutations:
            payload = week_payload()
            mutate(payload)
            with self.subTest(payload=payload), self.assertRaises(CoachValidationError):
                build_snapshot("Analiza mi entrenamiento de hoy", weekly_compact(payload), now=JOB_TIME)

    def test_incoherent_week_context_fails_v3_job_instead_of_returning_safe_answer(self):
        context = {"week_scope": deepcopy(SCOPE), "week_owner_id": "alice",
                   "week_context_status": "available", "week_plans": week_payload()}
        context["week_plans"]["owner_id"] = "bob"
        with patch.object(worker, "COACH_ANALYSIS_V3_ENABLED", True):
            with self.assertRaises(CoachValidationError):
                worker.call_coach("Analiza mi entrenamiento de hoy", context, now=JOB_TIME)


if __name__ == "__main__":
    unittest.main()
