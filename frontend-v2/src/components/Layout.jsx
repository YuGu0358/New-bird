import Sidebar from './Sidebar.jsx';
import TopBar from './TopBar.jsx';

export default function Layout({ children }) {
  return (
    <div className="flex min-h-screen bg-void text-text-primary">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <div className="flex-1 overflow-auto">
          <div className="px-12 py-9 max-w-[1600px]">{children}</div>
        </div>
      </main>
    </div>
  );
}
