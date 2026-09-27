"""
API v1 ML Models routes for EssentialPipeline.

Scoped to the model record itself (create/list/get/update/delete) - not
model versions, artifact upload/download, or execution, which is a
separate, larger piece of work (see plan.md's "ML model execution
service" item) that this deliberately doesn't reach into.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import MLModel, Project

bp = Blueprint('models', __name__, url_prefix='/models')


def _get_owned_model(model_id, user_id):
    model = MLModel.query.get_or_404(model_id)
    if model.owner_user_id != user_id:
        return None
    return model


@bp.route('/', methods=['GET'])
@jwt_required()
def list_models():
    user_id = int(get_jwt_identity())
    models = MLModel.query.filter_by(owner_user_id=user_id).order_by(MLModel.created_at.desc()).all()
    return jsonify({'models': [m.to_dict() for m in models]})


@bp.route('/', methods=['POST'])
@jwt_required()
def create_model():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    if not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    project_id = data.get('project_id')
    if project_id:
        project = Project.query.get(project_id)
        if not project or project.owner_user_id != user_id:
            return jsonify({'error': 'project_id must be a project you own'}), 400

    model = MLModel(
        name=data['name'],
        description=data.get('description'),
        model_type=data.get('model_type'),
        project_id=project_id,
        owner_user_id=user_id
    )
    db.session.add(model)
    db.session.commit()
    return jsonify(model.to_dict()), 201


@bp.route('/<int:model_id>', methods=['GET'])
@jwt_required()
def get_model(model_id):
    user_id = int(get_jwt_identity())
    model = _get_owned_model(model_id, user_id)
    if model is None:
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(model.to_dict())


@bp.route('/<int:model_id>', methods=['PUT'])
@jwt_required()
def update_model(model_id):
    user_id = int(get_jwt_identity())
    model = _get_owned_model(model_id, user_id)
    if model is None:
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json() or {}
    if 'name' in data:
        model.name = data['name']
    if 'description' in data:
        model.description = data['description']
    if 'model_type' in data:
        model.model_type = data['model_type']
    if 'is_active' in data:
        model.is_active = data['is_active']

    db.session.commit()
    return jsonify(model.to_dict())


@bp.route('/<int:model_id>', methods=['DELETE'])
@jwt_required()
def delete_model(model_id):
    user_id = int(get_jwt_identity())
    model = _get_owned_model(model_id, user_id)
    if model is None:
        return jsonify({'error': 'Access denied'}), 403

    db.session.delete(model)
    db.session.commit()
    return jsonify({'message': 'Model deleted successfully'}), 200
