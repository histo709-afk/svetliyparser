"""Telethon client setup and singleton."""
from __future__ import annotations

import asyncio
import os
import uuid

import structlog
from redis.asyncio import from_url as redis_from_url
from telethon import TelegramClient
from telethon.errors import AuthKeyDuplicatedError
from telethon.sessions import StringSession

from app.config import settings

log = structlog.get_logger(__name__)

_session_string = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()


class SessionRevokedError(RuntimeError):
    """The stored session string is permanently dead.

    Telegram revoked the auth key, which it does the moment the same key talks
    to it from two IPs at once. Nothing brings that key back — the only cure is
    generating a fresh TELEGRAM_SESSION_STRING by hand. Retrying the connection
    is not just useless, it hides the real problem behind a wall of warnings,
    which is exactly what happened on 6 September.
    """


class SessionLockUnavailableError(RuntimeError):
    """Another container is still holding the session.

    Unlike a revoked session this is a waiting game, not a dead end — the
    holder will exit sooner or later. Kept as its own type so the caller can
    keep retrying instead of giving up the way it must for a revoked key.
    """


# ── SESSION LOCK ──────────────────────────────────────────────────────────────
# Exactly one container may hold the userbot session at a time. Railway starts
# the new container before the old one is gone on every deploy, so both go to
# Telegram with the same auth key and Telegram kills it. That is not a rare
# race: it is the default behaviour of a rolling deploy, and it is what took
# the whole parser down for a day. Two pushes in a row simply widened the
# window enough to hit it.
#
# So we gate the connection on a Redis lock instead of hoping the timing works
# out. A booting container waits for the outgoing one to let go, and if it
# never does we refuse to connect at all — a parser that is down is annoying,
# a revoked session is a manual recovery with an SMS code.
SESSION_LOCK_KEY = "svetliyparser:userbot:session-lock"
SESSION_LOCK_TTL = 45  # seconds; the refresher renews it well before this
SESSION_LOCK_REFRESH = 15
SESSION_LOCK_WAIT = 300  # how long to let the outgoing container finish
SESSION_LOCK_SETTLE = 5  # let its TCP connection to Telegram actually die

# Compare-and-swap in Lua: only the container that owns the lock may renew or
# release it. A plain DEL would let a container whose TTL had already lapsed
# delete the lock its successor is now holding.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_REFRESH_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_instance_id = uuid.uuid4().hex
_lock_redis = None
_lock_refresher: "asyncio.Task | None" = None


class _UserbotStatus:
    """Whether the userbot is running, and why not if it isn't.

    The management bot survives a dead userbot now, so /status has to be able
    to say what happened — otherwise the only symptom is posts quietly not
    arriving, which is how a revoked session went unnoticed for hours.
    """

    def __init__(self) -> None:
        self.alive: bool = False
        self.error: "str | None" = None

    def mark_alive(self) -> None:
        self.alive, self.error = True, None

    def mark_dead(self, error: str) -> None:
        self.alive, self.error = False, error


userbot_status = _UserbotStatus()


def _make_client() -> TelegramClient:
    session = StringSession(_session_string) if _session_string else StringSession()
    return TelegramClient(
        session,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )


telethon_client = _make_client()


