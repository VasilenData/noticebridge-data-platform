"""Stage only the known, verified static-site files for GitHub Pages."""

import hashlib
import json
import shutil
from pathlib import Path

from noticebridge.operations import verify_edition

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = (
    "index.html",
    "styles.css",
    "app.js",
    "ui-utils.mjs",
    "mark.svg",
    "cover.svg",
    "data.json",
    "current.json",
)


def main() -> None:
    verify_edition(ROOT / "data", ROOT / "web")
    target = ROOT / "site"
    target.mkdir(exist_ok=True)
    # Refuse an unexpected staging file rather than deleting a computed path.
    manifest = {}
    releases = sorted((ROOT / "web/releases").glob("*.json"))
    for path in releases:
        if hashlib.sha256(path.read_bytes()).hexdigest() != path.stem:
            raise ValueError(f"Immutable public asset hash mismatch: {path.name}")
    public_files = [*PUBLIC_FILES, *("releases/" + p.name for p in releases)]
    allowed = set(public_files) | {"asset-manifest.json"}
    unexpected = [
        p.relative_to(target).as_posix()
        for p in target.rglob("*")
        if p.is_symlink()
        or (p.is_file() and p.relative_to(target).as_posix() not in allowed)
        or (p.is_dir() and p.relative_to(target).as_posix() != "releases")
    ]
    if unexpected:
        raise ValueError(f"Unexpected files in site staging: {unexpected}")
    for name in public_files:
        source = ROOT / "web" / name
        content = source.read_bytes()
        manifest[name] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / name)
    (target / "asset-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Staged {len(public_files)} verified public files in {target}")


if __name__ == "__main__":
    main()
