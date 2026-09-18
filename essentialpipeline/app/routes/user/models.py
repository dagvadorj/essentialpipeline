"""
User ML Models routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, redirect, url_for, flash
from flask_jwt_extended import jwt_required

bp = Blueprint('user_models', __name__)


@bp.route('/')
@jwt_required()
def list_models():
    """Placeholder until ML model management UI is implemented"""
    flash('ML model management is not implemented yet.', 'info')
    return redirect(url_for('user_dashboard.index'))
