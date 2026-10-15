import React from 'react';
import { Shield, Radio, Activity, RefreshCw, Pause } from 'lucide-react';

export default function Header({
  state,
  isPolling,
  onTogglePolling,
  onQuickSafe,
  onRefresh,
}) {
  const node = state?.node || { node_id: 'CONNECTING...', ip: '127.0.0.1', port: 5002, status: 'UNKNOWN' };
  const neighborCount = state?.neighbors?.length || 0;
  const routeCount = Object.keys(state?.routes || {}).length;
  const lossRate = state?.simulation?.loss_rate ? (state.simulation.loss_rate * 100).toFixed(1) : '0.0';
  const routingStrat = state?.routing_strategy === 'DISTANCE_VECTOR' ? 'Distance-Vector (Bellman-Ford)' : 'Link-State (Dijkstra)';

  return (
    <header className="topbar">
      <div className="topbar-branding">
        <div className="logo-mark">
          <span className="radar-dot"></span>
          <Radio size={22} className="text-cyan" />
        </div>
        <div>
          <div className="title-row">
            <h1>MeshLink</h1>
            <span className="product-label">Network operations</span>
            <span className={`badge ${state?.routing_strategy === 'DISTANCE_VECTOR' ? 'badge-accent' : 'badge-neutral'}`}>
              {routingStrat}
            </span>
          </div>
          <p className="node-meta">
            Node: <strong>{node.node_id}</strong> on {node.ip}:{node.port}
          </p>
        </div>
      </div>

      <div className="topbar-telemetry">
        <div className="telemetry-item">
          <span className="telemetry-label">Active Peers</span>
          <span className="telemetry-value text-emerald">{neighborCount}</span>
        </div>
        <div className="telemetry-item">
          <span className="telemetry-label">Known Routes</span>
          <span className="telemetry-value text-cyan">{routeCount}</span>
        </div>
        <div className="telemetry-item">
          <span className="telemetry-label">Channel Loss</span>
          <span className="telemetry-value text-amber">{lossRate}%</span>
        </div>
        <div className="telemetry-item">
          <span className="telemetry-label">Status</span>
          <span className={`status-pill ${node.status === 'ACTIVE' ? 'status-active' : 'status-lost'}`}>
            <Activity size={12} /> {node.status}
          </span>
        </div>
      </div>

      <div className="topbar-actions">
        <button
          type="button"
          className={`btn ${isPolling ? 'btn-secondary' : 'btn-chip'}`}
          onClick={onTogglePolling}
          aria-label={isPolling ? 'Pause automatic telemetry sync' : 'Resume automatic telemetry sync'}
        >
          {isPolling ? (
            <>
              <span className="pulse-indicator"></span> Auto-Sync: ON
            </>
          ) : (
            <>
              <Pause size={13} /> Auto-Sync: PAUSED
            </>
          )}
        </button>

        <button type="button" className="btn btn-chip" onClick={onRefresh} aria-label="Sync telemetry now">
          <RefreshCw size={13} /> <span className="button-label">Sync</span>
        </button>

        <button type="button" className="btn btn-emerald" onClick={onQuickSafe} title="Broadcast SAFE status to all peers">
          <Shield size={14} /> I'm Safe
        </button>
      </div>
    </header>
  );
}
