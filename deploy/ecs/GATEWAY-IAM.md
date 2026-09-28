# IAM Gateway option, matching LGExpenseDemo

The demo's `app/LGExpenseCopilot/gateway.py` uses SigV4 to connect its agent to an `AWS_IAM` AgentCore MCP Gateway and loads its tools with `langchain-mcp-adapters`. FieldSight's new `src/fieldsight/gateway_client.py` uses the same connection pattern. `script/configure_gateway_iam.py` previews an IAM Gateway; it does not create targets. No Cognito token is needed to invoke an IAM Gateway. The Runtime task role or local AWS profile needs `bedrock-agentcore:InvokeGateway` scoped to the actual Gateway ARN.

Install `deploy/ecs/gateway-client-requirements.txt` in the **agent's Runtime environment**, in addition to the project package. From an agent's trusted dispatcher code, use `async with gateway_tools(thread_id=context.session_id) as remote_tools:` and pass `remote_tools` into that graph's tool list. Set `AWS_REGION` and `FIELDSIGHT_GATEWAY_URL` (the complete AWS Gateway HTTPS URL ending in `/mcp`). `AGENTCORE_GATEWAY_FIELDSIGHTTOOLS_URL` is also accepted. The thread ID must come from the dispatcher session; the model must not choose it.

**Deployment gate:** The Flask ECS API now fails closed (`401`) until a production `caller_resolver` supplies a verified analyst identity. Do not deploy the IAM Gateway against that backend yet. The demo's target is a web search connector, so it does not address FieldSight's requirement to check the analyst's establishment grant on every ECS tool call. An API Gateway stage target signed with `GATEWAY_IAM_ROLE` reaches the ECS API as the **Gateway role**, not the original IAM caller. A forwarded thread ID or email alone does not prove who the analyst is. Complete a verified analyst-to-session binding and have the API recheck analyst identity and grants on every call before using `--apply` and attaching the two read tools.

Local preview:

```powershell
python script/configure_gateway_iam.py --gateway-role-arn arn:aws:iam::<account-id>:role/<gateway-role> --region <region>
python -m compileall -q src/fieldsight/gateway_client.py script/configure_gateway_iam.py
```

The former Cognito/JWT Gateway configuration, token forwarding interceptor, and token resolver have been removed. The repository module has not been modified.
