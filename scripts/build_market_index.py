"""Builds the DSH plugin market index (format 1) for dsh-ai-os.

The index is the document DSH's Discover tab reads. DSH ships no official index, so each
user adds index URLs themselves; without a public index a published npm package is
invisible to every DSH user.

The index ships inside the npm package it describes, so it needs no extra hosting.
DSH refuses redirects, so only these URLs work:

    https://cdn.jsdelivr.net/npm/dsh-ai-os/market-index.json     latest (purge after release)
    https://unpkg.com/dsh-ai-os@<version>/market-index.json      pinned

Usage:
    python scripts/build_market_index.py                 # write into the package
    python scripts/build_market_index.py --stdout        # print only

Validate before publishing:
    node scripts/validate_market_index.mjs integrations/dsh-ai-os/market-index.json \
        https://cdn.jsdelivr.net/npm/dsh-ai-os/market-index.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "integrations" / "dsh-ai-os"
REGISTRY = "https://registry.npmjs.org/"
HOMEPAGE = "https://github.com/pureheartrobotics/ai-os"
# DSH refuses redirects when it fetches an index, so the icon must be a URL that answers
# 200 directly. jsDelivr is unreachable from some networks; unpkg serves the pinned version
# without a redirect, which makes it the safer default.
CDN = "https://unpkg.com"
AUTHOR = "mr.z197009938"
# A comparator carrying a prerelease of the same triple lets `0.2.2-rc.3` satisfy the range.
DSH_RANGE = ">=0.2.2-0"


def package_manifest() -> dict:
    return json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))


def locale_meta(name: str) -> dict:
    path = PACKAGE / "locale" / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("meta", {})


def registry_document(name: str) -> dict:
    # A scoped name needs its slash escaped in the registry path; a plain one needs nothing.
    path = name.replace("/", "%2F")
    with urllib.request.urlopen(f"{REGISTRY}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def localized(text: str | None, other: str | None = None) -> dict[str, str]:
    """A LocalizedText object always carries `en`; other languages are optional."""
    result = {}
    if text:
        result["en"] = text
    if other and other != text:
        result["zh"] = other
    return result


def build() -> dict:
    """Builds the index for the version in package.json.

    The listed version must be the one this document ships inside: a reader compares the
    index's claim with what the registry serves, and a mismatch makes the entry look stale.
    Publication time comes from the registry when that version is already there, and is
    the build time while it is still being staged.
    """
    manifest = package_manifest()
    name = manifest["name"]
    latest = manifest["version"]

    registry = None
    published = None
    try:
        registry = registry_document(name)
        published = registry.get("time", {}).get(latest)
    except Exception:
        # Offline, or the version is not published yet: the manifest is the source of truth.
        registry = None

    version = (registry or {}).get("versions", {}).get(latest) or manifest

    en = locale_meta("en")
    zh = locale_meta("zh")

    stamp = (
        int(datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp())
        if published
        else int(time.time())
    )

    keywords = [k for k in version.get("keywords", []) if isinstance(k, str)]
    icon_path = (version.get("icon") or manifest.get("icon") or "icon.svg").lstrip("./")

    return {
        "format": 1,
        "title": localized("AI OS plugins", "AI OS 插件"),
        "description": localized(
            "Voice control for the Windows desktop, published as DSH bundles.",
            "Windows 桌面语音操作，以 DSH 插件形式发布。",
        ),
        "metadata": {
            "categories": {
                "computer-use": {"title": localized("Computer use", "电脑操作")},
                "voice": {"title": localized("Voice", "语音")},
            },
            "labels": {
                "windows": {"title": localized("Windows")},
                "mcp": {"title": localized("MCP tools", "MCP 工具")},
                "hands-free": {"title": localized("Hands-free", "免手操作")},
            },
            "sortKeys": {
                "published": {"title": localized("Published", "发布时间"), "order": "desc"},
            },
        },
        "plugins": [
            {
                "name": name,
                "title": localized(en.get("title"), zh.get("title")),
                "description": localized(en.get("description"), zh.get("description")),
                "icon": f"{CDN}/{name}@{latest}/{icon_path}",
                "author": AUTHOR,
                "homepage": HOMEPAGE,
                "metadata": {
                    "category": "computer-use",
                    "keywords": keywords,
                    "labels": ["windows", "mcp", "hands-free"],
                    "sortKeys": {"published": stamp},
                },
                "versions": [
                    {
                        "version": latest,
                        "publishTimestamp": stamp,
                        "source": {"type": "npm", "registry": REGISTRY},
                        "engines": {"dsh": DSH_RANGE},
                    }
                ],
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument(
        "--out",
        default=str(PACKAGE / "market-index.json"),
        help="where to write the index (default: inside the package, so npm CDNs serve it)",
    )
    args = parser.parse_args()

    index = build()
    text = json.dumps(index, ensure_ascii=False, indent=2) + "\n"

    if args.stdout:
        sys.stdout.write(text)
        return 0

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
