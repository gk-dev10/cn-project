/**
 * MeshLink Tactical Mission Control & Interactive Evaluation Suite
 * Powers live topology animations, GBN sliding-window visualizer,
 * multi-hop packet tracing, chaos simulation, and emergency telemetry.
 */

// Global State
let isPollingActive = true;
let pollTimer = null;
let lastKnownState = null;
let activePacketAnimations = [];

// DOM Element References
const nodeLine = document.querySelector("#nodeLine");
const networkStatus = document.querySelector("#networkStatus");
const routingBadge = document.querySelector("#routingBadge");
const neighborCount = document.querySelector("#neighborCount");
const routeCount = document.querySelector("#routeCount");
const lossRateDisplay = document.querySelector("#lossRateDisplay");
const updatedAt = document.querySelector("#updatedAt");
const topologySvg = document.querySelector("#topologySvg");

const neighborsEl = document.querySelector("#neighbors");
const routesTableBody = document.querySelector("#routesTableBody");
const neighborCountSmall = document.querySelector("#neighborCountSmall");
const routeCountSmall = document.querySelector("#routeCountSmall");

const eventConsole = document.querySelector("#eventConsole");
const eventCount = document.querySelector("#eventCount");
const chatMessageFlow = document.querySelector("#chatMessageFlow");
const chatCount = document.querySelector("#chatCount");
const sosAlertList = document.querySelector("#sosAlertList");
const statusCount = document.querySelector("#statusCount");

const nodeSuggestions = document.querySelector("#nodeSuggestions");
const selectSeverNode = document.querySelector("#selectSeverNode");
const sendFeedbackText = document.querySelector("#sendFeedbackText");
const toastContainer = document.querySelector("#toastContainer");

// Sliding window elements
const windowTrack = document.querySelector("#windowTrack");
const gbnStatusPill = document.querySelector("#gbnStatusPill");
const valSrtt = document.querySelector("#valSrtt");
const valRto = document.querySelector("#valRto");
const valWindow = document.querySelector("#valWindow");
const valRetries = document.querySelector("#valRetries");

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupEventListeners();
  startPolling();
});

// -----------------------------------------------------------------------------
// Setup Tabs and UI Controls
// -----------------------------------------------------------------------------

function setupTabs() {
  // Main Showcase tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const targetPane = document.getElementById(btn.dataset.tab);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Bottom Sub-panel feed pills
  document.querySelectorAll(".pill-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".feed-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const targetFeed = document.getElementById(btn.dataset.sub);
      if (targetFeed) targetFeed.classList.add("active");
    });
  });
}

