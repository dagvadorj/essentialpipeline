"""
Alert notification dispatch (Monitoring layer, plan.md P5).

Three channels, matching AlertRule.notification_channels:
- 'email': stdlib smtplib. Needs SMTP_HOST configured; without it, this
  is a documented no-op (logged, not raised) rather than pretending to
  have sent something - the same pattern services/connection_health.py
  uses for connection types with no driver installed.
- 'slack' / 'webhook': both are a JSON HTTP POST (Slack's Incoming
  Webhooks are exactly that), one per URL in notification_targets.

A failure in one channel or target never stops the others, and this
function never raises back into the alert-evaluation loop that calls it
(services/alerting.py) - a broken notification integration shouldn't
prevent an alert from being recorded.
"""

import logging
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 5


def send_notifications(alert) -> dict:
    """Returns {channel: [(target, ok_or_None, detail), ...]} for callers/tests that want to inspect what happened."""
    rule = alert.alert_rule
    results = {}
    for channel in (rule.notification_channels or []):
        try:
            if channel == 'email':
                results[channel] = _send_email(alert)
            elif channel in ('slack', 'webhook'):
                results[channel] = _send_webhook(alert)
            else:
                logger.warning(f"Alert {alert.id}: unknown notification channel '{channel}'")
        except Exception as e:
            logger.error(f"Alert {alert.id}: notification channel '{channel}' failed: {e}")
    return results


def _targets(alert) -> list:
    targets = alert.alert_rule.notification_targets or []
    return targets if isinstance(targets, list) else [targets]


def _send_email(alert) -> list:
    from flask import current_app

    config = current_app.config
    if not config.get('SMTP_HOST'):
        logger.info(f"Alert {alert.id}: SMTP_HOST not configured, skipping email notification")
        return [('*', None, 'SMTP not configured')]

    recipients = _targets(alert)
    if not recipients:
        return []

    msg = EmailMessage()
    msg['Subject'] = f"[{alert.severity}] {alert.title}"
    msg['From'] = config.get('SMTP_FROM_ADDRESS')
    msg['To'] = ', '.join(recipients)
    msg.set_content(alert.message)

    try:
        with smtplib.SMTP(config['SMTP_HOST'], config.get('SMTP_PORT', 587), timeout=_HTTP_TIMEOUT_SECONDS) as smtp:
            if config.get('SMTP_USE_TLS', True):
                smtp.starttls()
            if config.get('SMTP_USERNAME'):
                smtp.login(config['SMTP_USERNAME'], config['SMTP_PASSWORD'])
            smtp.send_message(msg)
        return [(', '.join(recipients), True, None)]
    except Exception as e:
        return [(', '.join(recipients), False, str(e))]


def _send_webhook(alert) -> list:
    import requests

    payload = {'text': f"[{alert.severity}] {alert.title}: {alert.message}", 'alert': alert.to_dict()}
    results = []
    for url in _targets(alert):
        try:
            resp = requests.post(url, json=payload, timeout=_HTTP_TIMEOUT_SECONDS)
            ok = 200 <= resp.status_code < 300
            results.append((url, ok, None if ok else f'HTTP {resp.status_code}'))
        except Exception as e:
            results.append((url, False, str(e)))
    return results
