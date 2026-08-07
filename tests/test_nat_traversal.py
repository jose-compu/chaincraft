# tests/test_nat_traversal.py
import json
import struct
import time
import unittest
from unittest.mock import MagicMock

from chaincraft import ChaincraftNode
from chaincraft.shared_message import SharedMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_stun_success_response(
    transaction_id: bytes,
    magic_cookie: int,
    ip: str,
    port: int,
    use_xor: bool = True,
) -> bytes:
    """Build a minimal STUN Binding Success Response for unit testing."""
    if use_xor:
        attr_type = 0x0020  # XOR-MAPPED-ADDRESS
        xored_port = port ^ (magic_cookie >> 16)
        ip_parts = [int(x) for x in ip.split(".")]
        ip_int = (
            (ip_parts[0] << 24)
            | (ip_parts[1] << 16)
            | (ip_parts[2] << 8)
            | ip_parts[3]
        )
        xored_ip = ip_int ^ magic_cookie
        attr_value = struct.pack(">BBH", 0x00, 0x01, xored_port) + struct.pack(
            ">I", xored_ip
        )
    else:
        attr_type = 0x0001  # MAPPED-ADDRESS
        ip_parts = [int(x) for x in ip.split(".")]
        attr_value = struct.pack(">BBH", 0x00, 0x01, port) + bytes(ip_parts)

    attr_length = len(attr_value)
    attributes = struct.pack(">HH", attr_type, attr_length) + attr_value

    msg_length = len(attributes)
    header = (
        struct.pack(">HHI", 0x0101, msg_length, magic_cookie) + transaction_id
    )
    return header + attributes


def wait_for_condition(cond_fn, timeout=5, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond_fn():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Unit tests for the STUN response parser
# ---------------------------------------------------------------------------

class TestStunResponseParser(unittest.TestCase):
    """Tests for _parse_stun_response – no network I/O required."""

    def setUp(self):
        self.node = ChaincraftNode(persistent=False)
        self.magic = 0x2112A442
        self.txn = b"\x00" * 12

    def tearDown(self):
        self.node.close()

    def test_parse_xor_mapped_address(self):
        data = _build_stun_success_response(
            self.txn, self.magic, "1.2.3.4", 12345, use_xor=True
        )
        result = self.node.nat.parse_stun_response(data, self.magic)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("1.2.3.4", 12345))

    def test_parse_mapped_address_fallback(self):
        data = _build_stun_success_response(
            self.txn, self.magic, "5.6.7.8", 54321, use_xor=False
        )
        result = self.node.nat.parse_stun_response(data, self.magic)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("5.6.7.8", 54321))

    def test_wrong_message_type_returns_none(self):
        # Craft a response with type 0x0100 (Binding Error) instead of 0x0101
        data = struct.pack(">HHI", 0x0100, 0, self.magic) + self.txn
        result = self.node.nat.parse_stun_response(data, self.magic)
        self.assertIsNone(result)

    def test_wrong_magic_cookie_returns_none(self):
        data = _build_stun_success_response(
            self.txn, self.magic, "1.2.3.4", 9999, use_xor=True
        )
        # Replace with a different magic cookie in the parsing call
        result = self.node.nat.parse_stun_response(data, 0xDEADBEEF)
        self.assertIsNone(result)

    def test_too_short_returns_none(self):
        result = self.node.nat.parse_stun_response(b"\x00" * 10, self.magic)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Unit tests for external address configuration
# ---------------------------------------------------------------------------

class TestExternalAddressConfig(unittest.TestCase):
    """Verify external address defaults and manual overrides."""

    def test_defaults_to_internal_address(self):
        node = ChaincraftNode(persistent=False, port=7777)
        try:
            self.assertEqual(node.external_host, "127.0.0.1")
            self.assertEqual(node.external_port, 7777)
        finally:
            node.close()

    def test_manual_external_address_override(self):
        node = ChaincraftNode(
            persistent=False,
            port=7778,
            nat_traversal=True,
            external_host="203.0.113.10",
            external_port=40000,
        )
        try:
            self.assertEqual(node.external_host, "203.0.113.10")
            self.assertEqual(node.external_port, 40000)
        finally:
            node.close()

    def test_nat_traversal_disabled_by_default(self):
        node = ChaincraftNode(persistent=False)
        try:
            self.assertFalse(node.nat_traversal)
        finally:
            node.close()

    def test_custom_stun_servers(self):
        custom = ["stun.example.com:3478"]
        node = ChaincraftNode(
            persistent=False, nat_traversal=True, stun_servers=custom
        )
        try:
            self.assertEqual(node.stun_servers, custom)
        finally:
            node.close()

    def test_nat_traversal_rejects_tcp(self):
        with self.assertRaises(ValueError):
            ChaincraftNode(
                persistent=False,
                nat_traversal=True,
                transport_protocol="tcp",
            )

    def test_manual_override_skips_stun_on_start(self):
        """Constructor-supplied public address must not be overwritten by STUN."""
        node = ChaincraftNode(
            persistent=False,
            nat_traversal=True,
            external_host="203.0.113.10",
            external_port=40000,
            stun_servers=["stun.example.com:3478"],
        )
        try:
            node.nat.stun_request = MagicMock(return_value=("1.2.3.4", 11111))
            node.start()
            self.assertEqual(node.external_host, "203.0.113.10")
            self.assertEqual(node.external_port, 40000)
            node.nat.stun_request.assert_not_called()
        finally:
            node.close()


