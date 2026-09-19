"""
User Tasks routes for EssentialPipeline
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_jwt_extended import jwt_required, get_jwt_identity
from essentialpipeline import db
from essentialpipeline.models import Task, TaskRun, Project

bp = Blueprint('user_tasks', __name__)


@bp.route('/')
@jwt_required()
def list_tasks():
    """List all tasks across the current user's projects"""
    user_id = int(get_jwt_identity())
    tasks = Task.query.join(Task.project).filter_by(owner_user_id=user_id) \
        .order_by(Task.created_at.desc()).all()

    return render_template('user/tasks/list.html', title='Tasks', tasks=tasks)


@bp.route('/new', methods=['GET', 'POST'])
@jwt_required()
def new_task():
    """Create a new task for one of the current user's projects"""
    user_id = int(get_jwt_identity())
    projects = Project.query.filter_by(owner_user_id=user_id).order_by(Project.name).all()

    if request.method == 'POST':
        project_id = request.form.get('project_id', type=int)
        name = request.form.get('name')

        project = Project.query.get(project_id) if project_id else None
        if not project or project.owner_user_id != user_id:
            flash('Select a valid project', 'danger')
            return render_template('user/tasks/new.html', title='New Task', projects=projects)

        if not name:
            flash('Task name is required', 'danger')
            return render_template('user/tasks/new.html', title='New Task', projects=projects)

        task = Task(
            project_id=project.id,
            project_version_id=project.current_version_id,
            name=name,
            task_type=request.form.get('task_type', 'python'),
            script_path=request.form.get('script_path') or None,
            schedule_cron=request.form.get('schedule_cron') or None,
            is_active=True
        )
        db.session.add(task)
        db.session.commit()

        if task.schedule_cron:
            from essentialpipeline.services.scheduler import schedule_task
            schedule_task(task.id)

        flash('Task created successfully!', 'success')
        return redirect(url_for('user_tasks.detail_task', task_id=task.id))

    selected_project_id = request.args.get('project_id', type=int)
    return render_template(
        'user/tasks/new.html',
        title='New Task',
        projects=projects,
        selected_project_id=selected_project_id
    )


@bp.route('/<int:task_id>')
@jwt_required()
def detail_task(task_id):
    """Show task details and run history"""
    user_id = int(get_jwt_identity())
    task = Task.query.get_or_404(task_id)

    if task.project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))

    runs = TaskRun.query.filter_by(task_id=task_id).order_by(TaskRun.start_time.desc()).limit(20).all()

    return render_template('user/tasks/detail.html', title=f'Task: {task.name}', task=task, runs=runs)


@bp.route('/<int:task_id>/trigger', methods=['POST'])
@jwt_required()
def trigger_task(task_id):
    """Manually trigger a task run"""
    user_id = int(get_jwt_identity())
    task = Task.query.get_or_404(task_id)

    if task.project.owner_user_id != user_id:
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard.index'))

    if not task.is_active:
        flash('Task is not active', 'warning')
        return redirect(url_for('user_tasks.detail_task', task_id=task.id))

    from essentialpipeline.services.scheduler import queue_task_execution
    task_run = queue_task_execution(task_id, triggered_by='manual', user_id=user_id)

    flash(f'Run #{task_run.id} queued.', 'success')
    return redirect(url_for('user_tasks.detail_task', task_id=task.id))
