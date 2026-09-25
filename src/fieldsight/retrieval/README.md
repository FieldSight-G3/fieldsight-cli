# Retrieval

## Chain

```
{"question": ...}
      |
   gather                      evidence.py
      |
      +-- nothing above threshold / KB unavailable --> refuse          grounding.py
      |
      +-- chunks found:
            assign(context = format_docs)                               chain.py
            | assign(draft = prompt | structured_model -> DraftAnswer)  chain.py
            | enforce_grounding                                         grounding.py
      |
GroundedAnswer
```

## Files

| File | Contains |
|---|---|
| `corpus.py` | The Knowledge Base queries: `kb_filter`, `build_retriever`, `search`, and `meta` for reading chunk metadata off a hit. No validation. |
| `references.py` | Decides where to search from text: `pick_filter` for the first search, and `hop_targets` for the second hops that cross-references call for (Part 1904 sections and letters of interpretation, capped at `MAX_HOPS`). |
| `evidence.py` | Runs the searches: the first search, the whole-corpus fallback, and the second hops. `gather` returns the chunks, a `Retrieval` record per search, and a refusal reason when nothing was found. |
| `grounding.py` | `enforce_grounding` checks the model's citations against the retrieved chunks; `refuse` builds the refusal naming what was searched and the escalation path. |
| `chain.py` | The system prompt, `format_docs`, and `build_rag_chain`, which pipes the pieces above together. |

The pydantic models (`Hop`, `Retrieval`, `Citation`, `DraftAnswer`, `GroundedAnswer`) are in `schemas/retrieval.py`.
