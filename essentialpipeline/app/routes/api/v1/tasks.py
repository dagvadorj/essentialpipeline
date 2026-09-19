"""
API v1 Tasks routes for EssentialPipeline
"""

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline.models import Task, TaskRun

bp = Blueprint('tasks', __name__, url_prefix='/tasks')


def _get_owned_task(task_id, user_id):
    """Look up a task and confirm the current user owns its project, or return None"""
    task = Task.query.get_or_404(task_id)
    if task.project.owner_user_id != user_id:
        return None
    return task


@bp.route('/', methods=['GET'])
@jwt_required()
def list_tasks():
    """List all tasks across the current user's projects"""
    user_id = int(get_jwt_identity())
    tasks = Task.query.join(Task.project).filter_by(owner_user_id=user_id).all()
    return jsonify({'tasks': [t.to_dict() for t in tasks]})


@bp.route('/<int:task_id>', methods=['GET'])
@jwt_required()
def get_task(task_id):
    """Get a single task"""
    user_id = int(get_jwt_identity())
    task = _get_owned_task(task_id, user_id)
    if task is None:
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(task.to_dict())


@bp.route('/<int:task_id>/runs', methods=['GET'])
@jwt_required()
def list_task_runs(task_id):
    """List the run history for a task, most recent first"""
    user_id = int(get_jwt_identity())
    task = _get_owned_task(task_id, user_id)
    if task is None:
        return jsonify({'error': 'Access denied'}), 403

    runs = TaskRun.query.filter_by(task_id=task_id).order_by(TaskRun.start_time.desc()).all()
    return jsonify({'runs': [r.to_dict() for r in runs]})


@bp.route('/<int:task_id>/trigger', methods=['POST'])
@jwt_required()
def trigger_task(task_id):
    """Trigger a manual run of a task"""
    user_id = int(get_jwt_identity())
    task = _get_owned_task(task_id, user_id)
    if task is None:
        return jsonify({'error': 'Access denied'}), 403

    if not task.is_active:
        return jsonify({'error': 'Task is not active'}), 400

    from essentialpipeline.services.scheduler import queue_task_execution
    task_run = queue_task_execution(task_id, triggered_by='api', user_id=user_id)

    return jsonify(task_run.to_dict()), 202
