"""Local, on-device text embedder.

Uses FastEmbed (ONNX, CPU-friendly) so embedding happens fully offline with
no API calls. The model is downloaded once and cached under SHARD_ROOT/models,
then loaded with local_files_only so subsequent runs never touch the network.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List

from fastembed import TextEmbedding

from .activity import activity
from .config import settings


class LocalEmbedder:
    def __init__(self) -> None:
        self._model: TextEmbedding | None = None
        self._lock = threading.Lock()
        self.dim = settings.vector_dim

    def _ensure_model(self) -> TextEmbedding:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            Path(settings.models_dir).mkdir(parents=True, exist_ok=True)
            # First run downloads + caches; later runs load from cache only.
            try:
                self._model = TextEmbedding(
                    model_name=settings.embed_model,
                    cache_dir=settings.models_dir,
                    local_files_only=True,
                )
            except Exception:
                # Cache miss (first ever run): allow a one-time download.
                self._model = TextEmbedding(
                    model_name=settings.embed_model,
                    cache_dir=settings.models_dir,
                )
            return self._model

    def warm(self) -> None:
        """Pre-load the model at startup so first request isn't slow."""
        start = time.perf_counter()
        model = self._ensure_model()
        # Run a tiny embed to fully initialize the ONNX session.
        _ = next(iter(model.embed(["warmup"])))
        activity.record(
            "status",
            "Embedding model ready",
            model=settings.embed_model,
            warmup_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    def embed_one(self, text: str) -> List[float]:
        model = self._ensure_model()
        start = time.perf_counter()
        vector = next(iter(model.embed([text]))).tolist()
        activity.record(
            "embed",
            "Embedded 1 item locally",
            chars=len(text),
            embed_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return vector

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        model = self._ensure_model()
        start = time.perf_counter()
        vectors = [v.tolist() for v in model.embed(texts)]
        activity.record(
            "embed",
            f"Embedded {len(texts)} items locally",
            count=len(texts),
            embed_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return vectors


embedder = LocalEmbedder()
