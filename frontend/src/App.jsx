import { Navigate, Route, Routes } from 'react-router-dom';
import AlertHistory from './pages/AlertHistory.jsx';
import Dashboard from './pages/Dashboard.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/alerts" element={<AlertHistory />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
