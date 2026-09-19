"""
Governance Gate for EssentialPipeline (README's project lifecycle:
Develop -> Test -> Validate -> Security Scan -> Governance Gate ->
Publish Version -> Deploy -> Run).

Publishing a version is a distinct, gated action - a ProjectVersion is
created unpublished, and evaluate_publish_gate() is the pre-publish
check both the web UI and API publish routes call before flipping
is_published.

Two checks, mirroring the two things governance actually models today:

1. Security scan: blocks if this version has a SecurityParseResult with
   overall_status='failed' (a blocking finding - vulnerable dependency
   or detected secret, per Decision 6). Real, correct logic - it just
   never has anything to find yet, since Decision 6 scanning (Bandit/
   Safety/secret detection) isn't wired up to actually run and create
   SecurityParseResult rows. This check will start doing real work the
   moment that lands, with no changes needed here.

2. Clearance: blocks unless the publishing user belongs to a group
   holding a Permission for resource_type='project', action in
   ('write', 'admin') - fails closed if no such permission/grant exists
   at all, rather than silently letting everyone through because
   nothing's been configured yet.
"""


def evaluate_publish_gate(user, project_version) -> dict:
    """
    Args:
        user: the User requesting to publish
        project_version: the ProjectVersion being published

    Returns:
        {'passed': bool, 'checks': [{'name': str, 'passed': bool, 'message': str}, ...]}
    """
    from essentialpipeline.models import SecurityParseResult

    checks = []

    failed_scan = SecurityParseResult.query.filter_by(
        project_version_id=project_version.id, overall_status='failed'
    ).first()
    checks.append({
        'name': 'security_scan',
        'passed': failed_scan is None,
        'message': (
            f"Blocking security scan result (parse result #{failed_scan.id})"
            if failed_scan else
            "No blocking security scan findings"
        )
    })

    has_clearance = any(
        p.resource_type == 'project' and p.action in ('write', 'admin')
        for group in user.groups
        for p in group.permissions
    )
    checks.append({
        'name': 'publish_clearance',
        'passed': has_clearance,
        'message': (
            "User belongs to a group with project write/admin clearance"
            if has_clearance else
            "User does not belong to any group holding a 'project' write/admin permission"
        )
    })

    return {'passed': all(c['passed'] for c in checks), 'checks': checks}
