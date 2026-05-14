import { relativeTime } from '../utils/alertUi.js';

export default function WorkerStatusBar({ online, lastSignalAt, protocolCount }) {
  const lastSeen = lastSignalAt ? relativeTime(lastSignalAt) : '—';
  const secondsSinceSignal = lastSignalAt ? Math.floor((Date.now() - new Date(lastSignalAt).getTime()) / 1000) : Infinity;
  const workerOnline = online && secondsSinceSignal <= 30;

  return (
    <section className="worker-status-bar">
      <span className={`worker-state ${workerOnline ? 'online' : 'offline'}`}>
        <span className="status-dot-symbol">{workerOnline ? '●' : '●'}</span>
        {workerOnline ? 'Worker running' : 'Worker offline'}
      </span>
      <span>Last checked {lastSeen}</span>
      <span>{protocolCount} protocols monitored</span>
    </section>
  );
}
