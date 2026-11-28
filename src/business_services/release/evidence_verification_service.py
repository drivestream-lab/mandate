"""Decides whether evidence for a commit is run-signed, complete and for the right test set.

Mandate accepts evidence only when every check below holds; any failure is a hard refusal
that names its reason, and refused evidence counts as missing:

- the Sigstore bundle verifies, the signer is exactly the signer workflow on the trusted
  branch (main), the build signer digest equals that branch's head read live once for this
  verification (no grace for an earlier head: "signed by mandate-verify <sha>, main is now
  <sha>"), and the run's source repository and commit are the target's;
- the attested subject is the sha256 of the evidence tarball that was downloaded;
- the tarball holds exactly the six bundle files, each as hashed in binding.json, and the
  binding, report and environment manifest are for the target commit and consistent;
- the binding's protected test-set digest equals the digest fixed at spec sign-off, which the
  caller supplies in the target (the recorded spec signoff), and also the digest Mandate
  recomputes from git at that commit in the format the signer's README documents; the tools
  digest equals the signer workflow's VERIFY_TOOLS_DIGEST at that head; the
  quarantine, test set and plugins are the target's;
- the result is pass, and the evidence is for exactly the latest run attempt of the caller
  workflow for the commit (a newer attempt without evidence, or one that failed, refuses).

worktree_clean_advisory is deliberately not read. The pure checks are module functions so
they can be tested without GitHub; the class reads GitHub and the signature through the
attestation service.
"""

import hashlib
import io
import tarfile
from collections.abc import Mapping, Sequence

from injector import inject
from pydantic import ValidationError

from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.attestation_service import AttestationError, AttestationService
from src.models.evidence_models import (
    BUNDLE_FILES,
    EvidenceArtifact,
    EvidenceBinding,
    EvidenceBundle,
    EvidenceEnvironment,
    EvidenceRefusal,
    EvidenceReport,
    EvidenceTarget,
    VerifiedEvidence,
)

_MAX_MEMBER_BYTES = 20_000_000
_FILE_MODES = ("100644", "100755")
_ROOT_CONFTEST = "conftest.py"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_paths(tree_paths: Sequence[str], test_set: Sequence[str]) -> list[str]:
    """The tracked files the test-set digest covers: every blob under a test-set path, plus the
    conftest.py at the root and in every directory above a test-set path. Sorted by path bytes."""
    chosen: set[str] = set()
    for token in test_set:
        token = token.strip("/")
        chosen |= {p for p in tree_paths if p == token or p.startswith(token + "/")}
    directories = {""}
    for token in test_set:
        parts = token.strip("/").split("/")
        directories |= {"/".join(parts[:i]) for i in range(1, len(parts))}
    tracked = set(tree_paths)
    for directory in directories:
        conftest = f"{directory}/{_ROOT_CONFTEST}" if directory else _ROOT_CONFTEST
        if conftest in tracked:
            chosen.add(conftest)
    return sorted(chosen, key=lambda path: path.encode("utf-8"))


def digest_inputs_text(contents: Mapping[str, bytes], plugins: Sequence[str]) -> str:
    """The exact text the signer hashes: `<sha256 of content>  <path>` per file in path-byte
    order, then `plugin:<name>` per plugin, sorted, each line ending in a newline."""
    lines = [
        f"{sha256_hex(contents[path])}  {path}\n"
        for path in sorted(contents, key=lambda p: p.encode("utf-8"))
    ]
    lines += [f"plugin:{name}\n" for name in sorted(plugins)]
    return "".join(lines)


def read_bundle(tarball: bytes) -> tuple[EvidenceBundle, Mapping[str, bytes]]:
    """Open the evidence tarball strictly. Truncated, partial, padded or inconsistent evidence
    is refused; the six files and their hashes in binding.json must all be present and agree."""
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            for member in archive:
                if not member.isreg() or member.name in files or member.name not in BUNDLE_FILES:
                    raise EvidenceRefusal(
                        f"unexpected entry in the evidence tarball: {member.name}"
                    )
                if member.size > _MAX_MEMBER_BYTES:
                    raise EvidenceRefusal(f"{member.name} is too large")
                handle = archive.extractfile(member)
                if handle is None:
                    raise EvidenceRefusal(f"{member.name} cannot be read")
                files[member.name] = handle.read()
    except (tarfile.TarError, EOFError, OSError) as error:
        raise EvidenceRefusal(
            f"the evidence tarball is truncated or unreadable: {error}"
        ) from error
    missing = [name for name in BUNDLE_FILES if name not in files]
    if missing:
        raise EvidenceRefusal(f"the evidence is partial; missing {', '.join(missing)}")
    try:
        binding = EvidenceBinding.model_validate_json(files["binding.json"])
        report = EvidenceReport.model_validate_json(files["report.json"])
        environment = EvidenceEnvironment.model_validate_json(files["environment.json"])
    except ValidationError as error:
        raise EvidenceRefusal(
            f"a bundle file is incomplete or malformed: {error.errors()[0]}"
        ) from error
    hashed = {name for name in BUNDLE_FILES if name != "binding.json"}
    if set(binding.artifacts) != hashed:
        raise EvidenceRefusal("binding.json does not hash every other bundle file")
    for name in sorted(hashed):
        if binding.artifacts[name] != sha256_hex(files[name]):
            raise EvidenceRefusal(f"{name} does not match its hash in binding.json")
    if not environment.packages or not environment.runner_image or not environment.python:
        raise EvidenceRefusal("the environment manifest is empty")
    collected = tuple(line for line in files["collected.txt"].decode("utf-8").split("\n") if line)
    if (
        sha256_hex("".join(f"{c}\n" for c in sorted(collected)).encode())
        != binding.collected_digest
    ):
        raise EvidenceRefusal("collected.txt does not match the collected digest")
    return (
        EvidenceBundle(
            binding=binding, report=report, environment=environment, collected=collected
        ),
        files,
    )


