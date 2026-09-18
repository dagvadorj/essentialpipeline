"""
API v1 Logs routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, jsonify

bp = Blueprint('logs', __name__, url_prefix='/logs')


@bp.route('/', methods=['GET'])
def list_logs():
    """Placeholder until log aggregation/streaming is implemented"""
    return jsonify({'error': 'not implemented'}), 501
