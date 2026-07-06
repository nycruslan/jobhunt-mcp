"""Tests for feed plumbing: JobSpy URL identity, HTML stripping, and the
pull() orchestration (error containment + aggregator dedup)."""
import config
import feeds
import feeds._location
from feeds._http import html_to_text
from feeds.jobspy import _url_hash

NY_PREFS = {
    "home_terms":   ["new york", "nyc"],
    "home_states":  ["NY"],
    "allow_remote": True,
    "remote_scope": "us",
}


# ── JobSpy URL hashing ────────────────────────────────────────────────────────

def test_url_hash_keeps_job_identity_params():
    # Indeed job identity lives in the query string — two jk= ids must differ.
    a = _url_hash("https://www.indeed.com/viewjob?jk=abc123")
    b = _url_hash("https://www.indeed.com/viewjob?jk=def456")
    assert a != b


def test_url_hash_ignores_tracking_noise():
    clean = _url_hash("https://www.indeed.com/viewjob?jk=abc123")
    noisy = _url_hash(
        "https://www.indeed.com/viewjob?jk=abc123"
        "&utm_source=x&utm_medium=y&gclid=zzz&fbclid=qqq&ref=serp&source=mail"
    )
    assert clean == noisy


def test_url_hash_stable_across_param_order_and_fragment():
    a = _url_hash("https://x.com/job?a=1&b=2#apply")
    b = _url_hash("https://x.com/job?b=2&a=1")
    assert a == b


def test_url_hash_empty_url():
    assert _url_hash("") == _url_hash(None or "")


# ── HTML stripping ────────────────────────────────────────────────────────────

def test_html_to_text_strips_script_and_style_bodies():
    html = ("<p>Real text</p><script type='text/javascript'>var tracker=1;</script>"
            "<style>.pay{color:red}</style><p>$150,000 - $200,000</p>")
    out = html_to_text(html)
    assert "Real text" in out
    assert "$150,000 - $200,000" in out
    assert "tracker" not in out
    assert "color" not in out


# ── pull() orchestration ──────────────────────────────────────────────────────

def _job(id_, company="", title="Engineer", location="New York, NY"):
    return {"id": id_, "company": company, "title": title, "location": location,
            "jd_text": "", "comp": ""}


def test_pull_contains_one_companys_failure(monkeypatch):
    monkeypatch.setattr(config, "company_aliases", lambda: {})

    def boom(slug):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(feeds.greenhouse, "fetch_jobs", boom)
    monkeypatch.setattr(feeds.lever, "fetch_jobs", lambda slug: [_job("lv_good_1")])

    stored = []
    new, errors, skipped = feeds.pull(
        [{"name": "BadCo", "ats": "greenhouse", "slug": "badco"},
         {"name": "GoodCo", "ats": "lever", "slug": "goodco"}],
        score_fn=lambda *a: 50,
        upsert_fn=lambda j: stored.append(j["id"]) or True,
    )
    assert ("BadCo", "connection reset") in errors
    assert stored == ["lv_good_1"]  # the failure didn't kill the pull
    assert new == 1


def test_pull_contains_per_job_store_failure(monkeypatch):
    monkeypatch.setattr(config, "company_aliases", lambda: {})
    monkeypatch.setattr(feeds.greenhouse, "fetch_jobs",
                        lambda slug: [_job("gh_1", title="A"), _job("gh_2", title="B")])

    stored = []

    def upsert(j):
        if j["id"] == "gh_1":
            raise RuntimeError("db locked")
        stored.append(j["id"])
        return True

    new, errors, skipped = feeds.pull(
        [{"name": "Acme", "ats": "greenhouse", "slug": "acme"}],
        score_fn=lambda *a: 0, upsert_fn=upsert,
    )
    assert stored == ["gh_2"]
    assert any("db locked" in detail for _, detail in errors)


def test_pull_aggregator_dedup_uses_aliases_and_location(monkeypatch):
    monkeypatch.setattr(config, "company_aliases", lambda: {"stripe inc": "Stripe"})
    monkeypatch.setattr(feeds.greenhouse, "fetch_jobs",
                        lambda slug: [_job("gh_stripe_1", title="Staff Engineer")])
    monkeypatch.setattr(feeds.adzuna_feed, "fetch_jobs", lambda: [
        # Alias spelling + equivalent location → duplicate of the ATS job.
        _job("adz_dupe", company="Stripe Inc", title="Staff Engineer",
             location="New York NY"),
        # Same title, different city → distinct posting, must be kept.
        _job("adz_kept", company="Stripe Inc", title="Staff Engineer",
             location="Chicago, IL"),
    ])
    # Aggregator jobs run through the location filter upstream in the real
    # feeds; pull() itself only dedups, so no prefs are needed here.

    stored = []
    new, errors, skipped = feeds.pull(
        [{"name": "Stripe", "ats": "greenhouse", "slug": "stripe"}],
        score_fn=lambda *a: 0,
        upsert_fn=lambda j: stored.append(j["id"]) or True,
        include_adzuna=True,
    )
    assert "adz_dupe" not in stored
    assert "adz_kept" in stored
    assert errors == []


def test_pull_aggregator_failure_lands_in_errors(monkeypatch):
    monkeypatch.setattr(config, "company_aliases", lambda: {})

    def boom():
        raise RuntimeError("rate limited")

    monkeypatch.setattr(feeds.remotive_feed, "fetch_jobs", boom)
    new, errors, skipped = feeds.pull(
        [], score_fn=lambda *a: 0, upsert_fn=lambda j: True, include_remotive=True,
    )
    assert ("Remotive", "rate limited") in errors


# ── Greenhouse normalization ──────────────────────────────────────────────────

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_greenhouse_company_name_and_first_published(monkeypatch):
    monkeypatch.setattr(feeds._location, "preferences", lambda: NY_PREFS)
    payload = {"jobs": [{
        "id": 1,
        "title": "Engineer",
        "company_name": "Stripe",
        "location": {"name": "New York, NY"},
        "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1",
        "content": "<p>desc</p>",
        "first_published": "2026-07-01T00:00:00-04:00",
        "updated_at": "2026-07-05T00:00:00-04:00",
    }]}
    monkeypatch.setattr(feeds.greenhouse.SESSION, "get",
                        lambda *a, **k: _Resp(payload))
    jobs = feeds.greenhouse.fetch_jobs("stripe")
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Stripe"        # job-level company_name, not slug
    assert jobs[0]["posted_at"] == "2026-07-01T00:00:00-04:00"  # not updated_at
