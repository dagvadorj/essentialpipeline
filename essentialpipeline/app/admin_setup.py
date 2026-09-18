"""
Flask-Admin configuration for EssentialPipeline
"""

from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import redirect, url_for, request, abort
from wtforms.validators import DataRequired
from essentialpipeline import db


class SecureAdminIndexView(AdminIndexView):
    """Custom admin index view with authentication"""
    
    @jwt_required()
    def is_accessible(self):
        from essentialpipeline.models import User
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        return user and user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # Redirect to login if not authenticated
        if not get_jwt_identity():
            return redirect(url_for('auth.login', next=request.url))
        return abort(403)


class SecureModelView(ModelView):
    """Base model view with authentication and admin check"""
    
    @jwt_required()
    def is_accessible(self):
        from essentialpipeline.models import User
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        return user and user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        if not get_jwt_identity():
            return redirect(url_for('auth.login', next=request.url))
        return abort(403)


class UserModelView(SecureModelView):
    """Custom view for User model"""
    column_exclude_list = ['password']
    form_exclude_columns = ['password', 'products']
    column_searchable_list = ['username', 'email']
    column_filters = ['is_active', 'created_at']


class GroupModelView(SecureModelView):
    """Custom view for Group model"""
    column_searchable_list = ['name']
    form_args = {
        'name': {
            'label': 'Group Name',
            'validators': [DataRequired()]
        }
    }


class ProjectModelView(SecureModelView):
    """Custom view for Project model"""
    column_list = ['id', 'name', 'description', 'owner_user_id', 'is_active', 'created_at']
    column_searchable_list = ['name', 'description']
    column_filters = ['is_active', 'created_at', 'owner_user_id']
    form_args = {
        'owner_user_id': {
            'label': 'Owner',
            'validators': [DataRequired()]
        }
    }


class EnvironmentModelView(SecureModelView):
    """Custom view for Environment model"""
    column_list = ['id', 'name', 'description', 'is_production', 'created_at']
    form_switches = {
        'is_production': {
            'label': 'Production Environment',
            'on_label': 'Yes',
            'off_label': 'No'
        }
    }


class DatabaseConnectionModelView(SecureModelView):
    """Custom view for DatabaseConnection model"""
    column_exclude_list = ['connection_string_encrypted']
    form_exclude_columns = ['connection_string_encrypted']
    column_list = ['id', 'name', 'connection_type', 'environment_id', 'is_active', 'created_at']
    column_filters = ['connection_type', 'environment_id', 'is_active']


class AuditLogModelView(SecureModelView):
    """Custom view for AuditLog model"""
    column_list = ['id', 'user_id', 'action', 'resource_type', 'resource_id', 'timestamp']
    column_searchable_list = ['action', 'resource_type']
    column_filters = ['action', 'resource_type', 'timestamp']
    page_size = 50
    can_create = False
    can_edit = False
    can_delete = False


class TaskModelView(SecureModelView):
    """Custom view for Task model"""
    column_list = ['id', 'name', 'project_id', 'task_type', 'is_active', 'created_at']
    column_searchable_list = ['name']
    column_filters = ['task_type', 'is_active', 'project_id']


class MLModelModelView(SecureModelView):
    """Custom view for MLModel model"""
    column_list = ['id', 'name', 'project_id', 'model_type', 'is_active', 'created_at']
    column_searchable_list = ['name', 'model_type']
    column_filters = ['model_type', 'is_active', 'project_id']


def configure_admin(app, admin_instance, db_instance):
    """Configure Flask-Admin with all models"""
    
    # Set up admin
    admin_instance.index_view = SecureAdminIndexView(
        name='Admin',
        template='admin/index.html'
    )
    admin_instance.template_mode = 'bootstrap4'
    admin_instance.base_template = 'admin/base.html'
    
    # Import models (circular import safe here)
    from essentialpipeline.models import (
        User, Group, Permission, Environment,
        DatabaseConnection, StorageConnection,
        AuditLog, Project, Task, MLModel
    )
    
    # Register model views
    admin_instance.add_view(UserModelView(User, db_instance.session, name='Users'))
    admin_instance.add_view(GroupModelView(Group, db_instance.session, name='Groups'))
    admin_instance.add_view(ModelView(Permission, db_instance.session, name='Permissions'))
    admin_instance.add_view(EnvironmentModelView(Environment, db_instance.session, name='Environments'))
    admin_instance.add_view(DatabaseConnectionModelView(DatabaseConnection, db_instance.session, name='DB Connections'))
    admin_instance.add_view(ModelView(StorageConnection, db_instance.session, name='Storage Connections'))
    admin_instance.add_view(AuditLogModelView(AuditLog, db_instance.session, name='Audit Logs'))
    admin_instance.add_view(ProjectModelView(Project, db_instance.session, name='Projects'))
    admin_instance.add_view(TaskModelView(Task, db_instance.session, name='Tasks'))
    admin_instance.add_view(MLModelModelView(MLModel, db_instance.session, name='ML Models'))
    
    # Add to app
    admin_instance.init_app(app)
    
    # Add admin index route
    @app.route('/admin')
    @jwt_required()
    def admin_index():
        from essentialpipeline.models import User
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user or not user.is_admin:
            abort(403)
        return redirect(admin_instance.index_url)
