"""Shared session cookie + merge for live / verifier routes."""
from flask import request

from .app_config import session_store

SESSION_COOKIE_NAME = "mi_session_id"


def store_session_data(new_data):
    """Merge new_data into the existing session or create a fresh one."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id and session_store.update_session(session_id, new_data):
        return session_id
    return session_store.create_session(new_data)
