import boto3
from functools import lru_cache
from fieldsight.config import AWS_REGION

@lru_cache(maxsize=1)
def get_session():
    """
    Get a cached AWS session.
    """
    return boto3.Session(region_name=AWS_REGION)

@lru_cache(maxsize=None)
def get_client(service_name):
    """Get a cached AWS client for the specified service."""
    return get_session().client(service_name)