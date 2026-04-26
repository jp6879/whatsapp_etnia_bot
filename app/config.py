from functools import lru_cache

from pydantic.fields import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_base_config = SettingsConfigDict(
    env_file="./.env",
    env_ignore_empty=True,
    extra="ignore",
)


class AppSettings(BaseSettings):
    WPP_ADAPTER_URL: str
    AUTH_SESSION_KEY: str

    model_config = _base_config


class RedisSettings(BaseSettings):
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_USER: str
    REDIS_PASSWORD: str

    @property
    def REDIS_DB_URL(self) -> str:
        return f"redis://{self.REDIS_USER}:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"

    model_config = _base_config


class WorkerRedisSettings(BaseSettings):
    WORKER_REDIS_HOST: str
    WORKER_REDIS_PORT: int
    WORKER_REDIS_USER: str
    WORKER_REDIS_PASSWORD: str

    @property
    def WORKER_REDIS_DB_URL(self) -> str:
        return f"redis://{self.WORKER_REDIS_USER}:{self.WORKER_REDIS_PASSWORD}@{self.WORKER_REDIS_HOST}:{self.WORKER_REDIS_PORT}"

    model_config = _base_config


class GoogleDriveSettings(BaseSettings):
    SERVICE_ACCOUNT_FILE: str
    TOKEN_FILE: str
    SCOPES: list[str] = Field(
        default=["https://www.googleapis.com/auth/drive.readonly"]
    )
    ADS_FILE_PATH: str
    OFFERS_DB_PATH: str
    FOLDER_ID: str
    FOLDER_ID_SEASONAL: str
    FOLDER_ID_GRUPAL: str

    model_config = _base_config


class GoogleSheetsSettings(BaseSettings):
    GOOGLE_SHEETS_SPREADSHEET_ID: str
    GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE: str
    GOOGLE_SHEETS_SCOPES: list[str] = Field(
        default=["https://www.googleapis.com/auth/spreadsheets"]
    )

    model_config = _base_config


class OpenAISettings(BaseSettings):
    OPENAI_API_KEY: str

    model_config = _base_config


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()


@lru_cache
def get_redis_settings() -> RedisSettings:
    return RedisSettings()


@lru_cache
def get_worker_redis_settings() -> WorkerRedisSettings:
    return WorkerRedisSettings()


@lru_cache
def get_google_drive_settings() -> GoogleDriveSettings:
    return GoogleDriveSettings()


@lru_cache
def get_google_sheets_settings() -> GoogleSheetsSettings:
    return GoogleSheetsSettings()


@lru_cache
def get_openai_settings() -> OpenAISettings:
    return OpenAISettings()
