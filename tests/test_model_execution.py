"""
Tests for ML model versions and execution (services/model_execution.py,
api/v1/models.py, user/models.py).

Docker is faked for the fast tests (FakeContainer records exactly how
the container was configured, which is where the security properties -
no network, read-only artifact - live); the @pytest.mark.docker class at
the bottom runs the real sample bundle through a real container.
"""

import io
import json
import os
import time

import pytest

from essentialpipeline.models import MLModel, MLModelVersion, MLModelExecution
from essentialpipeline.services import model_execution
from essentialpipeline.services.model_execution import (
    create_version, _run_in_container, ModelWorkflowError
)
from essentialpipeline.utils.project_validation import ProjectValidationError
from werkzeug.datastructures import FileStorage

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), '..', 'essentialpipeline', 'examples', 'sample_model')


def _wait_for(predicate, timeout=20, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _upload(zip_bytes, name='m.zip'):
    return FileStorage(stream=io.BytesIO(zip_bytes), filename=name)


@pytest.fixture
def model(db_session, test_user):
    m = MLModel(name='Test Model', owner_user_id=test_user.id)
    db_session.add(m)
    db_session.commit()
    return m


@pytest.fixture
def bundle(make_zip):
    return make_zip({'predict.py': 'print(1)\n', 'model.json': '{}'})


class FakeContainer:
    """Stands in for utils.docker.DockerContainer; scenario is set per test"""
    scenario = {}
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.predict_py_present = None
        FakeContainer.last = self

    def create_container(self, command=None):
        pass

    def execute(self, command, timeout=None):
        volumes = {v['bind']: (host, v['mode']) for host, v in self.kwargs['volumes'].items()}
        app_dir, _ = volumes['/app']
        io_dir, _ = volumes['/io']
        self.predict_py_present = os.path.isfile(os.path.join(app_dir, 'predict.py'))
        self.input_json = json.load(open(os.path.join(io_dir, 'input.json')))
        self.command, self.timeout = command, timeout
        s = FakeContainer.scenario
        if 'output_text' in s:
            with open(os.path.join(io_dir, 'output.json'), 'w') as f:
                f.write(s['output_text'])
        return {'exit_code': s.get('exit_code', 0), 'output': s.get('output', '')}

    def cleanup(self):
        pass


@pytest.fixture
def fake_docker(monkeypatch):
    FakeContainer.scenario = {}
    FakeContainer.last = None
    monkeypatch.setattr('essentialpipeline.utils.docker.DockerContainer', FakeContainer)
    return FakeContainer


class TestCreateVersion:
    def test_valid_bundle_becomes_current_version(self, db_session, model, bundle):
        version = create_version(model, _upload(bundle), framework='sklearn', framework_version='1.4',
                                 metadata={'accuracy': 0.9})
        assert version.version == '1.0.0'
        assert model.current_version_id == version.id
        assert version.framework == 'sklearn'
        assert version.metadata_json == {'accuracy': 0.9}
        assert version.artifact_size == len(bundle)

    def test_hash_matches_the_stored_bytes(self, db_session, model, bundle):
        import hashlib
        from essentialpipeline.utils.storage import get_file_path
        version = create_version(model, _upload(bundle))
        assert version.artifact_hash == hashlib.sha256(bundle).hexdigest()
        with open(get_file_path(version.artifact_path), 'rb') as f:
            assert f.read() == bundle

    def test_versions_increment(self, db_session, model, bundle):
        assert create_version(model, _upload(bundle)).version == '1.0.0'
        assert create_version(model, _upload(bundle)).version == '1.0.1'
        second = create_version(model, _upload(bundle))
        assert second.version == '1.0.2'
        assert model.current_version_id == second.id

    def test_bundle_without_predict_py_rejected(self, db_session, model, make_zip):
        with pytest.raises(ModelWorkflowError, match='predict.py'):
            create_version(model, _upload(make_zip({'model.json': '{}'})))
        assert MLModelVersion.query.count() == 0

    def test_predict_py_must_be_at_the_root(self, db_session, model, make_zip):
        with pytest.raises(ModelWorkflowError, match='predict.py'):
            create_version(model, _upload(make_zip({'sub/predict.py': 'x'})))

    def test_unsafe_zip_rejected(self, db_session, model, make_zip):
        with pytest.raises(ProjectValidationError):
            create_version(model, _upload(make_zip({'predict.py': 'x', '../evil.txt': 'x'})))

    def test_not_a_zip_rejected(self, db_session, model):
        with pytest.raises(ProjectValidationError):
            create_version(model, _upload(b'not a zip'))


class TestRunInContainer:
    """The container's configuration is where the isolation properties live"""

    def _version(self, model, bundle):
        return create_version(model, _upload(bundle))

    def test_container_has_no_network_and_readonly_artifact(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{"ok": true}'}
        _run_in_container(self._version(model, bundle), {'x': 1})

        kwargs = fake_docker.last.kwargs
        assert kwargs['network_mode'] == 'none'
        modes = {v['bind']: v['mode'] for v in kwargs['volumes'].values()}
        assert modes == {'/app': 'ro', '/io': 'rw'}
        assert kwargs['memory_limit'] == 512 * 1024 * 1024

    def test_artifact_extracted_and_input_written(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{}'}
        _run_in_container(self._version(model, bundle), {'features': [1, 2]})
        assert fake_docker.last.predict_py_present is True
        assert fake_docker.last.input_json == {'features': [1, 2]}
        assert fake_docker.last.command == ['python', 'predict.py']

    def test_uses_the_model_specific_timeout(self, app, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{}'}
        _run_in_container(self._version(model, bundle), {})
        assert fake_docker.last.timeout == app.config['MODEL_EXECUTION_TIMEOUT']
        assert app.config['MODEL_EXECUTION_TIMEOUT'] < app.config['EXECUTION_TIMEOUT']

    def test_success_returns_parsed_output(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{"prediction": 4.75}'}
        result = _run_in_container(self._version(model, bundle), {})
        assert result == {'ok': True, 'output_data': {'prediction': 4.75}, 'error': None}

    def test_nonzero_exit_reports_container_output(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'exit_code': 1, 'output': 'Traceback: boom'}
        result = _run_in_container(self._version(model, bundle), {})
        assert result['ok'] is False
        assert 'boom' in result['error']

    def test_missing_output_file(self, db_session, model, bundle, fake_docker):
        result = _run_in_container(self._version(model, bundle), {})
        assert result['ok'] is False
        assert 'output.json' in result['error']

    def test_invalid_output_json(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': 'not json'}
        result = _run_in_container(self._version(model, bundle), {})
        assert result['ok'] is False
        assert 'not valid JSON' in result['error']

    def test_oversized_output_rejected(self, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '"' + 'x' * (model_execution._MAX_OUTPUT_BYTES + 1) + '"'}
        result = _run_in_container(self._version(model, bundle), {})
        assert result['ok'] is False
        assert 'too large' in result['error']

    def test_docker_disabled_refuses_rather_than_running_on_the_host(self, app, monkeypatch, db_session, model, bundle):
        version = self._version(model, bundle)
        monkeypatch.setitem(app.config, 'DOCKER_ENABLED', False)
        with pytest.raises(ModelWorkflowError, match='Docker is disabled'):
            _run_in_container(version, {})


class TestApi:
    def _create_model(self, client, headers):
        return client.post('/api/v1/models/', json={'name': 'M'}, headers=headers).get_json()['id']

    def _upload(self, client, headers, model_id, bundle, **form):
        return client.post(f'/api/v1/models/{model_id}/versions',
                           data={'file': (io.BytesIO(bundle), 'm.zip'), **form},
                           headers=headers, content_type='multipart/form-data')

    def test_upload_list_download(self, client, auth_headers, bundle):
        model_id = self._create_model(client, auth_headers)
        resp = self._upload(client, auth_headers, model_id, bundle, framework='sklearn',
                            metadata=json.dumps({'k': 'v'}))
        assert resp.status_code == 201
        version = resp.get_json()
        assert version['version'] == '1.0.0'
        assert version['metadata'] == {'k': 'v'}

        assert client.get(f'/api/v1/models/{model_id}', headers=auth_headers).get_json()['current_version_id'] == version['id']
        listed = client.get(f'/api/v1/models/{model_id}/versions', headers=auth_headers).get_json()['versions']
        assert [v['id'] for v in listed] == [version['id']]

        resp = client.get(f'/api/v1/models/{model_id}/versions/{version["id"]}/download', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.data == bundle

    def test_bad_uploads_rejected(self, client, auth_headers, make_zip):
        model_id = self._create_model(client, auth_headers)
        assert self._upload(client, auth_headers, model_id, make_zip({'a.txt': 'x'})).status_code == 400
        assert self._upload(client, auth_headers, model_id, make_zip({'predict.py': 'x'}),
                            metadata='{not json').status_code == 400
        resp = client.post(f'/api/v1/models/{model_id}/versions',
                           data={'file': (io.BytesIO(b'hi'), 'notes.txt')},
                           headers=auth_headers, content_type='multipart/form-data')
        assert resp.status_code == 400
        resp = client.post(f'/api/v1/models/{model_id}/versions', data={}, headers=auth_headers,
                           content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_cross_user_access_denied_on_every_new_route(self, client, auth_headers, other_auth_headers, bundle):
        model_id = self._create_model(client, auth_headers)
        version_id = self._upload(client, auth_headers, model_id, bundle).get_json()['id']

        checks = [
            ('GET', f'/api/v1/models/{model_id}/versions'),
            ('POST', f'/api/v1/models/{model_id}/versions'),
            ('GET', f'/api/v1/models/{model_id}/versions/{version_id}/download'),
            ('POST', f'/api/v1/models/{model_id}/execute'),
            ('GET', f'/api/v1/models/{model_id}/executions'),
            ('GET', f'/api/v1/models/{model_id}/executions/1'),
        ]
        for method, path in checks:
            resp = client.open(path, method=method, json={'input_data': {}}, headers=other_auth_headers)
            assert resp.status_code == 403, f'{method} {path}'

    def test_execute_runs_in_background_and_stores_output(self, client, auth_headers, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{"prediction": 1}'}
        model_id = self._create_model(client, auth_headers)
        self._upload(client, auth_headers, model_id, bundle)

        resp = client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': {'features': [1]}},
                           headers=auth_headers)
        assert resp.status_code == 202
        execution_id = resp.get_json()['id']

        def done():
            body = client.get(f'/api/v1/models/{model_id}/executions/{execution_id}', headers=auth_headers).get_json()
            return body['status'] in ('success', 'failed')
        assert _wait_for(done)

        body = client.get(f'/api/v1/models/{model_id}/executions/{execution_id}', headers=auth_headers).get_json()
        assert body['status'] == 'success'
        assert body['output_data'] == {'prediction': 1}
        assert body['input_data'] == {'features': [1]}
        assert body['duration_seconds'] is not None

    def test_failed_execution_records_the_error(self, client, auth_headers, bundle, fake_docker):
        fake_docker.scenario = {'exit_code': 2, 'output': 'ValueError: bad features'}
        model_id = self._create_model(client, auth_headers)
        self._upload(client, auth_headers, model_id, bundle)
        execution_id = client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': {}},
                                   headers=auth_headers).get_json()['id']

        assert _wait_for(lambda: client.get(f'/api/v1/models/{model_id}/executions/{execution_id}',
                                            headers=auth_headers).get_json()['status'] == 'failed')
        body = client.get(f'/api/v1/models/{model_id}/executions/{execution_id}', headers=auth_headers).get_json()
        assert 'bad features' in body['error_message']
        assert body['output_data'] is None

    def test_execute_validation(self, client, auth_headers, bundle):
        model_id = self._create_model(client, auth_headers)

        resp = client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': {}}, headers=auth_headers)
        assert resp.status_code == 400  # no version yet

        self._upload(client, auth_headers, model_id, bundle)
        assert client.post(f'/api/v1/models/{model_id}/execute', json={}, headers=auth_headers).status_code == 400
        assert client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': 'a string'},
                           headers=auth_headers).status_code == 400

        big = {'blob': 'x' * (1024 * 1024 + 1)}
        assert client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': big},
                           headers=auth_headers).status_code == 400

        client.put(f'/api/v1/models/{model_id}', json={'is_active': False}, headers=auth_headers)
        assert client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': {}},
                           headers=auth_headers).status_code == 400

    def test_cannot_run_another_models_version(self, client, auth_headers, bundle):
        a = self._create_model(client, auth_headers)
        b = self._create_model(client, auth_headers)
        version_of_a = self._upload(client, auth_headers, a, bundle).get_json()['id']
        self._upload(client, auth_headers, b, bundle)

        resp = client.post(f'/api/v1/models/{b}/execute',
                           json={'input_data': {}, 'version_id': version_of_a}, headers=auth_headers)
        assert resp.status_code == 400

    def test_delete_cascades_versions_executions_and_artifacts(self, client, auth_headers, bundle, fake_docker):
        from essentialpipeline.utils.storage import get_file_path
        fake_docker.scenario = {'output_text': '{}'}
        model_id = self._create_model(client, auth_headers)
        version = self._upload(client, auth_headers, model_id, bundle).get_json()
        artifact = get_file_path(version['artifact_path'])
        assert os.path.isfile(artifact)

        execution_id = client.post(f'/api/v1/models/{model_id}/execute', json={'input_data': {}},
                                   headers=auth_headers).get_json()['id']
        assert _wait_for(lambda: MLModelExecution.query.get(execution_id).status != 'pending'
                         and MLModelExecution.query.get(execution_id).status != 'running')

        assert client.delete(f'/api/v1/models/{model_id}', headers=auth_headers).status_code == 200
        assert MLModel.query.get(model_id) is None
        assert MLModelVersion.query.filter_by(model_id=model_id).count() == 0
        assert MLModelExecution.query.filter_by(model_id=model_id).count() == 0
        assert not os.path.exists(artifact)


class TestWeb:
    def test_example_bundle_is_a_valid_upload(self, client, auth_headers, db_session, model):
        resp = client.get('/user/models/example', headers=auth_headers)
        assert resp.status_code == 200
        version = create_version(model, _upload(resp.data))
        assert version.version == '1.0.0'

    def test_upload_run_and_view_result(self, client, auth_headers, db_session, model, bundle, fake_docker):
        fake_docker.scenario = {'output_text': '{"prediction": 42}'}

        resp = client.post(f'/user/models/{model.id}/versions',
                           data={'bundle': (io.BytesIO(bundle), 'm.zip'), 'framework': 'custom'},
                           headers=auth_headers, content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        assert MLModelVersion.query.filter_by(model_id=model.id).count() == 1

        resp = client.post(f'/user/models/{model.id}/execute', data={'input_data': '{"features": [1]}'},
                           headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert _wait_for(lambda: MLModelExecution.query.filter_by(model_id=model.id, status='success').count() == 1)

        page = client.get(f'/user/models/{model.id}', headers=auth_headers)
        assert b'prediction' in page.data and b'42' in page.data

    def test_invalid_json_input_rejected(self, client, auth_headers, db_session, model, bundle):
        create_version(model, _upload(bundle))
        resp = client.post(f'/user/models/{model.id}/execute', data={'input_data': '{nope'},
                           headers=auth_headers, follow_redirects=True)
        assert b'valid JSON' in resp.data
        assert MLModelExecution.query.count() == 0

    def test_bad_bundle_flashes_error_and_creates_nothing(self, client, auth_headers, db_session, model, make_zip):
        resp = client.post(f'/user/models/{model.id}/versions',
                           data={'bundle': (io.BytesIO(make_zip({'a.txt': 'x'})), 'm.zip')},
                           headers=auth_headers, content_type='multipart/form-data', follow_redirects=True)
        assert b'predict.py' in resp.data
        assert MLModelVersion.query.count() == 0

    def test_other_user_cannot_upload_run_or_download(self, client, other_auth_headers, db_session, model, bundle):
        version = create_version(model, _upload(bundle))

        client.post(f'/user/models/{model.id}/versions', data={'bundle': (io.BytesIO(bundle), 'm.zip')},
                    headers=other_auth_headers, content_type='multipart/form-data')
        client.post(f'/user/models/{model.id}/execute', data={'input_data': '{}'}, headers=other_auth_headers)
        resp = client.get(f'/user/models/{model.id}/versions/{version.id}/download', headers=other_auth_headers,
                          follow_redirects=True)

        assert MLModelVersion.query.filter_by(model_id=model.id).count() == 1
        assert MLModelExecution.query.count() == 0
        assert b'Access denied' in resp.data


def _sample_bundle():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name in sorted(os.listdir(SAMPLE_DIR)):
            zf.write(os.path.join(SAMPLE_DIR, name), arcname=name)
    return buf.getvalue()


def _docker_available():
    try:
        from essentialpipeline.utils.docker import check_docker_availability
        return check_docker_availability()
    except Exception:
        return False


@pytest.mark.docker
@pytest.mark.skipif(not _docker_available(), reason='no reachable Docker daemon')
class TestRealContainer:
    def _run(self, model, zip_bytes, input_data):
        version = create_version(model, _upload(zip_bytes))
        return _run_in_container(version, input_data)

    def test_sample_model_predicts(self, db_session, model):
        result = self._run(model, _sample_bundle(), {'features': [1, 2, 3]})
        assert result['ok'], result['error']
        assert result['output_data'] == {'prediction': 4.75}

    def test_wrong_input_reports_failure(self, db_session, model):
        result = self._run(model, _sample_bundle(), {'features': [1]})
        assert result['ok'] is False
        assert 'expected 3 features' in result['error']

    def test_network_is_unreachable(self, db_session, model, make_zip):
        code = (
            "import json, socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
            "    reached = True\n"
            "except OSError:\n"
            "    reached = False\n"
            "json.dump({'reached': reached}, open('/io/output.json', 'w'))\n"
        )
        result = self._run(model, make_zip({'predict.py': code}), {})
        assert result['ok'], result['error']
        assert result['output_data'] == {'reached': False}

    def test_artifact_is_read_only(self, db_session, model, make_zip):
        code = (
            "import json\n"
            "try:\n"
            "    open('/app/planted.txt', 'w').write('x')\n"
            "    wrote = True\n"
            "except OSError:\n"
            "    wrote = False\n"
            "json.dump({'wrote': wrote}, open('/io/output.json', 'w'))\n"
        )
        result = self._run(model, make_zip({'predict.py': code}), {})
        assert result['ok'], result['error']
        assert result['output_data'] == {'wrote': False}
