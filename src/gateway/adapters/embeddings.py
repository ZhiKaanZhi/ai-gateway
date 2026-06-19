"""fastembed embedding adapter — implements :class:`EmbeddingProvider`.

fastembed runs MiniLM/bge-small as local ONNX (CPU, no PyTorch). The model is loaded once at
construction (in the composition root) and reused. The library is synchronous, so real calls will
offload to a thread (e.g. ``anyio.to_thread.run_sync``) to keep the event loop unblocked. Stub
only in the harness slice.
"""

from __future__ import annotations

from gateway.domain.models import Embedding


class FastembedEmbeddingProvider:
    """Local ONNX embeddings via fastembed. Implements ``EmbeddingProvider``."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    async def embed(self, text: str) -> Embedding:
        raise NotImplementedError
