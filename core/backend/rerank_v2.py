import math
import time
from logging import Logger
from os import getenv

import numpy as np
from cohere import AsyncClientV2
from cohere.v2.types import V2RerankResponse
from langchain_core.documents import Document
from logtools import getLogger

logger: Logger = getLogger()


def _none_to_num(x: int | None) -> int:
    return x if x is not None else 0


def _sigmoid(x: float) -> float:
    # numerically stable-ish sigmoid for typical score ranges
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _percentile_rank_from_values(values: np.ndarray) -> np.ndarray:
    """
    Compute percentile ranks in [0,1] for an array.
    Uses rank-based method that is robust to heavy tails and outliers.
    If all values are equal, returns zeros.
    """
    if values.size == 0:
        return values

    # If constant, no signal
    if np.all(values == values[0]):
        return np.zeros_like(values, dtype=np.float64)

    order = np.argsort(values, kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(values.size, dtype=np.float64)

    # Convert to [0,1]
    denom = max(values.size - 1, 1)
    return ranks / denom


def _log1p_percentile_visits(visits: np.ndarray) -> np.ndarray:
    """
    Robust popularity feature in [0,1]:
      vhat = percentile_rank(log1p(visits))
    """
    logv = np.log1p(visits.astype(np.float64))
    return _percentile_rank_from_values(logv)


class Reranker:
    def __init__(self) -> None:
        API_KEY: str | None = getenv("OPENAI_API_KEY")
        BASE_URL: str | None = getenv("OPENAI_API_BASE")

        self.max_reranked_docs: int = int(getenv("COHERE_RERANK_N_DOCS", 10))

        # Soft-boost hyperparameters
        # beta controls overall boost strength (multiplicative)
        self.popularity_beta: float = float(getenv("RERANKER_POPULARITY_BETA", 0.10))
        # tau is the relevance "turn-on" threshold for gating
        self.popularity_tau: float = float(getenv("RERANKER_POPULARITY_TAU", 0.35))
        # k controls gate softness; smaller = sharper
        self.popularity_k: float = float(getenv("RERANKER_POPULARITY_K", 0.10))
        # cap on multiplicative gain: rel * (1 + cap)
        self.popularity_cap: float = float(getenv("RERANKER_POPULARITY_CAP", 0.20))  # max +20% by default

        # where visits live in metadata (your current structure)
        # expects doc.metadata["site_stats"]["unique_visits"]
        self.popularity_field_path: tuple[str, str] = ("site_stats", "unique_visits")

        if API_KEY is None or BASE_URL is None:
            raise ValueError("OPENAI_API_KEY and OPENAI_API_BASE environment variables must be set for rerank model.")

        self.client: AsyncClientV2 = AsyncClientV2(api_key=API_KEY, base_url=BASE_URL)

    def _gate(self, rel_score: float) -> float:
        # sigmoid((rel - tau)/k)
        k = max(self.popularity_k, 1e-6)
        return _sigmoid((rel_score - self.popularity_tau) / k)

    async def arerank_documents(
        self,
        query: str,
        docs: dict[str, list[Document]],
        popularity_stats: dict[str, float] | None = None,  # not used in this version (local doc metadata used instead)
        **kwargs,
    ) -> list[Document]:
        """
        Asynchronously rerank a list of documents using the Cohere rerank model.
        Applies a soft popularity boost using:
          vhat = percentile_rank(log1p(visits))
          final = rel * (1 + clamp(beta * vhat * gate(rel), 0, cap))
        """
        if not docs:
            logger.error(f"No documents to rerank for query: {query}")
            return []

        if not isinstance(docs, dict):
            logger.error(f"Expected docs to be a dict[str, list[Document]], got {type(docs)}")
            return []

        candidates: list[Document] = []
        for _, docs_list in docs.items():
            if len(docs_list) > 0:
                candidates.extend(docs_list)

        if not candidates:
            logger.error(f"No candidates extracted for query: {query}")
            return []

        t = time.time()
        response: V2RerankResponse = await self.client.rerank(
            model=getenv("COHERE_RERANK_MODEL", "cohere-rerank-v3.5"),
            query=query,
            documents=[doc.metadata["description"] for doc in candidates],
            request_options=kwargs,  # type: ignore
        )
        logger.debug(f"Rerank API call took {time.time() - t:.2f} seconds")

        # Cohere returns results for provided docs; use indices to map back into candidates
        idxs = np.array([res.index for res in response.results], dtype=np.int64)

        rel_scores = np.array([res.relevance_score for res in response.results], dtype=np.float64)

        # Extract visits aligned with response.results ordering
        site_stats_key, visits_key = self.popularity_field_path
        visits = np.array(
            [_none_to_num(candidates[i].metadata.get(site_stats_key, {}).get(visits_key, 0)) for i in idxs],
            dtype=np.float64,
        )
        np.nan_to_num(visits, copy=False)

        # --- Popularity feature: log1p + percentile rank in [0,1] ---
        vhat = _log1p_percentile_visits(visits)

        # --- Soft gated multiplicative boost ---
        # gain_i = clamp(beta * vhat_i * gate(rel_i), 0, cap)
        gates = np.array([self._gate(float(s)) for s in rel_scores], dtype=np.float64)
        gains = self.popularity_beta * vhat * gates
        gains = np.clip(gains, 0.0, self.popularity_cap)

        final_scores = rel_scores * (1.0 + gains)

        # Update docs with scores + debug fields
        for i, rel, v, vh, g, gain, final in zip(idxs, rel_scores, visits, vhat, gates, gains, final_scores):
            idx = int(i)
            candidates[idx].metadata["rerank_score"] = float(final)
            candidates[idx].metadata["rerank_score_raw"] = float(rel)
            candidates[idx].metadata["popularity_visits"] = int(v)
            candidates[idx].metadata["popularity_vhat"] = float(vh)
            candidates[idx].metadata["popularity_gate"] = float(g)
            candidates[idx].metadata["popularity_gain"] = float(gain)
            candidates[idx].metadata["original_idx"] = idx

            logger.debug(
                f"Document {candidates[idx].metadata.get('name')}, original index: {idx}, "
                f"raw: {float(rel):.4f}, final: {float(final):.4f}, "
                f"visits: {int(v)}, vhat: {float(vh):.3f}, gate: {float(g):.3f}, gain: {float(gain):.3f}"
            )

        # Sort by final score
        reranked: list[Document] = sorted(candidates, key=lambda x: x.metadata.get("rerank_score", 0), reverse=True)

        # Keep only top_n
        top_n = min(self.max_reranked_docs, len(reranked))
        reranked = reranked[:top_n]

        reranked_info = [
            {
                "original_index": doc.metadata.get("original_idx"),
                "reranked_index": i,
                "rerank_score": doc.metadata.get("rerank_score"),
                "rerank_score_raw": doc.metadata.get("rerank_score_raw"),
                "popularity_visits": doc.metadata.get("popularity_visits"),
                "popularity_vhat": doc.metadata.get("popularity_vhat"),
                "name": doc.metadata.get("name"),
            }
            for i, doc in enumerate(reranked)
        ]
        logger.debug(f"Reranking for query: {query}\n{reranked_info}")

        return reranked
