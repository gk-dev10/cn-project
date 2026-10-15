import React, { useState, useRef, useEffect } from 'react';

export default function TelemetryStream({
  events = [],
  messages = [],
  statuses = [],
  onClearEvents,
}) {
  const [activeFeed, setActiveFeed] = useState('events');
  const eventConsoleRef = useRef(null);
  const chatFlowRef = useRef(null);

  // Auto-scroll when new items arrive
  useEffect(() => {
    if (activeFeed === 'events' && eventConsoleRef.current) {
      eventConsoleRef.current.scrollTop = eventConsoleRef.current.scrollHeight;
    }
  }, [events, activeFeed]);

  useEffect(() => {
    if (activeFeed === 'chat' && chatFlowRef.current) {
      chatFlowRef.current.scrollTop = chatFlowRef.current.scrollHeight;
    }
  }, [messages, activeFeed]);

  return (
    <section className="panel sub-panel" aria-labelledby="telemetryTitle">
      <div className="panel-header">
        <div className="tab-header-pills" role="group" aria-label="Telemetry feeds">
          <button
            type="button"
            className={`pill-btn ${activeFeed === 'events' ? 'active' : ''}`}
            onClick={() => setActiveFeed('events')}
            aria-pressed={activeFeed === 'events'}
          >
            System Event Log ({events.length})
          </button>
          <button
            type="button"
            className={`pill-btn ${activeFeed === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveFeed('chat')}
            aria-pressed={activeFeed === 'chat'}
          >
            Decentralized Chat ({messages.length})
          </button>
          <button
            type="button"
            className={`pill-btn ${activeFeed === 'sos' ? 'active' : ''}`}
            onClick={() => setActiveFeed('sos')}
            aria-pressed={activeFeed === 'sos'}
          >
            Disaster SOS Alerts ({statuses.length})
          </button>
        </div>
        {activeFeed === 'events' && (
          <button type="button" className="btn-chip" onClick={onClearEvents} title="Clear console">
            Clear
          </button>
        )}
      </div>

      <div className="feed-container">
        {/* System Event Log */}
        {activeFeed === 'events' && (
          <div className="feed-pane">
            <div ref={eventConsoleRef} className="terminal-log-flow">
              {events.length === 0 ? (
                <div className="text-dim">No network events recorded yet...</div>
              ) : (
                events.map((ev, idx) => {
                  const timeStr = new Date(ev.timestamp * 1000).toTimeString().split(' ')[0];
                  return (
                    <div key={ev.id || idx} className="log-entry">
                      <span className="log-time">{timeStr}</span>
                      <span className={`log-cat ${ev.category}`}>[{ev.category}]</span>
                      <span className="log-msg">{ev.summary}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Decentralized Chat */}
        {activeFeed === 'chat' && (
          <div className="feed-pane">
            <div ref={chatFlowRef} className="chat-message-flow">
              {messages.length === 0 ? (
                <div className="text-dim">No messages transmitted yet.</div>
              ) : (
                messages.map((msg, idx) => {
                  const isOut = msg.is_outgoing;
                  const timeStr = new Date(msg.timestamp * 1000).toLocaleTimeString();
                  return (
                    <div key={msg.id || idx} className={`chat-bubble ${isOut ? 'outgoing' : 'incoming'}`}>
                      <div className="chat-header">
                        <span>{isOut ? `TO: ${msg.destination || 'MESH'}` : `FROM: ${msg.source}`}</span>
                        <span>{timeStr} {msg.reliable ? '• Reliable (ACK)' : '• UDP'}</span>
                      </div>
                      <div className="chat-body">{msg.text}</div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Disaster SOS Alerts */}
        {activeFeed === 'sos' && (
          <div className="feed-pane">
            <div className="sos-alert-flow">
              {statuses.length === 0 ? (
                <div className="text-dim">No disaster status broadcasts received.</div>
              ) : (
                statuses.map((s, idx) => {
                  const isSafe = s.status === 'SAFE';
                  const timeStr = new Date(s.timestamp * 1000).toLocaleTimeString();
                  const loc = s.location
                    ? ` • Lat: ${s.location.latitude}, Lon: ${s.location.longitude} (${s.location.label || ''})`
                    : '';
                  return (
                    <div key={idx} className={`sos-card ${isSafe ? 'safe' : ''}`}>
                      <div className="chat-header">
                        <strong>{s.status} from {s.source}</strong>
                        <span>{timeStr}</span>
                      </div>
                      <div>{s.message || 'No description provided'}</div>
                      {loc && <div className="text-dim font-mono text-xs mt-1">📍 {loc}</div>}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
