import { useCallback, useEffect, useMemo, useState } from 'react';
import { addProtocol, getAlerts, getHealth, getProtocols, getTransactions, setStoredApiKey } from '../api.js';
import AlertDetailModal from '../components/AlertDetailModal.jsx';
import AlertFeed, { copyAlertSummary, downloadAlertJson } from '../components/AlertFeed.jsx';
import Header from '../components/Header.jsx';
import ProtocolCard from '../components/ProtocolCard.jsx';
import SystemStatusPanel from '../components/SystemStatusPanel.jsx';
import TransactionRow from '../components/TransactionRow.jsx';
import WorkerStatusBar from '../components/WorkerStatusBar.jsx';

export default function Dashboard() {
  const [protocols, setProtocols] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [online, setOnline] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [lastSignalAt, setLastSignalAt] = useState(null);
  const [now, setNow] = useState(Date.now());
  const [selectedAlert, setSelectedAlert] = useState(null);
  const [savedApiKey, setSavedApiKey] = useState(sessionStorage.getItem('talosly_api_key') || localStorage.getItem('talosly_api_key') || '');
  const [apiKeyDraft, setApiKeyDraft] = useState(savedApiKey);

  const activeProtocol = useMemo(() => protocols.find((item) => item.is_active) || protocols[0], [protocols]);
  const workerOnline = online && lastSignalAt && Math.floor((now - new Date(lastSignalAt).getTime()) / 1000) <= 30;

  const load = useCallback(async () => {
    try {
      await getHealth();
      setOnline(true);
      const nextProtocols = await getProtocols();
      setProtocols(nextProtocols);
      const selected = nextProtocols.find((item) => item.is_active) || nextProtocols[0];
      setTransactions(await getTransactions(selected?.id, 50));
      setAlerts(await getAlerts(12));
      const timestamp = new Date();
      setLastUpdated(timestamp.toLocaleTimeString());
      setLastSignalAt(timestamp.toISOString());
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  async function handleAdd(payload) {
    await addProtocol(payload);
    await load();
  }

  function handleDemoAlert() {
    const timestamp = new Date().toISOString();
    const demoAlert = {
      id: `demo-${timestamp}`,
      demo: true,
      protocol_name: 'Euler Finance',
      protocol: 'Euler Finance',
      tx_hash: '0xc310a0af...demo',
      txHash: '0xc310a0af...demo',
      risk_score: 96,
      riskScore: 96,
      risk_summary: 'Flash loan + price manipulation + full drain pattern',
      reason: 'Flash loan + price manipulation + full drain pattern',
      from_address: '0xb66cd966...attacker',
      to_address: '0x313ce567...euler_vault',
      value: '197M DAI',
      ai_summary: 'This transaction matches the March 2023 Euler Finance exploit pattern. A flash loan was used to manipulate the donateToReserves function, draining ~$197M across multiple assets.',
      risk_factors: ['Flash loan', 'Price manipulation', 'Full drain pattern'],
      created_at: timestamp,
      timestamp,
    };
    setAlerts((current) => [demoAlert, ...current]);
    setLastSignalAt(timestamp);
    setSelectedAlert(demoAlert);
  }

  return (
    <main className="app-shell">
      <Header online={online} lastUpdated={lastUpdated} onDemoAlert={handleDemoAlert} />
      <WorkerStatusBar online={online} lastSignalAt={lastSignalAt} protocolCount={protocols.length} />
      {!savedApiKey && (
        <section className="panel key-panel">
          <div>
            <div className="panel-label">Beta API key required</div>
            <h2>Connect your Talosly beta key</h2>
          </div>
          <form className="add-form" onSubmit={(event) => {
            event.preventDefault();
            const cleaned = apiKeyDraft.trim();
            setStoredApiKey(cleaned);
            setSavedApiKey(cleaned);
            load();
          }}>
            <input value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} placeholder="tals_..." required />
            <button type="submit">Use Key</button>
          </form>
        </section>
      )}
      {savedApiKey && (
        <section className="panel key-panel compact-key-panel">
          <div>
            <div className="panel-label">Beta API key connected</div>
            <p className="mono">{`${savedApiKey.slice(0, 9)}...${savedApiKey.slice(-6)}`}</p>
          </div>
          <button onClick={() => {
            setStoredApiKey('');
            setSavedApiKey('');
            setApiKeyDraft('');
          }}>Change Key</button>
        </section>
      )}
      {savedApiKey ? (
        <ProtocolCard protocol={activeProtocol} transactionCount={transactions.length} onAdd={handleAdd} />
      ) : (
        <section className="panel">
          <div className="panel-label">Protocol monitoring locked</div>
          <h2>Enter and save your beta API key first.</h2>
        </section>
      )}
      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-label">Live transaction feed</div>
            <h2>Recent transactions for {activeProtocol?.name || 'selected protocol'}</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>TX Hash</th>
                <th>From</th>
                <th>Value ETH</th>
                <th>Risk Score</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {transactions.length === 0 ? (
                <tr><td colSpan="5" className="empty-row">Monitoring active. No new transactions detected for this protocol yet.</td></tr>
              ) : (
                transactions.map((tx) => <TransactionRow tx={tx} key={tx.id} />)
              )}
            </tbody>
          </table>
        </div>
      </section>
      <AlertFeed alerts={alerts} onSelect={setSelectedAlert} now={now} />
      <SystemStatusPanel
        apiKeyConnected={Boolean(savedApiKey)}
        backendOnline={online}
        workerOnline={Boolean(workerOnline)}
        lastRpcSync={lastSignalAt}
        alertThreshold={70}
      />
      <AlertDetailModal
        alert={selectedAlert}
        onClose={() => setSelectedAlert(null)}
        onCopySummary={copyAlertSummary}
        onDownloadJson={downloadAlertJson}
      />
    </main>
  );
}
