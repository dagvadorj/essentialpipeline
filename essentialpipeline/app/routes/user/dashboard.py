"""
User Dashboard routes for EssentialPipeline
"""

from flask import Blueprint, render_template, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import (
    Project, Task, TaskRun, MLModel, 
    Deployment, ExecutionLog
)
from datetime import datetime, timedelta

bp = Blueprint('user_dashboard', __name__, template_folder='../../../templates/user')


@bp.route('/')
@bp.route('/dashboard')
@jwt_required()
def index():
    """User dashboard showing overview of projects, tasks, and activity"""

    user_id = int(get_jwt_identity())
    
    # Get user's projects
    user_projects = Project.query.filter_by(owner_user_id=user_id).order_by(Project.updated_at.desc()).limit(5).all()
    user_projects_count = Project.query.filter_by(owner_user_id=user_id).count()
    
    # Get recent task runs for user's projects
    project_ids = [p.id for p in Project.query.filter_by(owner_user_id=user_id).all()]
    recent_runs = TaskRun.query.filter(
        TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()])
    ).order_by(TaskRun.start_time.desc()).limit(10).all()
    
    # Count task runs by status
    running_tasks_count = TaskRun.query.filter(
        TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()]),
        TaskRun.status == 'running'
    ).count()
    
    queued_tasks_count = TaskRun.query.filter(
        TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()]),
        TaskRun.status == 'pending'
    ).count()
    
    failed_tasks_count = TaskRun.query.filter(
        TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()]),
        TaskRun.status == 'failed'
    ).count()
    
    # Get recent deployments
    recent_deployments = Deployment.query.filter(
        Deployment.requested_by == user_id
    ).order_by(Deployment.requested_at.desc()).limit(5).all()
    
    # Get recent execution logs
    recent_logs = ExecutionLog.query.filter(
        ExecutionLog.task_run_id.in_([r.id for r in TaskRun.query.filter(
            TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()])
        ).all()])
    ).order_by(ExecutionLog.timestamp.desc()).limit(20).all()
    
    return render_template(
        'dashboard.html',
        title='Dashboard',
        user_projects=user_projects,
        user_projects_count=user_projects_count,
        recent_runs=recent_runs,
        running_tasks_count=running_tasks_count,
        queued_tasks_count=queued_tasks_count,
        failed_tasks_count=failed_tasks_count,
        recent_deployments=recent_deployments,
        recent_logs=recent_logs
    )


@bp.route('/stats')
@jwt_required()
def stats():
    """Get dashboard statistics via API"""
    from flask import jsonify

    user_id = int(get_jwt_identity())
    
    # Get project count
    project_count = Project.query.filter_by(owner_user_id=user_id).count()
    
    # Get task count
    project_ids = [p.id for p in Project.query.filter_by(owner_user_id=user_id).all()]
    task_count = Task.query.filter(Task.project_id.in_(project_ids)).count()
    
    # Get task run counts by status
    task_run_counts = db.session.query(
        TaskRun.status,
        db.func.count(TaskRun.id)
    ).filter(
        TaskRun.task_id.in_([t.id for t in Task.query.filter(Task.project_id.in_(project_ids)).all()])
    ).group_by(TaskRun.status).all()
    
    status_counts = {status: count for status, count in task_run_counts}
    
    # Get deployment count
    deployment_count = Deployment.query.filter_by(requested_by=user_id).count()
    
    # Get ML model count
    model_count = MLModel.query.filter_by(owner_user_id=user_id).count()
    
    return jsonify({
        'projects': project_count,
        'tasks': task_count,
        'task_runs': status_counts,
        'deployments': deployment_count,
        'models': model_count
    })
