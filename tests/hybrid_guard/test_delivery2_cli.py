from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("hybrid_guard_delivery2", ROOT / ".opencode/scripts/hybrid_guard.py")
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class DeliveryTwoCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".opencode").mkdir()
        (self.root / ".opencode/hybrid-policy.json").write_text(
            json.dumps({"test_profiles": {"smoke": {}}}), encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / ".opencode/scripts/hybrid_guard.py"),
             "--project", str(self.root), *args],
            capture_output=True, text=True,
        )

    def active_manifest(self, task_id="task-1", *, test_passed=False):
        return {
            "version": guard.VERSION, "root": str(self.root), "task_id": task_id,
            "created_utc": utc_now(), "started_monotonic_hint": 1.0,
            "allowed": [], "preserved": {}, "before": guard.inventory(self.root),
            "test_profile": "smoke", "test_passed": test_passed,
            "test_result": {"returncode": 0} if test_passed else None,
            "tested_snapshot": {} if test_passed else None,
        }

    def put_session(self, status, *, task_id="task-1", child_pid=None, stale=False):
        state = guard.new_launch_session(self.root, task_id, status)
        state["supervisor_pid"] = os.getpid() if status in ("starting", "running") else None
        state["child_pid"] = child_pid
        if stale:
            expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
                seconds=guard.HEARTBEAT_TTL_SECONDS + 5
            )
            state["created_utc"] = expired.isoformat()
            state["heartbeat_utc"] = expired.isoformat()
            state["updated_utc"] = expired.isoformat()
        guard.write_launch_session(self.root, state)
        return state

    def test_recovery_without_active_task_can_be_reviewed_acknowledged_and_followed_by_begin(self):
        recovered = self.cli("recover-launch", "--reason", "Instalación inicial", "--confirm", "RECUPERAR")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        review = self.cli("launch-review")
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertIn("pending_review", review.stdout)
        invalid = self.cli("ack-launch", "--reason", "Revisado manualmente", "--confirm", "NO")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")
        empty_reason = self.cli("ack-launch", "--reason", "  ", "--confirm", "REVIEWED")
        self.assertNotEqual(empty_reason.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

        acknowledged = self.cli("ack-launch", "--reason", "Revisé la información disponible", "--confirm", "REVIEWED")
        self.assertEqual(acknowledged.returncode, 0, acknowledged.stderr)
        reviewed = guard.read_launch_session(self.root)
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertIsNone(reviewed["task_id"])
        self.assertIn("no garantiza", reviewed["review"]["scope_statement"].lower())
        self.assertEqual(len(guard.history_path(self.root).read_text().splitlines()), 1)

        begun = self.cli("begin", "--allow", "new.py", "--test", "smoke")
        self.assertEqual(begun.returncode, 0, begun.stderr)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "idle")
        self.assertEqual(guard.read_active(self.root)[1]["task_id"], guard.read_launch_session(self.root)["task_id"])
        self.assertEqual(len(guard.history_path(self.root).read_text().splitlines()), 1)

    def test_stale_running_session_is_persisted_pending_by_launch_review(self):
        self.put_session("running", stale=True, child_pid=99999999)
        result = self.cli("launch_review")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = guard.read_launch_session(self.root)
        self.assertEqual(state["status"], "pending_review")
        self.assertEqual(state["reason"], "supervision_stale")
        self.assertIn("heartbeat caducado", result.stdout.lower())
        self.assertIn("revisión pendiente registrada", result.stdout.lower())
        self.assertIn("descendientes", result.stdout.lower())
        self.assertNotIn("aislamiento garantizado", result.stdout.lower())

    def test_live_supervision_cannot_be_acknowledged(self):
        self.put_session("running", child_pid=os.getpid())
        review = self.cli("launch-review")
        self.assertEqual(review.returncode, 3)
        self.assertIn("PID", review.stdout)
        self.assertIn("descendientes", review.stdout.lower())
        before = guard.read_launch_session(self.root)
        ack = self.cli("ack-launch", "--reason", "He revisado los procesos", "--confirm", "REVIEWED")
        self.assertNotEqual(ack.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root), before)

    def test_unrepresentable_pid_is_reported_conservatively_not_as_absent(self):
        self.put_session("pending_review", child_pid=10 ** 100)
        review = self.cli("launch-review")
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertIn("unknown", review.stdout.lower())
        ack = self.cli("ack-launch", "--reason", "Revisé el estado del proceso", "--confirm", "REVIEWED")
        self.assertNotEqual(ack.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_stale_review_cannot_mutate_while_operation_lock_is_held(self):
        self.put_session("running", stale=True)
        with guard.operation_lock(self.root):
            result = self.cli("launch-review")
        self.assertEqual(result.returncode, 3)
        self.assertIn("no se pudo", result.stdout.lower())
        self.assertEqual(guard.read_launch_session(self.root)["status"], "running")

    def test_ack_requires_pending_record_and_operation_lock(self):
        absent = self.cli("ack-launch", "--reason", "Revisión confirmada manualmente", "--confirm", "REVIEWED")
        self.assertNotEqual(absent.returncode, 0)
        self.assertFalse(guard.session_path(self.root).exists())

        self.put_session("pending_review")
        args = ("ack-launch", "--reason", "Revisión confirmada manualmente", "--confirm", "REVIEWED")
        with guard.operation_lock(self.root):
            locked = self.cli(*args)
        self.assertNotEqual(locked.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_ack_rejects_review_record_from_a_different_active_task(self):
        self.put_session("pending_review", task_id="task-old")
        guard._atomic_write_bytes(guard.state_dir(self.root) / "active.json",
                                  json.dumps(self.active_manifest(task_id="task-new")).encode())
        result = self.cli("ack-launch", "--reason", "Revisión de la sesión anterior", "--confirm", "REVIEWED")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_sigkill_style_stale_supervisor_and_live_detached_process_never_claim_isolation(self):
        detached = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            self.put_session("running", stale=True, child_pid=detached.pid)
            review = self.cli("launch-review")
            self.assertEqual(review.returncode, 0, review.stderr)
            self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")
            self.assertIn("exists", review.stdout.lower())
            self.assertIn("descendientes desacoplados", review.stdout.lower())
            self.assertNotRegex(review.stdout.lower(), r"aislamiento garantizado|garantiza ausencia de descendientes")

            acknowledgment = self.cli(
                "ack-launch", "--reason", "He inspeccionado el proceso pendiente", "--confirm", "REVIEWED"
            )
            self.assertNotEqual(acknowledgment.returncode, 0)
            self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")
        finally:
            detached.terminate()
            detached.wait(timeout=5)

    def test_sigkill_supervisor_releases_operation_lock_and_stale_lease_moves_pending(self):
        script = r'''import datetime as dt, importlib.util, json, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("guard_sigkill", sys.argv[2])
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)
with guard.operation_lock(root):
    state = guard.new_launch_session(root, "task-killed", "running")
    expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=guard.HEARTBEAT_TTL_SECONDS + 5)
    state["created_utc"] = expired.isoformat()
    state["heartbeat_utc"] = expired.isoformat()
    state["updated_utc"] = expired.isoformat()
    state["supervisor_pid"] = __import__("os").getpid()
    guard.write_launch_session(root, state)
    print("SUPERVISOR_READY", flush=True)
    time.sleep(60)
'''
        supervisor = subprocess.Popen(
            [sys.executable, "-c", script, str(self.root), str(ROOT / ".opencode/scripts/hybrid_guard.py")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(supervisor.stdout.readline().strip(), "SUPERVISOR_READY")
            os.kill(supervisor.pid, 9)
            supervisor.wait(timeout=5)
            review = self.cli("launch-review")
            self.assertEqual(review.returncode, 0, review.stdout + review.stderr)
            self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")
            self.assertIn("heartbeat caducado", review.stdout.lower())
        finally:
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.wait(timeout=5)
            if supervisor.stdout:
                supervisor.stdout.close()
            if supervisor.stderr:
                supervisor.stderr.close()

    def test_abort_report_includes_review_and_limitation(self):
        guard._atomic_write_bytes(guard.state_dir(self.root) / "active.json",
                                  json.dumps(self.active_manifest()).encode())
        self.put_session("pending_review")
        ack = self.cli("ack-launch", "--reason", "Revisé los procesos observados", "--confirm", "REVIEWED")
        self.assertEqual(ack.returncode, 0, ack.stderr)
        aborted = self.cli("abort", "--reason", "Cancelar tras revisión humana", "--confirm", "ABORTAR")
        self.assertEqual(aborted.returncode, 0, aborted.stdout + aborted.stderr)
        reports = list((guard.state_dir(self.root) / "reports").glob("*-abort.json"))
        report = json.loads(reports[0].read_text())
        self.assertEqual(len(report["launch_reviews"]), 1)
        self.assertIn("descendientes desacoplados", report["process_review_limitations"].lower())

    def test_pending_review_blocks_sensitive_commands_and_another_launch(self):
        self.put_session("pending_review")
        guard._atomic_write_bytes(
            guard.state_dir(self.root) / "active.json",
            json.dumps(self.active_manifest()).encode(),
        )
        commands = (
            ("test",), ("finalize",), ("abort", "--reason", "Cancelar la tarea pendiente", "--confirm", "ABORTAR"),
            ("launch",),
        )
        for command in commands:
            with self.subTest(command=command):
                result = self.cli(*command)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_check_reports_missing_supervision_as_pending_and_corruption_as_invariant_failure(self):
        guard._atomic_write_bytes(guard.state_dir(self.root) / "active.json",
                                  json.dumps(self.active_manifest()).encode())
        missing = self.cli("check")
        self.assertEqual(missing.returncode, 3)
        guard.session_path(self.root).write_text("{bad json", encoding="utf-8")
        corrupt = self.cli("check")
        self.assertEqual(corrupt.returncode, 2)

    def test_acknowledgment_is_idempotent_and_finalize_report_contains_task_review(self):
        guard._atomic_write_bytes(guard.state_dir(self.root) / "active.json",
                                  json.dumps(self.active_manifest(test_passed=True)).encode())
        self.put_session("pending_review", child_pid=None)
        args = ("ack-launch", "--reason", "Inspeccioné la información disponible", "--confirm", "REVIEWED")
        first = self.cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        repeated = self.cli(*args)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(guard.history_path(self.root).read_text().splitlines()), 1)

        finalized = self.cli("finalize")
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        reports = list((guard.state_dir(self.root) / "reports").glob("*.json"))
        self.assertEqual(len(reports), 1)
        report = json.loads(reports[0].read_text())
        self.assertEqual(report["launch_reviews"][0]["session_id"], guard.read_launch_session(self.root)["session_id"])
        self.assertIn("descendientes", report["process_review_limitations"].lower())

    def test_finalize_reports_never_overwrite_when_closures_share_a_second(self):
        active_path = guard.state_dir(self.root) / "active.json"
        fixed = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        session = guard.new_launch_session(self.root, "task-1", "idle")
        session["created_utc"] = fixed.isoformat()
        session["updated_utc"] = fixed.isoformat()
        session["heartbeat_utc"] = fixed.isoformat()
        guard.write_launch_session(self.root, session)
        baseline = guard.inventory(self.root)
        first_manifest = self.active_manifest(test_passed=True)
        first_manifest.update(before=baseline, tested_snapshot=baseline, started_monotonic_hint=1.0)
        class FrozenDateTime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed if tz else fixed.replace(tzinfo=None)

        with patch.object(guard.dt, "datetime", FrozenDateTime):
            guard._atomic_write_bytes(active_path, json.dumps(first_manifest).encode())
            self.assertEqual(guard.finalize(self.root, active_path, first_manifest), 0)
            second_manifest = dict(first_manifest, task_id="task-2")
            guard._atomic_write_bytes(active_path, json.dumps(second_manifest).encode())
            self.assertEqual(guard.finalize(self.root, active_path, second_manifest), 0)

        reports = sorted((guard.state_dir(self.root) / "reports").glob("*.json"))
        self.assertEqual(len(reports), 2, [p.name for p in reports])
        self.assertEqual(len({p.read_text(encoding="utf-8") for p in reports}), 2)


if __name__ == "__main__":
    unittest.main()
