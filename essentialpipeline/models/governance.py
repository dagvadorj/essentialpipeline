"""
Governance layer models for EssentialPipeline
"""

from essentialpipeline import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json


class User(db.Model):
    """User model representing a system user"""
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # User info
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    groups = db.relationship('Group', secondary='user_groups', lazy='select', backref=db.backref('users', lazy=True))
    projects = db.relationship('Project', backref='owner', lazy=True, foreign_keys='Project.owner_user_id')
    
    @property
    def password(self):
        """Password setter"""
        raise AttributeError('password is not a readable attribute')
    
    @password.setter
    def password(self, password):
        """Password setter - hashes the password"""
        self.password_hash = generate_password_hash(password)
    
    def verify_password(self, password):
        """Verify the password against the hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_full_name(self):
        """Get the user's full name"""
        return f"{self.first_name} {self.last_name}" if self.first_name or self.last_name else self.username
    
    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'is_active': self.is_active,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
    
    def __repr__(self):
        return f'<User {self.username}>'


# Many-to-many relationship table for User-Group
user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True)
)


class Group(db.Model):
    """Group model for user grouping and permission management"""
    
    __tablename__ = 'groups'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    permissions = db.relationship('Permission', secondary='group_permissions', lazy='select', backref=db.backref('groups', lazy=True))
    connection_clearances = db.relationship('GroupConnectionClearance', backref='group', lazy=True)
    
    def to_dict(self):
        """Convert group to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Group {self.name}>'


# Many-to-many relationship table for Group-Permission
group_permissions = db.Table('group_permissions',
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'), primary_key=True)
)


class Permission(db.Model):
    """Permission model for defining what actions can be performed on resources"""
    
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)  # 'database', 'storage', 'project', 'task', etc.
    action = db.Column(db.String(50), nullable=False)  # 'read', 'write', 'admin', 'execute', 'delete'
    description = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert permission to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'resource_type': self.resource_type,
            'action': self.action,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<Permission {self.name}: {self.resource_type}.{self.action}>'


class Environment(db.Model):
    """Environment model for defining deployment environments (dev, qa, prod)"""
    
    __tablename__ = 'environments'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # 'dev', 'qa', 'prod'
    description = db.Column(db.Text)
    is_production = db.Column(db.Boolean, default=False)
    
    # Configuration (JSON)
    config = db.Column(db.JSON)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    database_connections = db.relationship('DatabaseConnection', backref='environment', lazy=True)
    storage_connections = db.relationship('StorageConnection', backref='environment', lazy=True)
    # Deployment.environment (in deployment.py) already provides the reverse side
    # via its own backref='environment_deployments'; a second relationship here
    # would create a duplicate/conflicting 'environment' attribute on Deployment.
    
    def to_dict(self):
        """Convert environment to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_production': self.is_production,
            'config': self.config,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<Environment {self.name}>'


class DatabaseConnection(db.Model):
    """Database connection model for storing connection details"""
    
    __tablename__ = 'database_connections'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), nullable=False)
    connection_string_encrypted = db.Column(db.Text, nullable=False)
    connection_type = db.Column(db.String(50), nullable=False)  # 'mysql', 'postgresql', 'sqlite', etc.
    environment_id = db.Column(db.Integer, db.ForeignKey('environments.id'))
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Note: GroupConnectionClearance.connection_id is a polymorphic reference
    # (points at either database_connections.id or storage_connections.id, keyed
    # by connection_type) with no real ForeignKey, so it can't be modeled as a
    # SQLAlchemy relationship here. Query GroupConnectionClearance directly by
    # connection_id/connection_type instead.

    def decrypt_connection_string(self):
        """Decrypt the connection string"""
        from essentialpipeline.utils.security import decrypt_data
        try:
            return decrypt_data(self.connection_string_encrypted)
        except Exception:
            return None
    
    def to_dict(self):
        """Convert database connection to dictionary (without sensitive data)"""
        return {
            'id': self.id,
            'name': self.name,
            'connection_type': self.connection_type,
            'environment_id': self.environment_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<DatabaseConnection {self.name} ({self.connection_type})>'


class StorageConnection(db.Model):
    """Storage connection model for object storage (Garage, S3, etc.)"""
    
    __tablename__ = 'storage_connections'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(80), nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    bucket = db.Column(db.String(80), nullable=False)
    credentials_encrypted = db.Column(db.Text, nullable=False)
    environment_id = db.Column(db.Integer, db.ForeignKey('environments.id'))
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Note: GroupConnectionClearance.connection_id is a polymorphic reference
    # (points at either database_connections.id or storage_connections.id, keyed
    # by connection_type) with no real ForeignKey, so it can't be modeled as a
    # SQLAlchemy relationship here. Query GroupConnectionClearance directly by
    # connection_id/connection_type instead.

    def decrypt_credentials(self):
        """Decrypt the credentials"""
        from essentialpipeline.utils.security import decrypt_data
        try:
            return decrypt_data(self.credentials_encrypted)
        except Exception:
            return None
    
    def to_dict(self):
        """Convert storage connection to dictionary (without sensitive data)"""
        return {
            'id': self.id,
            'name': self.name,
            'endpoint': self.endpoint,
            'bucket': self.bucket,
            'environment_id': self.environment_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<StorageConnection {self.name} ({self.endpoint}/{self.bucket})>'


class GroupConnectionClearance(db.Model):
    """Model for defining which groups have access to which connections"""
    
    __tablename__ = 'group_connection_clearances'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    connection_type = db.Column(db.Enum('database', 'storage'), nullable=False)
    connection_id = db.Column(db.Integer, nullable=False)
    access_level = db.Column(db.Enum('none', 'read', 'write', 'admin'), default='none', nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert clearance to dictionary"""
        return {
            'id': self.id,
            'group_id': self.group_id,
            'connection_type': self.connection_type,
            'connection_id': self.connection_id,
            'access_level': self.access_level,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Clearance group={self.group_id} {self.connection_type}={self.connection_id}: {self.access_level}>'


class AuditLog(db.Model):
    """Audit log model for tracking user actions"""
    
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)  # 'create', 'read', 'update', 'delete', 'execute'
    resource_type = db.Column(db.String(50), nullable=False)  # 'user', 'group', 'project', 'task', etc.
    resource_id = db.Column(db.Integer)
    resource_name = db.Column(db.String(255))
    details = db.Column(db.JSON)  # Additional context
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    
    # Timestamps
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = db.relationship('User', backref='audit_logs', lazy=True)
    
    def to_dict(self):
        """Convert audit log to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'resource_name': self.resource_name,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
    
    def __repr__(self):
        return f'<AuditLog user={self.user_id} action={self.action} resource={self.resource_type}({self.resource_id})>'
