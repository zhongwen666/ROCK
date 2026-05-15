"""
Unit tests for `_apply_cpu_overcommit_default` in admin gateway.

The function reads the Nacos key `cpu_overcommit_headroom` and, when the SDK
did NOT pass `limit_cpus`, derives `limit_cpus = min(2*cpus, cpus+headroom)`.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from rock.deployments.config import DockerDeploymentConfig


def _patch_manager(nacos_value, nacos_present=True):
    """Build a mock sandbox_manager with nacos.get_config_value -> nacos_value.

    When nacos_present is False, nacos_provider is None.
    """
    mgr = MagicMock()
    if not nacos_present:
        mgr.rock_config.nacos_provider = None
    else:
        nacos = MagicMock()
        nacos.get_config_value = AsyncMock(return_value=nacos_value)
        mgr.rock_config.nacos_provider = nacos
    # create=True is required because `sandbox_manager` is a bare PEP-526 type
    # annotation in sandbox_api.py — the attribute does not exist in the module
    # dict until set_sandbox_manager() is called by the admin bootstrap.
    return patch("rock.admin.entrypoints.sandbox_api.sandbox_manager", mgr, create=True)


class TestApplyCpuOvercommitDefault:
    async def test_sdk_explicit_value_wins(self):
        """SDK-supplied limit_cpus is preserved even when headroom is configured."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=8)
        with _patch_manager("4"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus == 8

    async def test_nacos_provider_absent_keeps_none(self):
        """When the rock instance has no Nacos provider, limit_cpus stays None."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
        with _patch_manager(None, nacos_present=False):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus is None

    async def test_headroom_zero_keeps_none(self):
        """headroom == 0 means no overcommit; limit_cpus stays None."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
        with _patch_manager("0"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus is None

    async def test_headroom_additive_arm_wins_for_large_cpus(self):
        """For cpus=8, headroom=4: min(16, 12) = 12 (cpus+headroom dominates)."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=8, limit_cpus=None)
        with _patch_manager("4"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus == 12

    async def test_headroom_2x_cap_wins_for_small_cpus(self):
        """For cpus=2, headroom=10: min(4, 12) = 4 (2*cpus dominates)."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
        with _patch_manager("10"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus == 4

    async def test_headroom_unparseable_keeps_none(self):
        """Garbage Nacos value falls back to headroom=0; limit_cpus stays None."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
        with _patch_manager("abc"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus is None

    async def test_headroom_negative_keeps_none(self):
        """Negative headroom is clamped to 0; limit_cpus stays None."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
        with _patch_manager("-3"):
            await _apply_cpu_overcommit_default(config)
        assert config.limit_cpus is None

    async def test_headroom_non_finite_keeps_none(self):
        """NaN / inf headroom must not propagate to docker run; limit_cpus stays None."""
        from rock.admin.entrypoints.sandbox_api import _apply_cpu_overcommit_default

        for raw in ("nan", "inf", "-inf"):
            config = DockerDeploymentConfig(cpus=2, limit_cpus=None)
            with _patch_manager(raw):
                await _apply_cpu_overcommit_default(config)
            assert config.limit_cpus is None, f"limit_cpus should stay None for raw={raw!r}"