function setupEventListeners() {
  // Auto-sync toggle
  const pollToggleBtn = document.querySelector("#pollToggleBtn");
  pollToggleBtn.addEventListener("click", () => {
    isPollingActive = !isPollingActive;
    if (isPollingActive) {
      pollToggleBtn.innerHTML = '<span class="pulse-indicator"></span> Auto-Sync: ON';
      pollToggleBtn.classList.remove("btn-chip");
      pollToggleBtn.classList.add("btn-secondary");
      startPolling();
      showToast("Live telemetry synchronization resumed");
    } else {
      pollToggleBtn.innerHTML = '⏸️ Auto-Sync: PAUSED';
      pollToggleBtn.classList.remove("btn-secondary");
      pollToggleBtn.classList.add("btn-chip");
      stopPolling();
      showToast("Live telemetry paused for analysis");
    }
  });

  // Manual Refresh
  document.querySelector("#refreshBtn").addEventListener("click", () => {
    loadState(true);
    showToast("Telemetry synced from mesh node");
  });

  // Quick Safe Button
  document.querySelector("#quickSafeBtn").addEventListener("click", async () => {
    await sendEmergencyStatus("SAFE", "Quick safe broadcast from dashboard");
  });

  // Showcase 1: Messaging form
  const messageForm = document.querySelector("#messageForm");
  messageForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSendMessage();
  });

  // Showcase 2: GBN Sliding Window form
  const gbnForm = document.querySelector("#gbnForm");
  gbnForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleStartGbn();
  });

  // Showcase 3: Emergency SOS quick buttons
  document.querySelectorAll(".btn-sos").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const status = btn.dataset.status;
      const msg = btn.dataset.msg;
      await sendEmergencyStatus(status, msg);
    });
  });

  // Showcase 3: Custom SOS form
  const customSosForm = document.querySelector("#customSosForm");
  customSosForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = document.querySelector("#sosMessage").value;
    const lat = parseFloat(document.querySelector("#sosLat").value);
    const lon = parseFloat(document.querySelector("#sosLon").value);
    const label = document.querySelector("#sosLabel").value;
    await sendEmergencyStatus("CRITICAL_SOS", msg, lat, lon, label);
  });

  // Showcase 4: Chaos sliders
  const sliderLoss = document.querySelector("#sliderLoss");
  const sliderDelay = document.querySelector("#sliderDelay");
  const sliderLossVal = document.querySelector("#sliderLossVal");
  const sliderDelayVal = document.querySelector("#sliderDelayVal");

  sliderLoss.addEventListener("input", () => {
    sliderLossVal.textContent = `${sliderLoss.value}%`;
  });
  sliderDelay.addEventListener("input", () => {
    sliderDelayVal.textContent = `${sliderDelay.value} ms`;
  });

  document.querySelector("#btnApplyImpairment").addEventListener("click", async () => {
    const lossRate = parseFloat(sliderLoss.value) / 100.0;
    const delaySec = parseFloat(sliderDelay.value) / 1000.0;
    await applySimulation(lossRate, delaySec, 0.01);
  });

  document.querySelector("#btnResetImpairment").addEventListener("click", async () => {
    sliderLoss.value = 0;
    sliderDelay.value = 0;
    sliderLossVal.textContent = "0%";
    sliderDelayVal.textContent = "0 ms";
    await applySimulation(0.0, 0.0, 0.0);
  });

  // Showcase 4: Sever node button
  document.querySelector("#btnSeverNode").addEventListener("click", async () => {
    const targetNode = selectSeverNode.value;
    if (!targetNode) {
      showToast("Select a node to sever first", "error");
      return;
    }
    await severNode(targetNode);
  });

  // Showcase 5: Routing switches
  const btnSwitchLS = document.querySelector("#btnSwitchLS");
  const btnSwitchDV = document.querySelector("#btnSwitchDV");

  btnSwitchLS.addEventListener("click", async () => {
    await switchRoutingAlgorithm("LINK_STATE");
    btnSwitchLS.classList.add("active");
    btnSwitchDV.classList.remove("active");
  });

  btnSwitchDV.addEventListener("click", async () => {
    await switchRoutingAlgorithm("DISTANCE_VECTOR");
    btnSwitchDV.classList.add("active");
    btnSwitchLS.classList.remove("active");
  });

  // Clear Event Log
  document.querySelector("#clearLogBtn").addEventListener("click", () => {
    eventConsole.innerHTML = "";
    showToast("Event log cleared");
  });
}

// -----------------------------------------------------------------------------
// Live Polling & State Engine
// -----------------------------------------------------------------------------

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  loadState();
  pollTimer = setInterval(loadState, 1500);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function loadState(force = false) {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) return;
    const state = await response.json();
    lastKnownState = state;
    renderDashboard(state);
  } catch (err) {
    console.error("Failed to fetch state:", err);
    networkStatus.textContent = "OFFLINE";
    networkStatus.className = "status-pill status-lost";
  }
}

// -----------------------------------------------------------------------------
// Render Orchestration
// -----------------------------------------------------------------------------

function renderDashboard(state) {
  // Topbar Telemetry
  nodeLine.textContent = `${state.node.node_id} on ${state.node.ip}:${state.node.port}`;
  networkStatus.textContent = state.node.status;
  neighborCount.textContent = String(state.neighbors.length);
  neighborCountSmall.textContent = String(state.neighbors.length);

  const routeEntries = Object.entries(state.routes || {});
  routeCount.textContent = String(routeEntries.length);
  routeCountSmall.textContent = String(routeEntries.length);

  if (state.simulation) {
    lossRateDisplay.textContent = `${(state.simulation.loss_rate * 100).toFixed(1)}%`;
  }

  // Routing Strategy Badge
  const strat = state.routing_strategy || "LINK_STATE";
  routingBadge.textContent = strat === "LINK_STATE" ? "Link-State (Dijkstra)" : "Distance-Vector (Bellman-Ford)";
  routingBadge.className = `badge ${strat === "LINK_STATE" ? "badge-purple" : "badge-accent"}`;

  updatedAt.textContent = new Date(state.generated_at * 1000).toLocaleTimeString();

  // Populate Dropdowns
  updateNodeSuggestions(state);

  // Render Visual Subcomponents
  renderTopology(state.topology, state.routes, state.node.node_id);
  renderNeighbors(state.neighbors);
  renderRoutes(routeEntries);
  renderTransfers(state.transfers || []);
  renderEventLog(state.events || []);
  renderChatMessages(state.messages || []);
  renderStatuses(state.statuses || []);
}

