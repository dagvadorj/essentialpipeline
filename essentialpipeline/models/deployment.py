"""
Deployment and ML Model models for EssentialPipeline
"""

from essentialpipeline import db
from datetime import datetime
from essentialpipeline.models.governance import User, Environment


class Deployment(db.Model):
    """Model for project deployments across environments"""
    
    __tablename__ = 'deployments'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id'), nullable=False)
    environment_id = db.Column(db.Integer, db.ForeignKey('environments.id'), nullable=False)
    
    # Deployment info
    status = db.Column(db.Enum(
        'pending', 'approved_qa', 'rejected_qa', 
        'approved_prod', 'rejected_prod', 'deployed', 
        'failed', 'rolled_back'
    ), default='pending', nullable=False)
    
    # Request info
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Deployment timestamps
    deployed_at = db.Column(db.DateTime)
    rollback_at = db.Column(db.DateTime)
    rollback_reason = db.Column(db.Text)
    
    # Relationships
    project_version = db.relationship('ProjectVersion', backref='deployments', lazy=True)
    environment = db.relationship('Environment', backref='environment_deployments', lazy=True)
    requested_by_user = db.relationship('User', backref='requested_deployments', foreign_keys=[requested_by])
    # Approval.deployment already defines its own explicit backref, so this
    # must not also set backref='deployment'.
    approvals = db.relationship('Approval', lazy=True, overlaps='approvals_list')
    # DeploymentLog.deployment (monitoring.py) already defines an explicit
    # relationship with backref='deployment_logs', which provides this same
    # attribute - declaring it again here too would collide.
    
    @property
    def status_color(self):
        """Get bootstrap color class for status"""
        status_colors = {
            'pending': 'secondary',
            'approved_qa': 'primary',
            'rejected_qa': 'danger',
            'approved_prod': 'success',
            'rejected_prod': 'danger',
            'deployed': 'success',
            'failed': 'danger',
            'rolled_back': 'warning'
        }
        return status_colors.get(self.status, 'secondary')
    
    def to_dict(self):
        """Convert deployment to dictionary"""
        return {
            'id': self.id,
            'project_version_id': self.project_version_id,
            'environment_id': self.environment_id,
            'status': self.status,
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None,
            'rollback_at': self.rollback_at.isoformat() if self.rollback_at else None,
            'rollback_reason': self.rollback_reason
        }
    
    def __repr__(self):
        return f'<Deployment {self.id} ({self.status})>'


