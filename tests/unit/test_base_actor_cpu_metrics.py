"""
Unit tests for the new CPU gauges (cpus_allocated / cpus_limit / cpus_used)
recorded by BaseActor._collect_sandbox_metrics().

We bypass the OTLP setup by injecting MagicMock gauges into actor._gauges,
mirroring the pattern used in tests/unit/test_base_actor.py.
"""

from unittest.mock import MagicMock

import pytest

from rock.sandbox.base_actor import BaseActor


class ConcreteBaseActor(BaseActor):
    """Minimal concrete subclass — get_sandbox_statistics returns a fixed dict."""

    _stats_payload: dict | None = None

    async def get_sandbox_statistics(self):
        return self._stats_payload


def _make_actor(cpus, limit_cpus, cpu_percent=50.0):
    """Build a ConcreteBaseActor with a mocked config + all gauges as MagicMocks."""
    config = MagicMock()
    config.container_name = "test-container"
    config.auto_clear_time = None
    config.cpus = cpus
    config.limit_cpus = limit_cpus

    deployment = MagicMock()
    deployment.__class__ = object  # make isinstance(deployment, DockerDeployment) False

    actor = ConcreteBaseActor(config, deployment)
    actor.host = "127.0.0.1"
    actor._stats_payload = {"cpu": cpu_percent, "mem": 20.0, "disk": 30.0, "net": 40.0}
    for key in ("cpu", "mem", "disk", "net", "rt", "cpus_allocated", "cpus_limit", "cpus_used"):
        actor._gauges[key] = MagicMock()
    return actor


class TestCpuMetricsRecording:
    async def test_no_overcommit_reports_limit_equal_to_cpus(self):
        """limit_cpus=None should be reported as cpus_limit == cpus_allocated."""
        actor = _make_actor(cpus=2, limit_cpus=None, cpu_percent=50.0)

        await actor._collect_sandbox_metrics("test-container")

        assert actor._gauges["cpus_allocated"].set.called
        assert actor._gauges["cpus_allocated"].set.call_args[0][0] == 2.0
        assert actor._gauges["cpus_limit"].set.call_args[0][0] == 2.0
        # cpu_percent=50, effective_limit=2 -> cpus_used = 0.5 * 2 = 1.0
        assert actor._gauges["cpus_used"].set.call_args[0][0] == pytest.approx(1.0)

    async def test_overcommit_reports_limit_above_cpus(self):
        """limit_cpus=6 with cpus=2 should report cpus_limit=6 and cpus_used scaled by 6."""
        actor = _make_actor(cpus=2, limit_cpus=6, cpu_percent=50.0)

        await actor._collect_sandbox_metrics("test-container")

        assert actor._gauges["cpus_allocated"].set.call_args[0][0] == 2.0
        assert actor._gauges["cpus_limit"].set.call_args[0][0] == 6.0
        # cpu_percent=50, effective_limit=6 -> cpus_used = 0.5 * 6 = 3.0
        assert actor._gauges["cpus_used"].set.call_args[0][0] == pytest.approx(3.0)

    async def test_cpus_zero_yields_zero_used(self):
        """Defensive: cpus=0 (degenerate) should report cpus_used=0 without ZeroDivisionError."""
        actor = _make_actor(cpus=0, limit_cpus=None, cpu_percent=50.0)

        await actor._collect_sandbox_metrics("test-container")

        assert actor._gauges["cpus_allocated"].set.call_args[0][0] == 0.0
        assert actor._gauges["cpus_limit"].set.call_args[0][0] == 0.0
        assert actor._gauges["cpus_used"].set.call_args[0][0] == 0.0
