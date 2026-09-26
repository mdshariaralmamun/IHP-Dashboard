"""Project stage state machine + append-only audit helper.

Per the v2 spec (Section 2A), the workflow forks after DISPOSITION:

- PROJECT branch: INTAKE -> MOM -> DISPOSITION -> EAR -> SOW -> MTO ->
                  PROCUREMENT -> WORK_PERMIT -> CONSTRUCTION -> CLOSEOUT.
- ICR branch:     INTAKE -> MOM -> DISPOSITION -> MTO -> MTO_APPROVED -> done.
                  ICR never reaches EAR, SOW, PROCUREMENT, WORK_PERMIT,
                  CONSTRUCTION, or CLOSEOUT — there is no work permit, no
                  construction-department hand-off. After MTO_APPROVED the
                  project routes to Project Control (orders materials) and
                  then to the Equipment Assessment Team (install + follow-up).
                  That hand-off is tracked in IcrHandoff, not in this state
                  machine.

ICR-vs-PROJECT is encoded into the transition table as a property of the
PROJECT class of stages: the ICR branch can never reach EAR_DRAFT, SOW_*,
PROCUREMENT, WORK_PERMIT, CONSTRUCTION, or CLOSEOUT.
"""

from sqlalchemy.orm import Session

from ..models import AuditLog, Project, User

# --- Stage constants ---------------------------------------------------------
INTAKE = "INTAKE"
MOM_SENT = "MOM_SENT"
MOM_CONFIRMED = "MOM_CONFIRMED"
DISPOSITION = "DISPOSITION"
EAR_DRAFT = "EAR_DRAFT"
EAR_REVIEW = "EAR_REVIEW"
EAR_APPROVED = "EAR_APPROVED"
SOW_DRAFT = "SOW_DRAFT"
SOW_REVIEW = "SOW_REVIEW"
SOW_APPROVED = "SOW_APPROVED"
MTO_DRAFT = "MTO_DRAFT"
MTO_APPROVED = "MTO_APPROVED"
PROCUREMENT = "PROCUREMENT"
WORK_PERMIT = "WORK_PERMIT"
CONSTRUCTION = "CONSTRUCTION"
CLOSEOUT = "CLOSEOUT"
# Punch-list stage: reached after WCC/WCH (closeout). Handover defects are
# tracked and cleared here before the project counts as fully closed.
PUNCH_LIST = "PUNCH_LIST"
# ICR branch terminal stage. Distinct from CLOSEOUT (which is a project-class
# closeout with as-builts, punch list, etc.). ICR_DONE means the MTO was
# handed to Project Control and the EAT install/follow-up is recorded.
ICR_DONE = "ICR_DONE"

STAGES = [
    INTAKE,
    MOM_SENT,
    MOM_CONFIRMED,
    DISPOSITION,
    EAR_DRAFT,
    EAR_REVIEW,
    EAR_APPROVED,
    SOW_DRAFT,
    SOW_REVIEW,
    SOW_APPROVED,
    MTO_DRAFT,
    MTO_APPROVED,
    PROCUREMENT,
    WORK_PERMIT,
    CONSTRUCTION,
    CLOSEOUT,
    PUNCH_LIST,
    ICR_DONE,
]

#: Stages that only the PROJECT branch can ever reach.
PROJECT_ONLY_STAGES: frozenset[str] = frozenset(
    {EAR_DRAFT, EAR_REVIEW, EAR_APPROVED, SOW_DRAFT, SOW_REVIEW, SOW_APPROVED,
     PROCUREMENT, WORK_PERMIT, CONSTRUCTION, CLOSEOUT, PUNCH_LIST}
)

#: Allowed forward transitions across project delivery lifecycle.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    INTAKE: {MOM_SENT, DISPOSITION, MTO_DRAFT},
    MOM_SENT: {MOM_CONFIRMED, INTAKE, DISPOSITION, MTO_DRAFT},
    MOM_CONFIRMED: {DISPOSITION, EAR_DRAFT, MTO_DRAFT},
    DISPOSITION: {EAR_DRAFT, MTO_DRAFT},
    EAR_DRAFT: {EAR_REVIEW, DISPOSITION},
    EAR_REVIEW: {EAR_APPROVED, EAR_DRAFT},
    EAR_APPROVED: {SOW_DRAFT, MTO_DRAFT},
    SOW_DRAFT: {SOW_REVIEW, EAR_APPROVED},
    SOW_REVIEW: {SOW_APPROVED, SOW_DRAFT},
    SOW_APPROVED: {MTO_DRAFT, PROCUREMENT},
    MTO_DRAFT: {MTO_APPROVED, DISPOSITION, SOW_APPROVED, ICR_DONE},
    MTO_APPROVED: {PROCUREMENT, WORK_PERMIT, ICR_DONE},
    PROCUREMENT: {WORK_PERMIT, CONSTRUCTION},
    WORK_PERMIT: {CONSTRUCTION},
    CONSTRUCTION: {CLOSEOUT},
    CLOSEOUT: {PUNCH_LIST},
    PUNCH_LIST: set(),
    ICR_DONE: set(),
}


class WorkflowError(Exception):
    """Raised when a stage transition is not allowed."""


def log_action(
    db: Session,
    user: User,
    action: str,
    project: Project | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Append an entry to the audit log (caller commits)."""
    entry = AuditLog(
        project_id=project.id if project else None,
        user_id=user.id,
        action=action,
        detail=detail or {},
    )
    db.add(entry)
    return entry


def transition(
    project: Project,
    to_stage: str,
    user: User,
    db: Session,
    detail: dict | None = None,
    action: str | None = None,
) -> Project:
    """Validate + apply a stage transition and write an AuditLog entry.

    `action` overrides the audit action name (default ``stage:<to_stage>``);
    from/to stages are always recorded in the audit detail. Caller commits.

    ICR-classified projects cannot enter any PROJECT-only stage
    (EAR/SOW/Procurement/WorkPermit/Construction/Closeout). The check is
    here (and not in disposition.py) so any caller — including direct
    transitions triggered by the construction panel, work-permit updates,
    etc. — is uniformly guarded.
    """
    from_stage = project.stage
    allowed = ALLOWED_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise WorkflowError(f"Transition {from_stage} -> {to_stage} is not allowed")
    if project.disposition == "ICR" and to_stage in PROJECT_ONLY_STAGES:
        raise WorkflowError(
            f"ICR-classified projects cannot transition into {to_stage} "
            f"(PROJECT-only stage). Use the ICR hand-off flow instead."
        )
    project.stage = to_stage
    audit_detail = {"from": from_stage, "to": to_stage}
    if detail:
        audit_detail.update(detail)
    log_action(db, user, action or f"stage:{to_stage}", project, audit_detail)
    return project