class Approval(db.Model):
    """Model for deployment approvals"""
    
    __tablename__ = 'approvals'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deployment_id = db.Column(db.Integer, db.ForeignKey('deployments.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Approval info
    approval_type = db.Column(db.Enum('qa', 'prod'), nullable=False)
    status = db.Column(db.Enum('pending', 'approved', 'rejected'), default='pending', nullable=False)
    comments = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    
    # Relationships
    deployment = db.relationship('Deployment', backref='approvals_list', lazy=True, foreign_keys=[deployment_id], overlaps='approvals')
    approver = db.relationship('User', backref='approvals_given', foreign_keys=[approver_id])
    
    def to_dict(self):
        """Convert approval to dictionary"""
        return {
            'id': self.id,
            'deployment_id': self.deployment_id,
            'approver_id': self.approver_id,
            'approval_type': self.approval_type,
            'status': self.status,
            'comments': self.comments,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None
        }
    
    def __repr__(self):
        return f'<Approval {self.approval_type} by {self.approver_id}: {self.status}>'


class MLModel(db.Model):
    """Model for ML models"""
    
    __tablename__ = 'ml_models'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'))
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Model info
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    model_type = db.Column(db.String(100))  # 'classification', 'regression', 'llm', etc.
    
    # Current version
    current_version_id = db.Column(db.Integer, db.ForeignKey('ml_model_versions.id', use_alter=True, name='fk_ml_models_current_version_id'))
    
    # Storage
    storage_path = db.Column(db.String(512))  # Path to model artifacts
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref=db.backref('ml_models_list', lazy=True), foreign_keys=[project_id], overlaps='models')
    owner = db.relationship('User', backref='ml_models_owned', foreign_keys=[owner_user_id])
    versions = db.relationship('MLModelVersion', backref='ml_model', lazy=True, order_by='desc(MLModelVersion.created_at)', foreign_keys='MLModelVersion.model_id', overlaps='model,ml_model_versions_list')
    executions = db.relationship('MLModelExecution', backref='ml_model', lazy=True, foreign_keys='MLModelExecution.model_id', overlaps='model,ml_model_executions_list')
    
    def to_dict(self):
        """Convert ML model to dictionary"""
        return {
            'id': self.id,
            'project_id': self.project_id,
            'owner_user_id': self.owner_user_id,
            'name': self.name,
            'description': self.description,
            'model_type': self.model_type,
            'current_version_id': self.current_version_id,
            'storage_path': self.storage_path,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<MLModel {self.name}>'


class MLModelVersion(db.Model):
    """Model for ML model versions"""
    
    __tablename__ = 'ml_model_versions'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    model_id = db.Column(db.Integer, db.ForeignKey('ml_models.id'), nullable=False)
    
    # Version info
    version = db.Column(db.String(50), nullable=False)  # e.g., '1.0.0'
    framework = db.Column(db.String(50))  # 'pytorch', 'tensorflow', 'sklearn', etc.
    framework_version = db.Column(db.String(50))
    
    # Metadata
    metadata_json = db.Column('metadata', db.JSON)  # Training params, performance metrics, etc.
    
    # Storage
    artifact_path = db.Column(db.String(512))
    artifact_size = db.Column(db.Integer)
    artifact_hash = db.Column(db.String(64))  # SHA-256
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    model = db.relationship('MLModel', backref=db.backref('ml_model_versions_list', overlaps='ml_model,versions'), lazy=True, foreign_keys=[model_id], overlaps='ml_model')
    # MLModelExecution.model_version (below) already defines its own explicit
    # backref, so this must not also set backref='model_version'.
    executions = db.relationship('MLModelExecution', lazy=True, foreign_keys='MLModelExecution.model_version_id', overlaps='ml_model_executions_list')
    
    def to_dict(self):
        """Convert ML model version to dictionary"""
        return {
            'id': self.id,
            'model_id': self.model_id,
            'version': self.version,
            'framework': self.framework,
            'framework_version': self.framework_version,
            'metadata': self.metadata_json,
            'artifact_path': self.artifact_path,
            'artifact_size': self.artifact_size,
            'artifact_hash': self.artifact_hash,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<MLModelVersion {self.model.name if self.model else "?"} v{self.version}>'


class MLModelExecution(db.Model):
    """Model for ML model executions"""
    
    __tablename__ = 'ml_model_executions'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    model_id = db.Column(db.Integer, db.ForeignKey('ml_models.id'))
    model_version_id = db.Column(db.Integer, db.ForeignKey('ml_model_versions.id'))
    task_run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id'))
    
    # Execution info
    input_data = db.Column(db.JSON, nullable=False)
    output_data = db.Column(db.JSON)
    status = db.Column(db.Enum('pending', 'running', 'success', 'failed'), default='pending', nullable=False)
    
    # Timestamps
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    
    # Error info
    error_message = db.Column(db.Text)
    
    # Relationships
    model = db.relationship('MLModel', backref=db.backref('ml_model_executions_list', overlaps='ml_model,executions'), lazy=True, foreign_keys=[model_id], overlaps='ml_model')
    model_version = db.relationship('MLModelVersion', backref='ml_model_executions_list', lazy=True, foreign_keys=[model_version_id], overlaps='executions')
    task_run = db.relationship('TaskRun', backref='ml_model_executions_list', lazy=True, foreign_keys=[task_run_id], overlaps='ml_executions')
    
    def to_dict(self):
        """Convert ML model execution to dictionary"""
        return {
            'id': self.id,
            'model_id': self.model_id,
            'model_version_id': self.model_version_id,
            'task_run_id': self.task_run_id,
            'input_data': self.input_data,
            'output_data': self.output_data,
            'status': self.status,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds,
            'error_message': self.error_message
        }
    
    def __repr__(self):
        return f'<MLModelExecution {self.id} ({self.status})>'
