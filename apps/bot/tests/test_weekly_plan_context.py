"""Historical week plans for a queued coach job."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, store
from app.config import Settings


MONDAY = date(2026, 10, 26)
JOB_TIME = "2026-10-28T12:00:00+00:00"


def fixture_rows():
    jobs = [
        {"id": "job-alice", "chat_id": "alice", "owner_id": "alice", "created_at": JOB_TIME, "status": "running"},
        {"id": "job-bob", "chat_id": "bob", "owner_id": "bob", "created_at": JOB_TIME, "status": "running"},
        {"id": "job-no-plan", "chat_id": "charlie", "owner_id": "charlie", "created_at": JOB_TIME, "status": "running"},
    ]
    plans = [
        {"id": "prior", "owner_id": "alice", "status": "superseded", "revision": 1,
         "start_date": "2026-10-26", "end_date": "2026-11-01", "created_at": "2026-10-25T08:00:00+00:00",
         "updated_at": "2026-10-28T10:00:00+00:00"},
        {"id": "current", "owner_id": "alice", "status": "active", "revision": 2,
         "start_date": "2026-10-28", "end_date": "2026-11-03", "created_at": "2026-10-28T10:00:00+00:00",
         "updated_at": "2026-10-28T10:00:00+00:00"},
        {"id": "too-new", "owner_id": "alice", "status": "superseded", "revision": 1,
         "start_date": "2026-10-28", "end_date": "2026-11-03", "created_at": "2026-10-28T13:00:00+00:00",
         "updated_at": "2026-10-28T13:00:00+00:00"},
        {"id": "outside", "owner_id": "alice", "status": "superseded", "revision": 1,
         "start_date": "2026-10-05", "end_date": "2026-10-11", "created_at": "2026-10-04T08:00:00+00:00",
         "updated_at": "2026-10-04T08:00:00+00:00"},
        {"id": "bob-plan", "owner_id": "bob", "status": "active", "revision": 1,
         "start_date": "2026-10-26", "end_date": "2026-11-01", "created_at": "2026-10-25T08:00:00+00:00",
         "updated_at": "2026-10-25T08:00:00+00:00"},
    ]
    sessions = [
        {"id": "prior-session-later", "training_plan_id": "prior", "owner_id": "alice", "date": "2026-10-27",
         "sequence": 0, "sport": "running", "session_type": "easy", "status": "planned", "optional": False,
         "completed_activity_id": None, "duration_min": 35, "duration_max": 45,
         "created_at": "2026-10-25T08:00:00+00:00", "updated_at": "2026-10-25T08:00:00+00:00"},
        {"id": "prior-session", "training_plan_id": "prior", "owner_id": "alice", "date": "2026-10-26",
         "sequence": 0, "sport": "running", "session_type": "easy", "status": "planned", "optional": False,
         "completed_activity_id": None, "duration_min": 40, "duration_max": 50,
         "created_at": "2026-10-25T08:00:00+00:00", "updated_at": "2026-10-25T08:00:00+00:00"},
        {"id": "current-session", "training_plan_id": "current", "owner_id": "alice", "date": "2026-10-28",
         "sequence": 0, "sport": "cycling", "session_type": "easy", "status": "planned", "optional": False,
         "completed_activity_id": None, "duration_min": 30, "duration_max": 45,
         "created_at": "2026-10-28T10:00:00+00:00", "updated_at": "2026-10-28T10:00:00+00:00"},
        {"id": "late-session", "training_plan_id": "current", "owner_id": "alice", "date": "2026-10-29",
         "sequence": 0, "sport": "strength", "session_type": "full_body", "status": "planned", "optional": False,
         "completed_activity_id": None, "created_at": "2026-10-28T13:00:00+00:00",
         "updated_at": "2026-10-28T13:00:00+00:00"},
        {"id": "bob-session", "training_plan_id": "bob-plan", "owner_id": "bob", "date": "2026-10-27",
         "sequence": 0, "sport": "running", "session_type": "easy", "status": "planned", "optional": False,
         "completed_activity_id": None, "created_at": "2026-10-25T08:00:00+00:00",
         "updated_at": "2026-10-25T08:00:00+00:00"},
    ]
    return jobs, plans, sessions


class FileWeekPlanTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        jobs, plans, sessions = fixture_rows()
        self.jobs_path = root / "ai_jobs.json"
        self.plans_path = root / "training_plan_state.json"
        self.jobs_path.write_text(json.dumps(jobs))
        self.plans_path.write_text(json.dumps({"plans": plans, "sessions": sessions}))
        self.enterContext(patch.object(store, "DATA_DIR", root))
        self.enterContext(patch.object(store, "AI_JOBS_FILE", self.jobs_path))
        self.enterContext(patch.object(store, "TRAINING_PLAN_STATE_FILE", self.plans_path))
        self.enterContext(patch.object(store, "DATABASE_URL", None))
        self.enterContext(patch.object(main, "settings", Settings(sync_secret="test-secret")))
        self.client = TestClient(main.app)

    def test_returns_only_owners_plans_known_at_job_time_without_writing(self):
        before = (self.jobs_path.read_bytes(), self.plans_path.read_bytes())
        response = self.client.get(
            "/ai/jobs/job-alice/week-plans?week_start=2026-10-26",
            headers={"X-Sync-Secret": "test-secret"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual((data["week_start"], data["week_end"], data["owner_id"]),
                         ("2026-10-26", "2026-11-01", "alice"))
        self.assertEqual([plan["id"] for plan in data["plans"]], ["prior", "current"])
        self.assertEqual(data["plans"][0]["status"], "superseded")
        self.assertEqual([session["id"] for session in data["plans"][0]["sessions"]],
                         ["prior-session", "prior-session-later"])
        self.assertEqual([session["id"] for session in data["plans"][1]["sessions"]], ["current-session"])
        self.assertEqual(data["plans"][1]["sessions"][0]["updated_at"], "2026-10-28T10:00:00+00:00")
        self.assertEqual(before, (self.jobs_path.read_bytes(), self.plans_path.read_bytes()))

    def test_rejects_missing_job_bad_week_owner_override_and_missing_secret(self):
        headers = {"X-Sync-Secret": "test-secret"}
        missing = self.client.get("/ai/jobs/missing/week-plans?week_start=2026-10-26", headers=headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "job_not_found")
        self.assertEqual(self.client.get("/ai/jobs/job-alice/week-plans?week_start=2026-10-27", headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/ai/jobs/job-alice/week-plans?week_start=bad", headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/ai/jobs/job-alice/week-plans?week_start=2026-10-26&owner_id=bob", headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/ai/jobs/job-alice/week-plans?week_start=2026-10-26").status_code, 401)

    def test_second_job_cannot_read_first_owners_plans(self):
        response = self.client.get(
            "/ai/jobs/job-bob/week-plans?week_start=2026-10-26",
            headers={"X-Sync-Secret": "test-secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([plan["id"] for plan in response.json()["plans"]], ["bob-plan"])

    def test_existing_job_without_plan_returns_verified_empty_result(self):
        response = self.client.get(
            "/ai/jobs/job-no-plan/week-plans?week_start=2026-10-26",
            headers={"X-Sync-Secret": "test-secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["owner_id"], "charlie")
        self.assertEqual(response.json()["plans"], [])


@unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class PostgresWeekPlanTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.types.json import Jsonb

        self.psycopg = psycopg
        self.schema = "week_" + uuid.uuid4().hex
        self.conn = psycopg.connect(os.environ["P03_TEST_DATABASE_URL"], autocommit=True)
        self.addCleanup(self.conn.close)
        self.conn.execute(sql.SQL("create schema {}").format(sql.Identifier(self.schema)))
        self.addCleanup(lambda: self.conn.execute(
            sql.SQL("drop schema {} cascade").format(sql.Identifier(self.schema))
        ))
        self.conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(self.schema)))
        store.ensure_schema(self.conn)
        schema_url = os.environ["P03_TEST_DATABASE_URL"] + "?options=-csearch_path%3D" + self.schema
        self.enterContext(patch.object(store, "DATABASE_URL", schema_url))
        self.enterContext(patch.object(main, "settings", Settings(sync_secret="test-secret")))
        self.client = TestClient(main.app)

        jobs, plans, sessions = fixture_rows()
        with psycopg.connect(schema_url) as conn:
            for job in jobs:
                conn.execute(
                    "insert into coach_ai_jobs (id, status, document, created_at) values (%s, %s, %s, %s)",
                    (job["id"], job["status"], Jsonb(job), job["created_at"]),
                )
            for plan in plans:
                conn.execute(
                    """insert into training_plans
                       (id, owner_id, status, start_date, end_date, document, created_at, updated_at, revision)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (plan["id"], plan["owner_id"], plan["status"], plan["start_date"], plan["end_date"],
                     Jsonb({}), plan["created_at"], plan["updated_at"], plan["revision"]),
                )
            for session in sessions:
                conn.execute(
                    """insert into planned_sessions
                       (id, training_plan_id, owner_id, session_date, sequence, sport, session_type,
                        status, optional, completed_activity_id, document, created_at, updated_at)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (session["id"], session["training_plan_id"], session["owner_id"], session["date"],
                     session["sequence"], session["sport"], session["session_type"], session["status"],
                     session["optional"], session["completed_activity_id"],
                     Jsonb({key: session[key] for key in ("duration_min", "duration_max") if key in session}),
                     session["created_at"], session["updated_at"]),
                )

    def test_postgres_endpoint_matches_file_bounds_and_keeps_rows(self):
        before = self.conn.execute("select count(*) from planned_sessions").fetchone()[0]
        response = self.client.get(
            "/ai/jobs/job-alice/week-plans?week_start=2026-10-26",
            headers={"X-Sync-Secret": "test-secret"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([plan["id"] for plan in data["plans"]], ["prior", "current"])
        self.assertEqual([session["id"] for session in data["plans"][1]["sessions"]], ["current-session"])
        self.assertEqual(data["plans"][1]["sessions"][0]["duration_min"], 30)
        self.assertEqual(before, self.conn.execute("select count(*) from planned_sessions").fetchone()[0])

    def test_postgres_missing_job_is_typed_404_and_other_owner_is_excluded(self):
        headers = {"X-Sync-Secret": "test-secret"}
        missing = self.client.get("/ai/jobs/missing/week-plans?week_start=2026-10-26", headers=headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "job_not_found")
        bob = self.client.get("/ai/jobs/job-bob/week-plans?week_start=2026-10-26", headers=headers)
        self.assertEqual(bob.status_code, 200)
        self.assertEqual([plan["id"] for plan in bob.json()["plans"]], ["bob-plan"])
        no_plan = self.client.get("/ai/jobs/job-no-plan/week-plans?week_start=2026-10-26", headers=headers)
        self.assertEqual(no_plan.status_code, 200)
        self.assertEqual(no_plan.json()["plans"], [])
