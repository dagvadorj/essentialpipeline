"""
Tests for services/scheduler.py - task execution wiring, mocking
execute_task_in_container so these don't need Docker (a small separate
marked suite, test_docker_integration.py, covers the real container path).

Covers the regressions actually found and fixed this project:
- queue_task_execution creating a TaskRun that execute_task then
  duplicated (fixed by passing task_run_id through)
- background-thread execution needing an app context pushed for it
  (_execute_task_entrypoint)
- execute_task_in_container's result never having a 'logs' key, so no
  ExecutionLog was ever saved regardless of outcome
"""

import time

import pytest

from essentialpipeline.models import Task, TaskRun, TaskDependency, Project, ExecutionLog
from essentialpipeline.services import scheduler as scheduler_module
from essentialpipeline.services.scheduler import (
    execute_task, queue_task_execution, trigger_dependent_tasks, extract_project_archive
)
from essentialpipeline.utils.docker import DockerExecutionError


def _wait_for(predicate, timeout=5, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def project_and_task(db_session, test_user, make_project_version):
    project_id, version_id = make_project_version(test_user.id, {'main.py': 'print("hi")'})
    task = Task(project_id=project_id, project_version_id=version_id, name='T', task_type='python', is_active=True)
    db_session.add(task)
    db_session.commit()
    return project_id, version_id, task.id


class TestExtractProjectArchive:
    def test_extracts_real_files(self, db_session, test_user, make_project_version, tmp_path):
        from essentialpipeline.models import ProjectVersion

        _, version_id = make_project_version(test_user.id, {'main.py': 'print(1)', 'sub/nested.txt': 'x'})
        version = ProjectVersion.query.get(version_id)

        dest = tmp_path / 'extracted'
        dest.mkdir()
        extract_project_archive(version, str(dest))

        assert (dest / 'main.py').read_text() == 'print(1)'
        assert (dest / 'sub' / 'nested.txt').read_text() == 'x'

    def test_zip_slip_rejected(self, db_session, test_user, make_project_version, tmp_path):
        from essentialpipeline.models import ProjectVersion

        _, version_id = make_project_version(test_user.id, {'../evil.txt': 'pwned'})
        version = ProjectVersion.query.get(version_id)

        dest = tmp_path / 'dest'
        dest.mkdir()
        with pytest.raises(DockerExecutionError, match='unsafe path'):
            extract_project_archive(version, str(dest))

        assert not (tmp_path / 'evil.txt').exists()
        assert list(dest.iterdir()) == []

    def test_missing_archive_raises_clean_error(self, db_session, test_user, tmp_path):
        from essentialpipeline.models import ProjectVersion

        project = Project(name='No File Project', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.flush()
        version = ProjectVersion(project_id=project.id, version='1.0.0')
        db_session.add(version)
        db_session.commit()

        with pytest.raises(DockerExecutionError, match='no uploaded archive'):
            extract_project_archive(version, str(tmp_path))


class TestExecuteTaskWithMockedDocker:
    def test_success_creates_exactly_one_task_run_and_execution_log(self, monkeypatch, app, db_session, project_and_task):
        """Regression test: queue_task_execution used to create a TaskRun that
        execute_task then duplicated with a second, separate row."""
        _, _, task_id = project_and_task

        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda task, task_run: {'exit_code': 0, 'output': 'hello\n', 'error': None, 'duration': 0.1, 'logs': 'hello\n'}
        )

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        runs = TaskRun.query.filter_by(task_id=task_id).all()
        assert len(runs) == 1
        assert runs[0].status == 'success'
        assert runs[0].duration_seconds == 0.1

        logs = ExecutionLog.query.filter_by(task_run_id=runs[0].id).all()
        assert len(logs) == 1
        assert logs[0].stdout == 'hello\n'

    def test_nonzero_exit_code_marks_failed(self, monkeypatch, app, db_session, project_and_task):
        _, _, task_id = project_and_task
        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda task, task_run: {'exit_code': 1, 'output': '', 'error': 'boom', 'duration': 0.1, 'logs': ''}
        )

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        run = TaskRun.query.filter_by(task_id=task_id).first()
        assert run.status == 'failed'
        assert run.error_message == 'boom'

    def test_inactive_task_is_not_run(self, monkeypatch, app, db_session, project_and_task):
        _, _, task_id = project_and_task
        Task.query.get(task_id).is_active = False
        db_session.commit()

        called = []
        monkeypatch.setattr(scheduler_module, 'execute_task_in_container', lambda t, r: called.append(1))

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        assert called == []
        assert TaskRun.query.filter_by(task_id=task_id).count() == 0

    def test_unmet_dependency_skips_without_running(self, monkeypatch, app, db_session, project_and_task):
        project_id, version_id, task_id = project_and_task
        upstream = Task(project_id=project_id, project_version_id=version_id, name='Upstream', task_type='python', is_active=True)
        db_session.add(upstream)
        db_session.commit()
        db_session.add(TaskDependency(task_id=task_id, depends_on_task_id=upstream.id))
        db_session.commit()

        called = []
        monkeypatch.setattr(scheduler_module, 'execute_task_in_container', lambda t, r: called.append(1))

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        assert called == [], "should have skipped before ever calling execute_task_in_container"
        run = TaskRun.query.filter_by(task_id=task_id).first()
        assert run.status == 'skipped'

    def test_met_dependency_allows_run(self, monkeypatch, app, db_session, project_and_task):
        project_id, version_id, task_id = project_and_task
        upstream = Task(project_id=project_id, project_version_id=version_id, name='Upstream', task_type='python', is_active=True)
        db_session.add(upstream)
        db_session.commit()
        db_session.add(TaskDependency(task_id=task_id, depends_on_task_id=upstream.id))
        db_session.add(TaskRun(task_id=upstream.id, status='success'))
        db_session.commit()

        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda t, r: {'exit_code': 0, 'output': '', 'error': None, 'duration': 0.1, 'logs': ''}
        )

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        run = TaskRun.query.filter_by(task_id=task_id).first()
        assert run.status == 'success'

    def test_success_triggers_dependents(self, monkeypatch, app, db_session, project_and_task):
        # Mocks queue_task_execution itself (rather than relying on the real
        # background ThreadPoolExecutor to finish in time) so this test
        # verifies the cascade logic - trigger_dependent_tasks finds the
        # dependent, creates its TaskRun, and hands that exact run off -
        # deterministically, without needing an async wait. The full real
        # background-execution path is covered separately and reliably by
        # TestQueueTaskExecution below.
        project_id, version_id, task_id = project_and_task
        dependent = Task(project_id=project_id, project_version_id=version_id, name='Dependent', task_type='python', is_active=True)
        db_session.add(dependent)
        db_session.commit()
        db_session.add(TaskDependency(task_id=dependent.id, depends_on_task_id=task_id))
        db_session.commit()

        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda t, r: {'exit_code': 0, 'output': '', 'error': None, 'duration': 0.1, 'logs': ''}
        )

        queued = []
        monkeypatch.setattr(
            scheduler_module, 'queue_task_execution',
            lambda task_id, **kwargs: queued.append((task_id, kwargs))
        )

        with app.app_context():
            execute_task(task_id, triggered_by='manual')

        assert len(queued) == 1
        queued_task_id, queued_kwargs = queued[0]
        assert queued_task_id == dependent.id
        assert queued_kwargs['triggered_by'] == 'upstream'

        dependent_run = TaskRun.query.filter_by(task_id=dependent.id).first()
        assert dependent_run is not None
        assert dependent_run.status == 'pending'
        assert queued_kwargs['task_run_id'] == dependent_run.id


