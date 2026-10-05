"""Pure, component-scoped observations and plan comparisons.

No selector, rendering, model calls, storage or plan decisions live here.
The validated snapshot is the sole authority; missing information stays missing.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, localcontext
from enum import Enum
from zoneinfo import ZoneInfo

from .coach_generation_context import ContextSnapshot, freeze
from .coach_intent import DateSelector


class Unit(str, Enum):
    SECONDS = 's'
    MINUTES = 'min'
    KILOMETRES = 'km'
    SECONDS_PER_KM = 's/km'
    BPM = 'bpm'
    WATTS = 'W'
    SCORE = 'score'
    BOOLEAN = 'boolean'
    TRIMP = 'trimp'
    TSS = 'tss'
    MUSCULAR_LOAD = 'muscular_load'
    PERCENT = '%'


class MatchState(str, Enum):
    CONFIRMED = 'confirmed'
    CANDIDATE = 'candidate'
    AMBIGUOUS_MULTIPLE = 'ambiguous_multiple'
    IMPLAUSIBLE_SINGLE = 'implausible_single'
    INSUFFICIENT_DATA = 'insufficient_data'
    NONE = 'none'


@dataclass(frozen=True)
class AnalysisFact:
    id: str
    metric: str
    value: Decimal | bool
    unit: Unit
    date: date
    sport: str | None
    source: str
    source_refs: tuple[str, ...]
    freshness: str
    source_records: tuple = ()
    operand_refs: tuple[str, ...] = ()
    formula: str | None = None
    coverage: str = 'unknown'


@dataclass(frozen=True)
class MagnitudeComparison:
    metric: str
    unit: Unit
    observed: Decimal
    lower: Decimal
    upper: Decimal
    reference: Decimal
    outside_band: bool
    operand_refs: tuple[str, ...]
    delta: Decimal | None = None
    percent: Decimal | None = None


@dataclass(frozen=True)
class PlanMatch:
    date: date
    sport: str | None
    state: MatchState
    activity_refs: tuple[str, ...]
    session_refs: tuple[str, ...]
    comparisons: tuple[MagnitudeComparison, ...] = ()


@dataclass(frozen=True)
class AnalysisFacts:
    snapshot_id: str
    component_index: int
    observed_dates: tuple[date, ...]
    facts: tuple[AnalysisFact, ...]
    matches: tuple[PlanMatch, ...]
    limitations: tuple[str, ...]
    provider_status: Mapping


_UNITS = {
    'duration_s': Unit.SECONDS, 'distance_km': Unit.KILOMETRES,
    'duration_min': Unit.MINUTES, 'duration_max': Unit.MINUTES,
    'total_minutes': Unit.MINUTES, 'deep_minutes': Unit.MINUTES,
    'rem_minutes': Unit.MINUTES, 'light_minutes': Unit.MINUTES,
    'awake_minutes': Unit.MINUTES, 'sleep_seconds': Unit.SECONDS,
    'avg_hr': Unit.BPM, 'max_hr': Unit.BPM, 'resting_hr': Unit.BPM,
    'avg_power': Unit.WATTS, 'avg_power_w': Unit.WATTS,
    'score': Unit.SCORE, 'stress_avg': Unit.SCORE,
    'trimp': Unit.TRIMP, 'tss': Unit.TSS, 'load_score_7d': Unit.MUSCULAR_LOAD,
    'pain': Unit.BOOLEAN, 'soreness': Unit.BOOLEAN,
}
_POSITIVE = {'duration_s', 'duration_min', 'duration_max', 'distance_km'}


def _number(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = Decimal(str(value))
    return number if number.is_finite() else None


def _day(value) -> date | None:
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _covered_empty(snapshot: ContextSnapshot, day: date) -> bool:
    """Only explicit, fresh, date-bounded empty activity coverage proves absence."""
    statuses = [s for s in snapshot.provider_status.values()
                if s.get('scope') == 'activities' and s.get('state') != 'not_configured']
    return bool(statuses) and all(
        s.get('state') == 'no_activity'
        and (start := _day(s.get('period_start'))) is not None
        and (end := _day(s.get('period_end'))) is not None
        and start <= day <= end
        and day.isoformat() not in (s.get('failed_dates') or ())
        for s in statuses)


def build_analysis_facts(snapshot: ContextSnapshot, component_index: int = 0) -> AnalysisFacts:
    """Build immutable facts for this component's observed dates only.

    Advice dates never become observations. Unresolved scope returns no facts.
    Decimal arithmetic uses a local precision independent of the caller's context.
    """
    if snapshot.now.tzinfo is None or snapshot.now.utcoffset() is None:
        raise ValueError('snapshot.now must be timezone-aware')
    if type(component_index) is not int or not 0 <= component_index < len(snapshot.intent.components):
        raise ValueError('invalid component index')
    with localcontext(Context(prec=28)):
        return _build(snapshot, component_index)


def _build(snapshot, index):
    component = snapshot.intent.components[index]
    today = snapshot.now.astimezone(ZoneInfo('Europe/Madrid')).date()
    limits, facts, matches = set(), [], []
    dates = tuple(sorted(set(d for d in component.observed_dates if d <= today)))
    if len(dates) != len(component.observed_dates):
        limits.add('FUTURE_OBSERVATIONS_EXCLUDED')
    if component.selector in (DateSelector.LATEST_ACTIVITY, DateSelector.LATEST_TRAINING_DAY):
        activities = [e for e in snapshot.evidence.values() if e.kind == 'activity'
                      and (d := _day(e.date)) is not None and d <= today]
        dates = (max(_day(e.date) for e in activities),) if activities else ()
        if component.selector is DateSelector.LATEST_ACTIVITY and dates:
            if sum(_day(e.date) == dates[0] for e in activities) > 1:
                dates = ()
                limits.add('LATEST_ACTIVITY_AMBIGUOUS')
    if not dates:
        limits.add('NO_OBSERVED_SCOPE')
    evidence = [e for e in snapshot.evidence.values() if _day(e.date) in dates and e.kind != 'plan']
    evidence.sort(key=lambda e: e.id)
    sessions = {k: s for k, s in snapshot.sessions.items() if _day(s.get('date')) in dates}
    by_key = {}

    def add(ref, metric, value, unit, day, sport, source, freshness,
            source_records=(), operands=(), formula=None):
        identifier = f'c{index}:{ref}:{metric}'
        operand_facts = [by_key[r] for r in operands]
        refs = tuple(sorted({r for f in operand_facts for r in f.source_refs})) if operands else (ref,)
        if operands:
            freshnesses = {f.freshness for f in operand_facts}
            freshness = next(iter(freshnesses)) if len(freshnesses) == 1 else 'partial'
            coverages = {f.coverage for f in operand_facts}
            coverage = next(iter(coverages)) if len(coverages) == 1 else 'partial'
        elif ref.startswith('session:'):
            coverage = 'snapshot_only'
        else:
            record = snapshot.evidence[ref]
            scope = {'activity': 'activities', 'wellness': 'wellness'}.get(record.kind)
            coverage = snapshot.provider_status.get(f'{source}.{scope}', {}).get('state', 'unknown')
        fact = AnalysisFact(identifier, metric, value, unit, day, sport, source,
                            refs, freshness, freeze(source_records), operands, formula, coverage)
        facts.append(fact)
        by_key[identifier] = fact
        return fact

    def raw(ref, values, day, sport, source, freshness, records=()):
        for metric, unit in _UNITS.items():
            value = values.get(metric)
            if value is None:
                continue
            if unit is Unit.BOOLEAN:
                if value not in (True, False, 0, 1):
                    limits.add('INVALID_MEASUREMENT')
                    continue
                number = bool(value)
            else:
                number = _number(value)
                if number is None or number < 0 or (metric in _POSITIVE and number == 0):
                    limits.add('INVALID_MEASUREMENT')
                    continue
            add(ref, metric, number, unit, day, sport, source, freshness, records)

    for e in evidence:
        raw(e.id, e.facts, _day(e.date), e.sport, e.source, e.freshness, e.source_records)
        duration = by_key.get(f'c{index}:{e.id}:duration_s')
        distance = by_key.get(f'c{index}:{e.id}:distance_km')
        if e.kind == 'activity' and e.sport in {'running', 'walking'} and duration and distance:
            add(e.id, 'pace_s_per_km', duration.value / distance.value, Unit.SECONDS_PER_KM,
                _day(e.date), e.sport, e.source, e.freshness, e.source_records,
                (duration.id, distance.id), 'duration_s / distance_km')
            limits.add('PACE_DURATION_BASIS_UNSPECIFIED')
        if e.kind == 'wellness':
            limits.add('WELLNESS_BASELINE_NOT_ESTABLISHED')

    for key, s in sorted(sessions.items()):
        ref = f'session:{key}'
        raw(ref, s, _day(s['date']), s.get('sport'), 'training_plan', 'unknown')
        for field in ('duration_min', 'duration_max'):
            fact = by_key.get(f'c{index}:{ref}:{field}')
            if fact:
                add(ref, field + '_s', fact.value * 60, Unit.SECONDS, fact.date, fact.sport,
                    'training_plan', 'unknown', operands=(fact.id,), formula=f'{field} * 60')

    def comparisons(activity, key):
        out = []
        specs = [('duration', 'duration_s', 'duration_min_s', 'duration_max_s', Unit.SECONDS),
                 ('distance', 'distance_km', 'distance_km', 'distance_km', Unit.KILOMETRES)]
        for metric, observed_key, low_key, high_key, unit in specs:
            obs = by_key.get(f'c{index}:{activity.id}:{observed_key}')
            low = by_key.get(f'c{index}:session:{key}:{low_key}')
            high = by_key.get(f'c{index}:session:{key}:{high_key}')
            if metric == 'duration' and bool(low) != bool(high):
                limits.add('INCOMPLETE_PLAN_RANGE')
            if low and high and low.value > high.value:
                limits.add('INVALID_PLAN_RANGE')
                continue
            if not (obs and low and high):
                continue
            reference = min(max(obs.value, low.value), high.value)
            ratio = obs.value / reference
            out.append(MagnitudeComparison(metric, unit, obs.value, low.value, high.value,
                       reference, not Decimal('0.5') <= ratio <= 2,
                       tuple(dict.fromkeys((obs.id, low.id, high.id)))))
        return tuple(out)

    def match(day, sport, activities, keys):
        refs = tuple(a.id for a in activities)
        keys = tuple(keys)

        def append(state, cs=(), selected_refs=refs, selected_keys=keys):
            matches.append(PlanMatch(day, sport, state, selected_refs,
                                     tuple('session:' + k for k in selected_keys), cs))

        linked = []
        for key in keys:
            link = sessions[key].get('completed_activity_id')
            if link:
                selected = [a for a in activities if a.id in (str(link), f'activity:{link}')]
                if len(selected) != 1:
                    append(MatchState.INSUFFICIENT_DATA)
                    limits.add('INVALID_CONFIRMED_LINK')
                    return
                linked.append((selected[0], key))
        if len({a.id for a, _ in linked}) != len(linked):
            append(MatchState.AMBIGUOUS_MULTIPLE)
            return
        if linked:
            for activity, key in linked:
                cs = final_comparisons(comparisons(activity, key), MatchState.CONFIRMED, day, sport, key)
                append(MatchState.CONFIRMED, cs, (activity.id,), (key,))
            remaining_a = [a for a in activities if a.id not in {a.id for a, _ in linked}]
            remaining_s = [k for k in keys if k not in {k for _, k in linked}]
            if remaining_a or remaining_s:
                match(day, sport, remaining_a, remaining_s)
            return
        if not activities or not keys:
            absence_known = (not keys and 'sessions' in snapshot.plan) or (
                not activities and _covered_empty(snapshot, day))
            append(MatchState.NONE if absence_known else MatchState.INSUFFICIENT_DATA)
        elif sport is None:
            append(MatchState.INSUFFICIENT_DATA)
        elif len(activities) * len(keys) > 1:
            append(MatchState.AMBIGUOUS_MULTIPLE)
        else:
            cs = comparisons(activities[0], keys[0])
            state = (MatchState.INSUFFICIENT_DATA if not cs else
                     MatchState.IMPLAUSIBLE_SINGLE if any(c.outside_band for c in cs)
                     else MatchState.CANDIDATE)
            append(state, final_comparisons(cs, state, day, sport, keys[0]))

    def final_comparisons(cs, state, day, sport, key):
        if state not in (MatchState.CANDIDATE, MatchState.CONFIRMED):
            return cs
        result = []
        for c in cs:
            delta = c.observed - c.reference
            percent = delta / c.reference * 100
            add(f'comparison:{key}', c.metric + '_delta', delta, c.unit, day, sport,
                'derived', 'derived', operands=c.operand_refs,
                formula='observed - clamp(observed, lower, upper)')
            add(f'comparison:{key}', c.metric + '_percent', percent, Unit.PERCENT, day, sport,
                'derived', 'derived', operands=c.operand_refs,
                formula='100 * (observed - clamp(observed, lower, upper)) / clamp(observed, lower, upper)')
            result.append(MagnitudeComparison(c.metric, c.unit, c.observed, c.lower, c.upper,
                          c.reference, c.outside_band, c.operand_refs, delta, percent))
        return tuple(result)

    for day in dates:
        activities = [e for e in evidence if e.kind == 'activity' and _day(e.date) == day]
        keys = [k for k, s in sorted(sessions.items()) if _day(s.get('date')) == day]
        sports = {e.sport for e in activities} | {sessions[k].get('sport') for k in keys}
        if len({s for s in sports if s}) > 1:
            limits.add('MULTISPORT_COMPONENTS_SEPARATE')
        if not activities:
            limits.add('ACTIVITY_NOT_RECORDED' if _covered_empty(snapshot, day) else 'DATA_COVERAGE_INCOMPLETE')
        for sport in sorted(sports or {None}, key=lambda s: s or ''):
            match(day, sport, [e for e in activities if e.sport == sport],
                  [k for k in keys if sessions[k].get('sport') == sport])
    if dates and any(s.get('state') in {'provider_error', 'partial', 'stale'}
                     for s in snapshot.provider_status.values()):
        limits.add('DATA_COVERAGE_INCOMPLETE')
    return AnalysisFacts(snapshot.id, index, dates, tuple(facts), tuple(matches),
                         tuple(sorted(limits)), freeze(snapshot.provider_status))
