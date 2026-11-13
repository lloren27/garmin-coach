"""Daily relation between planned sessions and recorded activities.

Task 4: compare day-level sets without inventing pairings.
Follows the informative states from the spec and the data profile from Task 3A.

Key rules:
- Only mark duration compatibility when sport, type are verifiable AND both
  duration_min and duration_max are present on the session.
- long_run, quality, rest and rest_mobility without a full duration range
  show magnitude with "sin criterio de compatibilidad validado".
- A valid completed_activity_id confirms the link even if updated_at is later;
  only the historical target comparison is limited when content may have changed.
- Optional sessions without activity are not a violation.
- Provider failure produces "insufficient_data", never "no_activity_recorded".
- No cross-sport equivalence claims in stage A.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DayPlanSelection:
    """Result of selecting which plan governs a given day."""
    day: date
    plan_id: str | None
    status: str  # "available" | "no_plan" | "indeterminate"
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class DailyRelation:
    """One relation between a session (or group) and the day's activities."""
    day: date
    status: str  # informative state label
    link_status: str  # "confirmed" | "unconfirmed" | "ambiguous"
    historical_target_status: str  # "certain" | "uncertain" | "n/a"
    session_ids: tuple[str, ...]
    activity_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


# Sessions whose type never admits a duration-based compatibility label.
# long_run: distance-only target; quality: text intervals; rest: no target;
# rest_mobility: duration present but never makes another activity equivalent.
_NO_DURATION_COMPAT = frozenset({"long_run", "quality", "rest", "rest_mobility"})

# Recovery sessions are excluded from sport-duration comparison.
_RECOVERY_SPORTS = frozenset({"recovery"})


def select_day_plan(
    plans: Sequence[Mapping],
    day: date,
    activity_times: Sequence[datetime],
    as_of: datetime,
) -> DayPlanSelection:
    """Select the plan that governs *day* from the available historical plans.

    Rules:
    - A plan covers a day when ``start_date <= day <= end_date``.
    - Among covering plans, prefer the one whose ``created_at`` is earliest
      (the version that was in effect before the day).
    - If the selected plan was created after the day's activities, add a
      limitation but still return the plan (the caller decides how to use it).
    - A plan created on the same day as the activity without reliable times
      is indeterminate.
    """
    covering: list[Mapping] = []
    for plan in plans:
        start = date.fromisoformat(plan["start_date"])
        end = date.fromisoformat(plan["end_date"])
        if start <= day <= end:
            covering.append(plan)

    if not covering:
        return DayPlanSelection(day, None, "no_plan", ())

    # Sort by created_at ascending — earliest plan is the one in effect first.
    covering.sort(key=lambda p: p["created_at"])
    selected = covering[0]
    plan_id = selected["id"]
    plan_created = datetime.fromisoformat(selected["created_at"])

    limitations: list[str] = []

    # Check if plan was created after the day.
    if plan_created.date() > day:
        limitations.append("plan_created_after_activity")
    elif plan_created.date() == day:
        # Same day — check if we have reliable activity times.
        has_reliable_time = any(
            t.tzinfo is not None for t in activity_times
        )
        if not has_reliable_time or not activity_times:
            # Cannot order plan vs activity on the same day.
            limitations.append("plan_created_after_activity")

    return DayPlanSelection(day, plan_id, "available", tuple(limitations))


def _has_full_duration_range(session: Mapping) -> bool:
    """Return True when the session has both duration_min and duration_max."""
    dmin = session.get("duration_min")
    dmax = session.get("duration_max")
    return (isinstance(dmin, (int, float)) and isinstance(dmax, (int, float))
            and dmin > 0 and dmax >= dmin)


def _provider_coverage_sufficient(
    provider_status: Mapping, day: date
) -> bool:
    """Check whether activity providers cover the day sufficiently.

    Returns False when a configured provider has an error or missing window
    that includes the day.
    """
    for name, status in provider_status.items():
        if not isinstance(status, Mapping):
            continue
        if status.get("status") in ("network_error", "error", "unavailable"):
            # Check if the failure affects our day.
            failed = status.get("failed_dates") or []
            if day.isoformat() in failed:
                return False
            # If period doesn't cover the day, also insufficient.
            period_start = status.get("period_start")
            if period_start and date.fromisoformat(period_start) > day:
                return False
    return True