function updateNodeSuggestions(state) {
  const allPeers = new Set();
  (state.neighbors || []).forEach((n) => allPeers.add(n.node_id));
  Object.keys(state.routes || {}).forEach((dst) => allPeers.add(dst));

  // Datalist for messaging
  nodeSuggestions.innerHTML = "";
  allPeers.forEach((id) => {
    const opt = document.createElement("option");
    opt.value = id;
    nodeSuggestions.appendChild(opt);
  });

  // Dropdown for severing
  const currentVal = selectSeverNode.value;
  selectSeverNode.innerHTML = '<option value="">-- Choose node to drop --</option>';
  (state.neighbors || []).forEach((n) => {
    const opt = document.createElement("option");
    opt.value = n.node_id;
    opt.textContent = `${n.node_id} (${n.ip}:${n.port})`;
    selectSeverNode.appendChild(opt);
  });
  if (currentVal) selectSeverNode.value = currentVal;
}

// -----------------------------------------------------------------------------
// Interactive Topology Radar Visualizer (SVG)
// -----------------------------------------------------------------------------

function renderTopology(topology, routes, selfNodeId) {
  const width = 860;
  const height = 460;
  const nodes = topology?.nodes || [];
  const links = topology?.links || [];

  const positions = new Map();
  nodes.forEach((n) => {
    positions.set(n.id, [n.x * width, n.y * height]);
  });

  // Calculate Route Hops to highlight
  const routeHopLinks = new Set();
  Object.entries(routes || {}).forEach(([dst, route]) => {
    const nextHop = route.next_hop;
    if (nextHop) {
      routeHopLinks.add(`${selfNodeId}->${nextHop}`);
      routeHopLinks.add(`${nextHop}->${selfNodeId}`);
    }
  });

  let svgHtml = `
    <!-- Radar Grid Circles -->
    <circle cx="${width/2}" cy="${height/2}" r="90" fill="none" stroke="rgba(56, 189, 248, 0.05)" stroke-width="1"></circle>
    <circle cx="${width/2}" cy="${height/2}" r="180" fill="none" stroke="rgba(56, 189, 248, 0.05)" stroke-width="1"></circle>
    <circle cx="${width/2}" cy="${height/2}" r="270" fill="none" stroke="rgba(56, 189, 248, 0.03)" stroke-width="1"></circle>
  `;

  // Draw Links
  links.forEach((link) => {
    const from = positions.get(link.source);
    const to = positions.get(link.target);
    if (!from || !to) return;

    const isRouteHop = routeHopLinks.has(`${link.source}->${link.target}`);
    const strokeColor = isRouteHop ? "#a855f7" : link.active ? "#475569" : "#dc2626";
    const strokeWidth = isRouteHop ? "3" : "1.8";

    svgHtml += `
      <line x1="${from[0]}" y1="${from[1]}" x2="${to[0]}" y2="${to[1]}" 
            stroke="${strokeColor}" stroke-width="${strokeWidth}" class="${isRouteHop ? 'topo-link' : ''}"></line>
      <text x="${(from[0] + to[0]) / 2}" y="${(from[1] + to[1]) / 2 - 6}" 
            fill="#64748b" font-family="'JetBrains Mono', monospace" font-size="10" text-anchor="middle">
        cost: ${link.cost || 1}
      </text>
    `;
  });

  // Draw Nodes
  nodes.forEach((node) => {
    const pos = positions.get(node.id);
    if (!pos) return;
    const [cx, cy] = pos;

    const isSelf = node.is_self;
    const isActive = node.status === "ACTIVE";
    const nodeColor = isSelf ? "#38bdf8" : isActive ? "#10b981" : "#f43f5e";

    svgHtml += `
      <g class="topo-node" data-id="${node.id}" style="cursor: pointer;">
        <!-- Pulsing Halo for Self and Active -->
        <circle cx="${cx}" cy="${cy}" r="26" fill="none" stroke="${nodeColor}" stroke-width="1" class="topo-node-ring"></circle>
        
        <!-- Node Center Disc -->
        <circle cx="${cx}" cy="${cy}" r="16" fill="#090f1b" stroke="${nodeColor}" stroke-width="2.5"></circle>
        
        <!-- Node Label -->
        <text x="${cx}" y="${cy + 30}" fill="#ffffff" font-family="'Outfit', sans-serif" font-weight="700" font-size="12" text-anchor="middle">
          ${node.id} ${isSelf ? '(YOU)' : ''}
        </text>
        <text x="${cx}" y="${cy + 42}" fill="#94a3b8" font-family="'JetBrains Mono', monospace" font-size="10" text-anchor="middle">
          ${node.ip}:${node.port}
        </text>
      </g>
    `;
  });

  // Render In-Flight Packet Particle Animations
  activePacketAnimations.forEach((pkt) => {
    const from = positions.get(pkt.from);
    const to = positions.get(pkt.to);
    if (from && to) {
      const curX = from[0] + (to[0] - from[0]) * pkt.progress;
      const curY = from[1] + (to[1] - from[1]) * pkt.progress;
      svgHtml += `
        <circle cx="${curX}" cy="${curY}" r="5" fill="#38bdf8" filter="drop-shadow(0 0 6px #38bdf8)"></circle>
        <text x="${curX}" y="${curY - 8}" fill="#38bdf8" font-family="'JetBrains Mono', monospace" font-size="9" font-weight="bold" text-anchor="middle">
          ${pkt.label}
        </text>
      `;
    }
  });

  topologySvg.innerHTML = svgHtml;
}

