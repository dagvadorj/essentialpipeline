"""
API v1 Projects routes for EssentialPipeline
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import Project, ProjectVersion, ProjectFile, Task, TaskRun
from essentialpipeline.utils.storage import save_file, delete_file
import os

bp = Blueprint('projects', __name__, url_prefix='/projects')


@bp.route('/', methods=['GET'])
@jwt_required()
def list_projects():
    """List all projects for the authenticated user"""
    user_id = int(get_jwt_identity())
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Query projects
    projects = Project.query.filter_by(owner_user_id=user_id)
    
    # Apply search filter
    search = request.args.get('search', '')
    if search:
        projects = projects.filter(
            (Project.name.contains(search)) | 
            (Project.description.contains(search))
        )
    
    # Apply status filter
    status = request.args.get('status')
    if status:
        projects = projects.filter_by(status=status)
    
    # Apply sorting
    sort_by = request.args.get('sort_by', 'updated_at')
    sort_order = request.args.get('sort_order', 'desc')
    
    if hasattr(Project, sort_by):
        if sort_order == 'desc':
            projects = projects.order_by(getattr(Project, sort_by).desc())
        else:
            projects = projects.order_by(getattr(Project, sort_by).asc())
    
    # Paginate
    paginated_projects = projects.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'projects': [p.to_dict() for p in paginated_projects.items],
        'total': paginated_projects.total,
        'pages': paginated_projects.pages,
        'current_page': paginated_projects.page,
        'per_page': paginated_projects.per_page
    })


@bp.route('/', methods=['POST'])
@jwt_required()
def create_project():
    """Create a new project"""
    user_id = int(get_jwt_identity())
    data = request.get_json()
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    
    # Create project
    project = Project(
        name=data['name'],
        description=data.get('description'),
        owner_user_id=user_id,
        is_active=data.get('is_active', True),
        status=data.get('status', 'draft')
    )
    
    db.session.add(project)
    db.session.flush()
    
    # Create first version
    version = ProjectVersion(
        project_id=project.id,
        version='1.0.0',
        changelog=data.get('changelog', 'Initial version')
    )
    db.session.add(version)
    project.current_version_id = version.id
    
    db.session.commit()
    
    return jsonify(project.to_dict()), 201


@bp.route('/<int:project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    """Get a specific project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    return jsonify(project.to_dict())


@bp.route('/<int:project_id>', methods=['PUT'])
@jwt_required()
def update_project(project_id):
    """Update a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    
    if 'name' in data:
        project.name = data['name']
    if 'description' in data:
        project.description = data['description']
    if 'is_active' in data:
        project.is_active = data['is_active']
    if 'status' in data:
        project.status = data['status']
    
    db.session.commit()
    
    return jsonify(project.to_dict())


@bp.route('/<int:project_id>', methods=['DELETE'])
@jwt_required()
def delete_project(project_id):
    """Delete a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    # Delete all related data
    versions = ProjectVersion.query.filter_by(project_id=project_id).all()
    for version in versions:
        files = ProjectFile.query.filter_by(project_version_id=version.id).all()
        for file in files:
            # Delete physical file
            if file.storage_path:
                delete_file(file.storage_path)
            db.session.delete(file)
        
        # Delete tasks for this project
        tasks = Task.query.filter_by(project_id=project_id, project_version_id=version.id).all()
        for task in tasks:
            # Delete task runs
            runs = TaskRun.query.filter_by(task_id=task.id).all()
            for run in runs:
                db.session.delete(run)
            db.session.delete(task)
        
        db.session.delete(version)
    
    db.session.delete(project)
    db.session.commit()
    
    return jsonify({'message': 'Project deleted successfully'}), 200


@bp.route('/<int:project_id>/upload', methods=['POST'])
@jwt_required()
def upload_project_file(project_id):
    """Upload a project file (ZIP)"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    
    # Validate file extension
    if not file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Only ZIP files are allowed'}), 400
    
    try:
        # Save the uploaded file
        file_result = save_file(file, subfolder=f'projects/{project.id}')
        
        # Get current version
        current_version = project.current_version
        current_version_num = current_version.version if current_version else '1.0.0'
        
        # Increment version
        major, minor, patch = map(int, current_version_num.split('.'))
        new_version_num = f"{major}.{minor}.{patch + 1}"
        
        # Create new version
        changelog = request.form.get('changelog', 'File upload')
        version = ProjectVersion(
            project_id=project.id,
            version=new_version_num,
            changelog=changelog
        )
        db.session.add(version)
        db.session.flush()
        
        # Update project current version
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
        
        return jsonify({
            'message': 'File uploaded successfully',
            'version': version.to_dict(),
            'file': project_file_record.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:project_id>/versions', methods=['GET'])
@jwt_required()
def list_project_versions(project_id):
    """List all versions of a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    versions = ProjectVersion.query.filter_by(project_id=project_id).order_by(ProjectVersion.created_at.desc()).all()
    
    return jsonify({'versions': [v.to_dict() for v in versions]})


@bp.route('/<int:project_id>/tasks', methods=['GET'])
@jwt_required()
def list_project_tasks(project_id):
    """List all tasks for a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    tasks = Task.query.filter_by(project_id=project_id).all()
    
    return jsonify({'tasks': [t.to_dict() for t in tasks]})


@bp.route('/<int:project_id>/tasks', methods=['POST'])
@jwt_required()
def create_project_task(project_id):
    """Create a new task for a project"""
    user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(project_id)
    
    # Check access
    if project.owner_user_id != user_id:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    
    task = Task(
        project_id=project_id,
        project_version_id=project.current_version_id,
        name=data['name'],
        task_type=data.get('task_type', 'python'),
        script_path=data.get('script_path'),
        schedule_cron=data.get('schedule_cron'),
        is_active=data.get('is_active', True)
    )
    
    db.session.add(task)
    db.session.commit()
    
    return jsonify(task.to_dict()), 201
