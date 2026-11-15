"""Weekly coach assessment uses only verified week context."""

from datetime import datetime, timezone
import unittest

from garmin_sync.coach_deterministic import deterministic_response
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_weekly_assessment import assess_week, render_week_assessment


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
QUESTION = "Analiza mi entrenamiento de hoy y cómo afecta a esta semana"


def _session(identifier, day, sport, kind, *, optional=False):
    stamp = "2026-10-28T07:00:00+00:00"
    return {
        "id": identifier, "training_plan_id": "plan-new", "owner_id": "alice",
        "date": day, "sequence": 0, "sport": sport, "session_type": kind,
        "status": "planned", "optional": optional,
        "duration_min": 35, "duration_max": 45,
        "created_at": stamp, "updated_at": stamp,
    }


def _compact(*, status="available", activities=None, checkins=None):
    plan = {
        "id": "plan-new", "owner_id": "alice", "revision": 1,
        "status": "active", "start_date": "2026-10-28", "end_date": "2026-11-03",
        "created_at": "2026-10-28T07:00:00+00:00",
        "updated_at": "2026-10-28T07:00:00+00:00",
        "sessions": [
            _session("run-today", "2026-10-28", "running", "easy"),
            _session("strength-friday", "2026-10-30", "strength", "full_body_a"),
            _session("run-sunday", "2026-11-01", "running", "long_run"),
            _session("bike-monday", "2026-11-02", "cycling", "easy", optional=True),
        ],
    }
    return {"extra_context": {
        "week_scope": {"monday": "2026-10-26", "sunday": "2026-11-01",
                       "reference_day": "2026-10-28"},
        "week_owner_id": "alice", "week_context_status": status,
        "week_plans": ({"week_start": "2026-10-26", "week_end": "2026-11-01",
                        "owner_id": "alice", "plans": [plan]}
                       if status == "available" else None),
        "recent_activities": activities if activities is not None else [
            {"id": "ride-tuesday", "source": "strava", "sport": "cycling",
             "type": "Ride", "date": "2026-10-27", "local_date": "2026-10-27",
             "started_at_utc": "2026-10-27T07:00:00Z", "duration_s": 3600,
             "distance_km": 27.5},
            {"id": "ride-today", "source": "strava", "sport": "cycling",
             "type": "Ride", "date": "2026-10-28", "local_date": "2026-10-28",
             "started_at_utc": "2026-10-28T08:00:00Z", "duration_s": 2700,
             "distance_km": 20.0},
            {"id": "strength-today", "source": "garmin", "sport": "strength",
             "type": "Strength", "date": "2026-10-28", "local_date": "2026-10-28",
             "started_at_utc": "2026-10-28T09:00:00Z", "duration_s": 1200},
        ],
        "activity_provider_status": {
            name: {"status": "ok", "records_received": 3,
                   "period_start": "2026-10-26", "period_end": "2026-11-01",
                   "last_success_at": "2026-10-28T11:00:00Z"}
            for name in ("garmin", "strava", "zepp")
        },
        "checkins": checkins or [],
        "training_plan": {"sessions": [
            {"id": "unrelated-old-plan", "date": "2026-10-27",
             "sport": "running", "session_type": "easy", "status": "planned"}]},
    }}


