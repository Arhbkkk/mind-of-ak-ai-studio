import base64

from app.auth import credentials_match


def _header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def test_accepts_exact_credentials():
    assert credentials_match(_header("owner", "correct horse"), "owner", "correct horse")


def test_rejects_wrong_password():
    assert not credentials_match(_header("owner", "wrong"), "owner", "correct horse")


def test_rejects_wrong_username():
    assert not credentials_match(_header("guest", "correct horse"), "owner", "correct horse")


def test_rejects_missing_or_malformed_header():
    assert not credentials_match(None, "owner", "secret")
    assert not credentials_match("Bearer token", "owner", "secret")
    assert not credentials_match("Basic !!!", "owner", "secret")
