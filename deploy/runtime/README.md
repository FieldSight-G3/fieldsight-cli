# FieldSight AgentCore Runtime

The second image (requirements §15): the LangGraph workflow served by `fieldsight.services.agent_runtime` on `:8080` (`POST /invocations`, `GET /ping`). Each invocation is one turn through `harness/run/wiring.turn()` — the same composition the CLI uses — as the analyst named by the caller proof.

## Invoking it

Send `{"command": "analyze" | "ask", "incident_id": "...", "question": "...", "caller_proof": "..."}` with a runtime session id. `caller_proof` is the 60-second STS proof from `security/iam_caller_proof.issue_proof(session_id, region)`, signed with the **analyst's own** assumed role and bound to that session id. The runtime verifies it against regional STS, requires an enrolled analyst role (`FIELDSIGHT_ANALYST_ROLE_ARNS`), checks the analyst's establishment grant, then runs the turn. Every denial is a structured `{"ok": false, "error": {"code": ...}}`. The proof is never logged or returned.

## One-time AWS setup

1. **ECR repository** `fieldsight-runtime` (the workflow's `RUNTIME_ECR_REPOSITORY`) with **scan on push** enabled.
2. **Execution role** for the runtime: Bedrock model and guardrail invoke, Knowledge Base retrieve, database access, and `sts:GetCallerIdentity` egress for proof checks. Never an analyst role.
3. **Create the runtime** from a container image built with `--platform linux/arm64` (AgentCore Runtime runs arm64), with the `FIELDSIGHT_*` environment variables `config.py` requires, and outbound HTTPS to regional STS.
4. Put its id in the GitHub repository variable **`AGENT_RUNTIME_ID`**.
5. The GitHub OIDC deploy role (`vars.ECS_ROLE`) additionally needs: ECR push to `fieldsight-runtime`, `bedrock-agentcore:GetAgentRuntime` and `bedrock-agentcore:UpdateAgentRuntime` on this runtime, and `iam:PassRole` on its execution role.

## Deploying

`.github/workflows/deploy.yml` builds the arm64 image with Buildx, pushes it, and runs `script/update_agent_runtime.py` with the pushed **digest**. The script reads the runtime's current settings, changes only the image, sends everything else back (UpdateAgentRuntime can reset settings it isn't sent), and waits for `READY`.

**Roll back:** rerun the script with the previous image digest (ECR keeps it), e.g.

```
python script/update_agent_runtime.py --runtime-id <id> --image <registry>/fieldsight-runtime@sha256:<previous> --region us-east-1
```

## Locally

`docker compose up agent-runtime` serves it on `http://localhost:8081` (native architecture is fine locally). `/ping` works without AWS; invocations need AWS credentials for Bedrock and STS.
