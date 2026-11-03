"""
Offline licence issuer (signing-machine only; never shipped).

Signs device-bound `SignedLicenceCertificate`s with the Ed25519 root
*private* key whose public half is embedded in
`autocorrect.licensing.root_key`. Also mints creator/lifetime certificates.

    # Print this machine's device hash (run on the target device):
    python -m pipeline.issue_licence --print-device-hash

    # Issue a 12-month Pro licence for a Windows device:
    python -m pipeline.issue_licence --sku PRO-WIN --device-hash <hash> \
        --order-id ORD-123 --out entitlement.lic

    # Issue a creator/lifetime certificate for the current platform:
    python -m pipeline.issue_licence --creator --device-hash <hash> --out entitlement.lic

Private key location: `--private-key PATH` or `AUTOCORRECT_ROOT_PRIVATE_KEY_PEM`
(default `~/.autocorrect_signing/root_ed25519_private.pem`).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autocorrect.licensing.activation_manager import compute_local_device_id_hash
from autocorrect.licensing.root_key import ROOT_PUBLIC_KEY_HEX
from autocorrect.licensing.signed_licence import (
    CREATOR_LICENCE_ID_PREFIX,
    Edition,
    ProductSKU,
    SignedLicenceCertificate,
    current_platform_sku,
    sign_licence_certificate,
    verify_licence_certificate,
)

DEFAULT_PRIVATE_KEY_PATH = Path.home() / ".autocorrect_signing" / "root_ed25519_private.pem"
CREATOR_FAR_FUTURE = "2099-12-31T00:00:00Z"


def load_private_key(path: Path | None = None) -> Ed25519PrivateKey:
    key_path = path or Path(os.environ.get("AUTOCORRECT_ROOT_PRIVATE_KEY_PEM", str(DEFAULT_PRIVATE_KEY_PATH)))
    if not key_path.is_file():
        raise FileNotFoundError(
            f"Root private key not found at {key_path}. Generate one with --generate-key."
        )
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Root key must be an Ed25519 private key")
    return key


def generate_private_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing key at {path}")
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def issue_certificate(
    private_key: Ed25519PrivateKey,
    sku: ProductSKU,
    device_id_hash: str,
    order_id: str,
    licence_id: str | None = None,
    issued_at: datetime | None = None,
    update_months: int = 12,
    creator: bool = False,
) -> SignedLicenceCertificate:
    """Build and sign a device-bound certificate (creator = Pro forever, no update window)."""
    now = (issued_at or datetime.now(UTC)).astimezone(UTC)
    if creator:
        sku = ProductSKU.for_platform(Edition.PRO, sku.platform)
        lic_id = licence_id or f"{CREATOR_LICENCE_ID_PREFIX}{secrets.token_hex(6).upper()}"
        if not lic_id.startswith(CREATOR_LICENCE_ID_PREFIX):
            lic_id = CREATOR_LICENCE_ID_PREFIX + lic_id
        expires = CREATOR_FAR_FUTURE
    else:
        lic_id = licence_id or f"LIC-{secrets.token_hex(8).upper()}"
        if lic_id.startswith(CREATOR_LICENCE_ID_PREFIX):
            raise ValueError("Non-creator licence ids must not use the CREATOR- prefix")
        expires = _iso(now + timedelta(days=30 * update_months))
    unsigned = SignedLicenceCertificate(
        licence_id=lic_id,
        order_id=order_id,
        sku=sku,
        edition=sku.edition,
        platform=sku.platform,
        device_id_hash=device_id_hash.lower(),
        perpetual_usage=True,
        issued_at=_iso(now),
        updates_expire_at=expires,
        entitled_app_max_release_date=expires,
    )
    return sign_licence_certificate(unsigned, private_key)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Issue Ed25519-signed AutoCorrect licence certificates")
    p.add_argument("--private-key", type=Path, default=None)
    p.add_argument("--generate-key", action="store_true", help="Create a new root private key and exit")
    p.add_argument(
        "--print-device-hash", action="store_true", help="Print this machine's device hash and exit"
    )
    p.add_argument(
        "--sku",
        choices=[s.value for s in ProductSKU],
        default=None,
        help="Defaults to the Pro SKU for the current platform",
    )
    p.add_argument("--device-hash", default=None, help="Target device SHA-256 hash (default: this machine)")
    p.add_argument("--order-id", default="MANUAL")
    p.add_argument("--licence-id", default=None)
    p.add_argument("--update-months", type=int, default=12)
    p.add_argument("--creator", action="store_true", help="Mint a lifetime creator certificate")
    p.add_argument("--out", type=Path, default=None, help="Write the certificate JSON here (default: stdout)")
    args = p.parse_args(argv)

    if args.generate_key:
        path = args.private_key or DEFAULT_PRIVATE_KEY_PATH
        key = generate_private_key(path)
        print(f"Private key written to {path}")
        print(f"Public key hex (embed in root_key.py): {key.public_key().public_bytes_raw().hex()}")
        return 0

    device_hash = (args.device_hash or compute_local_device_id_hash()).lower()
    if args.print_device_hash:
        print(device_hash)
        return 0

    private_key = load_private_key(args.private_key)
    pub_hex = private_key.public_key().public_bytes_raw().hex()
    if pub_hex != ROOT_PUBLIC_KEY_HEX:
        print(
            f"WARNING: private key public half {pub_hex[:16]}... does not match the embedded "
            f"root key {ROOT_PUBLIC_KEY_HEX[:16]}...; certificates will NOT verify in the app.",
            file=sys.stderr,
        )

    sku = ProductSKU(args.sku) if args.sku else current_platform_sku(Edition.PRO)
    cert = issue_certificate(
        private_key=private_key,
        sku=sku,
        device_id_hash=device_hash,
        order_id=args.order_id,
        licence_id=args.licence_id,
        update_months=args.update_months,
        creator=args.creator,
    )
    ok, reason = verify_licence_certificate(cert, private_key.public_key(), device_hash, cert.platform)
    if not ok:
        raise RuntimeError(f"Self-verification failed: {reason}")

    text = cert.to_json() + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Issued {cert.sku.value} {cert.licence_id} for device {device_hash[:16]}... -> {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
