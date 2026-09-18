"""
Execution layer models for EssentialPipeline
"""

from essentialpipeline import db
from datetime import datetime
from essentialpipeline.models.governance import User


class Project(db.Model):
    """Project model representing a user's pipeline project"""
    
    __tablename__ = 'projects'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Ownership
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Current version
    current_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id', use_alter=True, name='fk_projects_current_version_id'))
    
    # Storage
    storage_path = db.Column(db.String(512))  # Path to project files
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(50), default='draft')  # draft, active, archived, error
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    versions = db.relationship('ProjectVersion', backref='project', lazy=True, order_by='desc(ProjectVersion.created_at)', foreign_keys='ProjectVersion.project_id')
    # Task.project and MLModel.project (below) already define their own explicit
    # backrefs (tasks_list / ml_models_list), so these two must not also set
    # backref='project' - that would create a duplicate 'project' attribute.
    tasks = db.relationship('Task', lazy=True, foreign_keys='Task.project_id', overlaps='tasks_list')
    models = db.relationship('MLModel', lazy=True, foreign_keys='MLModel.project_id', overlaps='ml_models_list')
    current_version = db.relationship('ProjectVersion', foreign_keys=[current_version_id])
    
    @property
    def status_color(self):
        """Get bootstrap color class for status"""
        status_colors = {
            'active': 'success',
            'draft': 'secondary',
            'archived': 'warning',
            'error': 'danger'
        }
        return status_colors.get(self.status, 'secondary')
    
    def to_dict(self):
        """Convert project to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'owner_user_id': self.owner_user_id,
            'current_version_id': self.current_version_id,
            'storage_path': self.storage_path,
            'is_active': self.is_active,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Project {self.name}>'


class ProjectVersion(db.Model):
    """Project version model for tracking project versions"""
    
    __tablename__ = 'project_versions'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    version = db.Column(db.String(50), nullable=False)  # e.g., '1.0.0', '2.1.3'
    changelog = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    files = db.relationship('ProjectFile', backref='project_version', lazy=True)
    # Task.project_version (below) already defines its own explicit backref
    # (tasks_list), so this must not also set backref='project_version'.
    tasks = db.relationship('Task', lazy=True, foreign_keys='Task.project_version_id', overlaps='tasks_list')
    
    def to_dict(self):
        """Convert project version to dictionary"""
        return {
            'id': self.id,
            'project_id': self.project_id,
            'version': self.version,
            'changelog': self.changelog,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<ProjectVersion {self.project.name if self.project else "?"} v{self.version}>'


class ProjectFile(db.Model):
    """Project file model for tracking files in project versions"""
    
    __tablename__ = 'project_files'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id'), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)  # Path within project
    file_size = db.Column(db.Integer)
    file_hash = db.Column(db.String(64))  # SHA-256
    storage_path = db.Column(db.String(512))  # Path in object storage
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert project file to dictionary"""
        return {
            'id': self.id,
            'project_version_id': self.project_version_id,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'file_hash': self.file_hash,
            'storage_path': self.storage_path,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<ProjectFile {self.file_path}>'


class Task(db.Model):
    """Task model representing a pipeline task"""
    
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    project_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id'))
    
    # Task definition
    name = db.Column(db.String(255), nullable=False)
    task_type = db.Column(db.Enum('python', 'sql', 'bash', 'ml_model'), default='python', nullable=False)
    script_path = db.Column(db.String(512))  # Path to script within project
    
    # Scheduling
    schedule_cron = db.Column(db.String(100))  # e.g., '0 * * * *' for hourly
    is_active = db.Column(db.Boolean, default=True)
    
    # Status tracking
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    project = db.relationship('Project', backref=db.backref('tasks_list', lazy=True), foreign_keys=[project_id], overlaps='tasks')
    project_version = db.relationship('ProjectVersion', backref=db.backref('tasks_list', lazy=True), foreign_keys=[project_version_id], overlaps='tasks')
    runs = db.relationship('TaskRun', backref='task', lazy=True, foreign_keys='TaskRun.task_id')
    # TaskDependency.task and TaskDependency.depends_on (below) already define
    # their own explicit backrefs, so these must not also set backref=.
    dependencies = db.relationship('TaskDependency', lazy=True, foreign_keys='TaskDependency.task_id', overlaps='dependencies_list')
    dependent_tasks = db.relationship('TaskDependency', lazy=True, foreign_keys='TaskDependency.depends_on_task_id', overlaps='dependents')
    
    @property
    def status_color(self):
        """Get bootstrap color class for status"""
        if self.is_active:
            return 'success'
        return 'secondary'
    
    def to_dict(self):
        """Convert task to dictionary"""
        return {
            'id': self.id,
            'project_id': self.project_id,
            'project_version_id': self.project_version_id,
            'name': self.name,
            'task_type': self.task_type,
            'script_path': self.script_path,
            'schedule_cron': self.schedule_cron,
            'is_active': self.is_active,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<Task {self.name}>'


class TaskRun(db.Model):
    """Task run model for tracking task executions"""
    
    __tablename__ = 'task_runs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    
    # Execution info
    status = db.Column(db.Enum('pending', 'running', 'success', 'failed', 'skipped', 'cancelled'), default='pending', nullable=False)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)
    
    # Trigger info
    triggered_by = db.Column(db.Enum('scheduler', 'manual', 'api', 'upstream'), default='manual', nullable=False)
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Execution environment
    execution_environment_id = db.Column(db.Integer, db.ForeignKey('execution_environments.id'))
    
    # Logs and results
    log_file_path = db.Column(db.String(512))
    output_path = db.Column(db.String(512))
    error_message = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    triggered_by_user = db.relationship('User', backref='triggered_runs', foreign_keys=[triggered_by_user_id])
    execution_environment = db.relationship('ExecutionEnvironment', backref='task_runs', foreign_keys=[execution_environment_id])
    # ExecutionLog.task_run and MLModelExecution.task_run already define their
    # own explicit backrefs (in monitoring.py / deployment.py), so these must
    # not also set backref='task_run'.
    logs = db.relationship('ExecutionLog', lazy=True, foreign_keys='ExecutionLog.task_run_id', overlaps='execution_logs_list')
    ml_executions = db.relationship('MLModelExecution', lazy=True, foreign_keys='MLModelExecution.task_run_id', overlaps='ml_model_executions_list')
    
    @property
    def status_color(self):
        """Get bootstrap color class for status"""
        status_colors = {
            'pending': 'secondary',
            'running': 'primary',
            'success': 'success',
            'failed': 'danger',
            'skipped': 'warning',
            'cancelled': 'danger'
        }
        return status_colors.get(self.status, 'secondary')
    
    def to_dict(self):
        """Convert task run to dictionary"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'status': self.status,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds,
            'triggered_by': self.triggered_by,
            'triggered_by_user_id': self.triggered_by_user_id,
            'execution_environment_id': self.execution_environment_id,
            'log_file_path': self.log_file_path,
            'output_path': self.output_path,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<TaskRun {self.id} ({self.status})>'


class TaskDependency(db.Model):
    """Model for task dependencies (DAG edges)"""
    
    __tablename__ = 'task_dependencies'
    
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), primary_key=True, nullable=False)
    depends_on_task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), primary_key=True, nullable=False)
    
    # Relationships
    task = db.relationship('Task', backref=db.backref('dependencies_list', lazy=True), foreign_keys=[task_id], overlaps='dependencies')
    depends_on = db.relationship('Task', backref=db.backref('dependents', lazy=True), foreign_keys=[depends_on_task_id], overlaps='dependent_tasks')
    
    def to_dict(self):
        """Convert task dependency to dictionary"""
        return {
            'task_id': self.task_id,
            'depends_on_task_id': self.depends_on_task_id
        }
    
    def __repr__(self):
        return f'<TaskDependency {self.task_id} -> {self.depends_on_task_id}>'


class ExecutionEnvironment(db.Model):
    """Model for execution environments (Docker containers)"""
    
    __tablename__ = 'execution_environments'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id', use_alter=True, name='fk_execution_environments_task_run_id'))
    
    # Container info
    container_id = db.Column(db.String(255))  # Docker container ID
    image_name = db.Column(db.String(255))
    status = db.Column(db.Enum('creating', 'ready', 'running', 'stopped', 'failed', 'cleaned_up'), default='creating', nullable=False)
    
    # Resource limits
    resource_cpu = db.Column(db.Integer)  # in millicores
    resource_memory = db.Column(db.Integer)  # in MB
    
    # Network configuration
    network_mode = db.Column(db.Enum('default', 'none', 'host', 'bridge'), default='default', nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    task_run = db.relationship('TaskRun', backref='execution_environment_list', foreign_keys=[task_run_id])
    
    def to_dict(self):
        """Convert execution environment to dictionary"""
        return {
            'id': self.id,
            'task_run_id': self.task_run_id,
            'container_id': self.container_id,
            'image_name': self.image_name,
            'status': self.status,
            'resource_cpu': self.resource_cpu,
            'resource_memory': self.resource_memory,
            'network_mode': self.network_mode,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<ExecutionEnvironment {self.container_id[:12] if self.container_id else "?"} ({self.status})>'


class Dependency(db.Model):
    """Model for project dependencies"""
    
    __tablename__ = 'dependencies'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id'), nullable=False)
    
    # Dependency info
    name = db.Column(db.String(255), nullable=False)
    version_spec = db.Column(db.String(255), nullable=False)  # e.g., '==1.0.0', '>=2.0'
    resolved_version = db.Column(db.String(50))  # Actual installed version
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    project_version = db.relationship('ProjectVersion', backref='dependencies', lazy=True)
    cache = db.relationship('DependencyCache', backref='dependency', lazy=True, uselist=False)
    
    def to_dict(self):
        """Convert dependency to dictionary"""
        return {
            'id': self.id,
            'project_version_id': self.project_version_id,
            'name': self.name,
            'version_spec': self.version_spec,
            'resolved_version': self.resolved_version,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<Dependency {self.name} {self.version_spec}>'


class DependencyCache(db.Model):
    """Model for cached dependencies"""
    
    __tablename__ = 'dependency_cache'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dependency_id = db.Column(db.Integer, db.ForeignKey('dependencies.id'), nullable=False, unique=True)
    
    # Cache info
    cache_path = db.Column(db.String(512), nullable=False)  # Path to cached package
    cache_size = db.Column(db.Integer)
    cache_hash = db.Column(db.String(64))  # SHA-256
    
    # Timestamps
    cached_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert dependency cache to dictionary"""
        return {
            'id': self.id,
            'dependency_id': self.dependency_id,
            'cache_path': self.cache_path,
            'cache_size': self.cache_size,
            'cache_hash': self.cache_hash,
            'cached_at': self.cached_at.isoformat() if self.cached_at else None
        }
    
    def __repr__(self):
        return f'<DependencyCache {self.cache_path}>'


class SecurityParseResult(db.Model):
    """Model for security parsing results"""
    
    __tablename__ = 'security_parse_results'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_version_id = db.Column(db.Integer, db.ForeignKey('project_versions.id'), nullable=False)
    
    # Parse info
    parser_version = db.Column(db.String(50))
    overall_status = db.Column(db.Enum('passed', 'warning', 'failed'), default='passed', nullable=False)
    
    # Timestamps
    parsed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    project_version = db.relationship('ProjectVersion', backref='security_parse_results', lazy=True)
    findings = db.relationship('SecurityFinding', backref='parse_result', lazy=True)
    
    def to_dict(self):
        """Convert security parse result to dictionary"""
        return {
            'id': self.id,
            'project_version_id': self.project_version_id,
            'parser_version': self.parser_version,
            'overall_status': self.overall_status,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None
        }
    
    def __repr__(self):
        return f'<SecurityParseResult {self.id} ({self.overall_status})>'


class SecurityFinding(db.Model):
    """Model for individual security findings"""
    
    __tablename__ = 'security_findings'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    parse_result_id = db.Column(db.Integer, db.ForeignKey('security_parse_results.id'), nullable=False)
    
    # Finding info
    severity = db.Column(db.Enum('low', 'medium', 'high', 'critical'), default='medium', nullable=False)
    finding_type = db.Column(db.String(50), nullable=False)  # 'import', 'dependency', 'code_pattern'
    description = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.String(512))
    line_number = db.Column(db.Integer)
    code_snippet = db.Column(db.Text)
    recommendation = db.Column(db.Text)
    
    def to_dict(self):
        """Convert security finding to dictionary"""
        return {
            'id': self.id,
            'parse_result_id': self.parse_result_id,
            'severity': self.severity,
            'finding_type': self.finding_type,
            'description': self.description,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'code_snippet': self.code_snippet,
            'recommendation': self.recommendation
        }
    
    def __repr__(self):
        return f'<SecurityFinding {self.severity}: {self.description[:50]}>'


