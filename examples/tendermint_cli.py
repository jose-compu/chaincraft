#!/usr/bin/env python3
# examples/tendermint_cli.py

import argparse
import hashlib
import json
import os
import random
import socket
import sys
import time

# Try to import from installed package first, fall back to direct imports
try:
    from chaincraft.crypto_primitives.address import is_valid_address
    from chaincraft import ChaincraftNode
    from examples.tendermint_bft import TendermintBFT, TendermintNode
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from chaincraft.crypto_primitives.address import is_valid_address
    from chaincraft import ChaincraftNode
    from examples.tendermint_bft import TendermintBFT, TendermintNode

from typing import Dict, Any


class TendermintCLI:
    """Command-line interface for Tendermint BFT network management"""

    DEFAULT_CONFIG = {
        "node_id": f"node-{random.randint(1000, 9999)}",
        "host": "0.0.0.0",
        "port": 8001,
        "validators": [],
        "seed_nodes": [],
        "is_validator": True,
        "target_block_time": 15,
        "log_level": "info",
    }

    def __init__(self):
        self.config = self.DEFAULT_CONFIG.copy()
        self.node = None
        self.tendermint = None
        self.tendermint_node = None

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from a JSON file"""
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                self.config.update(config)
                return self.config
        except FileNotFoundError:
            print(f"Config file not found: {config_path}")
            print("Creating default configuration...")
            self.save_config(config_path)
            return self.config
        except json.JSONDecodeError:
            print(f"Error parsing config file: {config_path}")
            sys.exit(1)

    def save_config(self, config_path: str) -> None:
        """Save configuration to a JSON file"""
        with open(config_path, "w") as f:
            json.dump(self.config, f, indent=2)
        print(f"Configuration saved to {config_path}")

    def init_network(self, args) -> None:
        """Initialize a new Tendermint network"""
        config = self.load_config(args.config)

        print(f"Initializing Tendermint network: {config['node_id']}")

        # Create genesis block and validator key
        self.tendermint = TendermintBFT()
        self.tendermint.TARGET_BLOCK_TIME = config["target_block_time"]

        # Save validator information
        validator_info = {
            "address": self.tendermint.validator_address,
            "node_id": config["node_id"],
            "host": config.get(
                "public_host", socket.gethostbyname(socket.gethostname())
            ),
            "port": config["port"],
        }

        # Update config with validator info
        if config["is_validator"]:
            if validator_info not in config["validators"]:
                config["validators"].append(validator_info)

        # Save updated config
        self.save_config(args.config)

        # Create genesis file
        genesis = {
            "chain_id": f"tendermint-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}",
            "genesis_time": int(time.time()),
            "validators": config["validators"],
            "genesis_block": self.tendermint.blocks[0],
        }

        # Save genesis file
        with open("genesis.json", "w") as f:
            json.dump(genesis, f, indent=2)

        print("Genesis file created: genesis.json")
        print(f"Validator address: {self.tendermint.validator_address}")
        print("Network initialized successfully!")
        print(
            f"To start this node, run: python {sys.argv[0]} start --config {args.config}"
        )
        print(
            "For other nodes to join, share genesis.json and update seed_nodes config."
        )

    def start_node(self, args) -> None:
        """Start a Tendermint node"""
        config = self.load_config(args.config)

        print(f"Starting Tendermint node: {config['node_id']}")
        print(f"Listening on {config['host']}:{config['port']}")

        # Create and start Chaincraft node
        self.node = ChaincraftNode(port=config["port"], persistent=True)

        # Create Tendermint BFT instance
        self.tendermint = TendermintBFT()
        self.tendermint.TARGET_BLOCK_TIME = config["target_block_time"]

        # Add to Chaincraft node
        self.node.add_shared_object(self.tendermint)

        # Start the node
        self.node.start()

        # If we have seed nodes, connect to them
        for seed in config["seed_nodes"]:
            try:
                print(f"Connecting to seed node: {seed['host']}:{seed['port']}")
                self.node.connect_to_peer(seed["host"], seed["port"])
            except Exception as e:
                print(f"Error connecting to seed node: {e}")

        # Create and start Tendermint node
        self.tendermint_node = TendermintNode()
        self.tendermint_node.consensus = self.tendermint

        # Add validators
        for validator in config["validators"]:
            self.tendermint.validators.add(validator["address"])

        self.tendermint_node.start()

        print("Node started successfully!")
        print("Press Ctrl+C to stop...")

        try:
            while True:
                self._display_status()
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopping node...")
            self.tendermint_node.stop()
            self.node.close()
            print("Node stopped.")

    def join_network(self, args) -> None:
        """Join an existing Tendermint network"""
        config = self.load_config(args.config)

        if not args.genesis:
            print("Error: Genesis file is required to join a network")
            print(
                "Usage: python tendermint_cli.py join --config CONFIG --genesis GENESIS"
            )
            sys.exit(1)

        # Load genesis file
        try:
            with open(args.genesis, "r") as f:
                genesis = json.load(f)
        except Exception:
            print(f"Error loading genesis file: {args.genesis}")
            sys.exit(1)

        print(f"Joining Tendermint network: {genesis['chain_id']}")

        # Update config with genesis validators
        for validator in genesis["validators"]:
            if validator not in config["validators"]:
                config["validators"].append(validator)

                # Add to seed nodes if not already there
                seed_exists = False
                for seed in config["seed_nodes"]:
                    if (
                        seed["host"] == validator["host"]
                        and seed["port"] == validator["port"]
                    ):
                        seed_exists = True
                        break

                if not seed_exists and validator["node_id"] != config["node_id"]:
                    config["seed_nodes"].append(
                        {"host": validator["host"], "port": validator["port"]}
                    )

        # Save updated config
        self.save_config(args.config)

        print(f"Configuration updated with {len(genesis['validators'])} validators")
        print(
            f"To start this node, run: python {sys.argv[0]} start --config {args.config}"
        )

    def show_status(self, args) -> None:
        """Show the status of the Tendermint network"""
        if not self.node or not self.tendermint:
            print("Node is not running. Start it first with:")
            print(f"python {sys.argv[0]} start --config CONFIG")
            return

        self._display_status()

    def _display_status(self) -> None:
        """Display the current status of the node and network"""
        if not self.tendermint:
            return

        print("\n=== Tendermint Node Status ===")
        print(f"Validator Address: {self.tendermint.validator_address}")
        print(f"Current Height: {self.tendermint.current_height}")
        print(f"Current Step: {self.tendermint.current_step.name}")
        print(f"Validators: {len(self.tendermint.validators)}")
        lb = self.tendermint.blocks[-1]
        h = lb["hash"][:8]
        ht = lb["height"]
        print(f"Latest Block: {h}... @ {ht}")

        if self.node:
            print(f"Connected Peers: {len(self.node.peers)}")
            for peer in self.node.peers:
                paddr = f"{peer[0]}:{peer[1]}"
                print(f"  - {paddr}")

        print("==============================\n")

    def add_validator(self, args) -> None:
        """Add a new validator to the network"""
        if not args.address or not is_valid_address(args.address):
            print("Error: Invalid validator address")
            print(
                "Usage: python tendermint_cli.py add-validator --address VALIDATOR_ADDRESS"
            )
            return

        if not self.tendermint:
            print("Node is not running. Start it first with:")
            print(f"python {sys.argv[0]} start --config CONFIG")
            return

        self.tendermint.validators.add(args.address)
        print(f"Validator added: {args.address}")

        # Update config
        config = self.load_config(args.config)
        validator_exists = False
        for validator in config["validators"]:
            if validator["address"] == args.address:
                validator_exists = True
                break

        if not validator_exists:
            config["validators"].append(
                {
                    "address": args.address,
                    "node_id": "unknown",
                    "host": "unknown",
                    "port": 0,
                }
            )
            self.save_config(args.config)

        print(f"Validator {args.address} added to network")

    def list_transactions(self, args) -> None:
        """List transactions in the blockchain"""
        if not self.tendermint:
            print("Node is not running. Start it first with:")
            print(f"python {sys.argv[0]} start --config CONFIG")
            return

        print("\n=== Transaction History ===")
        total_tx = 0

        for block in self.tendermint.blocks:
            if "transactions" in block and block["transactions"]:
                print(
                    f"Block {block['height']}: {len(block['transactions'])} transactions"
                )
                for tx in block["transactions"]:
                    print(f"  - {tx}")
                total_tx += len(block["transactions"])

        print(f"\nTotal transactions: {total_tx}")
        print("===========================\n")

    def run(self) -> None:
        """Parse arguments and run the specified command"""
        parser = argparse.ArgumentParser(description="Tendermint BFT Network CLI")
        subparsers = parser.add_subparsers(dest="command", help="Command to run")

        # Init command
        init_parser = subparsers.add_parser(
            "init", help="Initialize a new Tendermint network"
        )
        init_parser.add_argument(
            "--config", required=True, help="Path to configuration file"
        )

        # Start command
        start_parser = subparsers.add_parser("start", help="Start a Tendermint node")
        start_parser.add_argument(
            "--config", required=True, help="Path to configuration file"
        )

        # Join command
        join_parser = subparsers.add_parser(
            "join", help="Join an existing Tendermint network"
        )
        join_parser.add_argument(
            "--config", required=True, help="Path to configuration file"
        )
        join_parser.add_argument(
            "--genesis", required=True, help="Path to genesis file"
        )

        # Status command
        status_parser = subparsers.add_parser("status", help="Show node status")
        status_parser.add_argument("--config", help="Path to configuration file")

        # Add validator command
        validator_parser = subparsers.add_parser(
            "add-validator", help="Add a new validator"
        )
        validator_parser.add_argument(
            "--address", required=True, help="Validator address"
        )
        validator_parser.add_argument(
            "--config", required=True, help="Path to configuration file"
        )

        # Transactions command
        tx_parser = subparsers.add_parser("transactions", help="List transactions")
        tx_parser.add_argument("--config", help="Path to configuration file")

        args = parser.parse_args()

        if args.command == "init":
            self.init_network(args)
        elif args.command == "start":
            self.start_node(args)
        elif args.command == "join":
            self.join_network(args)
        elif args.command == "status":
            self.show_status(args)
        elif args.command == "add-validator":
            self.add_validator(args)
        elif args.command == "transactions":
            self.list_transactions(args)
        else:
            parser.print_help()


if __name__ == "__main__":
    cli = TendermintCLI()
    cli.run()
