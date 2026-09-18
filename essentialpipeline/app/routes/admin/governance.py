"""
Admin Governance routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

bp = Blueprint('admin_governance', __name__)


@bp.route('/groups')
@jwt_required()
def list_groups():
    """Placeholder until the admin governance UI (groups/permissions/connections) is implemented"""
    from essentialpipeline.models import User
    user = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_admin:
        abort(403)
    flash('Governance admin UI is not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
