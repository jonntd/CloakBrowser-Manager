#!/usr/bin/env python3
"""把 Chrome 网上应用店的扩展加入 CloakAccounts 的全局共享扩展目录。

商店扩展是打包的 .crx,而共享加载(--load-extension / extension_paths)需要
“解压后的文件夹”。本脚本按扩展 ID 从 Google 下载 .crx、解包到
    ~/.cloak-accounts/extensions/<name>/
之后所有账号启动时都会自动加载它。

用法:
  python add_store_extension.py <扩展ID 或 网上应用店URL> [--name 目录名]

扩展ID = 网上应用店 URL 里那串 32 位 a-p 字母:
  https://chromewebstore.google.com/detail/<名称>/<扩展ID>

安全边界:
  - 只接受严格格式的 Chrome 扩展 ID(32 位 a-p 字母),不做宽松兜底。
  - --name 只允许安全目录名字符,防止把内容写到扩展目录之外。
  - 下载按分块读取并有大小上限;zip 逐条目校验解压路径,拒绝 Zip Slip。
  - 先解压到临时目录并校验 manifest.json,成功后才原子替换旧目录;
    失败时保留旧扩展。

依赖: 仅标准库。需要能访问 clients2.google.com。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

EXT_DIR = Path.home() / ".cloak-accounts" / "extensions"
CHROME_VERSION = "145.0.0.0"  # 任意较新的版本号即可
MAX_CRX_BYTES = 100 * 1024 * 1024  # 商店扩展下载上限
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
CHROME_ID = re.compile(r"\b[a-p]{32}\b")


def extract_id(s: str) -> str:
    # Chrome 扩展 ID 恰好是 32 个 a-p 字母;不收任意 32 位字母数字串。
    m = CHROME_ID.search(s)
    if not m:
        sys.exit("无法从输入解析扩展ID(需 32 位 a-p 字母,或网上应用店链接)")
    return m.group(0)


def safe_dir_name(name: str | None, ext_id: str) -> str:
    """目录名只允许安全字符,防止 --name 写到 EXT_DIR 之外。"""
    if name is None:
        return ext_id
    if not SAFE_NAME.fullmatch(name) or name.startswith("."):
        sys.exit("--name 只能是 1-64 位字母/数字/点/下划线/连字符,且不能以点开头")
    return name


def download_crx(ext_id: str) -> bytes:
    url = (
        "https://clients2.google.com/service/update2/crx"
        f"?response=redirect&acceptformat=crx2,crx3&prodversion={CHROME_VERSION}"
        f"&x=id%3D{ext_id}%26installsource%3Dondemand%26uc"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    chunks: list[bytes] = []
    total = 0
    with urllib.request.urlopen(req, timeout=60) as r:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_CRX_BYTES:
                sys.exit(f"下载内容超过 {MAX_CRX_BYTES // (1024 * 1024)} MiB 上限,已中止")
            chunks.append(chunk)
    return b"".join(chunks)


def _open_crx_zip(crx: bytes) -> zipfile.ZipFile:
    # .crx = 头部 + 标准 zip。zipfile 从末尾的中央目录读取,通常可直接解压;
    # 兜底:定位 zip 起始魔数 PK\x03\x04 再解。
    try:
        return zipfile.ZipFile(io.BytesIO(crx))
    except zipfile.BadZipFile:
        i = crx.find(b"PK\x03\x04")
        if i < 0:
            sys.exit("下载内容不是有效的 crx/zip(该扩展可能不允许直接下载)")
        return zipfile.ZipFile(io.BytesIO(crx[i:]))


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _extract_safely(zf: zipfile.ZipFile, dest: Path) -> None:
    """逐条目解压并校验 containment,拒绝 Zip Slip 和绝对路径;条目一律按
    普通文件落盘,zip 里的 symlink 位不会生效。"""
    dest_resolved = dest.resolve()
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            sys.exit(f"zip 条目路径越界,拒绝解压: {info.filename}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def unpack(crx: bytes, dest: Path) -> dict:
    """解压到临时目录,校验 manifest 后原子替换 dest;失败时保留旧目录。"""
    zf = _open_crx_zip(crx)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        staged = Path(tmp) / "ext"
        _extract_safely(zf, staged)
        mf_path = staged / "manifest.json"
        if not mf_path.exists():
            sys.exit("❌ 解压后未找到 manifest.json(可能不是标准扩展)")
        try:
            mf = json.loads(mf_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            sys.exit(f"❌ manifest.json 不是有效的 JSON: {exc}")
        # 只删 CRX3 验证残留的 _metadata(会被拒绝加载);
        # 保留 _locales / _platform_specific 等必需目录。
        meta = staged / "_metadata"
        if meta.is_dir():
            shutil.rmtree(meta, ignore_errors=True)

        backup = dest.with_name(dest.name + ".old")
        _remove(backup)
        had_old = dest.exists() or dest.is_symlink()
        if had_old:
            os.replace(dest, backup)
        try:
            os.replace(staged, dest)
        except OSError:
            if had_old:
                os.replace(backup, dest)
            raise
        if had_old:
            _remove(backup)
    return mf


def main() -> None:
    ap = argparse.ArgumentParser(description="下载并解包商店扩展到全局共享目录")
    ap.add_argument("id_or_url", help="扩展ID 或 网上应用店URL")
    ap.add_argument("--name", default=None, help="全局目录下的文件夹名(默认用扩展ID)")
    args = ap.parse_args()

    ext_id = extract_id(args.id_or_url)
    dest = EXT_DIR / safe_dir_name(args.name, ext_id)
    print(f"扩展ID: {ext_id}\n目标目录: {dest}")

    crx = download_crx(ext_id)
    print(f"已下载 .crx: {len(crx)} 字节")
    mf = unpack(crx, dest)
    print(f"✅ 已加入共享扩展:{mf.get('name')}  v{mf.get('version')}  (MV{mf.get('manifest_version')})")
    print("所有账号下次启动都会加载它。")


if __name__ == "__main__":
    main()
