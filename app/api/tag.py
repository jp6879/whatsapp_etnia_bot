from enum import Enum


class APITag(str, Enum):
    SHEETS = "Sheets"
    REDIS = "Redis"
    WEBHOOK = "Webhook"
