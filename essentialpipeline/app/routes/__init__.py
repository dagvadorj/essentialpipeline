"""
Route registration for EssentialPipeline
"""

from flask import Blueprint


def register_routes(app):
    """Register all route blueprints with the Flask application"""
    
    # API Routes (v1)
    from essentialpipeline.app.routes.api import v1
    app.register_blueprint(v1.bp, url_prefix='/api/v1')
    
    # User Web UI Routes
    from essentialpipeline.app.routes.user import auth as user_auth
    from essentialpipeline.app.routes.user import dashboard
    from essentialpipeline.app.routes.user import projects
    from essentialpipeline.app.routes.user import tasks
    from essentialpipeline.app.routes.user import models
    from essentialpipeline.app.routes.user import deployments
    from essentialpipeline.app.routes.user import logs as user_logs

    app.register_blueprint(user_auth.bp)
    app.register_blueprint(dashboard.bp, url_prefix='/user')
    app.register_blueprint(projects.bp, url_prefix='/user/projects')
    app.register_blueprint(tasks.bp, url_prefix='/user/tasks')
    app.register_blueprint(models.bp, url_prefix='/user/models')
    app.register_blueprint(deployments.bp, url_prefix='/user/deployments')
    app.register_blueprint(user_logs.bp, url_prefix='/user/logs')
    
    # Admin Web UI Routes
    from essentialpipeline.app.routes.admin import governance
    from essentialpipeline.app.routes.admin import monitoring
    
    app.register_blueprint(governance.bp, url_prefix='/admin/governance')
    app.register_blueprint(monitoring.bp, url_prefix='/admin/monitoring')
    
    # Legacy root route (redirect or show dashboard)
    @app.route('/')
    def index_redirect():
        from flask import redirect, url_for
        return redirect(url_for('user_dashboard.index'))
    
    # Health check
    @app.route('/health')
    def health_check():
        from flask import jsonify
        from sqlalchemy import text
        try:
            from essentialpipeline import db
            db.session.execute(text('SELECT 1'))
            return jsonify({"status": "healthy", "database": "connected"}), 200
        except Exception as e:
            return jsonify({"status": "unhealthy", "error": str(e)}), 500
