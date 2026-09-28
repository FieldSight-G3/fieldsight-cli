"""Call the extraction tool through Gateway as the current analyst."""

import argparse
import asyncio

import boto3

from fieldsight.interfaces.gateway_client import gateway_tools
from fieldsight.interfaces.iam_caller_proof import issue_proof


async def call_tool(thread_id: str) -> None:
    region = boto3.Session().region_name
    if not region:
        raise RuntimeError("Configure an AWS region for this profile")

    proof = issue_proof(thread_id, region)

    async with gateway_tools(thread_id, caller_proof=proof, region=region) as tools:
        extraction = next(
            (tool for tool in tools if tool.name.endswith("get_incident_extraction")),
            None,
        )
        if extraction is None:
            raise RuntimeError("Gateway did not expose get_incident_extraction")

        result = await extraction.ainvoke({})
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thread-id", required=True)
    args = parser.parse_args()
    asyncio.run(call_tool(args.thread_id))


if __name__ == "__main__":
    main()