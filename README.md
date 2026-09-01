# MeshLink

MeshLink is an academic offline mesh communication prototype. This repository currently implements Modules 1-12 from the implementation plan:

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

## Setup

Use Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Modules 1-12 use only the Python standard library, so `requirements.txt` is intentionally empty for now.

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
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5003 --discover --peer 127.0.0.1:5002
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --discover --peer 127.0.0.1:5003
```

Expected output after a few seconds:

```text
Discovered neighbor: DEVICE_B at 127.0.0.1:5002
Active neighbors: DEVICE_B(127.0.0.1:5002)
```

and in the other terminal:

```text
Discovered neighbor: DEVICE_A at 127.0.0.1:5001
Active neighbors: DEVICE_A(127.0.0.1:5001)
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
python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5003 --discover --link-state --peer 127.0.0.1:5002 --lsa-interval 3
```

Terminal 2:

```powershell
python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5002 --discover --link-state --peer 127.0.0.1:5003 --lsa-interval 3
```

Expected output after a few seconds:

```text
Discovered neighbor: DEVICE_B at 127.0.0.1:5002
Link-State Routing: ACTIVE
Routes updated: 1 destinations
Destination     Next Hop          Cost
--------------------------------------
DEVICE_B        DEVICE_B             1
```

For a 3-node chain (A -- B -- C), start a third terminal and both A and C will discover a 2-hop route to each other through B.

## Project Layout

```text
config/
core/
discovery/
routing/
transport/
tests/
main.py
requirements.txt
```

Later modules can extend this structure with relay, application, simulator, dashboard, and visualization packages.
