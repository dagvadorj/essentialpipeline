"""
End-to-end tests for the task routes (web: user/tasks.py, API:
api/v1/tasks.py) - creation, listing, detail, and triggering, with
execute_task_in_container mocked so these don't need Docker.
"""

from essentialpipeline.models import Task, TaskRun
from essentialpipeline.services import scheduler as scheduler_module


def _mock_success(monkeypatch):
    monkeypatch.setattr(
        scheduler_module, 'execute_task_in_container',
        lambda t, r: {'exit_code': 0, 'output': 'ok\n', 'error': None, 'duration': 0.1, 'logs': 'ok\n'}
    )


class TestWebTaskRoutes:
    def test_create_task_via_web_form(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post('/user/tasks/new', data={
            'project_id': str(project_id), 'name': 'My Task', 'task_type': 'python', 'script_path': 'main.py'
        }, headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200

        task = Task.query.filter_by(project_id=project_id, name='My Task').first()
        assert task is not None
        assert task.task_type == 'python'
        assert task.is_active is True

    def test_cannot_create_task_on_other_users_project(self, client, other_auth_headers, db_session, test_user, make_project_version):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})

        client.post('/user/tasks/new', data={
            'project_id': str(project_id), 'name': 'Sneaky Task', 'task_type': 'python'
        }, headers=other_auth_headers, follow_redirects=True)

        assert Task.query.filter_by(project_id=project_id, name='Sneaky Task').first() is None

    def test_list_tasks_shows_only_own(self, client, auth_headers, other_auth_headers, db_session, test_user, other_user, make_project_version):
        p1, v1 = make_project_version(test_user.id, {'main.py': 'x'}, project_name='Mine')
        p2, v2 = make_project_version(other_user.id, {'main.py': 'x'}, project_name='Theirs')
        db_session.add(Task(project_id=p1, project_version_id=v1, name='MyTask', task_type='python'))
        db_session.add(Task(project_id=p2, project_version_id=v2, name='TheirTask', task_type='python'))
        db_session.commit()

        resp = client.get('/user/tasks/', headers=auth_headers)
        assert resp.status_code == 200
        assert b'MyTask' in resp.data
        assert b'TheirTask' not in resp.data

    def test_trigger_task_success(self, client, auth_headers, monkeypatch, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        _mock_success(monkeypatch)
        resp = client.post(f'/user/tasks/{task_id}/trigger', headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert b'queued' in resp.data.lower()
        assert TaskRun.query.filter_by(task_id=task_id).count() == 1

    def test_trigger_inactive_task_rejected(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=False)
        db_session.add(task)
        db_session.commit()

        resp = client.post(f'/user/tasks/{task.id}/trigger', headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert TaskRun.query.filter_by(task_id=task.id).count() == 0

    def test_cannot_trigger_other_users_task(self, client, other_auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()

        client.post(f'/user/tasks/{task.id}/trigger', headers=other_auth_headers, follow_redirects=True)
        assert TaskRun.query.filter_by(task_id=task.id).count() == 0


class TestApiTaskRoutes:
    def test_create_and_get_task(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})

        resp = client.post(f'/api/v1/projects/{project_id}/tasks',
                            json={'name': 'API Task', 'task_type': 'python', 'script_path': 'main.py'},
                            headers=auth_headers)
        assert resp.status_code == 201
        task_id = resp.get_json()['id']

        resp = client.get(f'/api/v1/tasks/{task_id}', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'API Task'

    def test_trigger_and_list_runs(self, client, auth_headers, monkeypatch, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        _mock_success(monkeypatch)
        resp = client.post(f'/api/v1/tasks/{task_id}/trigger', headers=auth_headers)
        assert resp.status_code == 202
        run_id = resp.get_json()['id']

        resp = client.get(f'/api/v1/tasks/{task_id}/runs', headers=auth_headers)
        assert resp.status_code == 200
        runs = resp.get_json()['runs']
        assert any(r['id'] == run_id for r in runs)

    def test_cross_user_access_denied_on_every_task_route(self, client, other_auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        checks = [
            ('GET', f'/api/v1/tasks/{task_id}'),
            ('POST', f'/api/v1/tasks/{task_id}/trigger'),
            ('GET', f'/api/v1/tasks/{task_id}/runs'),
        ]
        for method, path in checks:
            resp = client.open(path, method=method, headers=other_auth_headers)
            assert resp.status_code == 403, f'{method} {path}'

        assert TaskRun.query.filter_by(task_id=task_id).count() == 0

    def test_inactive_task_trigger_returns_400(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {'main.py': 'x'})
        task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=False)
        db_session.add(task)
        db_session.commit()

        resp = client.post(f'/api/v1/tasks/{task.id}/trigger', headers=auth_headers)
        assert resp.status_code == 400