async def _refresh_session_lock() -> None:
    """Keep renewing our claim while we hold the session."""
    while True:
        await asyncio.sleep(SESSION_LOCK_REFRESH)
        try:
            still_ours = await _lock_redis.eval(
                _REFRESH_SCRIPT, 1, SESSION_LOCK_KEY, _instance_id, SESSION_LOCK_TTL
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A Redis blip is survivable — the TTL has room for a few misses.
            log.warning("session_lock_refresh_failed", error=str(exc)[:120])
            continue

        if not still_ours:
            # Our TTL lapsed (long Redis outage, event-loop stall) and another
            # container has taken the lock. It is talking to Telegram with this
            # session right now; staying connected is precisely the two-IP
            # situation that revokes the key. Drop the connection and die —
            # Railway restarts us and we queue up on the lock like anyone else.
            log.error("session_lock_lost", instance=_instance_id)
            try:
                if telethon_client.is_connected():
                    await telethon_client.disconnect()
            except Exception:
                pass
            os._exit(1)


async def _acquire_session_lock() -> bool:
    """Block until this container owns the session. Returns True if it had to
    wait, i.e. another container was still holding on when we booted."""
    global _lock_redis, _lock_refresher

    _lock_redis = redis_from_url(settings.REDIS_URL)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SESSION_LOCK_WAIT
    waited = False

    while not await _lock_redis.set(
        SESSION_LOCK_KEY, _instance_id, nx=True, ex=SESSION_LOCK_TTL
    ):
        if loop.time() >= deadline:
            raise SessionLockUnavailableError(
                f"Another instance has held the userbot session lock for "
                f"{SESSION_LOCK_WAIT}s. Refusing to connect — connecting anyway "
                f"is what revokes the auth key."
            )
        if not waited:
            log.info("session_lock_waiting", ttl=await _lock_redis.ttl(SESSION_LOCK_KEY))
            waited = True
        await asyncio.sleep(3)

    log.info("session_lock_acquired", instance=_instance_id, waited=waited)
    _lock_refresher = asyncio.create_task(_refresh_session_lock())
    return waited


async def release_session_lock() -> None:
    """Hand the session over. Callers must disconnect the client *first* — the
    next container starts connecting the moment this returns."""
    global _lock_refresher

    if _lock_refresher is not None:
        _lock_refresher.cancel()
        _lock_refresher = None
    if _lock_redis is None:
        return
    try:
        await _lock_redis.eval(_RELEASE_SCRIPT, 1, SESSION_LOCK_KEY, _instance_id)
        log.info("session_lock_released", instance=_instance_id)
    except Exception as exc:
        log.warning("session_lock_release_failed", error=str(exc)[:120])


async def shutdown_client() -> None:
    """Disconnect, then hand the session over — strictly in that order.

    The next container starts connecting the moment the lock frees, so
    releasing before the socket is closed would recreate the very overlap the
    lock exists to prevent.
    """
    try:
        if telethon_client.is_connected():
            await telethon_client.disconnect()
    except Exception as exc:
        log.warning("shutdown_disconnect_failed", error=str(exc)[:120])
    await release_session_lock()


async def start_client() -> TelegramClient:
    """Start and authenticate the Telethon client.

    Raises SessionRevokedError if the session string is dead. That is a
    terminal condition for the userbot, but *not* for the process: the
    management bot keeps running so the admin can still see what happened.
    """
    global telethon_client

    if not _session_string:
        raise SessionRevokedError(
            "TELEGRAM_SESSION_STRING is empty — set it in Railway."
        )
    log.info("session_string_loaded", length=len(_session_string))

    waited = await _acquire_session_lock()
    if waited:
        # The previous holder just let go. Give its socket to Telegram a moment
        # to actually close, or we recreate the overlap the lock exists to stop.
        await asyncio.sleep(SESSION_LOCK_SETTLE)

    # We hold the lock, so no sibling container can be racing us. A duplicate
    # error at this point therefore means the key was revoked in some earlier
    # incident and is gone for good — there is nothing to retry.
    try:
        telethon_client = _make_client()
        await telethon_client.connect()
        authorized = await telethon_client.is_user_authorized()
    except AuthKeyDuplicatedError as exc:
        await release_session_lock()
        raise SessionRevokedError(
            "Telegram revoked this auth key — it was used from two IPs at "
            "once. Generate a new TELEGRAM_SESSION_STRING and set it in "
            "Railway; retrying can never revive this one."
        ) from exc

    if not authorized:
        await release_session_lock()
        raise SessionRevokedError(
            "Telethon session is not authorized. Generate a new "
            "TELEGRAM_SESSION_STRING and set it in Railway."
        )

    log.info("telethon_authenticated")
    return telethon_client
