#!/usr/bin/env python
"""
Seed data script for EssentialPipeline
Creates initial environments, admin user, groups, and permissions
"""

import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from essentialpipeline.app import create_app
from essentialpipeline import db
from essentialpipeline.models import (
    User, Group, Permission, Environment,
    DatabaseConnection, StorageConnection,
    GroupConnectionClearance
)
from essentialpipeline.utils.security import encrypt_data

def create_admin_user():
    """Create admin user"""
    admin = User.query.filter_by(username='admin').first()
    if admin:
        print("Admin user already exists")
        return admin
    
    admin = User(
        username='admin',
        email='admin@essentialpipeline.local',
        first_name='Admin',
        last_name='User',
        is_active=True,
        is_admin=True
    )
    admin.password = 'admin123'  # In production, use a secure password
    
    db.session.add(admin)
    db.session.commit()
    print(f"Created admin user: {admin.username}")
    return admin


def create_environments():
    """Create default environments"""
    environments = [
        {'name': 'dev', 'description': 'Development Environment', 'is_production': False},
        {'name': 'qa', 'description': 'Quality Assurance Environment', 'is_production': False},
        {'name': 'prod', 'description': 'Production Environment', 'is_production': True}
    ]
    
    for env_data in environments:
        env = Environment.query.filter_by(name=env_data['name']).first()
        if env:
            print(f"Environment {env_data['name']} already exists")
            continue
        
        env = Environment(**env_data)
        db.session.add(env)
        db.session.commit()
        print(f"Created environment: {env.name}")
    
    return Environment.query.all()


def create_groups():
    """Create default user groups"""
    groups = [
        {'name': 'admins', 'description': 'System administrators with full access'},
        {'name': 'developers', 'description': 'Developers who can create and manage projects'},
        {'name': 'data-scientists', 'description': 'Data scientists who can work with ML models'},
        {'name': 'analysts', 'description': 'Analysts who can view and run reports'}
    ]
    
    for group_data in groups:
        group = Group.query.filter_by(name=group_data['name']).first()
        if group:
            print(f"Group {group_data['name']} already exists")
            continue
        
        group = Group(**group_data)
        db.session.add(group)
        db.session.commit()
        print(f"Created group: {group.name}")
    
    return Group.query.all()


def create_permissions():
    """Create default permissions"""
    permissions = [
        # Database permissions
        {'name': 'db_read', 'resource_type': 'database', 'action': 'read', 'description': 'Read access to databases'},
        {'name': 'db_write', 'resource_type': 'database', 'action': 'write', 'description': 'Write access to databases'},
        {'name': 'db_admin', 'resource_type': 'database', 'action': 'admin', 'description': 'Admin access to databases'},
        
        # Storage permissions
        {'name': 'storage_read', 'resource_type': 'storage', 'action': 'read', 'description': 'Read access to storage'},
        {'name': 'storage_write', 'resource_type': 'storage', 'action': 'write', 'description': 'Write access to storage'},
        {'name': 'storage_admin', 'resource_type': 'storage', 'action': 'admin', 'description': 'Admin access to storage'},
        
        # Project permissions
        {'name': 'project_create', 'resource_type': 'project', 'action': 'create', 'description': 'Create projects'},
        {'name': 'project_read', 'resource_type': 'project', 'action': 'read', 'description': 'Read projects'},
        {'name': 'project_write', 'resource_type': 'project', 'action': 'write', 'description': 'Write projects'},
        {'name': 'project_delete', 'resource_type': 'project', 'action': 'delete', 'description': 'Delete projects'},
        {'name': 'project_execute', 'resource_type': 'project', 'action': 'execute', 'description': 'Execute projects'},
        
        # Task permissions
        {'name': 'task_read', 'resource_type': 'task', 'action': 'read', 'description': 'Read tasks'},
        {'name': 'task_write', 'resource_type': 'task', 'action': 'write', 'description': 'Write tasks'},
        {'name': 'task_execute', 'resource_type': 'task', 'action': 'execute', 'description': 'Execute tasks'},
        {'name': 'task_delete', 'resource_type': 'task', 'action': 'delete', 'description': 'Delete tasks'},
        
        # Deployment permissions
        {'name': 'deployment_request', 'resource_type': 'deployment', 'action': 'create', 'description': 'Request deployments'},
        {'name': 'deployment_approve', 'resource_type': 'deployment', 'action': 'write', 'description': 'Approve deployments'},
        {'name': 'deployment_manage', 'resource_type': 'deployment', 'action': 'admin', 'description': 'Manage deployments'},
        
        # ML Model permissions
        {'name': 'model_create', 'resource_type': 'model', 'action': 'create', 'description': 'Create ML models'},
        {'name': 'model_read', 'resource_type': 'model', 'action': 'read', 'description': 'Read ML models'},
        {'name': 'model_execute', 'resource_type': 'model', 'action': 'execute', 'description': 'Execute ML models'},
        {'name': 'model_delete', 'resource_type': 'model', 'action': 'delete', 'description': 'Delete ML models'},
        
        # System permissions
        {'name': 'system_admin', 'resource_type': 'system', 'action': 'admin', 'description': 'Full system administration'},
        {'name': 'user_manage', 'resource_type': 'user', 'action': 'admin', 'description': 'Manage users and groups'},
        {'name': 'audit_view', 'resource_type': 'audit', 'action': 'read', 'description': 'View audit logs'}
    ]
    
    for perm_data in permissions:
        perm = Permission.query.filter_by(name=perm_data['name']).first()
        if perm:
            print(f"Permission {perm_data['name']} already exists")
            continue
        
        perm = Permission(**perm_data)
        db.session.add(perm)
        db.session.commit()
        print(f"Created permission: {perm.name}")
    
    return Permission.query.all()


