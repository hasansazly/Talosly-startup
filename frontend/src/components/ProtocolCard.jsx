import { useState } from 'react';

function shorten(value) {
  if (!value) return 'No address';
  return `${value.slice(0, 10)}...${value.slice(-6)}`;
}

export default function ProtocolCard({ protocol, transactionCount, onAdd }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault();
    setError('');
    try {
      await onAdd({ name, address });
      setName('');
      setAddress('');
      setOpen(false);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="panel protocol-panel">
      <div>
        <div className="panel-label">Monitored protocol</div>
        <h1>{protocol?.name || 'No protocol configured'}</h1>
        <p className="mono address">{protocol ? shorten(protocol.address) : 'Add an Ethereum contract to begin monitoring'}</p>
      </div>
      <div className="protocol-actions">
        <span className="count-badge">{transactionCount} TX</span>
        <button onClick={() => setOpen(!open)}>{open ? 'Close' : 'Add Protocol'}</button>
      </div>
      {open && (
        <form className="add-form" onSubmit={submit}>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Protocol name" required />
          <input value={address} onChange={(event) => setAddress(event.target.value)} placeholder="0x..." required />
          <button type="submit">Monitor</button>
          {error && <div className="form-error">{error}</div>}
        </form>
      )}
    </section>
  );
}
