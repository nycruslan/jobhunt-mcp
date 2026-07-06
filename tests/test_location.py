"""Tests for the shared location filter — prefs passed explicitly so nothing
here depends on the personal profile.yaml."""
from feeds._location import is_local_or_remote

# An NYC-based user with US-scope remote, mirroring the default prefs shape.
NY_PREFS = {
    "home_terms":   ["new york", "nyc", "new york city",
                     "manhattan", "brooklyn", "queens", "bronx"],
    "home_states":  ["NY"],
    "allow_remote": True,
    "remote_scope": "us",
}


def ny(loc: str) -> bool:
    return is_local_or_remote(loc, NY_PREFS)


def test_bare_remote_passes_under_us_scope():
    # No US anchor, but no foreign signal either — most US companies don't
    # anchor their US-only remote listings.
    assert ny("Remote")


def test_us_anchored_remote_passes():
    assert ny("Remote, US")
    assert ny("Remote - United States")


def test_foreign_remote_blocked():
    assert not ny("Remote - Canada")
    assert not ny("Remote (Poland)")
    assert not ny("Remote - EMEA")


def test_worldwide_remote_accepted():
    assert ny("Remote - Worldwide")


def test_home_state_code_wins_over_state_name_substring():
    # "washington" appears as a substring but the NY anchor must win.
    assert ny("Port Washington, NY")


def test_multi_state_codes_scan_all_not_just_first():
    # First code is CA, but NY appears later — must pass for an NY user.
    assert ny("US, CA; US, NY")


def test_multi_state_codes_all_foreign_blocked():
    assert not ny("US, CA; US, TX")


def test_home_city_passes():
    assert ny("New York, NY")
    assert ny("Brooklyn")


def test_non_home_city_blocked():
    assert not ny("San Francisco, CA")


def test_non_home_state_name_blocked():
    assert not ny("Seattle, Washington")


def test_plain_foreign_city_blocked():
    assert not ny("Toronto, Ontario, Canada")
    assert not ny("London")


def test_empty_location_blocked():
    assert not ny("")


def test_remote_scope_none_blocks_remote():
    prefs = {**NY_PREFS, "remote_scope": "none"}
    assert not is_local_or_remote("Remote, US", prefs)
    assert is_local_or_remote("New York, NY", prefs)  # local still passes


def test_allow_remote_false_blocks_remote():
    prefs = {**NY_PREFS, "allow_remote": False}
    assert not is_local_or_remote("Remote", prefs)


def test_remote_scope_anywhere_accepts_foreign_remote():
    prefs = {**NY_PREFS, "remote_scope": "anywhere"}
    assert is_local_or_remote("Remote - Canada", prefs)


def test_other_home_state():
    prefs = {**NY_PREFS, "home_terms": ["austin"], "home_states": ["TX"]}
    assert is_local_or_remote("Austin, TX", prefs)
    assert is_local_or_remote("US, CA; US, TX", prefs)
    assert not is_local_or_remote("New York, NY", prefs)


def test_remote_with_foreign_hubs_blocked():
    # Multi-location strings from real Greenhouse boards: European hubs plus a
    # remote token must not read as US remote (regression: Nordics were missing
    # from the foreign-signal list).
    prefs = {
        "home_terms": ["new york", "nyc"],
        "home_states": ["NY"],
        "allow_remote": True,
        "remote_scope": "us",
    }
    from feeds._location import is_local_or_remote
    assert not is_local_or_remote("Finland; Remote - Denmark; Stockholm, Sweden", prefs)
    assert not is_local_or_remote("Remote - Toronto", prefs)
    assert not is_local_or_remote("London or Remote", prefs)
    assert not is_local_or_remote("Remote (Bangalore)", prefs)
    # US remote is still fine.
    assert is_local_or_remote("Remote", prefs)
    assert is_local_or_remote("Remote - US", prefs)


def test_hyphenated_home_and_remote_tokens():
    prefs = {
        "home_terms": ["new york", "nyc"],
        "home_states": ["NY"],
        "allow_remote": True,
        "remote_scope": "us",
    }
    from feeds._location import is_local_or_remote
    # Boards write "New-York" and "CAN-Remote"; hyphens must read as spaces.
    assert is_local_or_remote("New-York, Atlanta, Remote, Toronto", prefs)
    assert not is_local_or_remote("Toronto, CAN-Remote", prefs)
