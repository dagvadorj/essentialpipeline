"""
Safe zip extraction, shared by project task execution
(services/scheduler.py) and ML model execution
(services/model_execution.py).

Guards against zip-slip (entries with `../` or absolute paths that would
write outside the destination). Extraction runs on the host, before any
container's isolation exists, so an unsafe entry has to be rejected
here rather than relied on to be harmless once inside a container.
"""

import os
import zipfile


class ArchiveError(ValueError):
    """Raised when an archive is missing, corrupt, or contains an unsafe path"""
    pass


def safe_extract_zip(zip_path: str, dest_dir: str) -> None:
    if not os.path.isfile(zip_path):
        raise ArchiveError(f"Archive not found on disk: {zip_path}")

    dest_dir_real = os.path.realpath(dest_dir)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                member_path = os.path.realpath(os.path.join(dest_dir, member.filename))
                if member_path != dest_dir_real and not member_path.startswith(dest_dir_real + os.sep):
                    raise ArchiveError(f"Refusing to extract unsafe path '{member.filename}' from archive")
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as e:
        raise ArchiveError(f"Archive is not a valid zip file: {e}")
