import { useCallback, useEffect, useMemo, useState } from 'react';
import { addProtocol, getAlerts, getHealth, getProtocols, getTransactions } from '../api.js';
import AlertFeed from '../components/AlertFeed.jsx';
import Header from '../components/Header.jsx';
import ProtocolCard from '../components/ProtocolCard.jsx';
import TransactionRow from '../components/TransactionRow.jsx';

export default function Dashboard() {
  const [protocols, setProtocols] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [online, setOnline] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');

  const activeProtocol = useMemo(() => protocols.find((item) => item.is_active) || protocols[0], [protocols]);

  const load = useCallback(async () => {
    try {
      await getHealth();
      setOnline(true);
      const nextProtocols = await getProtocols();
      setProtocols(nextProtocols);
      const selected = nextProtocols.find((item) => item.is_active) || nextProtocols[0];
      setTransactions(await getTransactions(selected?.id, 50));
      setAlerts(await getAlerts(12));
      setLastUpdated(new Date().toLocaleTimeString());
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  async function handleAdd(payload) {
    await addProtocol(payload);
    await load();
  }

  return (
    <main className="app-shell">
      <Header online={online} lastUpdated={lastUpdated} />
      <ProtocolCard protocol={activeProtocol} transactionCount={transactions.length} onAdd={handleAdd} />
      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-label">Live transaction feed</div>
            <h2>Recent transactions</h2>
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
                <tr><td colSpan="5" className="empty-row">No transactions captured yet</td></tr>
              ) : (
                transactions.map((tx) => <TransactionRow tx={tx} key={tx.id} />)
              )}
            </tbody>
          </table>
        </div>
      </section>
      <AlertFeed alerts={alerts} />
    </main>
  );
}
