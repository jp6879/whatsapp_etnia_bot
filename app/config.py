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
    REDIS_DB_URL: str

    model_config = _base_config


class GoogleDriveSettings(BaseSettings):
    SERVICE_ACCOUNT_FILE: str
    TOKEN_FILE: str
    SCOPES: list[str]
    ADS_FILE_PATH: str
    FOLDER_ID: str
    FOLDER_ID_SEASONAL: str
    FOLDER_ID_GRUPAL: str

    model_config = _base_config


redis_settings = RedisSettings()
gdrive_settings = GoogleDriveSettings()
wpp_settings = AppSettings()
