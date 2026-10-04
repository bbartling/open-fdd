"""R03/R06 — positive own-object controls and budget deadline integrity."""
from __future__ import annotations

import math
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/security"))

from openfdd_security.config import ConfigError  # noqa: E402
from openfdd_security.runner import _validate_budget_finite  # noqa: E402
from openfdd_security.suites import (  # noqa: E402
    _nonempty_own_control,
    _structured_deny,
)
from openfdd_security.transport import Budget, TransportError  # noqa: E402


class PositiveControlTests(unittest.TestCase):
    def test_error_object_is_not_own_success(self):
        self.assertFalse(
            _nonempty_own_control(b'{"ok":false,"error":"missing"}', "CANARY")
        )
        self.assertFalse(_nonempty_own_control(b'{"ok":false,"error":"missing"}'))

    def test_empty_list_is_not_own_success(self):
        self.assertFalse(_nonempty_own_control(b"[]", "CANARY"))
        self.assertFalse(_nonempty_own_control(b"[]"))

    def test_canary_required_when_supplied(self):
        without = b'{"equipment":[{"id":"AHU_1"}],"ok":true}'
        with_canary = b'{"equipment":[{"id":"AHU_1","tag":"CANARY-A"}],"ok":true}'
        self.assertFalse(_nonempty_own_control(without, "CANARY-A"))
        self.assertTrue(_nonempty_own_control(with_canary, "CANARY-A"))

    def test_populated_list_without_canary_ok(self):
        self.assertTrue(_nonempty_own_control(b'{"equipment":[{"id":"AHU_1"}]}'))

    def test_soft_ok_empty_equipment_is_not_own_success(self):
        body = b'{"ok":true,"count":0,"equipment":[]}'
        self.assertFalse(_nonempty_own_control(body))
        self.assertFalse(_nonempty_own_control(body, "CANARY_A_SYNTH"))

    def test_structured_deny_requires_envelope(self):
        self.assertFalse(_structured_deny(404, b"not found", foreign_canary="B"))
        self.assertFalse(_structured_deny(404, b"<html>nope</html>", foreign_canary="B"))
        self.assertTrue(_structured_deny(403, b'{"ok":false}', foreign_canary="B"))
        self.assertFalse(
            _structured_deny(403, b'{"ok":false,"x":"B"}', foreign_canary="B")
        )


class BudgetDeadlineTests(unittest.TestCase):
    def test_rate_sleep_cannot_pass_deadline(self):
        bud = Budget(
            max_requests=50,
            timeout_s=1.0,
            deadline_s=1.0,
            rate_rps=1.0,
            cleanup_reserved=0,
        )
        # Nearly exhausted deadline + rate wait that would previously overshoot.
        with self.assertRaises(TransportError) as ctx:
            bud.started_at = time.monotonic() - 0.9
            bud.deadline_s = 1.0
            bud._last_request_at = time.monotonic() - 0.01
            bud.request_count = 0
            bud.consume()
        self.assertIn("deadline", str(ctx.exception).lower())

    def test_validate_rejects_nan_inf_negative(self):
        with self.assertRaises(ConfigError):
            _validate_budget_finite(
                {"max_requests": 10, "deadline_s": math.nan, "timeout_s": 1.0},
                profile="isolated_full",
            )
        with self.assertRaises(ConfigError):
            _validate_budget_finite(
                {"max_requests": 10, "deadline_s": math.inf, "timeout_s": 1.0},
                profile="isolated_full",
            )
        with self.assertRaises(ConfigError):
            _validate_budget_finite(
                {"max_requests": -1, "deadline_s": 10.0, "timeout_s": 1.0},
                profile="isolated_full",
            )

    def test_validate_rejects_over_ceiling(self):
        with self.assertRaises(ConfigError):
            _validate_budget_finite(
                {"max_requests": 999, "deadline_s": 300.0, "timeout_s": 10.0},
                profile="isolated_full",
            )


if __name__ == "__main__":
    unittest.main()
