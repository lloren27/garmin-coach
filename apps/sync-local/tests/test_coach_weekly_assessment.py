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

    def test_new_plan_does_not_affect_past_day(self):
        """A plan created on 28/10 should not govern 27/10 when an older plan covers it.

        Regression test: select_day_plan always picked the oldest plan regardless
        of as_of, so a plan created 28/10 could govern 27/10.
        """
        old = _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", status="superseded")
        new = _plan("new", "2026-10-28", "2026-11-03", "2026-10-28T10:00:00")
        plans = (old, new)
        # as_of is 28/10 12:00 — the new plan exists at as_of.
        as_of = datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc)
        # For 27/10 (past day), only the old plan should apply.
        result = select_day_plan(plans, date(2026, 10, 27), (), as_of)
        self.assertEqual(result.plan_id, "old",
                         "Past day should use the plan that was in effect, not the new one")

    def test_new_plan_governs_future_day(self):
        """For a future day (29/10), the new plan (created 28/10) should be selected."""
        old = _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", status="superseded")
        new = _plan("new", "2026-10-28", "2026-11-03", "2026-10-28T10:00:00")
        plans = (old, new)
        as_of = datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc)
        # 29/10 is a future day relative to as_of (28/10).
        result = select_day_plan(plans, date(2026, 10, 29), (), as_of)
        self.assertEqual(result.plan_id, "new",
                         "Future day should use the most recent plan valid at as_of")

    def test_plan_created_after_as_of_excluded(self):
        """A plan created after as_of should not be considered."""
        future_plan = _plan("future", "2026-10-26", "2026-11-01", "2026-10-29T08:00:00")
        plans = (future_plan,)
        as_of = datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc)
        result = select_day_plan(plans, date(2026, 10, 27), (), as_of)
        self.assertIsNone(result.plan_id,
                          "Plan created after as_of should be excluded")
        self.assertEqual(result.status, "no_plan")

    def test_past_day_selects_plan_in_effect_at_activity_time(self):
        """For a past day, select the plan that was in effect when the activity occurred.

        Regression test: select_day_plan always picked the oldest plan for past
        days, even when a newer plan was already in effect at activity time.
        """
        tz = __import__("datetime").timezone.utc
        # Old plan created 25/10, new plan created 26/10 at 10:00.
        old = _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00",
                     status="superseded")
        new = _plan("new", "2026-10-26", "2026-11-01", "2026-10-26T10:00:00")
        plans = (old, new)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # Activity on 27/10 at 07:00 — after both plans were created.
        activity_time = datetime(2026, 10, 27, 7, 0, tzinfo=tz)
        result = select_day_plan(plans, date(2026, 10, 27), (activity_time,), as_of)
        # The new plan (created 26/10) was in effect at 27/10 07:00.
        self.assertEqual(result.plan_id, "new",
                         "Should select the plan in effect at activity time")
        self.assertNotIn("plan_created_after_activity", result.limitations)

    def test_past_day_activity_before_new_plan(self):
        """If activity occurred before the new plan was created, use the old plan."""
        tz = __import__("datetime").timezone.utc
        old = _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00",
                     status="superseded")
        new = _plan("new", "2026-10-26", "2026-11-01", "2026-10-26T10:00:00")
        plans = (old, new)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # Activity on 26/10 at 06:00 — before the new plan (10:00).
        activity_time = datetime(2026, 10, 26, 6, 0, tzinfo=tz)
        result = select_day_plan(plans, date(2026, 10, 26), (activity_time,), as_of)
        self.assertEqual(result.plan_id, "old",
                         "Activity before new plan — old plan was in effect")

    def test_same_day_plan_created_after_activity(self):
        """Plan created on the same day after the activity — limitation added."""
        tz = __import__("datetime").timezone.utc
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-27T10:00:00"),)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # Activity at 07:00, plan created at 10:00 on the same day.
        activity_time = datetime(2026, 10, 27, 7, 0, tzinfo=tz)
        result = select_day_plan(plans, date(2026, 10, 27), (activity_time,), as_of)
        self.assertEqual(result.plan_id, "p1")
        self.assertIn("plan_created_after_activity", result.limitations,
                      "Plan created after activity on the same day")

    def test_same_day_plan_created_before_activity(self):
        """Plan created on the same day before the activity — no limitation."""
        tz = __import__("datetime").timezone.utc
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-27T06:00:00"),)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # Activity at 07:00, plan created at 06:00 on the same day.
        activity_time = datetime(2026, 10, 27, 7, 0, tzinfo=tz)
        result = select_day_plan(plans, date(2026, 10, 27), (activity_time,), as_of)
        self.assertEqual(result.plan_id, "p1")
        self.assertNotIn("plan_created_after_activity", result.limitations,
                         "Plan created before activity — no limitation")

    def test_timezone_naive_activity_time_no_type_error(self):
        """Activity time without timezone should not raise TypeError.

        Regression test: min(activity_times) with timezone-naive datetime
        caused TypeError before reaching the indeterminate branch.
        """
        tz = __import__("datetime").timezone.utc
        # _plan appends +00:00, so pass a plain timestamp.
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-27T06:00:00"),)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # Timezone-naive activity time — no tzinfo.
        naive_time = datetime(2026, 10, 27, 7, 0)
        # Should not raise TypeError.
        result = select_day_plan(plans, date(2026, 10, 27), (naive_time,), as_of)
        self.assertEqual(result.plan_id, "p1")
        # Without reliable time, should be indeterminate.
        self.assertIn("plan_created_after_activity", result.limitations,
                      "Timezone-naive time should yield indeterminate ordering")

    def test_mixed_times_choose_latest_plan_created_before_day(self):
        day = date(2026, 10, 27)
        plans = (
            _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00"),
            _plan("new", "2026-10-26", "2026-11-01", "2026-10-26T08:00:00"),
        )
        times = (
            datetime(2026, 10, 27, 7),
            datetime(2026, 10, 27, 8, tzinfo=__import__("datetime").timezone.utc),
        )
        as_of = datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc)
        result = select_day_plan(plans, day, times, as_of)
        self.assertEqual(result.plan_id, "new")
        self.assertEqual(result.limitations, ())

    def test_mixed_times_with_same_day_plan_keep_order_uncertain(self):
        day = date(2026, 10, 27)
        plans = (
            _plan("old", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00"),
            _plan("new", "2026-10-26", "2026-11-01", "2026-10-27T06:00:00"),
        )
        times = (
            datetime(2026, 10, 27, 7),
            datetime(2026, 10, 27, 8, tzinfo=__import__("datetime").timezone.utc),
        )
        as_of = datetime(2026, 10, 28, 12, tzinfo=__import__("datetime").timezone.utc)
        result = select_day_plan(plans, day, times, as_of)
        self.assertEqual(result.plan_id, "old")
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
        # 35 min = 2100s, within 30-40 min range; activity type matches session.
        act = _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z")
        act["activity_type"] = "easy"
        activities = (act,)
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
        # 60 min = 3600s, outside 30-40 min range; activity type matches session.
        act = _activity("a1", "2026-10-27", "running", 3600, "2026-10-27T07:00:00Z")
        act["activity_type"] = "easy"
        activities = (act,)
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

    def test_provider_failed_without_coverage_dates(self):
        """Provider failure without coverage dates — insufficient_data, not no_activity_recorded.

        Regression test: _provider_coverage_sufficient returned True when Strava
        failed with no period_start/period_end, leading to no_activity_recorded.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        # Strava error with no coverage window — cannot verify absence.
        provider = {
            "garmin": {"status": "ok", "records_received": 0,
                       "period_start": "2026-10-26", "period_end": "2026-11-01",
                       "last_success_at": "2026-10-28T11:00:00Z"},
            "strava": {"status": "network_error", "records_received": None,
                       "period_start": None, "period_end": None,
                       "failed_dates": None},
            "zepp": {"status": "ok", "records_received": 0,
                     "last_success_at": "2026-10-28T11:00:00Z"},
        }
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        self.assertTrue(any(r.status == "insufficient_data" for r in relations),
                        "Should be insufficient_data when provider has no coverage window")
        for r in relations:
            self.assertNotEqual(r.status, "no_activity_recorded",
                                "Must not claim verified absence without coverage")

    def test_no_plan_selection_should_not_claim_compatibility(self):
        """When selection is no_plan, compare_day must not produce compatible_with_plan.

        Regression test: compare_day accepted sessions even when selection
        indicated no_plan, producing a false compatible_with_plan.
        """
        selection = DayPlanSelection(date(2026, 10, 27), None, "no_plan", ())
        sessions = ()  # No sessions because no plan.
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "No plan — must not claim compatibility")
        self.assertTrue(any(r.status == "activity_added" for r in relations))

    def test_duration_missing_should_not_be_compatible(self):
        """Activity without duration_s must not produce compatible_with_plan.

        Regression test: _duration_status returned compatible_with_plan when
        duration_s was None.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Activity without duration_s.
        act = _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z")
        del act["duration_s"]
        activities = (act,)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "Missing duration must not yield compatibility")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations))

    def test_two_run_sessions_no_forced_pairing(self):
        """Two run sessions and one run activity — no forced pairing, second session ambiguous.

        Regression test: compare_day assigned the single run to the first session
        and returned other_sport_same_day for the second session without an activity.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
            _session("s2", "p1", "2026-10-27", "running", "easy_progressions", 35, 45),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T06:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Both sessions should be ambiguous — cannot determine which activity
        # corresponds to which session.
        for r in relations:
            if r.session_ids:
                self.assertEqual(r.link_status, "ambiguous",
                                 "Multiple sessions same sport — must be ambiguous")

    def test_unassigned_activity_emits_relation(self):
        """Activities not assigned to any session should emit an activity_added relation.

        Regression test: unassigned activities were silently dropped.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # One run (matches session) + one bike (no session).
        activities = (
            _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T06:00:00Z"),
            _activity("a2", "2026-10-27", "cycling", 3600, "2026-10-27T16:00:00Z"),
        )
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # The bike activity should appear as activity_added.
        added = [r for r in relations if r.status == "activity_added"]
        self.assertTrue(len(added) > 0, "Unassigned activity should emit relation")
        self.assertTrue(any("a2" in r.activity_ids for r in added),
                        "Bike activity should be in activity_added relation")

    def test_selection_limitation_propagated(self):
        """Selection limitations should propagate to all relations."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        # Selection with plan_created_after_activity limitation.
        selection = DayPlanSelection(
            date(2026, 10, 27), "p1", "available",
            ("plan_created_after_activity",))
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertIn("plan_created_after_activity", r.limitations,
                          "Selection limitation should propagate to relations")

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

    def test_no_plan_with_sessions_must_not_claim_compatibility(self):
        """When selection is no_plan but sessions are provided, must not claim compatibility.

        Regression test: compare_day accepted sessions even when selection
        indicated no_plan, producing a false compatible_with_plan.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), None, "no_plan", ())
        # Sessions from a plan, but selection says no_plan.
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "No plan — must not claim compatibility even with sessions")
        # Should report as activity_added since no plan governs the day.
        self.assertTrue(any(r.status == "activity_added" for r in relations))

    def test_plan_created_after_activity_yields_insufficient_data(self):
        """When plan was created after activity, status is insufficient_data.

        Regression test: compare_day returned compatible_with_adjustments when
        plan was created after activity. That label still affirms a comparison
        with a plan that did not govern the training. The correct state is
        insufficient_data — we cannot compare against a non-applicable plan.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-28T10:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(
            date(2026, 10, 27), "p1", "available",
            ("plan_created_after_activity",))
        sessions = tuple(plan["sessions"])
        activities = (_activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "Plan created after activity — must not claim full compatibility")
            self.assertNotEqual(r.status, "compatible_with_adjustments",
                                "Plan created after activity — must not claim partial compatibility")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations),
                        "Plan not applicable — should be insufficient_data")

    def test_uncertain_historical_target_yields_insufficient_data(self):
        """When historical target is uncertain, status is insufficient_data.

        Regression test: compare_day returned compatible_with_adjustments when
        the historical target was uncertain. That label still affirms a
        comparison with an uncertain target. The correct state is
        insufficient_data.
        """
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
        for r in relations:
            if r.historical_target_status == "uncertain":
                self.assertNotEqual(r.status, "compatible_with_plan",
                                    "Uncertain target must not yield full compatibility")
                self.assertNotEqual(r.status, "compatible_with_adjustments",
                                    "Uncertain target must not yield partial compatibility")
                self.assertEqual(r.status, "insufficient_data",
                                 "Uncertain target should yield insufficient_data")

    def test_uncertain_historical_target_outside_duration_range(self):
        day = date(2026, 10, 27)
        selection = DayPlanSelection(day, "p1", "available", ())
        session = _session(
            "s1", "p1", day.isoformat(), "running", "easy", 30, 40,
            completed_activity_id="a1", created="2026-10-25T08:00:00",
            updated="2026-10-28T10:00:00",
        )
        activity = _activity("a1", day.isoformat(), "running", 3600,
                             "2026-10-27T07:00:00Z")
        activity["activity_type"] = "easy"
        relation = compare_day(day, selection, (session,), (activity,), {})[0]
        self.assertEqual(relation.link_status, "confirmed")
        self.assertEqual(relation.historical_target_status, "uncertain")
        self.assertEqual(relation.status, "insufficient_data")

    def test_empty_providers_returns_insufficient_data(self):
        """No providers configured — cannot verify absence.

        Regression test: _provider_coverage_sufficient returned True with
        empty providers, leading to no_activity_recorded.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        provider = {}  # No providers at all.
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "no_activity_recorded",
                                "No providers — must not claim verified absence")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations))

    def test_unknown_provider_status_returns_insufficient_data(self):
        """Provider with unknown status — cannot verify coverage.

        Regression test: _provider_coverage_sufficient returned True with
        unknown status, leading to no_activity_recorded.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        provider = {
            "garmin": {"status": "unknown", "records_received": None},
        }
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "no_activity_recorded",
                                "Unknown provider — must not claim verified absence")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations))

    def test_intervals_activity_not_compatible_with_easy_session(self):
        """An intervals activity should not be marked compatible with an easy session.

        Regression test: compare_day labeled an intervals activity as
        compatible_with_plan against an easy session if sport and duration matched.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Activity with session_type "intervals" — incompatible with "easy".
        act = _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z")
        act["session_type"] = "intervals"
        activities = (act,)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "Intervals activity must not be compatible with easy session")
        self.assertTrue(any("activity_type_mismatch" in r.limitations
                           for r in relations if r.limitations))

    def test_activity_type_field_used_instead_of_session_type(self):
        """Activity type should be read from activity_type, not session_type.

        Regression test: compare_day read session_type from the activity,
        but the real context uses activity_type. An intervals activity with
        activity_type="intervals" was marked compatible with an easy session.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Activity with activity_type "intervals" — the real context field.
        act = _activity("a1", "2026-10-27", "running", 2100, "2026-10-27T07:00:00Z")
        act["activity_type"] = "intervals"
        activities = (act,)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "Intervals activity_type must not be compatible with easy session")
        self.assertTrue(any("activity_type_mismatch" in r.limitations
                           for r in relations if r.limitations))

    def test_wellness_provider_does_not_affect_coverage(self):
        """Wellness and Wattwise providers should not affect coverage check.

        Regression test: _provider_coverage_sufficient evaluated wellness and
        Wattwise providers, returning insufficient_data even when activity
        providers confirmed an empty day.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        # Activity providers confirm coverage; wellness provider has no window.
        provider = {
            "garmin": {"status": "ok", "records_received": 0,
                       "period_start": "2026-10-26", "period_end": "2026-11-01",
                       "last_success_at": "2026-10-28T11:00:00Z"},
            "wellness": {"status": "ok", "records_received": 0},
            "wattwise": {"status": "unknown"},
        }
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Activity providers cover the day — should be no_activity_recorded.
        self.assertTrue(any(r.status == "no_activity_recorded" for r in relations),
                        "Wellness/Wattwise should not prevent verified absence")

    def test_compound_provider_keys_accepted(self):
        """Provider keys like 'garmin.activities' must be accepted.

        Regression test: _ACTIVITY_PROVIDERS filtered by 'garmin', 'strava',
        'zepp' but the real snapshot uses 'garmin.activities', etc.
        This caused insufficient_data when all three activity providers
        confirmed an empty day.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        activities = ()
        # Compound keys — the real snapshot format.
        provider = {
            "garmin.activities": {"status": "ok", "records_received": 0,
                                   "period_start": "2026-10-26", "period_end": "2026-11-01",
                                   "last_success_at": "2026-10-28T11:00:00Z"},
            "strava.activities": {"status": "ok", "records_received": 0,
                                   "period_start": "2026-10-26", "period_end": "2026-11-01",
                                   "last_success_at": "2026-10-28T11:00:00Z"},
            "zepp.activities": {"status": "ok", "records_received": 0,
                                 "period_start": "2026-10-26", "period_end": "2026-11-01",
                                 "last_success_at": "2026-10-28T11:00:00Z"},
        }
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # All activity providers cover the day — should be no_activity_recorded.
        self.assertTrue(any(r.status == "no_activity_recorded" for r in relations),
                        "Compound provider keys should be accepted")

    def test_stale_activity_coverage_cannot_prove_absence(self):
        day = date(2026, 10, 27)
        selection = DayPlanSelection(day, "p1", "available", ())
        sessions = (_session("s1", "p1", day.isoformat(), "running", "easy", 30, 40),)
        provider = {
            f"{name}.activities": {
                "scope": "activities", "state": "stale", "status": "ok",
                "records_received": 0, "period_start": "2026-10-26",
                "period_end": "2026-11-01", "failed_dates": [],
                "last_success_at": "2026-10-25T11:00:00Z",
            }
            for name in ("garmin", "strava", "zepp")
        }
        relations = compare_day(day, selection, sessions, (), provider)
        self.assertEqual(relations[0].status, "insufficient_data")
        self.assertIn("provider_coverage_insufficient", relations[0].limitations)

    def test_plan_not_applicable_degrades_all_compatibility(self):
        """Plan not applicable must degrade compatible_with_adjustments too.

        Regression test: when plan was created after activity, only
        compatible_with_plan was downgraded. If duration fell outside the
        range, status remained compatible_with_adjustments — still affirming
        a comparison with a non-applicable plan.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-28T10:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(
            date(2026, 10, 27), "p1", "available",
            ("plan_created_after_activity",))
        sessions = tuple(plan["sessions"])
        # Duration outside range — would be compatible_with_adjustments.
        activities = (_activity("a1", "2026-10-27", "running", 3600,
                                "2026-10-27T07:00:00Z"),)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_adjustments",
                                "Plan not applicable — must not claim partial compatibility")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations),
                        "Plan not applicable — should be insufficient_data")

    def test_missing_activity_type_yields_insufficient_data(self):
        """When activity type is not available, status is insufficient_data.

        Regression test: _activity_type_compatible_with_session returned True
        when activity_type was None, allowing compatible_with_plan without
        a verifiable type.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Activity without activity_type or session_type.
        act = _activity("a1", "2026-10-27", "running", 2100,
                        "2026-10-27T07:00:00Z")
        # Ensure no type field is present.
        act.pop("activity_type", None)
        act.pop("session_type", None)
        activities = (act,)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        for r in relations:
            self.assertNotEqual(r.status, "compatible_with_plan",
                                "No activity type — must not claim compatibility")
        self.assertTrue(any(r.status == "insufficient_data" for r in relations))
        self.assertTrue(any("activity_type_not_available" in r.limitations
                           for r in relations if r.limitations))

    def test_unvalidated_activity_type_does_not_claim_compatibility(self):
        day = date(2026, 10, 27)
        selection = DayPlanSelection(day, "p1", "available", ())
        session = _session("s1", "p1", day.isoformat(), "running", "easy", 30, 40)
        for activity_type in ("long_run", "unknown"):
            with self.subTest(activity_type=activity_type):
                activity = _activity("a1", day.isoformat(), "running", 2100)
                activity["activity_type"] = activity_type
                relation = compare_day(day, selection, (session,), (activity,), {})[0]
                self.assertEqual(relation.status, "insufficient_data")
                self.assertIn("activity_type_mismatch", relation.limitations)

    def test_mixed_timezone_activity_times_no_type_error(self):
        """Mixed timezone-aware and naive times should not raise TypeError.

        Regression test: min() with one timezone-aware and one timezone-naive
        datetime raises TypeError before reaching the indeterminate branch.
        """
        tz = __import__("datetime").timezone.utc
        plans = (_plan("p1", "2026-10-26", "2026-11-01", "2026-10-27T06:00:00"),)
        as_of = datetime(2026, 10, 28, 12, tzinfo=tz)
        # One timezone-aware, one timezone-naive — min() would raise TypeError.
        aware_time = datetime(2026, 10, 27, 7, 0, tzinfo=tz)
        naive_time = datetime(2026, 10, 27, 8, 0)
        # Should not raise TypeError.
        result = select_day_plan(plans, date(2026, 10, 27),
                                 (aware_time, naive_time), as_of)
        self.assertEqual(result.plan_id, "p1")
        # Mixed timezone — should be indeterminate.
        self.assertIn("plan_created_after_activity", result.limitations,
                      "Mixed timezone times should yield indeterminate ordering")

    def test_deduplication_preserves_distinct_activities_without_time(self):
        """Two activities of the same sport without started_at_utc are not deduplicated.

        Regression test: _deduplicate_activities treated all same-sport activities
        without started_at_utc as one, reducing two distinct activities to one ID.
        """
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Two running activities without started_at_utc — should remain distinct.
        act1 = _activity("a1", "2026-10-27", "running", 1800)
        act2 = _activity("a2", "2026-10-27", "running", 2400)
        activities = (act1, act2)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Both activity IDs should appear somewhere in the relations.
        all_activity_ids: set[str] = set()
        for r in relations:
            all_activity_ids.update(r.activity_ids)
        self.assertIn("a1", all_activity_ids,
                      "First activity should not be deduplicated away")
        self.assertIn("a2", all_activity_ids,
                      "Second activity should not be deduplicated away")

    def test_deduplication_removes_true_duplicates(self):
        """Two activities with the same sport and started_at_utc are deduplicated."""
        plan = _plan("p1", "2026-10-26", "2026-11-01", "2026-10-25T08:00:00", sessions=[
            _session("s1", "p1", "2026-10-27", "running", "easy", 30, 40),
        ])
        selection = DayPlanSelection(date(2026, 10, 27), "p1", "available", ())
        sessions = tuple(plan["sessions"])
        # Same sport, same time — true duplicate from different sources.
        act1 = _activity("a1", "2026-10-27", "running", 2100,
                         "2026-10-27T07:00:00Z", source="garmin")
        act2 = _activity("a2", "2026-10-27", "running", 2100,
                         "2026-10-27T07:00:00Z", source="strava")
        activities = (act1, act2)
        provider = _provider_status()
        relations = compare_day(
            date(2026, 10, 27), selection, sessions, activities, provider)
        # Only one activity ID should appear (the first one kept).
        all_activity_ids: set[str] = set()
        for r in relations:
            all_activity_ids.update(r.activity_ids)
        self.assertEqual(len(all_activity_ids), 1,
                         "True duplicates should be deduplicated to one")

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
