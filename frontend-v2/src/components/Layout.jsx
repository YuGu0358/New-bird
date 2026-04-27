import Sidebar from './Sidebar.jsx';
import TopBar from './TopBar.jsx';

export default function Layout({ children }) {
  return (
    <div className="flex h-screen bg-ink-950 text-steel-100">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <div className="flex-1 overflow-auto">
          <div className="px-8 py-6 max-w-[1600px] mx-auto">{children}</div>
        </div>
      </main>
    </div>
  );
}
