from __future__ import annotations

import datetime as dt
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hybrid_guard", ROOT / ".opencode/scripts/hybrid_guard.py"
)
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class LaunchStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, status="idle", session_id="session-1", task_id="task-1"):
        now = utc_now()
        return {
            "version": guard.SESSION_VERSION,
            "root": str(self.root),
            "task_id": task_id,
            "session_id": None if status == "idle" else session_id,
            "status": status,
            "created_utc": now,
            "updated_utc": now,
            "heartbeat_utc": now,
            "supervisor_pid": None,
            "child_pid": None,
        }

    def test_session_transitions_follow_lifecycle(self):
        state = self.record("idle")
        for status in ("starting", "running", "pending_review", "reviewed"):
            state = guard.transition_launch_session(state, status)
            self.assertEqual(state["status"], status)
            guard._validate_launch_session(self.root, state)
        self.assertTrue(state["session_id"])

    def test_session_rejects_skipped_backward_and_reopened_transitions(self):
        with self.assertRaises(guard.GuardError):
            guard.transition_launch_session(self.record("idle"), "running")
        with self.assertRaises(guard.GuardError):
            guard.transition_launch_session(self.record("running"), "starting")
        with self.assertRaises(guard.GuardError):
            guard.transition_launch_session(self.record("reviewed"), "starting")

    def test_state_write_is_atomic_and_private(self):
        state = self.record("idle")
        guard.write_launch_session(self.root, state)
        path = guard.session_path(self.root)
        self.assertEqual(guard.read_launch_session(self.root), state)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_failed_atomic_replace_keeps_previous_state(self):
        original = self.record("idle")
        guard.write_launch_session(self.root, original)
        replacement = dict(original, task_id="task-2")
        with mock.patch.object(guard.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                guard.write_launch_session(self.root, replacement)
        self.assertEqual(guard.read_launch_session(self.root), original)

    def test_state_rejects_wrong_root_unknown_version_and_bad_timestamp(self):
        state = self.record("idle")
        state["root"] = str(self.root / "other")
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

        state = self.record("idle")
        state["version"] = 999
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

        state = self.record("running")
        state["heartbeat_utc"] = "not-a-timestamp"
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

    def test_state_rejects_heartbeat_too_far_in_future(self):
        state = self.record("running")
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
        state["heartbeat_utc"] = future.isoformat()
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

    def test_state_requires_utc_timestamps_not_other_offsets(self):
        state = self.record("idle")
        state["created_utc"] = "2026-10-19T12:00:00+01:00"
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

    def test_state_rejects_inconsistent_timestamp_order(self):
        state = self.record("running")
        state["updated_utc"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=10)
        ).isoformat()
        with self.assertRaises(guard.GuardError):
            guard.write_launch_session(self.root, state)

    def test_archiving_same_session_is_idempotent(self):
        state = self.record("reviewed")
        state["review"] = {
            "reason": "Procesos conocidos revisados",
            "confirmed_utc": utc_now(),
        }
        guard.archive_launch_session(self.root, state)
        guard.archive_launch_session(self.root, state)
        history = guard.history_path(self.root).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0])["session_id"], "session-1")

    def test_archiving_rejects_conflicting_duplicate_session_id(self):
        first = self.record("reviewed")
        first["review"] = {"reason": "Revision original", "confirmed_utc": utc_now()}
        guard.archive_launch_session(self.root, first)
        conflicting = dict(first)
        conflicting["review"] = {"reason": "Revision distinta", "confirmed_utc": utc_now()}
        with self.assertRaises(guard.GuardError):
            guard.archive_launch_session(self.root, conflicting)

    def test_archiving_preserves_and_recovers_partial_history_tail(self):
        first = self.record("reviewed", "session-1")
        first["review"] = {"reason": "Primera revisión", "confirmed_utc": utc_now()}
        guard.archive_launch_session(self.root, first)
        history_path = guard.history_path(self.root)
        partial = b'{"session_id":"torn"'
        with history_path.open("ab") as output:
            output.write(partial)

        second = self.record("reviewed", "session-2")
        second["review"] = {"reason": "Segunda revisión", "confirmed_utc": utc_now()}
        guard.archive_launch_session(self.root, second)

        lines = history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["session_id"] for line in lines], ["session-1", "session-2"])
        evidence = list((guard.state_dir(self.root) / "evidence").glob("history-tail-*.bin"))
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0].read_bytes().endswith(partial))

    def test_archiving_recovers_valid_final_record_without_newline(self):
        first = self.record("reviewed", "session-1")
        first["review"] = {"reason": "Primera revisión", "confirmed_utc": utc_now()}
        guard.archive_launch_session(self.root, first)
        history_path = guard.history_path(self.root)
        history_path.write_bytes(history_path.read_bytes().rstrip(b"\n"))

        second = self.record("reviewed", "session-2")
        second["review"] = {"reason": "Segunda revisión", "confirmed_utc": utc_now()}
        guard.archive_launch_session(self.root, second)

        lines = history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["session_id"] for line in lines], ["session-1", "session-2"])


