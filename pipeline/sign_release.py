"""
Stage 7: Ed25519 Cryptographic Signing and Zstandard Package Builder
for Language Intelligence Resource Releases.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import zstandard as zstd
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonicalize_json_bytes(payload: dict[str, object]) -> bytes:
    """Produce deterministic canonical JSON bytes for Ed25519 signing/verification."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest_payload(
    manifest_payload: dict[str, object],
    private_key: Ed25519PrivateKey,
) -> str:
    """Sign a manifest dict with Ed25519 and return base64 signature."""
    raw = canonicalize_json_bytes(manifest_payload)
    sig = private_key.sign(raw)
    return base64.b64encode(sig).decode("ascii")


def verify_manifest_signature(
    manifest_payload: dict[str, object],
    signature_b64: str,
    public_key: Ed25519PublicKey,
) -> bool:
    """Verify an Ed25519 signature over a canonicalized manifest dict."""
    try:
        raw = canonicalize_json_bytes(manifest_payload)
        sig = base64.b64decode(signature_b64)
        public_key.verify(sig, raw)
        return True
    except Exception:
        return False


def create_zstd_bundle_archive(bundle_dir: Path, output_archive_path: Path) -> tuple[str, int]:
    """
    Package all files in `bundle_dir` into a deterministic `.tar.zst` archive.
    Returns `(sha256_hex, size_bytes)`.
    """
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for item in sorted(bundle_dir.rglob("*")):
            if item.is_file():
                rel = item.relative_to(bundle_dir).as_posix()
                tar.add(item, arcname=rel)

    compressor = zstd.ZstdCompressor(level=9)
    compressed = compressor.compress(tar_buffer.getvalue())
    output_archive_path.parent.mkdir(parents=True, exist_ok=True)
    output_archive_path.write_bytes(compressed)
    digest = hashlib.sha256(compressed).hexdigest()
    return digest, len(compressed)


def create_zstd_delta_patch(
    old_archive_bytes: bytes,
    new_archive_bytes: bytes,
    output_patch_path: Path,
) -> tuple[str, int]:
    """
    Create a zstd dictionary-compressed delta patch using `old_archive_bytes`
    as the reference prefix dictionary so incremental resource updates are tiny.
    Returns `(patch_sha256_hex, patch_size_bytes)`.
    """
    dict_data = zstd.ZstdCompressionDict(old_archive_bytes, dict_type=zstd.DICT_TYPE_RAWCONTENT)
    compressor = zstd.ZstdCompressor(level=9, dict_data=dict_data)
    patch_bytes = compressor.compress(new_archive_bytes)
    output_patch_path.parent.mkdir(parents=True, exist_ok=True)
    output_patch_path.write_bytes(patch_bytes)
    return hashlib.sha256(patch_bytes).hexdigest(), len(patch_bytes)
