import argparse
import json
import os
import random
import sys
import time

# Try to import from installed package first, fall back to direct imports
try:
    from examples.chatroom_protocol import ChatroomObject
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
except ImportError:
    # Add parent directory to path as fallback
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from examples.chatroom_protocol import ChatroomObject
    from chaincraft.crypto_primitives.sign import ECDSASignaturePrimitive
from chaincraft import ChaincraftNode

COLOR_RESET = "\033[0m"
COLOR_CYAN = "\033[96m"
COLOR_MAGENTA = "\033[95m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_BOLD = "\033[1m"

CHECK_EMOJI = "✅"
CHAT_EMOJI = "💬"
WARN_EMOJI = "⚠️ "
STAR_EMOJI = "✨"


def short_pem_id(pem_str: str) -> str:
    lines = pem_str.strip().splitlines()
    base64_lines = []
    for line in lines:
        if "BEGIN" in line or "END" in line:
            continue
        base64_lines.append(line.strip())

    # Combine all base64 lines (no headers)
    b64_content = "".join(base64_lines)
    # Strip trailing '='
    b64_content = b64_content.rstrip("=")

    # Return last 7 characters (or fewer if short)
    return b64_content[-7:]


class ChatroomCLI:
    def __init__(self, port=None, peer=None, debug=False):
        # ECDSA key
        self.ecdsa = ECDSASignaturePrimitive()
        self.ecdsa.generate_key()
        self.pub_pem = self.ecdsa.get_public_pem()

        # Node
        self.node = ChaincraftNode(
            persistent=False,
            debug=debug,
            port=port if port else random.randint(10000, 60000),
            local_discovery=True,
        )
        self.chatroom_object = ChatroomObject(
            on_message_added=self._on_chatroom_message
        )
        self.node.add_shared_object(self.chatroom_object)
        self.node.start()

        # Connect to a known peer
        if peer:
            host, p = peer.split(":")
            self.node.connect_to_peer(host, int(p), discovery=True)
            self.node.connect_to_peer_locally(host, int(p))

        addr = f"{self.node.host}:{self.node.port}"
        print(f"{STAR_EMOJI} {COLOR_BOLD}Chatroom CLI started at {addr}{COLOR_RESET}")
        print(
            f"Your ephemeral ECDSA public key (PEM):\n{COLOR_CYAN}{self.pub_pem}{COLOR_RESET}\n"
        )
        print(f"Type '{COLOR_BOLD}/help{COLOR_RESET}' to see commands.")

        self.current_chatroom = None

    def _on_chatroom_message(self, chatroom_name: str, msg: dict) -> None:
        """Called by ChatroomObject.add_message when a new message is added (ChaincraftNode handler thread)."""
        self._maybe_print_chat_message(chatroom_name, msg)
        self._maybe_auto_accept(chatroom_name, msg)

    def _maybe_print_chat_message(self, chatroom_name, msg):
        mtype = msg.get("message_type")
        user_pem = msg.get("public_key_pem", "")
        short_id = short_pem_id(user_pem)
        text = msg.get("text", "")

        if mtype == "POST_MESSAGE":
            print(
                f"\n{CHAT_EMOJI} {COLOR_YELLOW}[{chatroom_name}]{COLOR_RESET} "
                f"{COLOR_GREEN}{short_id}{COLOR_RESET}: "
                f"{COLOR_MAGENTA}{text}{COLOR_RESET}"
            )
        elif mtype == "REQUEST_JOIN":
            print(
                f"\n{CHAT_EMOJI} {COLOR_YELLOW}[{chatroom_name}]{COLOR_RESET} "
                f"{COLOR_GREEN}{short_id}{COLOR_RESET} requested to join!"
            )
        elif mtype == "ACCEPT_MEMBER":
            who = msg.get("requester_key_pem", "")
            who_short = short_pem_id(who)
            print(
                f"\n{CHECK_EMOJI} {COLOR_YELLOW}[{chatroom_name}]{COLOR_RESET}: "
                f"User {COLOR_GREEN}{who_short}{COLOR_RESET} has been accepted by admin!"
            )
        # else: CREATE_CHATROOM or other, remain silent or optionally print

    def _maybe_auto_accept(self, chatroom_name, msg):
        # If we're admin and see a REQUEST_JOIN, auto-accept
        mtype = msg.get("message_type")
        if mtype != "REQUEST_JOIN":
            return
        admin_key = self.chatroom_object.chatrooms[chatroom_name]["admin"]
        if admin_key == self.pub_pem:
            requester_key = msg["public_key_pem"]
            members = self.chatroom_object.chatrooms[chatroom_name]["members"]
            if requester_key not in members:
                accept_msg = {
                    "message_type": "ACCEPT_MEMBER",
                    "chatroom_name": chatroom_name,
                    "public_key_pem": self.pub_pem,
                    "requester_key_pem": requester_key,
                }
                self._sign_and_broadcast(accept_msg)

    def close(self):
        self.node.close()
        print(f"{WARN_EMOJI} Node closed. Goodbye!")

    def run_cli_loop(self):
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break

            if not line:
                continue

            if line.startswith("/"):
                parts = line.split(" ", 1)
                cmd = parts[0].lower()

                if cmd == "/help":
                    self.print_help()
                elif cmd == "/quit":
                    print("Exiting...")
                    break
                elif cmd == "/rooms":
                    self.print_rooms()
                elif cmd == "/create":
                    if len(parts) < 2:
                        print("Usage: /create <chatroom_name>")
                        continue
                    cname = parts[1].strip()
                    self.create_chatroom(cname)
                elif cmd == "/join":
                    if len(parts) < 2:
                        print("Usage: /join <chatroom_name>")
                        continue
                    cname = parts[1].strip()
                    self.request_join(cname)
                elif cmd == "/msg":
                    if len(parts) < 2:
                        print("Usage: /msg <text>")
                        continue
                    text_msg = parts[1].strip()
                    self.post_message(text_msg)
                else:
                    print("Unknown command. Type /help.")
            else:
                self.post_message(line)

        self.close()

    # --------------------------
    # Chatroom actions
    # --------------------------
    def create_chatroom(self, chatroom_name):
        data = {
            "message_type": "CREATE_CHATROOM",
            "chatroom_name": chatroom_name,
            "public_key_pem": self.pub_pem,
        }
        self._sign_and_broadcast(data)
        self.current_chatroom = chatroom_name
        print(f"{CHECK_EMOJI} Created chatroom '{chatroom_name}'. You are admin.")

    def request_join(self, chatroom_name):
        data = {
            "message_type": "REQUEST_JOIN",
            "chatroom_name": chatroom_name,
            "public_key_pem": self.pub_pem,
        }
        self._sign_and_broadcast(data)
        self.current_chatroom = chatroom_name
        print(f"{CHECK_EMOJI} Requested to join chatroom '{chatroom_name}'.")

    def post_message(self, text_msg):
        if not self.current_chatroom:
            print("No chatroom selected. Use /create or /join.")
            return
        data = {
            "message_type": "POST_MESSAGE",
            "chatroom_name": self.current_chatroom,
            "public_key_pem": self.pub_pem,
            "text": text_msg,
        }
        self._sign_and_broadcast(data)

    # --------------------------
    # Utility
    # --------------------------
    def _sign_and_broadcast(self, data_dict):
        if "timestamp" not in data_dict:
            data_dict["timestamp"] = time.time()
        data_dict.pop("signature", None)
        payload_str = json.dumps(data_dict, sort_keys=True)
        sig_bytes = self.ecdsa.sign(payload_str.encode("utf-8"))
        data_dict["signature"] = sig_bytes.hex()
        self.node.create_shared_message(data_dict)

    def print_help(self):
        print(f"{COLOR_BOLD}Commands:{COLOR_RESET}")
        print("/create <name>       Create chatroom (admin, auto-accept new joiners)")
        print("/join <name>         Request to join chatroom")
        print("/msg <text>          Post a message (or just type text w/o slash)")
        print("/rooms               List known chatrooms")
        print("/help                Show this help")
        print("/quit                Exit")

    def print_rooms(self):
        if not self.chatroom_object.chatrooms:
            print(
                "No chatrooms yet. Use /create <chatroom_name> or /join <chatroom_name>."
            )
            return
        print(f"{STAR_EMOJI} {COLOR_BOLD}Known chatrooms:{COLOR_RESET}")
        for cname, cdata in self.chatroom_object.chatrooms.items():
            admin_key = cdata["admin"]
            short_admin = short_pem_id(admin_key)
            members = cdata["members"]
            short_mems = [short_pem_id(m) for m in members]
            msg_count = len(cdata["messages"])
            print(
                f"  {COLOR_YELLOW}{cname}{COLOR_RESET} "
                f"(admin: {COLOR_CYAN}{short_admin}{COLOR_RESET}, "
                f"{len(members)} members, {msg_count} msgs)"
            )
            if short_mems:
                print(f"    members => {short_mems}")


def main():
    parser = argparse.ArgumentParser(
        description="Chaincraft Chatroom CLI (short PEM IDs)."
    )
    parser.add_argument(
        "--port", type=int, help="UDP port to bind this node to (default random)"
    )
    parser.add_argument(
        "--peer", type=str, help="host:port of a known peer to connect to"
    )
    parser.add_argument("--debug", action="store_true", help="Enable node debug prints")
    args = parser.parse_args()

    cli = ChatroomCLI(port=args.port, peer=args.peer, debug=args.debug)
    try:
        cli.run_cli_loop()
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
