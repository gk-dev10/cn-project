import React, { useState } from 'react';
import { Send, Zap, AlertTriangle, Flame, ShieldAlert, Cpu } from 'lucide-react';

export default function ShowcaseDeck({
  state,
  selectedDestination,
  onSendMessage,
  onStartGbn,
  onBroadcastSos,
  onApplyImpairment,
  onSeverNode,
  onSendFile,
  sendFeedback,
}) {
  const [activeTab, setActiveTab] = useState('messaging');

  // Tab 1 State
  const [destination, setDestination] = useState(selectedDestination || '');
  const [address, setAddress] = useState('');
  const [messageText, setMessageText] = useState('Need status update from forward outpost');
  const [reliable, setReliable] = useState(true);

  // Tab 2 State (GBN & File Transfer)
  const [gbnDest, setGbnDest] = useState(selectedDestination || '');
  const [gbnChunks, setGbnChunks] = useState(6);
  const [gbnWindowSize, setGbnWindowSize] = useState(4);
  const [gbnPayload, setGbnPayload] = useState('Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliet');
  const [gbnAdaptive, setGbnAdaptive] = useState(true);
  const [filePath, setFilePath] = useState('README.md');

  // Tab 3 State (SOS)
  const [sosMsg, setSosMsg] = useState('Medical triage station operational in Sector 4');
  const [sosLat, setSosLat] = useState(12.9716);
  const [sosLon, setSosLon] = useState(77.5946);
  const [sosLabel, setSosLabel] = useState('Shelter 4');

  // Tab 4 State (Chaos)
  const [lossRate, setLossRate] = useState(0);
  const [delayMs, setDelayMs] = useState(0);
  const [severNodeId, setSeverNodeId] = useState('');

  // Sync destination if selected from topology
  React.useEffect(() => {
    if (selectedDestination) {
      setDestination(selectedDestination);
      setGbnDest(selectedDestination);
    }
  }, [selectedDestination]);

  const latestTransfer = state?.transfers?.[0];

  const handleMessageSubmit = (e) => {
    e.preventDefault();
    if (!destination || !messageText) return;
    onSendMessage({ destination, text: messageText, reliable, address: address || null });
  };

  const handleGbnSubmit = (e) => {
    e.preventDefault();
    if (!gbnDest) return;
    onStartGbn({
      destination: gbnDest,
      message: gbnPayload,
      chunks: parseInt(gbnChunks, 10),
      window_size: parseInt(gbnWindowSize, 10),
      adaptive: gbnAdaptive,
    });
  };

  const handleCustomSos = (e) => {
    e.preventDefault();
    onBroadcastSos({
      status: 'CRITICAL_SOS',
      message: sosMsg,
      latitude: parseFloat(sosLat),
      longitude: parseFloat(sosLon),
      location_label: sosLabel,
    });
  };

  return (
    <section className="panel control-deck-panel" aria-labelledby="controlTitle">
      <div className="panel-header">
        <div>
          <h2 id="controlTitle">Showcase Evaluation Deck</h2>
          <span className="panel-subtitle">Interactive controls for professor demonstration</span>
        </div>
      </div>

      {/* Showcase Tabs */}
      <nav className="showcase-tabs" role="tablist">
        <button
          className={`tab-btn ${activeTab === 'messaging' ? 'active' : ''}`}
          onClick={() => setActiveTab('messaging')}
        >
          1. Message & Relay
        </button>
        <button
          className={`tab-btn ${activeTab === 'gbn' ? 'active' : ''}`}
          onClick={() => setActiveTab('gbn')}
        >
          2. Sliding Window
        </button>
        <button
          className={`tab-btn ${activeTab === 'emergency' ? 'active' : ''}`}
          onClick={() => setActiveTab('emergency')}
        >
          3. Disaster SOS
        </button>
        <button
          className={`tab-btn ${activeTab === 'chaos' ? 'active' : ''}`}
          onClick={() => setActiveTab('chaos')}
        >
          4. Chaos & Healing
        </button>
      </nav>

      <div className="tab-content-area">
        {/* TAB 1: Direct & Multi-Hop Messaging */}
        {activeTab === 'messaging' && (
          <div className="tab-pane active">
            <h3 className="pane-title">Direct & Multi-Hop Messaging (Modules 3, 6, 16)</h3>
            <p className="pane-desc">
              Test stop-and-wait reliable delivery with retries or test multi-hop packet forwarding across intermediate nodes.
            </p>

            <form onSubmit={handleMessageSubmit} className="control-form">
              <div className="form-row">
                <div className="form-group flex-1">
                  <label>Destination Node ID</label>
                  <input
                    type="text"
                    value={destination}
                    onChange={(e) => setDestination(e.target.value)}
                    placeholder="e.g. DEVICE_B or C"
                    required
                  />
                </div>
                <div className="form-group flex-1">
                  <label>Override IP:Port (Optional)</label>
                  <input
                    type="text"
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="e.g. 127.0.0.1:5003"
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Message Payload</label>
                <input
                  type="text"
                  value={messageText}
                  onChange={(e) => setMessageText(e.target.value)}
                  placeholder="Enter message to transmit through mesh..."
                  required
                />
              </div>

              <div className="form-row items-center">
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={reliable}
                    onChange={(e) => setReliable(e.target.checked)}
                  />
                  <span className="slider"></span>
                  <span className="toggle-label">Reliable Mode (ACK Retransmission)</span>
                </label>
                <button type="submit" className="btn btn-primary ml-auto">
                  <Send size={13} /> Transmit Packet
                </button>
              </div>
            </form>

            <div className="quick-status-box">
              <span className="box-label">Transmission Status:</span>
              <span className={sendFeedback?.isError ? 'text-rose' : 'text-emerald'}>
                {sendFeedback?.text || 'Awaiting transmission command...'}
              </span>
            </div>
          </div>
        )}

        {/* TAB 2: Go-Back-N & Adaptive AIMD Window */}
        {activeTab === 'gbn' && (
          <div className="tab-pane active">
            <h3 className="pane-title">Sliding Window & AIMD Congestion Control (Modules 8 & 9)</h3>
            <p className="pane-desc">
              Pipelined chunk transmission with Go-Back-N retransmission and dynamic AIMD window tuning.
            </p>

            <form onSubmit={handleGbnSubmit} className="control-form">
              <div className="form-row">
                <div className="form-group flex-1">
                  <label>Destination Node</label>
                  <input
                    type="text"
                    value={gbnDest}
                    onChange={(e) => setGbnDest(e.target.value)}
                    placeholder="e.g. DEVICE_B"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Total Chunks</label>
                  <input
                    type="number"
                    min="2"
                    max="20"
                    value={gbnChunks}
                    onChange={(e) => setGbnChunks(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Window Size</label>
                  <input
                    type="number"
                    min="1"
                    max="8"
                    value={gbnWindowSize}
                    onChange={(e) => setGbnWindowSize(e.target.value)}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Payload to Chunk & Stream</label>
                <input
                  type="text"
                  value={gbnPayload}
                  onChange={(e) => setGbnPayload(e.target.value)}
                />
              </div>

              <div className="form-row items-center">
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={gbnAdaptive}
                    onChange={(e) => setGbnAdaptive(e.target.checked)}
                  />
                  <span className="slider"></span>
                  <span className="toggle-label">Enable Adaptive Window Control (AIMD)</span>
                </label>
                <button type="submit" className="btn btn-primary ml-auto">
                  <Zap size={13} /> Stream Chunks
                </button>
              </div>
            </form>

            {/* Sliding Window Monitor */}
            <div className="window-monitor-box">
              <div className="box-header">
                <span>Active Window Pipeline</span>
                <span className={`badge ${latestTransfer?.status === 'completed' ? 'badge-emerald' : latestTransfer?.status === 'running' ? 'badge-accent' : 'badge-neutral'}`}>
                  {latestTransfer?.status?.toUpperCase() || 'IDLE'}
                </span>
              </div>
              <div className="window-track">
                {latestTransfer ? (
                  Array.from({ length: latestTransfer.chunks_total || 5 }).map((_, idx) => {
                    const isAcked = idx < (latestTransfer.chunks_acked || 0);
                    const isInFlight = !isAcked && idx < (latestTransfer.chunks_sent || 0);
                    let cls = 'chunk-slot';
                    let label = 'Pending';
                    if (isAcked) {
                      cls += ' acked';
                      label = '✓ ACKed';
                    } else if (isInFlight) {
                      cls += ' in-flight';
                      label = '⚡ In-Flight';
                    }
                    return (
                      <div key={idx} className={cls}>
                        <span>Chunk #{idx + 1}</span>
                        <span>{label}</span>
                      </div>
                    );
                  })
                ) : (
                  <div className="chunk-slot">Idle</div>
                )}
              </div>
              <div className="telemetry-mini-row">
                <span>SRTT: <strong>{latestTransfer?.srtt || '0.000'}s</strong></span>
                <span>RTO: <strong>{latestTransfer?.rto || '0.000'}s</strong></span>
                <span>Window ($W$): <strong>{latestTransfer?.window_size || 4}</strong></span>
                <span>Retries: <strong>{latestTransfer?.retransmissions || 0}</strong></span>
              </div>
            </div>

            {/* Module 19: Chunked File Transfer */}
            <div className="quick-status-box mt-3">
              <span className="box-label">Module 19: File Transfer & SHA256 Integrity Verification:</span>
              <div className="form-row mt-1 items-center">
                <input
                  type="text"
                  value={filePath}
                  onChange={(e) => setFilePath(e.target.value)}
                  placeholder="File path (e.g. README.md)"
                  className="flex-1"
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onSendFile && onSendFile({ destination: gbnDest || 'DEVICE_B', filePath })}
                >
                  📁 Send File
                </button>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: Emergency SOS & Disaster GPS */}
        {activeTab === 'emergency' && (
          <div className="tab-pane active">
            <h3 className="pane-title">Disaster Emergency Broadcast & GPS (Modules 20 & 21)</h3>
            <p className="pane-desc">
              Broadcast emergency status across all mesh nodes with duplicate-suppression and geographic telemetry.
            </p>

            <div className="quick-alert-buttons">
              <button
                className="btn btn-emerald-soft btn-sos"
                onClick={() => onBroadcastSos({ status: 'SAFE', message: 'All personnel accounted for' })}
              >
                🟢 Broadcast SAFE
              </button>
              <button
                className="btn btn-amber-soft btn-sos"
                onClick={() => onBroadcastSos({ status: 'NEED_SUPPLIES', message: 'Power generator low on fuel' })}
              >
                🟡 Need Supplies
              </button>
              <button
                className="btn btn-red-soft btn-sos"
                onClick={() => onBroadcastSos({ status: 'CRITICAL_SOS', message: 'Structural collapse near sector 3' })}
              >
                🔴 CRITICAL SOS
              </button>
            </div>

            <form onSubmit={handleCustomSos} className="control-form mt-3">
              <div className="form-group">
                <label>Emergency Situation Report</label>
                <input
                  type="text"
                  value={sosMsg}
                  onChange={(e) => setSosMsg(e.target.value)}
                  placeholder="Specific situation details..."
                />
              </div>
              <div className="form-row">
                <div className="form-group flex-1">
                  <label>Latitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    value={sosLat}
                    onChange={(e) => setSosLat(e.target.value)}
                  />
                </div>
                <div className="form-group flex-1">
                  <label>Longitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    value={sosLon}
                    onChange={(e) => setSosLon(e.target.value)}
                  />
                </div>
                <div className="form-group flex-1">
                  <label>Location Tag</label>
                  <input
                    type="text"
                    value={sosLabel}
                    onChange={(e) => setSosLabel(e.target.value)}
                  />
                </div>
              </div>
              <button type="submit" className="btn btn-red w-full">
                <AlertTriangle size={14} /> Transmit Emergency Broadcast
              </button>
            </form>
          </div>
        )}

        {/* TAB 4: Chaos & Self-Healing */}
        {activeTab === 'chaos' && (
          <div className="tab-pane active">
            <h3 className="pane-title">Impairment Simulation & Self-Healing (Modules 22 & 23)</h3>
            <p className="pane-desc">
              Inject artificial packet drop and latency, or simulate a severed node link to prove self-healing route pruning.
            </p>

            <div className="chaos-controls">
              <div className="slider-group">
                <div className="slider-label">
                  <span>Packet Drop Rate:</span>
                  <strong>{lossRate}%</strong>
                </div>
                <input
                  type="range"
                  min="0"
                  max="60"
                  step="5"
                  value={lossRate}
                  onChange={(e) => setLossRate(e.target.value)}
                />
              </div>

              <div className="slider-group">
                <div className="slider-label">
                  <span>Artificial Delay:</span>
                  <strong>{delayMs} ms</strong>
                </div>
                <input
                  type="range"
                  min="0"
                  max="400"
                  step="20"
                  value={delayMs}
                  onChange={(e) => setDelayMs(e.target.value)}
                />
              </div>

              <div className="form-row mt-2">
                <button
                  type="button"
                  className="btn btn-secondary flex-1"
                  onClick={() => onApplyImpairment({ lossRate: parseFloat(lossRate) / 100, delaySec: parseFloat(delayMs) / 1000 })}
                >
                  <Flame size={13} /> Apply Impairments
                </button>
                <button
                  type="button"
                  className="btn btn-chip"
                  onClick={() => {
                    setLossRate(0);
                    setDelayMs(0);
                    onApplyImpairment({ lossRate: 0, delaySec: 0 });
                  }}
                >
                  Reset
                </button>
              </div>
            </div>

            <div className="sever-box mt-3">
              <span className="box-label">Simulate Node Failure (Demonstrate Self-Healing):</span>
              <div className="form-row mt-1">
                <select
                  value={severNodeId}
                  onChange={(e) => setSeverNodeId(e.target.value)}
                  className="flex-1"
                >
                  <option value="">-- Choose node to drop --</option>
                  {(state?.neighbors || []).map((n) => (
                    <option key={n.node_id} value={n.node_id}>
                      {n.node_id} ({n.ip}:{n.port})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-red"
                  onClick={() => {
                    if (severNodeId) onSeverNode(severNodeId);
                  }}
                >
                  ✂️ Sever Node
                </button>
              </div>
              <p className="hint-text">
                Watch the network topology immediately re-converge and purge broken routes!
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
