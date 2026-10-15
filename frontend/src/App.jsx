import React, { useState, useEffect, useRef, useCallback } from 'react';
import Header from './components/Header';
import TopologyRadar from './components/TopologyRadar';
import ShowcaseDeck from './components/ShowcaseDeck';
import DeviceRoutingPanel from './components/DeviceRoutingPanel';
import TelemetryStream from './components/TelemetryStream';
import ToastContainer from './components/ToastContainer';

export default function App() {
  const [state, setState] = useState(null);
  const [isPolling, setIsPolling] = useState(true);
  const [selectedDestination, setSelectedDestination] = useState('');
  const [sendFeedback, setSendFeedback] = useState(null);
  const [packetAnimations, setPacketAnimations] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [localEvents, setLocalEvents] = useState([]);

  const animRef = useRef([]);
  animRef.current = packetAnimations;

  // Add toast helper
  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  // Packet flight animation
  const animatePacketFlight = useCallback((from, to, label = 'PKT') => {
    const id = Date.now() + Math.random();
    const duration = 1200; // ms
    const startTime = performance.now();

    const anim = { id, from, to, label, progress: 0.0 };
    setPacketAnimations((prev) => [...prev, anim]);

    function step(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(1.0, elapsed / duration);

      setPacketAnimations((prev) =>
        prev.map((a) => (a.id === id ? { ...a, progress } : a))
      );

      if (progress < 1.0) {
        requestAnimationFrame(step);
      } else {
        setPacketAnimations((prev) => prev.filter((a) => a.id !== id));
      }
    }
    requestAnimationFrame(step);
  }, []);

  // Fetch live state from backend
  const fetchState = useCallback(async () => {
    try {
      const res = await fetch('/api/state');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setState(data);
      if (data.events) {
        setLocalEvents(data.events);
      }
    } catch (err) {
      console.warn('Backend polling error:', err);
    }
  }, []);

  // Polling loop
  useEffect(() => {
    fetchState();
    if (!isPolling) return;
    const interval = setInterval(fetchState, 1500);
    return () => clearInterval(interval);
  }, [isPolling, fetchState]);

  // Action: Send Message
  const handleSendMessage = async ({ destination, text, reliable, address }) => {
    setSendFeedback({ text: `Transmitting packet to ${destination}...`, isError: false });
    try {
      const res = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination, message: text, reliable, address }),
      });
      const data = await res.json();

      if (data.sent) {
        const ackInfo = reliable
          ? data.acknowledged
            ? '✓ ACK Received!'
            : '⚠ Retried / Unacknowledged'
          : 'Dispatched over UDP';
        setSendFeedback({
          text: `Delivered (Seq #${data.sequence_number || 1}) via ${data.next_hop || destination} [${ackInfo}]`,
          isError: !data.acknowledged && reliable,
        });
        addToast(`Packet transmitted to ${destination} (${ackInfo})`);
        if (state?.node?.node_id) {
          animatePacketFlight(state.node.node_id, data.next_hop || destination, 'MSG');
        }
      } else {
        setSendFeedback({ text: `Failed: ${data.reason}`, isError: true });
        addToast(`Send failed: ${data.reason}`, 'error');
      }
      fetchState();
    } catch (err) {
      setSendFeedback({ text: `Network error: ${err.message}`, isError: true });
      addToast('Failed to reach node server', 'error');
    }
  };

  // Action: Start GBN
  const handleStartGbn = async ({ destination, message, chunks, window_size, adaptive }) => {
    try {
      const res = await fetch('/api/transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination, message, chunks, window_size, adaptive }),
      });
      const data = await res.json();
      if (data.started) {
        addToast(`Streaming ${chunks} chunks via GBN (window=${window_size}, adaptive=${adaptive})`);
        if (state?.node?.node_id) {
          animatePacketFlight(state.node.node_id, destination, 'GBN');
        }
      } else {
        addToast(`GBN launch failed: ${data.reason}`, 'error');
      }
      fetchState();
    } catch (err) {
      addToast('Failed to start GBN transfer', 'error');
    }
  };

  // Action: Send File (Module 19)
  const handleSendFile = async ({ destination, filePath }) => {
    try {
      const res = await fetch('/api/file/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination, file_path: filePath }),
      });
      const data = await res.json();
      if (data.started) {
        addToast(`Sending file '${data.file_name}' to ${destination}...`);
        if (state?.node?.node_id) {
          animatePacketFlight(state.node.node_id, destination, 'FILE');
        }
      } else {
        addToast(`File transfer failed: ${data.reason}`, 'error');
      }
      fetchState();
    } catch (err) {
      addToast('Error starting file transfer', 'error');
    }
  };

  // Action: Broadcast SOS
  const handleBroadcastSos = async ({ status, message, latitude, longitude, location_label }) => {
    try {
      const res = await fetch('/api/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, message, latitude, longitude, location_label }),
      });
      const data = await res.json();
      if (data.sent) {
        addToast(`Emergency alert broadcasted: [${status}]`);
      } else {
        addToast(`Alert failed: ${data.reason}`, 'error');
      }
      fetchState();
    } catch (err) {
      addToast('Failed to broadcast status', 'error');
    }
  };

  // Action: Switch Routing Protocol
  const handleSwitchStrategy = async (strategy) => {
    try {
      const res = await fetch('/api/routing/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy }),
      });
      const data = await res.json();
      if (data.success) {
        addToast(`Switched routing protocol to ${data.strategy}`);
      } else {
        addToast(`Protocol switch failed: ${data.reason}`, 'error');
      }
      fetchState();
    } catch (err) {
      addToast('Error switching routing strategy', 'error');
    }
  };

  // Action: Apply Simulation Impairment
  const handleApplyImpairment = async ({ lossRate, delaySec }) => {
    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loss_rate: lossRate, delay: delaySec, jitter: 0.01 }),
      });
      const data = await res.json();
      if (data.success) {
        addToast(`Impairment applied: loss=${(lossRate * 100).toFixed(0)}%, delay=${delaySec * 1000}ms`);
      }
      fetchState();
    } catch (err) {
      addToast('Error applying impairment', 'error');
    }
  };

  // Action: Sever Node
  const handleSeverNode = async (nodeId) => {
    try {
      const res = await fetch('/api/chaos/node-fail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_id: nodeId }),
      });
      const data = await res.json();
      if (data.success) {
        addToast(`Severed link to ${nodeId}! Triggered self-healing route pruning.`, 'error');
      }
      fetchState();
    } catch (err) {
      addToast('Error simulating node failure', 'error');
    }
  };

  const updatedAtStr = state?.generated_at
    ? new Date(state.generated_at * 1000).toLocaleTimeString()
    : '--:--:--';

  return (
    <div className="meshlink-app">
      <Header
        state={state}
        isPolling={isPolling}
        onTogglePolling={() => setIsPolling(!isPolling)}
        onQuickSafe={() =>
          handleBroadcastSos({ status: 'SAFE', message: 'Quick safe beacon from React mission control' })
        }
        onRefresh={() => {
          fetchState();
          addToast('Telemetry synchronized');
        }}
      />

      <main className="dashboard-grid">
        {/* CENTER TOP: Interactive Animated Topology Visualizer */}
        <TopologyRadar
          topology={state?.topology}
          routes={state?.routes}
          selfNodeId={state?.node?.node_id}
          routingStrategy={state?.routing_strategy || 'LINK_STATE'}
          onSwitchStrategy={handleSwitchStrategy}
          onSelectDestination={(id) => setSelectedDestination(id)}
          packetAnimations={packetAnimations}
        />

        {/* RIGHT TOP: Showcase Evaluation Deck */}
        <ShowcaseDeck
          state={state}
          selectedDestination={selectedDestination}
          onSendMessage={handleSendMessage}
          onStartGbn={handleStartGbn}
          onBroadcastSos={handleBroadcastSos}
          onApplyImpairment={handleApplyImpairment}
          onSeverNode={handleSeverNode}
          onSendFile={handleSendFile}
          sendFeedback={sendFeedback}
        />

        {/* BOTTOM LEFT: Nearby Devices & Computed Routing Table */}
        <DeviceRoutingPanel
          neighbors={state?.neighbors || []}
          routes={state?.routes || {}}
          updatedAt={updatedAtStr}
        />

        {/* BOTTOM RIGHT: Live Event Console, Chat, & Emergency Alert Feed */}
        <TelemetryStream
          events={localEvents}
          messages={state?.messages || []}
          statuses={state?.statuses || []}
          onClearEvents={() => setLocalEvents([])}
        />
      </main>

      <ToastContainer toasts={toasts} />
    </div>
  );
}
