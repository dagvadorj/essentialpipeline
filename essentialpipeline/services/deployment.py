"""
Deployment / approval workflow for EssentialPipeline (README's lifecycle:
... -> Publish Version -> Deploy -> Run). Deployment/Approval already
existed as pure data models with nothing creating or transitioning them;
this is the service logic that actually drives Deployment.status.

State machine (Deployment.status):

    pending --qa approval--> approved_qa --deployed()--> deployed --rollback()--> rolled_back
       |                        |
       reject()             prod approval (production environments only)
       v                        v
    rejected_qa             approved_prod --deployed()--> deployed --rollback()--> rolled_back
                                |
                                reject()
                                v
                            rejected_prod

A non-production Environment only needs the one qa-type approval before
it can be marked deployed. A production Environment (Environment.
is_production) needs a second, separate prod approval too - a fuller
sign-off reserved for the one target where a bad deploy actually
matters, rather than the same friction everywhere.

mark_deployed() is deliberately just state + timestamp bookkeeping, not
a real deployment mechanism - there's nowhere for a "deployed" project
to actually run beyond the same Docker task execution this app already
has (Decision 4/Garage, the storage layer a real deploy would need,
isn't built). It records that a human with the right permission signed
off; it doesn't push code anywhere.

Authorization mirrors the Governance Gate's group-permission pattern
(services/governance_gate.py): reuses the seeded deployment_request/
deployment_approve/deployment_manage Permissions rather than inventing
a parallel scheme, and fails closed if the acting user's groups don't
hold the relevant one.
"""

from datetime import datetime


class DeploymentWorkflowError(ValueError):
    """Raised when a deployment action is attempted out of turn"""
    pass


class DeploymentPermissionError(DeploymentWorkflowError):
    """Raised when the acting user isn't authorized for the attempted action"""
    pass


def has_permission(user, resource_type: str, action: str) -> bool:
    return any(
        p.resource_type == resource_type and p.action == action
        for group in user.groups
        for p in group.permissions
    )


def _log(deployment, level: str, message: str, context: dict = None):
    """Appends a DeploymentLog row to the same session, without its own commit -
    callers add it alongside the state change they're already committing."""
    from essentialpipeline import db
    from essentialpipeline.models import DeploymentLog

    db.session.add(DeploymentLog(
        deployment_id=deployment.id, level=level, message=message, context=context
    ))


def request_deployment(project_version, environment, requester):
    """Request a deployment of a published version to an environment."""
    from essentialpipeline import db
    from essentialpipeline.models import Deployment, DeploymentLog

    if not project_version.is_published:
        raise DeploymentWorkflowError('Only a published version can be deployed')

    if not has_permission(requester, 'deployment', 'create'):
        raise DeploymentPermissionError(
            "User does not belong to any group holding the 'deployment_request' permission"
        )

    in_flight = Deployment.query.filter(
        Deployment.project_version_id == project_version.id,
        Deployment.environment_id == environment.id,
        Deployment.status.in_(['pending', 'approved_qa', 'approved_prod'])
    ).first()
    if in_flight:
        raise DeploymentWorkflowError(
            f"A deployment to {environment.name} for this version is already in progress (#{in_flight.id})"
        )

    deployment = Deployment(
        project_version_id=project_version.id,
        environment_id=environment.id,
        status='pending',
        requested_by=requester.id
    )
    db.session.add(deployment)
    db.session.flush()
    db.session.add(DeploymentLog(
        deployment_id=deployment.id, level='info',
        message=f"{requester.username} requested deployment of v{project_version.version} to {environment.name}",
        context={'requested_by': requester.id, 'environment_id': environment.id}
    ))
    db.session.commit()
    return deployment


def _next_approval_stage(deployment):
    """Returns (approval_type, next_status_on_approve, next_status_on_reject), or raises"""
    if deployment.status == 'pending':
        return 'qa', 'approved_qa', 'rejected_qa'
    if deployment.status == 'approved_qa' and deployment.environment.is_production:
        return 'prod', 'approved_prod', 'rejected_prod'
    raise DeploymentWorkflowError(
        f"Deployment is in status '{deployment.status}' and has no pending approval stage"
    )


def approve(deployment, approver, comments=None):
    """Approve the next pending stage (qa, then prod for production environments only)."""
    from essentialpipeline import db
    from essentialpipeline.models import Approval

    if not has_permission(approver, 'deployment', 'write'):
        raise DeploymentPermissionError(
            "User does not belong to any group holding the 'deployment_approve' permission"
        )
    if approver.id == deployment.requested_by:
        raise DeploymentPermissionError('The requester cannot approve their own deployment')

    approval_type, next_status, _ = _next_approval_stage(deployment)

    db.session.add(Approval(
        deployment_id=deployment.id, approver_id=approver.id,
        approval_type=approval_type, status='approved', comments=comments,
        approved_at=datetime.utcnow()
    ))
    deployment.status = next_status
    _log(deployment, 'info', f"{approver.username} approved the {approval_type} stage", {'comments': comments})
    db.session.commit()
    return deployment


def reject(deployment, approver, comments=None):
    """Reject the next pending stage."""
    from essentialpipeline import db
    from essentialpipeline.models import Approval

    if not has_permission(approver, 'deployment', 'write'):
        raise DeploymentPermissionError(
            "User does not belong to any group holding the 'deployment_approve' permission"
        )

    approval_type, _, next_status = _next_approval_stage(deployment)

    db.session.add(Approval(
        deployment_id=deployment.id, approver_id=approver.id,
        approval_type=approval_type, status='rejected', comments=comments,
        approved_at=datetime.utcnow()
    ))
    deployment.status = next_status
    _log(deployment, 'warning', f"{approver.username} rejected the {approval_type} stage", {'comments': comments})
    db.session.commit()
    return deployment


def mark_deployed(deployment, actor):
    """Record that an approved deployment has actually been deployed."""
    from essentialpipeline import db

    if not has_permission(actor, 'deployment', 'admin'):
        raise DeploymentPermissionError(
            "User does not belong to any group holding the 'deployment_manage' permission"
        )

    ready_status = 'approved_prod' if deployment.environment.is_production else 'approved_qa'
    if deployment.status != ready_status:
        raise DeploymentWorkflowError(
            f"Deployment must be in status '{ready_status}' first (currently '{deployment.status}')"
        )

    deployment.status = 'deployed'
    deployment.deployed_at = datetime.utcnow()
    _log(deployment, 'info', f"{actor.username} marked this deployment as deployed")
    db.session.commit()
    return deployment


def rollback(deployment, actor, reason: str):
    """Roll back a deployed deployment."""
    from essentialpipeline import db

    if not has_permission(actor, 'deployment', 'admin'):
        raise DeploymentPermissionError(
            "User does not belong to any group holding the 'deployment_manage' permission"
        )
    if deployment.status != 'deployed':
        raise DeploymentWorkflowError("Only a deployed deployment can be rolled back")

    deployment.status = 'rolled_back'
    deployment.rollback_at = datetime.utcnow()
    deployment.rollback_reason = reason
    _log(deployment, 'error', f"{actor.username} rolled back this deployment", {'reason': reason})
    db.session.commit()
    return deployment
