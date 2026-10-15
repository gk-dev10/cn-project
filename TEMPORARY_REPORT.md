# Temporary Report: MeshLink Offline Mesh Communication Prototype

## 1. Project Overview

MeshLink is an academic offline mesh communication prototype. The main idea is to allow nearby devices to communicate without relying on internet access or a central server. Each device runs as a node, discovers nearby peers, exchanges packets over UDP, builds routes, forwards messages, transfers files, broadcasts emergency status, and exposes live state through a small dashboard.

The project is implemented in Python and currently covers Modules 1-25. The implementation uses only the Python standard library, which keeps setup simple and makes the project suitable for local demonstrations, classroom review, and controlled experiments.

## 2. Environment and Local Port Plan

Use Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Available local test ports:

- `5002`: default UDP node port, or Node A in multi-node demos
- `5003`: Node B or relay node in multi-node demos
- `5004`: Node C in multi-node demos
- `5010`: web dashboard

Sender-only commands usually omit `--port`. In that case, Windows chooses a free temporary UDP port automatically.

Run the full automated test suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected result:

```text
Ran 125 tests ...
OK
```

## 3. How to Work With the Project

The main entry point is `main.py`. You start one or more nodes from separate PowerShell terminals. Long-running receiver nodes keep waiting for UDP packets until stopped with `Ctrl+C`.

Basic receiver:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002
```

Basic sender:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Hello Device B"
```

Discovery between two local nodes:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --peer 127.0.0.1:5003
```

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --peer 127.0.0.1:5002
```

Three-node forwarding demo:

```powershell
.\.venv\Scripts\python.exe main.py --node-id A --host 127.0.0.1 --port 5002 --discover --link-state --forward --peer 127.0.0.1:5003
```

```powershell
.\.venv\Scripts\python.exe main.py --node-id B --host 127.0.0.1 --port 5003 --discover --link-state --forward --peer 127.0.0.1:5002 --peer 127.0.0.1:5004
```

```powershell
.\.venv\Scripts\python.exe main.py --node-id C --host 127.0.0.1 --port 5004 --discover --link-state --forward --peer 127.0.0.1:5003
```

Send a packet into the chain:

```powershell
.\.venv\Scripts\python.exe main.py --node-id A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination C --message "Hello C via relay"
```

Dashboard demo:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --self-heal --status-listen --dashboard --dashboard-port 5010 --peer 127.0.0.1:5003
```

Open:

```text
http://127.0.0.1:5010
```

## 4. Module-by-Module Description

### Module 1: Node Management

This module defines the basic identity and runtime state of a mesh node. A node has a node ID, IP address, UDP port, status, neighbor list, and routing table. The implementation is centered around the `MeshNode` model and related structures for neighbors and routes.

How to work with it:

- Create nodes using `--node-id`, `--host`, and `--port`.
- Use `MeshNode.add_neighbor()` to register a nearby node in code.
- Use `MeshNode.update_route()` to store the next hop for a destination.
- Use `MeshNode.as_dict()` when dashboard or reporting code needs structured state.

Significance:

Node management is the foundation of the project. Without a stable node identity and local state, discovery, routing, forwarding, status broadcast, and dashboard reporting would not have a consistent base to work from.

### Module 2: Packet Design, Serialization, and Checksums

This module defines the packet format used across the system. Packets include fields such as protocol version, packet type, source, destination, sequence number, TTL, payload, and checksum. Packets are serialized before network transmission and deserialized after reception.

How to work with it:

- Use packet creation helpers instead of manually building raw dictionaries.
- Send serialized packets through the UDP socket layer.
- Let the deserializer validate packet structure and checksum before the packet reaches higher modules.

Significance:

The packet format is the common language of the mesh network. Checksums provide basic data integrity, making it possible to detect corrupted packets before they affect routing or application logic.

### Module 3: UDP Send and Receive Communication

This module wraps Python UDP sockets in a reusable `UDPSocket` class. It supports binding to a local host and port, sending packets, receiving packets, and registering packet handlers for background receive loops.

How to work with it:

- Start a listener with `main.py --port 5002`.
- Send to another node with `--send-to 127.0.0.1:5002`.
- Omit `--port` in sender-only mode so the operating system picks a free temporary port.

Significance:

UDP is the transport base for the whole project. It is lightweight and suitable for offline local-network communication, but it does not guarantee delivery by itself. Later modules build reliability, routing, and application behavior on top of it.

### Module 4: Peer Discovery and Neighbor Tracking

Discovery allows nodes to find each other. Local demos use explicit `--peer` addresses because multiple nodes run on the same laptop with different UDP ports. The neighbor manager stores active neighbors and their last-seen timestamps.

How to work with it:

- Start nodes with `--discover`.
- Add one or more `--peer host:port` targets.
- Watch for `Discovered neighbor` and `Active neighbors` output.

Significance:

Discovery removes the need to manually configure every route. It lets a mesh node learn who is nearby and creates the neighbor data needed for routing and forwarding.

### Module 5: Heartbeat and Failure Detection

Heartbeat messages are sent periodically to prove that a neighbor is still alive. If a neighbor is not heard from within the configured timeout, it is marked offline or removed depending on the service behavior.

How to work with it:

- Use `--heartbeat-interval` to control how often heartbeats are sent.
- Use `--neighbor-timeout` to control how long a node waits before marking a peer offline.
- Stop one terminal during a discovery demo to observe failure detection.

Significance:

A mesh network changes over time. Devices can disconnect, move, or shut down. Heartbeats allow the system to detect these changes and avoid sending traffic through stale neighbors.

### Module 6: ACK-Based Reliable UDP Transport

UDP does not guarantee delivery. This module adds ACK handling, timeout tracking, and retransmission. When reliable mode is enabled, the sender waits for an acknowledgement and retries if needed.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Reliable hello" --reliable
```