// -----------------------------------------------------------------------------
// Interactive Packet Flight Animator
// -----------------------------------------------------------------------------

function animatePacketFlight(fromNode, toNode, label = "PKT") {
  const anim = {
    from: fromNode,
    to: toNode,
    label: label,
    progress: 0.0,
  };
  activePacketAnimations.push(anim);

  const duration = 1200; // ms
  const startTime = performance.now();

  function step(currentTime) {
    const elapsed = currentTime - startTime;
    anim.progress = Math.min(1.0, elapsed / duration);

    if (anim.progress < 1.0) {
      requestAnimationFrame(step);
    } else {
      activePacketAnimations = activePacketAnimations.filter((a) => a !== anim);
    }
    if (lastKnownState) {
      renderTopology(lastKnownState.topology, lastKnownState.routes, lastKnownState.node.node_id);
    }
  }
  requestAnimationFrame(step);
}

// -----------------------------------------------------------------------------
// Neighbors & Routing Tables
// -----------------------------------------------------------------------------

function renderNeighbors(neighbors) {
  if (!neighbors || neighbors.length === 0) {
    neighborsEl.innerHTML = '<div class="empty-hint">Scanning local network for beacons...</div>';
    return;
  }

  neighborsEl.innerHTML = neighbors
    .map((n) => `
      <div class="device-card">
        <div class="device-info">
          <span class="device-id">${escapeHtml(n.node_id)}</span>
          <span class="device-addr">${escapeHtml(n.ip)}:${escapeHtml(n.port)}</span>
        </div>
        <span class="status-pill ${n.status === 'ACTIVE' ? 'status-active' : 'status-lost'}">
          ${escapeHtml(n.status)}
        </span>
      </div>
    `)
    .join("");
}

function renderRoutes(routeEntries) {
  if (!routeEntries || routeEntries.length === 0) {
    routesTableBody.innerHTML = '<tr><td colspan="3" class="text-muted">No routes computed yet</td></tr>';
    return;
  }

  routesTableBody.innerHTML = routeEntries
    .map(([dst, route]) => `
      <tr>
        <td class="text-cyan font-bold">${escapeHtml(dst)}</td>
        <td>${escapeHtml(route.next_hop || '-')}</td>
        <td class="text-emerald">${escapeHtml(String(route.cost || 1))}</td>
      </tr>
    `)
    .join("");
}

// -----------------------------------------------------------------------------
// Sliding Window (GBN) Visualizer
// -----------------------------------------------------------------------------

