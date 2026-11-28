"""Reads run-signed evidence from GitHub and checks its Sigstore signature.

Everything GitHub-facing about evidence lives here: the workflow runs and artifacts of a
governed repository, the commit tree and blobs, the live head of the signer's branch, the
attestations for a digest, and the Sigstore verification of a bundle. A call that fails, or an
answer that does not fit the expected shape, raises: nothing is guessed. The signature check
accepts only the exact signer identity of the workflow on the trusted branch (main), a build
signer digest equal to that branch's head read live at verification time, and the target's
repository and commit as the run's source. Merging into that branch is the trust act; there
is no grace for an earlier head, so a run signed by an older head is refused naming both.

The run's source commit must be the target commit, so the governed repository's caller
workflow must run on `push` (under `pull_request`, github.sha is a merge commit and every
bundle would be refused). The commit's latest run attempt of that workflow decides: the
evidence must be for exactly that attempt, and a newer attempt without evidence refuses.
"""

import asyncio
import base64
import binascii
import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable

import httpx
from cryptography import x509
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from sigstore.errors import Error as SigstoreError
from sigstore.models import Bundle
from sigstore.verify import Verifier
from sigstore.verify.policy import (
    AllOf,
    Identity,
    OIDCBuildSignerDigest,
    OIDCSourceRepositoryDigest,
    OIDCSourceRepositoryURI,
)

from src.configs.evidence_settings import SIGNER_ISSUER, EvidenceSettings
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.evidence_models import EvidenceArtifact, EvidenceRefusal

logger = get_logger()

TokenProvider = Callable[[], Awaitable[str]]
_ATTEMPTS = 3
_MAX_ARTIFACT_BYTES = 50_000_000
_TOOLS_DIGEST_LINE = re.compile(r'^\s*VERIFY_TOOLS_DIGEST:\s*"([0-9a-f]{64})"\s*$', re.MULTILINE)
_NAME = re.compile(r"^evidence-(?P<commit>[0-9a-f]{40})-(?P<attempt>[0-9]+)$")


class AttestationError(Exception):
    """GitHub refused a call, or answered in a shape Mandate does not recognise."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Object(_Record):
    sha: str
    type: str


class _Ref(_Record):
    object: _Object


class RunListing(_Record):
    id: int
    run_attempt: int
    path: str
    status: str
    conclusion: str | None
    created_at: str
    run_started_at: str | None = None


class _Runs(_Record):
    workflow_runs: list[RunListing]


class ArtifactListing(_Record):
    id: int
    name: str
    expired: bool
    created_at: str
    size_in_bytes: int


class _Artifacts(_Record):
    artifacts: list[ArtifactListing]


class _TreeItem(_Record):
    path: str
    mode: str
    type: str
    sha: str


class _Tree(_Record):
    tree: list[_TreeItem]
    truncated: bool


class _Blob(_Record):
    content: str
    encoding: str


class _Attestation(_Record):
    bundle: dict[str, object]


class _Attestations(_Record):
    attestations: list[_Attestation]


_ATTESTATIONS = TypeAdapter(_Attestations)


def newest_caller_run(runs: list[RunListing], caller_workflow: str) -> RunListing:
    """The newest run of the caller workflow for the commit; it must have finished well."""
    ours = [run for run in runs if run.path == caller_workflow]
    if not ours:
        raise EvidenceRefusal(f"no run of {caller_workflow} exists for the commit")
    run = max(ours, key=lambda r: r.run_started_at or r.created_at)
    if run.status != "completed":
        raise EvidenceRefusal(
            f"the latest run {run.id} (attempt {run.run_attempt}) has not finished"
        )
    if run.conclusion != "success":
        raise EvidenceRefusal(
            f"the latest run {run.id} (attempt {run.run_attempt}) ended {run.conclusion}"
        )
    return run


def evidence_item(items: list[ArtifactListing], commit: str, run: RunListing) -> ArtifactListing:
    """The evidence artifact of exactly the run's current attempt, or a refusal."""
    name = f"evidence-{commit}-{run.run_attempt}"
    found = [item for item in items if item.name == name and not item.expired]
    if len(found) != 1:
        raise EvidenceRefusal(
            f"the latest attempt {run.run_attempt} of run {run.id} produced no evidence ({name})"
        )
    return found[0]


_BUILD_SIGNER_DIGEST_OID = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.10")


