"""Read-only queue aggregates, without schema creation or job claiming."""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

STATES = ('pending', 'running', 'completed', 'failed', 'unknown')
DATES = {'oldest_pending_at': ('pending', 'created_at', 'min'),
         'oldest_running_claimed_at': ('running', 'claimed_at', 'min'),
         'last_completed_at': ('completed', 'completed_at', 'max'),
         'last_failed_at': ('failed', 'completed_at', 'max')}
ISO = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'

class QueueSnapshot(TypedDict):
    available: bool
    counts: dict[str, int]
    oldest_pending_at: str | None
    oldest_running_claimed_at: str | None
    last_completed_at: str | None
    last_failed_at: str | None
    last_completed_output_source: str | None
    invalid_date_counts: dict[str, int]

def empty_snapshot(available=False) -> QueueSnapshot:
    return dict(available=available, counts=dict.fromkeys(STATES, 0),
                invalid_date_counts=dict.fromkeys(DATES, 0), last_completed_output_source=None,
                **dict.fromkeys(DATES))

def parse_date(value, now):
    if not isinstance(value, str) or not re.fullmatch(ISO, value):
        return None
    try:
        if value[-1] != 'Z':
            h, m = int(value[-5:-3]), int(value[-2:])
            if h > 14 or m > 59 or (h == 14 and m):
                return None
        local = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # datetime supports years 1..9999; reject boundary offsets that could
        # normalize outside that range, matching the SQL guard below.
        if local.year in (1, 9999) and local.utcoffset().total_seconds() != 0:
            return None
        result = local.astimezone(timezone.utc)
        return result if result <= now else None
    except (ValueError, OverflowError):
        return None

def _sql_date(expr):
    y, m, d = (f'substring({expr},{start},{size})::int' for start,size in [(1,4),(6,2),(9,2)])
    days = f'CASE WHEN {m}=2 THEN CASE WHEN mod({y},400)=0 OR (mod({y},4)=0 AND mod({y},100)<>0) THEN 29 ELSE 28 END WHEN {m} IN (4,6,9,11) THEN 30 ELSE 31 END'
    # No integer/date cast is reached before the whole shape has matched.
    return f'''CASE WHEN {expr} ~ '{ISO}' THEN CASE WHEN
      {y} BETWEEN 1 AND 9999 AND {m} BETWEEN 1 AND 12 AND {d} BETWEEN 1 AND ({days})
      AND substring({expr},12,2)::int BETWEEN 0 AND 23
      AND substring({expr},15,2)::int BETWEEN 0 AND 59
      AND substring({expr},18,2)::int BETWEEN 0 AND 59
      AND CASE WHEN substring({expr},1,4)::int IN (1,9999) AND right({expr},6) NOT IN ('+00:00','-00:00') THEN false
        WHEN right({expr},1)='Z' THEN true ELSE
        substring(right({expr},6),2,2)::int BETWEEN 0 AND 14 AND right({expr},2)::int BETWEEN 0 AND 59
        AND (substring(right({expr},6),2,2)::int<14 OR right({expr},2)::int=0) END
      THEN ({expr})::timestamptz END END'''

def read_snapshot(chat_id: str, *, now: datetime, database_url: str | None, path: Path) -> QueueSnapshot:
    if now.tzinfo is None:
        raise ValueError('timezone-aware now required')
    if not chat_id:
        return empty_snapshot()
    if database_url:
        return _postgres_snapshot(database_url, chat_id, now)
    try:
        rows = json.loads(path.read_text()) if path.exists() else []
        if not isinstance(rows, list):
            return empty_snapshot()
    except (OSError, ValueError):
        return empty_snapshot()
    result = empty_snapshot(True)
    last_completed_source_at = None
    for row in rows:
        if not isinstance(row, dict) or str(row.get('chat_id', '')) != chat_id:
            continue
        state = row.get('status')
        state = state if isinstance(state, str) and state in STATES else 'unknown'
        result['counts'][state] += 1
        for key, (target, field, operation) in DATES.items():
            if state != target:
                continue
            stamp = parse_date(row.get(field), now)
            if stamp is None:
                result['invalid_date_counts'][key] += 1
            else:
                value = stamp.isoformat()
                old = parse_date(result[key], now)
                chosen = stamp if old is None else (min(old, stamp) if operation == 'min' else max(old, stamp))
                result[key] = chosen.isoformat()
                if key == 'last_completed_at' and (last_completed_source_at is None or stamp >= last_completed_source_at):
                    last_completed_source_at = stamp
                    result['last_completed_output_source'] = row.get('output_source')
    return result

def _postgres_snapshot(url, chat_id, now):
    import psycopg
    projections = [f"count(*) FILTER (WHERE state='{s}')" for s in STATES]
    for key, (state, field, operation) in DATES.items():
        projections.extend([f"{operation}({field}) FILTER (WHERE state='{state}' AND {field}<=clock)",
                            f"count(*) FILTER (WHERE state='{state}' AND ({field} IS NULL OR {field}>clock))"])
    query = f'''WITH dated AS (SELECT
      CASE WHEN status IN ('pending','running','completed','failed') THEN status ELSE 'unknown' END AS state,
      created_at, {_sql_date("document->>'claimed_at'")} AS claimed_at,
      {_sql_date("document->>'completed_at'")} AS completed_at,
      document->>'output_source' AS output_source, %s::timestamptz AS clock
      FROM coach_ai_jobs WHERE document->>'chat_id'=%s)
      SELECT {', '.join(projections)},
        (SELECT latest.output_source FROM dated AS latest
         WHERE latest.state='completed' AND latest.completed_at<=latest.clock
         ORDER BY latest.completed_at DESC NULLS LAST LIMIT 1)
      FROM dated'''
    try:
        with psycopg.connect(url) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            row = conn.execute(query, (now, chat_id)).fetchone()
    except (psycopg.OperationalError, psycopg.errors.UndefinedTable, psycopg.errors.InsufficientPrivilege):
        logging.getLogger(__name__).warning('queue_status_unavailable')
        return empty_snapshot()
    result = empty_snapshot(True)
    result['counts'] = dict(zip(STATES, row[:5]))
    for i, key in enumerate(DATES):
        stamp, invalid = row[5+2*i:7+2*i]
        result[key] = stamp.astimezone(timezone.utc).isoformat() if stamp else None
        result['invalid_date_counts'][key] = invalid
    result['last_completed_output_source'] = row[5 + 2 * len(DATES)]
    return result
