"""add_store_extension.py 的安全边界测试(全部离线,不发网络请求)。"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import add_store_extension as ext

VALID_ID = "bhlhnicpbhignbdhedgjhgdocnmhomnp"  # 32 个 a-p 字母
MANIFEST = b'{"name":"Demo","version":"1.0","manifest_version":3}'


def _crx(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_id_accepts_url_and_id():
    assert ext.extract_id(f"https://chromewebstore.google.com/detail/foo/{VALID_ID}") == VALID_ID
    assert ext.extract_id(VALID_ID) == VALID_ID


def test_extract_id_rejects_non_chrome_charset():
    with pytest.raises(SystemExit):
        ext.extract_id("z" * 32)  # 不在 a-p 范围,旧宽松兜底会误收


@pytest.mark.parametrize("bad", ["../evil", "a/b", ".hidden", "..", "", "x" * 65])
def test_safe_dir_name_rejects_unsafe(bad):
    with pytest.raises(SystemExit):
        ext.safe_dir_name(bad, VALID_ID)


def test_safe_dir_name_defaults_to_id():
    assert ext.safe_dir_name(None, VALID_ID) == VALID_ID
    assert ext.safe_dir_name("My-Ext_1.0", VALID_ID) == "My-Ext_1.0"


def test_unpack_rejects_zip_slip(tmp_path):
    dest = tmp_path / "ext"
    with pytest.raises(SystemExit):
        ext.unpack(_crx({"../evil.txt": b"x"}), dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not dest.exists()


def test_unpack_rejects_absolute_entry(tmp_path):
    dest = tmp_path / "ext"
    with pytest.raises(SystemExit):
        ext.unpack(_crx({"/tmp/evil.txt": b"x"}), dest)
    assert not dest.exists()


def test_unpack_happy_path(tmp_path):
    dest = tmp_path / "ext"
    mf = ext.unpack(
        _crx(
            {
                "manifest.json": MANIFEST,
                "_metadata/verified_contents.json": b"{}",
                "js/background.js": b"//x",
            }
        ),
        dest,
    )
    assert mf["name"] == "Demo"
    assert (dest / "manifest.json").exists()
    assert (dest / "js" / "background.js").exists()
    assert not (dest / "_metadata").exists()


def test_unpack_keeps_old_extension_on_failure(tmp_path):
    dest = tmp_path / "ext"
    dest.mkdir()
    (dest / "manifest.json").write_text('{"name":"Old","version":"0.1","manifest_version":3}')
    with pytest.raises(SystemExit):
        ext.unpack(_crx({"readme.txt": b"not an extension"}), dest)
    assert (dest / "manifest.json").exists()
    assert "Old" in (dest / "manifest.json").read_text()
    assert not list(dest.parent.glob("*.old"))


def test_unpack_replaces_existing(tmp_path):
    dest = tmp_path / "ext"
    dest.mkdir()
    (dest / "manifest.json").write_text('{"name":"Old","version":"0.1","manifest_version":3}')
    mf = ext.unpack(_crx({"manifest.json": MANIFEST}), dest)
    assert mf["name"] == "Demo"
    assert not list(dest.parent.glob("*.old"))


def test_unpack_rejects_invalid_manifest_json(tmp_path):
    dest = tmp_path / "ext"
    with pytest.raises(SystemExit):
        ext.unpack(_crx({"manifest.json": b"{not json"}), dest)
    assert not dest.exists()
