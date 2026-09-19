"""
Upload-time validation for project zip files.

Catches obviously broken or unsafe uploads before they're even stored,
rather than only discovering a corrupt/unsafe archive later at task
execution time. extract_project_archive() (services/scheduler.py)
already guards against zip-slip at extraction time too - this catches
it earlier, at upload time, with a clearer error shown right on the
upload form/response instead of surfacing inside a task run's logs.

Also validates project.yaml, the manifest format README.md sketches,
if the zip has one - see MANIFEST_SCHEMA below. It's optional: a zip
with no project.yaml at all is unchanged from today (tasks are added
by hand via the UI/API afterward) - this only rejects a project.yaml
that exists but is malformed, not the absence of one.

Deliberately metadata-only for the zip-safety checks: it never
decompresses entries (no zipfile.testzip()/extractall()), since an
uploaded zip is untrusted and actually decompressing it here would run
on the app server itself, not inside the sandboxed execution container -
a zip bomb would be a real resource-exhaustion risk on the server, not
just the container. project.yaml is the one exception: it's just read
directly (not a bulk extract), after the entry has already passed the
same size accounting as everything else in the archive.
"""

import os
import zipfile

import yaml

MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024  # 500MB, matches Decision 1's Docker-sandbox assumption of "reasonable project size"
MAX_ENTRY_COUNT = 5000
MAX_MANIFEST_SIZE = 1024 * 1024  # 1MB - project.yaml itself should never be large

MANIFEST_TASK_TYPES = {'python', 'sql', 'bash', 'ml_model'}

# project.yaml schema (all keys optional - an absent manifest is fine too):
#
#   name: <string>            # informational only, not cross-checked against anything
#   tasks:
#     - name: <string>        # required
#       type: python|sql|bash|ml_model   # required
#       script: <string>      # required - path to the entry script, must exist in this zip
#       schedule: <string>    # optional - cron expression
#
# Unrecognized top-level or task keys are ignored (forward-compatible),
# not rejected.


class ProjectValidationError(ValueError):
    """Raised when an uploaded project zip fails validation"""
    pass


def validate_project_zip(file_storage) -> None:
    """
    Validate an uploaded project zip. Raises ProjectValidationError with
    a user-facing message on failure. Leaves the underlying stream
    position unchanged so the caller can still save it afterward.
    """
    stream = file_storage.stream
    start_position = stream.tell()

    try:
        if not zipfile.is_zipfile(stream):
            raise ProjectValidationError("File is not a valid zip archive")

        stream.seek(start_position)
        with zipfile.ZipFile(stream) as zf:
            infos = zf.infolist()

            if len(infos) > MAX_ENTRY_COUNT:
                raise ProjectValidationError(
                    f"Zip archive has too many entries ({len(infos)} > {MAX_ENTRY_COUNT})"
                )

            entry_names = set()
            total_uncompressed = 0
            for info in infos:
                normalized = _normalize_zip_path(info.filename)
                if normalized.startswith('/') or (len(normalized) > 1 and normalized[1] == ':'):
                    raise ProjectValidationError(f"Zip archive contains an absolute path: {info.filename}")
                if '..' in normalized.split('/'):
                    raise ProjectValidationError(f"Zip archive contains an unsafe path: {info.filename}")
                entry_names.add(normalized)

                total_uncompressed += info.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
                    raise ProjectValidationError(
                        f"Zip archive's uncompressed contents exceed the "
                        f"{MAX_UNCOMPRESSED_SIZE // (1024 * 1024)}MB limit"
                    )

            _validate_manifest(zf, entry_names)
    except zipfile.BadZipFile as e:
        raise ProjectValidationError(f"File is not a valid zip archive: {e}")
    finally:
        stream.seek(start_position)


def _normalize_zip_path(path: str) -> str:
    path = path.replace('\\', '/')
    if path.startswith('./'):
        path = path[2:]
    return path


def _validate_manifest(zf: zipfile.ZipFile, entry_names: set) -> None:
    """project.yaml is optional; if present, validate it against MANIFEST_TASK_TYPES's schema"""
    manifest_name = next((n for n in entry_names if n == 'project.yaml'), None)
    if manifest_name is None:
        return

    info = zf.getinfo('project.yaml')
    if info.file_size > MAX_MANIFEST_SIZE:
        raise ProjectValidationError(
            f"project.yaml is too large ({info.file_size} bytes > {MAX_MANIFEST_SIZE} bytes)"
        )

    raw = zf.read('project.yaml')
    try:
        manifest = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ProjectValidationError(f"project.yaml is not valid YAML: {e}")

    if manifest is None:
        return  # empty file - nothing to validate

    if not isinstance(manifest, dict):
        raise ProjectValidationError("project.yaml must be a YAML mapping at the top level")

    if 'name' in manifest and not isinstance(manifest['name'], str):
        raise ProjectValidationError("project.yaml: 'name' must be a string")

    tasks = manifest.get('tasks')
    if tasks is None:
        return
    if not isinstance(tasks, list):
        raise ProjectValidationError("project.yaml: 'tasks' must be a list")

    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ProjectValidationError(f"project.yaml: tasks[{i}] must be a mapping")

        name = task.get('name')
        if not name or not isinstance(name, str):
            raise ProjectValidationError(f"project.yaml: tasks[{i}].name is required and must be a string")

        task_type = task.get('type')
        if task_type not in MANIFEST_TASK_TYPES:
            raise ProjectValidationError(
                f"project.yaml: tasks[{i}].type must be one of {sorted(MANIFEST_TASK_TYPES)}, got {task_type!r}"
            )

        script = task.get('script')
        if not script or not isinstance(script, str):
            raise ProjectValidationError(f"project.yaml: tasks[{i}].script is required and must be a string")
        if _normalize_zip_path(script) not in entry_names:
            raise ProjectValidationError(
                f"project.yaml: tasks[{i}].script '{script}' does not exist in this zip"
            )

        schedule = task.get('schedule')
        if schedule is not None:
            if not isinstance(schedule, str):
                raise ProjectValidationError(f"project.yaml: tasks[{i}].schedule must be a string")
            try:
                from apscheduler.triggers.cron import CronTrigger
                CronTrigger.from_crontab(schedule)
            except ValueError as e:
                raise ProjectValidationError(
                    f"project.yaml: tasks[{i}].schedule '{schedule}' is not a valid cron expression: {e}"
                )
