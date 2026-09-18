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


def init_scheduler(app):
    """
    Initialize the scheduler with the Flask app
    
    Args:
        app: Flask application
    """
    global scheduler, job_store, executor
    
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
                execute_task,
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


def execute_task(task_id: int, triggered_by: str = 'manual', user_id: int = None):
    """
    Execute a task
    
    Args:
        task_id: ID of the task to execute
        triggered_by: How the task was triggered (scheduler, manual, api, upstream)
        user_id: ID of the user who triggered the task (if applicable)
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
    
    # Create task run record
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
        try:
            # Get project files
            project = task.project
            if project and project.current_version:
                files = project.current_version.files
                for file in files:
                    file_path = os.path.join(temp_dir, file.file_path)
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    
                    # Copy file from storage to temp directory
                    # In production, this would copy from Garage
                    # For now, we'll skip this step
            
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
            
            # Create and start container
            container.create_container()
            result = container.execute(command, timeout=config.EXECUTION_TIMEOUT)
            
            # Add metadata
            result['duration'] = (datetime.utcnow() - task_run.start_time).total_seconds()
            
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
            container.cleanup()


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
                
                # Queue for execution
                queue_task_execution(dep.task_id, task_run.id)


def queue_task_execution(task_id: int, task_run_id: int = None):
    """
    Queue a task for execution
    
    Args:
        task_id: ID of the task to execute
        task_run_id: Optional ID of the task run record
    """
    from essentialpipeline import db
    from essentialpipeline.models import TaskRun
    
    # If no task_run_id provided, create one
    if not task_run_id:
        task_run = TaskRun(
            task_id=task_id,
            status='queued',
            triggered_by='api',
            start_time=datetime.utcnow()
        )
        db.session.add(task_run)
        db.session.commit()
        task_run_id = task_run.id
    
    # Submit to executor
    future = executor.submit(execute_task, task_id, 'manual')
    
    logger.info(f"Queued task {task_id} for execution")


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
            execute_task,
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
