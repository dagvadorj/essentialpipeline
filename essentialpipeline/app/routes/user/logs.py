"""
User Logs routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash
from flask_jwt_extended import jwt_required

bp = Blueprint('user_logs', __name__)


@bp.route('/')
@jwt_required()
def list_logs():
    """Placeholder until log aggregation UI is implemented"""
    flash('Log viewing is not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
