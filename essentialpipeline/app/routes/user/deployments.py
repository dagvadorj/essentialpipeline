"""
User Deployments routes for EssentialPipeline - the approval workflow in
services/deployment.py, exposed as a web UI.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline.models import Deployment, Project, ProjectVersion, Environment, User
from essentialpipeline.services.deployment import (
    has_permission, request_deployment, approve, reject, mark_deployed, rollback,
    DeploymentWorkflowError, DeploymentPermissionError
)

bp = Blueprint('user_deployments', __name__)


def _current_user():
    return User.query.get(int(get_jwt_identity()))


def _visible_deployments(user):
    if has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin'):
        return Deployment.query.order_by(Deployment.requested_at.desc()).all()
    return Deployment.query.join(ProjectVersion).join(ProjectVersion.project) \
        .filter_by(owner_user_id=user.id).order_by(Deployment.requested_at.desc()).all()


def _get_deployment_or_none(deployment_id, user):
    deployment = Deployment.query.get_or_404(deployment_id)
    owns_project = deployment.project_version.project.owner_user_id == user.id
    can_review = has_permission(user, 'deployment', 'write') or has_permission(user, 'deployment', 'admin')
    return deployment if (owns_project or can_review) else None


@bp.route('/')
@jwt_required()
def list_deployments():
    user = _current_user()
    return render_template('user/deployments/list.html', title='Deployments', deployments=_visible_deployments(user))


@bp.route('/new', methods=['GET', 'POST'])
@jwt_required()
def new_deployment():
    user = _current_user()
    published_versions = ProjectVersion.query.join(ProjectVersion.project) \
        .filter(Project.owner_user_id == user.id, ProjectVersion.is_published.is_(True)) \
        .order_by(ProjectVersion.created_at.desc()).all()
    environments = Environment.query.order_by(Environment.name).all()

    if request.method == 'POST':
        version = ProjectVersion.query.get(request.form.get('project_version_id', type=int))
        environment = Environment.query.get(request.form.get('environment_id', type=int))

        if not version or not environment or version.project.owner_user_id != user.id:
            flash('Select a valid published version and environment', 'danger')
            return render_template('user/deployments/new.html', title='Request Deployment',
                                    published_versions=published_versions, environments=environments)

        try:
            deployment = request_deployment(version, environment, user)
        except (DeploymentWorkflowError, DeploymentPermissionError) as e:
            flash(str(e), 'danger')
            return render_template('user/deployments/new.html', title='Request Deployment',
                                    published_versions=published_versions, environments=environments)

        flash('Deployment requested!', 'success')
        return redirect(url_for('user_deployments.detail_deployment', deployment_id=deployment.id))

    return render_template('user/deployments/new.html', title='Request Deployment',
                            published_versions=published_versions, environments=environments)


@bp.route('/<int:deployment_id>')
@jwt_required()
def detail_deployment(deployment_id):
    user = _current_user()
    deployment = _get_deployment_or_none(deployment_id, user)
    if deployment is None:
        flash('Access denied', 'danger')
        return redirect(url_for('user_deployments.list_deployments'))

    return render_template(
        'user/deployments/detail.html', title=f'Deployment #{deployment.id}',
        deployment=deployment,
        can_approve=has_permission(user, 'deployment', 'write'),
        can_manage=has_permission(user, 'deployment', 'admin'),
        is_requester=(deployment.requested_by == user.id)
    )


def _act(deployment_id, action_fn):
    user = _current_user()
    deployment = _get_deployment_or_none(deployment_id, user)
    if deployment is None:
        flash('Access denied', 'danger')
        return redirect(url_for('user_deployments.list_deployments'))

    try:
        action_fn(deployment, user)
        flash('Done.', 'success')
    except (DeploymentWorkflowError, DeploymentPermissionError) as e:
        flash(str(e), 'danger')

    return redirect(url_for('user_deployments.detail_deployment', deployment_id=deployment_id))


@bp.route('/<int:deployment_id>/approve', methods=['POST'])
@jwt_required()
def approve_deployment(deployment_id):
    comments = request.form.get('comments')
    return _act(deployment_id, lambda d, u: approve(d, u, comments=comments))


@bp.route('/<int:deployment_id>/reject', methods=['POST'])
@jwt_required()
def reject_deployment(deployment_id):
    comments = request.form.get('comments')
    return _act(deployment_id, lambda d, u: reject(d, u, comments=comments))


@bp.route('/<int:deployment_id>/deploy', methods=['POST'])
@jwt_required()
def deploy_deployment(deployment_id):
    return _act(deployment_id, mark_deployed)


@bp.route('/<int:deployment_id>/rollback', methods=['POST'])
@jwt_required()
def rollback_deployment(deployment_id):
    reason = request.form.get('reason', '')
    return _act(deployment_id, lambda d, u: rollback(d, u, reason))
