"""
Admin Monitoring routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

bp = Blueprint('admin_monitoring', __name__)


@bp.route('/')
@jwt_required()
def index():
    """Placeholder until the admin monitoring dashboard is implemented"""
    from essentialpipeline.models import User
    user = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_admin:
        abort(403)
    flash('Monitoring admin UI is not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
