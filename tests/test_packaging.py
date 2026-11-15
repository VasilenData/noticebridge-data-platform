"""A nested staging residue must never be uploaded outside the manifest."""

import hashlib

import pytest

import package_site


def test_nested_unmanifested_file_refuses_packaging_without_rewriting_staged_files(
    tmp_path, monkeypatch
):
    root = tmp_path / "synthetic-project"
    web = root / "web"
    (web / "releases").mkdir(parents=True)
    for name in package_site.PUBLIC_FILES:
        (web / name).write_bytes(b"synthetic packager-only fixture: " + name.encode())
    release = b'{"synthetic_packaging_fixture":true}\n'
    (web / "releases" / (hashlib.sha256(release).hexdigest() + ".json")).write_bytes(release)

    staging = root / "site"
    (staging / "releases").mkdir(parents=True)
    residue = staging / "releases/unmanifested-notes.txt"
    residue.write_bytes(b"synthetic local notes that are not a public asset")
    existing = staging / "index.html"
    existing.write_bytes(b"existing staged index must stay unchanged on refusal")
    outside = tmp_path / "unrelated.txt"
    outside.write_bytes(b"unrelated file")
    before = {path: path.read_bytes() for path in (residue, existing, outside)}
    verified = []

    # Archive correctness is covered by operations tests. This isolates the
    # packager's independent allowlist boundary without a network/source fixture.
    monkeypatch.setattr(package_site, "ROOT", root)
    monkeypatch.setattr(
        package_site, "verify_edition", lambda data, site: verified.append((data, site))
    )
    with pytest.raises(ValueError, match="releases/unmanifested-notes.txt"):
        package_site.main()

    assert verified == [(root / "data", web)]
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (staging / "asset-manifest.json").exists()
