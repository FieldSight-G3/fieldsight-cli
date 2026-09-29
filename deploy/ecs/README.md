# FieldSight ECS read tools and IAM Gateway

The Flask API still serves the two read tools through ECS, an internal ALB, an AWS IAM protected REST API stage, and AgentCore Gateway. The Gateway's inbound authentication is AWS IAM with SigV4. The agent connects using `src/fieldsight/interfaces/gateway_client.py`. See `GATEWAY-IAM.md` and `GATEWAY-ANALYST-HANDOFF.md` for how the analyst's identity reaches the API.

## Deploy the existing tool API

Build `deploy/ecs/Dockerfile` from the project root with a real digest pinned Python base image; push to ECR (enable scan on push) and deploy by image digest behind an internal ALB with a minimum of two Fargate tasks and service auto-scaling on CPU or request count. `.github/workflows/deploy.yml` builds, pushes and renders the task definition with the pushed `@sha256` digest, never the tag. Use `/health/ready` for the target health check and `/health/live` for process liveness. The ECS task needs database access. Configure the existing `FIELDSIGHT_` environment settings required by `config.py`. No Cognito pool or access token is needed for the IAM Gateway.

Create a Regional AWS IAM protected REST API stage with a private VPC Link integration to the internal ALB. Generate the API schema with `python script/generate_tool_openapi.py --output deploy/ecs/fieldsight-tools.openapi.json --vpc-link-id <id> --alb-arn <arn> --alb-url http://<internal-alb-dns>` and restrict the Gateway service role to invoking the two POST methods. The target request is previewed by `python script/configure_gateway_target.py --region <region> --gateway-id <id> --rest-api-id <id> --stage prod`.

Preview IAM Gateway creation with `python script/configure_gateway_iam.py --region <region> --gateway-role-arn <arn>`. Both creation scripts write AWS resources only with `--apply`.

## Identity handoff (wired)

The Gateway's IAM authentication proves only the calling AWS principal, and the REST stage target reaches the API as the Gateway service role. So the analyst's identity travels separately: the trusted dispatcher sends a 60-second, thread-bound STS caller proof, and `tool_runtime.create_production_app()` wires `iam_caller_proof.caller_resolver` so the API verifies the proof, requires an enrolled analyst role, and maps it to the analyst with `AnalystRepository.email_for_iam_principal`. `GatewayReadStore` then rechecks the bound session and the establishment grant on every call; an analyst with no grant gets a structured `not_entitled` denial, never an empty result. `create_app()` without a resolver still denies every tool call (`401`).

The agent should open Gateway tools with `available_gateway_tools(...)`: if the Gateway or the ECS API is unreachable, the turn continues with its native tools and `unavailable` names each Gateway tool that is gone (requirements §13). `gateway_tools(...)` still fails loudly, for `script/call_gateway_tool.py`.

Before the demo, test the full client → Gateway → API Gateway → ECS → STS path with a granted analyst (successful extraction) and a different analyst (structured `not_entitled`). Then drive the Gateway from a second MCP client and save the Gateway-side log line showing the call was authorized as that caller, as the requirements specify.
