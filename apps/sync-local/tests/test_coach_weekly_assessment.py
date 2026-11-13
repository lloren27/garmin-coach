"""Daily relation between planned sessions and recorded activities.

Task 4: compare day-level sets without inventing pairings.
Follows the informative states from the spec and the data profile from Task 3A.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import unittest

from garmin_sync.coach_weekly_assessment import (
    DailyRelation,
    DayPlanSelection,
    compare_day,
    select_day_plan,
)


# ---------------------------------------------------------------------------
# Helpers to build test fixtures
# ---------------------------------------------------------------------------

def _plan(plan_id: str, start: str, end: str, created: str,
          status: str = "active", sessions: list | None = None) -> dict:
    return {
        "id": plan_id,
        "owner_id": "alice",
        "revision": 1,
        "status": status,
        "start_date": start,
        "end_date": end,
        "created_at": created + "+00:00",
        "updated_at": created + "+00:00",
        "sessions": sessions or [],
    }


def _session(session_id: str, plan_id: str, day: str, sport: str,
             session_type: str, duration_min: int | None = None,
             duration_max: int | None = None, optional: bool = False,
             completed_activity_id: str | None = None,
             created: str | None = None,
             updated: str | None = None) -> dict:
    stamp = (created or "2026-10-25T08:00:00") + "+00:00"
    upd = (updated or created or "2026-10-25T08:00:00") + "+00:00"
    entry = {
        "id": session_id,
        "training_plan_id": plan_id,
        "owner_id": "alice",
        "date": day,
        "sequence": 0,
        "sport": sport,
        "session_type": session_type,
        "status": "planned",
        "optional": optional,
        "created_at": stamp,
        "updated_at": upd,
    }
    if duration_min is not None:
        entry["duration_min"] = duration_min
    if duration_max is not None:
        entry["duration_max"] = duration_max
    if completed_activity_id is not None:
        entry["completed_activity_id"] = completed_activity_id
    return entry


def _activity(activity_id: str, day: str, sport: str, duration_s: int,
              started_at: str | None = None, source: str = "strava") -> dict:
    entry = {
        "id": activity_id,
        "source": source,
        "sport": sport,
        "date": day,
        "local_date": day,
        "duration_s": duration_s,
    }
    if started_at is not None:
        entry["started_at_utc"] = started_at
        entry["started_at"] = started_at.replace("Z", "+00:00")
        entry["time_context"] = "Europe/Madrid"
    return entry


def _provider_status(ok: bool = True, failed_dates: list | None = None) -> dict:
    if ok:
        return {
            "garmin": {"status": "ok", "records_received": 1,
                       "period_start": "2026-10-26", "period_end": "2026-11-01",
                       "last_success_at": "2026-10-28T11:00:00Z"},
            "strava": {"status": "ok", "records_received": 1,
                       "period_start": "2026-10-26", "period_end": "2026-11-01",
                       "last_success_at": "2026-10-28T11:00:00Z"},
            "zepp": {"status": "ok", "records_received": 0,
                     "last_success_at": "2026-10-28T11:00:00Z"},
        }
    return {
        "garmin": {"status": "ok", "records_received": 0,
                   "period_start": "2026-10-26", "period_end": "2026-11-01",
                   "last_success_at": "2026-10-28T11:00:00Z"},
        "strava": {"status": "network_error", "records_received": None,
                   "period_start": None, "period_end": None,
                   "failed_dates": failed_dates or ["2026-10-27"]},
        "zepp": {"status": "ok", "records_received": 0,
                 "last_success_at": "2026-10-28T11:00:00Z"},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class SelectDayPlanTests(unittest.TestCase):
    """Test plan selection for a given day."""

    def test_selects_plan_covering_day(self):
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00"),)
        result = select_day_plan(plans, date(2026, 10, 27), (),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(result.plan_id, "p1")
        self.assertEqual(result.status, "available")

    def test_no_plan_for_day(self):
        plans = (_plan("p1", "2026-11-02", "2026-11-08", "2026-11-01T08:00:00"),)
        result = select_day_plan(plans, date(2026, 10, 27), (),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertIsNone(result.plan_id)
        self.assertEqual(result.status, "no_plan")

    def test_plan_created_after_activity_not_applicable(self):
        """A plan created after the activity date cannot be the plan that governed it."""
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-28T10:00:00"),)
        activity_time = datetime(2026, 10, 27, 7, 0, tzinfo=__import__("datetime").timezone.utc)
        result = select_day_plan(plans, date(2026, 10, 27), (activity_time,),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(result.plan_id, "p1")
        self.assertIn("plan_created_after_activity", result.limitations)

    def test_superseded_plan_still_selected(self):
        """A superseded plan is still used if it covers the day."""
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00",
                       status="superseded"),)
        result = select_day_plan(plans, date(2026, 10, 27), (),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(result.plan_id, "p1")
        self.assertEqual(result.status, "available")

    def test_earlier_plan_preferred_for_past_day(self):
        """When two plans cover a day, prefer the one whose validity precedes the day."""
        old = _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", status="superseded")
        new = _plan("new", "2026-10-28", "2026-11-03", "2026-10-28T10:00:00")
        plans = (old, new)
        result = select_day_plan(plans, date(2026, 10, 27), (),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(result.plan_id, "old")

    def test_activity_without_reliable_time(self):
        """Activity on the same day without reliable time — indeterminate ordering."""
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-27T08:00:00"),)
        result = select_day_plan(plans, date(2026, 10, 27), (),
                                 datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc))
        self.assertEqual(result.plan_id, "p1")
        self.assertIn("plan_created_after_activity", result.limitations)


class CompareDayTests(unittest.TestCase):
    """Test daily comparison between sessions and activities."""

    def test_run_planned_bike_and_strength_recorded(self):
        """Reference case: run planned, bike+strength recorded — other sport same day."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (
            _activity("a1", "2026-10-27", "cycling", 3600, "2026-10-27T07:00:00Z"),
            _activity("a2", "2026-10-27", "strength", 2700, "2026-10-27T17:00:00Z"),
        )
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, _provider_status())
        self.assertTrue(any(r.status == "other_sport_same_day" for r in relations))
        # Must not claim the run was completed
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan")

    def test_double_session(self):
        """Two sessions on the same day — produce separate relations."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
            _session("s2", "p1", "2026-10-27", "cycling", "easy", 45, 60),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (
            _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T06:00:00Z"),
            _activity("a2", "2026-10-27", "cycling", 3000, "2026-10-27T16:00:00Z"),
        )
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, _provider_status())
        # Two sessions should produce at least two relations
        session_ids = {s["id"] for s in sessions}
        covered = {r.session_ids for r in relations}
        self.assertEqual(len(relations), 2)

    def test_optional_session_without_activity(self):
        """Optional session without activity is not a violation."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "cycling", "easy", 30, 40, optional=True),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Optional session skipped — no "no_activity_recorded"
        for r in relations:
            self.assertNotEqual(r.status, "no_activity_recorded")

    def test_rest_day_with_activity(self):
        """Activity on a rest day — described as difference, not harm."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "recovery", "rest"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "cycling", 1800, "2026-10-27T10:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.status == "other_sport_same_day" for r in relations))

    def test_explicit_link_confirmed(self):
        """A valid completed_activity_id confirms the relation."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40,
                     completed_activity_id="a1"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.link_status == "confirmed" for r in relations))

    def test_linked_session_with_later_updated_at(self):
        """A valid link preserves confirmation even if session updated_at is later."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40,
                     completed_activity_id="a1",
                     created="2026-10-25T08:00:00", updated="2026-10-28T10:00:00"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.link_status == "confirmed" for r in relations))
        # Historical target may be uncertain
        self.assertTrue(any(r.historical_target_status == "uncertain" for r in relations))

    def test_two_possible_pairs_no_arbitrary_choice(self):
        """Two activities and two sessions — no forced pairing."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
            _session("s2", "p1", "2026-10-27", "running", "easy_progressions", 35, 45),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (
            _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T06:00:00Z"),
            _activity("a2", "2026-10-27", "running", 2400, "2026-10-27T17:00:00Z"),
        )
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Should not force a single pairing
        for r in relations:
            self.assertNotEqual(r.link_status, "confirmed")

    def test_duration_within_range(self):
        """Activity duration within session range — compatible candidate."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # 35 min = 2100s, within 30-40 min range
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.status == "compatible_with_plan" for r in relations))

    def test_duration_outside_range(self):
        """Activity duration outside session range — compatible with adjustments."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # 60 min = 3600s, outside 30-40 min range
        activities = (_activity("a1", "2026-10-27", "running", 3600, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.status == "compatible_with_adjustments" for r in relations))

    def test_long_run_distance_only(self):
        """long_run with distance only — no duration compatibility label."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "long_run"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 5400, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Must show limitation, not a duration-based label
        for r in relations:
            if r.status in ("compatible_with_plan", "compatible_with_adjustments"):
                self.fail("Should not assign duration compatibility to long_run")
        self.assertTrue(any("sin criterio de compatibilidad validado" in r.limitations
                           for r in relations if r.limitations))

    def test_quality_session_text_only(self):
        """quality session with text description — no duration comparison."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "quality"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 3600, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            if r.status in ("compatible_with_plan", "compatible_with_adjustments"):
                self.fail("Should not assign duration compatibility to quality")

    def test_provider_failed_vs_verified_absence(self):
        """Provider failure — insufficient data, not 'no activity recorded'."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        provider = _provider_status(ok=False)
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.status == "insufficient_data" for r in relations))
        for r in relations:
            self.assertNotEqual(r.status, "no_activity_recorded")

    def test_no_plan_selection(self):
        """Day with no applicable plan."""
        selection = DayPlanSelection(date(2026, 10, 27), None, "no_plan", ())
        sessions = ()
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Activity recorded without plan — activity_added or similar
        self.assertTrue(any(r.status == "activity_added" for r in relations))

    def test_session_content_modified_after_activity_no_history(self):
        """Session content modified after activity without history — uncertain target."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40,
                     completed_activity_id="a1",
                     created="2026-10-25T08:00:00", updated="2026-10-28T10:00:00"),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Link confirmed, but historical target uncertain
        confirmed = [r for r in relations if r.link_status == "confirmed"]
        self.assertTrue(len(confirmed) > 0)
        self.assertTrue(any(r.historical_target_status == "uncertain" for r in confirmed))


class DailyRelationDataclassTests(unittest.TestCase):
    """Verify the data types are frozen and well-formed."""

    def test_daily_relation_is_frozen(self):
        r = DailyRelation(
            day=date(2026, 10, 27),
            status="compatible_with_plan",
            link_status="unconfirmed",
            historical_target_status="certain",
            session_ids=("s1",),
            activity_ids=("a1",),
            evidence_refs=(),
            limitations=(),
        )
        self.assertTrue(r.__hash__ is not None)

    def test_day_plan_selection_is_frozen(self):
        s = DayPlanSelection(
            day=date(2026, 10, 27),
            plan_id="p1",
            status="available",
            limitations=(),
        )
        self.assertTrue(s.__hash__ is not None)


if __name__ == "__main__":
    unittest.main()