Significance:

Reliable delivery is required for important user messages and file transfer. This module demonstrates how reliability can be layered above UDP without replacing the UDP transport itself.

### Module 7: Checksum-Based Error Detection

This module records checksum validation results and corruption statistics. It tracks accepted and rejected packets so the project can report network quality and detect bad packet data.

How to work with it:

- Packet deserialization performs checksum validation.
- Corrupt packets raise packet errors and are ignored.
- Tests cover checksum behavior and corruption statistics.

Significance:

Error detection protects the rest of the stack. Routing, file transfer, and emergency status handling should not process corrupted packets as if they were valid.

### Module 8: Go-Back-N Sliding Window Protocol

Go-Back-N allows the sender to transmit multiple chunks before waiting for acknowledgements. If a timeout occurs, the sender retransmits from the missing sequence onward.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "The quick brown fox jumps over the lazy dog" --gbn --window-size 4 --chunks 5
```

Significance:

Sliding windows improve throughput compared with sending one packet and waiting for one ACK every time. This module introduces a realistic transport-layer concept used in reliable network protocols.

### Module 9: Adaptive Window Control

The adaptive controller changes the window size based on delivery behavior. It uses AIMD behavior: increase gradually when the network is healthy and reduce when loss or timeout is detected. It also uses RTT measurements to tune timeout behavior.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Adaptive transfer test message" --gbn --window-size 4 --chunks 10 --adaptive
```

Significance:

Adaptive control makes the transport layer respond to network conditions instead of using one fixed window size. This is important in mesh networks where links may be unstable.

### Module 10: Network Topology Management

This module maintains a weighted graph of nodes and links. It records which nodes are connected and what the link costs are. Routing algorithms use this topology to compute paths.

How to work with it:

- Enable discovery and routing so links are added automatically.
- Use topology APIs in code to add or remove links.
- Use the topology visualizer to inspect current nodes and edges.

Significance:

The topology graph is the map of the network. Routing cannot make intelligent decisions unless it has a representation of the available links.

### Module 11: Link-State Routing With LSA Flooding

