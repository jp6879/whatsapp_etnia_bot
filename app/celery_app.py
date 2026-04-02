from celery import Celery
from kombu import Queue
from app.config import worker_redis_settings

celery = Celery(
    "difusionwsp",
    broker=worker_redis_settings.WORKER_REDIS_DB_URL,
    backend=worker_redis_settings.WORKER_REDIS_DB_URL,
    include=["app.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Argentina/Buenos_Aires",
    # ── Reliability ────────────────────────────────────────────────────────────
    # Acknowledge task only AFTER it completes (not when picked up).
    # Combined with reject_on_worker_lost, this guarantees at-least-once delivery:
    # if the worker dies mid-task, the task is re-queued automatically.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # ── Queue routing ─────────────────────────────────────────────────────────
    # Isolate Sheets sync on its own queue so a backlog of Sheets tasks
    # never blocks other work. Scale with: celery -Q sheets worker -c 2
    task_queues=[
        Queue("default"),
        Queue("sheets"),
    ],
    task_default_queue="default",
    task_routes={
        "app.tasks.sync_sheets_with_redis_task": {"queue": "sheets"},
    },
)
