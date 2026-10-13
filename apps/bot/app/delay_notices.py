"""Optional PostgreSQL-backed delayed-query notices."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
from datetime import datetime, timezone

import httpx

from .config import settings
from .experience import format_delay_notice
from . import store


logger = logging.getLogger(__name__)
MAX_DELAY_NOTICE_SECONDS = 604800
DELAY_NOTICE_MAX_JOBS_PER_CYCLE = 20
DELAY_NOTICE_POLL_SECONDS = 15
DELAY_NOTICE_SEND_TIMEOUT_SECONDS = 15
DELAY_NOTICE_COLUMNS = (
    "delay_notified_at",
    "delay_notice_claimed_at",
    "delay_notice_claim_token",
    "delay_notice_attempts",
)


def parse_delay_notice_seconds(raw: str | None) -> int | None:
    """Parse the opt-in threshold. ``None`` means disabled or invalid."""
    if raw is None:
        return None
    value = raw.strip()
    if value in ("", "0") or not re.fullmatch(r"[0-9]+", value):
        return None
    seconds = int(value)
    if not 1 <= seconds <= MAX_DELAY_NOTICE_SECONDS:
        return None
    return seconds


def is_delay_notice_disabled(raw: str | None) -> bool:
    return raw is None or raw.strip() in ("", "0")


def is_postgres_backend(database_url: str | None) -> bool:
    return bool(database_url and re.match(r"^postgres(?:ql)?://", database_url, re.IGNORECASE))


def missing_delay_notice_columns() -> tuple[str, ...]:
    """Inspect schema metadata only; never read or write column values here."""
    if not is_postgres_backend(store.DATABASE_URL):
        return DELAY_NOTICE_COLUMNS

    import psycopg

    with psycopg.connect(store.DATABASE_URL, connect_timeout=5) as conn:
        rows = conn.execute(
            """select column_name
               from information_schema.columns
               where table_schema = current_schema()
                 and table_name = 'coach_ai_jobs'
                 and column_name = any(%s)""",
            (list(DELAY_NOTICE_COLUMNS),),
        ).fetchall()
    present = {row[0] for row in rows}
    return tuple(column for column in DELAY_NOTICE_COLUMNS if column not in present)


async def _telegram_send(chat_id: str, text: str, *, total_timeout_seconds: float) -> bool:
    token = settings.telegram_bot_token
    if not token:
        return False
    if (
        isinstance(total_timeout_seconds, bool)
        or not isinstance(total_timeout_seconds, (int, float))
        or not math.isfinite(total_timeout_seconds)
        or total_timeout_seconds <= 0
    ):
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    async def request() -> bool:
        phase_timeout = max(0.1, min(float(total_timeout_seconds), 10.0))
        timeout = httpx.Timeout(
            connect=phase_timeout,
            read=phase_timeout,
            write=phase_timeout,
            pool=phase_timeout,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            payload = response.json()
            return isinstance(payload, dict) and payload.get("ok") is True

    try:
        return await asyncio.wait_for(request(), timeout=float(total_timeout_seconds))
    except (TimeoutError, httpx.HTTPError, ValueError):
        return False


def send_delay_notice(
    chat_id: str,
    text: str,
    *,
    total_timeout_seconds: float = DELAY_NOTICE_SEND_TIMEOUT_SECONDS,
) -> bool:
    """Send one Telegram message with a hard wall-clock deadline.

    The caller runs this synchronous boundary in ``asyncio.to_thread``. Its
    private event loop lets ``wait_for`` cancel HTTPX even if a response drips
    chunks below each individual phase timeout.
    """
    try:
        return asyncio.run(
            _telegram_send(chat_id, text, total_timeout_seconds=total_timeout_seconds)
        )
    except RuntimeError:
        # This function is a worker-thread boundary and must not run inside an
        # already running event loop.
        return False


def run_delay_notice_sweep_once(stop_event: threading.Event | None = None) -> int:
    """Claim, send and confirm at most 20 jobs sequentially in one cycle."""
    raw_threshold = settings.coach_delay_notice_seconds
    threshold_seconds = parse_delay_notice_seconds(raw_threshold)
    if (
        threshold_seconds is None
        or not is_postgres_backend(store.DATABASE_URL)
        or not settings.telegram_bot_token
        or (stop_event is not None and stop_event.is_set())
    ):
        return 0

    completed = 0
    attempted = 0
    while attempted < DELAY_NOTICE_MAX_JOBS_PER_CYCLE:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            claim = store.claim_next_delay_notice_job(threshold_seconds=threshold_seconds)
        except Exception:
            logger.exception("Delay-notice claim failed; sweep stopped")
            break
        if claim is None:
            break
        attempted += 1

        try:
            prepared = store.prepare_delay_notice_send(
                claim["job_id"], claim["claim_token"]
            )
            if prepared is None:
                continue
            sync = store.load_sync()
            notice = format_delay_notice(
                prepared, sync, now=datetime.now(timezone.utc)
            )
            prepared = store.prepare_delay_notice_send(
                prepared["job_id"], prepared["claim_token"]
            )
            if prepared is None:
                continue
            if not send_delay_notice(prepared["chat_id"], notice):
                continue
            if store.mark_delay_notice_sent(
                prepared["job_id"], prepared["claim_token"]
            ):
                completed += 1
        except Exception:
            logger.exception("Delay-notice attempt failed; lease will expire")

    return completed


async def run_delay_notice_loop(
    stop_event: threading.Event,
    wake_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(run_delay_notice_sweep_once, stop_event)
        if stop_event.is_set():
            break
        try:
            await asyncio.wait_for(wake_event.wait(), timeout=DELAY_NOTICE_POLL_SECONDS)
        except TimeoutError:
            continue
