"""
Tests for services/governance_gate.py and the publish routes that use it
(web: user/projects.py, API: api/v1/projects.py).
"""

import pytest

from essentialpipeline.models import (
    Group, Permission, ProjectVersion, SecurityParseResult
)
from essentialpipeline.services.governance_gate import evaluate_publish_gate


def _grant_project_write(db_session, user):
    group = Group(name='writers')
    db_session.add(group)
    db_session.flush()
    perm = Permission(name='project_write', resource_type='project', action='write')
    db_session.add(perm)
    db_session.flush()
    group.permissions.append(perm)
    user.groups.append(group)
    db_session.commit()
    return group


class TestEvaluatePublishGate:
    def test_blocked_with_no_clearance(self, db_session, test_user, make_project_version):
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        result = evaluate_publish_gate(test_user, version)
        assert result['passed'] is False
        clearance_check = next(c for c in result['checks'] if c['name'] == 'publish_clearance')
        assert clearance_check['passed'] is False

    def test_allowed_with_clearance_and_clean_scan(self, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        result = evaluate_publish_gate(test_user, version)
        assert result['passed'] is True

    def test_blocked_by_a_failed_security_scan_even_with_clearance(self, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        db_session.add(SecurityParseResult(project_version_id=version.id, overall_status='failed'))
        db_session.commit()

        result = evaluate_publish_gate(test_user, version)
        assert result['passed'] is False
        scan_check = next(c for c in result['checks'] if c['name'] == 'security_scan')
        assert scan_check['passed'] is False

    def test_warning_only_scan_does_not_block(self, db_session, test_user, make_project_version):
        """Decision 6: audit-only findings (Bandit) never block, only 'failed' does"""
        _grant_project_write(db_session, test_user)
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        db_session.add(SecurityParseResult(project_version_id=version.id, overall_status='warning'))
        db_session.commit()

        result = evaluate_publish_gate(test_user, version)
        assert result['passed'] is True

    def test_read_only_permission_is_not_enough(self, db_session, test_user, make_project_version):
        """A group with project *read* clearance shouldn't satisfy the write/admin check"""
        group = Group(name='readers')
        db_session.add(group)
        db_session.flush()
        perm = Permission(name='project_read', resource_type='project', action='read')
        db_session.add(perm)
        db_session.flush()
        group.permissions.append(perm)
        test_user.groups.append(group)
        db_session.commit()

        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        result = evaluate_publish_gate(test_user, version)
        assert result['passed'] is False


class TestPublishRoutesWeb:
    def test_publish_blocked_without_clearance(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/user/projects/{project_id}/versions/{version_id}/publish',
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert ProjectVersion.query.get(version_id).is_published is False
        assert b'governance gate' in resp.data.lower()

    def test_publish_succeeds_with_clearance(self, client, auth_headers, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/user/projects/{project_id}/versions/{version_id}/publish',
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        version = ProjectVersion.query.get(version_id)
        assert version.is_published is True
        assert version.published_by == test_user.id
        assert version.published_at is not None

    def test_publishing_twice_is_a_no_op_with_message(self, client, auth_headers, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        client.post(f'/user/projects/{project_id}/versions/{version_id}/publish', headers=auth_headers)

        resp = client.post(f'/user/projects/{project_id}/versions/{version_id}/publish',
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already published' in resp.data.lower()

    def test_version_project_mismatch_rejected(self, client, auth_headers, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'}, project_name='P1')
        other_project_id, _ = make_project_version(test_user.id, {'main.py': 'x'}, project_name='P2')

        resp = client.post(f'/user/projects/{other_project_id}/versions/{version_id}/publish',
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert b'does not belong' in resp.data.lower()
        assert ProjectVersion.query.get(version_id).is_published is False

    def test_other_users_project_publish_denied(self, client, other_auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/user/projects/{project_id}/versions/{version_id}/publish',
                            headers=other_auth_headers, follow_redirects=True)
        assert ProjectVersion.query.get(version_id).is_published is False


class TestPublishRoutesApi:
    def test_publish_blocked_without_clearance_returns_403_with_checks(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/api/v1/projects/{project_id}/versions/{version_id}/publish', headers=auth_headers)
        assert resp.status_code == 403
        body = resp.get_json()
        assert body['error'] == 'Publish blocked by governance gate'
        assert any(c['name'] == 'publish_clearance' and not c['passed'] for c in body['checks'])

    def test_publish_succeeds_with_clearance(self, client, auth_headers, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/api/v1/projects/{project_id}/versions/{version_id}/publish', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['is_published'] is True

    def test_publishing_twice_returns_409(self, client, auth_headers, db_session, test_user, make_project_version):
        _grant_project_write(db_session, test_user)
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        client.post(f'/api/v1/projects/{project_id}/versions/{version_id}/publish', headers=auth_headers)

        resp = client.post(f'/api/v1/projects/{project_id}/versions/{version_id}/publish', headers=auth_headers)
        assert resp.status_code == 409
