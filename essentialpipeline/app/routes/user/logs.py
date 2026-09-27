"""
User Logs routes for EssentialPipeline - a single page covering the
three log types that actually get written: ExecutionLog
(services/scheduler.py), DeploymentLog and SecurityLog
(services/deployment.py and services/security_scan.py).
"""

from flask import Blueprint, render_template, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline.models import (
    ExecutionLog, DeploymentLog, SecurityLog, Task, TaskRun, Project,
    Deployment, ProjectVersion, SecurityParseResult, User
)
from essentialpipeline.services.deployment import has_permission

bp = Blueprint('user_logs', __name__)

LOG_TYPES = ('execution', 'deployment', 'security')


@bp.route('/')
@jwt_required()
def list_logs():
    user = User.query.get(int(get_jwt_identity()))
    log_type = request.args.get('type', 'execution')
    if log_type not in LOG_TYPES:
        log_type = 'execution'
    level = request.args.get('level') or None
    page = request.args.get('page', 1, type=int)

    if log_type == 'execution':
        query = ExecutionLog.query.join(TaskRun).join(Task).join(Project) \
            .filter(Project.owner_user_id == user.id)
        if level:
            query = query.filter(ExecutionLog.level == level)
        pagination = query.order_by(ExecutionLog.timestamp.desc()).paginate(page=page, per_page=25, error_out=False)

    elif log_type == 'deployment':
        query = DeploymentLog.query.join(Deployment)
        if not (has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin')):
            query = query.join(ProjectVersion).join(ProjectVersion.project).filter(Project.owner_user_id == user.id)
        if level:
            query = query.filter(DeploymentLog.level == level)
        pagination = query.order_by(DeploymentLog.timestamp.desc()).paginate(page=page, per_page=25, error_out=False)

    else:
        query = SecurityLog.query.join(SecurityParseResult).join(ProjectVersion).join(ProjectVersion.project) \
            .filter(Project.owner_user_id == user.id)
        if level:
            query = query.filter(SecurityLog.level == level)
        pagination = query.order_by(SecurityLog.timestamp.desc()).paginate(page=page, per_page=25, error_out=False)

    return render_template(
        'user/logs/list.html', title='Logs',
        log_type=log_type, level=level, pagination=pagination, logs=pagination.items
    )
