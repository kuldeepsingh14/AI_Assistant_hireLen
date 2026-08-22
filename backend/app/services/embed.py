"""Optional local semantic embeddings via fastembed (free, offline, no API key)."""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None
_state = "uninitialized"


def _load(mode: str):
    """Return a fastembed model, or None when unavailable/disabled."""
    global _model, _state
    if _state != "uninitialized":
        return _model
    if mode == "lexical":
        _state = "lexical"
        return None
    try:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=_MODEL_NAME)
        _state = "fastembed"
        log.info("fastembed ready (%s)", _MODEL_NAME)
    except Exception as exc:
        if mode == "fastembed":
            # Explicitly requested, so make the failure loud rather than silently degrading.
            raise RuntimeError(
                f"EMBEDDER=fastembed but the model could not load: {exc}. "
                "Install it with `pip install -r requirements-optional.txt`."
            ) from exc
        log.warning("fastembed unavailable (%s); falling back to lexical BM25", exc)
        _model = None
        _state = "lexical"
    return _model


def encode(texts: list[str], mode: str = "auto") -> np.ndarray | None:
    """L2-normalized embedding matrix, or None if running lexical-only."""
    model = _load(mode)
    if model is None or not texts:
        return None
    vectors = np.array(list(model.embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-9, None)


def backend_name(mode: str = "auto") -> str:
    _load(mode)
    return "fastembed:" + _MODEL_NAME if _state == "fastembed" else "lexical:bm25"
