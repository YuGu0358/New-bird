import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import MarketsPage from './pages/MarketsPage.jsx';
import PortfolioPage from './pages/PortfolioPage.jsx';
import NewsPage from './pages/NewsPage.jsx';
import IntelligencePage from './pages/IntelligencePage.jsx';
import BacktestPage from './pages/BacktestPage.jsx';
import AlgorithmsPage from './pages/AlgorithmsPage.jsx';
import QuantLabPage from './pages/QuantLabPage.jsx';
import RiskPage from './pages/RiskPage.jsx';
import SocialPage from './pages/SocialPage.jsx';
import CodePage from './pages/CodePage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import NotFoundPage from './pages/NotFoundPage.jsx';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/markets" element={<MarketsPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/intelligence" element={<IntelligencePage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/algo" element={<AlgorithmsPage />} />
        <Route path="/quantlib" element={<QuantLabPage />} />
        <Route path="/risk" element={<RiskPage />} />
        <Route path="/social" element={<SocialPage />} />
        <Route path="/code" element={<CodePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Layout>
  );
}
