from app.auth import credentials_match


def test_rejects_missing_authorization():
    assert credentials_match(None, "owner", "configured-value") is False


def test_rejects_non_basic_authorization():
    assert credentials_match("Bearer sample-token", "owner", "configured-value") is False
