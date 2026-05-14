import { useState } from 'react';
import { relativeTime } from '../utils/alertUi.js';

export default function SystemStatusPanel({ apiKeyConnected, backendOnline, workerOnline, lastRpcSync, alertThreshold = 70 }) {
  const [open, setOpen] = useState(false);

  return (
    <section className="system-status-panel">
      <button className="ghost-toggle" type="button" onClick={() => setOpen((value) => !value)}>
        System Status {open ? '▴' : '▾'}
      </button>
      {open && (
        <div className="system-status-grid">
          <span>{apiKeyConnected ? '✓' : '—'} API key connected</span>
          <span>{backendOnline ? '✓' : '—'} Backend online</span>
          <span>{workerOnline ? '✓' : '—'} Worker online</span>
          <span>◷ Last RPC sync: {lastRpcSync ? relativeTime(lastRpcSync) : '—'}</span>
          <span>⚠ Alerts threshold: {alertThreshold}</span>
        </div>
      )}
    </section>
  );
}
