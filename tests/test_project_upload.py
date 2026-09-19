"""
End-to-end tests for the project upload routes (web: user/projects.py,
API: api/v1/projects.py) - zip/manifest validation wired in, and the
resulting Project/ProjectVersion/ProjectFile rows actually created
correctly.

Regression coverage: new_project()'s file-upload branch used to read
version.id before flushing the just-added ProjectVersion, silently
writing NULL into project_files.project_version_id on every project
created with an initial zip upload.
"""

import io

from essentialpipeline.models import Project, ProjectVersion, ProjectFile


class TestWebUpload:
    def test_new_project_with_valid_zip(self, client, auth_headers, make_zip):
        zip_bytes = make_zip({'main.py': 'print(1)'})
        resp = client.post(
            '/user/projects/new',
            data={'name': 'My Project', 'description': 'x', 'project_file': (io.BytesIO(zip_bytes), 'x.zip')},
            headers=auth_headers, content_type='multipart/form-data', follow_redirects=True
        )
        assert resp.status_code == 200

        project = Project.query.filter_by(name='My Project').first()
        assert project is not None
        assert project.current_version_id is not None

        version = ProjectVersion.query.get(project.current_version_id)
        assert version is not None

        # the actual regression: project_version_id used to be silently NULL here
        project_file = ProjectFile.query.filter_by(project_version_id=version.id).first()
        assert project_file is not None
        assert project_file.project_version_id == version.id
        assert project_file.file_size and project_file.file_size > 0

    def test_new_project_with_malicious_zip_rejected(self, client, auth_headers, make_zip):
        zip_bytes = make_zip({'../evil.txt': 'pwned'})
        resp = client.post(
            '/user/projects/new',
            data={'name': 'Evil Project', 'project_file': (io.BytesIO(zip_bytes), 'evil.zip')},
            headers=auth_headers, content_type='multipart/form-data', follow_redirects=True
        )
        assert resp.status_code == 200
        assert Project.query.filter_by(name='Evil Project').first() is None
        assert b'unsafe path' in resp.data.lower()

    def test_upload_new_version_with_valid_zip(self, client, auth_headers, db_session, test_user, make_project_version, make_zip):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})
        new_zip = make_zip({'main.py': 'print(2)'})

        resp = client.post(
            f'/user/projects/{project_id}/upload',
            data={'changelog': 'v2', 'project_file': (io.BytesIO(new_zip), 'v2.zip')},
            headers=auth_headers, content_type='multipart/form-data', follow_redirects=True
        )
        assert resp.status_code == 200
        versions = ProjectVersion.query.filter_by(project_id=project_id).order_by(ProjectVersion.created_at).all()
        assert len(versions) == 2
        assert versions[-1].version == '1.0.1'

    def test_upload_new_version_with_malicious_zip_rejected(self, client, auth_headers, db_session, test_user, make_project_version, make_zip):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})
        evil_zip = make_zip({'/etc/passwd': 'x'})

        resp = client.post(
            f'/user/projects/{project_id}/upload',
            data={'project_file': (io.BytesIO(evil_zip), 'evil.zip')},
            headers=auth_headers, content_type='multipart/form-data', follow_redirects=True
        )
        assert resp.status_code == 200
        assert ProjectVersion.query.filter_by(project_id=project_id).count() == 1
        assert b'absolute path' in resp.data.lower()

    def test_other_users_project_upload_denied(self, client, other_auth_headers, db_session, test_user, make_project_version, make_zip):
        project_id, _ = make_project_version(test_user.id, {'main.py': 'x'})
        zip_bytes = make_zip({'main.py': 'x'})

        resp = client.post(
            f'/user/projects/{project_id}/upload',
            data={'project_file': (io.BytesIO(zip_bytes), 'x.zip')},
            headers=other_auth_headers, content_type='multipart/form-data', follow_redirects=True
        )
        assert ProjectVersion.query.filter_by(project_id=project_id).count() == 1


class TestApiUpload:
    def test_upload_valid_zip(self, client, auth_headers, db_session, test_user, make_zip):
        resp = client.post('/api/v1/projects/', json={'name': 'API Project'}, headers=auth_headers)
        assert resp.status_code == 201
        project_id = resp.get_json()['id']

        zip_bytes = make_zip({'main.py': 'x'})
        resp = client.post(
            f'/api/v1/projects/{project_id}/upload',
            data={'file': (io.BytesIO(zip_bytes), 'x.zip')},
            headers=auth_headers, content_type='multipart/form-data'
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['version']['version'] == '1.0.1'

        project_file = ProjectFile.query.filter_by(project_version_id=body['version']['id']).first()
        assert project_file is not None

    def test_upload_malicious_zip_rejected_with_400(self, client, auth_headers, db_session, test_user, make_zip):
        resp = client.post('/api/v1/projects/', json={'name': 'API Evil Project'}, headers=auth_headers)
        project_id = resp.get_json()['id']

        evil_zip = make_zip({'../evil.txt': 'x'})
        resp = client.post(
            f'/api/v1/projects/{project_id}/upload',
            data={'file': (io.BytesIO(evil_zip), 'evil.zip')},
            headers=auth_headers, content_type='multipart/form-data'
        )
        assert resp.status_code == 400
        assert 'unsafe path' in resp.get_json()['error'].lower()

    def test_upload_non_zip_rejected(self, client, auth_headers, db_session, test_user):
        resp = client.post('/api/v1/projects/', json={'name': 'Not A Zip Project'}, headers=auth_headers)
        project_id = resp.get_json()['id']

        resp = client.post(
            f'/api/v1/projects/{project_id}/upload',
            data={'file': (io.BytesIO(b'hello'), 'notazip.txt')},
            headers=auth_headers, content_type='multipart/form-data'
        )
        assert resp.status_code == 400