class LaunchLifecycleCliTests(unittest.TestCase):
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

    def record(self, status, session_id="old-session", task_id="old-task"):
        now = utc_now()
        return {
            "version": guard.SESSION_VERSION,
            "root": str(self.root),
            "task_id": task_id,
            "session_id": None if status == "idle" else session_id,
            "status": status,
            "created_utc": now,
            "updated_utc": now,
            "heartbeat_utc": now if status in ("starting", "running") else None,
            "supervisor_pid": None,
            "child_pid": None,
        }

    def test_recover_launch_without_active_task_records_missing_state(self):
        result = self.cli("recover-launch", "--reason", "Instalación inicial", "--confirm", "RECUPERAR")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        state = guard.read_launch_session(self.root)
        self.assertEqual(state["status"], "pending_review")
        self.assertIsNone(state["task_id"])
        self.assertEqual(state["recovery"]["evidence"]["kind"], "missing")
        self.assertFalse((guard.state_dir(self.root) / "active.json").exists())

    def test_flock_rejects_another_process_operation(self):
        with guard.operation_lock(self.root):
            result = self.cli("recover-launch", "--reason", "Instalación inicial", "--confirm", "RECUPERAR")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Otra operacion de Hybrid Guard", result.stderr)
        self.assertFalse(guard.session_path(self.root).exists())

    def test_begin_rejects_globbed_write_permissions(self):
        guard.write_launch_session(self.root, self.record("idle"))
        result = self.cli("begin", "--allow", "apps/*.py", "--test", "smoke")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("comodines", result.stderr)
        self.assertFalse((guard.state_dir(self.root) / "active.json").exists())

    def test_runtime_permission_overlay_denies_native_writes_and_asks_exact_guard_routes(self):
        agents_dir = self.root / '.opencode' / 'agents'
        agents_dir.mkdir(parents=True, exist_ok=True)
        for name in ('orchestrator', 'explorer', 'reviewer'):
            (agents_dir / f'{name}.md').write_text('---\nmode: subagent\n---\n')
        content = guard.build_opencode_config_content(
            self.root,
            {"allowed": ["src/one.py", "src/two.py"]},
            inherited='{"agents":{"local-coder":{"permissions":[{"action":"edit","resource":"*","effect":"allow"}]}}}',
        )
        config = json.loads(content)
        denials = [
            {"action": action, "resource": "*", "effect": "deny"}
            for action in ("edit", "write", "apply_patch", "shell", "execute", "computer", "mcp")
        ]
        self.assertEqual(config["permissions"][-7:], denials)
        for name in ('orchestrator', 'explorer', 'reviewer'):
            self.assertEqual(config["agents"][name]["permissions"][-7:], denials)
        rules = config["agents"]["local-coder"]["permissions"]
        self.assertEqual(rules[-6:], [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "*", "effect": "allow"},
            {"action": "glob", "resource": "*", "effect": "allow"},
            {"action": "grep", "resource": "*", "effect": "allow"},
            {"action": "hybrid_guard_write", "resource": "src/one.py", "effect": "ask"},
            {"action": "hybrid_guard_write", "resource": "src/two.py", "effect": "ask"},
        ])
        wildcard_deny = max(i for i, rule in enumerate(rules) if rule["action"] == "*")
        self.assertTrue(any(
            i < wildcard_deny and rule["action"] == "edit" and rule["effect"] == "allow"
            for i, rule in enumerate(rules)
        ))
        self.assertEqual(rules[0]["resource"], "*")

    def test_runtime_permission_overlay_rejects_invalid_inherited_config(self):
        with self.assertRaises(guard.GuardError):
            guard.build_opencode_config_content(
                self.root, {"allowed": ["src/one.py"]}, inherited="{invalid"
            )

    def test_runtime_permission_overlay_with_empty_scope_denies_all_writes(self):
        config = json.loads(
            guard.build_opencode_config_content(self.root, {"allowed": []})
        )
        rules = config["agents"]["local-coder"]["permissions"]
        self.assertFalse(any(rule["action"] == "hybrid_guard_write" for rule in rules))
        self.assertIn({"action": "*", "resource": "*", "effect": "deny"}, rules)

    def test_runtime_permission_overlay_rejects_noncanonical_and_external_paths(self):
        for path in ("src/*.py", "src/../secret.py", "../outside.py", "/tmp/outside.py"):
            with self.subTest(path=path), self.assertRaises(guard.GuardError):
                guard.build_opencode_config_content(self.root, {"allowed": [path]})

    def test_launch_passes_temporary_permissions_only_to_child_environment(self):
        manifest = {"task_id": "task-1", "allowed": ["src/one.py", "src/two.py"]}
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        inherited = '{"model":"stub/test"}'
        with mock.patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": inherited}):
            with guard.operation_lock(self.root) as lock_fd:
                real_popen = subprocess.Popen
                child = mock.Mock(pid=12345)
                captured = {}

                def fake_popen(command, *args, **kwargs):
                    if command[:1] == ["opencode"]:
                        captured["command"] = command
                        captured.update(kwargs)
                        return child
                    return real_popen(command, *args, **kwargs)

                with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                     mock.patch.object(guard.subprocess, "Popen", side_effect=fake_popen), \
                     mock.patch.object(guard, "_supervise_child", return_value=(0, False)):
                    self.assertEqual(guard.launch(self.root, guard.state_dir(self.root) / "active.json", manifest, 1, lock_fd), 0)
                    child_env = captured["env"]
                    self.assertEqual(os.environ["OPENCODE_CONFIG_CONTENT"], inherited)
                    self.assertEqual(captured["command"], ["opencode", "--standalone"])
        config = json.loads(child_env["OPENCODE_CONFIG_CONTENT"])
        rules = config["agents"]["local-coder"]["permissions"]
        self.assertEqual(rules[-2:], [
            {"action": "hybrid_guard_write", "resource": "src/one.py", "effect": "ask"},
            {"action": "hybrid_guard_write", "resource": "src/two.py", "effect": "ask"},
        ])
        self.assertFalse(any(rule["action"] == "edit" and rule["effect"] == "allow" for rule in rules))
        self.assertEqual(config["model"], "stub/test")

    def test_begin_directs_user_to_supervised_launch(self):
        self.assertEqual(
            self.cli("recover-launch", "--reason", "Inicialización de prueba", "--confirm", "RECUPERAR").returncode,
            0,
        )
        self.assertEqual(self.cli("launch-review").returncode, 0)
        self.assertEqual(
            self.cli("ack-launch", "--reason", "Revisé la ausencia", "--confirm", "REVIEWED").returncode,
            0,
        )
        result = self.cli("begin", "--allow", "new.py", "--test", "smoke")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hybrid_guard.py launch", result.stdout)


class CheckStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".opencode").mkdir()
        self.manifest = {
            "before": guard.inventory(self.root),
            "allowed": [],
            "preserved": {},
        }

    def tearDown(self):
        self.temp.cleanup()

    def record(self, status):
        now = utc_now()
        return {
            "version": guard.SESSION_VERSION,
            "root": str(self.root),
            "task_id": "task-1",
            "session_id": None if status == "idle" else "session-1",
            "status": status,
            "created_utc": now,
            "updated_utc": now,
            "heartbeat_utc": now if status in ("starting", "running") else None,
            "supervisor_pid": None,
            "child_pid": None,
        }

    def test_check_returns_zero_for_idle_or_reviewed_supervision(self):
        for status in ("idle", "reviewed"):
            with self.subTest(status=status):
                guard.write_launch_session(self.root, self.record(status))
                self.assertEqual(guard.check(self.root, self.manifest), 0)

    def test_check_returns_three_for_active_or_pending_supervision(self):
        for status in ("starting", "running", "pending_review"):
            with self.subTest(status=status):
                guard.write_launch_session(self.root, self.record(status))
                self.assertEqual(guard.check(self.root, self.manifest), 3)

    def test_check_returns_three_for_expired_heartbeat(self):
        record = self.record("running")
        expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=guard.HEARTBEAT_TTL_SECONDS + 1)
        record["heartbeat_utc"] = expired.isoformat()
        guard.write_launch_session(self.root, record)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = guard.check(self.root, self.manifest)
        self.assertEqual(result, 3)
        self.assertIn("heartbeat", output.getvalue())

    def test_check_returns_two_for_file_scope_error_even_with_pending_review(self):
        guard.write_launch_session(self.root, self.record("pending_review"))
        (self.root / "unauthorized.txt").write_text("changed", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = guard.check(self.root, self.manifest)
        self.assertEqual(result, 2)
        self.assertIn("REVISIÓN PENDIENTE", output.getvalue())
        self.assertIn("unauthorized.txt", output.getvalue())


class LaunchLifecycleContinuationTests(unittest.TestCase):
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

    def record(self, status, session_id="old-session", task_id="old-task"):
        now = utc_now()
        return {
            "version": guard.SESSION_VERSION,
            "root": str(self.root),
            "task_id": task_id,
            "session_id": None if status == "idle" else session_id,
            "status": status,
            "created_utc": now,
            "updated_utc": now,
            "heartbeat_utc": now if status in ("starting", "running") else None,
            "supervisor_pid": None,
            "child_pid": None,
        }

    def test_recover_launch_without_active_task_preserves_corrupt_bytes(self):
        path = guard.session_path(self.root)
        path.parent.mkdir(parents=True)
        corrupt = b'{"version":'
        path.write_bytes(corrupt)
        result = self.cli("recover-launch", "--reason", "Estado ilegible", "--confirm", "RECUPERAR")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        state = guard.read_launch_session(self.root)
        self.assertEqual(state["status"], "pending_review")
        self.assertIsNone(state["task_id"])
        self.assertEqual(state["recovery"]["evidence"]["kind"], "corrupt")
        self.assertEqual(
            state["recovery"]["evidence"]["sha256"],
            __import__("hashlib").sha256(corrupt).hexdigest(),
        )
        evidence = list((guard.state_dir(self.root) / "evidence").glob("launch-session-*.bin"))
        self.assertEqual([item.read_bytes() for item in evidence], [corrupt])

    def test_begin_rejects_missing_state_until_recovery(self):
        result = self.cli("begin", "--allow", "new.py", "--test", "smoke")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recover-launch", result.stderr)
        self.assertFalse((guard.state_dir(self.root) / "active.json").exists())

    def test_begin_archives_reviewed_session_before_new_task(self):
        previous = self.record("reviewed")
        previous["review"] = {"reason": "Revisé los procesos", "confirmed_utc": utc_now()}
        guard.write_launch_session(self.root, previous)
        result = self.cli("begin", "--allow", "new.py", "--test", "smoke")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        current = guard.read_launch_session(self.root)
        self.assertEqual(current["status"], "idle")
        self.assertNotEqual(current["task_id"], "old-task")
        entries = guard.history_path(self.root).read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(entry)["session_id"] for entry in entries], ["old-session"])
        self.assertEqual(guard.read_active(self.root)[1]["task_id"], current["task_id"])

    def test_begin_rejects_pending_session(self):
        guard.write_launch_session(self.root, self.record("pending_review"))
        result = self.cli("begin", "--allow", "new.py", "--test", "smoke")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pending_review", result.stderr)
        self.assertFalse((guard.state_dir(self.root) / "active.json").exists())


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.state = guard.new_launch_session(self.root, "task-1", "idle")
        self.state = guard.transition_launch_session(self.state, "starting", supervisor_pid=os.getpid())
        self.state = guard.transition_launch_session(self.state, "running", child_pid=os.getpid())
        guard.write_launch_session(self.root, self.state)

    def tearDown(self):
        self.temp.cleanup()

    def test_supervisor_renews_heartbeat_and_records_review_on_exit(self):
        original_heartbeat = self.state["heartbeat_utc"]
        child = mock.Mock()
        child.poll.side_effect = [None, None, 0]
        clock = mock.Mock(side_effect=[0.0, 0.0, 3.1, 3.2, 3.3])
        with mock.patch.object(guard.time, "monotonic", clock), mock.patch.object(guard.time, "sleep"):
            code, timed_out = guard._supervise_child(self.root, child, self.state, 1)
        self.assertEqual((code, timed_out), (0, False))
        persisted = guard.read_launch_session(self.root)
        self.assertEqual(persisted["status"], "running")
        self.assertEqual(child.poll.call_count, 3)
        self.assertNotEqual(persisted["heartbeat_utc"], original_heartbeat)

    def test_supervisor_stops_renewing_when_state_write_fails(self):
        child = mock.Mock()
        child.poll.return_value = None
        clock = mock.Mock(side_effect=[0.0, 0.0, 3.1])
        with mock.patch.object(guard.time, "monotonic", clock), \
                mock.patch.object(guard.time, "sleep"), \
                mock.patch.object(guard, "write_launch_session", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                guard._supervise_child(self.root, child, self.state, 1)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "running")

    def test_supervisor_enforces_timeout(self):
        child = mock.Mock()
        child.poll.return_value = None
        clock = mock.Mock(side_effect=[0.0, 0.0, 61.0])
        with mock.patch.object(guard.time, "monotonic", clock), \
                mock.patch.object(guard, "_stop_child") as stop:
            code, timed_out = guard._supervise_child(self.root, child, self.state, 1)
        self.assertEqual((code, timed_out), (124, True))
        stop.assert_called_once_with(child)

    def test_sigterm_interrupt_is_recorded_as_pending_review(self):
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        active = self.root / "active.json"
        manifest = {"task_id": "task-1", "before": guard.inventory(self.root),
                    "allowed": [], "preserved": {}}
        active.write_text(json.dumps(manifest), encoding="utf-8")
        child = mock.Mock()
        child.pid = 12345
        child.poll.return_value = 0
        real_popen = subprocess.Popen
        def fake_opencode(command, *args, **kwargs):
            return child if command[:1] == ["opencode"] else real_popen(command, *args, **kwargs)
        with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                mock.patch.object(guard.subprocess, "Popen", side_effect=fake_opencode), \
                mock.patch.object(guard.signal, "signal"), \
                mock.patch.object(guard, "_supervise_child", side_effect=guard.LaunchInterrupted("SIGTERM")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.launch(self.root, active, manifest, 1, 42), 143)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_ctrl_c_interrupt_is_recorded_as_pending_review(self):
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        active = self.root / "active.json"
        manifest = {"task_id": "task-1", "before": guard.inventory(self.root),
                    "allowed": [], "preserved": {}}
        active.write_text(json.dumps(manifest), encoding="utf-8")
        child = mock.Mock()
        child.pid = 12345
        child.poll.return_value = 0
        real_popen = subprocess.Popen
        def fake_opencode(command, *args, **kwargs):
            return child if command[:1] == ["opencode"] else real_popen(command, *args, **kwargs)
        with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                mock.patch.object(guard.subprocess, "Popen", side_effect=fake_opencode), \
                mock.patch.object(guard.signal, "signal"), \
                mock.patch.object(guard, "_supervise_child", side_effect=KeyboardInterrupt()), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.launch(self.root, active, manifest, 1, 42), 130)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_heartbeat_write_failure_stops_child_and_blocks_session(self):
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        active = self.root / "active.json"
        manifest = {"task_id": "task-1", "before": guard.inventory(self.root),
                    "allowed": [], "preserved": {}}
        active.write_text(json.dumps(manifest), encoding="utf-8")
        child = mock.Mock()
        child.pid = 12345
        child.poll.return_value = 0
        real_popen = subprocess.Popen
        def fake_opencode(command, *args, **kwargs):
            return child if command[:1] == ["opencode"] else real_popen(command, *args, **kwargs)
        with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                mock.patch.object(guard.subprocess, "Popen", side_effect=fake_opencode), \
                mock.patch.object(guard.signal, "signal"), \
                mock.patch.object(guard, "_supervise_child", side_effect=OSError("disk full")), \
                mock.patch.object(guard, "_stop_child") as stop, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guard.launch(self.root, active, manifest, 1, 42), 1)
        stop.assert_called_once_with(child)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_popen_failure_leaves_pending_review(self):
        active = self.root / "active.json"
        manifest = {"before": guard.inventory(self.root), "allowed": [], "preserved": {}}
        active.write_text(json.dumps(manifest), encoding="utf-8")
        real_popen = subprocess.Popen
        def fail_opencode(command, *args, **kwargs):
            if command[:1] == ["opencode"]:
                raise OSError("spawn failed")
            return real_popen(command, *args, **kwargs)
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                mock.patch.object(guard.subprocess, "Popen", side_effect=fail_opencode):
            with self.assertRaises(OSError):
                guard.launch(self.root, active, manifest, 1, 99)
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")

    def test_launch_keeps_flock_descriptor_inherited_and_pending_after_exit(self):
        active = self.root / "active.json"
        manifest = {"before": guard.inventory(self.root), "allowed": [], "preserved": {}}
        active.write_text(json.dumps(manifest), encoding="utf-8")
        child = mock.Mock()
        child.pid = 12345
        child.poll.return_value = 0
        launch_kwargs = {}
        real_popen = subprocess.Popen
        def fake_opencode(command, *args, **kwargs):
            if command[:1] == ["opencode"]:
                launch_kwargs.update(kwargs)
                return child
            return real_popen(command, *args, **kwargs)
        guard.write_launch_session(self.root, guard.new_launch_session(self.root, "task-1", "idle"))
        with mock.patch.object(guard.shutil, "which", return_value="/usr/bin/opencode"), \
                mock.patch.object(guard.subprocess, "Popen", side_effect=fake_opencode), \
                contextlib.redirect_stdout(io.StringIO()):
            guard.launch(self.root, active, manifest, 1, 42)
        self.assertEqual(launch_kwargs["start_new_session"], True)
        self.assertEqual(launch_kwargs["pass_fds"], (42,))
        self.assertEqual(guard.read_launch_session(self.root)["status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
