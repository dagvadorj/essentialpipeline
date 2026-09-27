"""
API v1 Deployments routes for EssentialPipeline - the approval workflow
in services/deployment.py, exposed over the API.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline.models import Deployment, ProjectVersion, Environment, User
from essentialpipeline.services.deployment import (
    request_deployment, approve, reject, mark_deployed, rollback,
    DeploymentWorkflowError, DeploymentPermissionError
)

bp = Blueprint('deployments', __name__, url_prefix='/deployments')


def _visible_deployments(user):
    """
    Deployments for projects the user owns, plus - if they can act on
    deployments at all - every deployment, matching how an approver
    needs to see requests beyond their own projects to review them.
    """
    from essentialpipeline.services.deployment import has_permission

    if has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin'):
        return Deployment.query.order_by(Deployment.requested_at.desc()).all()

    return Deployment.query.join(ProjectVersion).join(ProjectVersion.project) \
        .filter_by(owner_user_id=user.id).order_by(Deployment.requested_at.desc()).all()


def _get_deployment_or_404(deployment_id, user):
    deployment = Deployment.query.get_or_404(deployment_id)
    owns_project = deployment.project_version.project.owner_user_id == user.id
    from essentialpipeline.services.deployment import has_permission
    can_review = has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin')
    if not owns_project and not can_review:
        return None
    return deployment


@bp.route('/', methods=['GET'])
@jwt_required()
def list_deployments():
    user = User.query.get(int(get_jwt_identity()))
    return jsonify({'deployments': [d.to_dict() for d in _visible_deployments(user)]})


@bp.route('/', methods=['POST'])
@jwt_required()
def create_deployment():
    """Request a deployment of a published project version to an environment"""
    user = User.query.get(int(get_jwt_identity()))
    data = request.get_json() or {}

    version = ProjectVersion.query.get(data.get('project_version_id'))
    environment = Environment.query.get(data.get('environment_id'))
    if not version or not environment:
        return jsonify({'error': 'project_version_id and environment_id are required and must exist'}), 400
    if version.project.owner_user_id != user.id:
        return jsonify({'error': 'Access denied to project'}), 403

    try:
        deployment = request_deployment(version, environment, user)
    except DeploymentPermissionError as e:
        return jsonify({'error': str(e)}), 403
    except DeploymentWorkflowError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify(deployment.to_dict()), 201


@bp.route('/<int:deployment_id>', methods=['GET'])
@jwt_required()
def get_deployment(deployment_id):
    user = User.query.get(int(get_jwt_identity()))
    deployment = _get_deployment_or_404(deployment_id, user)
    if deployment is None:
        return jsonify({'error': 'Access denied'}), 403

    data = deployment.to_dict()
    data['approvals'] = [a.to_dict() for a in deployment.approvals]
    return jsonify(data)


def _act(deployment_id, action_fn, extra_kwargs=None):
    user = User.query.get(int(get_jwt_identity()))
    deployment = _get_deployment_or_404(deployment_id, user)
    if deployment is None:
        return jsonify({'error': 'Access denied'}), 403

    try:
        action_fn(deployment, user, **(extra_kwargs or {}))
    except DeploymentPermissionError as e:
        return jsonify({'error': str(e)}), 403
    except DeploymentWorkflowError as e:
        return jsonify({'error': str(e)}), 409

    return jsonify(deployment.to_dict())


@bp.route('/<int:deployment_id>/approve', methods=['POST'])
@jwt_required()
def approve_deployment(deployment_id):
    comments = (request.get_json(silent=True) or {}).get('comments')
    return _act(deployment_id, lambda d, u: approve(d, u, comments=comments))


@bp.route('/<int:deployment_id>/reject', methods=['POST'])
@jwt_required()
def reject_deployment(deployment_id):
    comments = (request.get_json(silent=True) or {}).get('comments')
    return _act(deployment_id, lambda d, u: reject(d, u, comments=comments))


@bp.route('/<int:deployment_id>/deploy', methods=['POST'])
@jwt_required()
def deploy_deployment(deployment_id):
    return _act(deployment_id, mark_deployed)


@bp.route('/<int:deployment_id>/rollback', methods=['POST'])
@jwt_required()
def rollback_deployment(deployment_id):
    reason = (request.get_json(silent=True) or {}).get('reason', '')
    return _act(deployment_id, lambda d, u: rollback(d, u, reason))