def create_group_permissions():
    """Assign permissions to groups"""
    from essentialpipeline.models.governance import group_permissions
    admin_group = Group.query.filter_by(name='admins').first()
    dev_group = Group.query.filter_by(name='developers').first()
    ds_group = Group.query.filter_by(name='data-scientists').first()
    analyst_group = Group.query.filter_by(name='analysts').first()
    
    if not admin_group:
        print("Admin group not found")
        return
    
    # Get all permissions
    all_permissions = Permission.query.all()
    
    # Admin group gets all permissions
    for perm in all_permissions:
        # Check if already assigned
        existing = db.session.query(group_permissions).filter_by(
            group_id=admin_group.id,
            permission_id=perm.id
        ).first()
        
        if not existing:
            db.session.execute(group_permissions.insert().values(
                group_id=admin_group.id,
                permission_id=perm.id
            ))
    
    print(f"Assigned all permissions to admin group")
    
    # Developer permissions
    dev_perms = [
        'db_read', 'db_write',
        'storage_read', 'storage_write',
        'project_create', 'project_read', 'project_write', 'project_execute',
        'task_read', 'task_write', 'task_execute'
    ]
    
    for perm_name in dev_perms:
        perm = Permission.query.filter_by(name=perm_name).first()
        if perm and dev_group:
            existing = db.session.query(group_permissions).filter_by(
                group_id=dev_group.id,
                permission_id=perm.id
            ).first()
            
            if not existing:
                db.session.execute(group_permissions.insert().values(
                    group_id=dev_group.id,
                    permission_id=perm.id
                ))
    
    print(f"Assigned developer permissions to developers group")
    
    # Data scientist permissions
    ds_perms = [
        'storage_read', 'storage_write',
        'project_read',
        'model_create', 'model_read', 'model_execute'
    ]
    
    for perm_name in ds_perms:
        perm = Permission.query.filter_by(name=perm_name).first()
        if perm and ds_group:
            existing = db.session.query(group_permissions).filter_by(
                group_id=ds_group.id,
                permission_id=perm.id
            ).first()
            
            if not existing:
                db.session.execute(group_permissions.insert().values(
                    group_id=ds_group.id,
                    permission_id=perm.id
                ))
    
    print(f"Assigned data scientist permissions to data-scientists group")
    
    db.session.commit()


def create_sample_connections():
    """Create sample database and storage connections"""
    envs = Environment.query.all()
    if not envs:
        print("No environments found, skipping connections")
        return
    
    # Create sample database connections
    db_connections = [
        {
            'name': 'Local MySQL',
            'connection_string': 'mysql+mysqlconnector://root:password@localhost:3306/essentialpipeline',
            'connection_type': 'mysql',
            'environment_id': Environment.query.filter_by(name='dev').first().id,
            'is_active': True
        }
    ]
    
    for conn_data in db_connections:
        # Encrypt connection string
        conn_data['connection_string_encrypted'] = encrypt_data(conn_data.pop('connection_string'))
        
        conn = DatabaseConnection.query.filter_by(name=conn_data['name']).first()
        if conn:
            print(f"Database connection {conn_data['name']} already exists")
            continue
        
        conn = DatabaseConnection(**conn_data)
        db.session.add(conn)
        db.session.commit()
        print(f"Created database connection: {conn.name}")
    
    # Create sample storage connections
    storage_connections = [
        {
            'name': 'Local Storage',
            'endpoint': 'http://localhost:3900',
            'bucket': 'essentialpipeline',
            'credentials': '{"access_key": "test", "secret_key": "test"}',
            'environment_id': Environment.query.filter_by(name='dev').first().id,
            'is_active': True
        }
    ]
    
    for conn_data in storage_connections:
        # Encrypt credentials
        conn_data['credentials_encrypted'] = encrypt_data(conn_data.pop('credentials'))
        
        conn = StorageConnection.query.filter_by(name=conn_data['name']).first()
        if conn:
            print(f"Storage connection {conn_data['name']} already exists")
            continue
        
        conn = StorageConnection(**conn_data)
        db.session.add(conn)
        db.session.commit()
        print(f"Created storage connection: {conn.name}")


