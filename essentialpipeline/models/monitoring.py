"""
Monitoring layer models for EssentialPipeline
"""

from essentialpipeline import db
from datetime import datetime


class DeploymentLog(db.Model):
    """Model for deployment logs"""
    
    __tablename__ = 'deployment_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deployment_id = db.Column(db.Integer, db.ForeignKey('deployments.id'), nullable=False)
    
    # Log info
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.Enum('debug', 'info', 'warning', 'error', 'critical'), default='info', nullable=False)
    message = db.Column(db.Text, nullable=False)
    context = db.Column(db.JSON)  # Additional structured data
    
    # Relationships
    deployment = db.relationship('Deployment', backref='deployment_logs', lazy=True)
    
    def to_dict(self):
        """Convert deployment log to dictionary"""
        return {
            'id': self.id,
            'deployment_id': self.deployment_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'message': self.message,
            'context': self.context
        }
    
    def to_sse(self):
        """Convert to SSE format"""
        import json
        return json.dumps({
            'type': 'deployment_log',
            'data': self.to_dict()
        })
    
    def __repr__(self):
        return f'<DeploymentLog {self.level}: {self.message[:50]}>'


class SecurityLog(db.Model):
    """Model for security scanning logs"""
    
    __tablename__ = 'security_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    parse_result_id = db.Column(db.Integer, db.ForeignKey('security_parse_results.id'))
    task_run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id'))
    
    # Log info
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.Enum('debug', 'info', 'warning', 'error', 'critical'), default='info', nullable=False)
    event_type = db.Column(db.String(50), nullable=False)  # 'scan_started', 'finding_detected', etc.
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.JSON)
    
    # Relationships
    parse_result = db.relationship('SecurityParseResult', backref='security_logs', lazy=True)
    task_run = db.relationship('TaskRun', backref='security_logs_list', lazy=True)
    
    def to_dict(self):
        """Convert security log to dictionary"""
        return {
            'id': self.id,
            'parse_result_id': self.parse_result_id,
            'task_run_id': self.task_run_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'event_type': self.event_type,
            'message': self.message,
            'details': self.details
        }
    
    def to_sse(self):
        """Convert to SSE format"""
        import json
        return json.dumps({
            'type': 'security_log',
            'data': self.to_dict()
        })
    
    def __repr__(self):
        return f'<SecurityLog {self.level}: {self.event_type}: {self.message[:50]}>'


class ExecutionLog(db.Model):
    """Model for task execution logs"""
    
    __tablename__ = 'execution_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_run_id = db.Column(db.Integer, db.ForeignKey('task_runs.id'), nullable=False)
    
    # Log info
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.Enum('debug', 'info', 'warning', 'error', 'critical'), default='info', nullable=False)
    message = db.Column(db.Text, nullable=False)
    stdout = db.Column(db.Text)
    stderr = db.Column(db.Text)
    
    # Relationships
    task_run = db.relationship('TaskRun', backref='execution_logs_list', lazy=True, foreign_keys=[task_run_id], overlaps='logs')
    
    def to_dict(self):
        """Convert execution log to dictionary"""
        return {
            'id': self.id,
            'task_run_id': self.task_run_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'message': self.message,
            'stdout': self.stdout,
            'stderr': self.stderr
        }
    
    def to_sse(self):
        """Convert to SSE format for streaming"""
        import json
        return json.dumps({
            'id': self.id,
            'task_run_id': self.task_run_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'message': self.message
        })
    
    def __repr__(self):
        return f'<ExecutionLog {self.level}: {self.message[:50]}>'


class SystemMetric(db.Model):
    """Model for system metrics"""
    
    __tablename__ = 'system_metrics'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Metric info
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    metric_type = db.Column(db.String(50), nullable=False)  # 'cpu_usage', 'memory_usage', 'disk_usage'
    metric_value = db.Column(db.Float, nullable=False)
    host = db.Column(db.String(255))
    additional_data = db.Column(db.JSON)
    
    def to_dict(self):
        """Convert system metric to dictionary"""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'metric_type': self.metric_type,
            'metric_value': self.metric_value,
            'host': self.host,
            'additional_data': self.additional_data
        }
    
    def __repr__(self):
        return f'<SystemMetric {self.metric_type}={self.metric_value}>'


class Alert(db.Model):
    """Model for alerts"""
    
    __tablename__ = 'alerts'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    alert_rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id'), nullable=False)
    
    # Alert info
    severity = db.Column(db.Enum('low', 'medium', 'high', 'critical'), default='medium', nullable=False)
    status = db.Column(db.Enum('open', 'acknowledged', 'resolved'), default='open', nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    
    # Timestamps
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    acknowledged_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    
    # Resolution info
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolution_notes = db.Column(db.Text)
    
    # Relationships
    alert_rule = db.relationship('AlertRule', backref='alerts', lazy=True)
    resolved_by_user = db.relationship('User', backref='resolved_alerts', foreign_keys=[resolved_by])
    
    def to_dict(self):
        """Convert alert to dictionary"""
        return {
            'id': self.id,
            'alert_rule_id': self.alert_rule_id,
            'severity': self.severity,
            'status': self.status,
            'title': self.title,
            'message': self.message,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by': self.resolved_by,
            'resolution_notes': self.resolution_notes
        }
    
    def __repr__(self):
        return f'<Alert {self.severity}: {self.title}>'


class AlertRule(db.Model):
    """Model for alert rules"""
    
    __tablename__ = 'alert_rules'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Rule info
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    condition_type = db.Column(db.String(50), nullable=False)  # 'threshold', 'anomaly', 'absence'
    condition_config = db.Column(db.JSON, nullable=False)  # Configuration for the condition
    
    # Notification
    notification_channels = db.Column(db.JSON, nullable=False)  # ['email', 'slack', 'webhook']
    notification_targets = db.Column(db.JSON)  # Email addresses, Slack channels, etc.
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert alert rule to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'condition_type': self.condition_type,
            'condition_config': self.condition_config,
            'notification_channels': self.notification_channels,
            'notification_targets': self.notification_targets,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<AlertRule {self.name}>'
