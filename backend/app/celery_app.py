"""Celery 任务编排：定时采集 + 自动生成"""

from celery import Celery
from app.config import settings

celery_app = Celery(
    "aiviral",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "collect-rss-every-30min": {
            "task": "app.tasks.collect_rss",
            "schedule": 1800.0,  # 30 minutes
        },
        "collect-search-engine-every-2hours": {
            "task": "app.tasks.collect_search",
            "schedule": 7200.0,  # 2 hours
        },
        "sync-wechat-stats-daily": {
            "task": "app.tasks.sync_wechat_stats",
            "schedule": 43200.0,  # every 12 hours
            "kwargs": {"days": 7},
        },
        "collect-zhihu-every-2hours": {
            "task": "app.tasks.collect_zhihu",
            "schedule": 7200.0,
        },
        "publish-due-articles-every-5min": {
            "task": "app.tasks.publish_due_articles",
            "schedule": 300.0,
        },
    },
)

# 导入任务模块以完成注册（Celery 必须提前 import 才能发现任务）
from app import tasks  # noqa: F401
