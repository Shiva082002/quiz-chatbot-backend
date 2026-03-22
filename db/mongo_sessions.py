"""
MongoDB persistence for quiz sessions.
Configure via environment variables (typically in backend/.env):
  MONGODB_URI          — connection string (if empty, saves are skipped)
  MONGODB_DATABASE     — database name
  MONGODB_COLLECTION   — collection name for session documents

Serverless note (Vercel, etc.): a long-lived process may reuse a dead pooled connection.
We reset the client and retry on PyMongo errors, and tune the driver for shorter idle sockets.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

log = logging.getLogger(__name__)

_client: Optional[MongoClient] = None

# How many times to retry list/save after resetting the client (covers stale pools + blips).
_MAX_ATTEMPTS = 3


def _reset_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def _mongo_uri() -> str:
    return (os.getenv("MONGODB_URI") or "").strip()


def _db_and_collection_names() -> tuple[str, str]:
    db_name = (os.getenv("MONGODB_DATABASE") or "quiz_master").strip()
    coll_name = (os.getenv("MONGODB_COLLECTION") or "quiz_sessions").strip()
    return db_name, coll_name


def _get_or_create_client() -> Optional[MongoClient]:
    """Return a live client, or None if MongoDB is not configured."""
    global _client
    uri = _mongo_uri()
    if not uri:
        return None

    if _client is None:
        # Serverless-friendly: avoid holding idle sockets forever; allow driver retries.
        _client = MongoClient(
            uri,
            serverSelectionTimeoutMS=15_000,
            connectTimeoutMS=15_000,
            socketTimeoutMS=45_000,
            maxPoolSize=10,
            minPoolSize=0,
            maxIdleTimeMS=55_000,
            retryReads=True,
            retryWrites=True,
        )
    return _client


def _get_collection():
    client = _get_or_create_client()
    if client is None:
        return None
    db_name, coll_name = _db_and_collection_names()
    return client[db_name][coll_name]


def mongo_is_configured() -> bool:
    return bool(_mongo_uri())


def _serialize_session(doc: dict[str, Any]) -> dict[str, Any]:
    """Make a Mongo document JSON-safe for the API."""
    out: dict[str, Any] = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    sa = out.get("savedAt")
    if isinstance(sa, datetime):
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        out["savedAt"] = sa.isoformat()
    return out


def list_quiz_sessions(*, offset: int = 0, limit: int = 5) -> tuple[list[dict[str, Any]], int, bool, bool]:
    """
    Newest sessions first.

    Returns:
      (sessions, total, mongo_configured, query_succeeded)

    - mongo_configured: MONGODB_URI is set
    - query_succeeded: False only when URI is set but list/count failed after retries
    """
    if not mongo_is_configured():
        return [], 0, False, True

    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 50))

    last_err: Optional[Exception] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            coll = _get_collection()
            if coll is None:
                return [], 0, True, False

            # Force server selection before counting (fails fast on bad/stale client).
            coll.database.client.admin.command("ping")

            total = coll.count_documents({})
            cursor = (
                coll.find()
                .sort("savedAt", -1)
                .skip(offset)
                .limit(limit)
            )
            sessions = [_serialize_session(doc) for doc in cursor]
            return sessions, total, True, True
        except PyMongoError as e:
            last_err = e
            log.warning("list_quiz_sessions attempt %s/%s failed: %s", attempt, _MAX_ATTEMPTS, e)
            _reset_client()
            if attempt < _MAX_ATTEMPTS:
                time.sleep(0.25 * attempt)

    if last_err is not None:
        log.error("list_quiz_sessions gave up after %s attempts: %s", _MAX_ATTEMPTS, last_err)
    return [], 0, True, False


def save_quiz_session_document(doc: dict[str, Any]) -> bool:
    """
    Insert one quiz session document. Returns True if persisted, False if skipped or failed.
    """
    if not mongo_is_configured():
        return False

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            coll = _get_collection()
            if coll is None:
                return False
            coll.database.client.admin.command("ping")
            coll.insert_one(doc)
            return True
        except PyMongoError as e:
            log.warning("save_quiz_session_document attempt %s/%s failed: %s", attempt, _MAX_ATTEMPTS, e)
            _reset_client()
            if attempt < _MAX_ATTEMPTS:
                time.sleep(0.25 * attempt)

    return False
