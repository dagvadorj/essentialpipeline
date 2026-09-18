"""
API v1 Deployments routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, jsonify

bp = Blueprint('deployments', __name__, url_prefix='/deployments')


@bp.route('/', methods=['GET'])
def list_deployments():
    """Placeholder until deployment/promotion workflow is implemented"""
    return jsonify({'error': 'not implemented'}), 501
