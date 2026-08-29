"""Multi-tenancy: organizations, memberships, roles, and project authorization.

Model
-----
- The tenancy boundary is the **organization**. Every project belongs to an org.
- A user reaches a project through a **Membership** in that org, carrying a role
  (viewer < member < admin < owner).
- Each user gets a **personal org** (org of one) on first use, so the pre-tenancy
  single-user experience is preserved with zero friction.

Backward compatibility
-----------------------
Legacy projects created before tenancy have ``org_id IS NULL``. Access to those
falls back to the old ``owner_id == user`` check, and the project is lazily
"healed" onto the owner's personal org the first time it is authorized — so the
system converges to the tenancy model without a hard cutover.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import ROLE_RANK, Membership, Organization, Project

logger = get_logger("tenancy")


def role_ok(role: str | None, minimum: str) -> bool:
    if role is None:
        return False
    return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(minimum, 99)


async def ensure_personal_org(session: AsyncSession, user: str) -> str:
    """Return the user's personal org id, creating it (+ owner membership) once."""
    existing = await session.scalar(
        select(Organization.id).where(
            Organization.created_by == user, Organization.personal.is_(True))
    )
    if existing:
        return existing
    org = Organization(name="Personal workspace", personal=True, created_by=user)
    session.add(org)
    await session.flush()
    session.add(Membership(org_id=org.id, user_id=user, role="owner"))
    await session.flush()
    logger.info("created personal org", extra={"user": user[:12], "org": org.id})
    return org.id


async def role_in_org(session: AsyncSession, user: str, org_id: str) -> str | None:
    return await session.scalar(
        select(Membership.role).where(
            Membership.org_id == org_id, Membership.user_id == user)
    )


async def user_orgs(session: AsyncSession, user: str) -> list[dict]:
    """Every org the user belongs to, with their role — for an org switcher."""
    rows = (await session.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user)
        .order_by(Organization.personal.desc(), Organization.created_at)
    )).all()
    return [{"id": o.id, "name": o.name, "personal": o.personal, "role": role}
            for o, role in rows]


async def authorize_project(
    session: AsyncSession, project: Project, user: str, *, minimum: str = "viewer"
) -> bool:
    """True if `user` may act on `project` at >= `minimum` role.

    - org project: check the user's membership role in project.org_id.
    - legacy project (org_id is None): fall back to owner_id, and heal it onto
      the owner's personal org so future checks are membership-based.
    """
    if project.org_id:
        return role_ok(await role_in_org(session, user, project.org_id), minimum)
    # Legacy path.
    if project.owner_id != user:
        return False
    try:
        project.org_id = await ensure_personal_org(session, user)
    except Exception:
        logger.warning("could not heal legacy project onto personal org",
                       extra={"project": project.id})
    return True  # owner always satisfies any minimum
