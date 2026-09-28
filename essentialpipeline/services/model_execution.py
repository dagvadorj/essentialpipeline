"""
ML model versions and execution for EssentialPipeline.

Artifact contract: a model version is a zip bundle containing a
`predict.py` at its root. Running the model executes `python predict.py`
inside a container with the bundle mounted read-only at /app; predict.py
reads its input from /io/input.json and writes its result to
/io/output.json (both JSON). That keeps this framework-agnostic - the
bundle carries whatever weights/code it needs - and means the app server
never loads, unpickles, or otherwise interprets an uploaded model itself.

The container runs with network_mode='none' (an uploaded model is
untrusted code, and shouldn't be able to reach anything or exfiltrate
its input), a read-only artifact mount, a memory cap, and a
MODEL_EXECUTION_TIMEOUT much tighter than a scheduled task's. The
consequence of no network is that a bundle can't pip-install anything at
run time: it must be self-contained or stick to the standard library
(dependency installation for uploaded artifacts isn't built - see
plan.md).

There is deliberately no local (non-Docker) fallback the way tasks have
one: running an untrusted uploaded model directly on the app host isn't
acceptable, so with Docker disabled or unreachable an execution simply
fails with a clear message.
"""

import hashlib
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime

logger = logging.getLogger(__name__)

_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_ERROR_CHARS = 4000


class ModelWorkflowError(ValueError):
    """Raised for an invalid model version upload or execution request"""
    pass


def _next_version_string(model) -> str:
    from essentialpipeline.models import MLModelVersion

    latest = MLModelVersion.query.filter_by(model_id=model.id).order_by(MLModelVersion.id.desc()).first()
    if not latest:
        return '1.0.0'
    try:
        major, minor, patch = map(int, latest.version.split('.'))
    except ValueError:
        return '1.0.0'
    return f'{major}.{minor}.{patch + 1}'


def _require_predict_py(file_storage) -> None:
    stream = file_storage.stream
    position = stream.tell()
    try:
        with zipfile.ZipFile(stream) as zf:
            names = {n.replace('\\', '/') for n in zf.namelist()}
    finally:
        stream.seek(position)
    if 'predict.py' not in names:
        raise ModelWorkflowError('Model bundle must contain predict.py at its root')


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_version(model, file_storage, framework=None, framework_version=None, metadata=None):
    """
    Validate and store an uploaded model bundle as a new MLModelVersion,
    and make it the model's current version.

    Raises:
        ProjectValidationError: not a safe zip (same checks project uploads get)
        ModelWorkflowError: no predict.py at the bundle's root
    """
    from essentialpipeline import db
    from essentialpipeline.models import MLModelVersion
    from essentialpipeline.utils.project_validation import validate_project_zip
    from essentialpipeline.utils.storage import save_file

    validate_project_zip(file_storage)
    _require_predict_py(file_storage)

    saved = save_file(file_storage, subfolder=f'models/{model.id}')

    version = MLModelVersion(
        model_id=model.id,
        version=_next_version_string(model),
        framework=framework,
        framework_version=framework_version,
        metadata_json=metadata,
        artifact_path=saved['relative_path'],
        artifact_size=os.path.getsize(saved['path']),
        artifact_hash=_sha256(saved['path']),
    )
    db.session.add(version)
    db.session.flush()
    model.current_version_id = version.id
    db.session.commit()
    return version


def queue_model_execution(model, version, input_data):
    """
    Create a pending MLModelExecution and run it on the scheduler's
    thread pool. The row exists before this returns so the caller has an
    id to poll immediately.
    """
    from essentialpipeline import db
    from essentialpipeline.models import MLModelExecution
    from essentialpipeline.services import scheduler as scheduler_module
    from flask import current_app

    if version.model_id != model.id:
        raise ModelWorkflowError('Version does not belong to this model')
    if not isinstance(input_data, (dict, list)):
        raise ModelWorkflowError('input_data must be a JSON object or array')
    if len(json.dumps(input_data).encode('utf-8')) > current_app.config['MODEL_INPUT_MAX_BYTES']:
        raise ModelWorkflowError('input_data is too large')

    execution = MLModelExecution(
        model_id=model.id, model_version_id=version.id,
        input_data=input_data, status='pending'
    )
    db.session.add(execution)
    db.session.commit()

    scheduler_module.executor.submit(_execute_model_entrypoint, execution.id)
    return execution


