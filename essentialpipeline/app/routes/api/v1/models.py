"""
API v1 ML Models routes for EssentialPipeline (stub - not yet implemented)
"""

from flask import Blueprint, jsonify

bp = Blueprint('models', __name__, url_prefix='/models')


@bp.route('/', methods=['GET'])
def list_models():
    """Placeholder until ML model management is implemented"""
    return jsonify({'error': 'not implemented'}), 501
