"""Tests for MongoDB connection and internal DB name cache clearing."""
from unittest.mock import patch

from lib import app_config


class TestClearConnectionCache:
    def setup_method(self):
        app_config.get_mongo_client.cache_clear()
        with app_config._resolved_internal_db_lock:
            app_config._resolved_internal_db_cache.clear()

    def test_clear_connection_cache_clears_internal_db_and_client_cache(self):
        with app_config._resolved_internal_db_lock:
            app_config._resolved_internal_db_cache["mongodb://localhost:27017"] = (
                app_config.INTERNAL_DB_NAME_NEW
            )

        with patch.object(app_config.get_mongo_client, "cache_clear") as mock_cache_clear:
            app_config.clear_connection_cache()
            mock_cache_clear.assert_called_once()

        assert app_config._resolved_internal_db_cache == {}

    @patch("lib.app_config.get_mongo_client")
    def test_validate_connection_failure_clears_both_caches(self, mock_get_mongo_client):
        mock_get_mongo_client.cache_clear = app_config.get_mongo_client.cache_clear
        mock_get_mongo_client.side_effect = RuntimeError("connection failed")
        with app_config._resolved_internal_db_lock:
            app_config._resolved_internal_db_cache["mongodb://bad"] = (
                app_config.INTERNAL_DB_NAME
            )

        try:
            app_config.validate_connection("mongodb://bad")
        except RuntimeError:
            pass

        mock_get_mongo_client.cache_clear.assert_called_once()
        assert app_config._resolved_internal_db_cache == {}
