# tests/test_chatroom_protocol.py

import unittest
import time
import json
import os
import sys

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft import ChaincraftNode
    from examples.chatroom_protocol import ChatroomObject
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
except ImportError:
    # Add parent directory to path as fallback
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from chaincraft import ChaincraftNode
    from examples.chatroom_protocol import ChatroomObject
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive


def get_post_messages(chat_obj, room_name):
    """
    Return only POST_MESSAGE items from chat_obj.chatrooms[room_name]["messages"].
    """
    all_msgs = chat_obj.chatrooms[room_name]["messages"]
    return [m for m in all_msgs if m.get("message_type") == "POST_MESSAGE"]


class TestChatroomProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """
        We'll create some ECDSA keypairs for multiple users:
          - Admin user
          - Alice user
          - Bob user
          - Intruder user
        """
        cls.admin_ecdsa = ECDSASignaturePrimitive()
        cls.admin_ecdsa.generate_key()
        cls.admin_pub_pem = cls.admin_ecdsa.get_public_pem()  # Admin's public key (PEM)

        cls.alice_ecdsa = ECDSASignaturePrimitive()
        cls.alice_ecdsa.generate_key()
        cls.alice_pub_pem = cls.alice_ecdsa.get_public_pem()

        cls.bob_ecdsa = ECDSASignaturePrimitive()
        cls.bob_ecdsa.generate_key()
        cls.bob_pub_pem = cls.bob_ecdsa.get_public_pem()

        cls.intruder_ecdsa = ECDSASignaturePrimitive()
        cls.intruder_ecdsa.generate_key()
        cls.intruder_pub_pem = cls.intruder_ecdsa.get_public_pem()

    def setUp(self):
        # Create a small network of 3 nodes
        self.nodes = []
        for _ in range(3):
            node = ChaincraftNode(persistent=False, debug=False)
            node.add_shared_object(ChatroomObject())
            node.start()
            self.nodes.append(node)

        # Connect them all
        for i in range(len(self.nodes)):
            for j in range(i + 1, len(self.nodes)):
                self.nodes[i].connect_to_peer(self.nodes[j].host, self.nodes[j].port)
                self.nodes[j].connect_to_peer(self.nodes[i].host, self.nodes[i].port)

        time.sleep(1)

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def wait_for_db_count(self, count, timeout=5):
        start = time.time()
        while time.time() - start < timeout:
            if all(len(n.db) >= count for n in self.nodes):
                return True
            time.sleep(0.5)
        return False

    def sign_and_broadcast(self, ecdsa_obj: ECDSASignaturePrimitive, msg_dict: dict):
        """
        Utility to sign msg_dict with the ECDSA object, then broadcast from node[0].
        """
        if "timestamp" not in msg_dict:
            msg_dict["timestamp"] = time.time()

        msg_dict.pop("signature", None)

        payload_str = json.dumps(msg_dict, sort_keys=True)
        sig_bytes = ecdsa_obj.sign(payload_str.encode("utf-8"))
        signature_hex = sig_bytes.hex()

        msg_dict["signature"] = signature_hex
        self.nodes[0].create_shared_message(msg_dict)

    # --------------------------------------------------------------------------
    # BASIC TESTS
    # --------------------------------------------------------------------------

    def test_create_chatroom(self):
        """
        Basic test: Admin user creates a chatroom, check that it propagates
        """
        create_room_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": "fun_room",
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_room_msg)
        self.assertTrue(self.wait_for_db_count(count=1))

        # Check that each node recognizes the new room
        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            self.assertIn("fun_room", chat_obj.chatrooms)
            self.assertEqual(
                chat_obj.chatrooms["fun_room"]["admin"], self.admin_pub_pem
            )

    def test_join_and_accept(self):
        """
        Full flow: create room -> Alice requests join -> admin accepts -> Alice posts
        """
        # 1) Create chatroom
        create_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": "test_room",
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_msg)
        self.assertTrue(self.wait_for_db_count(1))

        # 2) Alice requests join
        request_join = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": "test_room",
            "public_key_pem": self.alice_pub_pem,
        }
        self.sign_and_broadcast(self.alice_ecdsa, request_join)
        self.assertTrue(self.wait_for_db_count(2))

        # 3) Admin accepts Alice
        accept_alice = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": "test_room",
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": self.alice_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, accept_alice)
        self.assertTrue(self.wait_for_db_count(3))

        # 4) Alice posts a message
        post_msg = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": "test_room",
            "public_key_pem": self.alice_pub_pem,
            "text": "Alice says hi!",
        }
        self.sign_and_broadcast(self.alice_ecdsa, post_msg)
        self.assertTrue(self.wait_for_db_count(4))

        # Confirm final state in each node
        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            self.assertIn("test_room", chat_obj.chatrooms)

            members = chat_obj.chatrooms["test_room"]["members"]
            self.assertIn(self.alice_pub_pem, members)

            # Now filter only POST_MESSAGE
            post_msgs = get_post_messages(chat_obj, "test_room")
            self.assertEqual(len(post_msgs), 1)
            self.assertEqual(post_msgs[0]["text"], "Alice says hi!")

    def test_intruder_post_fails(self):
        """
        If an intruder (not accepted by admin) tries to POST_MESSAGE,
        it should fail validation and never propagate.
        """
        # 1) Create chatroom as admin
        create_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": "secure_room",
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_msg)
        self.assertTrue(self.wait_for_db_count(1))

        # 2) Intruder attempts to post
        intruder_post = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": "secure_room",
            "public_key_pem": self.intruder_pub_pem,
            "text": "Hacked??",
        }
        # Should raise an exception because the intruder is not a member
        with self.assertRaises(Exception):
            self.sign_and_broadcast(self.intruder_ecdsa, intruder_post)

        # Wait a bit; no new messages should arrive
        time.sleep(1)
        for node in self.nodes:
            self.assertEqual(len(node.db), 1)
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, "secure_room")
            self.assertEqual(
                len(post_msgs), 0, "No post messages should exist from intruder"
            )

    def test_old_timestamp(self):
        """
        Messages older than 15s or more than 15s in the future are rejected.
        """
        # Force an old timestamp
        old_create = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": "old_room",
            "public_key_pem": self.admin_pub_pem,
            "timestamp": time.time() - 300,  # 5 minutes stale
        }
        with self.assertRaises(Exception):
            self.sign_and_broadcast(self.admin_ecdsa, old_create)

        time.sleep(1)
        for node in self.nodes:
            self.assertEqual(len(node.db), 0)

    def test_bad_signature(self):
        """
        Tampering with the signature should cause rejection.
        """
        create_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": "tamper_room",
            "public_key_pem": self.admin_pub_pem,
        }
        # sign it properly first
        self.sign_and_broadcast(self.admin_ecdsa, create_msg)
        self.assertTrue(self.wait_for_db_count(1))

        # Now let's try to tamper with a new message
        tampered_msg = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": "tamper_room",
            "public_key_pem": self.admin_pub_pem,
            "timestamp": time.time(),
            "text": "Should fail!",
        }
        # We'll sign it correctly, then manually break the signature
        payload_str = json.dumps(
            {k: tampered_msg[k] for k in tampered_msg if k != "signature"},
            sort_keys=True,
        )
        sig_bytes = self.admin_ecdsa.sign(payload_str.encode("utf-8"))
        tampered_msg["signature"] = sig_bytes.hex() + "00"

        with self.assertRaises(Exception):
            self.nodes[0].create_shared_message(tampered_msg)

        time.sleep(1)
        for node in self.nodes:
            self.assertEqual(len(node.db), 1)

    # --------------------------------------------------------------------------
    # COMPLEX TESTS
    # --------------------------------------------------------------------------

    def test_concurrent_posts(self):
        """
        Admin creates a room, accepts both Alice and Bob.
        Then each posts messages "concurrently".
        """
        room_name = "concurrent_room"

        # 1) Create the room and accept Alice
        self._create_room_and_accept_alice(room_name)

        # 2) Accept Bob too
        self._request_join_and_accept(room_name, self.bob_pub_pem, self.bob_ecdsa)

        # Now let's fire off several messages from each
        for i in range(3):
            alice_msg = {
                "message_type": "POST_MESSAGE",
                "chatroom_name": room_name,
                "public_key_pem": self.alice_pub_pem,
                "text": f"Alice concurrent {i}",
            }
            bob_msg = {
                "message_type": "POST_MESSAGE",
                "chatroom_name": room_name,
                "public_key_pem": self.bob_pub_pem,
                "text": f"Bob concurrent {i}",
            }
            # Send messages with increased delay between them
            self.sign_and_broadcast(self.alice_ecdsa, alice_msg)
            time.sleep(0.1)  # Increased from 0.01
            self.sign_and_broadcast(self.bob_ecdsa, bob_msg)
            time.sleep(0.1)  # Added additional delay after Bob's message

        # Summaries:
        #   1 CREATE + 1 ALICE join + 1 accept ALICE
        #   + 1 BOB join + 1 accept BOB
        #   + 3*2 (6) POST
        # total = 11 in the DB
        self.assertTrue(self.wait_for_db_count(11, timeout=15))  # Increased timeout

        # Check final chat - give more time for messages to propagate
        time.sleep(1)

        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, room_name)

            # Check that we have all 6 expected messages (3 from Alice, 3 from Bob)
            alice_msgs = [
                m for m in post_msgs if m["public_key_pem"] == self.alice_pub_pem
            ]
            bob_msgs = [m for m in post_msgs if m["public_key_pem"] == self.bob_pub_pem]

            self.assertEqual(
                len(alice_msgs),
                3,
                f"Expected 3 messages from Alice, got {len(alice_msgs)}",
            )
            self.assertEqual(
                len(bob_msgs), 3, f"Expected 3 messages from Bob, got {len(bob_msgs)}"
            )

            # Verify message content without relying on specific order
            alice_texts = [m["text"] for m in alice_msgs]
            bob_texts = [m["text"] for m in bob_msgs]

            for i in range(3):
                self.assertIn(f"Alice concurrent {i}", alice_texts)
                self.assertIn(f"Bob concurrent {i}", bob_texts)

    def test_multiple_members_chatting(self):
        """
        - Admin creates a room
        - Accept both Alice and Bob
        - Each posts messages
        - Confirm final messages appear
        """
        room_name = "group_chat"
        # 1) Create room
        create_room_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_room_msg)
        self.assertTrue(self.wait_for_db_count(1))

        # 2) Alice requests, then Bob requests
        req_alice = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": room_name,
            "public_key_pem": self.alice_pub_pem,
        }
        req_bob = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": room_name,
            "public_key_pem": self.bob_pub_pem,
        }
        self.sign_and_broadcast(self.alice_ecdsa, req_alice)
        time.sleep(0.2)
        self.sign_and_broadcast(self.bob_ecdsa, req_bob)
        self.assertTrue(self.wait_for_db_count(3))

        # 3) Admin accepts both
        accept_alice = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": self.alice_pub_pem,
        }
        accept_bob = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": self.bob_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, accept_alice)
        time.sleep(0.2)
        self.sign_and_broadcast(self.admin_ecdsa, accept_bob)
        self.assertTrue(self.wait_for_db_count(5))

        # 4) Alice posts 2, Bob posts 2
        for i in range(2):
            alice_msg = {
                "message_type": "POST_MESSAGE",
                "chatroom_name": room_name,
                "public_key_pem": self.alice_pub_pem,
                "text": f"Alice says {i}",
            }
            bob_msg = {
                "message_type": "POST_MESSAGE",
                "chatroom_name": room_name,
                "public_key_pem": self.bob_pub_pem,
                "text": f"Bob says {i}",
            }
            self.sign_and_broadcast(self.alice_ecdsa, alice_msg)
            time.sleep(0.1)
            self.sign_and_broadcast(self.bob_ecdsa, bob_msg)
            time.sleep(0.1)

        # total: 1 CREATE + 2 REQ + 2 ACCEPT + 4 POST = 9
        self.assertTrue(self.wait_for_db_count(9, timeout=10))
        time.sleep(0.5)

        # Check final chat messages (deduped in ChatGroup by payload id)
        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, room_name)
            alice_msgs = [
                m for m in post_msgs if m["public_key_pem"] == self.alice_pub_pem
            ]
            bob_msgs = [m for m in post_msgs if m["public_key_pem"] == self.bob_pub_pem]
            self.assertEqual(len(post_msgs), 4, "2 from Alice, 2 from Bob")
            self.assertEqual(len(alice_msgs), 2)
            self.assertEqual(len(bob_msgs), 2)
            texts = [m["text"] for m in post_msgs]
            self.assertIn("Alice says 0", texts)
            self.assertIn("Alice says 1", texts)
            self.assertIn("Bob says 0", texts)
            self.assertIn("Bob says 1", texts)

    def test_multiple_messages_same_user(self):
        """
        After a user is accepted, they post multiple messages in the chat.
        """
        # 1) Create & accept Alice
        self._create_room_and_accept_alice("multi_msgs_room")

        # 2) Have Alice post several messages
        for i in range(5):
            post_msg = {
                "message_type": "POST_MESSAGE",
                "chatroom_name": "multi_msgs_room",
                "public_key_pem": self.alice_pub_pem,
                "text": f"Alice's message {i}",
            }
            self.sign_and_broadcast(self.alice_ecdsa, post_msg)
            time.sleep(0.1)

        # By now we have 1 CREATE + 1 REQUEST + 1 ACCEPT + 5 POST = 8 total
        self.assertTrue(self.wait_for_db_count(8, timeout=8))

        # Check final chat
        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, "multi_msgs_room")
            self.assertEqual(len(post_msgs), 5)
            for j in range(5):
                self.assertIn(f"Alice's message {j}", post_msgs[j]["text"])

    def test_out_of_order_timestamps(self):
        """
        Post messages with artificially manipulated timestamps (slightly old, now, slightly future).
        All are within ±15s, so they should be accepted.
        We'll confirm they appear in the order broadcast.
        """
        room_name = "time_madness"
        self._create_room_and_accept_alice(room_name)

        # Slightly old
        msg_old = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": room_name,
            "public_key_pem": self.alice_pub_pem,
            "text": "Old by 10s",
            "timestamp": time.time() - 10,
        }
        self.sign_and_broadcast(self.alice_ecdsa, msg_old)
        time.sleep(0.2)

        # Now
        msg_now = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": room_name,
            "public_key_pem": self.alice_pub_pem,
            "text": "Now",
        }
        self.sign_and_broadcast(self.alice_ecdsa, msg_now)
        time.sleep(0.2)

        # Future
        msg_future = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": room_name,
            "public_key_pem": self.alice_pub_pem,
            "text": "Future by 10s",
            "timestamp": time.time() + 10,
        }
        self.sign_and_broadcast(self.alice_ecdsa, msg_future)

        # 1 CREATE + 1 REQUEST_JOIN + 1 ACCEPT + 3 POST = 6
        self.assertTrue(self.wait_for_db_count(6, timeout=5))

        for node in self.nodes:
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, room_name)
            self.assertEqual(len(post_msgs), 3)
            self.assertEqual(post_msgs[0]["text"], "Old by 10s")
            self.assertEqual(post_msgs[1]["text"], "Now")
            self.assertEqual(post_msgs[2]["text"], "Future by 10s")

    def test_post_beyond_15_seconds(self):
        """
        If a message has a timestamp older or newer than 15 seconds from now,
        it should be rejected.
        """
        room_name = "strict_time_room"
        self._create_room_and_accept_bob(room_name)

        # 2) Attempt to post with timestamp -20s
        msg_too_old = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": room_name,
            "public_key_pem": self.bob_pub_pem,
            "timestamp": time.time() - 20,
            "text": "This should fail",
        }
        with self.assertRaises(Exception):
            self.sign_and_broadcast(self.bob_ecdsa, msg_too_old)

        # 3) Attempt to post with timestamp +30s
        msg_too_future = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": room_name,
            "public_key_pem": self.bob_pub_pem,
            "timestamp": time.time() + 30,
            "text": "This also should fail",
        }
        with self.assertRaises(Exception):
            self.sign_and_broadcast(self.bob_ecdsa, msg_too_future)

        time.sleep(1)
        for node in self.nodes:
            # The DB itself might have 3 total for the create/join/accept,
            # but we only check POST messages to be sure none is accepted.
            chat_obj = node.shared_objects[0]
            post_msgs = get_post_messages(chat_obj, room_name)
            self.assertEqual(
                len(post_msgs), 0, "Bob's invalid timestamps should be rejected"
            )

    # --------------------------------------------------------------------------
    # Helper Methods
    # --------------------------------------------------------------------------
    def _create_room_and_accept_alice(self, room_name):
        create_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_msg)
        time.sleep(0.2)

        req_alice = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": room_name,
            "public_key_pem": self.alice_pub_pem,
        }
        self.sign_and_broadcast(self.alice_ecdsa, req_alice)
        time.sleep(0.2)

        accept_alice = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": self.alice_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, accept_alice)
        time.sleep(0.2)

    def _create_room_and_accept_bob(self, room_name):
        create_msg = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, create_msg)
        time.sleep(0.2)

        req_bob = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": room_name,
            "public_key_pem": self.bob_pub_pem,
        }
        self.sign_and_broadcast(self.bob_ecdsa, req_bob)
        time.sleep(0.2)

        accept_bob = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": self.bob_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, accept_bob)
        time.sleep(0.2)

    def _request_join_and_accept(self, room_name, user_pub_pem, user_ecdsa):
        req = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": room_name,
            "public_key_pem": user_pub_pem,
        }
        self.sign_and_broadcast(user_ecdsa, req)
        time.sleep(0.1)

        accept = {
            "message_type": "ACCEPT_MEMBER",
            "chatroom_name": room_name,
            "public_key_pem": self.admin_pub_pem,
            "requester_key_pem": user_pub_pem,
        }
        self.sign_and_broadcast(self.admin_ecdsa, accept)
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
