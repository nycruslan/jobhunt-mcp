"""Tests for the scoring engine (score.py). Assertions are relative so they hold
regardless of the exact profile.yaml weights."""
import score

JD = ("We build LLM agents with RAG and inference at scale. Python, distributed "
      "systems, Kubernetes, and a platform team that ships fast.")


def test_score_in_range():
    s = score.score_job("Senior Software Engineer", JD, "anthropic", "")
    assert 0 <= s <= 100


def test_level_numeral_does_not_penalize_senior():
    # The junior-regex must not crush a senior role that carries a level numeral.
    with_ii = score.score_job("Senior Software Engineer II, Platform", JD, "anthropic", "")
    without = score.score_job("Senior Software Engineer, Platform", JD, "anthropic", "")
    assert with_ii == without


def test_junior_and_offrole_rank_below_senior():
    senior = score.score_job("Senior Software Engineer", JD, "google", "")
    intern = score.score_job("Software Engineering Intern", JD, "google", "")
    sales = score.score_job("Sales Engineer", JD, "google", "")
    new_grad = score.score_job("Software Engineer I", JD, "google", "")
    assert intern < senior
    assert sales < senior
    assert new_grad < senior


def test_empty_inputs_safe():
    assert score.score_job("", "", "", "") >= 0


def test_real_comp_beats_no_comp_signal():
    # A strong posted band should not score below the same role with nothing.
    with_band = score.score_job("Senior Software Engineer", JD, "", "400-600K")
    no_band = score.score_job("Senior Software Engineer", JD, "", "")
    assert with_band >= no_band


def test_transparency_never_hurts_curated_company(monkeypatch):
    # Posted bands are BASE salary; the curated tc_range is TOTAL comp. A listed
    # company that discloses its (lower) base band must not rank below itself.
    # Fixed index so the test doesn't depend on the user's personal targets.yaml.
    monkeypatch.setattr(score, "_company_index",
                        lambda: {"examplecorp": {"tc_max": 900, "tc_range": "450-900K"}})
    with_band = score.score_job("Senior Software Engineer", JD, "ExampleCorp", "300-405K")
    no_band = score.score_job("Senior Software Engineer", JD, "ExampleCorp", "")
    assert with_band >= no_band
    # And a posting that pays above the curated ceiling still helps.
    assert score._comp_fit("ExampleCorp", "500-1200K") >= score._comp_fit("ExampleCorp", "")


def test_offrole_modifier_does_not_sink_engineer_title():
    # "Operations" as a specialty modifier must not trip the off-role penalty.
    mlops = score.score_job("Senior Software Engineer, Machine Learning Operations", "", "", "")
    ml = score.score_job("Senior Software Engineer, Machine Learning", "", "", "")
    assert mlops == ml
    hw_infra = score.score_job("Senior Software Engineer, Hardware Infrastructure", "", "", "")
    infra = score.score_job("Senior Software Engineer, Infrastructure", "", "", "")
    assert hw_infra == infra


def test_pure_offrole_titles_still_penalized():
    senior = score.score_job("Senior Software Engineer", JD, "", "")
    for title in ("Operations Manager", "Customer Support Specialist",
                  "Talent Acquisition Partner", "Hardware Engineer"):
        assert score.score_job(title, JD, "", "") < senior, title
