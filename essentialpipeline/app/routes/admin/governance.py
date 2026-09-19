"""
Admin Governance routes for EssentialPipeline.

Groups and Permissions already have raw CRUD via Flask-Admin
(admin_setup.py); this blueprint covers what Flask-Admin can't do well:
resolving GroupConnectionClearance's polymorphic connection reference to
an actual connection name, testing a connection's stored credentials, and
querying the audit log.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from essentialpipeline import db
from essentialpipeline.app.middleware import admin_required
from essentialpipeline.models import (
    Group, Permission, Environment, DatabaseConnection, StorageConnection,
    GroupConnectionClearance, AuditLog
)

bp = Blueprint('admin_governance', __name__)


def _all_connections():
    """All database + storage connections, each tagged with its clearance connection_type"""
    connections = []
    for conn in DatabaseConnection.query.order_by(DatabaseConnection.name).all():
        connections.append({'type': 'database', 'id': conn.id, 'name': conn.name, 'obj': conn})
    for conn in StorageConnection.query.order_by(StorageConnection.name).all():
        connections.append({'type': 'storage', 'id': conn.id, 'name': conn.name, 'obj': conn})
    return connections


def _resolve_connection(connection_type, connection_id):
    """Look up the actual connection a GroupConnectionClearance points at (no real FK - Decision 4/schema note)"""
    if connection_type == 'database':
        return DatabaseConnection.query.get(connection_id)
    if connection_type == 'storage':
        return StorageConnection.query.get(connection_id)
    return None


@bp.route('/')
@admin_required
def dashboard():
    """Governance overview"""
    counts = {
        'groups': Group.query.count(),
        'permissions': Permission.query.count(),
        'environments': Environment.query.count(),
        'connections': DatabaseConnection.query.count() + StorageConnection.query.count(),
        'clearances': GroupConnectionClearance.query.count(),
    }
    return render_template('admin/governance/dashboard.html', title='Governance', counts=counts)


@bp.route('/groups')
@admin_required
def list_groups():
    """List all groups"""
    groups = Group.query.order_by(Group.name).all()
    return render_template('admin/governance/groups_list.html', title='Groups', groups=groups)


@bp.route('/groups/new', methods=['GET', 'POST'])
@admin_required
def new_group():
    """Create a new group"""
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Group name is required', 'danger')
            return render_template('admin/governance/group_new.html', title='New Group')

        if Group.query.filter_by(name=name).first():
            flash('A group with that name already exists', 'danger')
            return render_template('admin/governance/group_new.html', title='New Group')

        group = Group(name=name, description=request.form.get('description'))
        db.session.add(group)
        db.session.commit()

        flash('Group created successfully!', 'success')
        return redirect(url_for('admin_governance.detail_group', group_id=group.id))

    return render_template('admin/governance/group_new.html', title='New Group')


@bp.route('/groups/<int:group_id>')
@admin_required
def detail_group(group_id):
    """Group detail: members, permissions, and connection clearances"""
    group = Group.query.get_or_404(group_id)
    all_permissions = Permission.query.order_by(Permission.resource_type, Permission.action).all()
    group_permission_ids = {p.id for p in group.permissions}

    clearances = GroupConnectionClearance.query.filter_by(group_id=group_id).all()
    clearances_view = [
        {'clearance': c, 'connection': _resolve_connection(c.connection_type, c.connection_id)}
        for c in clearances
    ]

    return render_template(
        'admin/governance/group_detail.html',
        title=f'Group: {group.name}',
        group=group,
        all_permissions=all_permissions,
        group_permission_ids=group_permission_ids,
        clearances=clearances_view,
        connections=_all_connections()
    )


@bp.route('/groups/<int:group_id>/permissions', methods=['POST'])
@admin_required
def update_group_permissions(group_id):
    """Replace a group's permission set from the submitted checkboxes"""
    group = Group.query.get_or_404(group_id)
    permission_ids = request.form.getlist('permission_ids', type=int)
    group.permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all() if permission_ids else []
    db.session.commit()

    flash('Permissions updated', 'success')
    return redirect(url_for('admin_governance.detail_group', group_id=group.id))