class DataGenerationRequest(db.Model):
    """Model for LLM-powered data generation requests"""
    
    __tablename__ = 'data_generation_requests'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    prompt_template_id = db.Column(db.Integer, db.ForeignKey('prompt_templates.id'))
    
    # Request info
    data_type = db.Column(db.String(50), nullable=False)  # 'csv', 'json', 'parquet', etc.
    data_schema = db.Column(db.JSON, nullable=False)  # Description of desired data structure
    num_rows = db.Column(db.Integer, default=100)
    
    # Status
    status = db.Column(db.Enum('pending', 'processing', 'completed', 'failed'), default='pending', nullable=False)
    
    # Results
    result_path = db.Column(db.String(512))  # Path to generated data
    error_message = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    project = db.relationship('Project', backref='data_generation_requests', lazy=True)
    requested_by_user = db.relationship('User', backref='data_generation_requests_list', foreign_keys=[requested_by])
    prompt_template = db.relationship('PromptTemplate', backref='data_generation_requests', lazy=True)
    
    def to_dict(self):
        """Convert data generation request to dictionary"""
        return {
            'id': self.id,
            'project_id': self.project_id,
            'requested_by': self.requested_by,
            'prompt_template_id': self.prompt_template_id,
            'data_type': self.data_type,
            'data_schema': self.data_schema,
            'num_rows': self.num_rows,
            'status': self.status,
            'result_path': self.result_path,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
    
    def __repr__(self):
        return f'<DataGenerationRequest {self.id} ({self.status})>'


class GeneratedDataset(db.Model):
    """Model for generated datasets"""
    
    __tablename__ = 'generated_datasets'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    request_id = db.Column(db.Integer, db.ForeignKey('data_generation_requests.id'), nullable=False)
    
    # Dataset info
    name = db.Column(db.String(255))
    description = db.Column(db.Text)
    data_type = db.Column(db.String(50), nullable=False)
    
    # Storage
    storage_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer)
    
    # Metadata
    metadata_json = db.Column('metadata', db.JSON)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    request = db.relationship('DataGenerationRequest', backref='generated_datasets', lazy=True)
    
    def to_dict(self):
        """Convert generated dataset to dictionary"""
        return {
            'id': self.id,
            'request_id': self.request_id,
            'name': self.name,
            'description': self.description,
            'data_type': self.data_type,
            'storage_path': self.storage_path,
            'file_size': self.file_size,
            'metadata': self.metadata_json,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<GeneratedDataset {self.name}>'


class PromptTemplate(db.Model):
    """Model for LLM prompt templates"""
    
    __tablename__ = 'prompt_templates'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    template_type = db.Column(db.String(50), nullable=False)  # 'csv', 'json', 'tabular', etc.
    template_text = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert prompt template to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'template_type': self.template_type,
            'template_text': self.template_text,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<PromptTemplate {self.name}>'
