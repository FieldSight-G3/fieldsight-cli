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
| max tool invocations per turn | | calls | |
| max graph recursion depth | | steps | |
| max reviewer iterations | | iterations | |
| max retrieved chunks / tokens | | | |
| per-turn wall clock / per-call HTTP timeout | | s | |
| session cost ceiling | | USD | |
| near-boundary margin — 24h clock | | hours | |
| near-boundary margin — 30-day fatality window | | days | |
| near-boundary margin — 180-day cap | | days | |
| near-boundary margin — 0.60 floor | | confidence (absolute) | |
| similarity refusal threshold | | score | see evaluation report |
| chunk size / overlap | | tokens | |
| boundary inclusivity (24h, 30 days) | | | |
| day-count convention (is return day counted?) | | | |
| model tier per agent | | | |
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
