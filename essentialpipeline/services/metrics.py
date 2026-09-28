"""
System metrics collection (Monitoring layer, plan.md P5).

Runs on the same APScheduler instance services/scheduler.py already
sets up for cron-scheduled tasks - schedule_metrics_collection() adds a
recurring interval job to it. That job's thread has no Flask context of
its own, the same as a scheduled task's, so it goes through the same
push-an-app-context wrapper as scheduler._execute_task_entrypoint.
"""

import logging
import socket

logger = logging.getLogger(__name__)

METRIC_TYPES = ('cpu_usage', 'memory_usage', 'disk_usage')


def collect_system_metrics():
    """
    Writes one SystemMetric row per type in METRIC_TYPES.

    Best-effort: a psutil failure (or psutil not being installed) is
    logged and returns an empty list rather than raising - a missed
    sample shouldn't take down the scheduler.
    """
    from flask import current_app
    from essentialpipeline import db
    from essentialpipeline.models import SystemMetric

    try:
        import psutil
    except ImportError:
        logger.warning("psutil is not installed; system metrics collection skipped")
        return []

    try:
        host = socket.gethostname()
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(current_app.config.get('UPLOAD_FOLDER', '.'))

        rows = [
            SystemMetric(metric_type='cpu_usage', metric_value=cpu_percent, host=host,
                         additional_data={'unit': 'percent'}),
            SystemMetric(metric_type='memory_usage', metric_value=memory.percent, host=host,
                         additional_data={'unit': 'percent', 'total_bytes': memory.total, 'used_bytes': memory.used}),
            SystemMetric(metric_type='disk_usage', metric_value=disk.percent, host=host,
                         additional_data={'unit': 'percent', 'total_bytes': disk.total, 'used_bytes': disk.used}),
        ]
        db.session.add_all(rows)
        db.session.commit()
        return rows
    except Exception as e:
        logger.warning(f"System metrics collection failed: {e}")
        return []


def _collect_metrics_entrypoint():
    from essentialpipeline.services import scheduler as scheduler_module
    with scheduler_module._app.app_context():
        collect_system_metrics()


def schedule_metrics_collection(app) -> bool:
    """No-op (and returns False) if the scheduler is disabled - matches schedule_all_tasks()'s own guard."""
    from essentialpipeline.services import scheduler as scheduler_module

    if not scheduler_module.scheduler:
        logger.info("Scheduler not initialized; system metrics collection not scheduled")
        return False

    interval = app.config.get('METRICS_COLLECTION_INTERVAL_MINUTES', 1)
    scheduler_module.scheduler.add_job(
        _collect_metrics_entrypoint, 'interval', minutes=interval,
        id='system_metrics_collector', name='System metrics collector', replace_existing=True
    )
    logger.info(f"Scheduled system metrics collection every {interval} minute(s)")
    return True
