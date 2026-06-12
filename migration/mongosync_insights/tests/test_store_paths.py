"""Tests for store path validation and path traversal hardening."""
import json
import os
import uuid
from unittest.mock import patch

import pytest

from lib import snapshot_store
from lib.log_store_registry import LogStoreRegistry
from lib.store_paths import (
    is_valid_store_id,
    safe_path_under,
    validate_store_id,
)


VALID_UUID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'


class TestValidateStoreId:
    def test_accepts_valid_uuid(self):
        assert validate_store_id(VALID_UUID) == VALID_UUID
        assert validate_store_id(str(uuid.uuid4()))

    @pytest.mark.parametrize('value', [
        '',
        '../etc/passwd',
        'foo/../../../bar',
        'not-a-uuid',
        'a/b',
        'a%2Fb',
        '12345678-1234-1234-1234-12345678901',  # too long
        '12345678-1234-1234-1234-123456789',    # too short
    ])
    def test_rejects_invalid_ids(self, value):
        with pytest.raises(ValueError, match='Invalid store id'):
            validate_store_id(value)
        assert not is_valid_store_id(value)


class TestSafePathUnder:
    def test_stays_under_base(self, tmp_path):
        base = tmp_path / 'store'
        base.mkdir()
        result = safe_path_under(str(base), 'mi_snapshot_test.json')
        assert result.startswith(str(base.resolve()))

    def test_rejects_escape(self, tmp_path):
        base = tmp_path / 'store'
        base.mkdir()
        outside = tmp_path / 'outside.txt'
        outside.write_text('secret')
        with pytest.raises(ValueError, match='escapes store directory'):
            safe_path_under(str(base), '..', 'outside.txt')


class TestLogstorePath:
    def test_valid_uuid_under_base(self, tmp_path, monkeypatch):
        monkeypatch.setattr(snapshot_store, 'LOG_STORE_DIR', str(tmp_path))
        path = snapshot_store.logstore_path(VALID_UUID)
        assert path.startswith(str(tmp_path.resolve()))
        assert path.endswith(f'mi_logstore_{VALID_UUID}.db')

    def test_traversal_payload_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(snapshot_store, 'LOG_STORE_DIR', str(tmp_path))
        with pytest.raises(ValueError):
            snapshot_store.logstore_path('../../../etc/passwd')


class TestSnapshotStorePoisonedJson:
    def test_load_snapshot_skips_invalid_log_store_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr(snapshot_store, 'LOG_STORE_DIR', str(tmp_path))
        snapshot_id = str(uuid.uuid4())
        path = snapshot_store._snapshot_path(snapshot_id)
        payload = {
            'snapshot_id': snapshot_id,
            'log_store_id': 'foo/../../../etc/passwd',
            'template_data': {'foo': 'bar'},
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)

        outside = tmp_path.parent / 'victim.txt'
        outside.write_text('keep me')

        data = snapshot_store.load_snapshot(snapshot_id)
        assert data is not None
        assert outside.read_text() == 'keep me'

    def test_delete_snapshot_does_not_remove_outside_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(snapshot_store, 'LOG_STORE_DIR', str(tmp_path))
        snapshot_id = str(uuid.uuid4())
        path = snapshot_store._snapshot_path(snapshot_id)
        payload = {
            'snapshot_id': snapshot_id,
            'log_store_id': 'foo/../../../etc/passwd',
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)

        victim = tmp_path.parent / 'victim.txt'
        victim.write_text('keep me')

        deleted, store_id = snapshot_store.delete_snapshot(snapshot_id)
        assert deleted is True
        assert store_id == ''
        assert victim.read_text() == 'keep me'
        assert not os.path.exists(path)


class TestLogStoreRegistry:
    def test_register_rejects_path_outside_store(self, tmp_path, monkeypatch):
        store_dir = tmp_path / 'store'
        store_dir.mkdir()
        monkeypatch.setattr(
            'lib.log_store_registry.LOG_STORE_DIR', str(store_dir)
        )
        registry = LogStoreRegistry()
        store_id = str(uuid.uuid4())
        outside = tmp_path / 'outside.db'
        outside.write_text('x')
        with pytest.raises(ValueError, match='LOG_STORE_DIR'):
            registry.register(store_id, str(outside))

    def test_register_accepts_path_inside_store(self, tmp_path, monkeypatch):
        store_dir = tmp_path / 'store'
        store_dir.mkdir()
        monkeypatch.setattr(
            'lib.log_store_registry.LOG_STORE_DIR', str(store_dir)
        )
        registry = LogStoreRegistry()
        store_id = str(uuid.uuid4())
        db_path = store_dir / f'mi_logstore_{store_id}.db'
        db_path.write_text('x')
        registry.register(store_id, str(db_path))
        assert registry.count() == 1


class TestLogsRoutes:
    @pytest.fixture
    def app_client(self, tmp_path, monkeypatch):
        log_dir = tmp_path / 'logs'
        log_dir.mkdir()
        monkeypatch.setenv('MI_LOG_FILE', str(log_dir / 'insights.log'))
        monkeypatch.setattr(snapshot_store, 'LOG_STORE_DIR', str(tmp_path / 'store'))
        (tmp_path / 'store').mkdir()

        with patch('lib.app_config.validate_config', return_value=True):
            with patch('lib.app_config.setup_logging') as mock_log:
                mock_log.return_value = __import__('logging').getLogger('test')
                from mongosync_insights import create_app
                app = create_app()
                app.config['TESTING'] = True
                with app.test_client() as client:
                    yield client

    def test_load_snapshot_invalid_id(self, app_client):
        r = app_client.get('/logs/load_snapshot/not-a-uuid')
        assert r.status_code == 200
        assert b'Snapshot Not Found' in r.data

    def test_delete_snapshot_invalid_id(self, app_client):
        r = app_client.delete('/logs/delete_snapshot/not-a-uuid')
        assert r.status_code == 404
        assert r.get_json()['error'] == 'Snapshot not found'

    def test_search_logs_invalid_store_id(self, app_client):
        r = app_client.get('/logs/search_logs?store_id=../x')
        assert r.status_code == 400
        assert r.get_json()['error'] == 'Invalid store_id parameter'
