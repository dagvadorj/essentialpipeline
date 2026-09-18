"""
User Deployments routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash
from flask_jwt_extended import jwt_required

bp = Blueprint('user_deployments', __name__)


@bp.route('/')
@jwt_required()
def list_deployments():
    """Placeholder until deployment/promotion UI is implemented"""
    flash('Deployments are not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