def create_sample_clearances():
    """Create sample group-connection clearances"""
    admin_group = Group.query.filter_by(name='admins').first()
    dev_group = Group.query.filter_by(name='developers').first()
    
    if not admin_group or not dev_group:
        print("Groups not found, skipping clearances")
        return
    
    # Get connections
    db_conns = DatabaseConnection.query.all()
    storage_conns = StorageConnection.query.all()
    
    # Admin group gets admin access to everything
    for conn in db_conns:
        clearance = GroupConnectionClearance.query.filter_by(
            group_id=admin_group.id,
            connection_type='database',
            connection_id=conn.id
        ).first()
        
        if not clearance:
            clearance = GroupConnectionClearance(
                group_id=admin_group.id,
                connection_type='database',
                connection_id=conn.id,
                access_level='admin'
            )
            db.session.add(clearance)
    
    for conn in storage_conns:
        clearance = GroupConnectionClearance.query.filter_by(
            group_id=admin_group.id,
            connection_type='storage',
            connection_id=conn.id
        ).first()
        
        if not clearance:
            clearance = GroupConnectionClearance(
                group_id=admin_group.id,
                connection_type='storage',
                connection_id=conn.id,
                access_level='admin'
            )
            db.session.add(clearance)
    
    # Developer group gets read/write to dev connections
    for conn in db_conns:
        clearance = GroupConnectionClearance.query.filter_by(
            group_id=dev_group.id,
            connection_type='database',
            connection_id=conn.id
        ).first()
        
        if not clearance:
            clearance = GroupConnectionClearance(
                group_id=dev_group.id,
                connection_type='database',
                connection_id=conn.id,
                access_level='write'
            )
            db.session.add(clearance)
    
    for conn in storage_conns:
        clearance = GroupConnectionClearance.query.filter_by(
            group_id=dev_group.id,
            connection_type='storage',
            connection_id=conn.id
        ).first()
        
        if not clearance:
            clearance = GroupConnectionClearance(
                group_id=dev_group.id,
                connection_type='storage',
                connection_id=conn.id,
                access_level='write'
            )
            db.session.add(clearance)
    
    db.session.commit()
    print("Created sample group-connection clearances")


def assign_admin_to_groups():
    """Assign admin user to admin group"""
    admin = User.query.filter_by(username='admin').first()
    admin_group = Group.query.filter_by(name='admins').first()
    
    if not admin or not admin_group:
        print("Admin user or admin group not found")
        return
    
    # Check if already assigned
    from essentialpipeline.models.governance import user_groups
    existing = db.session.query(user_groups).filter_by(
        user_id=admin.id,
        group_id=admin_group.id
    ).first()
    
    if not existing:
        db.session.execute(user_groups.insert().values(
            user_id=admin.id,
            group_id=admin_group.id
        ))
        db.session.commit()
        print(f"Assigned admin user to admin group")


def main():
    """Main seed function"""
    print("Starting EssentialPipeline seed data creation...")
    print("=" * 50)
    
    # Create app
    app = create_app(config_env='development')
    
    with app.app_context():
        # Import table for many-to-many relationships
        from essentialpipeline.models.governance import user_groups, group_permissions
        
        # Create tables
        print("Creating database tables...")
        db.create_all()
        
        # Seed data
        print("\nSeeding environments...")
        create_environments()
        
        print("\nSeeding groups...")
        create_groups()
        
        print("\nSeeding permissions...")
        create_permissions()
        
        print("\nCreating admin user...")
        create_admin_user()
        
        print("\nAssigning permissions to groups...")
        create_group_permissions()
        
        print("\nAssigning admin to groups...")
        assign_admin_to_groups()
        
        print("\nCreating sample connections...")
        create_sample_connections()
        
        print("\nCreating sample clearances...")
        create_sample_clearances()
        
        print("\n" + "=" * 50)
        print("Seed data creation completed!")
        
        # Print summary
        print(f"\nSummary:")
        print(f"  Users: {User.query.count()}")
        print(f"  Groups: {Group.query.count()}")
        print(f"  Permissions: {Permission.query.count()}")
        print(f"  Environments: {Environment.query.count()}")
        print(f"  DB Connections: {DatabaseConnection.query.count()}")
        print(f"  Storage Connections: {StorageConnection.query.count()}")


if __name__ == '__main__':
    main()