function renderTransfers(transfers) {
  if (!transfers || transfers.length === 0) {
    gbnStatusPill.textContent = "IDLE";
    gbnStatusPill.className = "badge badge-neutral";
    return;
  }

  const latest = transfers[0];
  gbnStatusPill.textContent = latest.status.toUpperCase();
  gbnStatusPill.className = `badge ${
    latest.status === "completed" ? "badge-emerald" : latest.status === "running" ? "badge-accent" : "badge-neutral"
  }`;

  valSrtt.textContent = `${latest.srtt || "0.000"}s`;
  valRto.textContent = `${latest.rto || "0.000"}s`;
  valWindow.textContent = String(latest.window_size || 4);
  valRetries.textContent = String(latest.retransmissions || 0);

  // Render Chunk Slots
  const total = latest.chunks_total || 5;
  const sent = latest.chunks_sent || 0;
  const acked = latest.chunks_acked || 0;

  let trackHtml = "";
  for (let i = 0; i < total; i++) {
    let slotClass = "chunk-slot";
    let slotText = `Chunk #${i + 1}`;
    if (i < acked) {
      slotClass += " acked";
      slotText += "<br>✓ ACKed";
    } else if (i < sent) {
      slotClass += " in-flight";
      slotText += "<br>⚡ In-Flight";
    } else {
      slotText += "<br>Pending";
    }
    trackHtml += `<div class="${slotClass}">${slotText}</div>`;
  }
  windowTrack.innerHTML = trackHtml;
}

// -----------------------------------------------------------------------------
// Event Console, Chat, and SOS Feeds
// -----------------------------------------------------------------------------

function renderEventLog(events) {
  eventCount.textContent = String(events.length);
  if (!events || events.length === 0) {
    eventConsole.innerHTML = '<div class="text-dim">No network events recorded yet...</div>';
    return;
  }

  eventConsole.innerHTML = events
    .map((ev) => {
      const timeStr = new Date(ev.timestamp * 1000).toTimeString().split(" ")[0];
      return `
        <div class="log-entry">
          <span class="log-time">${timeStr}</span>
          <span class="log-cat ${escapeHtml(ev.category)}">[${escapeHtml(ev.category)}]</span>
          <span class="log-msg">${escapeHtml(ev.summary)}</span>
        </div>
      `;
    })
    .join("");

  // Auto-scroll to bottom
  eventConsole.scrollTop = eventConsole.scrollHeight;
}

function renderChatMessages(messages) {
  chatCount.textContent = String(messages.length);
  if (!messages || messages.length === 0) {
    chatMessageFlow.innerHTML = '<div class="text-dim">No messages transmitted yet.</div>';
    return;
  }

  chatMessageFlow.innerHTML = messages
    .map((msg) => {
      const isOut = msg.is_outgoing;
      const timeStr = new Date(msg.timestamp * 1000).toLocaleTimeString();
      return `
        <div class="chat-bubble ${isOut ? 'outgoing' : 'incoming'}">
          <div class="chat-header">
            <span>${isOut ? `TO: ${escapeHtml(msg.destination || 'MESH')}` : `FROM: ${escapeHtml(msg.source)}`}</span>
            <span>${timeStr} ${msg.reliable ? '• Reliable (ACK)' : '• UDP'}</span>
          </div>
          <div class="chat-body">${escapeHtml(msg.text)}</div>
        </div>
      `;
    })
    .join("");

  chatMessageFlow.scrollTop = chatMessageFlow.scrollHeight;
}

function renderStatuses(statuses) {
  statusCount.textContent = String(statuses.length);
  if (!statuses || statuses.length === 0) {
    sosAlertList.innerHTML = '<div class="text-dim">No disaster status broadcasts received.</div>';
    return;
  }

  sosAlertList.innerHTML = statuses
    .map((s) => {
      const isSafe = s.status === "SAFE";
      const timeStr = new Date(s.timestamp * 1000).toLocaleTimeString();
      const loc = s.location ? ` • Lat: ${s.location.latitude}, Lon: ${s.location.longitude} (${s.location.label || ''})` : '';
      return `
        <div class="sos-card ${isSafe ? 'safe' : ''}">
          <div class="chat-header">
            <strong>${escapeHtml(s.status)} from ${escapeHtml(s.source)}</strong>
            <span>${timeStr}</span>
          </div>
          <div>${escapeHtml(s.message || 'No description')}</div>
          ${loc ? `<div class="text-dim font-mono text-xs mt-1">📍 ${escapeHtml(loc)}</div>` : ''}
        </div>
      `;
    })
    .join("");
}

// -----------------------------------------------------------------------------
// Interactive Action Handlers (Calling Phase 1 API)
// -----------------------------------------------------------------------------

