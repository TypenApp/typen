"""
Authenticated Local IPC package connecting `AutoCorrectDaemon` and the
out-of-process Desktop Customisation UI (`autocorrect-settings`).
"""

from autocorrect.ipc.client import LocalIPCClient
from autocorrect.ipc.protocol import (
    IPC_PROTOCOL_VERSION,
    IPCAuthenticationError,
    IPCConnectionError,
    IPCError,
    IPCRequest,
    IPCResponse,
)
from autocorrect.ipc.server import AVAILABLE_DOMAIN_PACK_METADATA, LocalIPCServer

__all__ = [
    "AVAILABLE_DOMAIN_PACK_METADATA",
    "IPC_PROTOCOL_VERSION",
    "IPCAuthenticationError",
    "IPCConnectionError",
    "IPCError",
    "IPCRequest",
    "IPCResponse",
    "LocalIPCClient",
    "LocalIPCServer",
]
