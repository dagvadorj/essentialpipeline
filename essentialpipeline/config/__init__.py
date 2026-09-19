"""
Configuration management for EssentialPipeline
"""

import os
from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration"""
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    ENV = os.environ.get('FLASK_ENV', 'development')
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'mysql+mysqlconnector://root:password@localhost:3309/essentialpipeline'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    
    # JWT Authentication
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ALGORITHM = 'HS256'
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 3600))  # 1 hour
    JWT_REFRESH_TOKEN_EXPIRES = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', 86400))  # 1 day

    # Accept the JWT from either an Authorization header (API clients) or an
    # httponly cookie (browser session for the /user/* and /admin/* web UI).
    JWT_TOKEN_LOCATION = ['headers', 'cookies']
    JWT_COOKIE_SECURE = os.environ.get('JWT_COOKIE_SECURE', 'False').lower() == 'true'
    JWT_COOKIE_SAMESITE = 'Lax'
    # No CSRF protection exists anywhere else in this app yet (no Flask-WTF
    # CSRFProtect, no tokens in any existing form) - disabling it here keeps
    # the cookie bridge consistent with that baseline rather than silently
    # fixing only this one path. Revisit together when forms get CSRF tokens.
    JWT_COOKIE_CSRF_PROTECT = False
    
    # Scheduler
    SCHEDULER_ENABLED = os.environ.get('SCHEDULER_ENABLED', 'True').lower() == 'true'
    SCHEDULER_MAX_WORKERS = int(os.environ.get('SCHEDULER_MAX_WORKERS', 10))
    
    # Uploads
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB
    ALLOWED_EXTENSIONS = {'zip', 'py', 'txt', 'json', 'yaml', 'yml'}
    
    # Execution
    DOCKER_ENABLED = os.environ.get('DOCKER_ENABLED', 'True').lower() == 'true'
    EXECUTION_TIMEOUT = int(os.environ.get('EXECUTION_TIMEOUT', 3600))  # 1 hour
    
    # Security
    SECURITY_SCAN_ENABLED = os.environ.get('SECURITY_SCAN_ENABLED', 'True').lower() == 'true'
    
    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True


class TestingConfig(Config):
    """
    Testing configuration - self-contained SQLite in-memory DB (no external
    MySQL dependency, so the test suite runs anywhere). StaticPool +
    check_same_thread=False keep the same single connection shared across
    threads, since a background-thread task run (queue_task_execution's
    ThreadPoolExecutor) needs to see the same in-memory database the test
    thread wrote to - the default pooling would otherwise hand each thread
    its own separate in-memory DB.
    """
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    # Long enough that no test's request/response cycle can spuriously hit
    # token expiry (the previous 1-second value was a real flakiness risk
    # for anything doing real Docker work mid-test).
    JWT_ACCESS_TOKEN_EXPIRES = 3600
    # APScheduler's SQLAlchemyJobStore is unrelated to what this suite
    # verifies (schedule_all_tasks() registering cron jobs isn't covered
    # here) and adds startup complexity against SQLite for no benefit.
    SCHEDULER_ENABLED = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SQLALCHEMY_ECHO = False
    SCHEDULER_ENABLED = True


# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config(env=None):
    """Get configuration based on environment"""
    if env is None:
        env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
