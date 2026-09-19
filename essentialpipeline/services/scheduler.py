"""
Scheduler service for EssentialPipeline
Custom thread-based scheduler for task execution
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
import logging
import json

from essentialpipeline import db
from essentialpipeline.models import Task, TaskRun, TaskDependency
from essentialpipeline.config import get_config

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None
job_store = None

# Thread pool for concurrent execution
executor = None
shutdown_flag = threading.Event()

# The Flask app, kept so background threads (ThreadPoolExecutor workers,
# APScheduler jobs) can push an app context before touching db.session or
# current_app - neither a request context nor an app context exists in
# those threads otherwise.
_app = None


def init_scheduler(app):
    """
    Initialize the scheduler with the Flask app

    Args:
        app: Flask application
    """
    global scheduler, job_store, executor, _app

    _app = app
    config = get_config()
    
    # Create thread pool
    max_workers = config.SCHEDULER_MAX_WORKERS
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='essentialpipeline_worker')
    logger.info(f"Initialized ThreadPoolExecutor with {max_workers} workers")
    
    # Create scheduler
    if config.SCHEDULER_ENABLED:
        # Use SQLAlchemy job store for persistence
        job_store = SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
        
        scheduler = BackgroundScheduler(jobstores={'default': job_store})
        scheduler.start()
        
        # Add shutdown hook
        import atexit
        atexit.register(shutdown_scheduler)
        
        logger.info("Initialized APScheduler with SQLAlchemy job store")
    else:
        logger.info("Scheduler is disabled")
    
    return scheduler


def shutdown_scheduler():
    """Shutdown the scheduler gracefully"""
    global scheduler, executor, shutdown_flag
    
    logger.info("Shutting down scheduler...")
    shutdown_flag.set()
    
    if scheduler:
        try:
            scheduler.shutdown(wait=True)
            logger.info("Scheduler shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")
    
    if executor:
        try:
            executor.shutdown(wait=True)
            logger.info("Executor shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down executor: {e}")


def schedule_all_tasks():
    """Schedule all active tasks from the database"""
    from essentialpipeline import db
    from essentialpipeline.models import Task
    
    if not scheduler:
        logger.warning("Scheduler not initialized")
        return 0
    
    # Clear existing jobs
    scheduler.remove_all_jobs()
    
    # Get all active tasks with schedules
    tasks = Task.query.filter(
        Task.is_active == True,
        Task.schedule_cron.isnot(None)
    ).all()
    
    scheduled_count = 0
    for task in tasks:
        try:
            # Schedule the task
            job = scheduler.add_job(
                _execute_task_entrypoint,
                trigger=CronTrigger.from_crontab(task.schedule_cron),
                args=[task.id],
                kwargs={'triggered_by': 'scheduler'},
                id=f'task_{task.id}',
                name=f'Task: {task.name}',
                replace_existing=True
            )
            
            # Update task next_run
            next_run = job.next_run_time
            if next_run:
                task.next_run = next_run
                db.session.commit()
            
            scheduled_count += 1
            logger.info(f"Scheduled task {task.id} ({task.name}) with cron: {task.schedule_cron}")
            
        except Exception as e:
            logger.error(f"Failed to schedule task {task.id}: {e}")
    
    logger.info(f"Scheduled {scheduled_count} tasks")
    return scheduled_count


def _execute_task_entrypoint(task_id: int, triggered_by: str = 'manual', user_id: int = None, task_run_id: int = None):
    """
    Entry point used by the ThreadPoolExecutor and APScheduler jobs, both of
    which run outside any Flask request - pushes an app context (via the
    app captured in `_app` by init_scheduler) before delegating to
    execute_task, which needs one for db.session/current_app.
    """
    with _app.app_context():
        execute_task(task_id, triggered_by=triggered_by, user_id=user_id, task_run_id=task_run_id)


def execute_task(task_id: int, triggered_by: str = 'manual', user_id: int = None, task_run_id: int = None):
    """
    Execute a task

    Args:
        task_id: ID of the task to execute
        triggered_by: How the task was triggered (scheduler, manual, api, upstream)
        user_id: ID of the user who triggered the task (if applicable)
        task_run_id: Reuse an already-created TaskRun (e.g. one created
            synchronously by queue_task_execution so the caller has an id
            to show immediately) instead of creating a new one
    """
    from essentialpipeline import db
    from essentialpipeline.models import Task, TaskRun, ExecutionLog
    from essentialpipeline.utils.docker import DockerContainer, DockerExecutionError
    from essentialpipeline.config import get_config
    import traceback

    config = get_config()

    # Get task
    task = Task.query.get(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return

    if not task.is_active:
        logger.warning(f"Task {task_id} is not active")
        return

    if task_run_id:
        task_run = TaskRun.query.get(task_run_id)
        if not task_run:
            logger.error(f"TaskRun {task_run_id} not found")
            return
    else:
        task_run = TaskRun(
            task_id=task.id,
            status='pending',
            triggered_by=triggered_by,
            triggered_by_user_id=user_id,
            start_time=datetime.utcnow()
        )
        db.session.add(task_run)
        db.session.flush()

    task_run_id = task_run.id

    try:
        # Update task run status
        task_run.status = 'running'
        db.session.commit()
        
        logger.info(f"Starting execution of task {task.id} ({task.name}), run {task_run_id}")
        
        # Check if task has dependencies
        dependencies = TaskDependency.query.filter_by(task_id=task.id).all()
        if dependencies:
            # Check if all dependencies have successful runs
            for dep in dependencies:
                # Get most recent run of dependent task
                last_run = TaskRun.query.filter_by(task_id=dep.depends_on_task_id).order_by(TaskRun.start_time.desc()).first()
                if not last_run or last_run.status != 'success':
                    task_run.status = 'skipped'
                    task_run.end_time = datetime.utcnow()
                    task_run.duration_seconds = 0
                    db.session.commit()
                    logger.info(f"Skipped task {task.id} due to unmet dependency on task {dep.depends_on_task_id}")
                    return
        
        # Execute the task
        result = execute_task_in_container(task, task_run)
        
        # Update task run
        task_run.status = 'success' if result.get('exit_code') == 0 else 'failed'
        task_run.end_time = datetime.utcnow()
        task_run.duration_seconds = result.get('duration', 0)
        task_run.error_message = result.get('error')
        
        # Save logs
        if result.get('logs'):
            execution_log = ExecutionLog(
                task_run_id=task_run_id,
                timestamp=datetime.utcnow(),
                level='info',
                message=result['logs'],
                stdout=result.get('output', ''),
                stderr=result.get('error', '')
            )
            db.session.add(execution_log)
        
        # Update task last_run
        task.last_run = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Completed execution of task {task.id} ({task.name}), run {task_run_id}: {task_run.status}")
        
        # Trigger dependent tasks if this task succeeded
        if task_run.status == 'success':
            trigger_dependent_tasks(task.id)
        
    except Exception as e:
        logger.error(f"Error executing task {task.id}: {e}")
        logger.error(traceback.format_exc())
        
        # Update task run
        task_run.status = 'failed'
        task_run.end_time = datetime.utcnow()
        task_run.error_message = str(e)
        
        db.session.commit()
        
        # Create error log
        execution_log = ExecutionLog(
            task_run_id=task_run_id,
            timestamp=datetime.utcnow(),
            level='error',
            message=f'Task execution failed: {e}',
            stderr=str(e)
        )
        db.session.add(execution_log)
        db.session.commit()


def execute_task_in_container(task: Task, task_run: TaskRun) -> dict:
    """
    Execute a task in a Docker container
    
    Args:
        task: Task to execute
        task_run: TaskRun record
        
    Returns:
        Dict with execution results
    """
    from essentialpipeline.utils.docker import DockerContainer, DockerExecutionError
    from essentialpipeline.config import get_config
    import tempfile
    import os

    config = get_config()

    if not config.DOCKER_ENABLED:
        # Fallback to local execution (not recommended for production)
        return execute_task_locally(task, task_run)

    # Create working directory
    with tempfile.TemporaryDirectory() as temp_dir:
        container = None
        try:
            project = task.project
            if not project or not project.current_version:
                raise DockerExecutionError(f"Task {task.id} has no project version to execute")

            extract_project_archive(project.current_version, temp_dir)

            # Create Docker container
            container = DockerContainer(
                image='python:3.11-slim',
                working_dir='/app',
                cpu_limit=config.SCHEDULER_MAX_WORKERS * 1000,  # Convert to millicores
                memory_limit=512 * 1024 * 1024,  # 512MB
                volumes={temp_dir: {'bind': '/app', 'mode': 'rw'}},
                environment={
                    'PYTHONPATH': '/app',
                    'ESSENTIALPIPELINE_TASK_ID': str(task.id),
                    'ESSENTIALPIPELINE_RUN_ID': str(task_run.id)
                }
            )
            
            # Build command based on task type
            if task.task_type == 'python':
                script_path = task.script_path or 'main.py'
                command = ['python', script_path]
            elif task.task_type == 'bash':
                command = ['bash', task.script_path]
            elif task.task_type == 'sql':
                command = ['python', '-c', f'print("SQL execution not implemented")']
            elif task.task_type == 'ml_model':
                command = ['python', '-c', f'print("ML model execution not implemented")']
            else:
                command = ['python', 'main.py']
            
            # Create and start container. The actual task command runs via
            # exec_run() below, not as the container's own process, so it
            # needs a long-lived keep-alive process to exec into - without
            # one, python:3.11-slim's default CMD (the python3 REPL) hits
            # EOF on its unattached stdin and exits almost immediately,
            # tearing the container down mid-exec (exit code 137).
            container.create_container(command=['sleep', 'infinity'])
            result = container.execute(command, timeout=config.EXECUTION_TIMEOUT)
            
            # Add metadata. container.execute() merges stdout+stderr into
            # 'output' (exec_run's default when demux isn't requested); mirror
            # it into 'logs' so execute_task's `if result.get('logs')` check
            # actually captures it into an ExecutionLog instead of no-op'ing.
            result['duration'] = (datetime.utcnow() - task_run.start_time).total_seconds()
            result['logs'] = result.get('output', '')

            return result
            
        except DockerExecutionError as e:
            logger.error(f"Docker execution error for task {task.id}: {e}")
            return {
                'exit_code': 1,
                'output': '',
                'error': str(e),
                'duration': (datetime.utcnow() - task_run.start_time).total_seconds()
            }
        except Exception as e:
            logger.error(f"Execution error for task {task.id}: {e}")
            return {
                'exit_code': 1,
                'output': '',
                'error': str(e),
                'duration': (datetime.utcnow() - task_run.start_time).total_seconds()
            }
        finally:
            if container is not None:
                container.cleanup()


def extract_project_archive(project_version, dest_dir: str) -> None:
    """
    Extract a project version's uploaded zip archive into dest_dir, so it
    can be bind-mounted into the execution container.

    Guards against zip-slip (archive entries with `../` or absolute paths
    that would write outside dest_dir): this runs on the host, before the
    Docker container - and its isolation - exists, so an unsafe entry has
    to be rejected here rather than relied on to be harmless once inside
    the container.

    Args:
        project_version: ProjectVersion whose uploaded archive to extract
        dest_dir: Existing directory to extract into

    Raises:
        DockerExecutionError: no uploaded archive, archive missing on
            disk, corrupt zip, or an unsafe path inside the archive
    """
    import os
    import zipfile
    from essentialpipeline.utils.docker import DockerExecutionError
    from essentialpipeline.utils.storage import get_file_path

    project_file = project_version.files[0] if project_version.files else None
    if not project_file or not project_file.storage_path:
        raise DockerExecutionError(
            f"Project version {project_version.id} has no uploaded archive to execute"
        )

    zip_path = get_file_path(project_file.storage_path)
    if not os.path.isfile(zip_path):
        raise DockerExecutionError(f"Uploaded project archive not found on disk: {zip_path}")

    dest_dir_real = os.path.realpath(dest_dir)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                member_path = os.path.realpath(os.path.join(dest_dir, member.filename))
                if member_path != dest_dir_real and not member_path.startswith(dest_dir_real + os.sep):
                    raise DockerExecutionError(
                        f"Refusing to extract unsafe path '{member.filename}' from project archive"
                    )
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as e:
        raise DockerExecutionError(f"Uploaded project archive is not a valid zip file: {e}")


def execute_task_locally(task: Task, task_run: TaskRun) -> dict:
    """
    Execute a task locally (fallback when Docker is disabled)
    
    Args:
        task: Task to execute
        task_run: TaskRun record
        
    Returns:
        Dict with execution results
    """
    import subprocess
    import shlex
    import tempfile
    import os
    
    logger.warning(f"Executing task {task.id} locally (Docker disabled)")
    
    # For demonstration, we'll just run a simple command
    start_time = datetime.utcnow()
    
    try:
        # This is a placeholder - in production, use Docker
        command = ['python', '-c', f'print("Executing task {task.id}: {task.name}")']
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        return {
            'exit_code': result.returncode,
            'output': result.stdout,
            'error': result.stderr,
            'duration': duration
        }
        
    except subprocess.TimeoutExpired:
        return {
            'exit_code': 1,
            'output': '',
            'error': 'Execution timed out',
            'duration': (datetime.utcnow() - start_time).total_seconds()
        }
    except Exception as e:
        return {
            'exit_code': 1,
            'output': '',
            'error': str(e),
            'duration': (datetime.utcnow() - start_time).total_seconds()
        }


def trigger_dependent_tasks(task_id: int):
    """
    Trigger all tasks that depend on the given task
    
    Args:
        task_id: ID of the task that just completed
    """
    from essentialpipeline import db
    from essentialpipeline.models import Task, TaskRun, TaskDependency
    
    # Find all tasks that depend on this task
    dependencies = TaskDependency.query.filter_by(depends_on_task_id=task_id).all()
    
    for dep in dependencies:
        dependent_task = Task.query.get(dep.task_id)
        if dependent_task and dependent_task.is_active:
            # Check if all dependencies for this task are met
            all_deps = TaskDependency.query.filter_by(task_id=dep.task_id).all()
            all_met = True
            
            for other_dep in all_deps:
                # Get most recent run of the dependency
                last_run = TaskRun.query.filter_by(task_id=other_dep.depends_on_task_id).order_by(TaskRun.start_time.desc()).first()
                if not last_run or last_run.status != 'success':
                    all_met = False
                    break
            
            if all_met:
                # Trigger the dependent task
                task_run = TaskRun(
                    task_id=dep.task_id,
                    status='pending',
                    triggered_by='upstream',
                    triggered_by_user_id=None,
                    start_time=datetime.utcnow()
                )
                db.session.add(task_run)
                db.session.commit()

                logger.info(f"Triggered dependent task {dep.task_id} ({dependent_task.name}) from task {task_id}")

                # Queue for execution, reusing the TaskRun just created above
                queue_task_execution(dep.task_id, triggered_by='upstream', task_run_id=task_run.id)


def queue_task_execution(task_id: int, triggered_by: str = 'manual', user_id: int = None, task_run_id: int = None) -> TaskRun:
    """
    Queue a task for execution on the thread pool.

    Args:
        task_id: ID of the task to execute
        triggered_by: How the task was triggered (manual, api, upstream)
        user_id: ID of the user who triggered the task (if applicable)
        task_run_id: Reuse an already-created TaskRun (e.g. from
            trigger_dependent_tasks) instead of creating a new one

    Returns:
        The TaskRun record (existing or newly created) for this run
    """
    from essentialpipeline.models import TaskRun

    if task_run_id:
        task_run = TaskRun.query.get(task_run_id)
        if not task_run:
            raise ValueError(f"TaskRun {task_run_id} not found")
    else:
        # Created synchronously (not inside execute_task) so the caller has
        # a run id to show immediately, before the background thread runs.
        # 'pending' (not 'queued' - not a value TaskRun.status's enum
        # allows) matches what execute_task itself would set on a fresh run.
        task_run = TaskRun(
            task_id=task_id,
            status='pending',
            triggered_by=triggered_by,
            triggered_by_user_id=user_id,
            start_time=datetime.utcnow()
        )
        db.session.add(task_run)
        db.session.commit()

    executor.submit(_execute_task_entrypoint, task_id, triggered_by, user_id, task_run.id)

    logger.info(f"Queued task {task_id} for execution (run {task_run.id})")
    return task_run


def run_pending_tasks():
    """Run all pending tasks"""
    from essentialpipeline import db
    from essentialpipeline.models import TaskRun
    
    # Get all pending task runs
    pending_runs = TaskRun.query.filter_by(status='pending').all()
    
    for run in pending_runs:
        # Submit to executor
        future = executor.submit(execute_task, run.task_id, run.triggered_by, run.triggered_by_user_id)
        
        # Update status to running
        run.status = 'running'
        db.session.commit()
        
        logger.info(f"Started pending task run {run.id} (task {run.task_id})")
    
    return len(pending_runs)


def schedule_task(task_id: int):
    """
    Schedule a single task
    
    Args:
        task_id: ID of the task to schedule
    """
    from essentialpipeline import db
    from essentialpipeline.models import Task
    
    task = Task.query.get(task_id)
    if not task or not task.schedule_cron:
        return False
    
    if not scheduler:
        logger.warning("Scheduler not initialized")
        return False
    
    try:
        # Remove existing job if it exists
        job_id = f'task_{task.id}'
        scheduler.remove_job(job_id)
        
        # Schedule the task
        job = scheduler.add_job(
            _execute_task_entrypoint,
            trigger=CronTrigger.from_crontab(task.schedule_cron),
            args=[task.id],
            kwargs={'triggered_by': 'scheduler'},
            id=job_id,
            name=f'Task: {task.name}',
            replace_existing=True
        )
        
        # Update task next_run
        task.next_run = job.next_run_time
        db.session.commit()
        
        logger.info(f"Scheduled task {task.id} ({task.name}) with cron: {task.schedule_cron}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to schedule task {task.id}: {e}")
        return False


def unschedule_task(task_id: int):
    """
    Remove a task from the schedule
    
    Args:
        task_id: ID of the task to unschedule
    """
    if not scheduler:
        logger.warning("Scheduler not initialized")
        return False
    
    try:
        job_id = f'task_{task_id}'
        scheduler.remove_job(job_id)
        logger.info(f"Unscheduled task {task_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to unschedule task {task_id}: {e}")
        return False
