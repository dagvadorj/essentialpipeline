"""
Admin Monitoring routes for EssentialPipeline.

Surfaces what services/metrics.py and services/alerting.py now populate:
SystemMetric (collected on a schedule) and Alert (fired by AlertRule
evaluation). AlertRule itself gets raw CRUD via Flask-Admin
(admin_setup.py), the same split governance.py uses for Group/Permission -
this blueprint covers what Flask-Admin can't do well: latest-value
dashboards and the acknowledge/resolve lifecycle actions.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from essentialpipeline.app.middleware import admin_required
from essentialpipeline.models import SystemMetric, Alert, AlertRule
from essentialpipeline.services.metrics import METRIC_TYPES
from essentialpipeline.services.alerting import acknowledge_alert, resolve_alert

bp = Blueprint('admin_monitoring', __name__)


@bp.route('/')
@admin_required
def dashboard():
    """Latest reading per metric type, plus open/acknowledged alert counts"""
    latest_metrics = {}
    for metric_type in METRIC_TYPES:
        latest_metrics[metric_type] = (
            SystemMetric.query.filter_by(metric_type=metric_type)
            .order_by(SystemMetric.timestamp.desc()).first()
        )

    counts = {
        'open_alerts': Alert.query.filter_by(status='open').count(),
        'acknowledged_alerts': Alert.query.filter_by(status='acknowledged').count(),
        'alert_rules': AlertRule.query.filter_by(is_active=True).count(),
    }
    recent_alerts = Alert.query.order_by(Alert.triggered_at.desc()).limit(10).all()

    return render_template(
        'admin/monitoring/dashboard.html', title='Monitoring',
        latest_metrics=latest_metrics, counts=counts, recent_alerts=recent_alerts
    )


@bp.route('/metrics')
@admin_required
def list_metrics():
    """System metric history, optionally filtered by type"""
    metric_type = request.args.get('metric_type', '')
    query = SystemMetric.query
    if metric_type:
        query = query.filter_by(metric_type=metric_type)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(SystemMetric.timestamp.desc()).paginate(page=page, per_page=50, error_out=False)

    return render_template(
        'admin/monitoring/metrics_list.html', title='System Metrics',
        pagination=pagination, metrics=pagination.items,
        metric_types=METRIC_TYPES, selected_type=metric_type
    )


@bp.route('/alerts')
@admin_required
def list_alerts():
    """Alert history, optionally filtered by status"""
    status = request.args.get('status', '')
    query = Alert.query
    if status:
        query = query.filter_by(status=status)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(Alert.triggered_at.desc()).paginate(page=page, per_page=50, error_out=False)

    return render_template(
        'admin/monitoring/alerts_list.html', title='Alerts',
        pagination=pagination, alerts=pagination.items, selected_status=status
    )


@bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@admin_required
def acknowledge(alert_id):
    alert = Alert.query.get_or_404(alert_id)
    try:
        acknowledge_alert(alert)
        flash(f'Alert "{alert.title}" acknowledged', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('admin_monitoring.list_alerts'))


@bp.route('/alerts/<int:alert_id>/resolve', methods=['POST'])
@admin_required
def resolve(alert_id):
    from flask_jwt_extended import get_jwt_identity
    from essentialpipeline.models import User

    alert = Alert.query.get_or_404(alert_id)
    actor = User.query.get(int(get_jwt_identity()))
    try:
        resolve_alert(alert, actor, notes=request.form.get('notes'))
        flash(f'Alert "{alert.title}" resolved', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    return redirect(url_for('admin_monitoring.list_alerts'))
