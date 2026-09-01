const stateUrl = "/api/state";

const nodeLine = document.querySelector("#nodeLine");
const networkStatus = document.querySelector("#networkStatus");
const topologySvg = document.querySelector("#topologySvg");
const neighborsEl = document.querySelector("#neighbors");
const routesEl = document.querySelector("#routes");
const metricsEl = document.querySelector("#metrics");
const statusesEl = document.querySelector("#statuses");
const neighborCount = document.querySelector("#neighborCount");
const routeCount = document.querySelector("#routeCount");
const statusCount = document.querySelector("#statusCount");
const updatedAt = document.querySelector("#updatedAt");

document.querySelector("#refreshBtn").addEventListener("click", loadState);
document.querySelector("#safeBtn").addEventListener("click", async () => {
  await fetch("/api/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "SAFE", message: "Dashboard broadcast" })
  });
  await loadState();
});

async function loadState() {
  const response = await fetch(stateUrl);
  const state = await response.json();
  renderState(state);
}

function renderState(state) {
  nodeLine.textContent = `${state.node.node_id} on ${state.node.ip}:${state.node.port}`;
  networkStatus.textContent = state.node.status;
  neighborCount.textContent = String(state.neighbors.length);
  const routes = Object.entries(state.routes);
  routeCount.textContent = String(routes.length);
  statusCount.textContent = String(state.statuses.length);
  updatedAt.textContent = new Date(state.generated_at * 1000).toLocaleTimeString();

  renderTopology(state.topology);
  renderNeighbors(state.neighbors);
  renderRoutes(routes);
  renderMetrics(state.metrics || {});
  renderStatuses(state.statuses);
}

function renderTopology(topology) {
  const width = 720;
  const height = 420;
  const nodes = topology.nodes || [];
  const links = topology.links || [];
  const positions = new Map(nodes.map((node) => [node.id, [node.x * width, node.y * height]]));
  const parts = [
    `<rect x="0" y="0" width="${width}" height="${height}" fill="#f8fafc"></rect>`
  ];

  for (const link of links) {
    const from = positions.get(link.source);
    const to = positions.get(link.target);
    if (!from || !to) continue;
    parts.push(
      `<line x1="${from[0]}" y1="${from[1]}" x2="${to[0]}" y2="${to[1]}" ` +
      `stroke="${link.active ? "#64748b" : "#cbd5e1"}" stroke-width="2"></line>`
    );
  }

  for (const node of nodes) {
    const pos = positions.get(node.id);
    if (!pos) continue;
    const fill = node.is_self ? "#2563eb" : node.status === "ACTIVE" ? "#16a34a" : "#d97706";
    parts.push(`<circle cx="${pos[0]}" cy="${pos[1]}" r="23" fill="${fill}" stroke="#0f172a" stroke-width="2"></circle>`);
    parts.push(`<text x="${pos[0]}" y="${pos[1] + 42}" text-anchor="middle" font-size="13" fill="#111827">${escapeHtml(node.id)}</text>`);
  }

  topologySvg.innerHTML = parts.join("");
}

function renderNeighbors(neighbors) {
  if (!neighbors.length) {
    neighborsEl.innerHTML = `<div class="empty">No neighbors</div>`;
    return;
  }
  neighborsEl.innerHTML = neighbors.map((neighbor) => `
    <div class="row">
      <div><strong>${escapeHtml(neighbor.node_id)}</strong><br><span>${escapeHtml(neighbor.ip)}:${neighbor.port}</span></div>
      <span>${escapeHtml(neighbor.status)}</span>
    </div>
  `).join("");
}

function renderRoutes(routes) {
  if (!routes.length) {
    routesEl.innerHTML = `<div class="empty">No routes</div>`;
    return;
  }
  routesEl.innerHTML = routes.map(([destination, route]) => `
    <div class="row">
      <div><strong>${escapeHtml(destination)}</strong><br><span>via ${escapeHtml(String(route.next_hop))}</span></div>
      <span>cost ${route.cost}</span>
    </div>
  `).join("");
}

function renderMetrics(metrics) {
  const entries = Object.entries(metrics);
  if (!entries.length) {
    metricsEl.innerHTML = `<div class="empty">No metrics yet</div>`;
    return;
  }
  metricsEl.innerHTML = entries.map(([key, value]) => `
    <div class="metric">
      <strong>${escapeHtml(String(value))}</strong>
      <span>${escapeHtml(key.replaceAll("_", " "))}</span>
    </div>
  `).join("");
}

function renderStatuses(statuses) {
  if (!statuses.length) {
    statusesEl.innerHTML = `<div class="empty">No status broadcasts</div>`;
    return;
  }
  statusesEl.innerHTML = statuses.slice(-6).reverse().map((status) => `
    <div class="row">
      <div><strong>${escapeHtml(status.source)}</strong><br><span>${escapeHtml(status.message || "")}</span></div>
      <span>${escapeHtml(status.status)}</span>
    </div>
  `).join("");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadState();
setInterval(loadState, 1500);