class TestQueueTaskExecution:
    """These exercise the real background ThreadPoolExecutor + app-context wiring."""

    def test_trigger_runs_in_background_and_reaches_success(self, monkeypatch, app, db_session, project_and_task):
        _, _, task_id = project_and_task
        monkeypatch.setattr(
            scheduler_module, 'execute_task_in_container',
            lambda t, r: {'exit_code': 0, 'output': 'bg\n', 'error': None, 'duration': 0.1, 'logs': 'bg\n'}
        )

        with app.app_context():
            task_run = queue_task_execution(task_id, triggered_by='manual', user_id=None)
            run_id = task_run.id
            assert task_run.status == 'pending'

        assert _wait_for(lambda: TaskRun.query.get(run_id).status not in ('pending', 'running'))
        with app.app_context():
            final = TaskRun.query.get(run_id)
            assert final.status == 'success'
            assert TaskRun.query.filter_by(task_id=task_id).count() == 1

    def test_returns_same_run_when_task_run_id_given(self, app, db_session, project_and_task):
        _, _, task_id = project_and_task
        with app.app_context():
            existing = TaskRun(task_id=task_id, status='pending', triggered_by='upstream')
            db_session.add(existing)
            db_session.commit()
            existing_id = existing.id

        with app.app_context():
            returned = queue_task_execution(task_id, triggered_by='upstream', task_run_id=existing_id)
            assert returned.id == existing_id
