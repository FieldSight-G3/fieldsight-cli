"""Central construction of AWS SDK clients and Bedrock models."""

from functools import lru_cache, cache
from typing import Any

import boto3
from botocore.config import Config
from langchain_aws import AmazonKnowledgeBasesRetriever, BedrockEmbeddings, ChatBedrockConverse
from langchain_aws import (
    AmazonKnowledgeBasesRetriever,
    BedrockEmbeddings,
    ChatBedrockConverse,
)
from langchain_core.embeddings import Embeddings

from fieldsight.config import settings

EMBEDDING_DIMENSIONS = 1024


@lru_cache(maxsize=1)
def session() -> boto3.Session:
    return boto3.Session(region_name=settings.aws_region)


@cache
def client(service: str) -> Any:
    return session().client(
        service,
        config=Config(
            retries={"mode": "adaptive", "max_attempts": 4},
            connect_timeout=5,
            read_timeout=30,
        ),
    )


def bedrock_agent() -> Any:
    return client("bedrock-agent")


def bedrock_agent_runtime() -> Any:
    return client("bedrock-agent-runtime")


def textract() -> Any:
    return client("textract")


def s3() -> Any:
    return client("s3")


def chat_model(
    *, 
    fast: bool = False, 
    temperature: float = 0.0
    ) -> BaseChatModel:
    
    return ChatBedrockConverse(
        model_id=settings.bedrock_fast_model_id if fast else settings.bedrock_model_id,
        region_name=settings.aws_region,
        temperature=temperature,
        guardrail_config={
            "guardrailIdentifier": settings.bedrock_guardrail_id,
            "guardrailVersion": settings.bedrock_guardrail_version,
            "trace": "enabled",
        },
    )


@lru_cache(maxsize=1)
def embeddings() -> Embeddings:
    """Titan v2 at 1024 dims, unit length so cosine distance works directly."""
    return BedrockEmbeddings(
        model_id=settings.bedrock_embedding_model_id,
        client=client("bedrock-runtime"),
        dimensions=EMBEDDING_DIMENSIONS,
        normalize=True,
    )


def corpus_retriever(search_filter: dict | None = None) -> BaseRetriever:
    """ the corpus Knowledge Base, optionally narrowed by a KB metadata filter; hits under the score threshold are dropped by Bedrock """

    return AmazonKnowledgeBasesRetriever(
        knowledge_base_id=settings.bedrock_kb_id,
        client=bedrock_agent_runtime(),
        retrieval_config={"vectorSearchConfiguration": {
            "numberOfResults": settings.retrieval_max_chunks, **({"filter": search_filter} if search_filter else {})}},
        min_score_confidence=settings.retrieval_score_threshold,
    )
