"""
Tests for ML model record CRUD (web: user/models.py, API:
api/v1/models.py) - scoped to the model record itself, not versions,
artifacts, or execution (a separate, larger piece of work).
"""

from essentialpipeline.models import MLModel


class TestApiModelCrud:
    def test_create_list_get_update_delete(self, client, auth_headers):
        resp = client.post('/api/v1/models/', json={'name': 'My Model', 'model_type': 'classification'}, headers=auth_headers)
        assert resp.status_code == 201
        model_id = resp.get_json()['id']

        resp = client.get('/api/v1/models/', headers=auth_headers)
        assert resp.status_code == 200
        assert any(m['id'] == model_id for m in resp.get_json()['models'])

        resp = client.get(f'/api/v1/models/{model_id}', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'My Model'

        resp = client.put(f'/api/v1/models/{model_id}', json={'name': 'Renamed', 'is_active': False}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'Renamed'
        assert resp.get_json()['is_active'] is False

        resp = client.delete(f'/api/v1/models/{model_id}', headers=auth_headers)
        assert resp.status_code == 200
        assert MLModel.query.get(model_id) is None

    def test_name_required(self, client, auth_headers):
        resp = client.post('/api/v1/models/', json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_cannot_attach_to_a_project_you_dont_own(self, client, auth_headers, db_session, other_user, make_project_version):
        project_id, _ = make_project_version(other_user.id, {'main.py': 'x'})
        resp = client.post('/api/v1/models/', json={'name': 'Sneaky', 'project_id': project_id}, headers=auth_headers)
        assert resp.status_code == 400

    def test_cross_user_access_denied(self, client, auth_headers, other_auth_headers):
        resp = client.post('/api/v1/models/', json={'name': 'Mine'}, headers=auth_headers)
        model_id = resp.get_json()['id']

        for method, path in [
            ('GET', f'/api/v1/models/{model_id}'),
            ('PUT', f'/api/v1/models/{model_id}'),
            ('DELETE', f'/api/v1/models/{model_id}'),
        ]:
            resp = client.open(path, method=method, json={'name': 'x'}, headers=other_auth_headers)
            assert resp.status_code == 403, f'{method} {path}'

        assert MLModel.query.get(model_id) is not None


class TestWebModelCrud:
    def test_create_via_form_and_view_detail(self, client, auth_headers):
        resp = client.post('/user/models/new', data={'name': 'Web Model', 'model_type': 'regression'},
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        model = MLModel.query.filter_by(name='Web Model').first()
        assert model is not None

        resp = client.get(f'/user/models/{model.id}', headers=auth_headers)
        assert resp.status_code == 200
        assert b'Web Model' in resp.data

    def test_edit_via_form(self, client, auth_headers, db_session, test_user):
        model = MLModel(name='Before', owner_user_id=test_user.id)
        db_session.add(model)
        db_session.commit()

        resp = client.post(f'/user/models/{model.id}/edit', data={'name': 'After'},
                            headers=auth_headers, follow_redirects=True)
        assert resp.status_code == 200
        assert MLModel.query.get(model.id).name == 'After'

    def test_other_user_cannot_view_or_delete(self, client, other_auth_headers, db_session, test_user):
        model = MLModel(name='Private', owner_user_id=test_user.id)
        db_session.add(model)
        db_session.commit()

        resp = client.get(f'/user/models/{model.id}', headers=other_auth_headers, follow_redirects=True)
        assert b'Access denied' in resp.data

        client.post(f'/user/models/{model.id}/delete', headers=other_auth_headers)
        assert MLModel.query.get(model.id) is not None

    def test_list_shows_only_own(self, client, auth_headers, db_session, test_user, other_user):
        db_session.add(MLModel(name='Mine', owner_user_id=test_user.id))
        db_session.add(MLModel(name='Theirs', owner_user_id=other_user.id))
        db_session.commit()

        resp = client.get('/user/models/', headers=auth_headers)
        assert b'Mine' in resp.data
        assert b'Theirs' not in resp.data