class WeeklyAssessmentTests(unittest.TestCase):
    def test_assess_week_uses_daily_historical_plan_and_keeps_future_sessions(self):
        snapshot = build_snapshot(QUESTION, _compact(), now=NOW)
        assessment = assess_week(snapshot)
        self.assertEqual((assessment.monday.isoformat(), assessment.sunday.isoformat()),
                         ("2026-10-26", "2026-11-01"))
        self.assertEqual(assessment.day_plans[1].status, "no_plan")
        self.assertTrue(any(r.day.isoformat() == "2026-10-27" and
                            "activity:ride-tuesday" in r.activity_ids
                            for r in assessment.relations))
        self.assertTrue(any(r.day.isoformat() == "2026-10-28" and
                            r.status == "other_sport_same_day" and
                            {"activity:ride-today", "activity:strength-today"} <= set(r.activity_ids)
                            for r in assessment.relations))
        self.assertEqual({s["id"] for s in assessment.future_sessions},
                         {"strength-friday", "run-sunday"})
        self.assertNotIn("unrelated-old-plan", assessment.evidence_refs)

    def test_response_explains_week_without_efficiency_verdict_or_plan_change(self):
        question = "¿Fue eficiente mi entrenamiento de hoy y cómo afecta a esta semana?"
        response = deterministic_response(question, _compact(), now=NOW)
        answer = response.answer.lower()
        self.assertIn("2026-10-26", answer)
        self.assertIn("2026-11-01", answer)
        self.assertIn("2026-10-28", answer)
        self.assertIn("ciclismo", answer)
        self.assertIn("fuerza", answer)
        self.assertIn("2026-10-30", answer)
        self.assertIn("sin plan verificable", answer)
        self.assertNotIn("fue eficiente", answer)
        self.assertNotIn("carga total", answer)
        self.assertIsNone(response.change_proposal)
        self.assertTrue(all(d.action in {"information_only", "ask_user"} for d in response.decisions))
        self.assertTrue(response.evidence)

    def test_added_activity_on_planned_day_is_not_called_no_plan(self):
        response = deterministic_response(QUESTION, _compact(), now=NOW)
        self.assertEqual(response.answer.count("2026-10-28:"), 1)
        self.assertIn("2026-10-27: ciclismo", response.answer)
        self.assertIn("sin plan verificable para esa fecha", response.answer)

    def test_unavailable_plan_context_only_reports_reference_day_facts(self):
        compact = _compact(status="unavailable")
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("No he podido verificar el plan de esta semana", response.answer)
        self.assertIn("2026-10-28", response.answer)
        self.assertIn("ciclismo", response.answer.lower())
        self.assertNotIn("2026-10-27", response.answer)
        self.assertNotIn("unrelated-old-plan", response.answer)
        self.assertIsNone(response.change_proposal)

    def test_unavailable_short_answer_keeps_plan_warning(self):
        response = deterministic_response(QUESTION, _compact(status="unavailable"),
                                          now=NOW, max_chars=80)
        self.assertIn("No he podido verificar el plan de esta semana", response.answer)

    def test_available_short_answer_respects_budget(self):
        response = deterministic_response(QUESTION, _compact(), now=NOW, max_chars=80)
        self.assertLessEqual(len(response.answer), 80)
        self.assertIn("Resumen limitado", response.answer)

    def test_unavailable_plan_context_keeps_recorded_symptom(self):
        compact = _compact(status="unavailable", checkins=[{
            "id": "knee", "source": "checkin", "date": "2026-10-28",
            "pain": "dolor de rodilla",
        }])
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("No he podido verificar el plan de esta semana", response.answer)
        self.assertIn("molestias registradas", response.answer.lower())

    def test_unavailable_short_answer_with_symptom_respects_budget(self):
        compact = _compact(status="unavailable", checkins=[{
            "id": "knee", "source": "checkin", "date": "2026-10-28",
            "pain": "dolor de rodilla",
        }])
        response = deterministic_response(QUESTION, compact, now=NOW, max_chars=80)
        self.assertLessEqual(len(response.answer), 80)
        self.assertIn("No he podido verificar el plan de esta semana", response.answer)
        self.assertIn("molestias", response.answer.lower())

    def test_small_budget_keeps_symptom_and_explicit_reserve(self):
        compact = _compact(checkins=[{
            "id": "knee", "source": "checkin", "date": "2026-10-28",
            "pain": "dolor de rodilla",
        }])
        snapshot = build_snapshot(QUESTION, compact, now=NOW)
        assessment = assess_week(snapshot)
        for budget in (80, 120):
            with self.subTest(budget=budget):
                response = render_week_assessment(assessment, max_chars=budget)
                self.assertLessEqual(len(response.answer), budget)
                self.assertIn("molestia", response.answer.lower())
                self.assertIn("resumen", response.answer.lower())
                self.assertNotIn("carga total", response.answer.lower())
                self.assertIsNone(response.change_proposal)
                self.assertIn("checkin", {item.source for item in response.evidence})

    def test_wellness_facts_are_dated_without_recovery_verdict(self):
        compact = _compact()
        compact["extra_context"]["wellness"] = {"effective": {
            "date": "2026-10-28",
            "sleep": {"id": "sleep-28", "date": "2026-10-28", "sleep_seconds": 27000},
            "resting_hr": {"id": "rhr-28", "date": "2026-10-28", "resting_hr": 52},
        }}
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("sueño", response.answer.lower())
        self.assertIn("7 h 30 min", response.answer)
        self.assertIn("pulso en reposo 52", response.answer.lower())
        self.assertIn("2026-10-28", response.answer)
        self.assertIn("garmin", response.answer.lower())
        self.assertIn("sin línea base", response.answer.lower())
        self.assertNotIn("recuperación buena", response.answer.lower())

    def test_future_activity_is_not_treated_as_completed(self):
        compact = _compact()
        compact["extra_context"]["recent_activities"].append({
            "id": "future-ride", "source": "strava", "sport": "cycling",
            "type": "Ride", "date": "2026-11-01", "local_date": "2026-11-01",
            "started_at_utc": "2026-11-01T08:00:00Z", "distance_km": 50,
        })
        snapshot = build_snapshot(QUESTION, compact, now=NOW)
        assessment = assess_week(snapshot)
        self.assertNotIn("activity:future-ride", assessment.evidence_refs)
        response = render_week_assessment(assessment, max_chars=3200)
        self.assertNotIn("50 km", response.answer)

    def test_plan_created_after_activity_without_session_is_not_called_added(self):
        compact = _compact()
        compact["extra_context"]["week_plans"]["plans"][0]["sessions"] = [
            session for session in compact["extra_context"]["week_plans"]["plans"][0]["sessions"]
            if session["date"] != "2026-10-28"
        ]
        compact["extra_context"]["recent_activities"] = [{
            "id": "early-ride", "source": "strava", "sport": "cycling",
            "type": "Ride", "date": "2026-10-28", "local_date": "2026-10-28",
            "started_at_utc": "2026-10-28T06:00:00Z", "duration_s": 2400,
        }]
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("2026-10-28: ciclismo", response.answer)
        self.assertIn("sin plan verificable para esa fecha", response.answer)
        self.assertNotIn("actividad adicional respecto al plan", response.answer)

    def test_plan_created_after_activity_with_session_is_not_called_planned(self):
        compact = _compact()
        compact["extra_context"]["recent_activities"] = [{
            "id": "early-ride", "source": "strava", "sport": "cycling",
            "type": "Ride", "date": "2026-10-28", "local_date": "2026-10-28",
            "started_at_utc": "2026-10-28T06:00:00Z", "duration_s": 2400,
        }]
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("2026-10-28: ciclismo", response.answer)
        self.assertIn("plan se creó después", response.answer)
        self.assertNotIn("previsto carrera easy", response.answer)
        self.assertNotIn("sustitución", response.answer)

    def test_linked_session_changed_later_does_not_claim_historical_target(self):
        compact = _compact()
        session = compact["extra_context"]["week_plans"]["plans"][0]["sessions"][0]
        session["completed_activity_id"] = "activity:run-today"
        session["updated_at"] = "2026-10-28T10:00:00+00:00"
        compact["extra_context"]["recent_activities"] = [{
            "id": "run-today", "source": "garmin", "sport": "running",
            "type": "easy", "date": "2026-10-28", "local_date": "2026-10-28",
            "started_at_utc": "2026-10-28T08:00:00Z", "duration_s": 2400,
        }]
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("objetivo histórico no verificable", response.answer)
        self.assertNotIn("previsto carrera easy", response.answer)
        self.assertNotIn("duración compatible", response.answer.lower())

    def test_multiple_possible_pairs_are_labelled_ambiguous(self):
        compact = _compact()
        plan = compact["extra_context"]["week_plans"]["plans"][0]
        plan["sessions"].append(_session("run-today-2", "2026-10-28", "running", "easy"))
        compact["extra_context"]["recent_activities"] = [
            {"id": identifier, "source": "garmin", "sport": "running",
             "type": "easy", "date": "2026-10-28", "local_date": "2026-10-28",
             "started_at_utc": started, "duration_s": 2400}
            for identifier, started in (
                ("run-a", "2026-10-28T08:00:00Z"),
                ("run-b", "2026-10-28T10:00:00Z"),
            )
        ]
        response = deterministic_response(QUESTION, compact, now=NOW)
        self.assertIn("emparejamiento ambiguo", response.answer.lower())
        self.assertNotIn("cumplida", response.answer.lower())


if __name__ == "__main__":
    unittest.main()
