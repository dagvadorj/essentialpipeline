"""
Tests for the log viewer (web: user/logs.py, API: api/v1/logs.py) and
the DeploymentLog/SecurityLog wiring added to services/deployment.py and
services/security_scan.py - previously those two tables were pure,
never-written data models, same situation Deployment/Approval were in
before the approval workflow was built.
"""

import pytest

from essentialpipeline.models import (
    ExecutionLog, DeploymentLog, SecurityLog, Environment, Group, Permission
)
from essentialpipeline.services.deployment import request_deployment, approve, mark_deployed, rollback
from essentialpipeline.services.security_scan import scan_uploaded_version
from essentialpipeline.services import scheduler as scheduler_module
from essentialpipeline.services.scheduler import execute_task


def _grant(db_session, user, action, resource_type='deployment'):
    group = Group(name=f'{resource_type}-{action}-{user.username}-loggrant')
    db_session.add(group)
    db_session.flush()
    perm = Permission(name=f'{resource_type}_{action}_loggrant', resource_type=resource_type, action=action)
    db_session.add(perm)
    db_session.flush()
    group.permissions.append(perm)
    user.groups.append(group)
    db_session.commit()


class TestDeploymentLogWiring:
    def test_full_workflow_writes_a_log_entry_per_transition(self, db_session, test_user, other_user, make_project_version):
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        _grant(db_session, other_user, 'admin')

        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        from essentialpipeline.models import ProjectVersion
        version = ProjectVersion.query.get(version_id)
        version.is_published = True
        db_session.commit()

        env = Environment(name='dev-log-test', is_production=False)
        db_session.add(env)
        db_session.commit()

        deployment = request_deployment(version, env, test_user)
        approve(deployment, other_user)
        mark_deployed(deployment, other_user)
        rollback(deployment, other_user, 'test rollback')

        logs = DeploymentLog.query.filter_by(deployment_id=deployment.id).order_by(DeploymentLog.id).all()
        assert len(logs) == 4
        assert 'requested' in logs[0].message.lower()
        assert 'approved' in logs[1].message.lower()
        assert 'deployed' in logs[2].message.lower()
        assert logs[3].level == 'error'
        assert logs[3].context == {'reason': 'test rollback'}


class TestSecurityLogWiring:
    def test_scan_writes_started_and_completed_events(self, db_session, test_user, make_project_version):
        _, version_id = make_project_version(test_user.id, {'main.py': 'print(1)\n'})
        from essentialpipeline.models import ProjectVersion
        version = ProjectVersion.query.get(version_id)

        result = scan_uploaded_version(version)

        logs = SecurityLog.query.filter_by(parse_result_id=result.id).order_by(SecurityLog.id).all()
        event_types = [l.event_type for l in logs]
        assert event_types[0] == 'scan_started'
        assert event_types[-1] == 'scan_completed'

    def test_each_finding_gets_its_own_log_entry(self, db_session, test_user, make_project_version):
        _, version_id = make_project_version(test_user.id, {
            'main.py': 'import subprocess\nsubprocess.call("ls", shell=True)\n'
        })
        from essentialpipeline.models import ProjectVersion
        version = ProjectVersion.query.get(version_id)

        result = scan_uploaded_version(version)
        finding_logs = SecurityLog.query.filter_by(parse_result_id=result.id, event_type='finding_detected').all()
        assert len(finding_logs) >= 1


class TestApiLogRoutes:
    def test_execution_logs_scoped_to_own_projects(self, client, auth_headers, other_auth_headers, monkeypatch,
                                                     db_session, test_user, other_user, make_project_version):
        from essentialpipeline.models import Task

        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()

        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda t, r: {'exit_code': 0, 'output': 'hi\n', 'error': None, 'duration': 0.1, 'logs': 'hi\n'}
        )
        with client.application.app_context():
            execute_task(task.id, triggered_by='manual')

        resp = client.get('/api/v1/logs/execution', headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['total'] == 1
        assert body['logs'][0]['stdout'] == 'hi\n'

        resp = client.get('/api/v1/logs/execution', headers=other_auth_headers)
        assert resp.get_json()['total'] == 0

    def test_deployment_logs_visible_to_approver_not_just_owner(self, client, auth_headers, other_auth_headers,
                                                                  db_session, test_user, other_user, make_project_version):
        from essentialpipeline.models import ProjectVersion

        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')

        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)
        version.is_published = True
        db_session.commit()

        env = Environment(name='dev-log-test2', is_production=False)
        db_session.add(env)
        db_session.commit()

        deployment = request_deployment(version, env, test_user)

        resp = client.get('/api/v1/logs/deployment', headers=auth_headers)
        assert resp.get_json()['total'] == 1

        resp = client.get('/api/v1/logs/deployment', headers=other_auth_headers)
        assert resp.get_json()['total'] == 1

    def test_security_logs_scoped_to_own_projects(self, client, auth_headers, other_auth_headers,
                                                    db_session, test_user, make_project_version):
        from essentialpipeline.models import ProjectVersion

        _, version_id = make_project_version(test_user.id, {'main.py': 'print(1)\n'})
        version = ProjectVersion.query.get(version_id)
        scan_uploaded_version(version)

        resp = client.get('/api/v1/logs/security', headers=auth_headers)
        assert resp.get_json()['total'] > 0

        resp = client.get('/api/v1/logs/security', headers=other_auth_headers)
        assert resp.get_json()['total'] == 0

    def test_level_filter(self, client, auth_headers, db_session, test_user, make_project_version):
        from essentialpipeline.models import ProjectVersion

        _, version_id = make_project_version(test_user.id, {
            'main.py': 'import subprocess\nsubprocess.call("ls", shell=True)\n'
        })
        version = ProjectVersion.query.get(version_id)
        scan_uploaded_version(version)

        resp = client.get('/api/v1/logs/security?level=info', headers=auth_headers)
        assert resp.status_code == 200
        assert all(l['level'] == 'info' for l in resp.get_json()['logs'])


class TestWebLogsPage:
    def test_page_renders_for_each_type(self, client, auth_headers):
        for log_type in ('execution', 'deployment', 'security'):
            resp = client.get(f'/user/logs/?type={log_type}', headers=auth_headers)
            assert resp.status_code == 200

    def test_invalid_type_falls_back_to_execution(self, client, auth_headers):
        resp = client.get('/user/logs/?type=nonsense', headers=auth_headers)
        assert resp.status_code == 200
