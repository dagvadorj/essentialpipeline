"""
Real Docker execution tests - skipped automatically if no daemon is
reachable. Everything else in the suite mocks execute_task_in_container;
this file is the one place that exercises the actual container lifecycle
(utils/docker.py) end to end, which is exactly where four real bugs were
found and fixed this project: docker-py/requests incompatibility, no
image-pull step, no keep-alive process for exec_run to run against (a
guaranteed exit 137), and an exec_run(timeout=...) kwarg that doesn't
exist in docker-py at all (a guaranteed TypeError). None of those could
have been caught by the mocked tests elsewhere in this suite.
"""

import time

import pytest

from essentialpipeline.models import Task, TaskRun, ExecutionLog
from essentialpipeline.utils.docker import check_docker_availability


def _docker_available():
    try:
        return check_docker_availability()
    except Exception:
        return False


pytestmark = pytest.mark.docker
requires_docker = pytest.mark.skipif(not _docker_available(), reason='no reachable Docker daemon')


def _wait_for(predicate, timeout=90, interval=1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@requires_docker
class TestRealContainerExecution:
    def test_python_task_runs_and_captures_stdout(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {
            'main.py': 'print("hello from the real container")\n'
        })
        task = Task(project_id=project_id, project_version_id=version_id, name='Real run', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        resp = client.post(f'/user/tasks/{task_id}/trigger', headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200

        assert _wait_for(lambda: TaskRun.query.filter_by(task_id=task_id).first() is not None
                          and TaskRun.query.filter_by(task_id=task_id).first().status not in ('pending', 'running'))

        run = TaskRun.query.filter_by(task_id=task_id).first()
        assert run.status == 'success', f'error_message={run.error_message}'

        log = ExecutionLog.query.filter_by(task_run_id=run.id).first()
        assert log is not None
        assert 'hello from the real container' in log.stdout

    def test_nonzero_exit_marks_task_failed(self, client, auth_headers, db_session, test_user, make_project_version):
        project_id, version_id = make_project_version(test_user.id, {
            'main.py': 'import sys\nsys.exit(7)\n'
        })
        task = Task(project_id=project_id, project_version_id=version_id, name='Fails on purpose', task_type='python', is_active=True)
        db_session.add(task)
        db_session.commit()
        task_id = task.id

        client.post(f'/user/tasks/{task_id}/trigger', headers=auth_headers)

        assert _wait_for(lambda: TaskRun.query.filter_by(task_id=task_id).first() is not None
                          and TaskRun.query.filter_by(task_id=task_id).first().status not in ('pending', 'running'))
        run = TaskRun.query.filter_by(task_id=task_id).first()
        assert run.status == 'failed'
