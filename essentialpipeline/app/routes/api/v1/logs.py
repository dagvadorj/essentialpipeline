"""
API v1 Logs routes for EssentialPipeline - read access to the three log
tables that actually get written: ExecutionLog (services/scheduler.py),
DeploymentLog and SecurityLog (services/deployment.py and
services/security_scan.py respectively).
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline.models import (
    ExecutionLog, DeploymentLog, SecurityLog, User
)
from essentialpipeline.services.deployment import has_permission

bp = Blueprint('logs', __name__, url_prefix='/logs')


def _paginate(query, order_col):
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    pagination = query.order_by(order_col.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return pagination


@bp.route('/', methods=['GET'])
@jwt_required()
def logs_index():
    """Three separate log types, not a unified stream - they have different shapes and owners"""
    return jsonify({
        'execution': '/api/v1/logs/execution',
        'deployment': '/api/v1/logs/deployment',
        'security': '/api/v1/logs/security'
    })


@bp.route('/execution', methods=['GET'])
@jwt_required()
def list_execution_logs():
    """Execution logs for the current user's own projects' task runs"""
    from essentialpipeline.models import Task, TaskRun, Project

    user_id = int(get_jwt_identity())
    query = ExecutionLog.query.join(TaskRun).join(Task).join(Project).filter(Project.owner_user_id == user_id)

    task_id = request.args.get('task_id', type=int)
    if task_id:
        query = query.filter(Task.id == task_id)
    task_run_id = request.args.get('task_run_id', type=int)
    if task_run_id:
        query = query.filter(ExecutionLog.task_run_id == task_run_id)
    level = request.args.get('level')
    if level:
        query = query.filter(ExecutionLog.level == level)

    pagination = _paginate(query, ExecutionLog.timestamp)
    return jsonify({
        'logs': [l.to_dict() for l in pagination.items],
        'page': pagination.page, 'pages': pagination.pages, 'total': pagination.total
    })


@bp.route('/deployment', methods=['GET'])
@jwt_required()
def list_deployment_logs():
    """
    Deployment logs for the current user's own projects' deployments,
    plus - if they can act on deployments at all - every deployment's
    logs, matching how the deployment views/routes already treat
    reviewer visibility (services/deployment.py callers).
    """
    from essentialpipeline.models import Deployment, ProjectVersion, Project

    user = User.query.get(int(get_jwt_identity()))
    query = DeploymentLog.query.join(Deployment)

    if not (has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin')):
        query = query.join(ProjectVersion).join(ProjectVersion.project).filter(Project.owner_user_id == user.id)

    deployment_id = request.args.get('deployment_id', type=int)
    if deployment_id:
        query = query.filter(DeploymentLog.deployment_id == deployment_id)
    level = request.args.get('level')
    if level:
        query = query.filter(DeploymentLog.level == level)

    pagination = _paginate(query, DeploymentLog.timestamp)
    return jsonify({
        'logs': [l.to_dict() for l in pagination.items],
        'page': pagination.page, 'pages': pagination.pages, 'total': pagination.total
    })


@bp.route('/security', methods=['GET'])
@jwt_required()
def list_security_logs():
    """Security scan logs for the current user's own projects' versions"""
    from essentialpipeline.models import SecurityParseResult, ProjectVersion, Project

    user_id = int(get_jwt_identity())
    query = SecurityLog.query.join(SecurityParseResult).join(ProjectVersion).join(ProjectVersion.project) \
        .filter(Project.owner_user_id == user_id)

    parse_result_id = request.args.get('parse_result_id', type=int)
    if parse_result_id:
        query = query.filter(SecurityLog.parse_result_id == parse_result_id)
    event_type = request.args.get('event_type')
    if event_type:
        query = query.filter(SecurityLog.event_type == event_type)
    level = request.args.get('level')
    if level:
        query = query.filter(SecurityLog.level == level)

    pagination = _paginate(query, SecurityLog.timestamp)
    return jsonify({
        'logs': [l.to_dict() for l in pagination.items],
        'page': pagination.page, 'pages': pagination.pages, 'total': pagination.total
    })
