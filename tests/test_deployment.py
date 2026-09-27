"""
Tests for services/deployment.py (the approval state machine) and the
routes that expose it (web: user/deployments.py, API: api/v1/deployments.py).
"""

import pytest

from essentialpipeline.models import (
    Group, Permission, ProjectVersion, Environment, Deployment, Approval
)
from essentialpipeline.services.deployment import (
    request_deployment, approve, reject, mark_deployed, rollback,
    DeploymentWorkflowError, DeploymentPermissionError
)


def _grant(db_session, user, action, resource_type='deployment'):
    group = Group(name=f'{resource_type}-{action}-{user.username}')
    db_session.add(group)
    db_session.flush()
    perm = Permission(name=f'{resource_type}_{action}', resource_type=resource_type, action=action)
    db_session.add(perm)
    db_session.flush()
    group.permissions.append(perm)
    user.groups.append(group)
    db_session.commit()
    return group


@pytest.fixture
def environments(db_session):
    dev = Environment(name='dev', is_production=False)
    prod = Environment(name='prod', is_production=True)
    db_session.add_all([dev, prod])
    db_session.commit()
    return dev, prod


@pytest.fixture
def published_version(db_session, test_user, make_project_version):
    _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
    version = ProjectVersion.query.get(version_id)
    version.is_published = True
    db_session.commit()
    return version


