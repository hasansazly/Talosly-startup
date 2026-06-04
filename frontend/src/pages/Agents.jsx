import { useEffect, useMemo, useState } from 'react';
import { createAgent, getAgents, getAgentScore, getHealth, scoreAgentAction, setStoredApiKey } from '../api.js';
import AgentList from '../components/AgentList.jsx';
import AgentTrustChart from '../components/AgentTrustChart.jsx';
import FlaggedActionPanel from '../components/FlaggedActionPanel.jsx';
import Header from '../components/Header.jsx';

const HISTORY_KEY = 'talosly_kya_score_history';
const EVM_ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;

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

function normalizeAgent(agent) {
  return {
    ...agent,
    latestScore: agent.latest_score || null,
  };
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
  const [agents, setAgents] = useState([]);
  const [history, setHistory] = useState(() => loadJson(HISTORY_KEY, {}));
  const [selectedId, setSelectedId] = useState(null);
  const [registerDraft, setRegisterDraft] = useState({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
  const [actionDraft, setActionDraft] = useState({ action: '', counterparty: '', value: '', selector: '' });
  const [message, setMessage] = useState('');
  const [registerError, setRegisterError] = useState('');

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
    if (!savedApiKey) {
      setAgents([]);
      setSelectedId(null);
      return;
    }
    getAgents()
      .then((items) => {
        const nextAgents = items.map(normalizeAgent);
        setAgents(nextAgents);
        setSelectedId((current) => nextAgents.some((agent) => agent.id === current) ? current : nextAgents[0]?.id || null);
      })
      .catch((error) => setMessage(error.message));
  }, [savedApiKey]);

  async function refreshScore(agent) {
    if (!agent) return;
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
    setRegisterError('');
    if (!EVM_ADDRESS_RE.test(registerDraft.wallet_address.trim())) {
      setRegisterError(`${registerDraft.chain} wallet addresses must be 0x followed by 40 hexadecimal characters.`);
      return;
    }
    try {
      const created = await createAgent(registerDraft);
      const nextAgents = (await getAgents()).map(normalizeAgent);
      setAgents(nextAgents);
      setSelectedId(created.id);
      setRegisterDraft({ name: '', principal_ref: '', wallet_address: '', chain: 'ethereum' });
      setMessage('Agent registered.');
    } catch (error) {
      setRegisterError(error.message);
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
            <select value={registerDraft.chain} onChange={(event) => setRegisterDraft({ ...registerDraft, chain: event.target.value })}>
              <option value="ethereum">Ethereum</option>
              <option value="base">Base</option>
            </select>
            <input value={registerDraft.wallet_address} onChange={(event) => {
              setRegisterDraft({ ...registerDraft, wallet_address: event.target.value });
              setRegisterError('');
            }} placeholder="0x wallet" required />
            <button type="submit">Register</button>
            {registerError && <div className="form-error">{registerError}</div>}
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
