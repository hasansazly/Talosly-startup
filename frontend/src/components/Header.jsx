import Nav from './Nav.jsx';

export default function Header({ online, lastUpdated }) {
  return <Nav online={online} lastUpdated={lastUpdated} />;
}
