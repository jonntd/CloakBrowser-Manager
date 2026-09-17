import json
from pathlib import Path

import pytest

import cloak_accounts_mcp as mcp


def test_base_url_rejects_remote(monkeypatch):
    monkeypatch.setattr(mcp, "_server_info", lambda: {"base_url": "http://example.com", "token": "x"})
    with pytest.raises(mcp.CloakAccountsError, match="本机"):
        mcp._base_url()


def test_base_url_rejects_non_http(monkeypatch):
    monkeypatch.setattr(mcp, "_server_info", lambda: {"base_url": "https://127.0.0.1:8797", "token": "x"})
    with pytest.raises(mcp.CloakAccountsError, match="本机"):
        mcp._base_url()


def test_safe_account_does_not_expose_secrets():
    result = mcp._safe_account(
        {
            "id": "id",
            "name": "demo",
            "proxy": "http://user:password@example.test:80",
            "user_data_dir": "/private/profile",
            "launch_args": ["--dangerous"],
            "status": "stopped",
        }
    )
    assert result == {"id": "id", "name": "demo", "status": "stopped"}
    assert "proxy" not in result
    assert "user_data_dir" not in result
    assert "launch_args" not in result


def test_resolve_id_rejects_ambiguous_name(monkeypatch):
    monkeypatch.setattr(
        mcp,
        "_accounts",
        lambda: [{"id": "one", "name": "same"}, {"id": "two", "name": "same"}],
    )
    with pytest.raises(mcp.CloakAccountsError, match="不唯一"):
        mcp._resolve_id("same")


def test_delete_requires_confirmation():
    with pytest.raises(mcp.CloakAccountsError, match="confirm=true"):
        mcp.delete_account("demo")


def test_clear_data_requires_confirmation():
    with pytest.raises(mcp.CloakAccountsError, match="confirm=true"):
        mcp.clear_account_data("demo")


def test_validate_url():
    assert mcp._validate_url("https://example.com/path") == "https://example.com/path"
    with pytest.raises(mcp.CloakAccountsError):
        mcp._validate_url("javascript:alert(1)")
