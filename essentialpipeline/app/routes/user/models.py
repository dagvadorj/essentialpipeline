"""
User ML Models routes for EssentialPipeline: model records, versions
(bundle upload/download), and running a version - see
services/model_execution.py for the bundle contract.
"""

import io
import json
import os
import zipfile

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import MLModel, MLModelVersion, MLModelExecution, Project
from essentialpipeline.services.model_execution import (
    create_version, queue_model_execution, delete_model as delete_model_cascade, ModelWorkflowError
)
from essentialpipeline.utils.project_validation import ProjectValidationError
from essentialpipeline.utils.storage import get_file_path

bp = Blueprint('user_models', __name__)

# essentialpipeline/app/routes/user/models.py -> essentialpipeline/examples/sample_model
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
EXAMPLE_MODEL_DIR = os.path.abspath(os.path.join(_PACKAGE_DIR, 'examples', 'sample_model'))


@bp.route('/example')
@jwt_required()
def download_example_model():
    """Download a minimal example model bundle, ready to upload as a version."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in sorted(os.listdir(EXAMPLE_MODEL_DIR)):
            zf.write(os.path.join(EXAMPLE_MODEL_DIR, filename), arcname=filename)
    buffer.seek(0)
    return send_file(buffer, mimetype='application/zip', as_attachment=True,
                     download_name='sample-model.zip')


@bp.route('/')
@jwt_required()
def list_models():
    user_id = int(get_jwt_identity())
    models = MLModel.query.filter_by(owner_user_id=user_id).order_by(MLModel.created_at.desc()).all()
    return render_template('user/models/list.html', title='ML Models', models=models)


@bp.route('/new', methods=['GET', 'POST'])
@jwt_required()
def new_model():
    user_id = int(get_jwt_identity())
    projects = Project.query.filter_by(owner_user_id=user_id).order_by(Project.name).all()

    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Model name is required', 'danger')
            return render_template('user/models/new.html', title='New Model', projects=projects)

        project_id = request.form.get('project_id', type=int)
        if project_id and not any(p.id == project_id for p in projects):
            flash('Select a valid project', 'danger')
            return render_template('user/models/new.html', title='New Model', projects=projects)

        model = MLModel(
            name=name,
            description=request.form.get('description'),
            model_type=request.form.get('model_type') or None,
            project_id=project_id or None,
            owner_user_id=user_id
        )
        db.session.add(model)
        db.session.commit()

        flash('Model created successfully!', 'success')
        return redirect(url_for('user_models.detail_model', model_id=model.id))

    return render_template('user/models/new.html', title='New Model', projects=projects)


@bp.route('/<int:model_id>')
@jwt_required()
def detail_model(model_id):
    user_id = int(get_jwt_identity())
    model = MLModel.query.get_or_404(model_id)
    if model.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_models.list_models'))

    versions = MLModelVersion.query.filter_by(model_id=model.id).order_by(MLModelVersion.id.desc()).all()
    executions = (MLModelExecution.query.filter_by(model_id=model.id)
                  .order_by(MLModelExecution.id.desc()).limit(10).all())
    return render_template('user/models/detail.html', title=f'Model: {model.name}',
                            model=model, versions=versions, executions=executions,
                            pretty=lambda v: json.dumps(v, indent=2))


@bp.route('/<int:model_id>/edit', methods=['GET', 'POST'])
@jwt_required()
def edit_model(model_id):
    user_id = int(get_jwt_identity())
    model = MLModel.query.get_or_404(model_id)
    if model.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_models.list_models'))

    if request.method == 'POST':
        model.name = request.form.get('name', model.name)
        model.description = request.form.get('description', model.description)
        model.model_type = request.form.get('model_type') or model.model_type
        model.is_active = request.form.get('is_active') == 'on'
        db.session.commit()
        flash('Model updated successfully!', 'success')
        return redirect(url_for('user_models.detail_model', model_id=model.id))

    return render_template('user/models/edit.html', title=f'Edit: {model.name}', model=model)


@bp.route('/<int:model_id>/delete', methods=['POST'])
@jwt_required()
def delete_model(model_id):
    user_id = int(get_jwt_identity())
    model = MLModel.query.get_or_404(model_id)
    if model.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_models.list_models'))

    delete_model_cascade(model)
    flash('Model deleted successfully!', 'success')
    return redirect(url_for('user_models.list_models'))


def _own_model_or_redirect(model_id):
    model = MLModel.query.get_or_404(model_id)
    if model.owner_user_id != int(get_jwt_identity()):
        flash('Access denied', 'danger')
        return None
    return model


@bp.route('/<int:model_id>/versions', methods=['POST'])
@jwt_required()
def upload_version(model_id):
    model = _own_model_or_redirect(model_id)
    if model is None:
        return redirect(url_for('user_models.list_models'))

    file = request.files.get('bundle')
    if not file or not file.filename:
        flash('Choose a bundle (.zip) to upload', 'danger')
    else:
        try:
            version = create_version(
                model, file,
                framework=request.form.get('framework') or None,
                framework_version=request.form.get('framework_version') or None
            )
            flash(f'Version {version.version} uploaded and set as current', 'success')
        except (ProjectValidationError, ModelWorkflowError) as e:
            flash(str(e), 'danger')

    return redirect(url_for('user_models.detail_model', model_id=model_id))


@bp.route('/<int:model_id>/versions/<int:version_id>/download')
@jwt_required()
def download_version(model_id, version_id):
    model = _own_model_or_redirect(model_id)
    if model is None:
        return redirect(url_for('user_models.list_models'))
    version = MLModelVersion.query.get_or_404(version_id)
    if version.model_id != model.id:
        flash('Version does not belong to this model', 'danger')
        return redirect(url_for('user_models.detail_model', model_id=model_id))

    return send_file(get_file_path(version.artifact_path), as_attachment=True,
                     download_name=f'{model.name}-{version.version}.zip')


@bp.route('/<int:model_id>/execute', methods=['POST'])
@jwt_required()
def run_model(model_id):
    model = _own_model_or_redirect(model_id)
    if model is None:
        return redirect(url_for('user_models.list_models'))

    detail = redirect(url_for('user_models.detail_model', model_id=model_id))

    if not model.is_active:
        flash('Model is not active', 'danger')
        return detail

    try:
        input_data = json.loads(request.form.get('input_data', ''))
    except ValueError:
        flash('Input must be valid JSON', 'danger')
        return detail

    version_id = request.form.get('version_id', type=int) or model.current_version_id
    version = MLModelVersion.query.get(version_id) if version_id else None
    if not version:
        flash('Upload a version before running this model', 'danger')
        return detail

    try:
        execution = queue_model_execution(model, version, input_data)
        flash(f'Execution #{execution.id} started - refresh to see the result', 'success')
    except ModelWorkflowError as e:
        flash(str(e), 'danger')

    return detail
