# MeshLink

MeshLink is an academic offline mesh communication prototype. This repository currently implements Modules 1-25 from the implementation plan:

- Module 1: node management
- Module 2: packet design, serialization, and checksums
- Module 3: UDP send/receive communication
- Module 4: peer discovery and neighbor tracking
- Module 5: heartbeat and failure detection
- Module 6: ACK-based reliable UDP transport with retransmission
- Module 7: checksum-based error detection with corruption statistics
- Module 8: Go-Back-N sliding window protocol
- Module 9: adaptive window control (AIMD + RTT-based timeout)
- Module 10: network topology management (weighted graph)
- Module 11: Link-State routing with LSA flooding
- Module 12: Dijkstra's shortest-path algorithm
- Module 13: Distance-Vector routing with periodic updates
- Module 14: Bellman-Ford route computation
- Module 15: Routing Manager (unified interface for LS / DV)
- Module 16: multi-hop packet forwarding (relay)
- Module 17: TTL management (integrated into forwarder)
- Module 18: messaging application service
- Module 19: file transfer with metadata, chunking, reassembly, and integrity check
- Module 20: emergency status broadcast with duplicate suppression
- Module 21: manual/simulated location service
- Module 22: packet loss, latency, and node failure simulator
- Module 23: resilience and self-healing route cleanup
- Module 24: live topology visualization data, ASCII, and SVG output
- Module 25: web dashboard with live state APIs

## Setup

Use Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Modules 1-25 use only the Python standard library, so `requirements.txt` is intentionally empty for now.

## Local Port Plan

Use only these local ports for manual testing on this laptop:

- `5002`: default UDP node port, or Node A in multi-node demos
- `5003`: Node B / relay node in multi-node demos
- `5004`: Node C in multi-node demos
- `5010`: web dashboard

Sender-only commands omit `--port`, so Windows picks a free temporary sender port automatically.

## Run Tests

```powershell
python -m unittest discover -s tests
```

## Try UDP Communication Locally

Terminal 1:

```powershell
python main.py --node-id DEVICE_B --port 5002
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_A --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Hello Device B"
```

The receiver prints the packet after checksum validation and deserialization.

In send-only mode, omit `--port` unless you specifically need a fixed local sender port. The program then binds to port `0`, which asks Windows to choose a free temporary UDP port.

## Try Reliable Delivery

Terminal 1:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Reliable hello" --reliable
```

Expected sender output:

```text
Delivered MESSAGE packet #1 from DEVICE_A on 127.0.0.1:<random_port> to 127.0.0.1:5002 after 0 retries
```

Expected receiver output:

```text
Received MESSAGE from DEVICE_A at 127.0.0.1:<random_port>
Sequence: 1 TTL: 10
Payload: Reliable hello
```

If no receiver is running, reliable send retries and then reports failure.

## Try Discovery and Heartbeats Locally

On one machine, use explicit `--peer` targets because each local test node must use a different UDP port.

Terminal 1:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --peer 127.0.0.1:5003
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --peer 127.0.0.1:5002
```

Expected output after a few seconds:

```text
Discovered neighbor: DEVICE_B at 127.0.0.1:5003
Active neighbors: DEVICE_B(127.0.0.1:5003)
```

and in the other terminal:

```text
Discovered neighbor: DEVICE_A at 127.0.0.1:5002
Active neighbors: DEVICE_A(127.0.0.1:5002)
```

If one node is stopped and no heartbeat is received before the timeout, the remaining node prints:

```text
Neighbor offline: DEVICE_B
```

## Try Go-Back-N Sliding Window (Module 8)

Send a message split into chunks using the GBN sliding-window protocol.

Terminal 1 (receiver):

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002
```

Terminal 2 (GBN sender):

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "The quick brown fox jumps over the lazy dog" --gbn --window-size 4 --chunks 5
```

Expected sender output:

```text
Sending 5 chunks via Go-Back-N (window=4) from DEVICE_A on 127.0.0.1:<port> to 127.0.0.1:5002

--- Go-Back-N Transfer Summary ---
Chunks sent:       5
Chunks ACKed:      5
Retransmissions:   0
Timeouts:          0
Final window size: 4
Loss rate:         0.0%

All 5 chunks delivered successfully.
```

## Try Adaptive Window Control (Module 9)

Add `--adaptive` to automatically tune the window size during transfer:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "A long message that will be split into many chunks for transfer over the mesh network" --gbn --window-size 4 --chunks 10 --adaptive
```

The adaptive controller uses AIMD (Additive Increase / Multiplicative Decrease) and prints its decisions:

```text
Adaptive window control: ENABLED (initial window=4)
...
--- Adaptive Window Controller ---
Last decision:     increase
SRTT:              0.0012s
RTO:               0.1048s
Corruption rate:   0.0%
```

## Try Link-State Routing (Modules 10-12)

Run two nodes with discovery and link-state routing enabled. Each node builds a network topology graph and runs Dijkstra's algorithm to compute shortest paths.

Terminal 1:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --peer 127.0.0.1:5003 --lsa-interval 3
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --link-state --peer 127.0.0.1:5002 --lsa-interval 3
```

Expected output after a few seconds:

```text
Discovered neighbor: DEVICE_B at 127.0.0.1:5003
Link-State Routing: ACTIVE
Routes updated: 1 destinations
Destination     Next Hop          Cost
--------------------------------------
DEVICE_B        DEVICE_B             1
```

