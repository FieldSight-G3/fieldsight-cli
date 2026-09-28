# AWS

## Chart

```
config.settings
      |
clients.py   session() --> client(service)    adaptive retries, 4 attempts, 5 s connect / 30 s read
      |
      +-- chat_model()        ChatBedrockConverse + Guardrails      --> specialists, Reviewer, RAG chain
      +-- embeddings()        Titan v2, 1024 dims, unit length      --> script/ingest_corpus_local.py
      +-- corpus_retriever()  Bedrock KB retriever, score-gated     --> retrieval/corpus.py
      +-- textract() -------> textract.py        start_analysis, get_analysis_status, get_blocks,
      |                                          load_output, analyze_bytes        --> ingest/
      +-- s3() -------------> s3.py              upload, put_text, list_objects, list_keys,
      |                                          read_json, delete_folder          --> ingest/, knowledge_base.py
      +-- bedrock_agent() --> knowledge_base.py  write_chunk, start_sync, get_sync --> ingest/corpus/indexing.py

errors.py   @raises(FieldSightError subclass, action): a boto failure becomes a typed FieldSight error
```

## Files

| File | Contains |
|---|---|
| `clients.py` | The one place AWS clients and Bedrock models are built: `session`, `client`, `chat_model`, `embeddings`, `corpus_retriever`, and a getter per service. |
| `textract.py` | The async Textract flow (`start_analysis`, `get_analysis_status`, `get_blocks`), reading saved output from S3 (`load_output`), and the synchronous `analyze_bytes` for single-page checks. |
| `s3.py` | Reads and writes on the project bucket. |
| `knowledge_base.py` | Writes a chunk and its `.metadata.json` sidecar to the KB's S3 data source, and starts and reads KB sync jobs. |
| `errors.py` | The `@raises` decorator. |

## Decisions

| Decision | Why |
|---|---|
| One module builds every AWS client and Bedrock model; nothing else imports `boto3` | Spec section 3: one module builds Bedrock clients; agents never touch `boto3` |
| `boto3.Session(region_name=...)` with the default credential chain; no keys in config | Section 11: IAM roles only, no long-lived access keys |
| The session and each client are cached, so they're built once per process | Clients are reused across calls |
| botocore adaptive retries: 4 attempts, 5 s connect timeout, 30 s read timeout | Section 10: bounded, backed-off retries that respect throttling |
| Every chat model call carries `guardrail_config` with trace enabled | Section 3: Guardrails content filters on every model call |
| Temperature 0 by default | Citation accuracy over variety |
| Titan v2 embeddings at 1024 dims, normalized | Unit length, so cosine distance works directly |
| The KB retriever returns `retrieval_max_chunks` hits gated by `retrieval_score_threshold`; `gated=False` only for threshold tuning | Section 7: refusal is gated on the per-chunk similarity score |
| Textract uses the async flow for anything multi-page; `analyze_bytes` is single-page only | Section 7: the synchronous API is capped at single-page documents |
| Textract's `ClientRequestToken` is the file hash, cut to 64 characters | A re-run of the same file reuses the job, so ingestion is idempotent |
| KB chunks go to S3 as `.txt` plus a `.metadata.json` sidecar of `metadataAttributes` | Section 7: `doc_type` and `section_path` must be filterable at query time |
| `@raises` (with `functools.wraps`) turns boto failures into `ExtractionError`, `RetrievalError`, and so on | Section 13: a custom exception hierarchy and decorators that preserve `wraps` |

## Not implemented

- Only one model tier. The fast tier (classification, the readiness gate), the judge deployment and the multimodal photo check aren't wired.
- `chat_model()` builds its own boto client from `region_name`, so the adaptive retry config above doesn't apply to model calls.
- The Guardrails Prompt Attacks filter on analyst input and on strings cracked out of artifacts (`ApplyGuardrail`); only `guardrail_config` on chat calls exists.
- Clients for AgentCore Runtime, Gateway and Identity.
- `get_analysis_status` and `get_blocks` aren't wrapped by `@raises`, so a failure there surfaces as a raw `ClientError`.
