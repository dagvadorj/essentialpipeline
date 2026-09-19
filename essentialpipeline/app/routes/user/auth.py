"""
Web UI login/logout for EssentialPipeline.

Bridges the API's JWT auth to a browser session: authenticates the same
way as /api/v1/auth/login, but hands the tokens back as httponly cookies
instead of a JSON body, so the @jwt_required() decorators already used
across the /user/* and /admin/* views work from a plain browser tab.
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    set_access_cookies, set_refresh_cookies, unset_jwt_cookies
)
from essentialpipeline import db
from essentialpipeline.models import User

bp = Blueprint('user_auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user or not user.verify_password(password) or not user.is_active:
            flash('Invalid username or password', 'danger')
            return render_template('user/login.html', username=username), 401

        user.last_login = db.func.now()
        db.session.commit()

        access_token = create_access_token(identity=str(user.id))
        refresh_token = create_refresh_token(identity=str(user.id))

        next_url = request.args.get('next') or url_for('user_dashboard.index')
        response = redirect(next_url)
        set_access_cookies(response, access_token)
        set_refresh_cookies(response, refresh_token)
        return response

    return render_template('user/login.html')


@bp.route('/logout')
def logout():
    response = redirect(url_for('user_auth.login'))
    unset_jwt_cookies(response)
    flash('Logged out', 'info')
    return response
