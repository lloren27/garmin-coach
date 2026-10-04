"""Trusted enqueue-time parsing for deterministic coach date resolution."""
from datetime import datetime


def job_created_at(job: dict) -> datetime:
    """Return the backend-stamped enqueue instant; never substitute worker time."""
    value = job.get('created_at') if isinstance(job, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('AI job is missing a valid creation timestamp')
    try:
        created_at = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('AI job is missing a valid creation timestamp') from None
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError('AI job is missing a valid creation timestamp')
    return created_at
