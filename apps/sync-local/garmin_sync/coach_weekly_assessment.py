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
    - Only consider plans created on or before ``as_of`` (the job creation time).
    - For past days (day < as_of.date()): select the plan that was in effect
      at the time of the activity. If activity_times are available, prefer the
      most recent plan created before the earliest activity. If no activity
      times are available, use the most recent plan created before the day.
      A plan created after the activity gets a limitation.
    - For future days (day >= as_of.date()): use the most recent plan valid at
      ``as_of`` that covers the day.
    - A plan created on the same day as the activity without reliable times
      is indeterminate.
    """
    # Filter: only plans created before as_of (the job was created at as_of).
    available: list[Mapping] = []
    for plan in plans:
        plan_created = datetime.fromisoformat(plan["created_at"])
        if plan_created > as_of:
            continue  # Plan didn't exist when the job was created.
        start = date.fromisoformat(plan["start_date"])
        end = date.fromisoformat(plan["end_date"])
        if start <= day <= end:
            available.append(plan)

    if not available:
        return DayPlanSelection(day, None, "no_plan", ())

    is_past_day = day < as_of.date()

    if is_past_day:
        # Past day: the plan that governed the day is the one that was in effect
        # at the time of the activity — the most recent plan created before
        # the activity (or before the day if no times available).
        if activity_times:
            # Check for mixed timezone awareness: if some times have tzinfo
            # and others don't, min() will raise TypeError.  Treat as
            # indeterminate — we cannot reliably order plan vs activity.
            tz_aware = [t for t in activity_times if t.tzinfo is not None]
            tz_naive = [t for t in activity_times if t.tzinfo is None]
            if tz_aware and tz_naive:
                # Mixed timezone awareness — cannot safely compare.
                earliest_activity = None
            elif tz_aware:
                earliest_activity = min(tz_aware)
            else:
                # All timezone-naive — cannot reliably order against plan.
                earliest_activity = None
            # Plans created before the earliest activity on this day.
            before_activity: list[Mapping] = []
            if earliest_activity is not None:
                before_activity = [
                    p for p in available
                    if datetime.fromisoformat(p["created_at"]) <= earliest_activity
                ]
            if before_activity:
                # Use the most recent plan created before the activity.
                before_activity.sort(key=lambda p: p["created_at"], reverse=True)
                selected = before_activity[0]
            elif earliest_activity is None:
                # Without comparable times, a plan created before the day is
                # known to precede every activity on that day.
                before_day = [
                    p for p in available
                    if datetime.fromisoformat(p["created_at"]).date() < day
                ]
                selected = max(before_day or available, key=lambda p: p["created_at"])
            else:
                # All available plans were created after the activity.
                # Use the earliest one (least recent creation) with limitation.
                available.sort(key=lambda p: p["created_at"])
                selected = available[0]
        else:
            # No activity times — use the most recent plan created before the day.
            before_day: list[Mapping] = [
                p for p in available
                if datetime.fromisoformat(p["created_at"]).date() < day
            ]
            if before_day:
                before_day.sort(key=lambda p: p["created_at"], reverse=True)
                selected = before_day[0]
            else:
                # All plans created on or after the day — indeterminate.
                available.sort(key=lambda p: p["created_at"])
                selected = available[0]
    else:
        # Future day: use the most recent plan valid at as_of.
        available.sort(key=lambda p: p["created_at"], reverse=True)
        selected = available[0]

    plan_id = selected["id"]
    plan_created = datetime.fromisoformat(selected["created_at"])

    limitations: list[str] = []

    # Check if plan was created after the day's activities.
    if plan_created.date() > day:
        limitations.append("plan_created_after_activity")
    elif plan_created.date() == day:
        # Same day — check if we have reliable activity times to order.
        if activity_times:
            tz_aware = [t for t in activity_times if t.tzinfo is not None]
            tz_naive = [t for t in activity_times if t.tzinfo is None]
            if tz_aware and tz_naive:
                # Mixed timezone awareness — indeterminate.
                limitations.append("plan_created_after_activity")
            elif tz_aware:
                # We can compare: check if plan was created after the activity.
                earliest_activity = min(tz_aware)
                if plan_created > earliest_activity:
                    limitations.append("plan_created_after_activity")
            else:
                # All timezone-naive — indeterminate.
                limitations.append("plan_created_after_activity")
        else:
            # No activity times available — cannot order plan vs activity.
            limitations.append("plan_created_after_activity")

    if (not activity_times or any(t.tzinfo is None for t in activity_times)) and any(
        datetime.fromisoformat(p["created_at"]).date() == day for p in available
    ) and "plan_created_after_activity" not in limitations:
        # A different plan may have taken effect during this day.
        limitations.append("plan_created_after_activity")

    return DayPlanSelection(day, plan_id, "available", tuple(limitations))


def _has_full_duration_range(session: Mapping) -> bool:
    """Return True when the session has both duration_min and duration_max."""
    dmin = session.get("duration_min")
    dmax = session.get("duration_max")
    return (isinstance(dmin, (int, float)) and isinstance(dmax, (int, float))
            and dmin > 0 and dmax >= dmin)


# Providers that supply activity records — only these are relevant for
# verifying whether a day has no activity recorded.  Wellness, Wattwise,
# and other non-activity providers are not consulted for coverage checks.
# The snapshot may use simple keys ("garmin") or compound keys
# ("garmin.activities").  Accept both forms.
_ACTIVITY_PROVIDERS = frozenset({"garmin", "strava", "zepp",
                                 "garmin.activities", "strava.activities",
                                 "zepp.activities"})


def _provider_coverage_sufficient(
    provider_status: Mapping, day: date
) -> bool:
    """Check whether activity providers cover the day sufficiently.

    Only evaluates activity providers (Garmin, Strava, Zepp).  Wellness,
    Wattwise and other non-activity providers are ignored — their status
    should not prevent confirming a day is empty when activity providers
    do cover it.

    Returns False when no activity provider has a confirmed coverage window
    that includes the day, or when any activity provider has an error or
    unknown status without a verified window.

    If no activity providers are configured at all, return False — we cannot
    verify absence without any source.
    """
    has_any_provider = False
    for name, status in provider_status.items():
        # Only evaluate activity providers — skip wellness, Wattwise, etc.
        if name not in _ACTIVITY_PROVIDERS:
            continue
        if not isinstance(status, Mapping):
            continue
        state = status.get("state")
        if state == "not_configured" or status.get("status") in ("disabled", "not_configured"):
            continue
        has_any_provider = True
        if state is not None:
            if state != "no_activity":
                return False
        elif status.get("status") != "ok" or status.get("records_received") != 0:
            return False
        period_start = status.get("period_start")
        period_end = status.get("period_end")

        # Provider claims "ok" — but does it have a coverage window?
        if period_start is None or period_end is None:
            # No coverage window — cannot verify the day is covered.
            return False

        # Check the coverage window includes the day.
        if date.fromisoformat(period_start) > day:
            return False
        if date.fromisoformat(period_end) < day:
            return False
        if day.isoformat() in (status.get("failed_dates") or ()):
            return False

    # No activity providers configured at all — cannot verify absence.
    if not has_any_provider:
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


def _activity_type_compatible_with_session(
    session_type: str, activity_type: str | None
) -> bool:
    """Only identical, known types support a duration comparison."""
    return bool(session_type and activity_type and session_type == activity_type)


def _deduplicate_activities(activities: Sequence[Mapping]) -> list[Mapping]:
    """Deduplicate activities that represent the same event across sources.

    Two activities are considered duplicates when they share the same
    sport and started_at_utc (within the same second). Keep the first
    occurrence encountered.

    Activities without started_at_utc are NOT deduplicated against each
    other — they may represent different events on the same day.
    Only activities with the same explicit started_at_utc are deduplicated.
    """
    seen: set[tuple[str, str]] = set()
    deduplicated: list[Mapping] = []
    for act in activities:
        sport = act.get("sport") or "unknown"
        started = act.get("started_at_utc")
        # Only deduplicate when we have a reliable started_at_utc.
        # Activities without started_at_utc are kept as distinct events.
        if started:
            key = (sport, started)
            if key in seen:
                continue  # Duplicate of a same-sport activity at the same time.
            seen.add(key)
        deduplicated.append(act)
    return deduplicated


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

    Rules:
    - If selection indicates no_plan, activities are reported as activity_added.
    - If selection has plan_created_after_activity limitation, propagate it
      to all relations so the caller knows the plan may not have governed the day.
    - Deduplicate activities across sources before comparison.
    - When multiple sessions share the same sport on a day and there are
      multiple matching activities, do not force pairings — mark ambiguous.
    - Emit a relation for activities that remain unassigned after all sessions
      are processed.
    """
    relations: list[DailyRelation] = []
    selection_limitations = selection.limitations

    # If selection indicates no_plan, we cannot compare against a plan.
    # Report all activities as activity_added and skip session comparison.
    if selection.status == "no_plan":
        raw_activities = [a for a in activities
                          if a.get("local_date") == day.isoformat()
                          or a.get("date") == day.isoformat()]
        day_activities = _deduplicate_activities(raw_activities)
        if day_activities:
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
                limitations=selection_limitations,
            ))
        return tuple(relations)

    # Filter sessions for this day.
    day_sessions = [s for s in sessions if s.get("date") == day.isoformat()]

    # If the plan was created after the activity, we cannot claim
    # compatibility — the plan may not have governed the day.
    plan_not_applicable = "plan_created_after_activity" in selection_limitations

    # Filter and deduplicate activities for this day.
    raw_activities = [a for a in activities
                      if a.get("local_date") == day.isoformat()
                      or a.get("date") == day.isoformat()]
    day_activities = _deduplicate_activities(raw_activities)

    # No sessions for this day.
    if not day_sessions:
        if day_activities:
            activity_ids = tuple(a["id"] for a in day_activities)
            evidence = tuple(a["id"] for a in day_activities)
            limitations = selection_limitations
            relations.append(DailyRelation(
                day=day,
                status="activity_added",
                link_status="unconfirmed",
                historical_target_status="n/a",
                session_ids=(),
                activity_ids=activity_ids,
                evidence_refs=evidence,
                limitations=limitations,
            ))
        return tuple(relations)

    # Build activity lookup by sport.
    activities_by_sport: dict[str, list[Mapping]] = {}
    for act in day_activities:
        sport = act.get("sport") or "unknown"
        activities_by_sport.setdefault(sport, []).append(act)

    # Track which activities have been referenced.
    used_activity_ids: set[str] = set()

    # Group sessions by sport to detect ambiguous pairings.
    sessions_by_sport: dict[str, list[Mapping]] = {}
    for session in day_sessions:
        sport = session.get("sport") or "unknown"
        sessions_by_sport.setdefault(sport, []).append(session)

    for session in day_sessions:
        session_id = session["id"]
        session_sport = session.get("sport")
        session_type = session.get("session_type", "")
        is_optional = session.get("optional", False)
        completed_id = session.get("completed_activity_id")

        # Base limitations from selection.
        rel_limitations: list[str] = list(selection_limitations)

        # --- Explicit link check ---
        if completed_id:
            linked_activity = None
            for act in day_activities:
                if act["id"] == completed_id:
                    linked_activity = act
                    break

            if linked_activity:
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
                    rel_limitations.append("sin criterio de compatibilidad validado")
                elif _has_full_duration_range(session):
                    # Check activity type compatibility — read activity_type
                    # (the real context field), falling back to session_type.
                    act_type = linked_activity.get("activity_type") or linked_activity.get("session_type")
                    if not _activity_type_compatible_with_session(session_type, act_type):
                        status = "insufficient_data"
                        if act_type is None:
                            rel_limitations.append("activity_type_not_available")
                        else:
                            rel_limitations.append("activity_type_mismatch")
                    else:
                        status = _duration_status(session, linked_activity)
                        # If the plan was created after the activity or the
                        # historical target is uncertain, we cannot claim
                        # compatibility — use insufficient_data instead.
                        if plan_not_applicable:
                            status = "insufficient_data"
                            rel_limitations.append("plan may not have governed the day")
                        elif target_status == "uncertain":
                            status = "insufficient_data"
                            rel_limitations.append("historical_target_uncertain")
                else:
                    status = "insufficient_data"
                    rel_limitations.append("sin criterio de compatibilidad validado")

                if target_status == "uncertain":
                    if "historical_target_uncertain" not in rel_limitations:
                        rel_limitations.append("historical_target_uncertain")

                used_activity_ids.add(completed_id)
                relations.append(DailyRelation(
                    day=day,
                    status=status,
                    link_status="confirmed",
                    historical_target_status=target_status,
                    session_ids=(session_id,),
                    activity_ids=(completed_id,),
                    evidence_refs=(session_id, completed_id),
                    limitations=tuple(rel_limitations),
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
                    limitations=tuple(rel_limitations + ["completed_activity_id_not_found"]),
                ))
                continue

        # --- No explicit link: set comparison ---

        # Optional session without activity — skip, not a violation.
        if is_optional and not day_activities:
            continue

        # Recovery / rest sessions — special handling.
        if session_sport in _RECOVERY_SPORTS:
            if day_activities:
                act_ids = tuple(a["id"] for a in day_activities)
                relations.append(DailyRelation(
                    day=day,
                    status="other_sport_same_day",
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=act_ids,
                    evidence_refs=(session_id, *act_ids),
                    limitations=tuple(rel_limitations + ["sin criterio de compatibilidad validado"]),
                ))
            else:
                # Rest day, no activity — fine.
                pass
            continue

        # Find matching activities by sport.
        all_matching = activities_by_sport.get(session_sport or "", [])
        # Filter out already-used activities.
        matching = [a for a in all_matching if a["id"] not in used_activity_ids]

        # Check if there are multiple sessions of the same sport.
        same_sport_sessions = sessions_by_sport.get(session_sport or "", [])
        has_multiple_sessions = len(same_sport_sessions) > 1

        # If multiple sessions share the same sport, we cannot determine which
        # activity corresponds to which session — all are ambiguous.
        # Use all_matching (before filtering used) to show all candidates.
        if has_multiple_sessions:
            candidates = [a for a in all_matching if a["id"] not in used_activity_ids]
            if candidates:
                act_ids = tuple(a["id"] for a in candidates)
                rel_limitations.append("multiple_matching_activities")
                relations.append(DailyRelation(
                    day=day,
                    status="insufficient_data",
                    link_status="ambiguous",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=act_ids,
                    evidence_refs=(session_id, *act_ids),
                    limitations=tuple(rel_limitations),
                ))
            else:
                # All activities of this sport were already consumed by a
                # previous ambiguous session — still ambiguous, no candidates.
                rel_limitations.append("multiple_matching_activities")
                relations.append(DailyRelation(
                    day=day,
                    status="insufficient_data",
                    link_status="ambiguous",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=(),
                    evidence_refs=(session_id,),
                    limitations=tuple(rel_limitations),
                ))
            # Mark all remaining candidates as used so subsequent sessions
            # of the same sport see no candidates.
            for a in candidates if 'candidates' in dir() else []:
                used_activity_ids.add(a["id"])
            continue

        if not matching:
            # No activity of the expected sport.
            if day_activities:
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
                    limitations=tuple(rel_limitations),
                ))
            else:
                # No activity at all.
                if _provider_coverage_sufficient(provider_status, day):
                    status = "no_activity_recorded"
                else:
                    status = "insufficient_data"
                    rel_limitations.append("provider_coverage_insufficient")
                relations.append(DailyRelation(
                    day=day,
                    status=status,
                    link_status="unconfirmed",
                    historical_target_status="n/a",
                    session_ids=(session_id,),
                    activity_ids=(),
                    evidence_refs=(session_id,),
                    limitations=tuple(rel_limitations),
                ))
            continue

        # Multiple matching activities for this session — ambiguous.
        if len(matching) > 1:
            act_ids = tuple(a["id"] for a in matching)
            rel_limitations.append("multiple_matching_activities")
            relations.append(DailyRelation(
                day=day,
                status="insufficient_data",
                link_status="ambiguous",
                historical_target_status="n/a",
                session_ids=(session_id,),
                activity_ids=act_ids,
                evidence_refs=(session_id, *act_ids),
                limitations=tuple(rel_limitations),
            ))
            for a in matching:
                used_activity_ids.add(a["id"])
            continue

        # Single matching activity — compare.
        activity = matching[0]
        act_ids = (activity["id"],)
        used_activity_ids.add(activity["id"])

        # Check if session type admits duration comparison.
        if session_type in _NO_DURATION_COMPAT:
            rel_limitations.append("sin criterio de compatibilidad validado")
            status = "insufficient_data"
        elif _has_full_duration_range(session):
            # Check activity type compatibility — read activity_type
            # (the real context field), falling back to session_type.
            act_type = activity.get("activity_type") or activity.get("session_type")
            if not _activity_type_compatible_with_session(session_type, act_type):
                status = "insufficient_data"
                if act_type is None:
                    rel_limitations.append("activity_type_not_available")
                else:
                    rel_limitations.append("activity_type_mismatch")
            else:
                status = _duration_status(session, activity)
                # If the plan was created after the activity, we cannot claim
                # compatibility — use insufficient_data instead.
                if plan_not_applicable:
                    status = "insufficient_data"
                    rel_limitations.append("plan may not have governed the day")
        else:
            # Same sport, no duration range — show magnitude only.
            status = "insufficient_data"
            rel_limitations.append("sin criterio de compatibilidad validado")

        relations.append(DailyRelation(
            day=day,
            status=status,
            link_status="unconfirmed",
            historical_target_status="n/a",
            session_ids=(session_id,),
            activity_ids=act_ids,
            evidence_refs=(session_id, *act_ids),
            limitations=tuple(rel_limitations),
        ))

    # Emit relations for activities that were not assigned to any session.
    unassigned = [a for a in day_activities if a["id"] not in used_activity_ids]
    if unassigned:
        unassigned_ids = tuple(a["id"] for a in unassigned)
        relations.append(DailyRelation(
            day=day,
            status="activity_added",
            link_status="unconfirmed",
            historical_target_status="n/a",
            session_ids=(),
            activity_ids=unassigned_ids,
            evidence_refs=unassigned_ids,
            limitations=tuple(selection_limitations),
        ))

    return tuple(relations)


def _duration_status(session: Mapping, activity: Mapping) -> str:
    """Compare activity duration against session's duration range.

    Returns "compatible_with_plan" if within range,
    "compatible_with_adjustments" if outside range,
    "insufficient_data" if the activity duration is not available.
    """
    dmin = session["duration_min"]  # minutes
    dmax = session["duration_max"]  # minutes
    duration_s = activity.get("duration_s")
    if duration_s is None:
        # Cannot compare without actual duration evidence.
        return "insufficient_data"

    # Convert session range to seconds for comparison.
    duration_min_s = dmin * 60
    duration_max_s = dmax * 60

    if duration_min_s <= duration_s <= duration_max_s:
        return "compatible_with_plan"
    return "compatible_with_adjustments"