def _execute_model_entrypoint(execution_id: int):
    """Runs on a worker thread, which has no Flask context of its own - see scheduler._execute_task_entrypoint"""
    from essentialpipeline.services import scheduler as scheduler_module

    with scheduler_module._app.app_context():
        execute_model(execution_id)


def execute_model(execution_id: int):
    from essentialpipeline import db
    from essentialpipeline.models import MLModelExecution

    execution = MLModelExecution.query.get(execution_id)
    if not execution:
        logger.error(f"MLModelExecution {execution_id} not found")
        return

    execution.status = 'running'
    execution.start_time = datetime.utcnow()
    db.session.commit()

    try:
        result = _run_in_container(execution.model_version, execution.input_data)
    except Exception as e:
        logger.warning(f"Model execution {execution_id} failed to run: {e}")
        result = {'ok': False, 'error': str(e), 'output_data': None}

    execution.end_time = datetime.utcnow()
    execution.duration_seconds = int((execution.end_time - execution.start_time).total_seconds())
    if result['ok']:
        execution.status = 'success'
        execution.output_data = result['output_data']
    else:
        execution.status = 'failed'
        execution.error_message = (result['error'] or '')[-_MAX_ERROR_CHARS:]
    db.session.commit()


def _run_in_container(version, input_data) -> dict:
    """
    Run one version against one input. Returns {'ok', 'output_data', 'error'}.
    Raises for infrastructure problems (Docker unavailable, bad archive) -
    execute_model records those as a failed execution.
    """
    from flask import current_app
    from essentialpipeline.utils.archive import safe_extract_zip, ArchiveError
    from essentialpipeline.utils.docker import DockerContainer
    from essentialpipeline.utils.storage import get_file_path

    config = current_app.config
    if not config.get('DOCKER_ENABLED', True):
        raise ModelWorkflowError('Docker is disabled; model execution requires it')

    with tempfile.TemporaryDirectory() as tmp:
        app_dir = os.path.join(tmp, 'app')
        io_dir = os.path.join(tmp, 'io')
        os.makedirs(app_dir)
        os.makedirs(io_dir)

        try:
            safe_extract_zip(get_file_path(version.artifact_path), app_dir)
        except ArchiveError as e:
            raise ModelWorkflowError(str(e))

        with open(os.path.join(io_dir, 'input.json'), 'w') as f:
            json.dump(input_data, f)

        container = None
        try:
            container = DockerContainer(
                image='python:3.11-slim',
                working_dir='/app',
                # DockerContainer feeds this straight into cpu_quota against a
                # 100000us period, so 100000 is one full CPU (its "millicores"
                # docstring is wrong - see plan.md).
                cpu_limit=100000,
                memory_limit=512 * 1024 * 1024,
                network_mode='none',
                volumes={
                    app_dir: {'bind': '/app', 'mode': 'ro'},
                    io_dir: {'bind': '/io', 'mode': 'rw'},
                },
                environment={'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': '/app'},
            )
            container.create_container(command=['sleep', 'infinity'])
            result = container.execute(['python', 'predict.py'], timeout=config['MODEL_EXECUTION_TIMEOUT'])
        finally:
            if container is not None:
                container.cleanup()

        if result['exit_code'] != 0:
            return {'ok': False, 'output_data': None,
                    'error': result.get('output') or f"predict.py exited with code {result['exit_code']}"}

        output_path = os.path.join(io_dir, 'output.json')
        if not os.path.isfile(output_path):
            return {'ok': False, 'output_data': None, 'error': 'predict.py did not write /io/output.json'}
        if os.path.getsize(output_path) > _MAX_OUTPUT_BYTES:
            return {'ok': False, 'output_data': None, 'error': '/io/output.json is too large'}
        try:
            with open(output_path) as f:
                return {'ok': True, 'output_data': json.load(f), 'error': None}
        except ValueError as e:
            return {'ok': False, 'output_data': None, 'error': f'/io/output.json is not valid JSON: {e}'}


def delete_model(model) -> None:
    """Delete a model along with its executions, versions, and stored artifacts."""
    from essentialpipeline import db
    from essentialpipeline.models import MLModelExecution, MLModelVersion
    from essentialpipeline.utils.storage import delete_file

    model.current_version_id = None
    db.session.flush()

    MLModelExecution.query.filter_by(model_id=model.id).delete(synchronize_session=False)
    for version in MLModelVersion.query.filter_by(model_id=model.id).all():
        if version.artifact_path:
            delete_file(version.artifact_path)
        db.session.delete(version)
    db.session.flush()

    db.session.delete(model)
    db.session.commit()
