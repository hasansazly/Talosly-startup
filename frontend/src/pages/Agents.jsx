import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  createAgent, getAgents, getAgentScore, getHealth,
  scoreAgentAction, sendAgentTestAlert, setStoredApiKey,
} from '../api.js';
import AgentList from '../components/AgentList.jsx';
import AgentTrustChart from '../components/AgentTrustChart.jsx';
import FlaggedActionPanel from '../components/FlaggedActionPanel.jsx';
import Nav from '../components/Nav.jsx';

const HISTORY_KEY  = 'talosly_kya_score_history';
const EVM_ADDR_RE  = /^0x[a-fA-F0-9]{40}$/;

function loadJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || ''); } catch { return fallback; }
}
function saveJson(key, value) { localStorage.setItem(key, JSON.stringify(value)); }
function normalizeAgent(agent) { return { ...agent, latestScore: agent.latest_score || null }; }
function appendHistory(history, agentId, score) {
  const next = { ...history };
  const entry = { ...score, computed_at: score.computed_at || new Date().toISOString() };
  next[agentId] = [...(next[agentId] || []), entry].slice(-24);
  saveJson(HISTORY_KEY, next);
  return next;
}

export default function Agents() {
  const [online, setOnline]         = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [savedApiKey, setSavedApiKey] = useState(
    sessionStorage.getItem('talosly_api_key') || localStorage.getItem('talosly_api_key') || ''
  );
  const [apiKeyDraft, setApiKeyDraft]   = useState(savedApiKey);
  const [agents, setAgents]             = useState([]);
  const [history, setHistory]           = useState(() => loadJson(HISTORY_KEY, {}));
  const [selectedId, setSelectedId]     = useState(null);
  const [registerDraft, setRegisterDraft] = useState({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
  const [actionDraft, setActionDraft]   = useState({ action: '', counterparty: '', value: '', selector: '' });
  const [message, setMessage]           = useState('');
  const [registerError, setRegisterError] = useState('');

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedId) || agents[0],
    [agents, selectedId]
  );
  const selectedHistory = history[selectedAgent?.id] || [];
  const flaggedScore = [...selectedHistory].reverse().find(
    (s) => 100 - Number(s.trust_score || 0) >= 70
  ) || selectedAgent?.latestScore;

  useEffect(() => {
    getHealth()
      .then(() => { setOnline(true); setLastUpdated(new Date().toLocaleTimeString()); })
      .catch(() => setOnline(false));
  }, []);

  useEffect(() => {
    if (!savedApiKey) { setAgents([]); setSelectedId(null); return; }
    getAgents()
      .then((items) => {
        const next = items.map(normalizeAgent);
        setAgents(next);
        setSelectedId((cur) => next.some((a) => a.id === cur) ? cur : next[0]?.id || null);
      })
      .catch((e) => setMessage(e.message));
  }, [savedApiKey]);

  async function refreshScore(agent) {
    if (!agent) return;
    try {
      const latest = await getAgentScore(agent.id);
      setAgents((items) => items.map((item) => item.id === agent.id ? { ...item, latestScore: latest } : item));
      setHistory((cur) => appendHistory(cur, agent.id, latest));
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    setMessage(''); setRegisterError('');
    if (!EVM_ADDR_RE.test(registerDraft.wallet_address.trim())) {
      setRegisterError('Wallet address must be 0x followed by 40 hex characters.');
      return;
    }
    try {
      const created = await createAgent(registerDraft);
      const next = (await getAgents()).map(normalizeAgent);
      setAgents(next);
      setSelectedId(created.id);
      setRegisterDraft({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
      setMessage('Agent registered.');
    } catch (e) {
      setRegisterError(e.message);
    }
  }

  async function handleScoreAction(event) {
    event.preventDefault();
    if (!selectedAgent) return;
    setMessage('');
    try {
      const scored = await scoreAgentAction({
        agent_id:     selectedAgent.id,
        wallet:       selectedAgent.wallet?.address || '',
        action:       actionDraft.action,
        counterparty: actionDraft.counterparty || null,
        value:        Number(actionDraft.value || 0),
        selector:     actionDraft.selector,
        raw:          { input: actionDraft.selector ? `0x${actionDraft.selector}` : '0x' },
        baseline:     {},
      });
      setAgents((items) => items.map((item) => item.id === selectedAgent.id ? { ...item, latestScore: scored } : item));
      setHistory((cur) => appendHistory(cur, selectedAgent.id, scored));
      setMessage('Action scored. Signed receipt emitted.');
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function handleTestAlert() {
    if (!selectedAgent) return;
    setMessage('');
    try {
      const r = await sendAgentTestAlert(selectedAgent.id);
      setMessage(r.message);
    } catch (e) {
      setMessage(e.message);
    }
  }

  return (
    <main className="app-shell agents-shell">
      <Nav online={online} lastUpdated={lastUpdated} />

      {!savedApiKey && (
        <section className="panel key-panel">
          <div>
            <div className="panel-label">Beta API key required</div>
            <h2 style={{ marginTop: 6 }}>Connect your Talosly beta key</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: 14, marginTop: 8 }}>
              Your key starts with <code style={{ fontFamily: 'var(--font-mono)' }}>tals_</code>.
              Issued via the admin panel.
            </p>
          </div>
          <form className="add-form" onSubmit={(e) => {
            e.preventDefault();
            const cleaned = apiKeyDraft.trim();
            setStoredApiKey(cleaned);
            setSavedApiKey(cleaned);
          }}>
            <input
              value={apiKeyDraft}
              onChange={(e) => setApiKeyDraft(e.target.value)}
              placeholder="tals_…"
              required
              className="mono"
            />
            <button type="submit">Connect</button>
          </form>
        </section>
      )}

      {savedApiKey && agents.length === 0 && (
        <div className="panel" style={{ color: 'var(--text-muted)', fontSize: 14 }}>
          No agents registered. Use the form below to register your first agent.
        </div>
      )}

      {/* agent workspace: list + chart + flagged */}
      {savedApiKey && (
        <section className="agents-grid">
          <AgentList
            agents={agents}
            selectedId={selectedAgent?.id}
            onSelect={(agent) => { setSelectedId(agent.id); refreshScore(agent); }}
          />
          <AgentTrustChart history={selectedHistory} />
          <FlaggedActionPanel score={flaggedScore} />
        </section>
      )}

      {/* detail link for selected agent */}
      {selectedAgent && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Link to={`/agents/${selectedAgent.id}`} className="button-link" style={{ fontSize: 13, padding: '8px 16px' }}>
            View detail + receipts →
          </Link>
          <button className="btn-ghost" onClick={handleTestAlert}>
            Send test alert
          </button>
          {message && <span className="form-message">{message}</span>}
        </div>
      )}

      {/* workbench */}
      <section className="panel agents-workbench">
        <div>
          <div className="panel-label">Register agent</div>
          <form className="agent-form" onSubmit={handleRegister}>
            <input
              value={registerDraft.name}
              onChange={(e) => setRegisterDraft({ ...registerDraft, name: e.target.value })}
              placeholder="Agent name"
              required
            />
            <input
              value={registerDraft.principal_ref}
              onChange={(e) => setRegisterDraft({ ...registerDraft, principal_ref: e.target.value })}
              placeholder="principal://ref"
              required
            />
            <select
              value={registerDraft.chain}
              onChange={(e) => setRegisterDraft({ ...registerDraft, chain: e.target.value })}
            >
              <option value="ethereum">Ethereum</option>
              <option value="base">Base</option>
            </select>
            <input
              value={registerDraft.wallet_address}
              onChange={(e) => { setRegisterDraft({ ...registerDraft, wallet_address: e.target.value }); setRegisterError(''); }}
              placeholder="0x wallet address"
              required
            />
            <button type="submit">Register</button>
            {registerError && <div className="form-error">{registerError}</div>}
          </form>
        </div>
        <div>
          <div className="panel-label">Score supplied action</div>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginBottom: 10 }}>
            {selectedAgent
              ? `Scoring for: ${selectedAgent.name}`
              : 'Register or select an agent first.'}
          </p>
          <form className="agent-form" onSubmit={handleScoreAction}>
            <input
              value={actionDraft.action}
              onChange={(e) => setActionDraft({ ...actionDraft, action: e.target.value })}
              placeholder="action / tx hash"
              required
            />
            <input
              value={actionDraft.counterparty}
              onChange={(e) => setActionDraft({ ...actionDraft, counterparty: e.target.value })}
              placeholder="counterparty address"
            />
            <input
              value={actionDraft.value}
              onChange={(e) => setActionDraft({ ...actionDraft, value: e.target.value })}
              placeholder="value ETH"
            />
            <input
              value={actionDraft.selector}
              onChange={(e) => setActionDraft({ ...actionDraft, selector: e.target.value })}
              placeholder="function selector"
            />
            <button type="submit" disabled={!selectedAgent}>Score</button>
          </form>
        </div>
        {!selectedAgent && (
          <div style={{ gridColumn: '1 / -1', color: 'var(--text-muted)', fontSize: 13 }}>
            Select an agent from the list above to score actions.
          </div>
        )}
      </section>
    </main>
  );
}
