"""
User Tasks routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash
from flask_jwt_extended import jwt_required

bp = Blueprint('user_tasks', __name__)


@bp.route('/')
@jwt_required()
def list_tasks():
    """Placeholder until task scheduling UI is implemented"""
    flash('Task scheduling is not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
