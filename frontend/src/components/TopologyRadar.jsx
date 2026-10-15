import React from 'react';

export default function TopologyRadar({
  topology,
  routes,
  selfNodeId,
  routingStrategy,
  onSwitchStrategy,
  onSelectDestination,
  packetAnimations = [],
}) {
  const width = 860;
  const height = 460;
  const nodes = topology?.nodes || [];
  const links = topology?.links || [];

  const positions = new Map();
  nodes.forEach((n) => {
    positions.set(n.id, [n.x * width, n.y * height]);
  });

  // Calculate route hops to highlight
  const routeHopLinks = new Set();
  Object.entries(routes || {}).forEach(([dst, route]) => {
    const nextHop = route.next_hop;
    if (nextHop) {
      routeHopLinks.add(`${selfNodeId}->${nextHop}`);
      routeHopLinks.add(`${nextHop}->${selfNodeId}`);
    }
  });

  return (
    <section className="panel topology-panel" aria-labelledby="topologyTitle">
      <div className="panel-header">
        <div className="panel-header-left">
          <h2 id="topologyTitle">Live Mesh Topology & Radar</h2>
          <span className="panel-subtitle">Real-time link costs, node health, and multi-hop routing paths</span>
        </div>
        <div className="topology-controls">
          <button
            className={`btn-chip ${routingStrategy === 'LINK_STATE' ? 'active' : ''}`}
            onClick={() => onSwitchStrategy('LINK_STATE')}
            title="Switch to Link-State Routing (Dijkstra's Shortest Path)"
          >
            Dijkstra (LS)
          </button>
          <button
            className={`btn-chip ${routingStrategy === 'DISTANCE_VECTOR' ? 'active' : ''}`}
            onClick={() => onSwitchStrategy('DISTANCE_VECTOR')}
            title="Switch to Distance-Vector Routing (Bellman-Ford Algorithm)"
          >
            Bellman-Ford (DV)
          </button>
        </div>
      </div>

      <div className="canvas-wrapper">
        <svg id="topologySvg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Interactive mesh network topology">
          {/* Radar Grid Circles */}
          <circle cx={width / 2} cy={height / 2} r="90" fill="none" stroke="rgba(56, 189, 248, 0.05)" strokeWidth="1" />
          <circle cx={width / 2} cy={height / 2} r="180" fill="none" stroke="rgba(56, 189, 248, 0.05)" strokeWidth="1" />
          <circle cx={width / 2} cy={height / 2} r="270" fill="none" stroke="rgba(56, 189, 248, 0.03)" strokeWidth="1" />

          {/* Links */}
          {links.map((link, idx) => {
            const from = positions.get(link.source);
            const to = positions.get(link.target);
            if (!from || !to) return null;

            const isRouteHop = routeHopLinks.has(`${link.source}->${link.target}`);
            const strokeColor = isRouteHop ? '#a855f7' : link.active ? '#475569' : '#dc2626';
            const strokeWidth = isRouteHop ? 3 : 1.8;

            return (
              <g key={`link-${idx}`}>
                <line
                  x1={from[0]}
                  y1={from[1]}
                  x2={to[0]}
                  y2={to[1]}
                  stroke={strokeColor}
                  strokeWidth={strokeWidth}
                  className={isRouteHop ? 'topo-link' : ''}
                />
                <text
                  x={(from[0] + to[0]) / 2}
                  y={(from[1] + to[1]) / 2 - 6}
                  fill="#64748b"
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="10"
                  textAnchor="middle"
                >
                  cost: {link.cost || 1}
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const pos = positions.get(node.id);
            if (!pos) return null;
            const [cx, cy] = pos;

            const isSelf = node.is_self;
            const isActive = node.status === 'ACTIVE';
            const nodeColor = isSelf ? '#38bdf8' : isActive ? '#10b981' : '#f43f5e';

            return (
              <g
                key={`node-${node.id}`}
                className="topo-node"
                style={{ cursor: 'pointer' }}
                onClick={() => onSelectDestination && onSelectDestination(node.id)}
                title={`Click to target node ${node.id}`}
              >
                {/* Pulsing Halo */}
                <circle cx={cx} cy={cy} r="26" fill="none" stroke={nodeColor} strokeWidth="1" className="topo-node-ring" />

                {/* Center Disc */}
                <circle cx={cx} cy={cy} r="16" fill="#090f1b" stroke={nodeColor} strokeWidth="2.5" />

                {/* Node Label */}
                <text
                  x={cx}
                  y={cy + 30}
                  fill="#ffffff"
                  fontFamily="'Outfit', sans-serif"
                  fontWeight="700"
                  fontSize="12"
                  textAnchor="middle"
                >
                  {node.id} {isSelf ? '(YOU)' : ''}
                </text>
                <text
                  x={cx}
                  y={cy + 42}
                  fill="#94a3b8"
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="10"
                  textAnchor="middle"
                >
                  {node.ip}:{node.port}
                </text>
              </g>
            );
          })}

          {/* In-Flight Packet Particle Animations */}
          {packetAnimations.map((pkt, idx) => {
            const from = positions.get(pkt.from);
            const to = positions.get(pkt.to);
            if (!from || !to) return null;

            const curX = from[0] + (to[0] - from[0]) * pkt.progress;
            const curY = from[1] + (to[1] - from[1]) * pkt.progress;

            return (
              <g key={`pkt-anim-${idx}`}>
                <circle cx={curX} cy={curY} r="5" fill="#38bdf8" filter="drop-shadow(0 0 6px #38bdf8)" />
                <text
                  x={curX}
                  y={curY - 8}
                  fill="#38bdf8"
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="9"
                  fontWeight="bold"
                  textAnchor="middle"
                >
                  {pkt.label || 'PKT'}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="topology-legend">
          <span className="legend-item"><span className="legend-dot self"></span> Local Node</span>
          <span className="legend-item"><span className="legend-dot peer"></span> Discovered Peer</span>
          <span className="legend-item"><span className="legend-dot active-link"></span> Active Link</span>
          <span className="legend-item"><span className="legend-dot route-hop"></span> Next-Hop Route</span>
        </div>
      </div>
    </section>
  );
}
