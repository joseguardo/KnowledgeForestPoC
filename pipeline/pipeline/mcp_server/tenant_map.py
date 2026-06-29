from __future__ import annotations

import json
from dataclasses import dataclass

from pipeline.config import settings

# Maps a logged-in user's email to the tenant(s) they belong to, so MCP login can
# auto-grant tenant_members and the existing per-tenant RLS visibility "just
# works". Membership is ADDITIVE: a user joins every firm whose explicit email
# list or domain matches (e.g. niklas is in both Kibo and Nzyme). The
# @kiboventures.com domain is shared between Kibo and Nzyme people, so Kibo is
# defined by an explicit list (not the domain); only nzalpha.com maps by domain.

KIBO_TENANT = "ca61f0e5-563e-5894-954f-38f5a9e0eabc"
NZYME_TENANT = "baa52eca-4c88-4861-9d45-720e743febb4"

_KIBO_EMAILS = {
    "nacho@kiboventures.com", "niklas@kiboventures.com", "jaaz@kiboventures.com",
    "ines@kiboventures.com", "jose@kiboventures.com", "juan@kiboventures.com",
    "hello@kiboventures.com", "sara@kiboventures.com", "juan@aallende.com",
    "sonia@kiboventures.com", "covadonga@kiboventures.com", "edvinas@kiboventures.com",
    "jma@kiboventures.com", "jordi@kiboventures.com", "aquilino@kiboventures.com",
    "lucia@kiboventures.com",
}
_NZYME_EMAILS = {
    "reyes@kiboventures.com", "santiago@kiboventures.com", "alf@kiboventures.com",
    "vicente@kiboventures.com", "gpa@kiboventures.com", "pablo@kiboventures.com",
    "juan@kiboventures.com", "jmg@kiboventures.com", "jaimegervas@kiboventures.com",
    "jaimepedrosa@kiboventures.com", "pablomayoral@kiboventures.com",
    "miguel@kiboventures.com", "aris@kiboventures.com", "jacob@kiboventures.com",
    "guillermo@kiboventures.com", "natalia@kiboventures.com", "mar@kiboventures.com",
    "jaaz@kiboventures.com", "fernando@kiboventures.com", "gsa@kiboventures.com",
    "ignacio@kiboventures.com", "sakhee.joisher@nzalpha.com",
    "alvaro.fresnillo@nzalpha.com", "niklas@kiboventures.com", "jose.guardo@nzyme.com",
}


@dataclass(frozen=True)
class _Firm:
    tenant_id: str
    domains: frozenset[str]
    emails: frozenset[str]


def _default_firms() -> list[_Firm]:
    return [
        _Firm(KIBO_TENANT, frozenset(), frozenset(e.lower() for e in _KIBO_EMAILS)),
        _Firm(
            NZYME_TENANT,
            frozenset({"nzalpha.com"}),
            frozenset(e.lower() for e in _NZYME_EMAILS),
        ),
    ]


def _load_firms() -> list[_Firm]:
    """Firms from MCP_TENANT_FIRMS env (JSON: [{tenant_id, domains[], emails[]}]),
    else the baked-in defaults."""
    raw = (settings.mcp_tenant_firms or "").strip()
    if not raw:
        return _default_firms()
    firms: list[_Firm] = []
    for f in json.loads(raw):
        firms.append(
            _Firm(
                f["tenant_id"],
                frozenset(d.strip().lower() for d in f.get("domains", [])),
                frozenset(e.strip().lower() for e in f.get("emails", [])),
            )
        )
    return firms


def resolve_tenants(email: str) -> list[str]:
    """All tenant_ids the email belongs to (additive). Empty if no firm matches."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return []
    domain = email.split("@")[-1]
    out: list[str] = []
    for f in _load_firms():
        if (email in f.emails or domain in f.domains) and f.tenant_id not in out:
            out.append(f.tenant_id)
    return out
