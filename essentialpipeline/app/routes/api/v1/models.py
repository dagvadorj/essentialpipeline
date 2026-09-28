"""
API v1 ML Models routes for EssentialPipeline: model records
(create/list/get/update/delete), versions (bundle upload/download), and
execution - see services/model_execution.py for the bundle contract.
"""

import json

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import MLModel, MLModelVersion, MLModelExecution, Project
from essentialpipeline.services.model_execution import (
    create_version, queue_model_execution, ModelWorkflowError
)
from essentialpipeline.services.model_execution import delete_model as delete_model_cascade
from essentialpipeline.utils.project_validation import ProjectValidationError
from essentialpipeline.utils.storage import get_file_path

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

    delete_model_cascade(model)
    return jsonify({'message': 'Model deleted successfully'}), 200


# --- Versions ---

def _own_model_or_403(model_id):
    """Returns (model, None) or (None, error_response)"""
    model = _get_owned_model(model_id, int(get_jwt_identity()))
    if model is None:
        return None, (jsonify({'error': 'Access denied'}), 403)
    return model, None


@bp.route('/<int:model_id>/versions', methods=['GET'])
@jwt_required()
def list_versions(model_id):
    model, err = _own_model_or_403(model_id)
    if err:
        return err
    versions = MLModelVersion.query.filter_by(model_id=model.id).order_by(MLModelVersion.id.desc()).all()
    return jsonify({'versions': [v.to_dict() for v in versions]})


@bp.route('/<int:model_id>/versions', methods=['POST'])
@jwt_required()
def upload_version(model_id):
    """Upload a model bundle (zip with predict.py at its root) as a new version"""
    model, err = _own_model_or_403(model_id)
    if err:
        return err

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file uploaded'}), 400
    if not file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Only ZIP bundles are allowed'}), 400

    metadata = None
    if request.form.get('metadata'):
        try:
            metadata = json.loads(request.form['metadata'])
        except ValueError:
            return jsonify({'error': 'metadata must be valid JSON'}), 400

    try:
        version = create_version(
            model, file,
            framework=request.form.get('framework'),
            framework_version=request.form.get('framework_version'),
            metadata=metadata
        )
    except (ProjectValidationError, ModelWorkflowError) as e:
        return jsonify({'error': str(e)}), 400

    return jsonify(version.to_dict()), 201


@bp.route('/<int:model_id>/versions/<int:version_id>/download', methods=['GET'])
@jwt_required()
def download_version(model_id, version_id):
    model, err = _own_model_or_403(model_id)
    if err:
        return err
    version = MLModelVersion.query.get_or_404(version_id)
    if version.model_id != model.id:
        return jsonify({'error': 'Version does not belong to this model'}), 400

    return send_file(get_file_path(version.artifact_path), as_attachment=True,
                     download_name=f'{model.name}-{version.version}.zip')


# --- Execution ---

@bp.route('/<int:model_id>/execute', methods=['POST'])
@jwt_required()
def execute(model_id):
    """Run a version (default: the current one) against input_data. Async - poll the returned execution."""
    model, err = _own_model_or_403(model_id)
    if err:
        return err
    if not model.is_active:
        return jsonify({'error': 'Model is not active'}), 400

    data = request.get_json(silent=True) or {}
    if 'input_data' not in data:
        return jsonify({'error': 'input_data is required'}), 400

    version_id = data.get('version_id') or model.current_version_id
    version = MLModelVersion.query.get(version_id) if version_id else None
    if not version:
        return jsonify({'error': 'Model has no version to run - upload one first'}), 400

    try:
        execution = queue_model_execution(model, version, data['input_data'])
    except ModelWorkflowError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify(execution.to_dict()), 202


@bp.route('/<int:model_id>/executions', methods=['GET'])
@jwt_required()
def list_executions(model_id):
    model, err = _own_model_or_403(model_id)
    if err:
        return err
    executions = MLModelExecution.query.filter_by(model_id=model.id) \
        .order_by(MLModelExecution.id.desc()).limit(50).all()
    return jsonify({'executions': [e.to_dict() for e in executions]})


@bp.route('/<int:model_id>/executions/<int:execution_id>', methods=['GET'])
@jwt_required()
def get_execution(model_id, execution_id):
    model, err = _own_model_or_403(model_id)
    if err:
        return err
    execution = MLModelExecution.query.get_or_404(execution_id)
    if execution.model_id != model.id:
        return jsonify({'error': 'Execution does not belong to this model'}), 400
    return jsonify(execution.to_dict())
