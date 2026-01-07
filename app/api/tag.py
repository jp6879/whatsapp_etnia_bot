from sqlalchemy import Enum


class APITag(str, Enum):
    SHEETS = "Sheets"
    REDIS = "Redis"