class TestRequestDeployment:
    def test_blocked_without_clearance(self, db_session, test_user, published_version, environments):
        dev, _ = environments
        with pytest.raises(DeploymentPermissionError):
            request_deployment(published_version, dev, test_user)

    def test_blocked_for_unpublished_version(self, db_session, test_user, make_project_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        version = ProjectVersion.query.get(version_id)

        with pytest.raises(DeploymentWorkflowError, match='published'):
            request_deployment(version, dev, test_user)

    def test_succeeds_with_clearance(self, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')

        deployment = request_deployment(published_version, dev, test_user)
        assert deployment.status == 'pending'
        assert deployment.requested_by == test_user.id

    def test_duplicate_in_flight_request_rejected(self, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        request_deployment(published_version, dev, test_user)

        with pytest.raises(DeploymentWorkflowError, match='already in progress'):
            request_deployment(published_version, dev, test_user)


class TestApprovalStateMachine:
    def test_non_production_needs_only_qa_approval(self, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        _grant(db_session, other_user, 'admin')

        deployment = request_deployment(published_version, dev, test_user)
        approve(deployment, other_user)
        assert deployment.status == 'approved_qa'

        mark_deployed(deployment, other_user)
        assert deployment.status == 'deployed'
        assert deployment.deployed_at is not None

    def test_production_needs_qa_then_prod_approval(self, db_session, test_user, other_user, published_version, environments):
        _, prod = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        _grant(db_session, other_user, 'admin')

        deployment = request_deployment(published_version, prod, test_user)
        approve(deployment, other_user)
        assert deployment.status == 'approved_qa'

        # not deployable yet - still needs the prod stage
        with pytest.raises(DeploymentWorkflowError):
            mark_deployed(deployment, other_user)

        approve(deployment, other_user)
        assert deployment.status == 'approved_prod'

        mark_deployed(deployment, other_user)
        assert deployment.status == 'deployed'

        approvals = Approval.query.filter_by(deployment_id=deployment.id).all()
        assert {a.approval_type for a in approvals} == {'qa', 'prod'}

    def test_requester_cannot_approve_own_deployment(self, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, test_user, 'write')

        deployment = request_deployment(published_version, dev, test_user)
        with pytest.raises(DeploymentPermissionError, match='cannot approve their own'):
            approve(deployment, test_user)

    def test_rejection_is_terminal(self, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')

        deployment = request_deployment(published_version, dev, test_user)
        reject(deployment, other_user, comments='not ready')
        assert deployment.status == 'rejected_qa'

        with pytest.raises(DeploymentWorkflowError, match='no pending approval stage'):
            approve(deployment, other_user)

    def test_reject_at_prod_stage(self, db_session, test_user, other_user, published_version, environments):
        _, prod = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')

        deployment = request_deployment(published_version, prod, test_user)
        approve(deployment, other_user)
        reject(deployment, other_user)
        assert deployment.status == 'rejected_prod'

    def test_cannot_deploy_without_manage_permission(self, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')

        deployment = request_deployment(published_version, dev, test_user)
        approve(deployment, other_user)

        with pytest.raises(DeploymentPermissionError):
            mark_deployed(deployment, other_user)


class TestRollback:
    def test_rollback_from_deployed(self, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        _grant(db_session, other_user, 'admin')

        deployment = request_deployment(published_version, dev, test_user)
        approve(deployment, other_user)
        mark_deployed(deployment, other_user)

        rollback(deployment, other_user, 'broke prod')
        assert deployment.status == 'rolled_back'
        assert deployment.rollback_reason == 'broke prod'

    def test_cannot_rollback_a_non_deployed_deployment(self, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'admin')

        deployment = request_deployment(published_version, dev, test_user)
        with pytest.raises(DeploymentWorkflowError, match='Only a deployed'):
            rollback(deployment, other_user, 'x')


class TestWebRoutes:
    def test_request_deployment_via_web(self, client, auth_headers, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')

        resp = client.post('/user/deployments/new', data={
            'project_version_id': str(published_version.id), 'environment_id': str(dev.id)
        }, headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert Deployment.query.filter_by(project_version_id=published_version.id).count() == 1

    def test_approve_via_web(self, client, auth_headers, other_auth_headers, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        deployment = request_deployment(published_version, dev, test_user)

        resp = client.post(f'/user/deployments/{deployment.id}/approve', data={'comments': 'lgtm'},
                            headers=other_auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert Deployment.query.get(deployment.id).status == 'approved_qa'

    def test_other_user_without_access_cannot_view(self, client, other_auth_headers, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        deployment = request_deployment(published_version, dev, test_user)

        resp = client.get(f'/user/deployments/{deployment.id}', headers=other_auth_headers, follow_redirects=True)
        assert b'Access denied' in resp.data

    def test_approver_without_ownership_can_still_view(self, client, other_auth_headers, db_session, test_user, other_user, published_version, environments):
        """An approver needs to see requests outside their own projects to review them"""
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        deployment = request_deployment(published_version, dev, test_user)

        resp = client.get(f'/user/deployments/{deployment.id}', headers=other_auth_headers)
        assert resp.status_code == 200


class TestApiRoutes:
    def test_full_workflow_via_api(self, client, auth_headers, other_auth_headers, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'write')
        _grant(db_session, other_user, 'admin')

        resp = client.post('/api/v1/deployments/', json={
            'project_version_id': published_version.id, 'environment_id': dev.id
        }, headers=auth_headers)
        assert resp.status_code == 201
        deployment_id = resp.get_json()['id']

        resp = client.post(f'/api/v1/deployments/{deployment_id}/approve', headers=other_auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'approved_qa'

        resp = client.post(f'/api/v1/deployments/{deployment_id}/deploy', headers=other_auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'deployed'

        resp = client.get(f'/api/v1/deployments/{deployment_id}', headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.get_json()['approvals']) == 1

    def test_permission_denied_returns_403(self, client, auth_headers, db_session, test_user, published_version, environments):
        dev, _ = environments
        resp = client.post('/api/v1/deployments/', json={
            'project_version_id': published_version.id, 'environment_id': dev.id
        }, headers=auth_headers)
        assert resp.status_code == 403
        assert 'deployment_request' in resp.get_json()['error']

    def test_state_violation_returns_409(self, client, auth_headers, other_auth_headers, db_session, test_user, other_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        _grant(db_session, other_user, 'admin')
        deployment = request_deployment(published_version, dev, test_user)

        resp = client.post(f'/api/v1/deployments/{deployment.id}/deploy', headers=other_auth_headers)
        assert resp.status_code == 409

    def test_unrelated_user_gets_403_on_get(self, client, other_auth_headers, db_session, test_user, published_version, environments):
        dev, _ = environments
        _grant(db_session, test_user, 'create')
        deployment = request_deployment(published_version, dev, test_user)

        resp = client.get(f'/api/v1/deployments/{deployment.id}', headers=other_auth_headers)
        assert resp.status_code == 403
