"""
Tests for services/security_scan.py (Decision 6: Bandit audit-only,
Safety blocking).

Bandit tests run the real tool (fast, no network, <1s on a couple of
files) - legitimate to run every time. Safety's vulnerability lookup
needs network access, so it's mocked here for the scan-status/blocking
logic (the thing actually worth protecting against regression), with
one real end-to-end check marked @pytest.mark.network.
"""

import json
import subprocess

import pytest

from essentialpipeline.models import Project, SecurityParseResult, SecurityFinding
from essentialpipeline.services import security_scan


class TestBanditReal:
    def test_flags_a_real_finding(self, tmp_path):
        (tmp_path / 'bad.py').write_text(
            'import subprocess\nsubprocess.call("ls " + input(), shell=True)\n'
        )
        findings = security_scan._run_bandit(str(tmp_path))
        assert len(findings) >= 1
        assert all(f['blocking'] is False for f in findings), "Bandit findings must never block (Decision 6: audit-only)"
        assert any(f['finding_type'] == 'code_pattern' for f in findings)

    def test_clean_code_has_no_findings(self, tmp_path):
        (tmp_path / 'clean.py').write_text('print("hello")\n')
        findings = security_scan._run_bandit(str(tmp_path))
        assert findings == []


class TestSafetyMocked:
    def test_no_requirements_file_means_no_findings(self, tmp_path):
        assert security_scan._run_safety(str(tmp_path)) == []

    def test_vulnerable_dependency_produces_blocking_finding(self, monkeypatch, tmp_path):
        (tmp_path / 'requirements.txt').write_text('django==2.0.1\n')

        fake_payload = {
            'vulnerabilities': [{
                'package_name': 'django', 'analyzed_version': '2.0.1',
                'advisory': 'A known vulnerability', 'fixed_versions': ['4.2.15']
            }]
        }

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=64, stdout=json.dumps(fake_payload), stderr='')

        monkeypatch.setattr(security_scan.subprocess, 'run', fake_run)
        findings = security_scan._run_safety(str(tmp_path))

        assert len(findings) == 1
        assert findings[0]['blocking'] is True
        assert findings[0]['severity'] == 'critical'
        assert 'django' in findings[0]['description']

    def test_tool_crash_is_swallowed_not_raised(self, monkeypatch, tmp_path):
        (tmp_path / 'requirements.txt').write_text('somepkg==1.0\n')

        def fake_run(*args, **kwargs):
            raise FileNotFoundError('safety not installed')

        monkeypatch.setattr(security_scan.subprocess, 'run', fake_run)
        assert security_scan._run_safety(str(tmp_path)) == []


class TestScanProjectVersion:
    def test_clean_project_passes(self, db_session, test_user, make_project_version):
        from essentialpipeline.models import ProjectVersion
        _, version_id = make_project_version(test_user.id, {'main.py': 'print(1)\n'})
        version = ProjectVersion.query.get(version_id)

        result = security_scan.scan_project_version(version, self._extracted_dir(version))
        assert result.overall_status == 'passed'

    def test_bandit_only_findings_produce_warning_not_failed(self, monkeypatch, db_session, test_user):
        monkeypatch.setattr(security_scan, '_run_bandit', lambda d: [{
            'severity': 'high', 'finding_type': 'code_pattern', 'description': 'x',
            'file_path': 'a.py', 'line_number': 1, 'code_snippet': None,
            'recommendation': None, 'blocking': False
        }])
        monkeypatch.setattr(security_scan, '_run_safety', lambda d: [])
        self._assert_status(db_session, test_user, expected='warning')

    def test_safety_finding_produces_failed(self, monkeypatch, db_session, test_user):
        monkeypatch.setattr(security_scan, '_run_bandit', lambda d: [])
        monkeypatch.setattr(security_scan, '_run_safety', lambda d: [{
            'severity': 'critical', 'finding_type': 'dependency', 'description': 'x',
            'file_path': 'requirements.txt', 'line_number': None, 'code_snippet': None,
            'recommendation': None, 'blocking': True
        }])
        self._assert_status(db_session, test_user, expected='failed')

    def test_both_bandit_and_safety_findings_still_failed_not_double_counted_wrong(self, monkeypatch, db_session, test_user):
        """A blocking Safety finding alongside a non-blocking Bandit one should still fail overall"""
        monkeypatch.setattr(security_scan, '_run_bandit', lambda d: [{
            'severity': 'low', 'finding_type': 'code_pattern', 'description': 'x',
            'file_path': 'a.py', 'line_number': 1, 'code_snippet': None,
            'recommendation': None, 'blocking': False
        }])
        monkeypatch.setattr(security_scan, '_run_safety', lambda d: [{
            'severity': 'critical', 'finding_type': 'dependency', 'description': 'y',
            'file_path': 'requirements.txt', 'line_number': None, 'code_snippet': None,
            'recommendation': None, 'blocking': True
        }])
        result = self._assert_status(db_session, test_user, expected='failed')
        assert SecurityFinding.query.filter_by(parse_result_id=result.id).count() == 2

    def _assert_status(self, db_session, user, expected):
        from essentialpipeline.models import ProjectVersion

        project = Project(name='Scan status test', owner_user_id=user.id)
        db_session.add(project)
        db_session.flush()
        version = ProjectVersion(project_id=project.id, version='1.0.0')
        db_session.add(version)
        db_session.commit()

        result = security_scan.scan_project_version(version, '/does/not/matter')
        assert result.overall_status == expected
        return result

    def _extracted_dir(self, version):
        import os
        import tempfile
        from essentialpipeline.services.scheduler import extract_project_archive
        d = tempfile.mkdtemp()
        extract_project_archive(version, d)
        return d


class TestScanUploadedVersionBestEffort:
    def test_missing_archive_does_not_raise(self, db_session, test_user):
        from essentialpipeline.models import ProjectVersion

        project = Project(name='No archive', owner_user_id=test_user.id)
        db_session.add(project)
        db_session.flush()
        version = ProjectVersion(project_id=project.id, version='1.0.0')
        db_session.add(version)
        db_session.commit()

        result = security_scan.scan_uploaded_version(version)
        assert result is None
        assert SecurityParseResult.query.filter_by(project_version_id=version.id).count() == 0

    def test_real_upload_gets_scanned(self, test_user, make_project_version):
        from essentialpipeline.models import ProjectVersion
        _, version_id = make_project_version(test_user.id, {
            'main.py': 'import subprocess\nsubprocess.call("ls", shell=True)\n'
        })
        version = ProjectVersion.query.get(version_id)

        result = security_scan.scan_uploaded_version(version)
        assert result is not None
        assert result.overall_status == 'warning'


@pytest.mark.network
class TestSafetyRealNetwork:
    def test_real_vulnerable_dependency_is_found(self, tmp_path):
        (tmp_path / 'requirements.txt').write_text('django==2.0.1\n')
        findings = security_scan._run_safety(str(tmp_path))
        assert len(findings) > 10
        assert all(f['severity'] == 'critical' and f['blocking'] for f in findings)
