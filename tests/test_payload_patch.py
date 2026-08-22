from danmakufuzz.findings.payload_patch import apply_payload_patch, create_payload_patch


def test_payload_patch_roundtrip_replace_and_delete() -> None:
    base = b"abcdefghij"
    target = b"abXYefijZ"
    patch = create_payload_patch(base, target)
    rebuilt = apply_payload_patch(base, patch)
    assert rebuilt == target


def test_payload_patch_rejects_wrong_base() -> None:
    patch = create_payload_patch(b"abc", b"axc")
    try:
        apply_payload_patch(b"zzz", patch)
    except ValueError as exc:
        assert "base sha256 mismatch" in str(exc)
    else:
        raise AssertionError("expected base sha256 mismatch")


def test_payload_patch_accepts_chunked_or_legacy_data() -> None:
    patch = create_payload_patch(b"abcdef", b"abXYZf")
    hunk = patch["hunks"][0]
    chunks = hunk.pop("data_b64_chunks")
    hunk["data_b64"] = "".join(chunks)
    rebuilt = apply_payload_patch(b"abcdef", patch)
    assert rebuilt == b"abXYZf"
