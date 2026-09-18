"""
API v1 Tasks routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, jsonify

bp = Blueprint('tasks', __name__, url_prefix='/tasks')


@bp.route('/', methods=['GET'])
def list_tasks():
    """Placeholder until task scheduling is implemented"""
    return jsonify({'error': 'not implemented'}), 501
