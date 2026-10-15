# MeshLink: Professor Presentation & Demonstration Guide

This guide provides a structured, step-by-step walkthrough to present **MeshLink** to your professor or evaluator. It is designed to demonstrate both the **underlying computer networks theory** in the terminals and the **visual mission-control interface** in the browser.

---

## 0. Pre-Flight Setup (1 Minute Before Demo)

Open **3 PowerShell terminal windows** and arrange them side-by-side or stacked on your screen alongside your browser.

```
┌─────────────────────────────────┬─────────────────────────────────┐
│           BROWSER               │      TERMINAL 1: Node A         │
│     http://127.0.0.1:5010       │     (Port 5002 + Dashboard)     │
├─────────────────────────────────┼─────────────────────────────────┤
│      TERMINAL 2: Node B         │      TERMINAL 3: Node C         │
│     (Port 5003 - Relay)         │  (Port 5004 - Remote Endpoint)  │
└─────────────────────────────────┴─────────────────────────────────┘
```

### Launch Commands:

* **Terminal 1 (Node A — Local Base Station + React Dashboard):**
  ```powershell
  python main.py --node-id DEVICE_A --host 127.0.0.1 --port 5002 --discover --link-state --forward --self-heal --status-listen --dashboard --dashboard-port 5010 --peer 127.0.0.1:5003
  ```

* **Terminal 2 (Node B — Intermediate Relay Node):**
  ```powershell
  python main.py --node-id DEVICE_B --host 127.0.0.1 --port 5003 --discover --link-state --forward --self-heal --peer 127.0.0.1:5002 --peer 127.0.0.1:5004
  ```

* **Terminal 3 (Node C — Remote Edge Node):**
  ```powershell
  python main.py --node-id DEVICE_C --host 127.0.0.1 --port 5004 --discover --link-state --forward --self-heal --peer 127.0.0.1:5003
  ```

* **Browser:**
  Open: `http://127.0.0.1:5010`

---

## 1. Scripted 6-Minute Presentation Flow

### Act 1: The Problem & Architecture (45 Seconds)
* **What to say:**
  > *"Professor, MeshLink is a decentralized, offline ad-hoc mesh communication network designed for disaster recovery and tactical field scenarios where internet infrastructure, cellular towers, and central DNS/DHCP servers are completely unavailable. Every node runs autonomously, dynamically discovers peers, builds routes, and provides reliable transport over raw UDP. On screen is our live React Mission Control dashboard running directly on Node A."*
* **What to point out:**
  * Top bar shows `DEVICE_A on 127.0.0.1:5002`.
  * Status indicator is glowing **ONLINE**.

---

### Act 2: Peer Discovery & Dynamic Topology Radar (1 Minute)
* **What to say:**
  > *"When nodes boot up, they do not have static IPs or predefined routes. They run peer discovery beacons and heartbeat keep-alives. Here, Node A has automatically discovered its neighbor Node B, and learned of Node C through Link-State Advertisements."*
* **What to demonstrate:**
  * Point to the **Topology Radar SVG**: show Node A (blue circle), Node B and C (green discs), and the active link lines with calculated link metrics (`cost: 1`).
  * Point to the bottom-left table: **Nearby One-Hop Devices** shows `DEVICE_B`, while **Computed Multi-Hop Routes** shows destination `DEVICE_C` reachable via next-hop `DEVICE_B`.

---

### Act 3: Multi-Hop Forwarding & TTL Relaying (1.5 Minutes)
* **What to say:**
  > *"Node A cannot communicate with Node C directly because they are out of radio/port range. Traffic must hop across Node B. Let's send a packet from A to C."*
* **What to demonstrate:**
  1. On the web dashboard, under **1. Message & Relay**:
     * **Destination:** `DEVICE_C`
     * **Message:** `Field evacuation plan approved`
     * **Reliable Mode:** Checked
     * Click **🚀 Transmit Packet**.
  2. Watch the visual packet flight animation hop on the radar screen.
  3. **Show Terminal 2 (Node B):**
     ```text
     Forwarded packet from DEVICE_A to DEVICE_C via DEVICE_C
     ```
  4. **Show Terminal 3 (Node C):**
     ```text
     Received MESSAGE from DEVICE_A at 127.0.0.1:5003
     Sequence: 1 TTL: 9
     Payload: Field evacuation plan approved
     ```
* **Theory to mention:** Explain that each forwarding hop decrements the **TTL (Time-To-Live)** from 10 to 9, which mathematically prevents infinite routing loops in mesh topologies.

---

### Act 4: Go-Back-N Pipelining & Adaptive Congestion Control (AIMD) (1.5 Minutes)
* **What to say:**
  > *"Sending one packet and waiting for an ACK is slow. In Module 8 & 9, we implemented pipelined Go-Back-N (GBN) with Additive Increase / Multiplicative Decrease (AIMD) adaptive window control, similar to TCP congestion algorithms."*
