"""
EssentialPipeline Pipeline Tool
An Airflow-like data/task pipeline orchestration system
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_admin import Admin

# Initialize extensions without app context
db = SQLAlchemy()
jwt = JWTManager()
admin = Admin()

__version__ = "0.1.0"
