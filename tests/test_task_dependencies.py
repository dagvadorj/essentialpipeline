"""
Tests for services/task_dependencies.py (cycle detection, Decision 5) and
its wiring into Flask-Admin's TaskDependencyModelView - the only place a
TaskDependency edge can currently be created.
"""

import pytest

from essentialpipeline.models import Task, TaskDependency, Project
from essentialpipeline.services.task_dependencies import creates_cycle, different_projects


@pytest.fixture
def three_tasks(db_session, test_user):
    """A->B->C dependency chain within one project (A depends on B depends on C)"""
    project = Project(name='Chain Project', owner_user_id=test_user.id)
    db_session.add(project)
    db_session.flush()

    a = Task(project_id=project.id, name='A', task_type='python', is_active=True)
    b = Task(project_id=project.id, name='B', task_type='python', is_active=True)
    c = Task(project_id=project.id, name='C', task_type='python', is_active=True)
    db_session.add_all([a, b, c])
    db_session.commit()

    db_session.add(TaskDependency(task_id=a.id, depends_on_task_id=b.id))
    db_session.add(TaskDependency(task_id=b.id, depends_on_task_id=c.id))
    db_session.commit()

    return project, a, b, c


class TestCreatesCycle:
    def test_no_cycle_for_a_fresh_edge(self, db_session, test_user):
        project = Project(name='P', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.flush()
        x = Task(project_id=project.id, name='X', task_type='python')
        y = Task(project_id=project.id, name='Y', task_type='python')
        db_session.add_all([x, y])
        db_session.commit()

        assert creates_cycle(x.id, y.id) is False

    def test_self_dependency_is_a_cycle(self, three_tasks):
        _, a, _, _ = three_tasks
        assert creates_cycle(a.id, a.id) is True

    def test_closing_the_loop_is_a_cycle(self, three_tasks):
        """A->B->C already exists; C->A would close the loop"""
        _, a, _, c = three_tasks
        assert creates_cycle(c.id, a.id) is True

    def test_extending_the_chain_is_not_a_cycle(self, three_tasks, db_session):
        """A->B->C already exists; a new task D->A does not close any loop"""
        project, a, _, _ = three_tasks
        d = Task(project_id=project.id, name='D', task_type='python')
        db_session.add(d)
        db_session.commit()

        assert creates_cycle(d.id, a.id) is False


class TestDifferentProjects:
    def test_same_project_returns_false(self, three_tasks):
        _, a, b, _ = three_tasks
        assert different_projects(a.id, b.id) is False

    def test_different_projects_returns_true(self, db_session, test_user):
        p1 = Project(name='P1', owner_user_id=test_user.id)
        p2 = Project(name='P2', owner_user_id=test_user.id)
        db_session.add_all([p1, p2])
        db_session.flush()
        t1 = Task(project_id=p1.id, name='T1', task_type='python')
        t2 = Task(project_id=p2.id, name='T2', task_type='python')
        db_session.add_all([t1, t2])
        db_session.commit()

        assert different_projects(t1.id, t2.id) is True


class TestFlaskAdminIntegration:
    """
    Regression coverage for the SQLAlchemy autoflush bug this cycle-check
    wiring originally hit: querying inside on_model_change flushed the
    not-yet-ready pending TaskDependency row and crashed every attempt.
    """

    def test_cyclic_edge_rejected_via_admin_form(self, client, admin_headers, three_tasks):
        _, a, _, c = three_tasks
        resp = client.post(
            '/admin/taskdependency/new/',
            data={'task_id': str(c.id), 'depends_on_task_id': str(a.id)},
            headers=admin_headers, follow_redirects=True
        )
        assert resp.status_code == 200
        assert TaskDependency.query.filter_by(task_id=c.id, depends_on_task_id=a.id).first() is None

    def test_cross_project_edge_rejected_via_admin_form(self, client, admin_headers, three_tasks, db_session, test_user):
        _, a, _, _ = three_tasks
        other_project = Project(name='Other', owner_user_id=test_user.id)
        db_session.add(other_project)
        db_session.flush()
        d = Task(project_id=other_project.id, name='D', task_type='python')
        db_session.add(d)
        db_session.commit()

        resp = client.post(
            '/admin/taskdependency/new/',
            data={'task_id': str(a.id), 'depends_on_task_id': str(d.id)},
            headers=admin_headers, follow_redirects=True
        )
        assert resp.status_code == 200
        assert TaskDependency.query.filter_by(task_id=a.id, depends_on_task_id=d.id).first() is None

    def test_legitimate_edge_created_via_admin_form(self, client, admin_headers, three_tasks, db_session):
        project, a, _, _ = three_tasks
        e = Task(project_id=project.id, name='E', task_type='python')
        db_session.add(e)
        db_session.commit()

        resp = client.post(
            '/admin/taskdependency/new/',
            data={'task_id': str(e.id), 'depends_on_task_id': str(a.id)},
            headers=admin_headers, follow_redirects=True
        )
        assert resp.status_code == 200
        assert TaskDependency.query.filter_by(task_id=e.id, depends_on_task_id=a.id).first() is not None
