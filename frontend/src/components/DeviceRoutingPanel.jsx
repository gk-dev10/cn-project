import React from 'react';

export default function DeviceRoutingPanel({ neighbors = [], routes = {}, updatedAt = '--:--:--' }) {
  const routeEntries = Object.entries(routes || {});

  return (
    <section className="panel sub-panel" aria-labelledby="networkStateTitle">
      <div className="panel-header">
        <h2 id="networkStateTitle">Discovered Devices & Routing Table</h2>
        <span className="timestamp-tag">{updatedAt}</span>
      </div>

      <div className="dual-columns">
        <div className="column-block">
          <div className="block-title">Nearby One-Hop Devices ({neighbors.length})</div>
          <div className="device-card-list">
            {neighbors.length === 0 ? (
              <div className="empty-hint text-dim">Scanning local network for beacons...</div>
            ) : (
              neighbors.map((n) => (
                <div key={n.node_id} className="device-card">
                  <div className="device-info">
                    <span className="device-id">{n.node_id}</span>
                    <span className="device-addr">{n.ip}:{n.port}</span>
                  </div>
                  <span className={`status-pill ${n.status === 'ACTIVE' ? 'status-active' : 'status-lost'}`}>
                    {n.status}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="column-block">
          <div className="block-title">Computed Multi-Hop Routes ({routeEntries.length})</div>
          <div className="route-table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Destination</th>
                  <th>Next Hop</th>
                  <th>Metric</th>
                </tr>
              </thead>
              <tbody>
                {routeEntries.length === 0 ? (
                  <tr>
                    <td colSpan="3" className="text-muted">No routes computed yet</td>
                  </tr>
                ) : (
                  routeEntries.map(([dst, route]) => (
                    <tr key={dst}>
                      <td className="text-cyan font-bold">{dst}</td>
                      <td>{route.next_hop || '-'}</td>
                      <td className="text-emerald">{route.cost || 1}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
