from functools import cache, lru_cache

import boto3

from fieldsight.config import settings


@lru_cache(maxsize=1)
def get_session():
    """Get a cached AWS session."""
    return boto3.Session(region_name=settings.aws_region)

@cache
def get_client(service_name: str):
    """Get a cached AWS client."""
    return get_session().client(service_name)