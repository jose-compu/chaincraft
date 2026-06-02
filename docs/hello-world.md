# Hello World Tutorial

> Interactive version with diagrams: open [`index.html`](index.html) in this folder (or serve with `python -m http.server` from `docs/`).

This tutorial demonstrates how to run a simple "Hello World" example using Chaincraft nodes.

## Chaincraft CLI Parameters

The `chaincraft-cli.py` script accepts the following command-line parameters:

- `-d`, `--debug`: Enable debugging output (default: off)
- `-p PORT`, `--port PORT`: Specify the port number to use for the node (default: 21000)
- `-r`, `--random-port`: Use a random port number instead of the default or specified port
- `-m`, `--memory`: Use non-persistent memory storage instead of the default persistent storage
- `-s HOST:PORT`, `--seed-peer HOST:PORT`: Specify a seed peer to connect to for initial peer discovery
- `-c`, `--compression`: Enable message compression (default: off)

If no parameters are provided, the script will start a node with the following default settings:
- Debugging disabled
- Port 21000
- Persistent storage
- No seed peer
- Compression disabled

## Tutorial Steps

1. Open 3 terminal windows and navigate to the directory containing `chaincraft-cli.py` in each one.

2. Start the nodes with debugging enabled:
   - In Terminal 1: `python chaincraft-cli.py -p 21001 -d -m`
   - In Terminal 2: `python chaincraft-cli.py -p 21002 -s 127.0.0.1:21001 -d -m`
   - In Terminal 3: `python chaincraft-cli.py -p 21003 -s 127.0.0.1:21002 -d -m`

   This will start three nodes on ports 21001, 21002, and 21003, with debugging output enabled. The second and third nodes use the previous node as a seed peer for initial discovery.

3. In Terminal 1, enter the following JSON message and press Enter:
   ```json
   {"message": "Hello, world!"}
   ```

   This will create a shared message containing the "Hello, world!" string.

4. Observe the debug output in all three terminals as the message is gossiped from the first node to the others through the peer discovery process.

5. Experiment by sending additional messages from different nodes and watching the debug logs to see how they propagate through the network.

6. When finished, press Ctrl+C in each terminal window to shut down the nodes.

This basic Chaincraft example demonstrates how messages are gossiped between nodes that discover each other as peers, with detailed logging enabled to provide insight into the process.

By default, the nodes use persistent storage to maintain their state across restarts. You can use the `-m` flag to use non-persistent memory storage instead, which will start each node with a clean state every time.

The `-r` flag allows you to start nodes on random port numbers, which can be useful for testing or running multiple instances without worrying about port collisions.

The `-s` flag lets you specify a seed peer for initial discovery, which is helpful for bootstrapping a new node and connecting it to an existing network. Without a seed peer, a node will start in isolation and won't be able to discover or communicate with other nodes until it becomes aware of them through other means, such as manual peer addition or incoming peer connections.