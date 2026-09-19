"""
Flask application factory for EssentialPipeline
"""

import os
from flask import Flask
from essentialpipeline import db, jwt, admin
from essentialpipeline.config import get_config


def create_app(config_env=None):
    """Create and configure the Flask application"""
    
    # Create app instance. Flask(__name__) would default template_folder/static_folder
    # to paths relative to this package (essentialpipeline/app/), but the actual
    # templates/ and static/ directories live at the project root and repo root
    # respectively, so both must be pointed there explicitly.
    package_dir = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(package_dir, '..', 'templates'),
        static_folder=os.path.join(package_dir, '..', '..', 'static'),
    )
    
    # Load configuration
    config = get_config(config_env)
    app.config.from_object(config)
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)

    # For browser navigations to /user/* or /admin/*, a missing/invalid/expired
    # JWT should redirect to the login page rather than return raw JSON 401 -
    # API callers (/api/*) still get the JSON error as before.
    from flask import request, jsonify, redirect, url_for

    def _is_api_request():
        return request.path.startswith('/api/')

    @jwt.unauthorized_loader
    def _missing_token(reason):
        if _is_api_request():
            return jsonify({'error': 'Missing or invalid token', 'message': reason}), 401
        return redirect(url_for('user_auth.login', next=request.path))

    @jwt.invalid_token_loader
    def _invalid_token(reason):
        if _is_api_request():
            return jsonify({'error': 'Invalid token', 'message': reason}), 401
        return redirect(url_for('user_auth.login', next=request.path))

    @jwt.expired_token_loader
    def _expired_token(jwt_header, jwt_payload):
        if _is_api_request():
            return jsonify({'error': 'Token has expired'}), 401
        return redirect(url_for('user_auth.login', next=request.path))

    # Makes `current_user` available in templates (e.g. the admin-nav-link
    # check in templates/user/base.html), read from whichever JWT location
    # (header or cookie) the request actually used, if any.
    @app.context_processor
    def _inject_current_user():
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
        from essentialpipeline.models import User
        try:
            verify_jwt_in_request(optional=True)
            identity = get_jwt_identity()
            if identity:
                return {'current_user': User.query.get(int(identity))}
        except Exception:
            pass
        return {'current_user': None}

    # Configure admin (calls admin.init_app() itself, after views are registered)
    from essentialpipeline.app.admin_setup import configure_admin
    configure_admin(app, admin, db)
    
    # Register blueprints
    from essentialpipeline.app.routes import register_routes
    register_routes(app)
    
    # Register middleware
    from essentialpipeline.app.middleware import register_middleware
    register_middleware(app)
    
    # Initialize scheduler
    from essentialpipeline.services.scheduler import init_scheduler, schedule_all_tasks
    init_scheduler(app)

    # Create database tables (development only)
    if app.config.get('ENV') == 'development':
        with app.app_context():
            db.create_all()

    # Register any active cron-scheduled tasks with APScheduler, after the
    # tasks table above is guaranteed to exist.
    with app.app_context():
        schedule_all_tasks()

    return app


def get_app():
    """Get or create the application instance"""
    from flask import current_app
    if current_app:
        return current_app._get_current_object()
    return create_app()
