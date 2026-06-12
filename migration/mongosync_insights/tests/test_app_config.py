"""Tests for environment variable parsing and startup validation."""
import os
from unittest.mock import patch

import pytest

from lib import app_config
from lib.app_config import (
    build_progress_endpoint_url,
    normalize_progress_endpoint_url,
    parse_env_int,
    validate_config,
    validate_progress_endpoint_url,
)


class TestParseEnvInt:
    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MI_TEST_INT", None)
            assert parse_env_int("MI_TEST_INT", 42) == 42

    def test_valid_override(self):
        with patch.dict(os.environ, {"MI_TEST_INT": "99"}):
            assert parse_env_int("MI_TEST_INT", 42) == 99

    def test_empty_string_uses_default(self):
        with patch.dict(os.environ, {"MI_TEST_INT": ""}):
            assert parse_env_int("MI_TEST_INT", 42) == 42

    def test_non_integer_raises(self):
        with patch.dict(os.environ, {"MI_TEST_INT": "abc"}):
            with pytest.raises(ValueError, match="MI_TEST_INT"):
                parse_env_int("MI_TEST_INT", 42)

    def test_below_min_raises(self):
        with patch.dict(os.environ, {"MI_TEST_INT": "0"}):
            with pytest.raises(ValueError, match=">= 1"):
                parse_env_int("MI_TEST_INT", 42, min_value=1)

    def test_above_max_raises(self):
        with patch.dict(os.environ, {"MI_TEST_INT": "70000"}):
            with pytest.raises(ValueError, match="<= 65535"):
                parse_env_int("MI_TEST_INT", 42, max_value=65535)


class TestValidateConfig:
    @patch.object(app_config, "LOG_LEVEL", "VERBOSE")
    @patch("lib.app_config.os.access", return_value=True)
    @patch("lib.app_config.Path")
    def test_rejects_unknown_log_level(self, mock_path, mock_access):
        mock_path.return_value.parent.exists.return_value = True
        with pytest.raises(ValueError, match="LOG_LEVEL"):
            validate_config()

    @patch.object(app_config, "LOG_LEVEL", "INFO")
    @patch("lib.app_config.os.access", return_value=True)
    @patch("lib.app_config.Path")
    def test_accepts_valid_log_level(self, mock_path, mock_access):
        mock_path.return_value.parent.exists.return_value = True
        assert validate_config() is True

    @patch.object(app_config, "LOG_LEVEL", "critical")
    @patch("lib.app_config.os.access", return_value=True)
    @patch("lib.app_config.Path")
    def test_accepts_log_level_case_insensitive(self, mock_path, mock_access):
        mock_path.return_value.parent.exists.return_value = True
        assert validate_config() is True


class TestProgressEndpointUrl:
    def test_build_empty_host_returns_none(self):
        assert build_progress_endpoint_url("", "27182") is None
        assert build_progress_endpoint_url("  ", "27182") is None

    def test_build_default_port(self):
        assert (
            build_progress_endpoint_url("myhost", None)
            == "myhost:27182/api/v1/progress"
        )

    def test_build_custom_port(self):
        assert (
            build_progress_endpoint_url("myhost", "9999")
            == "myhost:9999/api/v1/progress"
        )

    def test_normalize_short_form(self):
        assert (
            normalize_progress_endpoint_url("localhost:27182")
            == "localhost:27182/api/v1/progress"
        )

    def test_normalize_full_form_with_scheme(self):
        assert (
            normalize_progress_endpoint_url("http://host:27182/api/v1/progress")
            == "host:27182/api/v1/progress"
        )

    def test_normalize_already_canonical(self):
        url = "host:27182/api/v1/progress"
        assert normalize_progress_endpoint_url(url) == url

    def test_validate_accepts_normalized_output(self):
        url = normalize_progress_endpoint_url("localhost:27182")
        assert validate_progress_endpoint_url(url) is True