# ---------------------------------------------------------------------------
# Unit tests for discover_external_address (STUN mocked)
# ---------------------------------------------------------------------------

class TestDiscoverExternalAddress(unittest.TestCase):
    def setUp(self):
        self.node = ChaincraftNode(
            persistent=False,
            nat_traversal=True,
            stun_servers=["stun.example.com:3478"],
        )

    def tearDown(self):
        self.node.close()

    def test_successful_stun_updates_external_address(self):
        self.node.nat.stun_request = MagicMock(return_value=("203.0.113.1", 30000))
        result = self.node.discover_external_address()
        self.assertEqual(result, ("203.0.113.1", 30000))
        self.assertEqual(self.node.external_host, "203.0.113.1")
        self.assertEqual(self.node.external_port, 30000)

    def test_override_short_circuits_discover(self):
        node = ChaincraftNode(
            persistent=False,
            nat_traversal=True,
            external_host="198.51.100.9",
            external_port=45000,
        )
        try:
            node.nat.stun_request = MagicMock(return_value=("1.2.3.4", 9))
            result = node.discover_external_address()
            self.assertEqual(result, ("198.51.100.9", 45000))
            node.nat.stun_request.assert_not_called()
        finally:
            node.close()

    def test_all_stun_servers_fail_returns_none(self):
        self.node.nat.stun_request = MagicMock(side_effect=OSError("network error"))
        result = self.node.discover_external_address()
        self.assertIsNone(result)

    def test_stun_returns_none_falls_through_to_none(self):
        self.node.nat.stun_request = MagicMock(return_value=None)
        result = self.node.discover_external_address()
        self.assertIsNone(result)

    def test_multiple_servers_tries_next_on_failure(self):
        self.node.stun_servers = [
            "bad.example.com:3478",
            "good.example.com:3478",
        ]
        responses = [OSError("fail"), ("1.2.3.4", 11111)]

        def side_effect(host, port):
            return responses.pop(0)

        self.node.nat.stun_request = MagicMock(side_effect=side_effect)
        result = self.node.discover_external_address()
        self.assertEqual(result, ("1.2.3.4", 11111))


# ---------------------------------------------------------------------------
# Integration: hole punching sends packets
# ---------------------------------------------------------------------------

