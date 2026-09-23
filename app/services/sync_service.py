"""Reliable synchronization from the offline SQLite POS to the hosted API."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Setting, SyncQueue

REMOTE_URL_KEY = "sync_remote_url"
TOKEN_KEY = "sync_token"
SYNC_INTERVAL_SECONDS = 15
_sync_lock = threading.Lock()
_sync_wakeup = threading.Event()
_worker_started = False


def offline_mode() -> bool:
    return os.getenv("TOP_CITY_OFFLINE_MODE", "").strip().lower() in {"1", "true", "yes"}


def _setting(session, key: str) -> str:
    row = session.scalar(select(Setting).where(Setting.key == key))
    return (row.value if row else "").strip()


def sync_settings() -> dict:
    with SessionLocal() as session:
        remote_url = _setting(session, REMOTE_URL_KEY) or os.getenv("TOP_CITY_SYNC_URL", "").strip().rstrip("/")
        token = _setting(session, TOKEN_KEY)
        pending = session.scalar(select(func.count()).select_from(SyncQueue).where(SyncQueue.status != "synced")) or 0
        failed = session.scalar(select(func.count()).select_from(SyncQueue).where(SyncQueue.status == "failed")) or 0
        last_synced = session.scalar(select(func.max(SyncQueue.synced_at)))
    return {
        "enabled": offline_mode(),
        "remote_url": remote_url,
        "token_configured": bool(token),
        "pending": int(pending),
        "failed": int(failed),
        "last_synced_at": last_synced.isoformat() if last_synced else None,
    }


def save_sync_settings(remote_url: str, token: str | None = None) -> dict:
    remote_url = remote_url.strip().rstrip("/")
    parsed = urlparse(remote_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter the public Railway application URL, beginning with https://")
    with SessionLocal() as session:
        values = {REMOTE_URL_KEY: remote_url}
        if token is not None and token.strip():
            values[TOKEN_KEY] = token.strip()
        for key, value in values.items():
            row = session.scalar(select(Setting).where(Setting.key == key))
            if row:
                row.value = value
            else:
                session.add(Setting(key=key, value=value))
        session.commit()
    return sync_settings()


def queue_order(client_order_id: str, payload: dict) -> None:
    if not offline_mode() or not client_order_id:
        return
    with SessionLocal() as session:
        existing = session.scalar(select(SyncQueue).where(SyncQueue.entity_key == client_order_id))
        if existing:
            return
        session.add(SyncQueue(entity_type="order", entity_key=client_order_id,
                              payload=json.dumps(payload, separators=(",", ":")), status="pending"))
        session.commit()
    # Upload immediately when a connection is available. If it is not, the
    # same durable row remains queued for the periodic retry.
    _sync_wakeup.set()


def _post_order(remote_url: str, token: str, payload: str) -> None:
    request = Request(remote_url + "/api/sync/orders", data=payload.encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "X-Sync-Token": token,
                               "User-Agent": "TopCityPOSOffline/1.0"})
    with urlopen(request, timeout=12) as response:
        if response.status not in {200, 201}:
            raise RuntimeError("Remote server returned HTTP %s" % response.status)


def sync_pending_orders() -> dict:
    if not offline_mode():
        return {"ok": False, "message": "Synchronization is only active in the offline desktop edition."}
    if not _sync_lock.acquire(False):
        return {"ok": True, "message": "Synchronization is already running."}
    synced = 0
    try:
        with SessionLocal() as session:
            remote_url = _setting(session, REMOTE_URL_KEY) or os.getenv("TOP_CITY_SYNC_URL", "").strip().rstrip("/")
            token = _setting(session, TOKEN_KEY)
            rows = list(session.scalars(select(SyncQueue).where(SyncQueue.status != "synced").order_by(SyncQueue.id)))
        if not remote_url or not token:
            return {"ok": False, "message": "Configure the Railway application URL and sync token first.", "pending": len(rows)}
        for queued in rows:
            error = None
            try:
                _post_order(remote_url, token, queued.payload)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                error = "HTTP %s: %s" % (exc.code, detail)
            except (URLError, OSError, RuntimeError) as exc:
                error = str(exc)[:500]
            with SessionLocal() as session:
                current = session.get(SyncQueue, queued.id)
                if not current:
                    continue
                current.attempts += 1
                if error:
                    current.status = "failed"
                    current.last_error = error
                else:
                    current.status = "synced"
                    current.last_error = None
                    current.synced_at = datetime.now()
                    synced += 1
                session.commit()
            if error and ("timed out" in error.lower() or "urlopen error" in error.lower()):
                break
        result = sync_settings()
        result.update({"ok": result["pending"] == 0, "synced_now": synced,
                       "message": ("All local orders are synchronized." if result["pending"] == 0
                                   else "Some orders are still waiting; automatic retry remains active.")})
        return result
    finally:
        _sync_lock.release()


def start_sync_worker() -> None:
    global _worker_started
    if not offline_mode() or _worker_started:
        return
    _worker_started = True

    def worker():
        while True:
            _sync_wakeup.wait(SYNC_INTERVAL_SECONDS)
            _sync_wakeup.clear()
            try:
                sync_pending_orders()
            except Exception:
                # A failed pass must never stop checkout or future retries.
                pass

    threading.Thread(target=worker, name="railway-sync", daemon=True).start()
