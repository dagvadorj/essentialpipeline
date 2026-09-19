"""
Tests for app/middleware/__init__.py's RBAC decorators and the 403 error
handler - admin_required and project_access_required both eventually
call abort(403), which used to render Flask's default HTML error page
on API routes instead of JSON (no 403 handler existed, unlike 404/500).
"""

from essentialpipeline.models import Project


class TestAdminRequired:
    def test_admin_can_access(self, client, admin_headers):
        resp = client.get('/api/v1/admin/groups', headers=admin_headers)
        assert resp.status_code == 200

    def test_non_admin_gets_json_403(self, client, auth_headers):
        resp = client.get('/api/v1/admin/groups', headers=auth_headers)
        assert resp.status_code == 403
        assert resp.content_type == 'application/json'
        assert 'error' in resp.get_json()

    def test_unauthenticated_gets_401_not_403(self, client):
        resp = client.get('/api/v1/admin/groups')
        assert resp.status_code == 401


class TestProjectAccessRequired:
    def test_owner_can_access(self, client, auth_headers, db_session, test_user):
        project = Project(name='Mine', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.commit()

        resp = client.get(f'/api/v1/projects/{project.id}', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['id'] == project.id

    def test_non_owner_gets_json_403(self, client, other_auth_headers, db_session, test_user):
        project = Project(name='Mine', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.commit()

        resp = client.get(f'/api/v1/projects/{project.id}', headers=other_auth_headers)
        assert resp.status_code == 403
        assert resp.content_type == 'application/json'
        assert resp.get_json()['error'] == 'Access denied to project'

    def test_nonexistent_project_gets_404(self, client, auth_headers):
        resp = client.get('/api/v1/projects/999999', headers=auth_headers)
        assert resp.status_code == 404

    def test_denied_on_every_project_scoped_route(self, client, other_auth_headers, db_session, test_user):
        """Regression coverage: project_access_required is wired into all 8
        project-scoped routes, not just a couple of them."""
        project = Project(name='Mine', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.commit()
        pid = project.id

        checks = [
            ('GET', f'/api/v1/projects/{pid}'),
            ('PUT', f'/api/v1/projects/{pid}'),
            ('DELETE', f'/api/v1/projects/{pid}'),
            ('GET', f'/api/v1/projects/{pid}/versions'),
            ('GET', f'/api/v1/projects/{pid}/tasks'),
            ('POST', f'/api/v1/projects/{pid}/tasks'),
        ]
        for method, path in checks:
            resp = client.open(path, method=method, headers=other_auth_headers)
            assert resp.status_code == 403, f'{method} {path} should have been denied, got {resp.status_code}'
            assert resp.content_type == 'application/json', f'{method} {path} should return JSON'
