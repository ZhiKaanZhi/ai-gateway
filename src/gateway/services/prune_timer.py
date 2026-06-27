"""Background prune timer — periodically deletes stale intent rows (D37, D40).

A standalone module-level coroutine (not a closure inside the lifespan) so a unit test can drive it
with a fake repository, with no DB and no app. The lifespan starts it as a task on boot and cancels
it on shutdown (see ``gateway.main``).
"""

from __future__ import annotations

import asyncio
import logging

from gateway.domain.ports import IntentRepository

logger = logging.getLogger(__name__)


async def run_prune_loop(
    repo: IntentRepository, *, interval_seconds: float, max_age_seconds: float
) -> None:
    """Sleep, prune, repeat. A failed sweep is logged and skipped, never propagated (D40).

    The sweep age (``max_age_seconds``) is the gate's staleness setting (D39); the cadence
    (``interval_seconds``) is its own config value (D40). A persistently failing sweep degrades to
    no-cleanup — the log line is the only signal — which is acceptable for a disposable cache.
    """
    while True:
        # Sleep FIRST so a deploy/boot does not prune on every startup. The sleep is outside the try
        # so a cancel during it unwinds the loop directly, rather than being mistaken for a sweep.
        await asyncio.sleep(interval_seconds)
        try:
            deleted = await repo.prune_older_than(max_age_seconds)
            logger.info("intent prune: deleted %d stale rows", deleted)
        except asyncio.CancelledError:
            # Shutdown cancelled us. CancelledError is a BaseException (not caught by the Exception
            # clause below); the explicit re-raise just makes the clean exit obvious.
            raise
        except Exception:  # noqa: BLE001 — a failed sweep must never crash the app (D40)
            logger.exception("intent prune sweep failed; retrying next interval")
