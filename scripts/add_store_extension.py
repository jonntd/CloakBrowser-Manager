#!/usr/bin/env python3
"""把 Chrome 网上应用店的扩展加入 CloakAccounts 的全局共享扩展目录。

商店扩展是打包的 .crx,而共享加载(--load-extension / extension_paths)需要
“解压后的文件夹”。本脚本按扩展 ID 从 Google 下载 .crx、解包到
    ~/.cloak-accounts/extensions/<name>/
之后所有账号启动时都会自动加载它。

用法:
  python add_store_extension.py <扩展ID 或 网上应用店URL> [--name 目录名]

扩展ID = 网上应用店 URL 里那串 32 位字母:
  https://chromewebstore.google.com/detail/<名称>/<扩展ID>

依赖: 仅标准库。需要能访问 clients2.google.com。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

EXT_DIR = Path.home() / ".cloak-accounts" / "extensions"
CHROME_VERSION = "145.0.0.0"  # 任意较新的版本号即可


def extract_id(s: str) -> str:
    # Chrome 扩展 ID 是 32 个 a-p 字母
    m = re.search(r"\b([a-p]{32})\b", s)
    if not m:
        m = re.search(r"([a-zA-Z0-9]{32})", s)
    if not m:
        sys.exit("无法从输入解析扩展ID(需 32 位字符,或网上应用店链接)")
    return m.group(1)


def download_crx(ext_id: str) -> bytes:
    url = (
        "https://clients2.google.com/service/update2/crx"
        f"?response=redirect&acceptformat=crx2,crx3&prodversion={CHROME_VERSION}"
        f"&x=id%3D{ext_id}%26installsource%3Dondemand%26uc"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def unpack(crx: bytes, dest: Path) -> None:
    # .crx = 头部 + 标准 zip。zipfile 从末尾的中央目录读取,通常可直接解压;
    # 兜底:定位 zip 起始魔数 PK\x03\x04 再解。
    try:
        zf = zipfile.ZipFile(io.BytesIO(crx))
    except zipfile.BadZipFile:
        i = crx.find(b"PK\x03\x04")
        if i < 0:
            sys.exit("下载内容不是有效的 crx/zip(该扩展可能不允许直接下载)")
        zf = zipfile.ZipFile(io.BytesIO(crx[i:]))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    zf.extractall(dest)
    # 只删 CRX3 验证残留的 _metadata(会被拒绝加载);
    # 保留 _locales / _platform_specific 等必需目录。
    meta = dest / "_metadata"
    if meta.is_dir():
        shutil.rmtree(meta, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="下载并解包商店扩展到全局共享目录")
    ap.add_argument("id_or_url", help="扩展ID 或 网上应用店URL")
    ap.add_argument("--name", default=None, help="全局目录下的文件夹名(默认用扩展ID)")
    args = ap.parse_args()

    ext_id = extract_id(args.id_or_url)
    dest = EXT_DIR / (args.name or ext_id)
    print(f"扩展ID: {ext_id}\n目标目录: {dest}")

    crx = download_crx(ext_id)
    print(f"已下载 .crx: {len(crx)} 字节")
    unpack(crx, dest)

    mf_path = dest / "manifest.json"
    if not mf_path.exists():
        sys.exit("❌ 解压后未找到 manifest.json(可能不是标准扩展)")
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    print(f"✅ 已加入共享扩展:{mf.get('name')}  v{mf.get('version')}  (MV{mf.get('manifest_version')})")
    print("所有账号下次启动都会加载它。")


if __name__ == "__main__":
    main()