def _check_historical_target_certainty(
    session: Mapping, activity_started: datetime | None
) -> str:
    """Determine whether the session's historical target is certain.

    Returns "uncertain" when the session's updated_at is after the activity
    and we cannot rule out a content change.
    """
    session_updated = session.get("updated_at")
    session_created = session.get("created_at")
    if not session_updated or not session_created:
        return "certain"

    if activity_started is None:
        return "certain"

    updated_dt = datetime.fromisoformat(session_updated)
    created_dt = datetime.fromisoformat(session_created)

    # If updated_at == created_at, no change.
    if updated_dt == created_dt:
        return "certain"

    # updated_at is after activity start — content may have changed.
    if updated_dt > activity_started:
        return "uncertain"

    return "certain"


def compare_day(
    day: date,
    selection: DayPlanSelection,
    sessions: Sequence[Mapping],
    activities: Sequence[Mapping],
    provider_status: Mapping,
) -> tuple[DailyRelation, ...]:
    """Compare the day's planned sessions against recorded activities.

    Returns one DailyRelation per session (or per activity group when no plan).
    Produces informative states without inventing pairings.
    """
    relations: list[DailyRelation] = []

    # Filter sessions for this day.
    day_sessions = [s for s in sessions if s.get("date") == day.isoformat()]
    day_activities = [a for a in activities
                      if a.get("local_date") == day.isoformat()
                      or a.get("date") == day.isoformat()]

    # No plan for this day.
    if not day_sessions:
        if day_activities:
            # Activities without a plan — activity_added.
            activity_ids = tuple(a["id"] for a in day_activities)
            evidence = tuple(a["id"] for a in day_activities)
            relations.append(DailyRelation(
                day=day,
                status="activity_added",
                link_status="unconfirmed",
                historical_target_status="n/a",
                session_ids=(),
                activity_ids=activity_ids,
                evidence_refs=evidence,
                limitations=(),
            ))
        return tuple(relations)

    # Build activity lookup by sport.
    activities_by_sport: dict[str, list[Mapping]] = {}
    for act in day_activities:
        sport = act.get("sport") or "unknown"
        activities_by_sport.setdefault(sport, []).append(act)

    # Track which activities have been referenced.
    used_activity_ids: set[str] = set()

    for session in day_sessions:
        session_id = session["id"]
        session_sport = session.get("sport")
        session_type = session.get("session_type", "")
        is_optional = session.get("optional", False)
        completed_id = session.get("completed_activity_id")

        # --- Explicit link check ---
        if completed_id:
            linked_activity = None
            for act in day_activities:
                if act["id"] == completed_id:
                    linked_activity = act
                    break

            if linked_activity:
                # Link is confirmed.
                activity_started_str = linked_activity.get("started_at_utc")
                activity_started = None
                if activity_started_str:
                    try:
                        activity_started = datetime.fromisoformat(
                            activity_started_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                target_status = _check_historical_target_certainty(
                    session, activity_started
                )

                # Determine status based on sport match and duration.
                act_sport = linked_activity.get("sport")
                if act_sport != session_sport:
                    status = "other_sport_same_day"
                elif session_type in _NO_DURATION_COMPAT:
                    status = "insufficient_data"
                elif _has_full_duration_range(session):
                    status = _duration_status(session, linked_activity)
                else:
                    status = "insufficient_data"

                limitations: list[str] = []
                if session_type in _NO_DURATION_COMPAT:
                    limitations.append("sin criterio de compatibilidad validado")
                if target_status == "uncertain":
                    limitations.append("historical_target_uncertain")

                used_activity_ids.add(completed_id)
                relations.append(DailyRelation(
                    day=day,
                    status=status,
                    link_status="confirmed",
                    historical_target_status=target_status,
                    session_ids=(session_id,),
                    activity_ids=(completed_id,),
                    evidence_refs=(session_id, completed_id),
                    limitations=tuple(limitations),
                ))
                continue
            else:
                # Link points to missing activity — insufficient data.
                relations.append(DailyRelation(
                    day=day,
                    status="insufficient_data",
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=(),
                    evidence_refs=(session_id,),
                    limitations=("completed_activity_id_not_found",),
                ))
                continue

        # --- No explicit link: set comparison ---

        # Optional session without activity — skip, not a violation.
        if is_optional and not day_activities:
            continue

        # Recovery / rest sessions — special handling.
        if session_sport in _RECOVERY_SPORTS:
            if day_activities:
                # Activity on a rest day.
                act_ids = tuple(a["id"] for a in day_activities)
                relations.append(DailyRelation(
                    day=day,
                    status="other_sport_same_day",
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=act_ids,
                    evidence_refs=(session_id, *act_ids),
                    limitations=("sin criterio de compatibilidad validado",),
                ))
            else:
                # Rest day, no activity — fine.
                pass
            continue

        # Find matching activities by sport.
        matching = activities_by_sport.get(session_sport or "", [])
        # Filter out already-used activities.
        matching = [a for a in matching if a["id"] not in used_activity_ids]

        if not matching:
            # No activity of the expected sport.
            if day_activities:
                # Other sport(s) recorded.
                act_ids = tuple(a["id"] for a in day_activities
                                if a["id"] not in used_activity_ids)
                relations.append(DailyRelation(
                    day=day,
                    status="other_sport_same_day",
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=act_ids,
                    evidence_refs=(session_id, *act_ids),
                    limitations=(),
                ))
            else:
                # No activity at all.
                if _provider_coverage_sufficient(provider_status, day):
                    status = "no_activity_recorded"
                    limitations = ()
                else:
                    status = "insufficient_data"
                    limitations = ("provider_coverage_insufficient",)
                relations.append(DailyRelation(
                    day=day,
                    status=status,
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=(),
                    evidence_refs=(session_id,),
                    limitations=limitations,
                ))
            continue

        # Multiple matching activities — ambiguous, don't force pairing.
        if len(matching) > 1:
            act_ids = tuple(a["id"] for a in matching)
            relations.append(DailyRelation(
                day=day,
                status="insufficient_data",
                link_status="ambiguous",
                historical_target_status="n/a",
                session_ids=(session_id,),
                activity_ids=act_ids,
                evidence_refs=(session_id, *act_ids),
                limitations=("multiple_matching_activities",),
            ))
            continue

        # Single matching activity — compare.
        activity = matching[0]
        act_ids = (activity["id"],)
        used_activity_ids.add(activity["id"])

        limitations: list[str] = []

        # Check if session type admits duration comparison.
        if session_type in _NO_DURATION_COMPAT:
            limitations.append("sin criterio de compatibilidad validado")
            status = "insufficient_data"
        elif _has_full_duration_range(session):
            status = _duration_status(session, activity)
        else:
            # Same sport, no duration range — show magnitude only.
            status = "insufficient_data"
            limitations.append("sin criterio de compatibilidad validado")

        relations.append(DailyRelation(
            day=day,
            status=status,
            link_status="unconfirmed",
            historical_target_status="n/a",
            session_ids=(session_id,),
            activity_ids=act_ids,
            evidence_refs=(session_id, *act_ids),
            limitations=tuple(limitations),
        ))

    return tuple(relations)


def _duration_status(session: Mapping, activity: Mapping) -> str:
    """Compare activity duration against session's duration range.

    Returns "compatible_with_plan" if within range,
    "compatible_with_adjustments" if outside range.
    """
    dmin = session["duration_min"]  # minutes
    dmax = session["duration_max"]  # minutes
    duration_s = activity.get("duration_s")
    if duration_s is None:
        return "compatible_with_plan"

    # Convert session range to seconds for comparison.
    duration_min_s = dmin * 60
    duration_max_s = dmax * 60

    if duration_min_s <= duration_s <= duration_max_s:
        return "compatible_with_plan"
    return "compatible_with_adjustments"
