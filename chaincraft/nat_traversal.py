"""UDP NAT traversal helpers for ChaincraftNode (STUN, hole punch, relay).

Extracted from ``node.py`` to keep the node core lighter. Requires
``transport_protocol="udp"``.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from .shared_message import SharedMessage

if TYPE_CHECKING:
    from .node import ChaincraftNode

STUN_MAGIC_COOKIE = 0x2112A442
DEFAULT_STUN_SERVERS = [
    "stun.l.google.com:19302",
    "stun1.l.google.com:19302",
]
HOLE_PUNCH_SENTINEL = b"\x00"


class NatTraversal:
    """STUN discovery, UDP hole punching, and relay-coordinated introductions."""

    def __init__(
        self,
        node: "ChaincraftNode",
        *,
        enabled: bool = False,
        external_host: Optional[str] = None,
        external_port: Optional[int] = None,
        stun_servers: Optional[List[str]] = None,
    ) -> None:
        if enabled and node.transport_protocol != "udp":
            raise ValueError("nat_traversal requires transport_protocol='udp'")

        self.node = node
        self.enabled: bool = enabled
        self._external_override: bool = (
            external_host is not None or external_port is not None
        )
        self.external_host: str = (
            external_host if external_host is not None else node.host
        )
        self.external_port: int = (
            external_port if external_port is not None else node.port
        )
        self.stun_servers: List[str] = list(stun_servers or DEFAULT_STUN_SERVERS)

    # ------------------------------------------------------------------ #
    # Discovery                                                            #
    # ------------------------------------------------------------------ #

    def discover_external_address(self) -> Optional[Tuple[str, int]]:
        """
        Discover public IP/port via STUN (RFC 5389).

        Skips STUN when ``external_host`` / ``external_port`` were set at
        construction. On success, caches and returns ``(host, port)``.
        """
        if self._external_override:
            return (self.external_host, self.external_port)

        for server_str in self.stun_servers:
            try:
                stun_host, stun_port_str = server_str.rsplit(":", 1)
                stun_port = int(stun_port_str)
                result = self.stun_request(stun_host, stun_port)
                if result:
                    self.external_host, self.external_port = result
                    if self.node.debug:
                        print(
                            "NAT traversal: external address discovered "
                            f"{self.external_host}:{self.external_port}"
                        )
                    return result
            except Exception as e:
                if self.node.debug:
                    print(f"STUN request to {server_str} failed: {e}")
        if self.node.debug:
            print("NAT traversal: could not discover external address via STUN")
        return None

    def stun_request(self, stun_host: str, stun_port: int) -> Optional[Tuple[str, int]]:
        """
        Send a STUN Binding Request and parse the mapped address.

        Prefers the node's bound UDP socket so the mapped port matches the
        advertised port; falls back to a short-lived socket when unbound.
        """
        transaction_id = os.urandom(12)
        header = struct.pack(">HHI", 0x0001, 0, STUN_MAGIC_COOKIE) + transaction_id

        use_main = (
            self.node.socket is not None and self.node.transport_protocol == "udp"
        )
        if use_main:
            sock = self.node.socket
            previous_timeout = sock.gettimeout()
            try:
                sock.settimeout(3)
                sock.sendto(header, (stun_host, stun_port))
                response, _ = sock.recvfrom(1024)
            finally:
                sock.settimeout(previous_timeout)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.settimeout(3)
                sock.sendto(header, (stun_host, stun_port))
                response, _ = sock.recvfrom(1024)
            finally:
                sock.close()

        return self.parse_stun_response(response, STUN_MAGIC_COOKIE)

    @staticmethod
    def parse_stun_response(
        data: bytes, magic_cookie: int = STUN_MAGIC_COOKIE
    ) -> Optional[Tuple[str, int]]:
        """
        Parse a STUN Binding Success Response; return mapped ``(ip, port)``.

        Handles MAPPED-ADDRESS (0x0001) and XOR-MAPPED-ADDRESS (0x0020);
        XOR takes precedence.
        """
        if len(data) < 20:
            return None

        msg_type, _msg_length, cookie = struct.unpack(">HHI", data[:8])
        if msg_type != 0x0101:  # Binding Success Response
            return None
        if cookie != magic_cookie:
            return None

        mapped: Optional[Tuple[str, int]] = None
        offset = 20
        while offset + 4 <= len(data):
            attr_type, attr_length = struct.unpack(
                ">HH", data[offset : offset + 4]  # noqa: E203
            )
            offset += 4
            attr_value = data[offset : offset + attr_length]  # noqa: E203
            offset += attr_length + ((-attr_length) % 4)

            if attr_type == 0x0001 and attr_length >= 8:
                if attr_value[1] == 0x01:  # IPv4
                    port = struct.unpack(">H", attr_value[2:4])[0]
                    ip = ".".join(str(b) for b in attr_value[4:8])
                    if mapped is None:
                        mapped = (ip, port)

            elif attr_type == 0x0020 and attr_length >= 8:
                if attr_value[1] == 0x01:  # IPv4
                    xored_port = struct.unpack(">H", attr_value[2:4])[0]
                    port = xored_port ^ (magic_cookie >> 16)
                    xored_ip = struct.unpack(">I", attr_value[4:8])[0]
                    ip_int = xored_ip ^ magic_cookie
                    ip = ".".join(
                        str((ip_int >> (24 - 8 * i)) & 0xFF) for i in range(4)
                    )
                    mapped = (ip, port)

        return mapped

    # ------------------------------------------------------------------ #
    # Hole punch / relay                                                   #
    # ------------------------------------------------------------------ #

    def initiate_hole_punch(self, target_host: str, target_port: int) -> None:
        """Send UDP sentinel packets to open a NAT pinhole toward the target."""
        node = self.node
        if node.socket is None or node.transport_protocol != "udp":
            return
        for _ in range(3):
            try:
                node.socket.sendto(HOLE_PUNCH_SENTINEL, (target_host, target_port))
                if node.debug:
                    print(
                        "NAT traversal: hole-punch packet sent to "
                        f"{target_host}:{target_port}"
                    )
            except Exception as e:
                if node.debug:
                    print(
                        "NAT traversal: hole-punch to "
                        f"{target_host}:{target_port} failed: {e}"
                    )

    def send_request(
        self, relay_host: str, relay_port: int, target_host: str, target_port: int
    ) -> None:
        """Ask ``relay`` to introduce this node to ``target`` for hole punching."""
        node = self.node
        if node.socket is None:
            return
        request_message = json.dumps(
            {
                SharedMessage.NAT_TRAVERSAL_REQUEST: {
                    "requester": f"{self.external_host}:{self.external_port}",
                    "target": f"{target_host}:{target_port}",
                }
            }
        )
        node._send_bytes(
            (relay_host, relay_port), node.compress_message(request_message)
        )

    def handle_request(
        self, shared_message: SharedMessage, addr: Tuple[str, int]
    ) -> None:
        """Relay: forward the requester's external address to the target."""
        payload: Dict[str, str] = shared_message.data[
            SharedMessage.NAT_TRAVERSAL_REQUEST
        ]
        requester_addr: str = payload.get("requester", "")
        target_addr: str = payload.get("target", "")
        if not requester_addr or not target_addr:
            return

        try:
            target_host, target_port_str = target_addr.split(":")
            target_port = int(target_port_str)
        except ValueError:
            return

        response_message = json.dumps(
            {SharedMessage.NAT_TRAVERSAL_RESPONSE: {"peer": requester_addr}}
        )
        try:
            self.node._send_bytes(
                (target_host, target_port),
                self.node.compress_message(response_message),
            )
            if self.node.debug:
                print(
                    f"NAT traversal relay: forwarded {requester_addr} to "
                    f"{target_host}:{target_port}"
                )
        except Exception as e:
            if self.node.debug:
                print(f"NAT traversal relay failed: {e}")

    def handle_response(
        self, shared_message: SharedMessage, addr: Tuple[str, int]
    ) -> None:
        """Hole-punch and connect after a relay-forwarded peer address."""
        payload: Dict[str, str] = shared_message.data[
            SharedMessage.NAT_TRAVERSAL_RESPONSE
        ]
        peer_addr: str = payload.get("peer", "")
        if not peer_addr:
            return

        try:
            peer_host, peer_port_str = peer_addr.split(":")
            peer_port = int(peer_port_str)
        except ValueError:
            return

        self.initiate_hole_punch(peer_host, peer_port)
        self.node.connect_to_peer(peer_host, peer_port, discovery=True)
        if self.node.debug:
            print(
                "NAT traversal: hole-punched and connected to "
                f"{peer_host}:{peer_port}"
            )

    def external_address_str(self) -> str:
        """Return ``host:port`` for peer-discovery payloads."""
        return f"{self.external_host}:{self.external_port}"
