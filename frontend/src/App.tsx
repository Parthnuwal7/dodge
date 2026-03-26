import { BrowserRouter, Routes, Route } from 'react-router-dom';
import TopBar from './components/TopBar';
import Explorer from './pages/Explorer';
import Ingestion from './pages/Ingestion';

export default function App() {
  return (
    <BrowserRouter>
      <TopBar />
      <Routes>
        <Route path="/" element={<Explorer />} />
        <Route path="/ingest" element={<Ingestion />} />
      </Routes>
    </BrowserRouter>
  );
}
