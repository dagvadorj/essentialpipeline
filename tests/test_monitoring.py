"""
Tests for the Monitoring layer (plan.md P5): services/metrics.py,
services/alerting.py, services/notifications.py, and the admin/API
routes that expose SystemMetric/Alert/AlertRule.
"""

import pytest

from essentialpipeline.models import SystemMetric, Alert, AlertRule
from essentialpipeline.services.metrics import collect_system_metrics, METRIC_TYPES
from essentialpipeline.services.alerting import (
    evaluate_alert_rules, acknowledge_alert, resolve_alert, AlertRuleConfigError,
    _evaluate_threshold, _evaluate_absence,
)


# --- services/metrics.py ---

class TestCollectSystemMetrics:
    def test_writes_one_row_per_metric_type(self, app, db_session):
        with app.app_context():
            rows = collect_system_metrics()
            assert {r.metric_type for r in rows} == set(METRIC_TYPES)
        assert SystemMetric.query.count() == len(METRIC_TYPES)

    def test_missing_psutil_is_swallowed(self, app, db_session, monkeypatch):
        import essentialpipeline.services.metrics as metrics_module
        import builtins

        real_import = builtins.__import__

        def _fail_psutil(name, *args, **kwargs):
            if name == 'psutil':
                raise ImportError('no psutil')
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', _fail_psutil)
        with app.app_context():
            rows = metrics_module.collect_system_metrics()
        assert rows == []
        assert SystemMetric.query.count() == 0


# --- services/alerting.py ---

@pytest.fixture
def cpu_rule(db_session):
    rule = AlertRule(
        name='High CPU', condition_type='threshold',
        condition_config={'metric_type': 'cpu_usage', 'operator': '>', 'value': 90, 'severity': 'high'},
        notification_channels=[], is_active=True
    )
    db_session.add(rule)
    db_session.commit()
    return rule


@pytest.fixture
def absence_rule(db_session):
    rule = AlertRule(
        name='Collector Down', condition_type='absence',
        condition_config={'metric_type': 'cpu_usage', 'window_minutes': 5},
        notification_channels=[], is_active=True
    )
    db_session.add(rule)
    db_session.commit()
    return rule


class TestEvaluateThreshold:
    def test_no_data_does_not_fire(self, db_session, cpu_rule):
        fired, message = _evaluate_threshold(cpu_rule)
        assert fired is False

    def test_fires_when_condition_met(self, db_session, cpu_rule):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=95.0))
        db_session.commit()
        fired, message = _evaluate_threshold(cpu_rule)
        assert fired is True
        assert '95.0' in message

    def test_does_not_fire_when_below_threshold(self, db_session, cpu_rule):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=10.0))
        db_session.commit()
        fired, _ = _evaluate_threshold(cpu_rule)
        assert fired is False

    def test_invalid_config_raises(self, db_session):
        bad_rule = AlertRule(
            name='Bad', condition_type='threshold', condition_config={'metric_type': 'cpu_usage'},
            notification_channels=[], is_active=True
        )
        with pytest.raises(AlertRuleConfigError):
            _evaluate_threshold(bad_rule)


class TestEvaluateAbsence:
    def test_fires_when_nothing_recorded(self, db_session, absence_rule):
        fired, _ = _evaluate_absence(absence_rule)
        assert fired is True

    def test_does_not_fire_when_recent_data_exists(self, db_session, absence_rule):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=5.0))
        db_session.commit()
        fired, _ = _evaluate_absence(absence_rule)
        assert fired is False


class TestEvaluateAlertRules:
    def test_fires_and_creates_alert(self, app, db_session, cpu_rule):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=99.0))
        db_session.commit()

        with app.app_context():
            triggered = evaluate_alert_rules()

        assert len(triggered) == 1
        assert Alert.query.count() == 1
        assert Alert.query.first().alert_rule_id == cpu_rule.id

    def test_does_not_duplicate_while_open(self, app, db_session, cpu_rule):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=99.0))
        db_session.commit()

        with app.app_context():
            evaluate_alert_rules()
            evaluate_alert_rules()

        assert Alert.query.count() == 1

    def test_refires_after_resolution(self, app, db_session, cpu_rule, admin_user):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=99.0))
        db_session.commit()

        with app.app_context():
            evaluate_alert_rules()
            resolve_alert(Alert.query.first(), admin_user)
            evaluate_alert_rules()

        assert Alert.query.count() == 2

    def test_inactive_rule_is_skipped(self, app, db_session, cpu_rule):
        cpu_rule.is_active = False
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=99.0))
        db_session.commit()

        with app.app_context():
            triggered = evaluate_alert_rules()
        assert triggered == []

    def test_unconfigured_rule_is_skipped_not_raised(self, app, db_session):
        bad_rule = AlertRule(
            name='Bad', condition_type='threshold', condition_config={},
            notification_channels=[], is_active=True
        )
        db_session.add(bad_rule)
        db_session.commit()

        with app.app_context():
            triggered = evaluate_alert_rules()
        assert triggered == []


