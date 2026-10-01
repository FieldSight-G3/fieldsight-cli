"""Central construction of AWS SDK clients and Bedrock models: one module builds them (spec section 3).

Models, embeddings and Knowledge Base retrieval are LangChain classes configured in place; each builds its own
Bedrock client from the region and the shared retry config. boto3 clients remain only for the AWS APIs LangChain
doesn't wrap: the standalone ApplyGuardrail screen, Knowledge Base ingestion jobs, Textract, S3 and the RDS IAM token.
"""

from functools import cache, lru_cache
from typing import Any

import boto3
from botocore.config import Config
from langchain_aws import (
    AmazonKnowledgeBasesRetriever,
    BedrockEmbeddings,
    ChatBedrockConverse,
)
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.retrievers import BaseRetriever

from fieldsight.config import settings

EMBEDDING_DIMENSIONS = 1024

# bounded, backed-off retries that respect throttling, and timeouts, on every AWS call (section 13)
RETRIES = Config(retries={"mode": "adaptive", "max_attempts": 4}, connect_timeout=5, read_timeout=30)


def chat_model(*, fast: bool = False, temperature: float = 0.0) -> BaseChatModel:
    """ the reasoning tier for the workers; fast=True is the fast tier, for the readiness gate """

    return ChatBedrockConverse(
        model_id=settings.bedrock_fast_model_id if fast else settings.bedrock_model_id,
        region_name=settings.aws_region,
        config=RETRIES,
        temperature=temperature,
        guardrail_config={
            "guardrailIdentifier": settings.bedrock_guardrail_id,
            "guardrailVersion": settings.bedrock_guardrail_version,
            "trace": "enabled",
        },
    )



def judge_model() -> BaseChatModel:
    """ the judge deployment for the custom evaluators (§14), kept apart from the reasoning tier it judges """

    return ChatBedrockConverse(model_id=settings.bedrock_judge_model_id, region_name=settings.aws_region,
                               config=RETRIES, temperature=0.0)

@lru_cache(maxsize=1)
def embeddings() -> Embeddings:
    """Titan v2 at 1024 dims, unit length so cosine distance works directly."""
    return BedrockEmbeddings(
        model_id=settings.bedrock_embedding_model_id,
        region_name=settings.aws_region,
        config=RETRIES,
        dimensions=EMBEDDING_DIMENSIONS,
        normalize=True,
    )


def corpus_retriever(search_filter: dict | None = None) -> BaseRetriever:
    """ corpus KB retriever with an optional metadata filter; ungated, since retrieval/corpus.py rescores and gates the hits """

    return AmazonKnowledgeBasesRetriever(
        knowledge_base_id=settings.bedrock_kb_id,
        region_name=settings.aws_region,
        config=RETRIES,
        # the corpus KB is a Bedrock-managed KB, which takes managedSearchConfiguration (a vector-store KB takes vectorSearchConfiguration)
        retrieval_config={"managedSearchConfiguration": {
            "numberOfResults": settings.retrieval_max_chunks, **({"filter": search_filter} if search_filter else {})}},
    )


@lru_cache(maxsize=1)
def session() -> boto3.Session:
    return boto3.Session(region_name=settings.aws_region)


@cache
def client(service: str) -> Any:
    return session().client(service, config=RETRIES)


def guardrail_client() -> Any:
    """ ApplyGuardrail: the stage-2 Prompt Attacks screen on one string, with no model call (aws/guardrails.py) """

    return client("bedrock-runtime")


def bedrock_agent() -> Any:
    """ the Knowledge Base's ingestion jobs (aws/knowledge_base.py); retrieval is corpus_retriever """

    return client("bedrock-agent")


def textract() -> Any:
    return client("textract")


def rds() -> Any:
    return client("rds")


def s3() -> Any:
    return client("s3")