class TestHolePunch(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n in self.nodes:
            n.close()

    def _make_node(self, **kwargs):
        n = ChaincraftNode(persistent=False, **kwargs)
        self.nodes.append(n)
        return n

    def test_hole_punch_sends_packets(self):
        node = self._make_node(nat_traversal=True)
        node.start()

        # Replace socket with a MagicMock to count sendto calls
        mock_socket = MagicMock()
        node.socket = mock_socket

        node.initiate_hole_punch("127.0.0.1", node.port + 1)
        self.assertEqual(mock_socket.sendto.call_count, 3, "Expected 3 hole-punch packets")
        for call in mock_socket.sendto.call_args_list:
            self.assertEqual(call[0][1], ("127.0.0.1", node.port + 1))

    def test_hole_punch_no_op_when_socket_none(self):
        node = self._make_node(nat_traversal=True)
        # Do not start; socket is None
        node.initiate_hole_punch("127.0.0.1", 9999)  # must not raise


# ---------------------------------------------------------------------------
# Integration: peer discovery with external address
# ---------------------------------------------------------------------------

class TestPeerDiscoveryWithNat(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n in self.nodes:
            n.close()

    def _make_node(self, **kwargs):
        n = ChaincraftNode(persistent=False, **kwargs)
        self.nodes.append(n)
        return n

    def test_discovery_message_includes_external_address(self):
        """send_peer_discovery() embeds external_address when nat_traversal=True."""
        node = self._make_node(
            nat_traversal=True,
            external_host="203.0.113.5",
            external_port=50000,
        )
        node.start()

        # Replace socket with a Mock so we can inspect what was sent
        mock_socket = MagicMock()
        node.socket = mock_socket

        node.send_peer_discovery("127.0.0.1", 9999)

        mock_socket.sendto.assert_called_once()
        data = mock_socket.sendto.call_args[0][0]
        parsed = json.loads(data.decode())
        self.assertIn("external_address", parsed)
        self.assertEqual(parsed["external_address"], "203.0.113.5:50000")
        self.assertIn(SharedMessage.PEER_DISCOVERY, parsed)

    def test_discovery_message_no_external_address_when_nat_disabled(self):
        """Without nat_traversal the discovery message must not contain external_address."""
        node = self._make_node(nat_traversal=False)
        node.start()

        mock_socket = MagicMock()
        node.socket = mock_socket

        node.send_peer_discovery("127.0.0.1", 9999)

        mock_socket.sendto.assert_called_once()
        data = mock_socket.sendto.call_args[0][0]
        parsed = json.loads(data.decode())
        self.assertNotIn("external_address", parsed)

    def test_two_nat_nodes_connect_via_external_address(self):
        """
        When both nodes advertise an external address (which is the same as their
        internal address in this loopback scenario) peer discovery should result in
        a bidirectional connection.
        """
        node1 = self._make_node(nat_traversal=True)
        node2 = self._make_node(nat_traversal=True)
        node1.start()
        node2.start()

        # Simulate public-address discovery by pointing each node at itself
        node1.external_host = node1.host
        node1.external_port = node1.port
        node2.external_host = node2.host
        node2.external_port = node2.port

        node2.connect_to_peer(node1.host, node1.port, discovery=True)

        connected = wait_for_condition(
            lambda: len(node1.peers) >= 1 and len(node2.peers) >= 1, timeout=5
        )
        self.assertTrue(connected, "Nodes did not connect via external address")


# ---------------------------------------------------------------------------
# Integration: NAT_TRAVERSAL_REQUEST / RESPONSE relay
# ---------------------------------------------------------------------------

class TestNatTraversalRelay(unittest.TestCase):
    def setUp(self):
        self.nodes = []

    def tearDown(self):
        for n in self.nodes:
            n.close()

    def _make_node(self, **kwargs):
        n = ChaincraftNode(persistent=False, **kwargs)
        self.nodes.append(n)
        return n

    def test_relay_forwards_response_to_target(self):
        """
        relay receives NAT_TRAVERSAL_REQUEST → sends NAT_TRAVERSAL_RESPONSE to target.
        """
        relay = self._make_node()
        target = self._make_node()
        relay.start()
        target.start()

        received_responses = []
        original_handle = target.handle_message

        def capturing_handle(message, message_hash, addr):
            if SharedMessage.NAT_TRAVERSAL_RESPONSE in message:
                received_responses.append(json.loads(message))
            original_handle(message, message_hash, addr)

        target.handle_message = capturing_handle

        # Build and inject a NAT_TRAVERSAL_REQUEST into the relay
        request_data = {
            SharedMessage.NAT_TRAVERSAL_REQUEST: {
                "requester": "203.0.113.1:40000",
                "target": f"{target.host}:{target.port}",
            }
        }
        shared_msg = SharedMessage(data=request_data)
        relay._handle_nat_traversal_request(
            shared_msg, (relay.host, relay.port)
        )

        responded = wait_for_condition(
            lambda: len(received_responses) >= 1, timeout=3
        )
        self.assertTrue(responded, "Target did not receive NAT_TRAVERSAL_RESPONSE")
        resp_payload = received_responses[0][SharedMessage.NAT_TRAVERSAL_RESPONSE]
        self.assertEqual(resp_payload["peer"], "203.0.113.1:40000")

    def test_handle_nat_traversal_response_connects_peer(self):
        """
        Receiving a NAT_TRAVERSAL_RESPONSE initiates hole-punch and peer connection.
        """
        node1 = self._make_node(nat_traversal=True)
        node2 = self._make_node(nat_traversal=True)
        node1.start()
        node2.start()

        response_data = {
            SharedMessage.NAT_TRAVERSAL_RESPONSE: {
                "peer": f"{node2.host}:{node2.port}",
            }
        }
        shared_msg = SharedMessage(data=response_data)
        node1._handle_nat_traversal_response(
            shared_msg, (node1.host, node1.port)
        )

        connected = wait_for_condition(
            lambda: (node2.host, node2.port) in node1.peers, timeout=3
        )
        self.assertTrue(
            connected,
            f"node1 did not add node2 as a peer after NAT_TRAVERSAL_RESPONSE. "
            f"node1.peers={node1.peers}",
        )


if __name__ == "__main__":
    unittest.main()
