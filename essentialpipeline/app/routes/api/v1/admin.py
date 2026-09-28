"""
API v1 Admin/Governance routes for EssentialPipeline.

API equivalent of app/routes/admin/governance.py - groups, permissions,
environments, connections, clearances, and audit log querying, all
gated by admin_required.
"""

from flask import Blueprint, jsonify, request
from essentialpipeline import db
from essentialpipeline.app.middleware import admin_required
from essentialpipeline.models import (
    Group, Permission, Environment, DatabaseConnection, StorageConnection,
    GroupConnectionClearance, AuditLog, SystemMetric, Alert, AlertRule
)

bp = Blueprint('admin', __name__, url_prefix='/admin')


def _resolve_connection(connection_type, connection_id):
    """Look up the connection a GroupConnectionClearance points at (no real FK - polymorphic by design)"""
    if connection_type == 'database':
        return DatabaseConnection.query.get(connection_id)
    if connection_type == 'storage':
        return StorageConnection.query.get(connection_id)
    return None


# --- Groups ---

@bp.route('/groups', methods=['GET'])
@admin_required
def list_groups():
    groups = Group.query.order_by(Group.name).all()
    return jsonify({'groups': [g.to_dict() for g in groups]})


@bp.route('/groups', methods=['POST'])
@admin_required
def create_group():
    data = request.get_json() or {}
    if not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    if Group.query.filter_by(name=data['name']).first():
        return jsonify({'error': 'A group with that name already exists'}), 409

    group = Group(name=data['name'], description=data.get('description'))
    db.session.add(group)
    db.session.commit()
    return jsonify(group.to_dict()), 201


@bp.route('/groups/<int:group_id>', methods=['GET'])
@admin_required
def get_group(group_id):
    group = Group.query.get_or_404(group_id)
    data = group.to_dict()
    data['permission_ids'] = [p.id for p in group.permissions]
    data['member_ids'] = [u.id for u in group.users]
    data['clearances'] = [c.to_dict() for c in group.connection_clearances]
    return jsonify(data)


# --- Permissions / Environments (read-only here - full CRUD via Flask-Admin) ---

@bp.route('/permissions', methods=['GET'])
@admin_required
def list_permissions():
    permissions = Permission.query.order_by(Permission.resource_type, Permission.action).all()
    return jsonify({'permissions': [p.to_dict() for p in permissions]})


@bp.route('/environments', methods=['GET'])
@admin_required
def list_environments():
    environments = Environment.query.order_by(Environment.name).all()
    return jsonify({'environments': [e.to_dict() for e in environments]})


# --- Connections ---

@bp.route('/connections', methods=['GET'])
@admin_required
def list_connections():
    db_connections = [dict(c.to_dict(), connection_ref_type='database') for c in DatabaseConnection.query.all()]
    storage_connections = [dict(c.to_dict(), connection_ref_type='storage') for c in StorageConnection.query.all()]
    return jsonify({'connections': db_connections + storage_connections})


@bp.route('/connections/<conn_type>/<int:connection_id>/test', methods=['POST'])
@admin_required
def test_connection(conn_type, connection_id):
    connection = _resolve_connection(conn_type, connection_id)
    if not connection:
        return jsonify({'error': 'Connection not found'}), 404

    from essentialpipeline.services.connection_health import test_database_connection, test_storage_connection
    result = test_database_connection(connection) if conn_type == 'database' else test_storage_connection(connection)
    return jsonify(result)


# --- Connection Clearances ---

@bp.route('/clearances', methods=['GET'])
@admin_required
def list_clearances():
    query = GroupConnectionClearance.query
    group_id = request.args.get('group_id', type=int)
    if group_id:
        query = query.filter_by(group_id=group_id)
    return jsonify({'clearances': [c.to_dict() for c in query.all()]})


@bp.route('/clearances', methods=['POST'])
@admin_required
def create_clearance():
    data = request.get_json() or {}
    group_id = data.get('group_id')
    connection_type = data.get('connection_type')
    connection_id = data.get('connection_id')
    access_level = data.get('access_level', 'read')

    if not group_id or connection_type not in ('database', 'storage') or not connection_id:
        return jsonify({'error': 'group_id, connection_type (database|storage), and connection_id are required'}), 400

    if not Group.query.get(group_id):
        return jsonify({'error': 'Group not found'}), 404
    if not _resolve_connection(connection_type, connection_id):
        return jsonify({'error': 'Connection not found'}), 404

    existing = GroupConnectionClearance.query.filter_by(
        group_id=group_id, connection_type=connection_type, connection_id=connection_id
    ).first()
    if existing:
        existing.access_level = access_level
        db.session.commit()
        return jsonify(existing.to_dict())

    clearance = GroupConnectionClearance(
        group_id=group_id, connection_type=connection_type,
        connection_id=connection_id, access_level=access_level
    )
    db.session.add(clearance)
    db.session.commit()
    return jsonify(clearance.to_dict()), 201


@bp.route('/clearances/<int:clearance_id>', methods=['PATCH'])
@admin_required
def update_clearance(clearance_id):
    clearance = GroupConnectionClearance.query.get_or_404(clearance_id)
    data = request.get_json() or {}
    if 'access_level' in data:
        clearance.access_level = data['access_level']
    db.session.commit()
    return jsonify(clearance.to_dict())


@bp.route('/clearances/<int:clearance_id>', methods=['DELETE'])
@admin_required
def delete_clearance(clearance_id):
    clearance = GroupConnectionClearance.query.get_or_404(clearance_id)
    db.session.delete(clearance)
    db.session.commit()
    return jsonify({'message': 'Clearance deleted'}), 200


# --- Audit Logs ---

@bp.route('/audit-logs', methods=['GET'])
@admin_required
def list_audit_logs():
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
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'logs': [log.to_dict() for log in pagination.items],
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total
    })


# --- Monitoring: system metrics ---

@bp.route('/metrics', methods=['GET'])
@admin_required
def list_metrics():
    query = SystemMetric.query
    metric_type = request.args.get('metric_type')
    if metric_type:
        query = query.filter_by(metric_type=metric_type)

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    pagination = query.order_by(SystemMetric.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'metrics': [m.to_dict() for m in pagination.items],
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total
    })


# --- Monitoring: alerts ---

@bp.route('/alerts', methods=['GET'])
@admin_required
def list_alerts():
    query = Alert.query
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    pagination = query.order_by(Alert.triggered_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'alerts': [a.to_dict() for a in pagination.items],
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total
    })


@bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@admin_required
def acknowledge_alert_route(alert_id):
    from essentialpipeline.services.alerting import acknowledge_alert

    alert = Alert.query.get_or_404(alert_id)
    try:
        acknowledge_alert(alert)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(alert.to_dict())


@bp.route('/alerts/<int:alert_id>/resolve', methods=['POST'])
@admin_required
def resolve_alert_route(alert_id):
    from flask_jwt_extended import get_jwt_identity
    from essentialpipeline.models import User
    from essentialpipeline.services.alerting import resolve_alert

    alert = Alert.query.get_or_404(alert_id)
    actor = User.query.get(int(get_jwt_identity()))
    data = request.get_json(silent=True) or {}
    try:
        resolve_alert(alert, actor, notes=data.get('notes'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(alert.to_dict())


# --- Monitoring: alert rules (read-only here - full CRUD via Flask-Admin) ---

@bp.route('/alert-rules', methods=['GET'])
@admin_required
def list_alert_rules():
    rules = AlertRule.query.order_by(AlertRule.name).all()
    return jsonify({'alert_rules': [r.to_dict() for r in rules]})
