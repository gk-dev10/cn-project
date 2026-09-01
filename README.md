# MeshLink

MeshLink is an academic offline mesh communication prototype. This repository currently implements Modules 1-3 from the implementation plan:

- Module 1: node management
- Module 2: packet design, serialization, and checksums
- Module 3: UDP send/receive communication

## Setup

Use Python 3.12 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Modules 1-3 use only the Python standard library, so `requirements.txt` is intentionally empty for now.

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

## Project Layout

```text
config/
core/
transport/
tests/
main.py
requirements.txt
```

Later modules can extend this structure with discovery, reliable transport, routing, relay, application, simulator, dashboard, and visualization packages.
