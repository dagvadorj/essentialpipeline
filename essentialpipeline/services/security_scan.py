"""
Security scanning for EssentialPipeline (Decision 6).

Runs right after a project version is uploaded, creating a
SecurityParseResult + SecurityFinding rows so the Governance Gate's
security-scan check (services/governance_gate.py) has real data to
evaluate instead of nothing.

Only two of Decision 6's four scanning layers are wired here, matching
what's actually decided and available:
- Bandit (source/AST): audit-only. Isolation already covers what a
  malicious code pattern could do at runtime, so findings are recorded
  but never block (never set overall_status to 'failed').
- Safety (dependency vulnerabilities, against requirements.txt if
  present): blocks. A running project is granted real DB/storage
  credentials, so a known-vulnerable package is a live risk independent
  of isolation - any finding sets overall_status='failed'.

Secret detection and container image scanning (the other two Decision 6
layers) still have no library chosen (see plan.md) and aren't run here.

Best-effort throughout: if a scanner tool itself fails to run (not
found, crashes, Safety's vulnerability lookup unreachable), that tool's
findings are skipped with a logged warning rather than blocking the
upload that triggered the scan - only genuine findings from a tool that
ran successfully affect the result.
"""

import json
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_BANDIT_SEVERITY_MAP = {'LOW': 'low', 'MEDIUM': 'medium', 'HIGH': 'high'}
_SCAN_TIMEOUT_SECONDS = 60


def scan_uploaded_version(project_version):
    """
    Extract project_version's archive into a temp dir and scan it.

    Fully best-effort: catches anything (extraction failure, a scanner
    tool erroring, a DB issue while saving results) and just logs a
    warning, returning None, rather than raising - callers use this
    right after an upload has already succeeded and been committed, and
    a scan failure must never turn that into a broken response.
    """
    import tempfile
    from essentialpipeline.services.scheduler import extract_project_archive

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            extract_project_archive(project_version, temp_dir)
            return scan_project_version(project_version, temp_dir)
    except Exception as e:
        logger.warning(f"Security scan skipped for version {project_version.id}: {e}")
        return None


def scan_project_version(project_version, source_dir: str):
    """
    Run Bandit and Safety against an already-extracted project version
    and persist a SecurityParseResult + SecurityFinding rows.

    Args:
        project_version: the ProjectVersion being scanned
        source_dir: local directory the version's zip has already been
            extracted into

    Returns:
        the created SecurityParseResult
    """
    from essentialpipeline import db
    from essentialpipeline.models import SecurityParseResult, SecurityFinding

    findings = _run_bandit(source_dir) + _run_safety(source_dir)

    has_blocking = any(f['blocking'] for f in findings)
    overall_status = 'failed' if has_blocking else ('warning' if findings else 'passed')

    parse_result = SecurityParseResult(
        project_version_id=project_version.id,
        parser_version='bandit==1.7.7,safety==2.3.5',
        overall_status=overall_status
    )
    db.session.add(parse_result)
    db.session.flush()

    for f in findings:
        db.session.add(SecurityFinding(
            parse_result_id=parse_result.id,
            severity=f['severity'],
            finding_type=f['finding_type'],
            description=f['description'],
            file_path=f.get('file_path'),
            line_number=f.get('line_number'),
            code_snippet=f.get('code_snippet'),
            recommendation=f.get('recommendation')
        ))

    db.session.commit()
    logger.info(f"Security scan for version {project_version.id}: {overall_status} ({len(findings)} findings)")
    return parse_result


def _run_bandit(source_dir: str) -> list:
    """Source/AST scan (audit-only, Decision 6) - entries never set 'blocking'"""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'bandit', '-r', '-f', 'json', source_dir],
            capture_output=True, text=True, timeout=_SCAN_TIMEOUT_SECONDS
        )
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
        logger.warning(f"Bandit scan skipped: {e}")
        return []

    findings = []
    for issue in data.get('results', []):
        try:
            file_path = os.path.relpath(issue['filename'], source_dir)
        except ValueError:
            file_path = issue.get('filename')
        findings.append({
            'severity': _BANDIT_SEVERITY_MAP.get(issue.get('issue_severity'), 'medium'),
            'finding_type': 'code_pattern',
            'description': f"{issue.get('test_id')}: {issue.get('issue_text')}",
            'file_path': file_path,
            'line_number': issue.get('line_number'),
            'code_snippet': issue.get('code'),
            'recommendation': issue.get('more_info'),
            'blocking': False
        })
    return findings


def _run_safety(source_dir: str) -> list:
    """Dependency vulnerability scan against requirements.txt (blocks, Decision 6)"""
    requirements_path = os.path.join(source_dir, 'requirements.txt')
    if not os.path.isfile(requirements_path):
        return []

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'safety', 'check', '-r', requirements_path, '--json'],
            capture_output=True, text=True, timeout=_SCAN_TIMEOUT_SECONDS
        )
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError) as e:
        logger.warning(f"Safety scan skipped: {e}")
        return []

    findings = []
    for vuln in data.get('vulnerabilities', []):
        fixed_versions = vuln.get('fixed_versions') or []
        findings.append({
            'severity': 'critical',
            'finding_type': 'dependency',
            'description': f"{vuln.get('package_name')} {vuln.get('analyzed_version')}: "
                            f"{(vuln.get('advisory') or '')[:500]}",
            'file_path': 'requirements.txt',
            'line_number': None,
            'code_snippet': None,
            'recommendation': f"Fixed in: {', '.join(fixed_versions)}" if fixed_versions else 'No fix published yet',
            'blocking': True
        })
    return findings