* **What to demonstrate:**
  1. Click **Tab 2: Sliding Window** on the dashboard.
  2. Set **Destination:** `DEVICE_B` (or `DEVICE_C`).
  3. Set **Total Chunks:** `6`, **Window Size:** `4`. Check **Enable Adaptive Window Control (AIMD)**.
  4. Click **⚡ Stream Chunks**.
  5. Watch the **Active Window Pipeline** slots illuminate:
     * Chunks turn cyan (`⚡ In-Flight`) as they enter the transmission window.
     * Chunks turn emerald (`✓ ACKed`) upon acknowledgement.
  6. Point out live telemetry: **SRTT (Smoothed Round-Trip Time)** and **RTO (Retransmission Timeout)** calculated on the fly using Jacobson/Karels algorithm.

---

### Act 5: Shortest Path Routing Protocol Switching (1 Minute)
* **What to say:**
  > *"MeshLink supports pluggable routing engines via our unified RoutingManager. Right now it is using Link-State Routing with Dijkstra's shortest path. We can dynamically switch to Distance-Vector Routing running the Bellman-Ford algorithm at runtime."*
* **What to demonstrate:**
  1. Click the top-right button on the radar: **`Bellman-Ford (DV)`**.
  2. The badge updates to **Distance-Vector (Bellman-Ford)**.
  3. Show the **System Event Log** below:
     ```text
     [ROUTING] Switched routing algorithm to DISTANCE_VECTOR
     [ROUTING] Routes recomputed: 2 destinations active
     ```

---

### Act 6: Fault Tolerance & Self-Healing Network (1 Minute)
* **What to say:**
  > *"A critical requirement for mesh networks is resilience. If a relay node goes dark, the network must self-heal and purge stale routes without crashing."*
* **What to demonstrate:**
  1. Go to **Tab 4: Chaos & Healing**.
  2. In the dropdown, select `DEVICE_B` and click **✂️ Sever Node** (or press `Ctrl+C` in Terminal 2).
  3. Watch the radar immediately turn the node red.
  4. Point to the Event Console:
     ```text
     [HEARTBEAT] Neighbor offline: DEVICE_B
     [RESILIENCE] Self-healing: removed failed node DEVICE_B; purged routes: DEVICE_C
     ```
  5. The routing table automatically purges the unreachable route.

---

### Act 7: Disaster Emergency Broadcast & GPS Telemetry (45 Seconds)
* **What to say:**
  > *"Finally, in emergency disaster relief, nodes broadcast SOS beacons. To prevent broadcast storms, our StatusBroadcastService implements a duplicate-suppression cache."*
* **What to demonstrate:**
  1. Go to **Tab 3: Disaster SOS**.
  2. Click **🔴 CRITICAL SOS** (or enter custom GPS coordinates like `12.9716, 77.5946, Shelter 4`).
  3. All terminals immediately display the alert.
  4. The **Disaster SOS Alerts** feed logs the situational report with clickable/readable coordinates.

---

## 2. Teacher Q&A Defense Cheat-Sheet

| Likely Professor Question | Model Answer |
| :--- | :--- |
| **Why UDP instead of TCP?** | TCP requires a point-to-point connection handshake (SYN/ACK) and is ill-suited for ad-hoc multi-hop meshes where paths change and broadcast beacons are needed. UDP is connectionless and lightweight; we implemented reliability (ACKs, timeouts, sliding windows) at the application/transport layer. |
| **How does your GBN differ from Stop-and-Wait?** | Stop-and-Wait has low channel utilization because it waits for an ACK after every packet ($Utilization \approx \frac{RTT}{RTT + Transmission}$). GBN pipelines $N$ packets concurrently, filling the bandwidth-delay product and achieving up to $N \times$ higher throughput. |
| **How does the Adaptive AIMD window work?** | On successful chunk acknowledgements, the window increases linearly ($W \leftarrow W + 1$). When a timeout or packet corruption occurs, the window drops multiplicatively ($W \leftarrow \max(1, W / 2)$), preventing congestion collapse. |
| **How do you avoid routing loops in multi-hop relays?** | Every packet has a `ttl` (Time-to-Live) field decremented at each hop. If $TTL \le 0$, the packet is dropped. Furthermore, each node maintains a duplicate cache `(source, sequence_number)` so the same packet is never relayed twice. |
| **What is the difference between your Link-State and Distance-Vector implementations?** | Link-State broadcasts Link-State Advertisements (LSAs) so every node has a global weighted graph, then computes shortest paths via **Dijkstra's algorithm** ($O(V^2)$ or $O(E \log V)$). Distance-Vector only exchanges local distance vectors with direct neighbors and converges using the **Bellman-Ford equation** ($D_x(y) = \min_v \{c(x,v) + D_v(y)\}$). |
