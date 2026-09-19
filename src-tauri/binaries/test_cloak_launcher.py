"""cloak_launcher 的 launch_args 安全边界测试(全部离线,不启动浏览器)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cloak_launcher as cl


def test_filter_keeps_normal_args():
    args = ["--lang=zh-CN", "--window-size=1280,800", "--mute-audio"]
    allowed, reserved = cl._filter_launch_args(args)
    assert allowed == args
    assert reserved == []


def test_filter_drops_remote_debugging_family():
    allowed, reserved = cl._filter_launch_args(
        [
            "--remote-debugging-port=9999",
            "--remote-debugging-address=0.0.0.0",
            "--remote-debugging-pipe",
            "--lang=zh-CN",
        ]
    )
    assert allowed == ["--lang=zh-CN"]
    assert reserved == [
        "--remote-debugging-port=9999",
        "--remote-debugging-address=0.0.0.0",
        "--remote-debugging-pipe",
    ]


def test_filter_drops_profile_and_proxy_overrides():
    allowed, reserved = cl._filter_launch_args(
        [
            "--user-data-dir=/tmp/evil",
            "--proxy-server=http://host:8080",
            "--proxy-pac-url=http://host/pac",
            "--proxy-bypass-list=*",
            "--no-proxy-server",
            "--keep-alive",
        ]
    )
    assert allowed == ["--keep-alive"]
    assert reserved == [
        "--user-data-dir=/tmp/evil",
        "--proxy-server=http://host:8080",
        "--proxy-pac-url=http://host/pac",
        "--proxy-bypass-list=*",
        "--no-proxy-server",
    ]


def test_resolve_extensions_merges_shared_and_account_paths(monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    (shared / "extA").mkdir(parents=True)
    (shared / "extA" / "manifest.json").write_text("{}", encoding="utf-8")
    (shared / "not_an_ext").mkdir()  # 没有 manifest.json,应被跳过
    monkeypatch.setattr(cl, "GLOBAL_EXTENSIONS_DIR", shared)

    paths, remaining = cl._resolve_extensions(
        {"launch_args": ["--foo", "--load-extension=/x,/y", "--load-extension=/x"]}
    )
    assert paths == [str(shared / "extA"), "/x", "/y"]
    assert remaining == ["--foo"]


def test_resolve_extensions_without_launch_args(monkeypatch, tmp_path):
    monkeypatch.setattr(cl, "GLOBAL_EXTENSIONS_DIR", tmp_path / "missing")
    paths, remaining = cl._resolve_extensions({})
    assert paths == []
    assert remaining == []
