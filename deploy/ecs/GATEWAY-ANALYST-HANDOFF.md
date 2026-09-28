# IAM analyst identity handoff

FieldSight uses IAM roles, not IAM Identity Center. The requirements prohibit long-lived access keys: locally, use an assumed role backed by short-lived console credentials (`aws login`); deployed compute uses its execution role. Give each analyst a distinct IAM role such as `FieldSightAnalystLogan` with no IAM path. Restrict its trust policy to that analyst's authorized principal. Never share one analyst role between analysts: anyone who can assume a shared role can choose its session name.

The trusted dispatcher uses the analyst's temporary assumed-role credentials and calls `issue_proof(thread_id, region)` to make a 60-second, session-bound STS `GetCallerIdentity` proof. Pass it to `gateway_tools(thread_id, caller_proof=proof)`; the model cannot supply the proof or thread ID. The target allowlists `x-fieldsight-thread-id` and `x-fieldsight-caller-proof` and forwards both to ECS. ECS validates the URL, calls regional STS, requires an exact role from `allowed_role_arns`, and passes the verified **analyst role ARN** to the resolver. The Gateway's execution role signs the target request but is never an analyst role.

**Wired:** `AnalystRepository.email_for_iam_principal(role_arn)` maps an exact, uniquely enrolled analyst IAM role ARN to the analyst's email, and `tool_runtime.create_production_app()` passes it to `caller_resolver(...)` with only the enrolled analyst roles in `allowed_role_arns` (never the Gateway or Runtime roles). The Gateway read queries live in the repository module (`GatewayReadRepository`); `tool_store.GatewayReadStore` applies the session and establishment-grant checks on every call.

Local smoke test (AWS CLI 2.32 or newer, with an assigned analyst role):

```powershell
aws login --profile fieldsight-signin
aws configure set role_arn "arn:aws:iam::ACCOUNT_ID:role/FieldSightAnalystLogan" --profile fieldsight-analyst
aws configure set source_profile fieldsight-signin --profile fieldsight-analyst
aws configure set region us-east-1 --profile fieldsight-analyst
$env:AWS_PROFILE = "fieldsight-analyst"
aws sts get-caller-identity --profile fieldsight-analyst --query Arn --output text
python script/check_iam_caller_proof.py --role-arn "arn:aws:iam::ACCOUNT_ID:role/FieldSightAnalystLogan"
```

Replace the role ARN and region with your assigned values. STS should report `arn:aws:sts::ACCOUNT_ID:assumed-role/FieldSightAnalystLogan/...`. If AssumeRole is denied, both the IAM user policy and the role trust policy must allow it. Signing as an IAM user, even with temporary `aws login` credentials, is rejected.

Treat the proof URL as a short-lived bearer secret: keep it out of application, ALB, API Gateway and Gateway request logs, graph checkpoints, and Postgres. Refresh it for each turn. ECS needs outbound HTTPS to regional STS. For a deployed Runtime, the proof must arrive from an authenticated analyst-facing dispatcher (configure a Runtime header allowlist if applicable); signing with the Runtime execution role fails. A second external client needs its own analyst role and proof. Before enabling tools, test the full client → Gateway → API Gateway → ECS → STS path, including cross-analyst denials.
