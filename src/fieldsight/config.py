from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    database_url: str = Field(
        ...,
        description="Postgres connection string, e.g. postgresql://user:pass@host:port/dbname",
    )


settings = Settings()