@bp.route('/groups/<int:group_id>/clearances', methods=['POST'])
@admin_required
def add_clearance(group_id):
    """Grant a group access to a connection"""
    group = Group.query.get_or_404(group_id)

    connection_ref = request.form.get('connection_ref', '')
    access_level = request.form.get('access_level', 'none')

    try:
        connection_type, connection_id = connection_ref.split(':')
        connection_id = int(connection_id)
    except ValueError:
        flash('Select a connection', 'danger')
        return redirect(url_for('admin_governance.detail_group', group_id=group_id))

    if not _resolve_connection(connection_type, connection_id):
        flash('That connection no longer exists', 'danger')
        return redirect(url_for('admin_governance.detail_group', group_id=group_id))

    existing = GroupConnectionClearance.query.filter_by(
        group_id=group_id, connection_type=connection_type, connection_id=connection_id
    ).first()
    if existing:
        existing.access_level = access_level
        flash('Clearance updated', 'success')
    else:
        db.session.add(GroupConnectionClearance(
            group_id=group_id, connection_type=connection_type,
            connection_id=connection_id, access_level=access_level
        ))
        flash('Clearance granted', 'success')

    db.session.commit()
    return redirect(url_for('admin_governance.detail_group', group_id=group_id))


@bp.route('/clearances/<int:clearance_id>', methods=['POST'])
@admin_required
def update_clearance(clearance_id):
    """Change a clearance's access level"""
    clearance = GroupConnectionClearance.query.get_or_404(clearance_id)
    clearance.access_level = request.form.get('access_level', clearance.access_level)
    db.session.commit()

    flash('Clearance updated', 'success')
    return redirect(url_for('admin_governance.detail_group', group_id=clearance.group_id))


@bp.route('/clearances/<int:clearance_id>/delete', methods=['POST'])
@admin_required
def delete_clearance(clearance_id):
    """Revoke a clearance"""
    clearance = GroupConnectionClearance.query.get_or_404(clearance_id)
    group_id = clearance.group_id
    db.session.delete(clearance)
    db.session.commit()

    flash('Clearance revoked', 'success')
    return redirect(url_for('admin_governance.detail_group', group_id=group_id))


@bp.route('/connections')
@admin_required
def list_connections():
    """List database and storage connections with their environment"""
    db_connections = DatabaseConnection.query.order_by(DatabaseConnection.name).all()
    storage_connections = StorageConnection.query.order_by(StorageConnection.name).all()
    return render_template(
        'admin/governance/connections_list.html',
        title='Connections',
        db_connections=db_connections,
        storage_connections=storage_connections
    )


@bp.route('/connections/<conn_type>/<int:connection_id>/test', methods=['POST'])
@admin_required
def test_connection(conn_type, connection_id):
    """Run a health check against a stored connection"""
    connection = _resolve_connection(conn_type, connection_id)
    if not connection:
        flash('Connection not found', 'danger')
        return redirect(url_for('admin_governance.list_connections'))

    from essentialpipeline.services.connection_health import test_database_connection, test_storage_connection
    result = test_database_connection(connection) if conn_type == 'database' else test_storage_connection(connection)

    category = 'success' if result['ok'] is True else ('warning' if result['ok'] is None else 'danger')
    flash(f"{connection.name}: {result['message']}", category)
    return redirect(url_for('admin_governance.list_connections'))


@bp.route('/audit-logs')
@admin_required
def list_audit_logs():
    """Query the audit log, optionally filtered by action/resource_type/user_id"""
    query = AuditLog.query

    action = request.args.get('action')
    resource_type = request.args.get('resource_type')
    user_id = request.args.get('user_id', type=int)

    if action:
        query = query.filter_by(action=action)
    if resource_type:
        query = query.filter_by(resource_type=resource_type)
    if user_id:
        query = query.filter_by(user_id=user_id)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)

    return render_template(
        'admin/governance/audit_logs.html',
        title='Audit Logs',
        pagination=pagination,
        logs=pagination.items,
        filters={'action': action or '', 'resource_type': resource_type or '', 'user_id': user_id or ''}
    )
