import { useEffect, useMemo, useState } from 'react';
import { createAgent, getAgentScore, getHealth, scoreAgentAction, setStoredApiKey } from '../api.js';
import AgentList from '../components/AgentList.jsx';
import AgentTrustChart from '../components/AgentTrustChart.jsx';
import FlaggedActionPanel from '../components/FlaggedActionPanel.jsx';
import Header from '../components/Header.jsx';

const AGENTS_KEY = 'talosly_kya_agents';
const HISTORY_KEY = 'talosly_kya_score_history';

const DEMO_AGENTS = [
  {
    id: 'demo-treasury',
    name: 'Treasury Rebalancer',
    principal_ref: 'agent://treasury-rebalancer',
    status: 'active',
    wallet: { chain: 'ethereum', address: '0x6b175474e89094c44da98b954eedeac495271d0f' },
    latestScore: {
      agent_id: 'demo-treasury',
      trust_score: 28,
      action: '0xdeviating-action',
      risk_factors: ['new_counterparty', 'value_outlier', 'cadence_break'],
      shap_top: [
        { feature: 'pool_drain_ratio', value: 1, shap: 0.2 },
        { feature: 'velocity', value: 20, shap: 0.12 },
        { feature: 'gas_anomaly_zscore', value: 50, shap: 0.1 },
      ],
      confidence: 0.82,
      computed_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
    },
  },
  {
    id: 'demo-research',
    name: 'Research Runner',
    principal_ref: 'agent://research-runner',
    status: 'active',
    wallet: { chain: 'ethereum', address: '0x1111111254eeb25477b68fb85ed929f73a960582' },
    latestScore: {
      agent_id: 'demo-research',
      trust_score: 86,
      risk_factors: [],
      shap_top: [
        { feature: 'velocity', value: 0.3, shap: 0.02 },
        { feature: 'calldata_entropy', value: 2.8, shap: 0.01 },
      ],
      confidence: 0.76,
      computed_at: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    },
  },
];

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || '');
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function seedHistory(agents) {
  const existing = loadJson(HISTORY_KEY, {});
  let changed = false;
  const next = { ...existing };
  for (const agent of agents) {
    if (!next[agent.id] && agent.latestScore) {
      const base = Number(agent.latestScore.trust_score || 0);
      next[agent.id] = [3, 2, 1, 0].map((offset) => ({
        ...agent.latestScore,
        trust_score: Math.max(Math.min(base + offset * 4 - 5, 100), 0),
        computed_at: new Date(Date.now() - offset * 1000 * 60 * 30).toISOString(),
      }));
      changed = true;
    }
  }
  if (changed) saveJson(HISTORY_KEY, next);
  return next;
}

function appendHistory(history, agentId, score) {
  const next = { ...history };
  const computed = score.computed_at || new Date().toISOString();
  const entry = { ...score, computed_at: computed };
  next[agentId] = [...(next[agentId] || []), entry].slice(-24);
  saveJson(HISTORY_KEY, next);
  return next;
}

