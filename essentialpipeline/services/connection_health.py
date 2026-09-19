"""
Connection health-check service for EssentialPipeline.

Always confirms the stored encrypted credential decrypts (catches a
corrupted secret). Attempts a live round-trip only for connection types
we actually have a driver for - currently just mysql, since
mysql-connector-python is the only DB driver in requirements.txt and no
object-storage client (Garage/S3) is installed yet (Decision 4).
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def test_database_connection(connection) -> dict:
    """
    Best-effort health check for a DatabaseConnection.

    Returns:
        dict with 'ok' (True/False/None - None means "not verified live")
        and 'message'
    """
    connection_string = connection.decrypt_connection_string()
    if connection_string is None:
        return {'ok': False, 'message': 'Stored credential could not be decrypted'}

    if connection.connection_type != 'mysql':
        return {
            'ok': None,
            'message': f"Credential decrypts OK; no driver installed to live-test "
                       f"'{connection.connection_type}' connections"
        }

    try:
        import mysql.connector

        parsed = urlparse(connection_string)
        cnx = mysql.connector.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip('/') or None,
            connection_timeout=5
        )
        cnx.close()
        return {'ok': True, 'message': 'Connected successfully'}
    except Exception as e:
        logger.warning(f"Database connection test failed for connection {connection.id}: {e}")
        return {'ok': False, 'message': str(e)}


def test_storage_connection(connection) -> dict:
    """
    Best-effort health check for a StorageConnection.

    No object-storage client library is installed yet (Garage integration
    is Decision 4, not implemented - see plan.md), so this only confirms
    the stored credential decrypts.
    """
    credentials = connection.decrypt_credentials()
    if credentials is None:
        return {'ok': False, 'message': 'Stored credential could not be decrypted'}

    return {
        'ok': None,
        'message': 'Credential decrypts OK; no storage client installed to live-test this connection'
    }