def _signed_by_older_head(bundle: Bundle, identity: str, head: str) -> str | None:
    """The signer commit of a bundle whose workflow identity is right but whose build signer
    digest is not the branch head, or None when that is not why verification failed."""
    try:
        certificate = bundle.signing_certificate
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        uris = names.value.get_values_for_type(x509.UniformResourceIdentifier)
        raw = certificate.extensions.get_extension_for_oid(_BUILD_SIGNER_DIGEST_OID).value
        data = raw.value if isinstance(raw, x509.UnrecognizedExtension) else b""
    except (x509.ExtensionNotFound, ValueError):
        return None
    if identity not in uris or len(data) < 2 or data[0] != 0x0C:
        return None
    signed = data[2 : 2 + data[1]].decode("ascii", errors="replace")
    return signed if signed != head else None


class AttestationService(BaseInfraService):
    """GitHub's evidence, read with a token the caller supplies, and Sigstore's verdict on it."""

    def __init__(
        self,
        token_provider: TokenProvider,
        settings: EvidenceSettings | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        self._settings = settings if settings is not None else EvidenceSettings.get_instance()
        self._token_provider = token_provider
        self._client: httpx.AsyncClient | None = None
        self._verifier: Verifier | None = verifier

    @property
    def settings(self) -> EvidenceSettings:
        return self._settings

    async def initialize(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.api_url.rstrip("/"),
                timeout=self._settings.request_timeout_seconds,
                follow_redirects=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        try:
            await self.signer_head()
        except (AttestationError, EvidenceRefusal, httpx.HTTPError):
            return False
        return True

    async def signer_head(self) -> str:
        """The head commit of the signer's branch right now, read live."""
        repo = self._settings.verify_repository
        ref = _Ref.model_validate_json(
            await self._get_bytes(f"/repos/{repo}/git/ref/heads/{self._settings.signer_branch}")
        )
        if ref.object.type != "commit":
            raise AttestationError(
                f"the signer branch does not point at a commit ({ref.object.type})"
            )
        return ref.object.sha

    async def signer_tools_digest(self, signer_commit: str) -> str:
        """VERIFY_TOOLS_DIGEST as written in the signer workflow at the branch head read live."""
        repo = self._settings.verify_repository
        raw = await self._get_bytes(
            f"/repos/{repo}/contents/{self._settings.workflow_path}",
            {"ref": signer_commit},
            raw=True,
        )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AttestationError("the signer workflow is not text") from error
        found = _TOOLS_DIGEST_LINE.findall(text)
        if len(found) != 1:
            raise AttestationError("the signer workflow does not state one VERIFY_TOOLS_DIGEST")
        return found[0]

    async def latest_evidence(
        self, repository: str, commit: str, caller_workflow: str
    ) -> EvidenceArtifact:
        """The evidence of the commit's latest run attempt of the caller workflow, or a refusal."""
        runs = _Runs.model_validate_json(
            await self._get_bytes(
                f"/repos/{repository}/actions/runs", {"head_sha": commit, "per_page": 100}
            )
        )
        run = newest_caller_run(runs.workflow_runs, caller_workflow)
        listing = _Artifacts.model_validate_json(
            await self._get_bytes(
                f"/repos/{repository}/actions/runs/{run.id}/artifacts", {"per_page": 100}
            )
        )
        item = evidence_item(listing.artifacts, commit, run)
        return EvidenceArtifact(
            artifact_id=item.id,
            run_id=run.id,
            run_attempt=run.run_attempt,
            created_at=item.created_at,
            size_bytes=item.size_in_bytes,
        )

    async def download_evidence(self, repository: str, artifact: EvidenceArtifact) -> bytes:
        """The evidence tarball inside the artifact's zip, read with a byte cap."""
        if artifact.size_bytes > _MAX_ARTIFACT_BYTES:
            raise EvidenceRefusal("the evidence artifact is too large")
        archive = await self._get_capped(
            f"/repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip", _MAX_ARTIFACT_BYTES
        )
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                names = zipped.namelist()
                if names != ["evidence.tgz"]:
                    raise EvidenceRefusal(f"the evidence artifact holds {names}, not evidence.tgz")
                info = zipped.getinfo("evidence.tgz")
                if info.file_size > _MAX_ARTIFACT_BYTES:
                    raise EvidenceRefusal("the evidence tarball is too large")
                return zipped.read("evidence.tgz")
        except zipfile.BadZipFile as error:
            raise EvidenceRefusal("the evidence artifact is not a complete zip") from error

    async def tree_blobs(self, repository: str, commit: str) -> dict[str, tuple[str, str]]:
        """Every file of the commit: path to (mode, blob sha). A cut-off listing raises."""
        tree = _Tree.model_validate_json(
            await self._get_bytes(f"/repos/{repository}/git/trees/{commit}", {"recursive": "1"})
        )
        if tree.truncated:
            raise AttestationError("the commit tree is too large to list")
        return {item.path: (item.mode, item.sha) for item in tree.tree if item.type != "tree"}

    async def blob(self, repository: str, sha: str) -> bytes:
        item = _Blob.model_validate_json(
            await self._get_bytes(f"/repos/{repository}/git/blobs/{sha}")
        )
        if item.encoding != "base64":
            raise AttestationError("a blob came in an unexpected encoding")
        try:
            return base64.b64decode(item.content, validate=False)
        except binascii.Error as error:
            raise AttestationError("a blob could not be decoded") from error

    async def attestations(self, repository: str, subject_digest: str) -> list[dict[str, object]]:
        """Every attestation bundle GitHub holds for this sha256 digest (none: an empty list)."""
        path = f"/repos/{repository}/attestations/sha256:{subject_digest}"
        response = await self._send(path, None, raw=False)
        if response.status_code == 404:
            return []
        self._raise_for_status(response, path)
        try:
            return [
                item.bundle for item in _ATTESTATIONS.validate_json(response.content).attestations
            ]
        except ValidationError as error:
            raise AttestationError(f"unexpected attestations answer for {path}") from error

    async def verify_signature(
        self,
        bundle: dict[str, object],
        subject_digest: str,
        repository: str,
        commit: str,
        signer_commit: str,
    ) -> None:
        """Verify the Sigstore bundle and its subject, or raise EvidenceRefusal with the reason."""
        policy = AllOf(
            [
                Identity(identity=self._settings.signer_identity, issuer=SIGNER_ISSUER),
                OIDCBuildSignerDigest(signer_commit),
                OIDCSourceRepositoryURI(f"https://github.com/{repository}"),
                OIDCSourceRepositoryDigest(commit),
            ]
        )
        try:
            parsed = Bundle.from_json(json.dumps(bundle))
        except (SigstoreError, ValueError) as error:
            raise EvidenceRefusal(f"the Sigstore verification failed: {error}") from error
        try:
            payload = await asyncio.to_thread(self._verify_dsse, parsed, policy)
        except (SigstoreError, ValueError) as error:
            older = _signed_by_older_head(parsed, self._settings.signer_identity, signer_commit)
            if older is not None:
                shown = older if re.fullmatch(r"[0-9a-f]{40}", older) else "an unrecognised commit"
                raise EvidenceRefusal(
                    f"signed by mandate-verify {shown}, "
                    f"{self._settings.signer_branch} is now {signer_commit}"
                ) from error
            raise EvidenceRefusal(f"the Sigstore verification failed: {error}") from error
        try:
            statement = json.loads(payload)
            digests = [item["digest"]["sha256"] for item in statement["subject"]]
        except (ValueError, KeyError, TypeError) as error:
            raise EvidenceRefusal("the attestation statement has no subject digest") from error
        if digests != [subject_digest]:
            raise EvidenceRefusal("the attested subject is not the downloaded evidence")

    def _verify_dsse(self, bundle: Bundle, policy: AllOf) -> bytes:
        if self._verifier is None:
            self._verifier = Verifier.production()
        _, payload = self._verifier.verify_dsse(bundle, policy)
        return payload

    async def _get_capped(self, path: str, cap: int) -> bytes:
        """A body read in chunks and refused past the cap, so a huge answer is never held."""
        if self._client is None:
            raise AttestationError("the attestation service is not initialised")
        headers = {
            "Authorization": f"Bearer {await self._token_provider()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with self._client.stream("GET", path, headers=headers) as response:
                self._raise_for_status(response, path)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > cap:
                        raise EvidenceRefusal("the evidence download exceeds its size cap")
                return bytes(body)
        except httpx.HTTPError as error:
            raise AttestationError(f"GET {path} failed: {type(error).__name__}") from error

    async def _get_bytes(
        self, path: str, params: dict[str, int | str] | None = None, raw: bool = False
    ) -> bytes:
        response = await self._send(path, params, raw)
        self._raise_for_status(response, path)
        return response.content

    async def _send(
        self, path: str, params: dict[str, int | str] | None, raw: bool
    ) -> httpx.Response:
        if self._client is None:
            raise AttestationError("the attestation service is not initialised")
        headers = {
            "Authorization": f"Bearer {await self._token_provider()}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response: httpx.Response | None = None
        error: httpx.HTTPError | None = None
        for _ in range(_ATTEMPTS):
            try:
                response = await self._client.get(path, params=params, headers=headers)
            except httpx.HTTPError as caught:
                error = caught
                continue
            error = None
            if response.status_code < 500:
                break
        if response is None:
            raise AttestationError(f"GET {path} failed: {type(error).__name__}") from error
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, path: str) -> None:
        if not response.is_success:
            raise AttestationError(f"GET {path} answered {response.status_code}")
