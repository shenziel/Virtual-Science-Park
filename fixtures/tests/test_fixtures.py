"""Validate every seed folder (real data in fixtures/, mock data in fixtures/mock/ if present).

Data-dependent checks skip while a folder is empty.
"""

import pytest

from contracts.models import ProfileField, User
from fixtures.loader import FIXTURES, MOCK, load_seed

FOLDERS = [FIXTURES] + ([MOCK] if MOCK.exists() else [])


@pytest.fixture(params=FOLDERS, ids=lambda f: f.name)
def seed(request):
    return load_seed(request.param)


def test_loads_and_validates(seed):
    assert seed is not None  # load_seed raises on any contract violation


def test_profiles_cover_every_field_or_flag_it(seed):
    for p in seed.profiles.values():
        assert {c.field for c in p.claims} | set(p.missing_fields) == set(ProfileField), p.company_id


def test_recommendations_reference_real_things(seed):
    for r in seed.recommendations:
        assert r.company_id in seed.profiles, r
        assert r.opportunity_id in seed.opportunities, r
        assert set(r.matched_claims) <= {c.id for c in seed.profiles[r.company_id].claims}, r


def test_seed_users_are_valid(seed):
    users = [User(**{k: v for k, v in u.items() if k != "password"}) for u in seed.users]
    assert any(u.role.value == "admin" for u in users)
    assert all(u["password"].startswith("demo-") for u in seed.users), "throwaway passwords only"
    assert len({u.email for u in users}) == len(users)


def test_companies_list_is_valid():
    """fixtures/companies.json drives the profiler: unique slugs, official http(s) websites."""
    import json
    import re

    companies = json.loads((FIXTURES / "companies.json").read_text(encoding="utf-8"))
    ids = [c["company_id"] for c in companies]
    assert len(ids) == len(set(ids))
    for c in companies:
        assert set(c) == {"company_id", "name", "website"}, c
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", c["company_id"]), c
        assert re.fullmatch(r"https?://\S+", c["website"]), c
        assert c["name"].strip(), c


def test_company_users_match_profiles(seed):
    if not seed.profiles:
        pytest.skip("no company profiles yet")
    assert {u["company_id"] for u in seed.users if u["company_id"]} == set(seed.profiles)
