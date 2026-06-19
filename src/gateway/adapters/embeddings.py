"""fastembed embedding adapter — implements :class:`EmbeddingProvider`.

fastembed runs MiniLM/bge-small as local ONNX (CPU, no PyTorch). The model is loaded once at
construction (in the composition root) and reused for every request. The library is synchronous,
so :meth:`embed` offloads the call to a worker thread (``anyio.to_thread.run_sync``) to keep the
event loop unblocked — the async discipline this gateway holds to.
"""

from __future__ import annotations

import anyio
from fastembed import TextEmbedding

from gateway.domain.models import Embedding


class FastembedEmbeddingProvider:
    """Local ONNX embeddings via fastembed. Implements ``EmbeddingProvider``."""

    def __init__(self, model_name: str) -> None:
        # Loading the ONNX model is the expensive step; do it once, here, never per request.
        self._model = TextEmbedding(model_name=model_name)

    async def embed(self, text: str) -> Embedding:
        return await anyio.to_thread.run_sync(self._embed_sync, text)

    def _embed_sync(self, text: str) -> Embedding:
        # ``embed`` yields one numpy array per input; we pass a single text and take the first.
        vector = next(iter(self._model.embed([text])))
        # Explicit float() conversion keeps mypy --strict honest (fastembed is typed as Any).
        return [float(x) for x in vector]
