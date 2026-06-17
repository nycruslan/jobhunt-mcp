"""Tests for the pipeline automation policy (auto.py) — all pure, no I/O."""
import auto


def test_application_confirmation_detection():
    assert auto.is_application_confirmation("Thank you for applying to Stripe!")
    assert auto.is_application_confirmation("We have received your application.")
    assert auto.is_application_confirmation("Your application was submitted successfully")
    assert not auto.is_application_confirmation("Here is your weekly tech newsletter")
    assert not auto.is_application_confirmation("")


def test_signal_status_mapping():
    assert auto.signal_status("application_received") == "applied"
    assert auto.signal_status("rejected") == "rejected"
    assert auto.signal_status("interview") == "screen"
    assert auto.signal_status("onsite") == "onsite"
    assert auto.signal_status("offer") == "offer"
    assert auto.signal_status("nonsense") is None


def test_auto_apply_gate():
    assert auto.should_auto_apply("application_received")
    assert auto.should_auto_apply("rejected")
    assert auto.should_auto_apply("interview")
    # High-stakes signals require human confirmation.
    assert not auto.should_auto_apply("onsite")
    assert not auto.should_auto_apply("offer")


def test_candidate_statuses():
    assert auto.candidate_statuses("application_received") == ("new", "reviewed", "drafted", "applied")
    assert auto.candidate_statuses("rejected") == ("applied", "screen", "onsite")


def test_is_forward_progress():
    assert auto.is_forward("drafted", "applied")
    assert auto.is_forward("applied", "screen")
    assert auto.is_forward("screen", "onsite")
    assert auto.is_forward("new", "offer")
    # Forward to a terminal close is always allowed from a live stage.
    assert auto.is_forward("applied", "rejected")
    # Never regress, never re-apply the same stage, never revive a terminal row.
    assert not auto.is_forward("onsite", "screen")
    assert not auto.is_forward("applied", "applied")
    assert not auto.is_forward("rejected", "screen")


def test_match_jobs_exact_and_subset():
    jobs = [{"company": "Stripe"}, {"company": "Google"}, {"company": "Scale AI"}]
    assert [j["company"] for j in auto.match_jobs("Stripe", jobs)] == ["Stripe"]
    assert [j["company"] for j in auto.match_jobs("Scale AI", jobs)] == ["Scale AI"]
    # Legal suffix / extra word should still match the brand.
    assert auto.match_jobs("Stripe Inc", [{"company": "Stripe"}])
    assert auto.match_jobs("Stripe", [{"company": "Stripe Payments"}])


def test_match_jobs_no_false_positive_and_multiple():
    assert auto.match_jobs("Google", [{"company": "Stripe"}]) == []
    # A generic-only name carries no signal and must not match anything.
    assert auto.match_jobs("AI", [{"company": "Scale AI"}]) == []
    # Several matches are returned so the caller can refuse to guess.
    multi = auto.match_jobs("Stripe", [{"company": "Stripe"}, {"company": "Stripe Payments"}])
    assert len(multi) == 2
