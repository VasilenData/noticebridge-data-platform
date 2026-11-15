"""Stage only the known, verified static-site files for GitHub Pages."""

import hashlib
import json
import shutil
from pathlib import Path

from noticebridge.publish import verify_path

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = (
    "index.html",
    "styles.css",
    "app.js",
    "ui-utils.mjs",
    "mark.svg",
    "cover.svg",
    "data.json",
)


def main() -> None:
    verify_path(ROOT / "data/source_snapshot.json", ROOT / "web/data.json")
    target = ROOT / "site"
    target.mkdir(exist_ok=True)
    # Refuse an unexpected staging file rather than deleting a computed path.
    allowed = set(PUBLIC_FILES) | {"asset-manifest.json"}
    unexpected = [p.name for p in target.iterdir() if p.name not in allowed or not p.is_file()]
    if unexpected:
        raise ValueError(f"Unexpected files in site staging: {unexpected}")
    manifest = {}
    for name in PUBLIC_FILES:
        source = ROOT / "web" / name
        content = source.read_bytes()
        manifest[name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        shutil.copyfile(source, target / name)
    (target / "asset-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Staged {len(PUBLIC_FILES)} verified public files in {target}")


if __name__ == "__main__":
    main()