def check_binding(
    bundle: EvidenceBundle,
    target: EvidenceTarget,
    recomputed_test_set_digest: str,
    expected_tools_digest: str,
    artifact: EvidenceArtifact,
) -> None:
    """Compare what the signed run says with what Mandate expects; raise on the first mismatch."""
    binding, report = bundle.binding, bundle.report
    if binding.repository != target.repository:
        raise EvidenceRefusal("the evidence is for another repository")
    if binding.commit != target.commit or binding.caller_sha != target.commit:
        raise EvidenceRefusal("the evidence is for another commit")
    if binding.result != "pass" or report.result != "pass":
        raise EvidenceRefusal(f"the protected test set did not pass ({report.result})")
    if report.failures or report.errors or report.skipped or report.tests <= 0:
        raise EvidenceRefusal("the report shows failures, errors, skips or no tests")
    if report.pytest_exit_code != 0 or report.collect_exit_code != 0:
        raise EvidenceRefusal("pytest or its collection exited with an error")
    if report.tests != len(bundle.collected) - len(binding.quarantine):
        raise EvidenceRefusal("the tests that ran are not the collected tests less the quarantine")
    if binding.test_set != list(target.test_set) or binding.plugins != list(target.plugins):
        raise EvidenceRefusal("the run used another test set or other plugins")
    if binding.quarantine != list(target.quarantine):
        raise EvidenceRefusal("the quarantine list differs from the one on record")
    if binding.test_set_digest != target.expected_test_set_digest:
        raise EvidenceRefusal("the test-set digest differs from the one fixed at spec sign-off")
    if binding.test_set_digest != recomputed_test_set_digest:
        raise EvidenceRefusal("the protected test-set digest differs from the one recomputed")
    if binding.tools_digest != expected_tools_digest:
        raise EvidenceRefusal("the tools digest differs from the signer workflow's constant")
    if binding.run_id != str(artifact.run_id) or binding.run_attempt != str(artifact.run_attempt):
        raise EvidenceRefusal("the binding is for another run or attempt than the artifact")


class EvidenceVerificationService(BaseBusinessService):
    """Accepts evidence for a commit or refuses it with a reason."""

    @inject
    def __init__(self, attestations: AttestationService) -> None:
        super().__init__()
        self._attestations = attestations

    async def verify(self, target: EvidenceTarget) -> VerifiedEvidence:
        """Fetch the latest evidence for the commit and verify it."""
        try:
            artifact = await self._attestations.latest_evidence(
                target.repository, target.commit, target.caller_workflow
            )
            tarball = await self._attestations.download_evidence(target.repository, artifact)
        except (AttestationError, ValidationError) as error:
            raise EvidenceRefusal(f"the evidence could not be fetched: {error}") from error
        return await self.verify_bytes(target, tarball, artifact)

    async def verify_bytes(
        self, target: EvidenceTarget, tarball: bytes, artifact: EvidenceArtifact
    ) -> VerifiedEvidence:
        """Verify this tarball (the downloaded bytes) against the target and its artifact."""
        try:
            return await self._verify(target, tarball, artifact)
        except (AttestationError, ValidationError) as error:
            raise EvidenceRefusal(f"the evidence could not be checked: {error}") from error

    async def test_set_digest_at(
        self, repository: str, commit: str, test_set: Sequence[str], plugins: Sequence[str]
    ) -> str:
        """The protected test-set digest of a commit, recomputed from git in the signer's format.

        The recorded spec signoff is the source of the digest a target expects; this is how a
        digest is computed from a commit (and how Mandate checks the commit under test)."""
        service = self._attestations
        tree = await service.tree_blobs(repository, commit)
        paths = digest_paths(list(tree), test_set)
        if not paths:
            raise EvidenceRefusal("the test set matches no tracked file")
        contents: dict[str, bytes] = {}
        for path in paths:
            mode, sha = tree[path]
            if mode not in _FILE_MODES:
                raise EvidenceRefusal(f"{path} is not a regular file")
            contents[path] = await service.blob(repository, sha)
        return sha256_hex(digest_inputs_text(contents, plugins).encode("utf-8"))

    async def _verify(
        self, target: EvidenceTarget, tarball: bytes, artifact: EvidenceArtifact
    ) -> VerifiedEvidence:
        service = self._attestations
        digest = sha256_hex(tarball)
        signer_commit = await service.signer_head()
        bundles = await service.attestations(target.repository, digest)
        if not bundles:
            raise EvidenceRefusal("no attestation exists for the downloaded evidence")
        failures: list[str] = []
        for candidate in bundles:
            try:
                await service.verify_signature(
                    candidate, digest, target.repository, target.commit, signer_commit
                )
                break
            except EvidenceRefusal as refusal:
                failures.append(refusal.reason)
        else:
            raise EvidenceRefusal(failures[0])
        bundle, _ = read_bundle(tarball)
        recomputed = await self.test_set_digest_at(
            target.repository, target.commit, target.test_set, target.plugins
        )
        expected_tools = await service.signer_tools_digest(signer_commit)
        check_binding(bundle, target, recomputed, expected_tools, artifact)
        binding = bundle.binding
        return VerifiedEvidence(
            repository=target.repository,
            commit=target.commit,
            run_id=int(binding.run_id),
            run_attempt=int(binding.run_attempt),
            tests=bundle.report.tests,
            test_set_digest=binding.test_set_digest,
            tools_digest=binding.tools_digest,
            dependencies_digest=binding.dependencies_digest,
            signer_identity=service.settings.signer_identity,
            signer_digest=signer_commit,
        )