class TestAcknowledgeAndResolve:
    def test_acknowledge_open_alert(self, db_session, cpu_rule):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        acknowledge_alert(alert)
        assert alert.status == 'acknowledged'
        assert alert.acknowledged_at is not None

    def test_cannot_acknowledge_non_open_alert(self, db_session, cpu_rule):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='resolved', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        with pytest.raises(ValueError):
            acknowledge_alert(alert)

    def test_resolve_records_actor_and_notes(self, db_session, cpu_rule, admin_user):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        resolve_alert(alert, admin_user, notes='fixed it')
        assert alert.status == 'resolved'
        assert alert.resolved_by == admin_user.id
        assert alert.resolution_notes == 'fixed it'

    def test_cannot_resolve_already_resolved(self, db_session, cpu_rule, admin_user):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='resolved', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        with pytest.raises(ValueError):
            resolve_alert(alert, admin_user)


# --- services/notifications.py ---

class TestSendNotifications:
    def test_email_is_noop_without_smtp_host(self, app, db_session, cpu_rule):
        from essentialpipeline.services.notifications import send_notifications

        cpu_rule.notification_channels = ['email']
        cpu_rule.notification_targets = ['ops@example.com']
        db_session.commit()
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        with app.app_context():
            results = send_notifications(alert)
        assert results['email'][0][1] is None  # ok_or_None is None for "not configured"

    def test_webhook_success(self, app, db_session, cpu_rule, monkeypatch):
        import requests
        from essentialpipeline.services.notifications import send_notifications

        cpu_rule.notification_channels = ['webhook']
        cpu_rule.notification_targets = ['https://example.com/hook']
        db_session.commit()
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        class _FakeResponse:
            status_code = 200

        monkeypatch.setattr(requests, 'post', lambda *a, **k: _FakeResponse())

        with app.app_context():
            results = send_notifications(alert)
        assert results['webhook'][0][1] is True

    def test_unknown_channel_is_logged_not_raised(self, app, db_session, cpu_rule):
        from essentialpipeline.services.notifications import send_notifications

        cpu_rule.notification_channels = ['carrier_pigeon']
        db_session.commit()
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        with app.app_context():
            results = send_notifications(alert)
        assert results == {}


# --- admin routes ---

class TestAdminMonitoringRoutes:
    def test_dashboard_requires_admin(self, client, auth_headers):
        resp = client.get('/admin/monitoring/', headers=auth_headers)
        assert resp.status_code == 403

    def test_dashboard_ok_for_admin(self, client, admin_headers):
        resp = client.get('/admin/monitoring/', headers=admin_headers)
        assert resp.status_code == 200

    def test_metrics_list(self, client, admin_headers, db_session):
        db_session.add(SystemMetric(metric_type='cpu_usage', metric_value=42.0))
        db_session.commit()
        resp = client.get('/admin/monitoring/metrics', headers=admin_headers)
        assert resp.status_code == 200

    def test_alerts_list_and_acknowledge(self, client, admin_headers, db_session, cpu_rule):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        resp = client.get('/admin/monitoring/alerts', headers=admin_headers)
        assert resp.status_code == 200

        resp = client.post(f'/admin/monitoring/alerts/{alert.id}/acknowledge', headers=admin_headers)
        assert resp.status_code == 302
        assert Alert.query.get(alert.id).status == 'acknowledged'


# --- API routes ---

class TestApiMonitoringRoutes:
    def test_metrics_requires_admin(self, client, auth_headers):
        resp = client.get('/api/v1/admin/metrics', headers=auth_headers)
        assert resp.status_code == 403

    def test_list_metrics(self, client, admin_headers, db_session):
        db_session.add(SystemMetric(metric_type='memory_usage', metric_value=50.0))
        db_session.commit()
        resp = client.get('/api/v1/admin/metrics', headers=admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()['total'] == 1

    def test_list_alert_rules(self, client, admin_headers, cpu_rule):
        resp = client.get('/api/v1/admin/alert-rules', headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.get_json()['alert_rules']) == 1

    def test_acknowledge_and_resolve_via_api(self, client, admin_headers, db_session, cpu_rule):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='open', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        resp = client.post(f'/api/v1/admin/alerts/{alert.id}/acknowledge', headers=admin_headers)
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'acknowledged'

        resp = client.post(
            f'/api/v1/admin/alerts/{alert.id}/resolve', headers=admin_headers, json={'notes': 'done'}
        )
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'resolved'

    def test_resolve_already_resolved_returns_400(self, client, admin_headers, db_session, cpu_rule):
        alert = Alert(alert_rule_id=cpu_rule.id, severity='high', status='resolved', title='x', message='x')
        db_session.add(alert)
        db_session.commit()

        resp = client.post(f'/api/v1/admin/alerts/{alert.id}/resolve', headers=admin_headers, json={})
        assert resp.status_code == 400
