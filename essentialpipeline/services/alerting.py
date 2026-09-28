"""
Alert rule evaluation and lifecycle (Monitoring layer, plan.md P5).

AlertRule/Alert existed as pure data models with nothing creating or
evaluating them, the same situation Deployment/Approval and
DeploymentLog/SecurityLog were each in before earlier passes.

Two of AlertRule.condition_type's three documented values are
implemented here, against SystemMetric data (see services/metrics.py):
- 'threshold': condition_config = {"metric_type": str, "operator":
  one of ">" ">=" "<" "<=" "==", "value": number}. Fires if the most
  recent metric of that type satisfies the comparison.
- 'absence': condition_config = {"metric_type": str, "window_minutes":
  number}. Fires if no metric of that type was recorded within the
  window - e.g. the collector itself stopped running.

The third, 'anomaly', has no evaluator - condition_type is a free
string on the model, not an enum, so a rule can exist with it, but
evaluate_alert_rules() logs and skips it. A real anomaly detector needs
a statistical model this project has no basis for choosing yet (same
"needs a decision, not just scoping" situation as Decision 6's
still-unchosen secret-detection/container-scanning tools).

Re-firing is suppressed while an alert for the same rule is still open
or acknowledged, so a sustained condition doesn't create a new row
every evaluation cycle - only after the existing one is resolved.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_COMPARATORS = {
    '>': lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<': lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
    '==': lambda a, b: a == b,
}


class AlertRuleConfigError(ValueError):
    """Raised when an AlertRule's condition_config doesn't match its condition_type"""
    pass


def evaluate_alert_rules() -> list:
    """Evaluates every active AlertRule. Returns the Alerts newly created this pass."""
    from essentialpipeline.models import AlertRule

    triggered = []
    for rule in AlertRule.query.filter_by(is_active=True).all():
        try:
            fired, message = _evaluate_rule(rule)
        except AlertRuleConfigError as e:
            logger.warning(f"Alert rule {rule.id} ({rule.name}) has an invalid condition_config: {e}")
            continue
        if fired:
            alert = _fire_alert(rule, message)
            if alert:
                triggered.append(alert)
    return triggered


def _evaluate_rule(rule):
    if rule.condition_type == 'threshold':
        return _evaluate_threshold(rule)
    if rule.condition_type == 'absence':
        return _evaluate_absence(rule)
    logger.debug(f"Alert rule {rule.id} has condition_type '{rule.condition_type}', which has no evaluator")
    return False, None


def _evaluate_threshold(rule):
    from essentialpipeline.models import SystemMetric

    config = rule.condition_config or {}
    metric_type, operator, value = config.get('metric_type'), config.get('operator'), config.get('value')
    if not metric_type or operator not in _COMPARATORS or value is None:
        raise AlertRuleConfigError(str(config))

    latest = SystemMetric.query.filter_by(metric_type=metric_type).order_by(SystemMetric.timestamp.desc()).first()
    if latest is None:
        return False, None

    if _COMPARATORS[operator](latest.metric_value, value):
        return True, f"{metric_type} is {latest.metric_value} ({operator} {value})"
    return False, None


def _evaluate_absence(rule):
    from essentialpipeline.models import SystemMetric

    config = rule.condition_config or {}
    metric_type, window_minutes = config.get('metric_type'), config.get('window_minutes')
    if not metric_type or not window_minutes:
        raise AlertRuleConfigError(str(config))

    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    recent = SystemMetric.query.filter(
        SystemMetric.metric_type == metric_type, SystemMetric.timestamp >= cutoff
    ).first()
    if recent is None:
        return True, f"No {metric_type} metric received in the last {window_minutes} minute(s)"
    return False, None


def _fire_alert(rule, message):
    from essentialpipeline import db
    from essentialpipeline.models import Alert

    already_active = Alert.query.filter(
        Alert.alert_rule_id == rule.id, Alert.status.in_(['open', 'acknowledged'])
    ).first()
    if already_active:
        return None

    severity = (rule.condition_config or {}).get('severity', 'medium')
    alert = Alert(alert_rule_id=rule.id, severity=severity, status='open', title=rule.name, message=message)
    db.session.add(alert)
    db.session.commit()
    logger.warning(f"Alert triggered: {rule.name}: {message}")

    from essentialpipeline.services.notifications import send_notifications
    send_notifications(alert)
    return alert


def _evaluate_entrypoint():
    from essentialpipeline.services import scheduler as scheduler_module
    with scheduler_module._app.app_context():
        evaluate_alert_rules()


def schedule_alert_evaluation(app) -> bool:
    """No-op (and returns False) if the scheduler is disabled - matches schedule_all_tasks()'s own guard."""
    from essentialpipeline.services import scheduler as scheduler_module

    if not scheduler_module.scheduler:
        logger.info("Scheduler not initialized; alert rule evaluation not scheduled")
        return False

    interval = app.config.get('ALERT_EVALUATION_INTERVAL_MINUTES', 1)
    scheduler_module.scheduler.add_job(
        _evaluate_entrypoint, 'interval', minutes=interval,
        id='alert_rule_evaluator', name='Alert rule evaluator', replace_existing=True
    )
    logger.info(f"Scheduled alert rule evaluation every {interval} minute(s)")
    return True


def acknowledge_alert(alert):
    from essentialpipeline import db

    if alert.status != 'open':
        raise ValueError(f"Alert is '{alert.status}', not 'open'")
    alert.status = 'acknowledged'
    alert.acknowledged_at = datetime.utcnow()
    db.session.commit()
    return alert


def resolve_alert(alert, actor, notes=None):
    from essentialpipeline import db

    if alert.status == 'resolved':
        raise ValueError('Alert is already resolved')
    alert.status = 'resolved'
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = actor.id
    alert.resolution_notes = notes
    db.session.commit()
    return alert
