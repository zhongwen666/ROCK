import pytest
from pydantic import ValidationError

from rock.sdk.sandbox.config import SandboxConfig


class TestSandboxConfigAutoDeleteSeconds:
    def test_default_is_none(self):
        config = SandboxConfig()
        assert config.auto_delete_seconds is None

    def test_none_is_valid(self):
        config = SandboxConfig(auto_delete_seconds=None)
        assert config.auto_delete_seconds is None

    def test_zero_is_valid(self):
        config = SandboxConfig(auto_delete_seconds=0)
        assert config.auto_delete_seconds == 0

    def test_positive_value_is_valid(self):
        config = SandboxConfig(auto_delete_seconds=300)
        assert config.auto_delete_seconds == 300

    def test_negative_value_raises_error(self):
        with pytest.raises(ValidationError, match="auto_delete_seconds must be >= 0"):
            SandboxConfig(auto_delete_seconds=-1)

    def test_large_negative_value_raises_error(self):
        with pytest.raises(ValidationError, match="auto_delete_seconds must be >= 0"):
            SandboxConfig(auto_delete_seconds=-100)
