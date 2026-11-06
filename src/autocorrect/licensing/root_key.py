"""
Embedded Ed25519 *public* root key.

Every licence certificate (`entitlement.lic`), language-resource manifest,
model manifest and application-release descriptor is verified against this
key. The matching private key never ships: it lives only on the signing
machine (see `pipeline/issue_licence.py`) and is never committed.

Rotating the key means changing `ROOT_PUBLIC_KEY_HEX` here *and*
`ED25519_PUBLIC_KEY_HEX` in `site/src/data/releases.ts`; every certificate
signed with the previous key stops verifying.
"""

from __future__ import annotations

import os
from typing import Final

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT_PUBLIC_KEY_HEX: Final[str] = "79f7c2e422116b9597ae50d9c2f9e633d2f210b89a280983b52d6bce16344f78"

# Test/developer override. Only honoured when running from source; a frozen
# build ignores it so an end user cannot swap the trust root with an env var.
ROOT_PUBLIC_KEY_ENV_VAR: Final[str] = "AUTOCORRECT_ROOT_PUBLIC_KEY_HEX"


def load_root_public_key() -> Ed25519PublicKey:
    """Return the embedded root verification key (or the dev override when unfrozen)."""
    import sys

    hex_key = ROOT_PUBLIC_KEY_HEX
    if not getattr(sys, "frozen", False):
        override = os.environ.get(ROOT_PUBLIC_KEY_ENV_VAR, "").strip().lower()
        if len(override) == 64:
            hex_key = override
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key))
