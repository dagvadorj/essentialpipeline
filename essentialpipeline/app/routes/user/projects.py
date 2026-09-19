"""
User Projects routes for EssentialPipeline
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
import io
import os
import zipfile
from essentialpipeline import db
from essentialpipeline.models import Project, ProjectVersion, ProjectFile
from essentialpipeline.utils.storage import save_file

bp = Blueprint('user_projects', __name__, template_folder='../../../templates/user/projects')

# This file lives at essentialpipeline/app/routes/user/projects.py; walk up
# to the essentialpipeline/ package root to find examples/hello_pipeline.
_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
EXAMPLE_PROJECT_DIR = os.path.abspath(os.path.join(_PACKAGE_DIR, 'examples', 'hello_pipeline'))


@bp.route('/example')
@jwt_required()
def download_example_project():
    """Download a minimal example project zip, ready to upload as-is."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename in sorted(os.listdir(EXAMPLE_PROJECT_DIR)):
            zf.write(os.path.join(EXAMPLE_PROJECT_DIR, filename), arcname=filename)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='hello-pipeline-example.zip'
    )


@bp.route('/')
@jwt_required()
def list_projects():
    """List all projects for the current user"""
    user_id = int(get_jwt_identity())
    projects = Project.query.filter_by(owner_user_id=user_id).order_by(Project.updated_at.desc()).all()
    
    return render_template('list.html', title='My Projects', projects=projects)


@bp.route('/new', methods=['GET', 'POST'])
@jwt_required()
def new_project():
    """Create a new project"""
    if request.method == 'POST':
        user_id = int(get_jwt_identity())
        
        name = request.form.get('name')
        description = request.form.get('description')
        
        if not name:
            flash('Project name is required', 'danger')
            return render_template('new.html', title='New Project')
        
        # Check if project file was uploaded
        project_file = request.files.get('project_file')
        if project_file and project_file.filename:
            try:
                # Save the uploaded file
                file_result = save_file(project_file, subfolder='projects')
                
                # Create the project
                project = Project(
                    name=name,
                    description=description,
                    owner_user_id=user_id,
                    storage_path=file_result['relative_path']
                )
                db.session.add(project)
                db.session.flush()
                
                # Create first version
                version = ProjectVersion(
                    project_id=project.id,
                    version='1.0.0',
                    changelog='Initial version'
                )
                db.session.add(version)
                db.session.flush()
                project.current_version_id = version.id

                # Create project file record
                project_file_record = ProjectFile(
                    project_version_id=version.id,
                    file_path=file_result['filename'],
                    file_size=os.path.getsize(file_result['path']),
                    storage_path=file_result['relative_path']
                )
                db.session.add(project_file_record)
                
                db.session.commit()
                
                flash('Project created successfully!', 'success')
                return redirect(url_for('user_projects.detail_project', project_id=project.id))
                
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating project: {e}")
                flash(f'Error creating project: {e}', 'danger')
        else:
            # Create project without file (can be added later)
            project = Project(
                name=name,
                description=description,
                owner_user_id=user_id
            )
            db.session.add(project)
            db.session.flush()
            
            # Create first version
            version = ProjectVersion(
                project_id=project.id,
                version='1.0.0',
                changelog='Initial version'
            )
            db.session.add(version)
            project.current_version_id = version.id
            
            db.session.commit()
            
            flash('Project created successfully!', 'success')
            return redirect(url_for('user_projects.detail_project', project_id=project.id))
    
    return render_template('new.html', title='New Project')


@bp.route('/<int:project_id>')
@jwt_required()
def detail_project(project_id):
    """Show project details"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))
    
    # Get versions
    versions = ProjectVersion.query.filter_by(project_id=project_id).order_by(ProjectVersion.created_at.desc()).all()
    
    # Get files from current version
    current_version = project.current_version
    files = []
    if current_version:
        files = ProjectFile.query.filter_by(project_version_id=current_version.id).all()

    from essentialpipeline.models import Task
    tasks = Task.query.filter_by(project_id=project_id).order_by(Task.created_at.desc()).all()

    return render_template(
        'detail.html',
        title=f'Project: {project.name}',
        project=project,
        versions=versions,
        files=files,
        tasks=tasks
    )


@bp.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@jwt_required()
def edit_project(project_id):
    """Edit project settings"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))
    
    if request.method == 'POST':
        project.name = request.form.get('name', project.name)
        project.description = request.form.get('description', project.description)
        project.is_active = request.form.get('is_active') == 'on'
        
        db.session.commit()
        flash('Project updated successfully!', 'success')
        return redirect(url_for('user_projects.detail_project', project_id=project.id))
    
    return render_template('edit.html', title=f'Edit: {project.name}', project=project)


@bp.route('/<int:project_id>/upload', methods=['GET', 'POST'])
@jwt_required()
def upload_project_version(project_id):
    """Upload a new version of the project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))
    
    if request.method == 'POST':
        project_file = request.files.get('project_file')
        version_notes = request.form.get('changelog', '')
        
        if not project_file or not project_file.filename:
            flash('Please select a file to upload', 'danger')
            return render_template('upload.html', title=f'Upload: {project.name}', project=project)
        
        try:
            # Save the uploaded file
            file_result = save_file(project_file, subfolder=f'projects/{project.id}')
            
            # Get current version
            current_version = project.current_version
            current_version_num = current_version.version if current_version else '1.0.0'
            
            # Increment version
            major, minor, patch = map(int, current_version_num.split('.'))
            new_version_num = f"{major}.{minor}.{patch + 1}"
            
            # Create new version
            version = ProjectVersion(
                project_id=project.id,
                version=new_version_num,
                changelog=version_notes
            )
            db.session.add(version)
            db.session.flush()
            
            # Update project current version
            project.current_version_id = version.id
            project.updated_at = db.func.now()
            
            # Create project file record
            project_file_record = ProjectFile(
                project_version_id=version.id,
                file_path=file_result['filename'],
                file_size=os.path.getsize(file_result['path']),
                storage_path=file_result['relative_path']
            )
            db.session.add(project_file_record)
            
            db.session.commit()
            
            flash('New version uploaded successfully!', 'success')
            return redirect(url_for('user_projects.detail_project', project_id=project.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error uploading version: {e}")
            flash(f'Error uploading version: {e}', 'danger')
    
    return render_template('upload.html', title=f'Upload: {project.name}', project=project)


@bp.route('/<int:project_id>/delete', methods=['POST'])
@jwt_required()
def delete_project(project_id):
    """Delete a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))
    
    try:
        # Delete all versions and files
        versions = ProjectVersion.query.filter_by(project_id=project_id).all()
        for version in versions:
            files = ProjectFile.query.filter_by(project_version_id=version.id).all()
            for file in files:
                db.session.delete(file)
            db.session.delete(version)
        
        db.session.delete(project)
        db.session.commit()
        
        flash('Project deleted successfully!', 'success')
        return redirect(url_for('user_projects.list_projects'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting project: {e}")
        flash(f'Error deleting project: {e}', 'danger')
        return redirect(url_for('user_projects.detail_project', project_id=project.id))
