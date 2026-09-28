# Retrieval

## Chart

```
{"question": ...}
      |
   gather                                                          evidence.py
      |  pick_filter --> first search (doc_type / section_path)     references.py, corpus.py
      |  filtered search empty --> whole-corpus search, first marked superseded
      |  hop_targets --> up to MAX_HOPS second hops                 references.py
      |
      +-- nothing above threshold / KB unavailable --> refuse       grounding.py
      |
      +-- chunks found:
            assign(context = format_docs)                           chain.py
            | assign(draft = prompt | structured_model -> DraftAnswer)
            | enforce_grounding                                     grounding.py
      |
GroundedAnswer  (or a refusal naming what was searched and where to escalate)

Specialists and the Reviewer reach retrieval only through the search_knowledge_base tool,
which calls corpus.search.
```

## Files

| File | Contains |
|---|---|
| `corpus.py` | The Knowledge Base queries: `kb_filter`, `build_retriever`, `search`, and `meta` for reading chunk metadata off a hit. |
| `references.py` | `pick_filter` for the first search, and `hop_targets` for the second hops that cross-references call for. |
| `evidence.py` | `gather`: the first search, the whole-corpus fallback and the second hops, with a `Retrieval` record per search. |
| `grounding.py` | `enforce_grounding` checks the model's citations against the retrieved chunks; `refuse` builds the refusal. |
| `chain.py` | The grounded system prompt, `format_docs`, and `build_rag_chain`. |

The pydantic models (`Hop`, `Retrieval`, `Citation`, `DraftAnswer`, `GroundedAnswer`) are in `schemas/retrieval.py`.

## Decisions

| Decision | Why |
|---|---|
| One module owns retrieval; the workers and the Reviewer use it only through `search_knowledge_base` | Spec section 3: one module owns retrieval |
| Semantic search over the Bedrock KB, top `retrieval_max_chunks`, dropping hits below `retrieval_score_threshold` | Section 7: refusal is gated on the per-chunk similarity score |
| The first search is filtered only when the question names a layer, a letter or a single Part 1904 section; if it finds nothing, the whole corpus is searched and the filtered search is marked superseded | Section 7: filter where the query implies it, without losing recall |
| Second hops follow chunk cross-references to Part 1904 sections (from non-regulation chunks) and to letters of interpretation (from directive and preamble chunks), capped at `MAX_HOPS` = 3 | Section 7: reach the second hop deliberately through the metadata filters, with bounded context |
| Every search is recorded: query, filters, reason, and each chunk id with its score | Section 5: the run record keeps every retrieval with chunk ids and scores |
| The model answers only from the excerpts, as a structured `DraftAnswer` with its chunk ids | Section 7: a machine-checkable `sources` array |
| `enforce_grounding` refuses when the draft says it isn't grounded or cites a chunk that wasn't retrieved | Section 7: every grounded claim carries a citation that resolves |
| A refusal is typed with a reason, names what was searched and the escalation path, is logged for corpus-gap review, and never falls back on model knowledge | Sections 7 and 13 |
| The system prompt describes, never determines | Section 1: the system describes; the analyst determines |

## Not implemented

- The similarity threshold value is still TBD; it will be chosen with `script/tune_threshold.py` over the golden set.
- There's no retriever over the local `corpus_chunks` pgvector table: `script/ingest_corpus_local.py` fills it, but `corpus.py` only queries the KB.
- The chain's automatic hops don't follow regulation to letter of interpretation (section 1904.39 to the letter carving out an exception), or section 1904.7(b)(3) to the Form 301 column definitions. The specialists reach those by searching again themselves.
- The chain isn't wired into a graph node yet, for `policy_question` or `ask` turns.
- Retrieval latency isn't measured yet (target under 800 ms).
