# FieldSight — Architecture (§16.2)

A reference document, not an essay. Fill every section.

## Topology
- Orchestrator/worker as a LangGraph StateGraph (diagram).
- Why orchestrator/worker: (one line)
- Why not sequential: (one line)
- Why not fully concurrent: (one line)

## Decisions table
| Decision | Value | Unit | Reasoning |
|---|---|---|---|
| max tokens per call — coordinator / each worker / reviewer | | tokens | |
| max tool invocations per turn | 10 model calls per specialist (`MAX_SPECIALIST_TOOL_ROUNDS`) | rounds | Hard cap independent of the model stopping |
| max graph recursion depth | | steps | |
| max reviewer iterations | | iterations | |
| max retrieved chunks / tokens | `RETRIEVAL_MAX_CHUNKS` per search, max 3 hops | chunks | Bounds context size |
| per-turn wall clock / per-call HTTP timeout | 300 (`max_turn_wall_clock_seconds`) / 5 connect, 30 read, 4 attempts | s | Measured: a turn with one Reviewer rejection and re-dispatch took 110–170 s (worker, Reviewer, worker again, Reviewer again), so 120 cut it off before the second verdict; 300 leaves room for that cycle on a slow Bedrock day. Adaptive retry absorbs throttling |
| session cost ceiling | | USD | |
| near-boundary margin — 24h clock | 1.0 (`reporting_24h_margin_hours`) | hours | Measured on incident → in-patient admission, amputation or loss of eye. Both timestamps come from packet text, often rounded to the hour, so a one-hour error can decide whether a 1904.39 report is due; escalates at 23–25 h inclusive |
| near-boundary margin — 30-day fatality window | 1.0 (`fatality_30d_margin_days`) | days | Measured on incident → death. Dates are often recorded without a time or time zone, so ±1 day covers that imprecision; escalates at 29–31 days inclusive |
| near-boundary margin — 180-day cap | 1 (`log_180d_margin_days`) | days | Measured on days away + restricted days for recordable cases. Whole-day counts, and the day-count convention (is the return day counted?) can move the total by one; escalates at 179–181 days inclusive |
| near-boundary margin — 0.60 floor | 0.02 (`confidence_margin_absolute`) | confidence (absolute) | Measured on the extracted field whose confidence is closest to 0.60; escalates at 0.58–0.62 inclusive. A starting value, not yet tuned against extraction data |
| similarity refusal threshold | TBD (`script/tune_threshold.py`) | score | see evaluation report |
| chunk size / overlap | 1800 / 300 | chars | ~One provision per chunk; tables kept whole |
| boundary inclusivity (24h, 30 days) | | | |
| day-count convention (is return day counted?) | | | |
| model tier per agent | retrieval, recordability, reportability: standard, temp 0 | | Citation accuracy over speed |
| judge model + version | | | |
| pinned versions: python, boto3, langgraph, langgraph-checkpoint-postgres, langchain-aws, pydantic, pydantic-settings, bedrock-agentcore, flask | | | |

## Degraded modes
| Failure | Behaviour | What the analyst sees |
|---|---|---|
| Bedrock timeout / 5xx / throttling | | |
| Textract fails on an artifact | | |
| Retrieval unavailable | | |
| Nothing above threshold | | |
| insufficient_data | | |
| Structured output fails validation | | |
| Gateway / ECS API unreachable | | |
| Write fails after approval | | |
| Cost or token ceiling breached | | |

## What we cut and why

## Threat and responsible-AI note (one page)
- Trust boundaries, each with a mitigation or an explicit accepted risk
  (analyst input, packet artifacts, corpus, model output, Gateway, ECS API, DB, CI/CD).
- Accepted risks — name them, incl. the two-person approver split and the Gateway identity posture.
- Intended use / out-of-scope use.
- Cost to the analyst of each failure mode.

### Gateway identity posture (accepted risk)
- **Boundary:** agent → AgentCore Gateway → API Gateway (IAM) → internal ALB → ECS tool API.
- **Mitigation:** the Gateway uses AWS IAM (SigV4) inbound auth, so an unsigned or unauthorized principal is rejected at the Gateway. The analyst is identified separately by a 60-second, thread-bound STS `GetCallerIdentity` proof that the dispatcher signs with the analyst's own assumed role. The ECS API verifies it against regional STS, requires an enrolled analyst role, maps it to the analyst, and rechecks the bound session and establishment grant on every call (structured `not_entitled` denial, never empty results).
- **Accepted risk:** the Gateway authenticates the AWS principal, not the analyst. Analyst identity is verified at the ECS API, not rejected at the Gateway, and the target reaches ECS as the Gateway's service role. A leaked proof is replayable for its 60-second life on its bound thread, so proofs are kept out of logs, checkpoints and Postgres. We chose IAM over a JWT authorizer because no long-lived secrets are allowed and every analyst already holds a distinct IAM role.

### Two-person approver split (accepted risk)
- **Mitigation:** the reviewer must differ from the submitting analyst, enforced in `submit_review` and by the `ck_review_queue_separate_reviewer` database check. The reviewer's establishment grant is checked on every decision, the reviewer's identity comes from the verified session (never an argument), and a decision is recorded once (conditional update).
- **Accepted risk:** the split is between analyst records. One person who can assume two enrolled analyst roles could approve their own dossier, so each analyst role's trust policy must admit only that analyst.
