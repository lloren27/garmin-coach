"""Explicit availability, independent from numeric wellness/activity evidence."""
from datetime import datetime

ERRORS = {'auth_error', 'network_error', 'api_error', 'invalid_data', 'error', 'unavailable'}

def state_record(raw, *, scope, now, collected_at=None):
    raw = raw if isinstance(raw, dict) else {}
    status = raw.get('status', 'unknown')
    count = raw.get('records_received')
    if status in ERRORS:
        state = 'provider_error'
    elif status in {'disabled', 'not_configured'}:
        state = 'not_configured'
    elif status == 'partial':
        state = 'partial'
    elif status == 'ok':
        state = ('no_activity' if scope == 'activities' else 'no_data') if count == 0 else 'available'
    elif status == 'unknown':
        state = 'unknown'
    else:
        state = 'no_data'
    stamp = raw.get('last_success_at') or collected_at
    if state in {'available', 'no_activity'}:
        try:
            parsed = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                state = 'unknown'
            elif parsed.astimezone(now.tzinfo).date() < now.date():
                state = 'stale'
        except (TypeError, ValueError):
            state = 'unknown'
    reason = raw.get('reason')
    if not isinstance(reason, str) or not reason.replace('_', '').isalnum() or len(reason) > 80:
        reason = None
    return dict(state=state, status=status, scope=scope, reason=reason,
                last_attempt_at=raw.get('last_attempt_at') or collected_at,
                last_success_at=raw.get('last_success_at'),
                period_start=raw.get('period_start'), period_end=raw.get('period_end'),
                failed_dates=raw.get('failed_dates', []),
                records_received=count, error=status if status in ERRORS else None)

def context_provider_states(extra, now):
    result = {}
    collected = extra.get('generated_at')
    for scope, statuses in [('activities', extra.get('activity_provider_status') or {}),
                            ('wellness', (extra.get('wellness') or {}).get('provider_status') or extra.get('provider_status') or {})]:
        providers = ('garmin', 'zepp', 'strava') if scope == 'activities' else ('garmin', 'zepp')
        for provider in providers:
            result[f'{provider}.{scope}'] = state_record(statuses.get(provider), scope=scope,
                                                       now=now, collected_at=collected)
    raw = extra.get('wattwise_live')
    result['wattwise'] = state_record(raw, scope='analysis', now=now,
                                      collected_at=(raw or {}).get('observed_at'))
    return result
