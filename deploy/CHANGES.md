# Deployment changes

Changes in the code that affect a deployed piece: the ECS tool API, the AgentCore Runtime, the database, or `docker compose`. Newest first. Each entry says what changed, what it affects, and what to do before or after deploying.

The ECS task definition (`vars.AWS_TASK_DEF_ARN`) and the AgentCore Runtime's environment live in AWS, not in this repo: `deploy.yml` only swaps their image, and `script/update_agent_runtime.py` sends every other Runtime setting back unchanged. So an environment variable they need has to be added in AWS.

## 2026-09-30: `incidents.embedding` is 1024 dimensions (migration `b1d4f6a8c2e0`)

The column was `vector(1536)`, but Titan Text Embeddings v2 is configured for 1024 (`aws/clients.EMBEDDING_DIMENSIONS`), and 1536 isn't a size it produces.

- **Affects:** the database. The migration clears any existing embeddings, because a vector can't be cast to another size. Nothing writes them yet (seed and `submit` leave them empty), and they're rebuilt from the narrative.
- **Do:** `alembic upgrade head` against RDS; the same run covers the migrations below.

## 2026-09-30: service entry points moved out of `interfaces/`

`interfaces/` now holds only what an analyst uses: the CLI (`cli.py`, `requests.py`, `responses.py`). The processes other hosts call moved to `services/`:

| Before | After |
|---|---|
| `fieldsight.interfaces.agent_runtime` | `fieldsight.services.agent_runtime` |
| `fieldsight.interfaces.tool_api` | `fieldsight.services.tool_api` |
| `fieldsight.interfaces.tool_runtime:create_production_app` | `fieldsight.services.tool_api:create_production_app` (the 19-line `tool_runtime.py` merged into `tool_api.py`) |

- **Affects:** both images. `deploy/ecs/Dockerfile` and `deploy/runtime/Dockerfile` already run the new module paths, and `docker compose` builds from the same Dockerfiles.
- **Do:** nothing beyond the normal deploy, which rebuilds both images. The task definition and the Runtime config name an image, never a module.
- **Rollback:** the previous image digests still run the old paths, since each image carries its own code.

## 2026-09-30: `run_records.dossier` column (migration `a7c3e9d1f2b4`)

`analyze` and `ask` now save the dossier they showed, so `fieldsight dossier` and `fieldsight sources` can read it later.

- **Affects:** the database. Every run-record insert from new code writes the column.
- **Do:** run `alembic upgrade head` against RDS **before** deploying code from this change. `deploy.yml` doesn't run migrations; locally, `docker compose up` runs `migrate` first. Without the column, every `analyze` and `ask` turn fails when it saves its run record.

## 2026-09-29: `run_records.reviewer_verdicts` column (GF-53, migration `6abb4ad152bf`)

- **Affects:** the database, the same way as the entry above.
- **Do:** `alembic upgrade head` against RDS before deploying GF-53 code; one upgrade covers both migrations.

## 2026-09-29: model price settings required (GF-53)

`config.py` now requires `FIELDSIGHT_REASONING_PRICE_IN`, `FIELDSIGHT_REASONING_PRICE_OUT`, `FIELDSIGHT_FAST_PRICE_IN` and `FIELDSIGHT_FAST_PRICE_OUT` (USD per million tokens; see `.env.example`). Every process that imports `fieldsight` exits with a `KeyError` without them.

- **Fixed in the repo:** `.github/workflows/ci.yml` and `docker-compose.yml` (defaults from `.env.example`).
- **Do:** add all four to the ECS task definition's container environment and to the AgentCore Runtime's environment **before** deploying any image built from GF-53 or later. Otherwise the ECS tasks fail their health check and the Runtime never reaches `READY`.
