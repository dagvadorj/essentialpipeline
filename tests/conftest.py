"""
Shared pytest fixtures for the EssentialPipeline test suite.

Uses a single in-memory SQLite database for the whole test session
(TestingConfig - see essentialpipeline/config/__init__.py), created once
and wiped between tests by _clean_db rather than per-test transactional
rollback: several code paths under test (queue_task_execution's
background thread, execute_task) call db.session.commit() internally,
which would end an outer transaction a rollback-based approach would
need to stay open - a straightforward "delete every row after each
test" is simpler and avoids relying on how those commits interact with
savepoints.
"""

import io
import os
import zipfile

# get_config() (essentialpipeline/config/__init__.py), used internally by
# services/scheduler.py (init_scheduler, execute_task_in_container, ...),
# ignores create_app()'s config_env argument and reads FLASK_ENV from the
# OS environment instead. Without this, those call sites would silently
# resolve to DevelopmentConfig regardless of create_app('testing') below -
# starting a real APScheduler background thread against a *different*,
# separately-created SQLite connection than the one this suite's app uses,
# since SQLALCHEMY_ENGINE_OPTIONS (the StaticPool sharing) is Flask-
# SQLAlchemy-specific and APScheduler's own SQLAlchemyJobStore never sees it.
os.environ['FLASK_ENV'] = 'testing'

import pytest

from essentialpipeline import db as _db
from essentialpipeline.app import create_app


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    """
    The Flask app, created once for the whole test session. db, jwt, and
    admin (essentialpipeline/__init__.py) are module-level singletons
    that Flask-Admin in particular doesn't tolerate being re-initialized
    against a second app in the same process, so this must not be
    function- or module-scoped.
    """
    application = create_app('testing')
    application.config['UPLOAD_FOLDER'] = str(tmp_path_factory.mktemp('uploads'))

    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture(autouse=True)
def _clean_db(app):
    """
    Wipe every table after each test so tests don't see each other's rows.

    First drains services.scheduler's ThreadPoolExecutor (shutdown(wait=True)
    blocks until every submitted background task run has actually
    finished, not just been queued) and replaces it with a fresh one via
    init_scheduler(). That executor is a session-scoped resource shared by
    every test; without draining it, a background task_run from one test
    (queue_task_execution/trigger_dependent_tasks) can still be executing
    when the next test starts - and since table IDs restart after the
    delete below, that stale background call can end up silently
    operating on a same-numbered but unrelated row from the new test. This
    was intermittent and genuinely hard to pin down before being traced
    to this cause - a test that's flaky roughly 1 run in 5 is worse than
    no test at all, so this drain is not optional.

    Also removes the session (clearing its identity map) - without this,
    SQLite can reassign a deleted row's primary key to an unrelated row in
    a later test, and the long-lived session-scoped db.session would still
    have a stale object cached under that id from the earlier test
    (observed as "Identity map already had an identity ... replacing it
    with newly flushed object" warnings - harmless on its own, but exactly
    the shape of bug that returns a stale cached object instead of fresh
    data).
    """
    yield
    from essentialpipeline.services import scheduler as scheduler_module
    if scheduler_module.executor is not None:
        scheduler_module.executor.shutdown(wait=True)
        with app.app_context():
            scheduler_module.init_scheduler(app)

    with app.app_context():
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        _db.session.remove()
        _db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    """
    The live db.session, for tests that need to create rows directly.
    No context push here - the session-scoped `app` fixture already keeps
    one active for the whole run; pushing a second, nested one confuses
    SQLAlchemy's session scoping (a stale identity map surfaced this as a
    real bug while writing these fixtures - see test_auth.py history).
    """
    return _db.session


def _make_user(*, username, email, password='testpassword123', is_admin=False):
    from essentialpipeline.models import User

    user = User(username=username, email=email, is_admin=is_admin)
    user.password = password
    _db.session.add(user)
    _db.session.commit()
    return user.id


@pytest.fixture
def test_user(app):
    """A plain, non-admin user."""
    from essentialpipeline.models import User

    user_id = _make_user(username='alice', email='alice@example.com')
    return User.query.get(user_id)


@pytest.fixture
def other_user(app):
    """A second, distinct non-admin user - for cross-user access-denial tests."""
    from essentialpipeline.models import User

    user_id = _make_user(username='bob', email='bob@example.com')
    return User.query.get(user_id)


@pytest.fixture
def admin_user(app):
    from essentialpipeline.models import User

    user_id = _make_user(username='admin', email='admin@example.com', is_admin=True)
    return User.query.get(user_id)


def _token_headers(user_id):
    from flask_jwt_extended import create_access_token
    return {'Authorization': f'Bearer {create_access_token(identity=str(user_id))}'}


@pytest.fixture
def auth_headers(app, test_user):
    return _token_headers(test_user.id)


@pytest.fixture
def other_auth_headers(app, other_user):
    return _token_headers(other_user.id)


@pytest.fixture
def admin_headers(app, admin_user):
    return _token_headers(admin_user.id)


@pytest.fixture
def make_zip():
    """Factory fixture: make_zip({'main.py': 'print(1)'}) -> raw zip bytes"""
    def _make(entries: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return buf.getvalue()
    return _make


@pytest.fixture
def make_project_version(app):
    """
    Factory fixture: creates a Project + ProjectVersion + ProjectFile
    backed by a real zip saved under UPLOAD_FOLDER, the way a real
    upload would - so extract_project_archive() and the security scanner
    can operate on it exactly as they would in the app.

    make_project_version(owner_id, {'main.py': 'print(1)'}) -> (project, version)
    """
    def _make(owner_id: int, entries: dict, project_name='Test Project'):
        from essentialpipeline.models import Project, ProjectVersion, ProjectFile

        zip_bytes = io.BytesIO()
        with zipfile.ZipFile(zip_bytes, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        zip_bytes.seek(0)

        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'projects')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f'{project_name.replace(" ", "_")}_{os.urandom(4).hex()}.zip'
        saved_path = os.path.join(upload_dir, saved_name)
        with open(saved_path, 'wb') as f:
            f.write(zip_bytes.getvalue())

        project = Project(name=project_name, owner_user_id=owner_id)
        _db.session.add(project)
        _db.session.flush()

        version = ProjectVersion(project_id=project.id, version='1.0.0', changelog='test')
        _db.session.add(version)
        _db.session.flush()
        project.current_version_id = version.id

        project_file = ProjectFile(
            project_version_id=version.id,
            file_path=saved_name,
            file_size=os.path.getsize(saved_path),
            storage_path=os.path.join('projects', saved_name)
        )
        _db.session.add(project_file)
        _db.session.commit()

        return project.id, version.id
    return _make
