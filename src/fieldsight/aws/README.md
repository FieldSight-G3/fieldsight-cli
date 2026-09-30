# AWS

## Chart

```
config.settings
      |
clients.py   session() --> client(service)    adaptive retries, 4 attempts, 5 s connect / 30 s read
      |
      +-- chat_model()        ChatBedrockConverse + Guardrails      --> specialists, Reviewer, RAG chain
      |   chat_model(fast=True)  the fast tier                      --> harness/guardrails/turn_check.py (readiness)
      +-- bedrock_runtime() --> guardrails.py    screen (ApplyGuardrail), prompt_attack_detected
      |                                          --> harness/guardrails/turn_check.py
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
| `guardrails.py` | `screen`: the ApplyGuardrail API over a string, with no model call; `prompt_attack_detected` reads the result. |
| `s3.py` | Reads and writes on the project bucket. |
| `knowledge_base.py` | Writes a chunk and its `.metadata.json` sidecar to the KB's S3 data source, and starts and reads KB sync jobs. |
| `errors.py` | The `@raises` decorator. |
| `gateway_client.py` | The SigV4-signed MCP client to the AgentCore Gateway: `gateway_tools`, and `available_gateway_tools`, which degrades to native tools when the Gateway or the ECS API is unreachable. |

## Decisions

| Decision | Why |
|---|---|
| One module builds every AWS client and Bedrock model; nothing else imports `boto3` | Spec section 3: one module builds Bedrock clients; agents never touch `boto3` |
| `boto3.Session(region_name=...)` with the default credential chain; no keys in config | Section 11: IAM roles only, no long-lived access keys |
| The session and each client are cached, so they're built once per process | Clients are reused across calls |
| botocore adaptive retries: 4 attempts, 5 s connect timeout, 30 s read timeout | Section 10: bounded, backed-off retries that respect throttling |
| Every chat model call carries `guardrail_config` with trace enabled | Section 3: Guardrails content filters on every model call |
| Temperature 0 by default | Citation accuracy over variety |
| Two model tiers: the reasoning tier by default, `fast=True` for the readiness classifier | Section 3: a fast tier for classification and the readiness gate |
| The Prompt Attacks filter runs through `ApplyGuardrail` with `source="INPUT"`, outside any model call; only a `PROMPT_ATTACK` filter that `BLOCKED` counts | Section 10: the filter runs on analyst input and on every cracked string, before either reaches a model |
| Titan v2 embeddings at 1024 dims, normalized | Unit length, so cosine distance works directly |
| The KB retriever returns `retrieval_max_chunks` hits gated by `retrieval_score_threshold`; `gated=False` only for threshold tuning | Section 7: refusal is gated on the per-chunk similarity score |
| Textract uses the async flow for anything multi-page; `analyze_bytes` is single-page only | Section 7: the synchronous API is capped at single-page documents |
| Textract's `ClientRequestToken` is the file hash, cut to 64 characters | A re-run of the same file reuses the job, so ingestion is idempotent |
| KB chunks go to S3 as `.txt` plus a `.metadata.json` sidecar of `metadataAttributes` | Section 7: `doc_type` and `section_path` must be filterable at query time |
| `@raises` (with `functools.wraps`) turns boto failures into `ExtractionError`, `RetrievalError`, and so on | Section 13: a custom exception hierarchy and decorators that preserve `wraps` |

## Not implemented

- The judge deployment and the multimodal photo check aren't wired.
- `chat_model()` builds its own boto client from `region_name`, so the adaptive retry config above doesn't apply to model calls.
- Confirm in the console that the guardrail has the Prompt attacks filter enabled, and that the role allows `bedrock:ApplyGuardrail`; the code only passes the guardrail's id and version.
- Clients for AgentCore Runtime, Gateway and Identity.
- `get_analysis_status` and `get_blocks` aren't wrapped by `@raises`, so a failure there surfaces as a raw `ClientError`.
