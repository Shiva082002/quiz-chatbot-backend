"""
MongoDB persistence for quiz sessions.
Configure via environment variables (typically in backend/.env):
  MONGODB_URI          — connection string (if empty, saves are skipped)
  MONGODB_DATABASE     — database name
  MONGODB_COLLECTION   — collection name for session documents
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

_client: Optional[MongoClient] = None


def _get_collection():
    global _client
    uri = (os.getenv("MONGODB_URI") or "").strip()
    if not uri:
        return None

    db_name = (os.getenv("MONGODB_DATABASE") or "quiz_master").strip()
    coll_name = (os.getenv("MONGODB_COLLECTION") or "quiz_sessions").strip()

    if _client is None:
        _client = MongoClient(uri, serverSelectionTimeoutMS=8000)

    return _client[db_name][coll_name]


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


def list_quiz_sessions(*, offset: int = 0, limit: int = 5) -> tuple[list[dict[str, Any]], int]:
    """
    Newest sessions first. Returns (sessions, total_count).
    If Mongo is not configured, returns ([], 0).
    """
    coll = _get_collection()
    if coll is None:
        return [], 0

    try:
        total = coll.count_documents({})
        cursor = (
            coll.find()
            .sort("savedAt", -1)
            .skip(max(0, offset))
            .limit(max(1, min(int(limit), 50)))
        )
        sessions = [_serialize_session(doc) for doc in cursor]
        return sessions, total  
    except PyMongoError:
        return [], 0


def save_quiz_session_document(doc: dict[str, Any]) -> bool:
    """
    Insert one quiz session document. Returns True if persisted, False if skipped or failed.
    """
    coll = _get_collection()
    if coll is None:
        return False

    try:
        coll.insert_one(doc)
        return True
    except PyMongoError:
        return False
