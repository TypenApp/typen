"""
Independent Language Resource Update Manager.
Supports:
- Ed25519 manifest signature verification.
- SHA-256 package digest verification.
- Zstandard (.tar.zst) full and dictionary delta patch application.
- Safe extraction into a staging directory.
- Pre-flight smoke validation via `ResourceManager.load_bundle_from_dir`.
- Atomic installation pointer swap (`os.replace`) and automatic rollback
  to `last_known_good` or bundled baseline if any step fails.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import zstandard as zstd
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from autocorrect.intelligence.resource_manager import ResourceManager
from autocorrect.updates.update_policy import UpdateEligibilityResult, UpdatePolicyEngine
from pipeline.sign_release import verify_manifest_signature


@dataclass(frozen=True, slots=True)
class ResourceUpdateDescriptor:
    """Signed remote update manifest for a language intelligence bundle."""

    version: str
    schema_version: int
    released_at: str
    full_archive_sha256: str
    full_archive_size: int
    delta_from_version: str | None = None
    delta_patch_sha256: str | None = None
    delta_patch_size: int | None = None

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "schema_version": self.schema_version,
            "released_at": self.released_at,
            "full_archive_sha256": self.full_archive_sha256,
            "full_archive_size": self.full_archive_size,
            "delta_from_version": self.delta_from_version,
            "delta_patch_sha256": self.delta_patch_sha256,
            "delta_patch_size": self.delta_patch_size,
        }


class LanguageResourceUpdater:
    """
    Manages safe, atomic, offline-resilient updates of the Global Language Intelligence Library.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        user_resources_dir: Path,
        public_key: Ed25519PublicKey,
    ) -> None:
        self._resource_manager = resource_manager
        self._user_resources_dir = user_resources_dir
        self._public_key = public_key
        self._staging_dir = user_resources_dir / "staging"
        self._versions_dir = user_resources_dir / "versions"
        self._active_ptr_path = user_resources_dir / "active_version.json"

    def verify_signed_descriptor(
        self,
        descriptor: ResourceUpdateDescriptor,
        signature_b64: str,
    ) -> bool:
        """Verify the Ed25519 signature of the update manifest descriptor."""
        return verify_manifest_signature(
            descriptor.to_canonical_dict(), signature_b64, self._public_key
        )

    def check_eligibility(
        self,
        descriptor: ResourceUpdateDescriptor,
        signature_b64: str,
        updates_expire_at: datetime | None = None,
    ) -> UpdateEligibilityResult:
        if not self.verify_signed_descriptor(descriptor, signature_b64):
            return UpdateEligibilityResult(
                eligible=False,
                reason="Invalid Ed25519 manifest signature",
            )
        current_ver = self._resource_manager.active_bundle.version
        return UpdatePolicyEngine.check_resource_update_eligibility(
            current_version=current_ver,
            remote_version=descriptor.version,
            remote_schema_version=descriptor.schema_version,
            remote_released_at_iso=descriptor.released_at,
            updates_expire_at=updates_expire_at,
        )

    def install_from_archive_bytes(
        self,
        descriptor: ResourceUpdateDescriptor,
        signature_b64: str,
        archive_or_patch_bytes: bytes,
        is_delta_patch: bool = False,
        base_archive_bytes: bytes | None = None,
        updates_expire_at: datetime | None = None,
    ) -> bool:
        """
        Verify signature, eligibility, and SHA-256 digest; apply delta or full archive
        into staging; validate binary integrity; and atomically hot-swap the active bundle.
        """
        eligibility = self.check_eligibility(
            descriptor, signature_b64, updates_expire_at=updates_expire_at
        )
        if not eligibility.eligible:
            raise PermissionError(f"Resource update rejected: {eligibility.reason}")

        if is_delta_patch:
            if not descriptor.delta_patch_sha256 or base_archive_bytes is None:
                raise ValueError("Missing delta patch metadata or base archive bytes")
            actual_patch_hash = hashlib.sha256(archive_or_patch_bytes).hexdigest()
            if actual_patch_hash != descriptor.delta_patch_sha256:
                raise ValueError("Corrupted delta patch: SHA-256 mismatch")

            dict_data = zstd.ZstdCompressionDict(
                base_archive_bytes, dict_type=zstd.DICT_TYPE_RAWCONTENT
            )
            decompressor = zstd.ZstdDecompressor(dict_data=dict_data)
            full_archive_bytes = decompressor.decompress(
                archive_or_patch_bytes, max_output_size=descriptor.full_archive_size + 1024 * 1024
            )
        else:
            full_archive_bytes = archive_or_patch_bytes

        # Verify full archive SHA-256 digest
        actual_full_hash = hashlib.sha256(full_archive_bytes).hexdigest()
        if actual_full_hash != descriptor.full_archive_sha256:
            raise ValueError(
                f"Corrupted resource archive: expected {descriptor.full_archive_sha256}, got {actual_full_hash}"
            )

        # Clean staging directory and extract safely
        if self._staging_dir.exists():
            shutil.rmtree(self._staging_dir)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            dctx = zstd.ZstdDecompressor()
            tar_bytes = dctx.decompress(full_archive_bytes)
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
                for member in tar.getmembers():
                    # Path traversal & executable file security guard
                    if member.name.startswith("/") or ".." in Path(member.name).parts:
                        raise SecurityError(f"Unsafe path in resource archive: {member.name}")
                    if member.name.endswith((".exe", ".dll", ".so", ".dylib", ".py", ".sh", ".bat")):
                        raise SecurityError(
                            f"Executable code forbidden in language resource package: {member.name}"
                        )
                tar.extractall(path=self._staging_dir, filter="data")

            # Verify per-file artifact hashes in extracted manifest.json
            extracted_manifest = json.loads(
                (self._staging_dir / "manifest.json").read_text(encoding="utf-8")
            )
            for fname, expected_sha in extracted_manifest.get("artifacts", {}).items():
                fpath = self._staging_dir / fname
                if not fpath.exists():
                    raise FileNotFoundError(f"Missing required artifact in bundle: {fname}")
                if hashlib.sha256(fpath.read_bytes()).hexdigest() != expected_sha:
                    raise ValueError(f"Artifact checksum mismatch for {fname}")

            # Move staging to versioned immutable directory
            self._versions_dir.mkdir(parents=True, exist_ok=True)
            target_version_dir = self._versions_dir / descriptor.version
            if target_version_dir.exists():
                shutil.rmtree(target_version_dir)
            shutil.move(str(self._staging_dir), str(target_version_dir))

            # Pre-flight load and smoke test before switching pointer
            previous_bundle = self._resource_manager.active_bundle
            prev_dir = str(previous_bundle.bundle_dir)
            new_bundle = self._resource_manager.load_bundle_from_dir(
                target_version_dir, max_entitled_date=updates_expire_at
            )

            # Atomically update active_version.json pointer
            ptr_payload = {
                "active_version": descriptor.version,
                "active_dir": str(target_version_dir),
                "last_known_good_dir": prev_dir,
            }
            tmp_ptr = self._user_resources_dir / "active_version.json.tmp"
            tmp_ptr.write_text(json.dumps(ptr_payload, indent=2), encoding="utf-8")
            os.replace(tmp_ptr, self._active_ptr_path)

            # Swap in-memory bundle atomically
            self._resource_manager.atomic_swap(new_bundle)
            return True

        except Exception:
            if self._staging_dir.exists():
                shutil.rmtree(self._staging_dir, ignore_errors=True)
            raise

    def rollback_to_last_known_good(self) -> bool:
        """Roll back to `last_known_good_dir` or bundled baseline if an active version is faulty."""
        if self._active_ptr_path.exists():
            try:
                ptr = json.loads(self._active_ptr_path.read_text(encoding="utf-8"))
                lkg = ptr.get("last_known_good_dir")
                if lkg and Path(lkg).exists():
                    new_ptr = {
                        "active_version": "rollback",
                        "active_dir": lkg,
                        "last_known_good_dir": lkg,
                    }
                    tmp_ptr = self._user_resources_dir / "active_version.json.tmp"
                    tmp_ptr.write_text(json.dumps(new_ptr, indent=2), encoding="utf-8")
                    os.replace(tmp_ptr, self._active_ptr_path)
            except Exception:
                self._active_ptr_path.unlink(missing_ok=True)

        self._resource_manager.load_best_available()
        return True


class SecurityError(Exception):
    """Raised when an update archive violates security constraints."""
