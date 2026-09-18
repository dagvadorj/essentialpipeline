"""
API v1 routes for EssentialPipeline
"""

from flask import Blueprint

bp = Blueprint('v1', __name__, url_prefix='/v1')

# Import all API v1 routes
from essentialpipeline.app.routes.api.v1 import projects, tasks, models, deployments, logs, auth

# Register blueprints
bp.register_blueprint(projects.bp)
bp.register_blueprint(tasks.bp)
bp.register_blueprint(models.bp)
bp.register_blueprint(deployments.bp)
bp.register_blueprint(logs.bp)
bp.register_blueprint(auth.bp)

# Health check for API
@bp.route('/health')
def health_check():
    from flask import jsonify
    return jsonify({
        'status': 'healthy',
        'version': 'v1',
        'endpoints': {
            'auth': '/api/v1/auth',
            'projects': '/api/v1/projects',
            'tasks': '/api/v1/tasks',
            'models': '/api/v1/models',
            'deployments': '/api/v1/deployments',
            'logs': '/api/v1/logs'
        }
    })

@bp.route('/')
def api_v1_root():
    from flask import jsonify
    return jsonify({
        'message': 'EssentialPipeline API v1',
        'endpoints': {
            'auth': '/api/v1/auth',
            'projects': '/api/v1/projects',
            'tasks': '/api/v1/tasks',
            'models': '/api/v1/models',
            'deployments': '/api/v1/deployments',
            'logs': '/api/v1/logs',
            'health': '/api/v1/health'
        },
        'version': '1.0.0'
    })