For a 3-node chain (A -- B -- C), start a third terminal and both A and C will discover a 2-hop route to each other through B.

## Try Distance-Vector Routing (Modules 13-14)

Use `--distance-vector` instead of `--link-state` to use the Bellman-Ford algorithm:

Terminal 1:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --distance-vector --peer 127.0.0.1:5003 --routing-interval 3
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --distance-vector --peer 127.0.0.1:5002 --routing-interval 3
```

The `--routing-interval` flag controls how often distance vectors are sent.

## Try Multi-Hop Forwarding (Modules 16-17)

Add `--forward` to enable relay mode. In a 3-node chain (A -- B -- C), node B can forward packets from A to C:

Terminal 1 (Node A):

```powershell
python main.py --node-id A --host 127.0.0.1 --port 5002 --discover --link-state --forward --peer 127.0.0.1:5003
```

Terminal 2 (Node B — relay):

```powershell
python main.py --node-id B --host 127.0.0.1 --port 5003 --discover --link-state --forward --peer 127.0.0.1:5002 --peer 127.0.0.1:5004
```

Terminal 3 (Node C):

```powershell
python main.py --node-id C --host 127.0.0.1 --port 5004 --discover --link-state --forward --peer 127.0.0.1:5003
```

Now send from A to C (which goes through B):

```powershell
python main.py --node-id A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination C --message "Hello C via relay"
```

Node B will print:

```text
Forwarded packet from A to C via C
```

Node C will print:

```text
Received MESSAGE from A ...
Payload: Hello C via relay
```

## Try Messaging Application (Module 18)

The normal `--message` flow now goes through the application-layer messaging service.

Terminal 1:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --message "Need medical assistance"
```

Expected receiver output:

```text
Message from DEVICE_A: Need medical assistance
```

## Try File Transfer (Module 19)

Terminal 1, receive and reassemble files:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --receive-files --output-dir received_files
```

Terminal 2, send a file:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --send-to 127.0.0.1:5002 --destination DEVICE_B --send-file .\README.md --chunk-size 1024
```

Expected sender output:

```text
Sent file README.md (...) from DEVICE_A on 127.0.0.1:<port> to 127.0.0.1:5002
Transfer ID:      ...
Chunks:           ...
Packets sent:     ...
Packets ACKed:    ...
Retransmissions:  0
Success:          True
```

Expected receiver output:

```text
Received file README.md (...) -> received_files\README.md
```

## Try Emergency Status Broadcast (Module 20)

Terminal 1, listen for status broadcasts:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --status-listen
```

Terminal 2, broadcast "I'm safe":

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --peer 127.0.0.1:5002 --im-safe --message "All clear"
```

Expected sender output:

```text
Broadcast STATUS SAFE from DEVICE_A to 127.0.0.1:5002
Broadcast ID: ...
```

Expected receiver output:

```text
Status from DEVICE_A: SAFE - All clear
```

## Try Location Service (Module 21)

Attach manual/simulated coordinates to a status broadcast:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --peer 127.0.0.1:5002 --im-safe --message "All clear" --latitude 12.9716 --longitude 77.5946 --location-label Bengaluru
```

Expected sender output includes:

```text
Location: 12.9716, 77.5946 (Bengaluru)
```

## Try Network Simulator (Module 22)

Run a standalone simulation with packet loss and delay:

```powershell
python main.py --sim-demo --sim-packets 10 --loss-rate 0.3 --delay 0.1 --jitter 0.05
```

Expected output:

```text
--- Network Simulator ---
Packets attempted:  10
Packets delivered:  ...
Dropped by loss:    ...
Delivery rate:      ...
```

Simulate a failed destination:

```powershell
python main.py --sim-demo --sim-packets 5 --fail-node SIM_B
```

Expected output includes:

```text
Dropped by failure: 5
```

## Try Self-Healing and Topology View (Modules 23-24)

Run nodes with discovery, routing, self-healing, and periodic topology output:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --self-heal --print-topology --peer 127.0.0.1:5003 --neighbor-timeout 5
```

In another terminal:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --link-state --self-heal --peer 127.0.0.1:5002 --neighbor-timeout 5
```

Stop `DEVICE_B`. After the timeout, `DEVICE_A` prints:

```text
Neighbor offline: DEVICE_B
Self-healing: removed failed node DEVICE_B; purged routes: ...
```

The topology output lists nodes, links, and routes.

## Try Web Dashboard (Module 25 & React Mission Control)

Start a node with dashboard enabled:

```powershell
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --self-heal --status-listen --dashboard --dashboard-port 5010 --peer 127.0.0.1:5003
```

Open:

```text
http://127.0.0.1:5010
```

The compiled React SPA is served directly by the Python node without requiring Node.js to be running. It provides an interactive mission-control interface featuring:
* Animated SVG radar mesh topology with live packet flight animations
* Interactive Showcase Control Deck for triggering messaging, GBN sliding window, emergency alerts, and chaos impairment
* Live routing table & convergence viewer (Dijkstra vs. Bellman-Ford)
* Real-time system telemetry and decentralized chat streams

### Optional: React Development Server (Vite)

If modifying the React frontend with hot module replacement:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173` (proxies all API requests to the Python node on port `5010`).
To re-build the production bundle:

```powershell
npm.cmd run build
```

## Project Layout

```text
config/
core/
application/
dashboard/
discovery/
relay/
resilience/
routing/
simulator/
transport/
visualization/
tests/
main.py
requirements.txt
```

The project is now implemented through Module 25.
