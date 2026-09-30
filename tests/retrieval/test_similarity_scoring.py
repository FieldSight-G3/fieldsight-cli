"""Corpus hits are scored by their own similarity to the question, so the threshold can refuse an off-corpus question."""

import math

import pytest
from langchain_core.documents import Document

from fieldsight.retrieval import corpus


def unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


# a tiny embedding space: the question and each chunk's text map to a fixed unit vector
VECTORS = {
    "When is a work-related injury recordable?": unit(1, 0, 0),
    "general recording criteria": unit(0.9, 0.1, 0),
    "first aid list": unit(0.6, 0.8, 0),
    "What is the best recipe for sourdough bread?": unit(0, 0, 1),
}


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return VECTORS[text]


class FakeRetriever:
    """ the managed KB: whatever the question, its best hit scores near 1.0 """

    def __init__(self, hits: list[Document]) -> None:
        self.hits = hits

    def invoke(self, query: str) -> list[Document]:
        return [Document(page_content=h.page_content, metadata=dict(h.metadata)) for h in self.hits]


def hit(chunk_id: str, text: str, kb_score: float) -> Document:
    return Document(page_content=text, metadata={"score": kb_score, "source_metadata": {"chunk_id": chunk_id}})


HITS = [hit("CFR-1904-a", "first aid list", 1.0), hit("CFR-1904-b", "general recording criteria", 0.97)]


@pytest.fixture
def kb(monkeypatch):
    embeddings = FakeEmbeddings()
    monkeypatch.setattr(corpus.clients, "embeddings", lambda: embeddings)
    monkeypatch.setattr(corpus.clients, "corpus_retriever", lambda search_filter=None: FakeRetriever(HITS))
    monkeypatch.setattr(corpus.settings, "retrieval_score_threshold", 0.5)
    corpus.chunk_vector.cache_clear()
    return embeddings


def test_hits_are_reordered_by_their_similarity_to_the_question(kb):
    hits = corpus.search("When is a work-related injury recordable?")

    assert [corpus.meta(h)["chunk_id"] for h in hits] == ["CFR-1904-b", "CFR-1904-a"]
    assert hits[0].metadata["score"] == pytest.approx(0.9 / math.sqrt(0.82))
    # the KB's relative score is kept alongside, not used
    assert hits[0].metadata["kb_score"] == 0.97


def test_an_off_corpus_question_is_gated_out_even_though_the_kb_ranked_its_hits_high(kb):
    assert corpus.search("What is the best recipe for sourdough bread?") == []
    # ungated, for threshold tuning: the hits come back with their real (floored) similarity
    assert [h.metadata["score"] for h in corpus.search("What is the best recipe for sourdough bread?", gated=False)] == [0.0, 0.0]


def test_below_threshold_hits_are_dropped_and_the_rest_kept(kb):
    hits = corpus.search("When is a work-related injury recordable?")

    # first aid list: cosine 0.6 clears 0.5; both stay
    assert len(hits) == 2
    corpus.settings.retrieval_score_threshold = 0.7
    assert [corpus.meta(h)["chunk_id"] for h in corpus.search("When is a work-related injury recordable?")] == ["CFR-1904-b"]


def test_each_chunk_is_embedded_once_per_process(kb):
    corpus.search("When is a work-related injury recordable?")
    corpus.search("When is a work-related injury recordable?")

    # two chunk embeddings the first time, then only the question each search
    assert kb.calls == 2 + 1 + 1


def test_no_hits_embeds_no_chunks(kb, monkeypatch):
    monkeypatch.setattr(corpus.clients, "corpus_retriever", lambda search_filter=None: FakeRetriever([]))

    # only the question, which is embedded while the KB searches
    assert corpus.search("When is a work-related injury recordable?") == [] and kb.calls == 1
