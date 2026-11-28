"""Reads run-signed evidence from GitHub and checks its Sigstore signature.

Everything GitHub-facing about evidence lives here: the workflow runs and artifacts of a
governed repository, the commit tree and blobs, the live commit of the signer's tag, the
attestations for a digest, and the Sigstore verification of a bundle. A call that fails, or an
answer that does not fit the expected shape, raises: nothing is guessed. The signature check
accepts only the exact signer identity of the pinned workflow, a build signer digest equal to
the tag's commit, and the target's repository and commit as the run's source.
"""

import asyncio
import base64
import io
import json
import re
import zipfile
from collections.abc import Awaitable, Callable

import httpx
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


class _Run(_Record):
    id: int


class _Runs(_Record):
    workflow_runs: list[_Run]


class _ArtifactItem(_Record):
    id: int
    name: str
    expired: bool
    created_at: str


class _Artifacts(_Record):
    artifacts: list[_ArtifactItem]


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


class AttestationService(BaseInfraService):
    """GitHub's evidence, read with a token the caller supplies, and Sigstore's verdict on it."""

    def __init__(
        self, token_provider: TokenProvider, settings: EvidenceSettings | None = None
    ) -> None:
        self._settings = settings if settings is not None else EvidenceSettings.get_instance()
        self._token_provider = token_provider
        self._client: httpx.AsyncClient | None = None
        self._verifier: Verifier | None = None

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
            await self.signer_commit()
        except (AttestationError, EvidenceRefusal, httpx.HTTPError):
            return False
        return True

    async def signer_commit(self) -> str:
        """The commit the signer's tag points at right now, read live (a moved tag changes it)."""
        repo = self._settings.verify_repository
        ref = _Ref.model_validate_json(
            await self._get_bytes(f"/repos/{repo}/git/ref/tags/{self._settings.signer_tag}")
        )
        sha, kind = ref.object.sha, ref.object.type
        if kind == "tag":
            tag = _Ref.model_validate_json(await self._get_bytes(f"/repos/{repo}/git/tags/{sha}"))
            sha, kind = tag.object.sha, tag.object.type
        if kind != "commit":
            raise AttestationError(f"the signer tag does not point at a commit ({kind})")
        return sha

    async def signer_tools_digest(self, signer_commit: str) -> str:
        """VERIFY_TOOLS_DIGEST as written in the signer workflow at the tag's commit."""
        repo = self._settings.verify_repository
        text = (
            await self._get_bytes(
                f"/repos/{repo}/contents/{self._settings.workflow_path}",
                {"ref": signer_commit},
                raw=True,
            )
        ).decode("utf-8")
        found = _TOOLS_DIGEST_LINE.findall(text)
        if len(found) != 1:
            raise AttestationError("the signer workflow does not state one VERIFY_TOOLS_DIGEST")
        return found[0]

    async def latest_evidence(self, repository: str, commit: str) -> EvidenceArtifact | None:
        """The newest evidence artifact any run of this commit produced, or None."""
        runs = _Runs.model_validate_json(
            await self._get_bytes(
                f"/repos/{repository}/actions/runs", {"head_sha": commit, "per_page": 100}
            )
        )
        newest: EvidenceArtifact | None = None
        for run in runs.workflow_runs:
            listing = _Artifacts.model_validate_json(
                await self._get_bytes(
                    f"/repos/{repository}/actions/runs/{run.id}/artifacts", {"per_page": 100}
                )
            )
            for item in listing.artifacts:
                match = _NAME.fullmatch(item.name)
                if item.expired or match is None or match["commit"] != commit:
                    continue
                candidate = EvidenceArtifact(
                    artifact_id=item.id,
                    run_id=run.id,
                    run_attempt=int(match["attempt"]),
                    created_at=item.created_at,
                )
                if newest is None or candidate.created_at > newest.created_at:
                    newest = candidate
        return newest

    async def download_evidence(self, repository: str, artifact: EvidenceArtifact) -> bytes:
        """The evidence tarball inside the artifact's zip."""
        archive = await self._get_bytes(
            f"/repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip"
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
        return base64.b64decode(item.content)

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
            payload = await asyncio.to_thread(self._verify_dsse, parsed, policy)
        except (SigstoreError, ValueError) as error:
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
