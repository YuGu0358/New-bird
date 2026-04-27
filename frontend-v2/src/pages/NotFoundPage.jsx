import { Compass } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Compass size={48} className="text-steel-300 mb-4" strokeWidth={1.5} />
      <h1 className="h-page mb-2">Lost in the noise.</h1>
      <p className="text-body text-steel-200 mb-6">404 — 这条路不存在或者还没建好。</p>
      <Link to="/" className="btn-primary">回到 Dashboard</Link>
    </div>
  );
}
