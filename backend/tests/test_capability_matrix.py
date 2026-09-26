"""Capability-matrix RBAC tests.

Pins the role-default permission table in ``core.rbac`` so that any accidental
edit to ``ROLE_DEFAULT_PERMISSIONS`` (drop a cap, add one to the wrong role,
etc.) trips a test failure here instead of a silent authz bug in production.
"""

from app.core.rbac import (
    ALL_CAPABILITIES,
    CAP_AI_PROPOSAL_ACCEPT,
    CAP_ATTACHMENTS_DELETE,
    CAP_ATTACHMENTS_UPLOAD,
    CAP_BOQ_MANAGE,
    CAP_CLOSEOUT_MANAGE,
    CAP_CONSTRUCTION_MANAGE,
    CAP_DATA_CONFIRM,
    CAP_DATA_MANAGE,
    CAP_DISPOSITION_MANAGE,
    CAP_EAR_INPUT,
    CAP_EAR_MANAGE,
    CAP_ICR_HANDOFF,
    CAP_MOM_AGENDA,
    CAP_MOM_MANAGE,
    CAP_MTO_MANAGE,
    CAP_PROCUREMENT_MANAGE,
    CAP_PROJECTS_CREATE,
    CAP_PROJECTS_DELETE,
    CAP_PROJECTS_EDIT,
    CAP_SOW_MANAGE,
    CAP_USERS_MANAGE,
    CAP_WORK_PERMIT_MANAGE,
    ROLE_DEFAULT_PERMISSIONS,
)


def test_all_capabilities_frozenset_matches_constants():
    """ALL_CAPABILITIES is the canonical set; if a new cap is added to
    ROLE_DEFAULT_PERMISSIONS without being added here, the test fails."""
    assert ALL_CAPABILITIES == frozenset(
        {
            CAP_PROJECTS_CREATE,
            CAP_PROJECTS_EDIT,
            CAP_PROJECTS_DELETE,
            CAP_ATTACHMENTS_UPLOAD,
            CAP_ATTACHMENTS_DELETE,
            CAP_MOM_MANAGE,
            CAP_MOM_AGENDA,
            CAP_USERS_MANAGE,
            CAP_DISPOSITION_MANAGE,
            CAP_EAR_INPUT,
            CAP_EAR_MANAGE,
            CAP_SOW_MANAGE,
            CAP_BOQ_MANAGE,
            CAP_MTO_MANAGE,
            CAP_PROCUREMENT_MANAGE,
            CAP_WORK_PERMIT_MANAGE,
            CAP_CONSTRUCTION_MANAGE,
            CAP_CLOSEOUT_MANAGE,
            CAP_ICR_HANDOFF,
            CAP_AI_PROPOSAL_ACCEPT,
            CAP_DATA_MANAGE,
            CAP_DATA_CONFIRM,
        }
    )


def test_admin_has_every_capability():
    """Admins inherit the full set. Always. No exceptions."""
    assert ROLE_DEFAULT_PERMISSIONS["admin"] == ALL_CAPABILITIES


def test_trade_role_default_caps():
    """Trade users contribute their discipline input into EAR / SOW / MTO and
    accept AI drafts. They are not allowed to manage the SOW record itself
    or to set dispositions, manage construction, etc."""
    assert ROLE_DEFAULT_PERMISSIONS["trade"] == frozenset(
        {
            CAP_MOM_AGENDA,
            CAP_EAR_INPUT,
            CAP_MTO_MANAGE,
            CAP_AI_PROPOSAL_ACCEPT,
        }
    )


def test_planning_role_default_caps():
    """Planning owns the disposition / EAR / SOW / BOQ / procurement records
    and the §3 traceability engine (data.manage + data.confirm)."""
    assert ROLE_DEFAULT_PERMISSIONS["planning"] == frozenset(
        {
            CAP_MOM_AGENDA,
            CAP_DISPOSITION_MANAGE,
            CAP_EAR_MANAGE,
            CAP_SOW_MANAGE,
            CAP_BOQ_MANAGE,
            CAP_MTO_MANAGE,
            CAP_PROCUREMENT_MANAGE,
            CAP_AI_PROPOSAL_ACCEPT,
            CAP_DATA_MANAGE,
            CAP_DATA_CONFIRM,
        }
    )


def test_construction_manager_role_default_caps():
    """Construction managers own work permits, construction, and closeout.
    They also reconcile the construction MTO against design and drive the
    ICR hand-off flow."""
    assert ROLE_DEFAULT_PERMISSIONS["construction_manager"] == frozenset(
        {
            CAP_MOM_AGENDA,
            CAP_MTO_MANAGE,
            CAP_WORK_PERMIT_MANAGE,
            CAP_CONSTRUCTION_MANAGE,
            CAP_CLOSEOUT_MANAGE,
            CAP_ICR_HANDOFF,
            CAP_AI_PROPOSAL_ACCEPT,
        }
    )


def test_team_member_role_default_caps():
    """A team_member has read-only MOM agenda access and nothing else by
    default. Explicit per-user overrides grant higher trust."""
    assert ROLE_DEFAULT_PERMISSIONS["team_member"] == frozenset({CAP_MOM_AGENDA})


def test_every_role_default_cap_is_in_all_capabilities():
    """No role gets a capability that isn't registered. Catches a typo like
    `mom.agendaa` that would be silently meaningless."""
    for role, caps in ROLE_DEFAULT_PERMISSIONS.items():
        unknown = caps - ALL_CAPABILITIES
        assert not unknown, f"role {role!r} has unknown caps: {sorted(unknown)}"


def test_no_role_default_has_duplicate_or_empty():
    """Sanity: the defaults are frozensets, not lists (so .isdisjoint() works
    for role-mix-up checks) and they aren't empty (an empty default for admin
    would mean admins are useless)."""
    for role, caps in ROLE_DEFAULT_PERMISSIONS.items():
        assert isinstance(caps, frozenset), f"{role} caps is not a frozenset"
        if role == "admin":
            assert len(caps) > 0
        # Non-admin roles can have empty defaults in principle; we only
        # assert that admin is non-empty (test_admin_has_every_capability
        # already pins the rest).


def test_icr_handoff_only_construction_manager_by_default():
    """icr.handoff is construction-specific — only the construction_manager
    role should have it by default. If we ever grant it to planning, the
    audit log will start showing planners recording hand-offs.

    Admin always has everything; we exclude admin from this check."""
    roles_with_icr = [
        role
        for role, caps in ROLE_DEFAULT_PERMISSIONS.items()
        if role != "admin" and CAP_ICR_HANDOFF in caps
    ]
    assert roles_with_icr == ["construction_manager"], roles_with_icr


def test_disposition_manage_only_planning_by_default():
    """Setting a project's disposition is a planning-team decision."""
    roles_with_disp = [
        role
        for role, caps in ROLE_DEFAULT_PERMISSIONS.items()
        if role != "admin" and CAP_DISPOSITION_MANAGE in caps
    ]
    assert roles_with_disp == ["planning"], roles_with_disp


def test_work_permit_only_construction_manager_by_default():
    """Work permits are filed by the construction department. Trade and
    planning don't see the work-permit endpoint by default."""
    roles_with_wp = [
        role
        for role, caps in ROLE_DEFAULT_PERMISSIONS.items()
        if role != "admin" and CAP_WORK_PERMIT_MANAGE in caps
    ]
    assert roles_with_wp == ["construction_manager"], roles_with_wp
