"""Unit test for the prune timer's failure safety (D40, D42) — no DB, no app.

Backs D40's two promises that the integration test never exercises: a sweep that raises is logged
and skipped (the loop keeps going), and the loop stops cleanly when cancelled. Asserts behaviour
only — never sleep durations or log strings.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from gateway.domain.models import Embedding, IntentCandidate, IntentEntry
from gateway.services.prune_timer import run_prune_loop


class FlakyPruneRepo:
    """``IntentRepository`` whose ``prune_older_than`` raises on its first call, then succeeds.

    ``second_call`` fires once a sweep has completed *after* the raising one — proof the loop
    continued past the exception instead of propagating it.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.second_call = asyncio.Event()

    async def search(
        self, embedding: Embedding, threshold: float, limit: int = 5
    ) -> list[IntentCandidate]:
        return []  # unused by the timer

    async def store(self, entry: IntentEntry) -> None:  # unused by the timer
        return None

    async def prune_older_than(self, max_age_seconds: float) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        self.second_call.set()
        return 0


async def test_loop_continues_after_a_failed_sweep_and_stops_on_cancel() -> None:
    repo = FlakyPruneRepo()
    task = asyncio.create_task(
        run_prune_loop(repo, interval_seconds=0.001, max_age_seconds=86400.0)
    )

    # The loop must survive the first sweep raising and reach a second, successful sweep.
    await asyncio.wait_for(repo.second_call.wait(), timeout=1.0)
    assert repo.calls >= 2
    assert not task.done()  # the RuntimeError did not propagate out of the loop

    # Cancelling stops the loop cleanly: the task ends cancelled, surfacing no other error.
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_loop_exits_when_cancelled_during_sleep() -> None:
    # A long interval means the cancel lands while the loop is asleep (the common shutdown case).
    repo = FlakyPruneRepo()
    task = asyncio.create_task(
        run_prune_loop(repo, interval_seconds=1000.0, max_age_seconds=86400.0)
    )
    await asyncio.sleep(0)  # let the task start and enter its first sleep
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert repo.calls == 0  # cancelled before any sweep ran