async function handleSendMessage() {
  const destination = document.querySelector("#msgDestination").value.trim();
  const address = document.querySelector("#msgAddress").value.trim();
  const text = document.querySelector("#msgText").value.trim();
  const reliable = document.querySelector("#msgReliable").checked;

  if (!destination || !text) {
    showToast("Please enter destination and message", "error");
    return;
  }

  sendFeedbackText.innerHTML = `<span class="text-cyan">Transmitting packet to ${escapeHtml(destination)}...</span>`;

  try {
    const res = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destination,
        message: text,
        reliable,
        address: address || null,
      }),
    });
    const result = await res.json();

    if (result.sent) {
      const ackText = reliable ? (result.acknowledged ? "✓ ACK Received!" : "⚠ Retried / Unacknowledged") : "Dispatched over UDP";
      sendFeedbackText.innerHTML = `
        <span class="text-emerald">Delivered (Seq #${result.sequence_number || 1}) via ${result.next_hop || destination} [${ackText}]</span>
      `;
      showToast(`Packet sent to ${destination} (${ackText})`);
      if (lastKnownState) {
        animatePacketFlight(lastKnownState.node.node_id, result.next_hop || destination, "MSG");
      }
    } else {
      sendFeedbackText.innerHTML = `<span class="text-rose">Failed: ${escapeHtml(result.reason || "Unknown error")}</span>`;
      showToast(`Send failed: ${result.reason}`, "error");
    }
    await loadState();
  } catch (err) {
    sendFeedbackText.innerHTML = `<span class="text-rose">Network error: ${escapeHtml(err.message)}</span>`;
    showToast("Failed to reach dashboard server", "error");
  }
}

async function handleStartGbn() {
  const destination = document.querySelector("#gbnDestination").value.trim();
  const chunks = parseInt(document.querySelector("#gbnChunks").value, 10);
  const windowSize = parseInt(document.querySelector("#gbnWindowSize").value, 10);
  const adaptive = document.querySelector("#gbnAdaptive").checked;
  const payload = document.querySelector("#gbnPayload").value.trim();

  if (!destination) {
    showToast("Enter a destination node for GBN transfer", "error");
    return;
  }

  try {
    const res = await fetch("/api/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destination,
        message: payload,
        chunks,
        window_size: windowSize,
        adaptive,
      }),
    });
    const result = await res.json();
    if (result.started) {
      showToast(`Streaming ${chunks} chunks via GBN (window=${windowSize}, adaptive=${adaptive})`);
      if (lastKnownState) {
        animatePacketFlight(lastKnownState.node.node_id, destination, "GBN");
      }
    } else {
      showToast(`GBN start failed: ${result.reason}`, "error");
    }
    await loadState();
  } catch (err) {
    showToast("Failed to launch GBN transfer", "error");
  }
}

async function sendEmergencyStatus(status, message, lat, lon, label) {
  try {
    const res = await fetch("/api/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        message,
        latitude: lat,
        longitude: lon,
        location_label: label,
      }),
    });
    const result = await res.json();
    if (result.sent) {
      showToast(`Emergency alert broadcasted: [${status}]`);
    } else {
      showToast(`Alert failed: ${result.reason}`, "error");
    }
    await loadState();
  } catch (err) {
    showToast("Failed to broadcast emergency status", "error");
  }
}

async function switchRoutingAlgorithm(strategy) {
  try {
    const res = await fetch("/api/routing/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy }),
    });
    const result = await res.json();
    if (result.success) {
      showToast(`Switched routing protocol to ${result.strategy}`);
    } else {
      showToast(`Protocol switch failed: ${result.reason}`, "error");
    }
    await loadState();
  } catch (err) {
    showToast("Error switching routing algorithm", "error");
  }
}

async function applySimulation(lossRate, delay, jitter) {
  try {
    const res = await fetch("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        loss_rate: lossRate,
        delay: delay,
        jitter: jitter,
      }),
    });
    const result = await res.json();
    if (result.success) {
      showToast(`Impairment applied: loss=${(lossRate * 100).toFixed(0)}%, delay=${delay * 1000}ms`);
    }
    await loadState();
  } catch (err) {
    showToast("Error applying simulation impairment", "error");
  }
}

async function severNode(nodeId) {
  try {
    const res = await fetch("/api/chaos/node-fail", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: nodeId }),
    });
    const result = await res.json();
    if (result.success) {
      showToast(`Severed link to ${nodeId}! Triggered self-healing route pruning.`, "error");
    }
    await loadState();
  } catch (err) {
    showToast("Error simulating node failure", "error");
  }
}

// -----------------------------------------------------------------------------
// Utilities
// -----------------------------------------------------------------------------

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `
    <span>${type === "error" ? "🚨" : "⚡"}</span>
    <span>${escapeHtml(message)}</span>
  `;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
