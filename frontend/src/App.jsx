import { Navigate, Route, Routes } from 'react-router-dom';
import AlertHistory from './pages/AlertHistory.jsx';
import Admin from './pages/Admin.jsx';
import Agents from './pages/Agents.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Landing from './pages/Landing.jsx';
import Replay from './pages/Replay.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/replay" element={<Replay />} />
      <Route path="/alerts" element={<AlertHistory />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
