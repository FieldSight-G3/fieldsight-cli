# FieldSight ECS read tools and IAM Gateway

The Flask API still serves the two read tools through ECS, an internal ALB, an AWS IAM protected REST API stage, and AgentCore Gateway. The Gateway's inbound authentication is AWS IAM with SigV4. The agent connects using `src/fieldsight/interfaces/gateway_client.py`. See `GATEWAY-IAM.md` for the current identity handoff limitation.

## Deploy the existing tool API

Build `deploy/ecs/Dockerfile` from the project root with a real digest pinned Python base image; push to ECR and deploy behind an internal ALB with two Fargate tasks. Use `/health/ready` for the target health check and `/health/live` for process liveness. The ECS task needs database access. Configure the existing `FIELDSIGHT_` environment settings required by `config.py`. No Cognito pool or access token is needed for the IAM Gateway.

Create a Regional AWS IAM protected REST API stage with a private VPC Link integration to the internal ALB. Generate the API schema with `python script/generate_tool_openapi.py --output deploy/ecs/fieldsight-tools.openapi.json --vpc-link-id <id> --alb-arn <arn> --alb-url http://<internal-alb-dns>` and restrict the Gateway service role to invoking the two POST methods. The target request is previewed by `python script/configure_gateway_target.py --region <region> --gateway-id <id> --rest-api-id <id> --stage prod`.

Preview IAM Gateway creation with `python script/configure_gateway_iam.py --region <region> --gateway-role-arn <arn>`. Both creation scripts write AWS resources only with `--apply`.

## Remaining identity handoff

Do **not** run the IAM Gateway against this ECS API yet. Gateway IAM authentication establishes the calling AWS principal, but the REST stage target calls the API using the Gateway service role. Neither that role nor a client supplied thread ID identifies the analyst who owns the session. The ECS API now denies tool requests by default (`401 unauthenticated`) until `create_app(caller_resolver=...)` is supplied a production resolver backed by a verified analyst-to-session identity handoff. The caller resolver must obtain an identity from a trusted source; it must never accept a caller email from a model argument or a plain client header. The service rechecks the session and establishment grants in `GatewayReadStore` on every call.

When that handoff exists, test a successful extraction with a granted analyst and a structured `not_entitled` denial with a different analyst. Then use a separate MCP client to list and call a tool through Gateway and save the Gateway invocation log as the requirements specify. The old Cognito/JWT interceptor, token forwarding, and its setup instructions have been removed.
