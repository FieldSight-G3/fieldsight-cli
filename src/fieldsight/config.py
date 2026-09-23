import os

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="forbid")

    environment: str = Field(min_length=1)
    aws_region: str = Field(min_length=1)
    bedrock_model_id: str = Field(min_length=1)
    bedrock_fast_model_id: str = Field(min_length=1)
    bedrock_judge_model_id: str = Field(min_length=1)
    bedrock_kb_id: str = Field(min_length=1)
    bedrock_guardrail_id: str = Field(min_length=1)
    bedrock_guardrail_version: str = Field(min_length=1)
    packet_bucket: str = Field(min_length=1)
    database_url: str = Field(min_length=1)
    retrieval_score_threshold: float = Field(ge=0.0, le=1.0)
    confidence_floor: float = Field(ge=0.0, le=1.0)
    gateway_api_key: str = Field(min_length=1)
    allow_dev_identity: bool

settings = Settings(
    environment=os.environ["FIELDSIGHT_ENVIRONMENT"],
    aws_region=os.environ["FIELDSIGHT_AWS_REGION"],
    bedrock_model_id=os.environ["FIELDSIGHT_BEDROCK_MODEL_ID"],
    bedrock_fast_model_id=os.environ["FIELDSIGHT_BEDROCK_FAST_MODEL_ID"],
    bedrock_judge_model_id=os.environ["FIELDSIGHT_BEDROCK_JUDGE_MODEL_ID"],
    bedrock_kb_id=os.environ["FIELDSIGHT_BEDROCK_KB_ID"],
    bedrock_guardrail_id=os.environ["FIELDSIGHT_BEDROCK_GUARDRAIL_ID"],
    bedrock_guardrail_version=os.environ["FIELDSIGHT_BEDROCK_GUARDRAIL_VERSION"],
    packet_bucket=os.environ["FIELDSIGHT_PACKET_BUCKET"],
    database_url=os.environ["FIELDSIGHT_DATABASE_URL"],
    retrieval_score_threshold=float(os.environ["FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD"]),
    confidence_floor=float(os.environ["FIELDSIGHT_CONFIDENCE_FLOOR"]),
    gateway_api_key=os.environ["FIELDSIGHT_GATEWAY_API_KEY"],
    allow_dev_identity=os.environ["FIELDSIGHT_ALLOW_DEV_IDENTITY"].lower() == "true"
)