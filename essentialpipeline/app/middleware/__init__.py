"""
Middleware registration for EssentialPipeline
"""

from flask import request, g
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def register_middleware(app):
    """Register all middleware with the Flask application"""
    
    # Request ID middleware
    app.before_request(request_id_middleware)
    
    # Audit logging middleware
    app.after_request(audit_log_middleware)
    
    # Error handling
    app.errorhandler(403)(forbidden_handler)
    app.errorhandler(404)(not_found_handler)
    app.errorhandler(500)(internal_error_handler)


def request_id_middleware():
    """Generate a unique request ID for each request"""
    import uuid
    g.request_id = str(uuid.uuid4())
    logger.debug(f"Request started: {g.request_id}")


def audit_log_middleware(response):
    """Log audit information for each request"""
    from essentialpipeline import db
    from essentialpipeline.models import AuditLog
    from flask_jwt_extended import get_jwt_identity
    
    # Skip for static files and certain endpoints
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return response
    
    try:
        # Get user info
        user_id = None
        try:
            raw_identity = get_jwt_identity()
            user_id = int(raw_identity) if raw_identity is not None else None
        except:
            pass
        
        # Extract action from method
        method = request.method
        action = 'read' if method in ['GET', 'HEAD', 'OPTIONS'] else \
                'create' if method == 'POST' else \
                'update' if method in ['PUT', 'PATCH'] else \
                'delete' if method == 'DELETE' else method.lower()
        
        # Extract resource type from path
        resource_type = extract_resource_type(request.path)
        resource_id = extract_resource_id(request.path)
        
        # Log to database
        if db and hasattr(db, 'session'):
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=request.path,
                details={
                    'ip': request.remote_addr,
                    'user_agent': request.user_agent.string,
                    'method': method,
                    'status_code': response.status_code
                },
                ip_address=request.remote_addr,
                user_agent=str(request.user_agent)[:255]
            )
            db.session.add(audit_log)
            db.session.commit()
        
        logger.info(f"Audit: user={user_id}, action={action}, resource={resource_type}, path={request.path}")
        
    except Exception as e:
        logger.error(f"Audit logging failed: {e}")
    
    return response


def extract_resource_type(path):
    """Extract resource type from request path"""
    # Map paths to resource types
    path_map = {
        '/api/v1/projects': 'project',
        '/api/v1/tasks': 'task',
        '/api/v1/models': 'model',
        '/api/v1/deployments': 'deployment',
        '/api/v1/logs': 'log',
        '/user/projects': 'project',
        '/user/tasks': 'task',
        '/user/models': 'model',
        '/admin/governance/groups': 'group',
        '/admin/governance/users': 'user',
        '/admin/governance/permissions': 'permission',
    }
    
    for prefix, resource in path_map.items():
        if path.startswith(prefix):
            return resource
    
    return 'unknown'


def extract_resource_id(path):
    """Extract resource ID from request path"""
    import re
    # Find numeric IDs in path
    match = re.search(r'/(?:api|user|admin)/[^/]+/(\d+)', path)
    if match:
        return int(match.group(1))
    return None


def forbidden_handler(error):
    """
    Handle 403 errors (admin_required/project_access_required abort(403)).

    Without this, abort(403) from an /api/* route returned Flask's default
    HTML error page instead of JSON, inconsistent with every other error
    response those routes return.
    """
    from flask import jsonify
    description = getattr(error, 'description', None) or 'Forbidden'
    logger.warning(f"403: {request.path} - {description}")
    if request.path.startswith('/api/'):
        return jsonify({'error': description}), 403
    return description, 403


def not_found_handler(error):
    """Handle 404 errors"""
    from flask import jsonify
    logger.warning(f"404: {request.path}")
    if request.accept_mimetypes.accept_json:
        return jsonify({'error': 'Not found'}), 404
    return 'Not found', 404


def internal_error_handler(error):
    """Handle 500 errors"""
    from flask import jsonify
    logger.error(f"500: {request.path} - {error}")
    if request.accept_mimetypes.accept_json:
        return jsonify({'error': 'Internal server error'}), 500
    return 'Internal server error', 500


# RBAC Decorators

def admin_required(f):
    """Decorator to require admin privileges"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        from essentialpipeline.models import User
        
        verify_jwt_in_request()
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)

        if not user or not user.is_admin:
            from flask import abort
            logger.warning(f"Admin access denied for user {user_id} at {request.path}")
            abort(403, description="Admin access required")
        
        return f(*args, **kwargs)
    return decorated


def user_required(f):
    """Decorator to require authenticated user"""
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request()
        return f(*args, **kwargs)
    return decorated


def project_access_required(f):
    """
    Decorator to check project access. Stashes the fetched project on
    g.project so the wrapped view doesn't need to query for it again.
    """
    @wraps(f)
    def decorated(project_id, *args, **kwargs):
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        from essentialpipeline.models import Project, User

        verify_jwt_in_request()
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        project = Project.query.get_or_404(project_id)
        g.project = project

        # Check if user owns project or has access
        if project.owner_user_id != user_id:
            from flask import abort
            logger.warning(f"Project access denied for user {user_id} to project {project_id}")
            abort(403, description="Access denied to project")
        
        return f(project_id, *args, **kwargs)
    return decorated