Link-state routing shares local link information with other nodes. Each node builds a network-wide topology view and calculates routes from that view.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --peer 127.0.0.1:5003 --lsa-interval 3
```

Significance:

Link-state routing is useful when nodes need a broader view of the mesh. It allows each node to independently calculate good routes after learning the network topology.

### Module 12: Dijkstra's Shortest-Path Algorithm

Dijkstra's algorithm computes the lowest-cost path from one node to all reachable destinations in the topology graph.

How to work with it:

- Enable `--link-state`.
- Add or discover links.
- Check the printed route table to see next hops and costs.

Significance:

Dijkstra's algorithm turns topology data into actual forwarding decisions. It answers the practical question: "Which neighbor should I send this packet to next?"

### Module 13: Distance-Vector Routing

Distance-vector routing works by exchanging routing tables with neighbors. Each node learns destinations through neighbor advertisements and updates its own view periodically.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --distance-vector --peer 127.0.0.1:5003 --routing-interval 3
```

Significance:

Distance-vector routing is simpler than link-state routing and demonstrates another major routing strategy. It is useful for comparing algorithm behavior and tradeoffs.

### Module 14: Bellman-Ford Route Computation

Bellman-Ford is the algorithmic base behind the distance-vector approach. It computes best known paths using neighbor cost information and can handle incremental route updates.

How to work with it:

- Enable `--distance-vector`.
- Observe periodic route updates.
- Use tests in `tests/test_bellman_ford.py` and `tests/test_distance_vector.py` to validate route computation.

Significance:

Bellman-Ford shows how distributed routing can be implemented without every node needing the full network topology at once.

### Module 15: Routing Manager

The routing manager provides one unified interface for routing behavior. It can coordinate link-state or distance-vector routing and keep the node routing table updated.

How to work with it:

- Use `--link-state` for topology-based routing.
- Use `--distance-vector` for vector-based routing.
- Avoid enabling both modes at the same time for normal demos.

Significance:

This module separates routing mode selection from the rest of the node runtime. Forwarding and application services can rely on the routing table without caring which routing algorithm produced it.

### Module 16: Multi-Hop Packet Forwarding

Forwarding allows a node to relay packets that are not meant for itself. The forwarder checks the destination, finds the next hop from the routing table, and sends the packet onward.

How to work with it:

- Start a chain such as A on `5002`, B on `5003`, and C on `5004`.
- Enable `--forward` on relay-capable nodes.
- Send a message to C through A and B.

Significance:

Multi-hop forwarding is what turns separate point-to-point links into a real mesh. It lets two nodes communicate even when they are not direct neighbors.

### Module 17: TTL Management

TTL, or Time To Live, limits how many hops a packet can take. Each forwarding step decrements TTL. If TTL reaches zero, the packet is dropped.

How to work with it:

- TTL is integrated into packet forwarding.
- Use multi-hop forwarding to observe TTL decreasing across relays.
- Use tests around the packet forwarder to validate drop behavior.

Significance:

TTL prevents packets from looping forever. This is essential in mesh networks because routing mistakes or stale routes can otherwise create repeated forwarding cycles.

### Module 18: Messaging Application Service

The messaging service handles user text messages above the transport and routing layers. It formats outgoing message payloads and displays incoming messages cleanly.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Need medical assistance"
```

Significance:

This module converts the lower-level networking system into an actual user-facing communication feature.

### Module 19: File Transfer

The file transfer service splits a file into chunks, sends them over the reliable/sliding-window layer, reassembles them at the receiver, and verifies the received file data.

How to work with it:

Receiver:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --receive-files --output-dir received_files
```

Sender:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --send-file .\README.md --chunk-size 1024
```

Significance:

Text messages are useful, but disaster and offline communication often require documents, images, logs, or other files. This module expands MeshLink beyond plain text.

### Module 20: Emergency Status Broadcast

This module broadcasts emergency status messages such as `SAFE` or `NEED_HELP`. It includes duplicate suppression so repeated broadcasts do not create noisy repeated processing.

How to work with it:

Listener:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --status-listen
```

Broadcaster:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --peer 127.0.0.1:5002 --im-safe --message "All clear"
```

Significance:

Emergency broadcasts are a key use case for offline mesh communication. They allow fast one-to-many status sharing when centralized infrastructure is unavailable.

### Module 21: Manual or Simulated Location Service

The location service validates latitude and longitude values and attaches location data to status payloads. It supports manual or simulated coordinates.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --peer 127.0.0.1:5002 --im-safe --message "All clear" --latitude 12.9716 --longitude 77.5946 --location-label Bengaluru
```

