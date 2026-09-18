"""
Storage utilities for EssentialPipeline
"""

import os
import shutil
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_upload_folder():
    """Get the upload folder path from config"""
    from flask import current_app
    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    return os.path.abspath(upload_folder)


def ensure_upload_folder():
    """Ensure the upload folder exists"""
    upload_folder = get_upload_folder()
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def save_file(file, subfolder=None):
    """
    Save an uploaded file to the uploads directory
    
    Args:
        file: The file object from Flask request
        subfolder: Optional subfolder within uploads
        
    Returns:
        dict: {'path': absolute_path, 'filename': original_filename, 'saved_filename': saved_filename}
    """
    from essentialpipeline.utils.security import sanitize_filename
    from flask import current_app
    
    upload_folder = get_upload_folder()
    
    if subfolder:
        subfolder_path = os.path.join(upload_folder, subfolder)
        os.makedirs(subfolder_path, exist_ok=True)
        upload_folder = subfolder_path
    
    # Sanitize filename
    filename = sanitize_filename(file.filename)
    if not filename:
        raise ValueError("Invalid filename")
    
    # Generate unique filename to prevent collisions
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = os.urandom(4).hex()
    saved_filename = f"{timestamp}_{unique_id}_{filename}"
    
    # Save file
    filepath = os.path.join(upload_folder, saved_filename)
    file.save(filepath)
    
    logger.info(f"File saved: {file.filename} -> {saved_filename}")
    
    return {
        'path': filepath,
        'filename': file.filename,
        'saved_filename': saved_filename,
        'relative_path': os.path.join(subfolder or '', saved_filename) if subfolder else saved_filename
    }


def get_file_path(relative_path):
    """
    Get the absolute path for a stored file
    
    Args:
        relative_path: The relative path from the uploads directory
        
    Returns:
        str: Absolute file path
    """
    upload_folder = get_upload_folder()
    return os.path.abspath(os.path.join(upload_folder, relative_path))


def delete_file(relative_path):
    """
    Delete a stored file
    
    Args:
        relative_path: The relative path from the uploads directory
        
    Returns:
        bool: True if deleted, False if file didn't exist
    """
    filepath = get_file_path(relative_path)
    if os.path.exists(filepath):
        os.remove(filepath)
        logger.info(f"File deleted: {relative_path}")
        return True
    return False


def get_file_info(relative_path):
    """
    Get information about a stored file
    
    Args:
        relative_path: The relative path from the uploads directory
        
    Returns:
        dict: File information (size, modified_time, etc.)
    """
    filepath = get_file_path(relative_path)
    
    if not os.path.exists(filepath):
        return None
    
    stat = os.stat(filepath)
    
    return {
        'exists': True,
        'path': filepath,
        'size': stat.st_size,
        'modified': datetime.fromtimestamp(stat.st_mtime),
        'created': datetime.fromtimestamp(stat.st_ctime)
    }


def list_files(subfolder=None):
    """
    List all files in the uploads directory
    
    Args:
        subfolder: Optional subfolder to list
        
    Returns:
        list: List of file information dictionaries
    """
    upload_folder = get_upload_folder()
    
    if subfolder:
        folder = os.path.join(upload_folder, subfolder)
    else:
        folder = upload_folder
    
    if not os.path.exists(folder):
        return []
    
    files = []
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        if os.path.isfile(filepath):
            stat = os.stat(filepath)
            files.append({
                'filename': filename,
                'path': filepath,
                'relative_path': os.path.join(subfolder or '', filename) if subfolder else filename,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime)
            })
    
    return files


def cleanup_old_files(max_age_days=30):
    """
    Clean up old files from the uploads directory
    
    Args:
        max_age_days: Maximum age in days for files to keep
        
    Returns:
        int: Number of files deleted
    """
    from datetime import timedelta
    
    upload_folder = get_upload_folder()
    now = datetime.now()
    max_age = timedelta(days=max_age_days)
    
    deleted_count = 0
    
    for root, dirs, files in os.walk(upload_folder):
        for filename in files:
            filepath = os.path.join(root, filename)
            file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
            
            if now - file_modified > max_age:
                try:
                    os.remove(filepath)
                    logger.info(f"Cleaned up old file: {filepath}")
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Error deleting file {filepath}: {e}")
    
    return deleted_count
