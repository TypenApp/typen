"""
Pro Edition Local AI Model Updater.
Manages optional downloads, Ed25519 manifest checks, and SHA-256 integrity
verification for quantized ONNX / GGUF local grammar and rewrite models.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pipeline.sign_release import verify_manifest_signature

from autocorrect.updates.update_policy import UpdatePolicyEngine


@dataclass(frozen=True, slots=True)
class LocalModelDescriptor:
    """Descriptor for an optional downloadable Pro local AI model."""

    model_id: str  # e.g. 'grammar-onnx-int8-small' or 'rewrite-gguf-q4'
    version: str
    released_at: str
    format: str  # 'onnx-int8' | 'gguf-q4'
    min_ram_mb: int
    size_bytes: int
    sha256: str

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "released_at": self.released_at,
            "format": self.format,
            "min_ram_mb": self.min_ram_mb,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


class ModelUpdater:
    """Downloads, verifies, and atomically installs optional Pro local AI models."""

    def __init__(self, models_dir: Path, public_key: Ed25519PublicKey) -> None:
        self._models_dir = models_dir
        self._public_key = public_key

    def install_model_bytes(
        self,
        descriptor: LocalModelDescriptor,
        signature_b64: str,
        model_bytes: bytes,
        is_pro_entitled: bool,
        updates_expire_at: datetime | None = None,
    ) -> Path:
        if not is_pro_entitled:
            raise PermissionError("Local AI models require a Pro Edition entitlement")

        if not verify_manifest_signature(descriptor.to_canonical_dict(), signature_b64, self._public_key):
            raise ValueError("Invalid Ed25519 signature on local model manifest")

        elig = UpdatePolicyEngine.check_resource_update_eligibility(
            current_version="0.0.0",
            remote_version=descriptor.version,
            remote_schema_version=1,
            remote_released_at_iso=descriptor.released_at,
            updates_expire_at=updates_expire_at,
        )
        if not elig.eligible:
            raise PermissionError(f"Model update outside entitlement window: {elig.reason}")

        actual_sha = hashlib.sha256(model_bytes).hexdigest()
        if actual_sha != descriptor.sha256:
            raise ValueError("Local AI model SHA-256 checksum mismatch")

        self._models_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._models_dir / f"{descriptor.model_id}-{descriptor.version}.tmp"
        final_path = self._models_dir / f"{descriptor.model_id}-{descriptor.version}.model"
        tmp_path.write_bytes(model_bytes)
        os.replace(tmp_path, final_path)
        return final_path
