"""
Security utilities for EssentialPipeline
"""

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging

logger = logging.getLogger(__name__)

# Get encryption key from environment or generate a default
_ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')


def _get_fernet():
    """Get or create a Fernet instance for encryption"""
    global _ENCRYPTION_KEY
    
    if _ENCRYPTION_KEY is None:
        # Generate a default key (for development only)
        _ENCRYPTION_KEY = Fernet.generate_key().decode()
        logger.warning("Using generated encryption key. Set ENCRYPTION_KEY in environment for production.")
    
    return Fernet(_ENCRYPTION_KEY.encode())


def encrypt_data(data: str) -> str:
    """
    Encrypt sensitive data using Fernet symmetric encryption
    
    Args:
        data: The plaintext string to encrypt
        
    Returns:
        Base64-encoded encrypted string
    """
    if not data:
        return ""
    
    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(data.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt_data(encrypted_data: str) -> str:
    """
    Decrypt encrypted data
    
    Args:
        encrypted_data: Base64-encoded encrypted string
        
    Returns:
        Decrypted plaintext string
    """
    if not encrypted_data:
        return ""
    
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted_data.encode('utf-8'))
        return decrypted.decode('utf-8')
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise


def hash_password(password: str) -> str:
    """
    Hash a password using PBKDF2
    
    Args:
        password: The plaintext password
        
    Returns:
        Hashed password string
    """
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password)


def verify_password(password: str, hash: str) -> bool:
    """
    Verify a password against a hash
    
    Args:
        password: The plaintext password to verify
        hash: The stored hash
        
    Returns:
        True if password matches, False otherwise
    """
    from werkzeug.security import check_password_hash
    return check_password_hash(hash, password)


def generate_secure_token() -> str:
    """Generate a secure random token"""
    import secrets
    return secrets.token_urlsafe(32)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent directory traversal attacks
    
    Args:
        filename: The original filename
        
    Returns:
        Sanitized filename
    """
    import re
    # Remove any path separators
    sanitized = re.sub(r'[/\\]+', '_', filename)
    # Remove any control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)
    return sanitized.strip(' .')


def validate_connection_string(connection_string: str) -> bool:
    """
    Validate a database connection string
    
    Args:
        connection_string: The connection string to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Basic validation - check for expected format
    # Format: dialect+driver://username:password@host:port/database
    if not connection_string:
        return False
    
    # Check for dangerous patterns
    dangerous_patterns = [';', '--', '/*', '*/', 'xp_', 'exec', 'union']
    for pattern in dangerous_patterns:
        if pattern.lower() in connection_string.lower():
            return False
    
    return True