Significance:

Location turns a status update into actionable information. In emergency scenarios, knowing that someone is safe is useful, but knowing where they are is much more useful.

### Module 22: Packet Loss, Latency, and Node Failure Simulator

The simulator introduces controlled packet loss, delivery delay, jitter, and node failure. It can be used without running multiple real nodes.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --sim-demo --sim-packets 10 --loss-rate 0.3 --delay 0.1 --jitter 0.05
```

Simulate failed destination:

```powershell
.\.venv\Scripts\python.exe main.py --sim-demo --sim-packets 5 --fail-node SIM_B
```

Significance:

Network simulations make it easier to test resilience without needing many real devices or unstable physical networks.

### Module 23: Resilience and Self-Healing Route Cleanup

Self-healing watches for failed neighbors and removes stale routes and topology entries. It helps the node recover after a peer disappears.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --self-heal --print-topology --peer 127.0.0.1:5003 --neighbor-timeout 5
```

Then run a second node on `5003`, stop it, and wait for the timeout message.

Significance:

Mesh networks are dynamic. Self-healing prevents the system from continuing to rely on failed nodes and keeps route data closer to reality.

### Module 24: Live Topology Visualization Data, ASCII, and SVG Output

The topology visualizer converts node, link, neighbor, route, and status information into readable output formats. It supports structured JSON, terminal-friendly ASCII, and SVG output.

How to work with it:

- Use `--print-topology` to see terminal output.
- Use dashboard APIs to view structured topology state.
- Use tests in `tests/test_topology_visualizer.py` to validate output shape.

Significance:

Visualization makes the mesh easier to understand and debug. It helps demonstrate how nodes are connected and which routes are active.

### Module 25: Web Dashboard With Live State APIs

The dashboard serves a local web interface showing node status, neighbors, routes, topology, transfer statistics, and status broadcasts. It also exposes live APIs consumed by the frontend JavaScript.

How to work with it:

```powershell
.\.venv\Scripts\python.exe main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --self-heal --status-listen --dashboard --dashboard-port 5010 --peer 127.0.0.1:5003
```

Open:

```text
http://127.0.0.1:5010
```

Significance:

The dashboard makes the project easier to present. Instead of only reading terminal logs, users can inspect the live state of the mesh through a browser.

## 5. Significance of the Whole Project

MeshLink demonstrates how a communication system can be built in layers:

- Node identity and state form the base.
- Packets and UDP provide low-level communication.
- Discovery and heartbeat allow nodes to find and monitor peers.
- Reliability and sliding windows improve delivery.
- Routing algorithms calculate paths through the mesh.
- Forwarding enables multi-hop communication.
- Application services provide messaging, file transfer, emergency status, and location.
- Simulation, self-healing, visualization, and dashboard modules make the system testable, resilient, and presentable.

The project is significant because it combines multiple computer networking concepts into one working prototype. It is not just a collection of separate algorithms. Each module feeds into the next, creating an end-to-end offline mesh communication system.

## 6. Development and Testing Workflow

Recommended workflow:

1. Activate the virtual environment.
2. Run the full unit test suite.
3. Start simple two-node UDP tests.
4. Test reliable messaging and Go-Back-N.
5. Test discovery and routing.
6. Test multi-hop forwarding with three terminals.
7. Test file transfer and emergency status.
8. Run simulator scenarios.
9. Start the dashboard and inspect live state.

Core test command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Useful troubleshooting command for occupied ports:

```powershell
netstat -ano | findstr :5002
```

If a port is occupied, stop the existing process or move the node to another available port from `5002` to `5010`.

## 7. Conclusion

The current MeshLink project implements all 25 planned modules. It provides a working local prototype for offline mesh communication, including transport, reliability, routing, forwarding, application services, simulation, self-healing, topology visualization, and a web dashboard.

This temporary report can be used as a base for a final project report, presentation notes, or viva preparation.
