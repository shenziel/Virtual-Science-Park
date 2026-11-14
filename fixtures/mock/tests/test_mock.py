"""Mock-only checks. Deleted together with fixtures/mock/."""

from contracts.models import Visibility
from fixtures.loader import MOCK, load_seed

SEED = load_seed(MOCK)


def test_three_companies():
    assert len(SEED.profiles) == 3


def test_everything_is_labelled_simulated():
    assert all(p.is_simulated and "(simulated)" in p.name for p in SEED.profiles.values())
    assert all(o.is_simulated for o in SEED.opportunities.values())


def test_only_example_domains():
    urls = [p.website for p in SEED.profiles.values()]
    urls += [c.evidence_url for p in SEED.profiles.values() for c in p.claims if c.evidence_url]
    urls += [o.url for o in SEED.opportunities.values()]
    assert all(".example.com" in u for u in urls)


def test_both_visibilities_present():
    assert {p.visibility for p in SEED.profiles.values()} == set(Visibility)


def test_different_companies_get_different_top_match():
    best = {}
    for r in SEED.recommendations:
        if r.score > best.get(r.company_id, (-1, ""))[0]:
            best[r.company_id] = (r.score, r.opportunity_id)
    tops = [opp for _, opp in best.values()]
    assert len(tops) >= 2 and len(set(tops)) == len(tops)
