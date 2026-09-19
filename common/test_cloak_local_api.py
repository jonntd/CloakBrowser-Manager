"""cloak_local_api 的安全边界测试(全部离线,不发网络请求)。"""
import io
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cloak_local_api as cla


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._payload


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8797", "http://127.0.0.1:8797"),
        ("http://localhost:8797/", "http://localhost:8797"),
        ("http://[::1]:8797", "http://[::1]:8797"),
    ],
)
def test_validate_base_url_accepts_loopback_root(url, expected):
    assert cla.validate_base_url(url) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "http://example.com",
        "https://127.0.0.1:8797",
        "http://127.0.0.1:9999",
        "http://127.0.0.1:8797/api",
        "http://user:pw@127.0.0.1:8797",
        "http://127.0.0.1:8797/?x=1",
        "http://127.0.0.1:8797#frag",
        "http://127.0.0.1:notaport",
        "http://127.0.0.1",
        123,
        None,
    ],
)
def test_validate_base_url_rejects(bad):
    with pytest.raises(cla.LocalApiError):
        cla.validate_base_url(bad)


def test_validate_token():
    assert cla.validate_token("abc") == "abc"
    with pytest.raises(cla.LocalApiError):
        cla.validate_token("")
    with pytest.raises(cla.LocalApiError):
        cla.validate_token(None)


def test_api_config_reads_and_validates(tmp_path):
    p = tmp_path / "server.json"
    p.write_text('{"base_url": "http://127.0.0.1:8797", "token": "t"}', encoding="utf-8")
    assert cla.api_config(p) == ("http://127.0.0.1:8797", "t")


def test_api_config_rejects_remote(tmp_path):
    p = tmp_path / "server.json"
    p.write_text('{"base_url": "http://evil.example", "token": "t"}', encoding="utf-8")
    with pytest.raises(cla.LocalApiError, match="本机"):
        cla.api_config(p)


def test_api_config_rejects_missing_file(tmp_path):
    with pytest.raises(cla.LocalApiError, match="无法读取"):
        cla.api_config(tmp_path / "missing.json")


def test_api_config_rejects_non_object(tmp_path):
    p = tmp_path / "server.json"
    p.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(cla.LocalApiError, match="格式无效"):
        cla.api_config(p)


def test_request_json_sends_token_and_parses(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["token"] = req.get_header("X-auth-token")
        captured["body"] = req.data
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(cla.urllib.request, "urlopen", fake_urlopen)
    result = cla.request_json(
        "POST", "/accounts/abc/start", {"url": "https://x.test"}, config=("http://127.0.0.1:8797", "sekrit")
    )
    assert result == {"ok": True}
    assert captured["url"] == "http://127.0.0.1:8797/accounts/abc/start"
    assert captured["method"] == "POST"
    assert captured["token"] == "sekrit"
    assert captured["body"] is not None


def test_request_json_empty_response(monkeypatch):
    monkeypatch.setattr(cla.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(b""))
    assert cla.request_json("GET", "/endpoints", config=("http://127.0.0.1:8797", "t")) == {}


def test_request_json_maps_401(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, io.BytesIO(b""))

    monkeypatch.setattr(cla.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(cla.LocalApiError, match="401"):
        cla.request_json("GET", "/accounts", config=("http://127.0.0.1:8797", "t"))


def test_request_json_maps_http_error_with_detail(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", None, io.BytesIO(b"nope"))

    monkeypatch.setattr(cla.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(cla.LocalApiError, match="HTTP 400"):
        cla.request_json("GET", "/accounts", config=("http://127.0.0.1:8797", "t"))


def test_request_json_maps_connection_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cla.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(cla.LocalApiError, match="无法连接"):
        cla.request_json("GET", "/accounts", config=("http://127.0.0.1:8797", "t"))


def test_request_json_maps_invalid_json(monkeypatch):
    monkeypatch.setattr(cla.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(b"{bad"))
    with pytest.raises(cla.LocalApiError, match="无效 JSON"):
        cla.request_json("GET", "/accounts", config=("http://127.0.0.1:8797", "t"))


def test_request_json_reads_config_dynamically(tmp_path, monkeypatch):
    p = tmp_path / "server.json"
    p.write_text('{"base_url": "http://127.0.0.1:8797", "token": "t1"}', encoding="utf-8")
    monkeypatch.setattr(cla, "SERVER_INFO_PATH", p)
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("X-auth-token"))
        return _FakeResponse(b"{}")

    monkeypatch.setattr(cla.urllib.request, "urlopen", fake_urlopen)
    cla.request_json("GET", "/accounts")

    p.write_text('{"base_url": "http://127.0.0.1:8797", "token": "t2"}', encoding="utf-8")
    cla.request_json("GET", "/accounts")
    assert seen == ["t1", "t2"]
