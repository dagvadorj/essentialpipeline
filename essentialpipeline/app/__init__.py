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
    from essentialpipeline.services.scheduler import init_scheduler
    init_scheduler(app)
    
    # Create database tables (development only)
    if app.config.get('ENV') == 'development':
        with app.app_context():
            db.create_all()
    
    return app


def get_app():
    """Get or create the application instance"""
    from flask import current_app
    if current_app:
        return current_app._get_current_object()
    return create_app()
