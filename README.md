# FieldSight — Incident Intelligence Copilot

A multi-agent CLI that reads workplace incident packets (a scanned OSHA Form 301, photographs, supporting notes), grounds every finding in a corpus of real public-domain OSHA regulatory text, applies Part 1904 thresholds with deterministic rules, and drafts a cited dossier for a human analyst to approve.

> **The system describes; the analyst determines.** FieldSight presents rule outcomes and the evidence behind them. It never states a legal conclusion on anyone's behalf. Every dossier is AI-generated and must be verified.
>
> **Synthetic data.** The client (Meridian Utilities) and every incident packet are fictional. The corpus is real OSHA and federal material, excerpted and frozen at its retrieval date. It is a training artifact, not a current or authoritative source.

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Using the CLI](#using-the-cli)
- [Configuration](#configuration)
- [Testing and evaluation](#testing-and-evaluation)
- [Operations: deploy, roll back, tear down](#operations-deploy-roll-back-tear-down)
- [Security model](#security-model)
- [Documentation](#documentation)
- [Team process](#team-process)

---

## What it does

1. **Cracks** a packet into a typed, normalized record with per-field confidence (Amazon Textract, async flow; photographs checked against the narrative by a multimodal model).
2. **Plans** which workers the incident needs and dispatches them (a Coordinator on a LangGraph `StateGraph`).
3. **Retrieves** grounding evidence from the regulatory corpus (Bedrock Knowledge Base on OpenSearch Serverless).
4. **Computes** recordability, reporting clocks and 300-Log classification with five pure-Python rules. Thresholds never come from a model.
5. **Produces** a cited dossier with a proposed classification, reporting determination and (when energized equipment is involved) a hazard control.
6. **Escalates** to a human review queue whenever a named, deterministic trigger fires.

### The rules engine

| Rule | Decides | Source |
|---|---|---|
| R1 | Recordable / not recordable | 29 CFR 1904.4, 1904.5, 1904.7(b)(1) |
| R2 | Reporting clock: fatality 8 h; in-patient hospitalization, amputation, loss of eye 24 h | 1904.39 (incl. the (b)(10) observation-only and (b)(11) amputation exclusions) |
| R3 | Medical treatment beyond first aid | 1904.7(b)(5)(ii) closed list |
| R4 | 300-Log column G/H/I/J, most severe wins, 180-day cap | 1904.7(b)(3), 1904.29(b)(3), Form 301 |
| R5 | Confidence floor: any field below 0.60 goes to a human | Pipeline parameter |

Each rule returns the outcome, the rule id, every source it was decided from and the inputs it used. A missing input returns `insufficient_data` naming the field, never a default.

---

## Architecture

Orchestrator/worker topology built as a LangGraph `StateGraph`, with typed state, conditional edges and a Postgres checkpointer.

```
                 ┌──────────────────────────────────────────────────┐
                 ▼                                                  │
          COORDINATOR ── conditional ──▶ HAZARD CONTROL ──┐         │
               │                                          │         │
               ├── parallel ──▶ RECORDABILITY ────────────┤         │
               └── parallel ──▶ REPORTABILITY ────────────┤         │
                                                          ▼         │
                                                      REVIEWER ─ rejected (bounded)
                                                          │
                                                          ▼ approved / out of iterations
                                                  ELIGIBILITY CHECK
                                                  (output guardrails + escalation triggers)
```

| Participant | Question it answers | Tools |
|---|---|---|
| **Coordinator** | Which workers does this incident need? Returns a typed `DispatchPlan`; plain Python routes on it. | none |
| **Recordability Worker** | Recordable, and which 300-Log column? (R1, R3, R4) | `search_knowledge_base`, `get_incident_extraction`, `evaluate_rule`, `propose_classification` |
| **Reportability Worker** | Reportable, on what clock, does an exclusion apply? (R2) | `search_knowledge_base`, `get_incident_extraction`, `evaluate_rule`, `propose_reporting_determination` |
| **Hazard Control Worker** *(conditional)* | What control does 1910.269(l) require, and is there precedent? Only dispatched for energized equipment. | `search_knowledge_base`, `find_similar_incidents`, `propose_hazard_control` |
| **Reviewer** | Is every claim grounded, cited, attributed, and free of determination-shaped language? Sees only typed proposals, on its own checkpointer thread. | `search_knowledge_base` |

Key properties:

- **Workers loop on their own tools** until they stop requesting them, capped by `max_specialist_tool_rounds`.
- **Recordability and Reportability run concurrently**; the Reviewer waits for every dispatched leg.
- **A Reviewer rejection narrows the goal and re-dispatches** through a bounded cycle (`max_reviewer_iterations`), with `max_graph_recursion_depth` as an independent hard cap.
- **The model chooses what, never whose.** No tool accepts an incident id from the model; the subject is injected from the session.
- **No agent tool writes.** `propose_*` tools validate and return; the only write happens in the harness after a recorded human approval.

Every turn (including `ask`) runs the full harness: input validation → Bedrock Guardrails Prompt Attacks filter → readiness gate → workflow → output guardrails → escalation, and persists one run record. See [`src/fieldsight/graph/README.md`](src/fieldsight/graph/README.md) for the node-by-node chart and design decisions.

### AWS services

| Service | Job in FieldSight |
|---|---|
| Amazon Bedrock | Reasoning, fast, embedding, multimodal and judge models via the Converse API |
| Bedrock Knowledge Bases + OpenSearch Serverless | The corpus index, filterable on `doc_type` and `section_path` |
| Amazon Textract | Async `StartDocumentAnalysis` for corpus PDFs and packet artifacts (Forms + Tables) |
| Bedrock Guardrails | Content filters and the Prompt Attacks filter on analyst input and cracked artifact text |
| RDS/Aurora PostgreSQL + `pgvector` | Incidents, run records, review queue, sessions, checkpoints, similar-incident search |
| Amazon ECR | Image registry for both services; deploy by digest |
| Bedrock AgentCore (Runtime, Gateway, Identity) | Runtime hosts the LangGraph workflow; Gateway exposes the read tools as MCP and routes two of them to ECS |
| Amazon ECS (Fargate) + ALB | Hosts the Flask tool API (`get_incident_extraction`, `find_similar_incidents`) |

> **Model note:** the team's AWS account cannot invoke Claude on Bedrock, so with instructor approval the reasoning and fast tiers use on-demand Amazon Nova models (see `.env.example`). The judge runs on a separate model ID.

---

## Repository layout

```
corpus/                 Six excerpted OSHA/federal PDFs, plain-text copies, MANIFEST.md (provenance, distractors, out-of-corpus list)
packets/                Four incident packets (inc-0411 … inc-0414) built on the real OSHA Form 301
src/fieldsight/
  interfaces/           CLI entry point (cli.py), request/response shaping, remote Runtime client
  graph/                LangGraph StateGraph: Coordinator, workers, Reviewer, eligibility check
  harness/              Turn lifecycle, guardrails, bounds, escalation triggers, metering, idempotency
  rules/                R1–R5 and proposal review (pure Python, no I/O)
  retrieval/            The one module that owns retrieval, grounding and citation references
  ingest/               Packet ingestion (store → crack → corroborate → redact → normalize) and corpus chunking
  aws/                  The one module that builds boto3/Bedrock clients (Textract, KB, Guardrails, S3, Gateway)
  repository/           The one module that owns every SQL query (parameterized, Pydantic in/out)
  tools/                Agent tools and the tool service
  security/             Redaction, entitlements, STS caller-proof identity
  services/             Flask tool API (ECS) and the AgentCore Runtime entry point
  schemas/, types/      Pydantic models shared across layers
  evaluation/           Golden-set loader, deterministic (CI) tier, live tier, judge
migrations/             Alembic versioned migrations
evals/                  golden/ (15 cases), escalation/ (paired trigger cases), fixtures/injection/, results/
script/                 Corpus ingestion, threshold/bounds tuning, eval runner, Gateway and Runtime setup
deploy/                 Dockerfiles (ecs/, runtime/, migrate/), Gateway/IAM notes, AWS Budget
docs/                   architecture.md, evaluation-report.md, process/ (sprints, retros, DoD, board snapshots)
tests/                  Unit and integration tests (pytest)
```

---

## Getting started

### Prerequisites

- Python 3.11+ (CI runs 3.13)
- Docker and Docker Compose
- An AWS identity you reach by **assuming an IAM role** (SSO or `aws sts assume-role`). No long-lived access keys.
- Bedrock model access approved for the reasoning, fast, embedding, multimodal and judge models in your region

### 1. Install

```bash
git clone https://github.com/FieldSight-G3/fieldsight-cli.git
cd fieldsight-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

### 2. Configure

```bash
cp .env.example .env
```

Fill in `.env` (see [Configuration](#configuration)). `config.py` loads it with `python-dotenv` and validates every setting at startup; a missing or invalid value fails immediately.

For local work point the database at the compose Postgres, which is published on host port **5434**:

```
FIELDSIGHT_DATABASE_URL=postgresql://fieldsight:fieldsight_dev@localhost:5434/fieldsight
```

### 3. Start local services

```bash
docker compose up -d
```

This starts:

| Service | Port | What it is |
|---|---|---|
| `postgres` | 5434 | `pgvector/pgvector:pg16` |
| `migrate` | — | Runs `alembic upgrade head` once, then exits |
| `tool-api` | 8080 | Local stand-in for the ECS Flask tool API (`/health/live`, `/health/ready`) |
| `agent-runtime` | 8081 | Local stand-in for the AgentCore Runtime (`/ping`, `POST /invocations`) |

Every setting has a placeholder default in `docker-compose.yml`, so `docker compose up` succeeds on a fresh clone. Real model calls still need AWS credentials and real IDs in `.env`.

### 4. Seed analysts, grants and historical incidents

```bash
python -m fieldsight.seed
```

Seeds three analysts (Alice, Bob, Carol) across three establishments (North, Central, South Substation), their establishment grants, and 12+ historical incidents with narratives and outcomes. Narratives are embedded with the Bedrock embedding model for `find_similar_incidents`, so this step needs AWS access. `python script/embed_incidents.py` backfills any embeddings that failed.

### 5. Enroll your IAM role as an analyst

The CLI identifies you by your **assumed IAM role**, never by a flag. Add your role ARN to `FIELDSIGHT_ANALYST_ROLE_ARNS` and map it to an analyst row:

```sql
UPDATE analysts SET iam_role_arn = 'arn:aws:iam::<account>:role/<YourAnalystRole>'
WHERE email = 'alice@example.invalid';
```

### 6. Ingest the corpus (once, or when `corpus/` changes)

```bash
python script/ingest_corpus.py          # Textract async → structure-aware chunking → stage to S3 → sync the KB
```

Part 1904 is chunked one paragraph per chunk; other documents use 1,800-char chunks with 300 overlap, and the `CFR-269` approach-distance tables are split by row under their header. The KB data source uses chunking `NONE` so Bedrock keeps these chunks intact. `script/ingest_corpus_local.py` loads the same chunks into local pgvector instead.

---

## Using the CLI

```bash
fieldsight submit ./packets/inc-0412             # crack the packet inline (~60 s) → prints the incident id
fieldsight analyze <incident-id>                 # run the workflow (one turn)
fieldsight dossier <incident-id>                 # render the dossier with numbered citations
fieldsight ask <incident-id> "why column H?"     # follow-up turn on the same session
fieldsight sources <incident-id> --ref 2         # print the chunk behind citation [2]
fieldsight trace <incident-id>                   # the plan, dispatches, tool loops, rule invocations, Reviewer verdicts
fieldsight queue                                 # escalated dossiers and the triggers that fired
fieldsight review <incident-id>                  # show the decision card
fieldsight review <incident-id> --action approve
fieldsight review <incident-id> --action edit_then_approve --narrative "..." --note "..." --repoint 2=<chunk_id>
fieldsight review <incident-id> --action reject --reason "..."
```

- Every command starts cold and reads state from Postgres; an escalated dossier is a database row, not a suspended process.
- Refusals and entitlement denials print as answers, with the reason and escalation path.
- **Edit-then-approve changes the narrative, never the determination.** Rule outcomes, computed dates and cited documents cannot be edited; a reviewer who disagrees rejects.
- The reviewer must be a different analyst from the submitter.
- Logs go to `~/.fieldsight/cli.log` (override with `FIELDSIGHT_CLI_LOG`) so the terminal shows only results.
- Set `FIELDSIGHT_RUNTIME_ID` to send `analyze` and `ask` turns to the deployed AgentCore Runtime instead of running in-process.

### The packets

| Packet | Folder | Exercises | Workers dispatched |
|---|---|---|---|
| P1 | `inc-0411` | Happy path, treatment beyond first aid | Recordability |
| P2 | `inc-0412` | In-patient admission (24 h clock), near the 180-day cap, energized equipment | All three |
| P3 | `inc-0413` | Illegible date of injury, below the 0.60 floor | None: readiness gate routes to the analyst |
| P4 | `inc-0414` | Observation-only stay (recordable, not reportable under 1904.39(b)(10)); malformed artifact; contradicting photo | Recordability + Reportability, with a Reviewer rejection and narrowed re-dispatch |

---

## Configuration

All settings are typed in `src/fieldsight/config.py`. Required unless noted.

| Variable | Purpose |
|---|---|
| `FIELDSIGHT_ENVIRONMENT` | `local`, `ci`, `dev`, `prod` … |
| `FIELDSIGHT_AWS_REGION` | e.g. `us-east-1` |
| `FIELDSIGHT_ANALYST_ROLE_ARNS` | Comma-separated enrolled analyst role ARNs |
| `FIELDSIGHT_BEDROCK_MODEL_ID` | Reasoning tier (workers, Reviewer) |
| `FIELDSIGHT_BEDROCK_FAST_MODEL_ID` | Fast tier (Coordinator plan, readiness classifier) |
| `FIELDSIGHT_BEDROCK_JUDGE_MODEL_ID` | Separate judge model for evaluators |
| `FIELDSIGHT_BEDROCK_MULTIMODAL_MODEL_ID` | *Optional.* Photo corroboration; defaults to the reasoning model |
| `FIELDSIGHT_BEDROCK_EMBEDDING_MODEL_ID` | Embedding model (Titan v2) |
| `FIELDSIGHT_BEDROCK_KB_ID`, `FIELDSIGHT_BEDROCK_KB_DATA_SOURCE_ID` | Knowledge Base and its data source |
| `FIELDSIGHT_BEDROCK_GUARDRAIL_ID`, `FIELDSIGHT_BEDROCK_GUARDRAIL_VERSION` | Bedrock Guardrail |
| `FIELDSIGHT_PACKET_BUCKET` | S3 bucket for content-hashed artifacts and Textract output |
| `FIELDSIGHT_DATABASE_URL` | Postgres URL |
| `FIELDSIGHT_DATABASE_IAM_AUTH` | *Optional*, default `false`. `true` mints an IAM auth token per connection (deployed path) |
| `FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD` | Similarity score below which retrieval refuses (tuned value in `docs/architecture.md`) |
| `FIELDSIGHT_RETRIEVAL_MAX_CHUNKS` | Chunks per search |
| `FIELDSIGHT_GATEWAY_API_KEY` | Gateway client setting |
| `FIELDSIGHT_ALLOW_DEV_IDENTITY` | `false` everywhere except CI test fixtures |
| `FIELDSIGHT_REASONING_PRICE_IN/OUT`, `FIELDSIGHT_FAST_PRICE_IN/OUT` | USD per million tokens, used to compute measured cost |
| `FIELDSIGHT_MULTIMODAL_PRICE_IN/OUT` | *Optional.* Pricing for a separate multimodal model |
| `FIELDSIGHT_RUNTIME_ID` | *Optional.* Route CLI turns to the deployed AgentCore Runtime |

### Bounds

Defaults live in `src/fieldsight/harness/bounds.py`; override any of them per environment with `FIELDSIGHT_BOUNDS_<FIELD>` (e.g. `FIELDSIGHT_BOUNDS_SESSION_COST_CEILING_USD=3.00`).

| Bound | Default |
|---|---|
| Max tokens per call (coordinator / workers / reviewer) | 4,096 / 6,144 / 4,096 |
| Max tool invocations per turn | 54 |
| Max specialist tool rounds | 10 |
| Max reviewer iterations | 2 |
| Max graph recursion depth | 32 |
| Max retrieved chunks / tokens per turn | 113 / 25,767 |
| Per-turn wall clock | 300 s |
| Session cost ceiling (accumulates across `ask` turns) | $5.00 |

Budgets are check-and-stop: usage accumulates after each call, and the next leg won't start once a ceiling is spent. Near-boundary escalation margins (24 h, 30 days, 180 days, 0.60) and their reasoning are recorded in `docs/architecture.md`.

---

## Testing and evaluation

### Tests

```bash
ruff check . --extend-exclude corpus
pytest -v
```

Tests need a migrated Postgres (`docker compose up -d` locally). They cover every rule at its boundaries (exactly 30 days, 24 hours, 180 days, 0.60, the observation-only and amputation exclusions), guardrails, bounds, entitlements, idempotency-key canonicalization, redaction, injection resistance, the Coordinator and specialist loops, the review flow, and **session isolation** (`tests/test_session_isolation.py`, two incidents concurrently).

### Golden set

`evals/golden/` holds 15 machine-readable cases (single-document, multi-hop, threshold pairs, incident-backed, out-of-corpus refusals, a determination probe, four adversarial cases and a near-miss). `evals/escalation/` holds paired cases that fire and don't fire each escalation trigger.

```bash
python script/run_evals.py --tier ci                    # deterministic, no AWS; exits 1 on any failure (gates CI)
python script/run_evals.py --tier live --label final    # every case through the harness, plus the judge
python script/run_evals.py --tier live --cases single-01 ooc-01 --label smoke
python script/tune_threshold.py                         # re-derive the refusal threshold from the golden set
```

The live tier writes run records to the database `FIELDSIGHT_DATABASE_URL` points at and refuses a remote database unless `--allow-remote` is passed. Results land in `evals/results/<UTC-time>-<label>/` (`results.json` + `summary.md`). Analysis, both judged runs and their delta, refusal precision/recall, cost and latency are in [`docs/evaluation-report.md`](docs/evaluation-report.md).

### CI

`.github/workflows/ci.yml` runs on every pull request to `main`: **ruff** → **migrations + deterministic golden tier + unit tests** (against a pgvector service container) → **gitleaks** secret scan.

---

## Operations: deploy, roll back, tear down

Two images, both multi-stage, non-root, built on a digest-pinned base image and deployed **by digest, never by tag**:

| Image | Dockerfile | ECR repository | Runs on |
|---|---|---|---|
| Tool API (Flask + gunicorn) | `deploy/ecs/Dockerfile` | `fieldsightosha` | ECS Fargate behind an internal ALB, min 2 tasks |
| Agent workflow (LangGraph) | `deploy/runtime/Dockerfile` | `fieldsight-runtime` | AgentCore Runtime (linux/arm64) |

### One-time setup

- AWS Budget with alert thresholds: `deploy/budget/budget.json`, `deploy/budget/notifications.json`.
- GitHub OIDC deploy role; set repository variables `ECS_ROLE`, `AWS_TASK_DEF_ARN` and `AGENT_RUNTIME_ID`. No AWS keys are stored as secrets.
- ECR repositories with scan-on-push enabled.
- Gateway and IAM setup: [`deploy/ecs/README.md`](deploy/ecs/README.md), [`deploy/ecs/GATEWAY-IAM.md`](deploy/ecs/GATEWAY-IAM.md). Runtime setup: [`deploy/runtime/README.md`](deploy/runtime/README.md).

### Deploy

Merging to `main` (or running the workflow manually) triggers `.github/workflows/deploy.yml`:

1. Assume the deploy role via GitHub OIDC.
2. Build and push the tool API image (amd64); capture its `@sha256` digest.
3. Build and push the Runtime image (arm64, Buildx); capture its digest.
4. Render the ECS task definition with the digest and deploy, waiting for service stability.
5. Run `script/update_agent_runtime.py`, which changes only the Runtime's image and waits for `READY`.

Apply database migrations against the deployed database with the `deploy/migrate` image or `alembic upgrade head` from a host with access.

### Roll back

**ECS tool API:** redeploy the previous task-definition revision (it pins the previous digest):

```bash
aws ecs update-service --cluster fieldsight-cluster --service fieldsight-tools \
  --task-definition <family>:<previous-revision>
aws ecs wait services-stable --cluster fieldsight-cluster --services fieldsight-tools
```

**AgentCore Runtime:** point it back at the previous digest (ECR keeps it):

```bash
python script/update_agent_runtime.py --runtime-id <id> \
  --image <registry>/fieldsight-runtime@sha256:<previous> --region us-east-1
```

**Database:** `alembic downgrade -1` (only for a migration with no data you need to keep).

### Tear down

Remove in dependency order, from consumers to backing services:

```bash
# 1. ECS tool API
aws ecs update-service --cluster fieldsight-cluster --service fieldsight-tools --desired-count 0
aws ecs delete-service --cluster fieldsight-cluster --service fieldsight-tools --force
aws ecs delete-cluster --cluster fieldsight-cluster
#    then delete the ALB, its target group and listener, the VPC Link and API Gateway REST API

# 2. AgentCore: delete the Gateway target, the Gateway, then the Runtime
aws bedrock-agentcore-control delete-gateway-target --gateway-identifier <gw-id> --target-id <target-id>
aws bedrock-agentcore-control delete-gateway --gateway-identifier <gw-id>
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id <runtime-id>

# 3. Images
aws ecr delete-repository --repository-name fieldsightosha --force
aws ecr delete-repository --repository-name fieldsight-runtime --force
```

Then delete the Knowledge Base, its OpenSearch Serverless collection, the Guardrail, the packet S3 bucket and the RDS/Aurora instance if the environment is being retired. Locally: `docker compose down -v`.

---

## Security model

- **IAM roles only.** An assumed role locally, an execution role on the Runtime, Gateway, ECS task and CI. No long-lived keys anywhere.
- **Identity comes from a proof, never an argument.** The caller signs a 60-second, session-bound STS caller proof with their own assumed role; the Runtime and tool API verify it against STS and map it to an enrolled analyst.
- **Entitlements are checked inside the tool on every call.** An analyst without a grant over the incident's establishment gets a structured `not_entitled` denial, never an empty result.
- **PII is redacted** (employee name, address, date of birth) by one redactor before any text reaches a model, a log or the index.
- **Indirect injection is tested.** The poisoned fixture lives in `evals/fixtures/injection/`, never in `packets/`, and is stopped by the Prompt Attacks filter and the output guardrails.
- **Run records are append-only.** A correction is a new record referencing the original.
- **Two-person approval.** The reviewer must differ from the submitter, enforced in code and by a database check.

Accepted risks (Gateway identity posture, approver split) are documented in [`docs/architecture.md`](docs/architecture.md).

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Topology, decisions table (bounds, margins, model tiers, pinned versions), degraded modes, cuts, threat and responsible-AI note |
| [`docs/evaluation-report.md`](docs/evaluation-report.md) | Golden set results, threshold method, judged runs and delta, adversarial cases, measured cost and latency |
| [`src/fieldsight/graph/README.md`](src/fieldsight/graph/README.md) | Graph chart, files and design decisions |
| [`corpus/MANIFEST.md`](corpus/MANIFEST.md) | Source provenance, cross-references, retrieval distractors, out-of-corpus and near-miss topics |
| [`deploy/`](deploy/) | Gateway, IAM and Runtime setup notes |
| [`FieldSight-Project2-Requirements.md`](FieldSight-Project2-Requirements.md) | The full project specification |

### Pinned versions

`boto3==1.43.96` · `langgraph==1.2.11` · `langgraph-checkpoint-postgres==3.1.2` · `langchain-aws==1.7.8` · `langchain-core==1.6.3` · `pydantic==2.13.5` · `pydantic-settings==2.15.0` · `Flask==3.1.2` · `psycopg==3.3.6` · `alembic==1.20.0` · `pgvector==0.5.0` (full list in `pyproject.toml` and `uv.lock`).

---

## Team process

Three one-week sprints with a Jira board, feature branches, reviewed pull requests (no direct pushes to `main`) and a shared definition of done. Sprint goals, reviews, retros, board snapshots and the working agreement are in [`docs/process/`](docs/process/).

**Definition of done:** a story meets its acceptance criteria, has passing tests (including boundary cases), is `ruff` clean, has updated docs, and its PR has been reviewed by a teammate and merged to `main`.

---

*FieldSight is a training project. It is not safety, legal or compliance advice.*
