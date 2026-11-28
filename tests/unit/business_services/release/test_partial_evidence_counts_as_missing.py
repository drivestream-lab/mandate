"""Partial, truncated, padded or inconsistent evidence counts as missing.

These are the conditions a signed run cannot produce (the signer always writes a complete
bundle), so they are tested through the pure functions that decide them.
"""

import hashlib
import io
import json
import tarfile

import pytest

from src.business_services.release.evidence_verification_service import (
    check_binding,
    digest_inputs_text,
    digest_paths,
    read_bundle,
    sha256_hex,
)
from src.models.evidence_models import (
    BUNDLE_FILES,
    EvidenceArtifact,
    EvidenceRefusal,
    EvidenceTarget,
)

COMMIT = "a" * 40
TARGET = EvidenceTarget(
    repository="o/r",
    commit=COMMIT,
    caller_workflow=".github/workflows/verify.yml",
    test_set=("tests/unit",),
    expected_test_set_digest="1" * 64,
)
ARTIFACT = EvidenceArtifact(
    artifact_id=1, run_id=7, run_attempt=1, created_at="2026-11-28T00:00:00Z", size_bytes=10
)


def _files(**changes: str | None) -> dict[str, bytes]:
    collected = "tests/unit/test_a.py::test_one\ntests/unit/test_a.py::test_two\n"
    files = {
        "report.json": json.dumps(
            {
                "result": "pass", "tests": 2, "failures": 0, "errors": 0, "skipped": 0,
                "pytest_exit_code": 0, "collect_exit_code": 0, "collected": 2, "deselected": 0,
            }
        ),
        "environment.json": json.dumps(
            {
                "runner_image": "ubuntu24 1", "os": "linux", "python": "3.12.8",
                "packages": ["pytest==8.3.5"], "packages_sha256": "0" * 64,
            }
        ),
        "junit.xml": "<testsuite/>",
        "collected.txt": collected,
        "digest-inputs.txt": "x",
    }  # fmt: skip
    files.update({k: v for k, v in changes.items() if v is not None})
    hashed = {name: sha256_hex(data.encode()) for name, data in files.items()}
    binding = {
        "repository": "o/r", "commit": COMMIT, "caller_sha": COMMIT, "run_id": "7",
        "run_attempt": "1", "test_set": ["tests/unit"], "test_set_digest": "1" * 64,
        "dependencies_digest": "2" * 64, "tools_digest": "3" * 64,
        "collected_digest": sha256_hex(
            "".join(f"{c}\n" for c in sorted(collected.split("\n")[:2])).encode()
        ),
        "quarantine": [], "plugins": [], "result": "pass", "artifacts": hashed,
    }  # fmt: skip
    files["binding.json"] = json.dumps(binding)
    return {name: data.encode() for name, data in files.items()}


def _tar(files: dict[str, bytes], drop: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            if name in drop:
                continue
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.mark.req("REQ-62")
@pytest.mark.parametrize("missing", ["binding.json", "report.json", "environment.json"])
def test_a_missing_file_is_partial_evidence(missing: str) -> None:
    with pytest.raises(EvidenceRefusal, match="partial"):
        read_bundle(_tar(_files(), drop=(missing,)))


@pytest.mark.req("REQ-62")
def test_a_truncated_tarball_is_refused() -> None:
    whole = _tar(_files())
    with pytest.raises(EvidenceRefusal, match="truncated"):
        read_bundle(whole[: len(whole) // 2])


@pytest.mark.req("REQ-62")
def test_a_file_that_differs_from_its_hash_is_refused() -> None:
    files = _files()
    files["report.json"] = files["report.json"].replace(b'"tests": 2', b'"tests": 9')
    with pytest.raises(EvidenceRefusal, match="hash"):
        read_bundle(_tar(files))


@pytest.mark.req("REQ-62")
def test_an_extra_file_is_refused() -> None:
    files = _files()
    files["extra.txt"] = b"x"
    with pytest.raises(EvidenceRefusal, match="unexpected entry"):
        read_bundle(_tar(files))


@pytest.mark.req("REQ-61")
def test_the_six_files_of_a_complete_bundle_are_read() -> None:
    bundle, files = read_bundle(_tar(_files()))
    assert set(files) == set(BUNDLE_FILES)
    assert bundle.report.tests == 2


@pytest.mark.req("REQ-61")
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("commit", "b" * 40, "another commit"),
        ("repository", "o/other", "another repository"),
        ("quarantine", ["tests/unit/test_a.py::test_one"], "quarantine"),
        ("tools_digest", "4" * 64, "tools digest"),
        ("test_set_digest", "5" * 64, "fixed at spec sign-off"),
    ],
)
def test_evidence_that_does_not_match_the_target_is_refused(
    field: str, value: object, reason: str
) -> None:
    files = _files()
    binding = json.loads(files["binding.json"])
    binding[field] = value
    if field == "commit":
        binding["caller_sha"] = value
    files["binding.json"] = json.dumps(binding).encode()
    bundle, _ = read_bundle(_tar(files))
    with pytest.raises(EvidenceRefusal, match=reason):
        check_binding(bundle, TARGET, "1" * 64, "3" * 64, ARTIFACT)


@pytest.mark.req("REQ-61")
def test_a_failing_report_is_refused() -> None:
    files = _files()
    report = json.loads(files["report.json"])
    report.update(result="fail", failures=1)
    files["report.json"] = json.dumps(report).encode()
    binding = json.loads(files["binding.json"])
    binding["artifacts"]["report.json"] = sha256_hex(files["report.json"])
    files["binding.json"] = json.dumps(binding).encode()
    bundle, _ = read_bundle(_tar(files))
    with pytest.raises(EvidenceRefusal, match="did not pass"):
        check_binding(bundle, TARGET, "1" * 64, "3" * 64, ARTIFACT)


@pytest.mark.req("REQ-108")
def test_the_test_set_digest_follows_the_documented_format() -> None:
    tree = [
        "conftest.py",
        "tests/conftest.py",
        "tests/unit/a.py",
        "tests/unit/sub/b.py",
        "src/x.py",
    ]
    assert digest_paths(tree, ["tests/unit"]) == [
        "conftest.py", "tests/conftest.py", "tests/unit/a.py", "tests/unit/sub/b.py",
    ]  # fmt: skip
    text = digest_inputs_text({"b.py": b"B", "a.py": b"A"}, ["pytest_asyncio"])
    expected = (
        f"{hashlib.sha256(b'A').hexdigest()}  a.py\n"
        f"{hashlib.sha256(b'B').hexdigest()}  b.py\n"
        "plugin:pytest_asyncio\n"
    )
    assert text == expected
