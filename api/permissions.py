"""Who may see or change what (AGENTS.md section 6). Owner: Backend 1.

Checked server-side on every request. The rules:
- Visitor: published profiles and their recommendations; all opportunities.
- Company user: own profile in any state + published ones; edits only their own.
- BSP admin: sees and edits everything.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from contracts.models import Role, User, Visibility

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, "You can only change your own company's profile")


def not_found(what: str = "Company") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def can_view(user: User | None, company_id: str, visibility: Visibility) -> bool:
    if visibility == Visibility.published:
        return True
    if user is None:
        return False
    return user.role == Role.admin or user.company_id == company_id


def require_edit(user: User, company_id: str) -> None:
    """403 unless the user is a BSP admin or belongs to `company_id`.

    Checked before looking the company up, so a 403 never reveals whether
    another company exists.
    """
    if user.role == Role.admin:
        return
    if user.company_id != company_id:
        raise FORBIDDEN
