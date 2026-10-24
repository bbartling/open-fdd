"""Offline byte-integrity regressions for the ZAP wrapper's redaction boundary."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/qualification/zap/artifact_integrity.py"
WRAPPER = ROOT / "scripts/qualification/run_isolated_zap_af.sh"
SPEC = importlib.util.spec_from_file_location("zap_artifact_integrity", HELPER)
guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guard)


class ZapArtifactIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.art = self.directory / "artifacts"
        self.priv = self.directory / "private"
        self.art.mkdir()
        self.priv.mkdir(mode=0o700)
        self.state = self.priv / "snapshot.json"
        self.report = self.art / "artifact_integrity.json"
        self.verdicts = [self.art / "verdict.json", self.art / "negative_control_verdict.json"]
        self.raw = self.art / "raw-report.json"
        self.raw.write_bytes(b'{"fixture":"unaltered scanner bytes"}\n')
        for verdict in self.verdicts:
            verdict.write_text('{"suite":"fixture","status":"PASS"}\n', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_guard(self, action, **changes):
        kwargs = dict(action=action, root=self.art, state=self.state,
                      report=self.report, verdicts=self.verdicts)
        kwargs.update(changes)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return guard.run_guard(**kwargs)

    def assert_invalidated(self):
        for path in self.verdicts:
            self.assertEqual(json.loads(path.read_text())["status"], "ERROR")
        self.assertEqual(json.loads(self.report.read_text())["status"], "ERROR")

    def test_unchanged_bytes_pass_without_rewriting_original_verdicts(self):
        before = {path: path.read_bytes() for path in [self.raw, *self.verdicts]}
        self.assertEqual(self.run_guard("snapshot"), 0)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.run_guard("verify"), 0)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        result = json.loads(self.report.read_text())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["scope"], "wrapper_cleanup_byte_integrity_only")
        self.assertEqual(result["counts"], dict(before_files=3, after_files=3, added=0, deleted=0, changed=0))

    def test_changed_deleted_and_added_artifacts_invalidate_both_pass_claims(self):
        for operation in ("rewrite", "delete", "add"):
            with self.subTest(operation=operation):
                self.tearDown()
                self.setUp()
                self.assertEqual(self.run_guard("snapshot"), 0)
                if operation == "rewrite":
                    self.raw.write_bytes(b'{"fixture":"[REDACTED]"}\n')
                elif operation == "delete":
                    self.raw.unlink()
                else:
                    (self.art / "late-file.txt").write_text("unexpected artifact")
                self.assertEqual(self.run_guard("verify"), 1)
                self.assert_invalidated()
                counts = json.loads(self.report.read_text())["counts"]
                key = {"rewrite": "changed", "delete": "deleted", "add": "added"}[operation]
                self.assertEqual(counts[key], 1)

    def test_unreadable_evidence_fails_for_root_and_nonroot_test_users(self):
        self.assertEqual(self.run_guard("snapshot"), 0)
        original = Path.open

        def unreadable(path, *args, **kwargs):
            if path == self.raw:
                raise PermissionError("fixture-secret-do-not-print")
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", unreadable):
            self.assertEqual(self.run_guard("verify"), 1)
        self.assert_invalidated()
        self.assertNotIn("fixture-secret", self.report.read_text())

    def test_large_artifact_is_hashed_with_bounded_reads(self):
        payload = b"large fixture bytes" * 150000
        sizes = []

        class BoundedReader(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > 1024 * 1024:
                    raise AssertionError("unbounded artifact read")
                sizes.append(size)
                return super().read(size)

        original = Path.open

        def open_fixture(path, *args, **kwargs):
            if path == self.raw:
                return BoundedReader(payload)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", open_fixture):
            self.assertEqual(self.run_guard("snapshot"), 0)
        state = json.loads(self.state.read_text())
        key = hashlib.sha256(os.fsencode(self.raw.relative_to(self.art))).hexdigest()
        self.assertEqual(state["files"][key], dict(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)))
        self.assertGreater(len(sizes), 2)

    def test_snapshot_failure_also_invalidates_existing_passes(self):
        with mock.patch.object(guard, "snapshot_tree", side_effect=OSError("secret-path")):
            self.assertEqual(self.run_guard("snapshot"), 1)
        self.assert_invalidated()

    def test_redaction_command_failure_is_error_even_when_bytes_match(self):
        self.assertEqual(self.run_guard("snapshot"), 0)
        self.assertEqual(self.run_guard("verify", redaction_failed=True), 1)
        self.assert_invalidated()

    def test_symlink_artifact_is_not_followed(self):
        self.assertEqual(self.run_guard("snapshot"), 0)
        external = self.priv / "private-secret"
        external.write_text("CANARY_PRIVATE_CONTENT")
        (self.art / "redirect.txt").symlink_to(external)
        self.assertEqual(self.run_guard("verify"), 1)
        self.assert_invalidated()
        self.assertEqual(external.read_text(), "CANARY_PRIVATE_CONTENT")
        self.assertNotIn("CANARY", self.report.read_text())

    def test_snapshot_contains_digests_not_names_or_contents(self):
        canary = "CANARY_PRIVATE_FILENAME_AND_CONTENT"
        (self.art / canary).write_text(canary)
        self.assertEqual(self.run_guard("snapshot"), 0)
        self.assertNotIn(canary, self.state.read_text())
        self.assertNotIn(str(self.art), self.state.read_text())

    def test_snapshot_inside_artifacts_or_corrupt_state_fails_closed(self):
        self.assertEqual(self.run_guard("snapshot", state=self.art / "snapshot.json"), 1)
        self.assert_invalidated()
        self.tearDown()
        self.setUp()
        self.assertEqual(self.run_guard("snapshot"), 0)
        self.state.write_text('{"schema":"wrong"}')
        self.assertEqual(self.run_guard("verify"), 1)
        self.assert_invalidated()

    def test_root_binding_refuses_snapshot_from_another_artifact_tree(self):
        self.assertEqual(self.run_guard("snapshot"), 0)
        data = json.loads(self.state.read_text())
        data["root_digest"] = "0" * 64
        self.state.write_text(json.dumps(data))
        self.assertEqual(self.run_guard("verify"), 1)
        self.assert_invalidated()

    def test_unmodifiable_verdict_is_removed_instead_of_retaining_pass(self):
        self.assertEqual(self.run_guard("snapshot"), 0)
        self.raw.unlink()
        original = guard._atomic_json

        def no_verdict_replacement(path, payload, **kwargs):
            if path == self.verdicts[0]:
                raise PermissionError("fixture")
            return original(path, payload, **kwargs)

        with mock.patch.object(guard, "_atomic_json", side_effect=no_verdict_replacement):
            self.assertEqual(self.run_guard("verify"), 1)
        self.assertFalse(self.verdicts[0].exists())
        self.assertEqual(json.loads(self.verdicts[1].read_text())["status"], "ERROR")

    def test_cli_returns_nonzero_and_emits_no_sensitive_details(self):
        shared = ["--root", str(self.art), "--state", str(self.state), "--report", str(self.report)]
        for path in self.verdicts:
            shared += ["--verdict", str(path)]
        baseline = subprocess.run([sys.executable, "-B", str(HELPER), "snapshot", *shared], capture_output=True, text=True)
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.raw.write_text("CANARY_SECRET_DO_NOT_PRINT")
        result = subprocess.run([sys.executable, "-B", str(HELPER), "verify", *shared], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("PASS", result.stdout + result.stderr)
        self.assertNotIn("CANARY", result.stdout + result.stderr + self.report.read_text())
        self.assert_invalidated()

    def test_wrapper_orders_snapshot_cleanup_verify_before_any_final_pass(self):
        text = WRAPPER.read_text()
        snapshot = text.index('"${INTEGRITY[@]}" snapshot')
        cleanup = text.index('chmod -R u+rwX,g+rwX,o-rwx "$WRK"', snapshot)
        redaction = text.index('portal_redact_file "$f"', cleanup)
        verify = text.index('"${INTEGRITY[@]}" verify', redaction)
        summary = text.index('evaluator status=', verify)
        final_pass = text.index('echo "PASS: isolated ZAP AF', summary)
        self.assertLess(snapshot, cleanup)
        self.assertLess(cleanup, redaction)
        self.assertLess(redaction, verify)
        self.assertLess(verify, summary)
        self.assertLess(summary, final_pass)
        self.assertIn('>"$PORTAL_PRIV/zap-evaluator.stdout" 2>"$PORTAL_PRIV/zap-evaluator.stderr"', text[:snapshot])
        self.assertIn('>"$PORTAL_PRIV/zap-negative.stdout" 2>"$PORTAL_PRIV/zap-negative.stderr"', text[:snapshot])
        self.assertIn('--state "$PORTAL_PRIV/zap-artifacts-before.json"', text)
        self.assertIn('--redaction-failed', text)


if __name__ == "__main__":
    unittest.main()
