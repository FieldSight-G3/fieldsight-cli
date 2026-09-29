# IAM Gateway option, matching LGExpenseDemo

The demo's `app/LGExpenseCopilot/gateway.py` uses SigV4 to connect its agent to an `AWS_IAM` AgentCore MCP Gateway and loads its tools with `langchain-mcp-adapters`. FieldSight's new `src/fieldsight/interfaces/gateway_client.py` uses the same connection pattern. `script/configure_gateway_iam.py` previews an IAM Gateway; it does not create targets. No Cognito token is needed to invoke an IAM Gateway. The Runtime task role or local AWS profile needs `bedrock-agentcore:InvokeGateway` scoped to the actual Gateway ARN.

Install `deploy/ecs/gateway-client-requirements.txt` in the **agent's Runtime environment**, in addition to the project package. From the trusted dispatcher, after obtaining the analyst's IAM role proof, use `async with available_gateway_tools(thread_id=context.session_id, caller_proof=proof) as toolset:`, pass `toolset.tools` into that graph's tool list, and tell the analyst about anything in `toolset.unavailable`; an unreachable Gateway or ECS API disables only those tools. The proof must originate from the analyst's assumed role, not the Runtime execution role. Set `AWS_REGION` and `FIELDSIGHT_GATEWAY_URL` (the complete AWS Gateway HTTPS URL ending in `/mcp`). `AGENTCORE_GATEWAY_FIELDSIGHTTOOLS_URL` is also accepted. The thread ID must come from the dispatcher session; the model must not choose it. See `GATEWAY-ANALYST-HANDOFF.md` for the IAM role setup and proof smoke test.

**Identity binding (wired):** An API Gateway stage target signed with `GATEWAY_IAM_ROLE` reaches the ECS API as the Gateway role, not the original IAM caller, so the analyst is identified by the forwarded, thread-bound STS caller proof instead. `tool_runtime.create_production_app()` verifies it with `iam_caller_proof.caller_resolver`, and `GatewayReadStore` rechecks the analyst's session and establishment grant on every call. The demo's target is a web search connector, so it has no equivalent of this per-call grant check.

Local preview:

```powershell
python script/configure_gateway_iam.py --gateway-role-arn arn:aws:iam::<account-id>:role/<gateway-role> --region <region>
python -m compileall -q src/fieldsight/interfaces/gateway_client.py script/configure_gateway_iam.py
```

The former Cognito/JWT Gateway configuration, token forwarding interceptor, and token resolver have been removed. The repository module has not been modified.
