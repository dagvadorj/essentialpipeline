"""
User ML Models routes for EssentialPipeline.

Scoped to the model record itself (create/list/detail/edit/delete) -
not versions, artifact upload/download, or execution ("Test Model" in
the nav is still a dead link for that reason - see plan.md's "ML model
execution service" item).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import MLModel, Project

bp = Blueprint('user_models', __name__)


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

    return render_template('user/models/detail.html', title=f'Model: {model.name}', model=model)


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

    db.session.delete(model)
    db.session.commit()
    flash('Model deleted successfully!', 'success')
    return redirect(url_for('user_models.list_models'))
