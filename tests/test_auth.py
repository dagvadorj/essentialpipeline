"""
Tests for login/logout and the JWT cookie session bridge (Decision 3) -
app/routes/user/auth.py and the token-location/redirect wiring in
app/__init__.py.
"""


class TestLogin:
    def test_valid_login_sets_cookies_and_redirects(self, client, test_user):
        resp = client.post('/login', data={'username': 'alice', 'password': 'testpassword123'})
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/user/dashboard'
        set_cookie_headers = resp.headers.getlist('Set-Cookie')
        assert any('access_token_cookie' in h for h in set_cookie_headers)
        assert any('refresh_token_cookie' in h for h in set_cookie_headers)

    def test_login_with_email_also_works(self, client, test_user):
        resp = client.post('/login', data={'username': 'alice@example.com', 'password': 'testpassword123'})
        assert resp.status_code == 302

    def test_wrong_password_rejected(self, client, test_user):
        resp = client.post('/login', data={'username': 'alice', 'password': 'wrong-password'})
        assert resp.status_code == 401
        assert b'Invalid username or password' in resp.data

    def test_unknown_user_rejected(self, client):
        resp = client.post('/login', data={'username': 'nobody', 'password': 'x'})
        assert resp.status_code == 401

    def test_inactive_user_rejected(self, app, client, test_user, db_session):
        test_user.is_active = False
        db_session.commit()

        resp = client.post('/login', data={'username': 'alice', 'password': 'testpassword123'})
        assert resp.status_code == 401

    def test_next_param_respected_on_redirect(self, client, test_user):
        resp = client.post('/login?next=/user/projects/', data={'username': 'alice', 'password': 'testpassword123'})
        assert resp.status_code == 302
        assert resp.headers['Location'] == '/user/projects/'


class TestSessionBridge:
    def test_browser_request_without_token_redirects_to_login(self, client):
        resp = client.get('/user/projects/')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_api_request_without_token_gets_json_401(self, client):
        resp = client.get('/api/v1/projects/')
        assert resp.status_code == 401
        assert resp.content_type == 'application/json'

    def test_cookie_from_login_authenticates_subsequent_browser_request(self, client, test_user):
        login_resp = client.post('/login', data={'username': 'alice', 'password': 'testpassword123'})
        assert login_resp.status_code == 302

        resp = client.get('/user/projects/')
        assert resp.status_code == 200

    def test_bearer_token_authenticates_api_request(self, client, auth_headers):
        resp = client.get('/api/v1/projects/', headers=auth_headers)
        assert resp.status_code == 200


class TestLogout:
    def test_logout_clears_session_and_redirects(self, client, test_user):
        client.post('/login', data={'username': 'alice', 'password': 'testpassword123'})
        assert client.get('/user/projects/').status_code == 200

        logout_resp = client.get('/logout')
        assert logout_resp.status_code == 302

        resp = client.get('/user/projects/')
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']
