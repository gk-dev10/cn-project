# MeshLink

MeshLink is an academic offline mesh communication prototype. This repository currently implements Modules 1-6 from the implementation plan:

- Module 1: node management
- Module 2: packet design, serialization, and checksums
- Module 3: UDP send/receive communication
- Module 4: peer discovery and neighbor tracking
- Module 5: heartbeat and failure detection
- Module 6: ACK-based reliable UDP transport with retransmission

## Setup

Use Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Modules 1-6 use only the Python standard library, so `requirements.txt` is intentionally empty for now.

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

## Project Layout

```text
config/
core/
discovery/
transport/
tests/
main.py
requirements.txt
```

Later modules can extend this structure with discovery, reliable transport, routing, relay, application, simulator, dashboard, and visualization packages.
