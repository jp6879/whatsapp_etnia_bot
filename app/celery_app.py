from celery import Celery
from app.config import redis_settings

celery = Celery(
    "difusionwsp",
    broker=redis_settings.REDIS_DB_URL,
    backend=redis_settings.REDIS_DB_URL,
    include=["app.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Argentina/Buenos_Aires",
)
