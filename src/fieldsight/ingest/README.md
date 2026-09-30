# Ingest

## Chart

```
CORPUS  (script/ingest_corpus.py, run when corpus/ changes)

corpus/sources.json --corpus_docs--> crack_corpus                         corpus/sources.py, corpus/cracking.py
                                       upload each PDF, start every async Textract job
                                       (TABLES + LAYOUT, output saved under textract/<doc_id>), wait on each
      |
chunk_chain().batch(docs)                                                  corpus/chain.py, corpus/loader.py
   TextractLoader --> layout_by_page --> split on ## headings,             corpus/layout.py, corpus/chunking.py
                      fall back to 1800 / 300 chars; tables as whole chunks;
                      section_path + stable chunk_id on every chunk        corpus/sections.py
      |
stage_chunks --> kb/corpus/<doc_id>/<chunk_id>.txt + .metadata.json        corpus/indexing.py
sync_knowledge_base --> KB ingestion job, polled until COMPLETE

(local: script/ingest_corpus_local.py reuses the saved Textract output, embeds with Titan v2,
 and writes the corpus_chunks table in pgvector instead of the KB)


PACKET  (the pieces exist; no submit command wires them yet)

artifact files --upload_artifact--> S3 packets/<sha256>/<name>             artifacts/storage.py
      |
crack (async Textract FORMS + TABLES, token = file hash)                   crack.py
      |
extract_form_fields --> {label, value, confidence, artifact, page}         artifacts/fields.py, blocks.py
      |
crack_packet --> {artifacts, fields, failures}; malformed ones skipped     artifacts/packet.py
      |
redact --> PII fields dropped, names/SSN/email/phone scrubbed, spans       artifacts/redact.py   (no caller yet)
ingestion_report --> processed, extracted, below floor, failures           artifacts/report.py   (no caller yet)
```

## Files

| File | Contains |
|---|---|
| `blocks.py` | Textract block helpers shared by both pipelines: `index_blocks`, `related`, `text_of`. |
| `crack.py` | `crack` and `finish`: start or await a Textract job and return its blocks; `wait_until_done` polls. |
| `artifacts/storage.py` | `upload_artifact`: an artifact in S3, keyed by content hash. |
| `artifacts/fields.py` | `extract_form_fields`: each filled-in form field, traced to its artifact and page. |
| `artifacts/packet.py` | `crack_artifact` and `crack_packet`: every artifact's fields, with failures recorded and skipped. |
| `artifacts/redact.py` | `redact`: removes PII from the fields and narrative and returns the removed spans. |
| `artifacts/report.py` | `ingestion_report`. |
| `normalize.py` | `normalize_chain`: the one structured-output call to a `NormalizedIncident`; each field's confidence and source artifact come from the Textract fields (`FORM_SOURCES`), never the model. |
| `submit.py` | `packet_artifacts` (skip and log unsupported files) and `ingest_packet` (crack, screen, redact, normalize, report); the screen is passed in, and `harness/run/wiring.submit` composes and saves it. |
| `corpus/sources.py` | `corpus_docs`, `letters`, and each doc's local PDF path and S3 key. |
| `corpus/cracking.py` | `crack_corpus`: all corpus Textract jobs started in parallel, then awaited. |
| `corpus/layout.py` | Layout and table blocks as page markdown, with tables kept column-aligned. |
| `corpus/sections.py` | `section_path` for a chunk, from its header or its excerpt's page range. |
| `corpus/chunking.py` | `split_corpus_doc`, `CHUNK_CHARS` / `OVERLAP_CHARS`, and `chunk_id`. |
| `corpus/loader.py` | `TextractLoader`, a LangChain document loader over the saved Textract output. |
| `corpus/chain.py` | `chunk_chain`: one doc in, its chunks out; `.batch()` runs the corpus. |
| `corpus/indexing.py` | `stage_chunks` and `sync_knowledge_base`. |

Paths are relative to `src/fieldsight/ingest/`. The shapes (`StoredArtifact`, `ExtractedField`, `CorpusDoc`, `ChunkMetadata` and others) are TypedDicts in `types/`.

## Decisions

| Decision | Why |
|---|---|
| Ingestion is a deterministic pipeline, not an agent or a graph node; it runs before the graph | Spec section 5: extraction is a deterministic pipeline plus one structured-output call |
| The async Textract flow for every document | Section 7: the synchronous API is single-page only, and `CPL-172` is 21 pages |
| Idempotent on content hash: S3 key `packets/<sha256>/<name>`, and the Textract request token is the file hash | Section 7: store by content hash, idempotent on hash |
| The corpus is cracked with TABLES + LAYOUT, packets with FORMS + TABLES | Headings and column-aligned tables drive corpus chunking; packets are forms |
| The corpus must fully succeed; a packet keeps `PARTIAL_SUCCESS` | A partial corpus breaks retrieval, but most of a packet's pages are still useful |
| Chunks split on headings, fall back to 1800 characters with 300 overlap; tables are their own chunks under the header in force | Section 7: structure-aware chunking; the `CFR-269` approach-distance tables survive with their columns |
| Chunk id = `doc_id` + the first 12 hex chars of sha256(section_path, page, text) | Section 7: stable, deterministic ids; a `CFR-269` chunk id starts with `CFR-269-` |
| Metadata (`doc_id`, `title`, `doc_type`, `section_path`, `page`, `chunk_id`) is attached at ingestion | Section 7: filterable at query time |
| Every doc is chunked before anything is written, and staging replaces a doc's whole folder | One failure leaves the data source untouched; a re-run leaves no stale chunks |
| A field's confidence is the lower of its key's and value's | A misread label is as bad as a misread value |
| Redaction by field label, plus a pattern scrub of names, SSNs, emails and phones; spans are returned, never the removed text | Section 7: deterministic PII redaction by field name that returns the removed spans |
| Malformed artifacts are logged and skipped, not fatal | Section 7: skip and log; the dossier states what failed |
| Only data from outside is validated: `sources.json` (`CORPUS_DOC`) and the metadata sent to the KB (`CHUNK_METADATA`); shapes this code builds itself are plain TypedDicts | Validating a dict we just built from known values can't catch anything |

## Not implemented

- Photograph corroboration with Bedrock's multimodal model (section 7 step 3): `submit` lists photos as not yet corroborated.
- The narrative embedding for similar-incident search: `incidents.embedding` is 1536 dimensions, but the Titan model is configured for 1024.
- `script/ingest_corpus_local.py` is broken: it imports `CorpusChunkRepository`, which `repository.py` doesn't have, and nothing reads the local pgvector table.
