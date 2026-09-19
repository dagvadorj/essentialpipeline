"""
Tests for essentialpipeline/utils/project_validation.py - zip-safety and
project.yaml manifest validation, run at upload time.
"""

import io
import zipfile

import pytest
from werkzeug.datastructures import FileStorage

from essentialpipeline.utils.project_validation import (
    validate_project_zip, ProjectValidationError, MAX_ENTRY_COUNT, MAX_UNCOMPRESSED_SIZE
)


def _zip_bytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _validate(raw_bytes: bytes):
    """Runs validate_project_zip and returns (ok, message, stream_position_after)"""
    stream = io.BytesIO(raw_bytes)
    fs = FileStorage(stream=stream, filename='test.zip')
    try:
        validate_project_zip(fs)
        return True, None
    except ProjectValidationError as e:
        return False, str(e)


class TestZipSafety:
    def test_valid_zip_passes(self):
        ok, msg = _validate(_zip_bytes({'main.py': 'print(1)'}))
        assert ok, msg

    def test_not_a_zip_rejected(self):
        ok, msg = _validate(b'not a zip file at all')
        assert not ok
        assert 'not a valid zip' in msg.lower()

    def test_zip_slip_parent_dir_rejected(self):
        ok, msg = _validate(_zip_bytes({'../evil.txt': 'x'}))
        assert not ok
        assert 'unsafe path' in msg.lower()

    def test_zip_slip_nested_parent_dir_rejected(self):
        ok, msg = _validate(_zip_bytes({'a/../../evil.txt': 'x'}))
        assert not ok
        assert 'unsafe path' in msg.lower()

    def test_absolute_unix_path_rejected(self):
        ok, msg = _validate(_zip_bytes({'/etc/passwd': 'x'}))
        assert not ok
        assert 'absolute path' in msg.lower()

    def test_absolute_windows_path_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('C:/Windows/evil.txt', 'x')
        ok, msg = _validate(buf.getvalue())
        assert not ok
        assert 'absolute path' in msg.lower()

    def test_too_many_entries_rejected(self):
        entries = {f'f{i}.txt': 'x' for i in range(MAX_ENTRY_COUNT + 1)}
        ok, msg = _validate(_zip_bytes(entries))
        assert not ok
        assert 'too many entries' in msg.lower()

    def test_zip_bomb_rejected_from_metadata_alone(self):
        """A highly-compressible file whose declared uncompressed size exceeds the cap"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('huge.txt', b'0' * (MAX_UNCOMPRESSED_SIZE + 1024 * 1024))
        compressed_size = len(buf.getvalue())

        ok, msg = _validate(buf.getvalue())
        assert not ok
        assert 'exceed' in msg.lower()
        # the whole point: caught from a ~500MB+ declared size while the
        # actual uploaded payload was tiny - never decompressed to check
        assert compressed_size < 2 * 1024 * 1024

    def test_stream_position_restored_after_validation(self):
        """Caller still needs to read/save the file after validating it"""
        raw = _zip_bytes({'main.py': 'print(1)'})
        stream = io.BytesIO(raw)
        fs = FileStorage(stream=stream, filename='test.zip')
        validate_project_zip(fs)
        assert fs.stream.tell() == 0
        assert fs.stream.read(2) == b'PK'


class TestManifest:
    def test_no_manifest_is_fine(self):
        ok, msg = _validate(_zip_bytes({'main.py': 'x'}))
        assert ok, msg

    def test_valid_manifest_passes(self):
        manifest = (
            "name: my-pipeline\n"
            "tasks:\n"
            "  - name: Extract\n"
            "    type: python\n"
            "    script: extract.py\n"
            '    schedule: "0 * * * *"\n'
            "  - name: Main\n"
            "    type: python\n"
            "    script: main.py\n"
        )
        ok, msg = _validate(_zip_bytes({'main.py': 'x', 'extract.py': 'y', 'project.yaml': manifest}))
        assert ok, msg

    def test_empty_manifest_file_is_fine(self):
        ok, msg = _validate(_zip_bytes({'project.yaml': ''}))
        assert ok, msg

    def test_bad_yaml_syntax_rejected(self):
        ok, msg = _validate(_zip_bytes({'project.yaml': 'tasks: [unterminated'}))
        assert not ok
        assert 'not valid yaml' in msg.lower()

    def test_top_level_list_rejected(self):
        ok, msg = _validate(_zip_bytes({'project.yaml': '- a\n- b\n'}))
        assert not ok
        assert 'mapping' in msg.lower()

    def test_tasks_not_a_list_rejected(self):
        ok, msg = _validate(_zip_bytes({'project.yaml': 'tasks: nope'}))
        assert not ok
        assert "'tasks'" in msg

    def test_task_missing_name_rejected(self):
        manifest = 'tasks:\n  - type: python\n    script: main.py\n'
        ok, msg = _validate(_zip_bytes({'main.py': 'x', 'project.yaml': manifest}))
        assert not ok
        assert 'name' in msg.lower()

    def test_task_unknown_type_rejected(self):
        manifest = 'tasks:\n  - name: t\n    type: rust\n    script: main.py\n'
        ok, msg = _validate(_zip_bytes({'main.py': 'x', 'project.yaml': manifest}))
        assert not ok
        assert 'type' in msg.lower()

    def test_task_script_not_in_zip_rejected(self):
        manifest = 'tasks:\n  - name: t\n    type: python\n    script: missing.py\n'
        ok, msg = _validate(_zip_bytes({'project.yaml': manifest}))
        assert not ok
        assert 'does not exist' in msg.lower()

    def test_task_bad_cron_schedule_rejected(self):
        manifest = 'tasks:\n  - name: t\n    type: python\n    script: main.py\n    schedule: "not a cron"\n'
        ok, msg = _validate(_zip_bytes({'main.py': 'x', 'project.yaml': manifest}))
        assert not ok
        assert 'cron' in msg.lower()

    def test_unknown_extra_keys_tolerated(self):
        manifest = (
            "name: x\n"
            "description: something extra\n"
            "tasks:\n"
            "  - name: t\n"
            "    type: python\n"
            "    script: main.py\n"
            "    extra_field: ignored\n"
        )
        ok, msg = _validate(_zip_bytes({'main.py': 'x', 'project.yaml': manifest}))
        assert ok, msg

    def test_manifest_too_large_rejected(self):
        from essentialpipeline.utils.project_validation import MAX_MANIFEST_SIZE
        huge_yaml = 'name: ' + ('x' * (MAX_MANIFEST_SIZE + 1))
        ok, msg = _validate(_zip_bytes({'project.yaml': huge_yaml}))
        assert not ok
        assert 'too large' in msg.lower()
