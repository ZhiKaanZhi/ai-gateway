"""Domain errors — failures that cross a port back to the caller.

Kept separate from :mod:`gateway.domain.models` (which is plain data, no behaviour). An adapter
raises these so its transport library never leaks past the seam — e.g. ``httpx`` stays behind the
backend adapter, mirroring how raw SQL stays behind the repository.
"""

from __future__ import annotations


class BackendError(Exception):
    """A model backend failed to produce a completion.

    Raised on a transport error / timeout, a non-2xx response, or a malformed body (no choices).
    ``is_timeout`` lets the API layer map the failure to 504 (gateway timeout) vs 502 (bad gateway)
    without importing ``httpx`` — the transport detail stays behind the adapter.
    """

    def __init__(self, message: str, *, is_timeout: bool) -> None:
        super().__init__(message)
        self.is_timeout = is_timeout