export default function Agents() {
  const [online, setOnline] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [savedApiKey, setSavedApiKey] = useState(sessionStorage.getItem('talosly_api_key') || localStorage.getItem('talosly_api_key') || '');
  const [apiKeyDraft, setApiKeyDraft] = useState(savedApiKey);
  const [agents, setAgents] = useState(() => {
    const stored = loadJson(AGENTS_KEY, null);
    return stored?.length ? stored : DEMO_AGENTS;
  });
  const [history, setHistory] = useState(() => seedHistory(loadJson(AGENTS_KEY, null)?.length ? loadJson(AGENTS_KEY, []) : DEMO_AGENTS));
  const [selectedId, setSelectedId] = useState(() => agents[0]?.id || null);
  const [registerDraft, setRegisterDraft] = useState({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
  const [actionDraft, setActionDraft] = useState({ action: '', counterparty: '', value: '', selector: '' });
  const [message, setMessage] = useState('');

  const selectedAgent = useMemo(() => agents.find((agent) => agent.id === selectedId) || agents[0], [agents, selectedId]);
  const selectedHistory = history[selectedAgent?.id] || [];
  const flaggedScore = [...selectedHistory].reverse().find((score) => 100 - Number(score.trust_score || 0) >= 70) || selectedAgent?.latestScore;

  useEffect(() => {
    getHealth()
      .then(() => {
        setOnline(true);
        setLastUpdated(new Date().toLocaleTimeString());
      })
      .catch(() => setOnline(false));
  }, []);

  useEffect(() => {
    saveJson(AGENTS_KEY, agents.filter((agent) => !String(agent.id).startsWith('demo-')));
  }, [agents]);

  async function refreshScore(agent) {
    if (!agent || String(agent.id).startsWith('demo-')) return;
    try {
      const latest = await getAgentScore(agent.id);
      setAgents((items) => items.map((item) => (item.id === agent.id ? { ...item, latestScore: latest } : item)));
      setHistory((current) => appendHistory(current, agent.id, latest));
      setMessage('Latest KYA score loaded.');
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    setMessage('');
    try {
      const created = await createAgent(registerDraft);
      const nextAgent = { ...created, latestScore: null };
      setAgents((items) => [nextAgent, ...items.filter((item) => !String(item.id).startsWith('demo-'))]);
      setSelectedId(created.id);
      setRegisterDraft({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
      setMessage('Agent registered.');
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function handleScoreAction(event) {
    event.preventDefault();
    if (!selectedAgent) return;
    setMessage('');
    try {
      const scored = await scoreAgentAction({
        agent_id: selectedAgent.id,
        wallet: selectedAgent.wallet?.address || actionDraft.wallet || '',
        action: actionDraft.action,
        counterparty: actionDraft.counterparty || null,
        value: Number(actionDraft.value || 0),
        selector: actionDraft.selector,
        raw: { input: actionDraft.selector ? `0x${actionDraft.selector}` : '0x' },
        baseline: {},
      });
      setAgents((items) => items.map((item) => (item.id === selectedAgent.id ? { ...item, latestScore: scored } : item)));
      setHistory((current) => appendHistory(current, selectedAgent.id, scored));
      setMessage('Action scored.');
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <main className="app-shell agents-shell">
      <Header online={online} lastUpdated={lastUpdated} />

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
          }}>
            <input value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} placeholder="tals_..." required />
            <button type="submit">Use Key</button>
          </form>
        </section>
      )}

      <section className="agents-grid">
        <AgentList agents={agents} selectedId={selectedAgent?.id} onSelect={(agent) => {
          setSelectedId(agent.id);
          refreshScore(agent);
        }} />
        <AgentTrustChart history={selectedHistory} />
        <FlaggedActionPanel score={flaggedScore} />
      </section>

      <section className="panel agents-workbench">
        <div>
          <div className="panel-label">Register agent</div>
          <form className="agent-form" onSubmit={handleRegister}>
            <input value={registerDraft.name} onChange={(event) => setRegisterDraft({ ...registerDraft, name: event.target.value })} placeholder="Agent name" required />
            <input value={registerDraft.principal_ref} onChange={(event) => setRegisterDraft({ ...registerDraft, principal_ref: event.target.value })} placeholder="principal://ref" required />
            <input value={registerDraft.wallet_address} onChange={(event) => setRegisterDraft({ ...registerDraft, wallet_address: event.target.value })} placeholder="0x wallet" required />
            <button type="submit">Register</button>
          </form>
        </div>
        <div>
          <div className="panel-label">Score supplied action</div>
          <form className="agent-form" onSubmit={handleScoreAction}>
            <input value={actionDraft.action} onChange={(event) => setActionDraft({ ...actionDraft, action: event.target.value })} placeholder="action / tx hash" required />
            <input value={actionDraft.counterparty} onChange={(event) => setActionDraft({ ...actionDraft, counterparty: event.target.value })} placeholder="counterparty" />
            <input value={actionDraft.value} onChange={(event) => setActionDraft({ ...actionDraft, value: event.target.value })} placeholder="value ETH" />
            <input value={actionDraft.selector} onChange={(event) => setActionDraft({ ...actionDraft, selector: event.target.value })} placeholder="selector" />
            <button type="submit">Score</button>
          </form>
        </div>
        {message && <div className="form-error">{message}</div>}
      </section>
    </main>
  );
}
