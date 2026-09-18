"""
API v1 Authentication routes for EssentialPipeline
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from werkzeug.security import generate_password_hash, check_password_hash
from essentialpipeline import db
from essentialpipeline.models import User
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['POST'])
def login():
    """Authenticate user and return JWT tokens"""
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Username and password are required'}), 400
    
    username = data['username']
    password = data['password']
    
    # Find user by username or email
    user = User.query.filter(
        (User.username == username) | (User.email == username)
    ).first()
    
    if not user or not user.verify_password(password):
        logger.warning(f"Login failed for username: {username}")
        return jsonify({'error': 'Invalid username or password'}), 401
    
    if not user.is_active:
        logger.warning(f"Login attempted for inactive user: {username}")
        return jsonify({'error': 'Account is inactive'}), 403
    
    # Update last login
    user.last_login = db.func.now()
    db.session.commit()
    
    # Create tokens (identity must be a string per JWT spec / flask-jwt-extended)
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    
    logger.info(f"User {user.id} ({user.username}) logged in")
    
    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'user': user.to_dict(),
        'expires_in': current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 3600)
    })


@bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token using refresh token"""
    current_user = int(get_jwt_identity())

    # Verify user exists and is active
    user = User.query.get(current_user)
    if not user or not user.is_active:
        return jsonify({'error': 'Invalid user'}), 401

    # Create new access token
    access_token = create_access_token(identity=str(user.id))
    
    return jsonify({
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', 3600)
    })


@bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Handle logout (JWT is stateless, so this is mainly for cleanup)"""
    current_user = get_jwt_identity()
    
    logger.info(f"User {current_user} logged out")
    
    return jsonify({'message': 'Logged out successfully'})


@bp.route('/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_fields = ['username', 'email', 'password']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400
    
    # Check if username exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 409
    
    # Check if email exists
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 409
    
    # Create user
    user = User(
        username=data['username'],
        email=data['email'],
        first_name=data.get('first_name'),
        last_name=data.get('last_name'),
        is_active=data.get('is_active', True),
        is_admin=data.get('is_admin', False)
    )
    user.password = data['password']
    
    db.session.add(user)
    db.session.commit()
    
    logger.info(f"New user registered: {user.username} ({user.email})")
    
    return jsonify({
        'message': 'User registered successfully',
        'user': user.to_dict()
    }), 201


@bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user"""
    current_user = int(get_jwt_identity())
    user = User.query.get_or_404(current_user)
    
    return jsonify(user.to_dict())


@bp.route('/users', methods=['GET'])
@jwt_required()
def list_users():
    """List all users (admin only)"""
    current_user = int(get_jwt_identity())
    user = User.query.get(current_user)
    
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    users = User.query.order_by(User.username)
    
    # Apply search filter
    search = request.args.get('search', '')
    if search:
        users = users.filter(
            (User.username.contains(search)) | 
            (User.email.contains(search)) |
            (User.first_name.contains(search)) |
            (User.last_name.contains(search))
        )
    
    paginated_users = users.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'users': [u.to_dict() for u in paginated_users.items],
        'total': paginated_users.total,
        'pages': paginated_users.pages,
        'current_page': paginated_users.page,
        'per_page': paginated_users.per_page
    })


@bp.route('/password/reset', methods=['POST'])
def password_reset_request():
    """Request password reset (placeholder)"""
    data = request.get_json()
    
    if not data or 'email' not in data:
        return jsonify({'error': 'Email is required'}), 400
    
    # In a real implementation, this would send an email with a reset link
    # For now, we'll just log the request
    logger.info(f"Password reset requested for: {data['email']}")
    
    return jsonify({
        'message': 'If an account with that email exists, a reset link has been sent'
    })


@bp.route('/password/change', methods=['POST'])
@jwt_required()
def change_password():
    """Change password for authenticated user"""
    current_user = int(get_jwt_identity())
    data = request.get_json()
    
    if not data or 'current_password' not in data or 'new_password' not in data:
        return jsonify({'error': 'Current password and new password are required'}), 400
    
    user = User.query.get_or_404(current_user)
    
    # Verify current password
    if not user.verify_password(data['current_password']):
        return jsonify({'error': 'Current password is incorrect'}), 401
    
    # Update password
    user.password = data['new_password']
    db.session.commit()
    
    logger.info(f"User {user.id} changed password")
    
    return jsonify({'message': 'Password changed successfully'})
