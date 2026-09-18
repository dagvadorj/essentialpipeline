"""
Database models for EssentialPipeline
"""

from essentialpipeline import db
from datetime import datetime

# Import all models to register them with SQLAlchemy
from essentialpipeline.models.governance import (
    User, Group, Permission, Environment,
    DatabaseConnection, StorageConnection,
    GroupConnectionClearance, AuditLog
)
from essentialpipeline.models.execution import (
    Project, ProjectVersion, ProjectFile,
    Task, TaskRun, TaskDependency,
    ExecutionEnvironment, Dependency,
    DependencyCache, SecurityParseResult,
    SecurityFinding, DataGenerationRequest,
    GeneratedDataset, PromptTemplate
)
from essentialpipeline.models.monitoring import (
    DeploymentLog, SecurityLog,
    ExecutionLog, SystemMetric,
    Alert, AlertRule
)
from essentialpipeline.models.deployment import (
    Deployment, Approval, MLModel,
    MLModelVersion, MLModelExecution
)

__all__ = [
    # Governance
    'User', 'Group', 'Permission', 'Environment',
    'DatabaseConnection', 'StorageConnection',
    'GroupConnectionClearance', 'AuditLog',
    
    # Execution
    'Project', 'ProjectVersion', 'ProjectFile',
    'Task', 'TaskRun', 'TaskDependency',
    'ExecutionEnvironment', 'Dependency',
    'DependencyCache', 'SecurityParseResult',
    'SecurityFinding', 'DataGenerationRequest',
    'GeneratedDataset', 'PromptTemplate',
    
    # Monitoring
    'DeploymentLog', 'SecurityLog',
    'ExecutionLog', 'SystemMetric',
    'Alert', 'AlertRule',
    
    # Deployment
    'Deployment', 'Approval', 'MLModel',
    'MLModelVersion', 'MLModelExecution'
]
