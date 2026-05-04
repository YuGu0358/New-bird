import { Compass } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export default function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Compass size={48} className="text-text-muted mb-4" strokeWidth={1.5} />
      <h1 className="h-page mb-2">{t('common.notFoundTitle')}</h1>
      <p className="text-body text-text-secondary mb-6">{t('common.notFoundHint')}</p>
      <Link to="/" className="btn-primary">{t('common.backToDashboard')}</Link>
    </div>
  );
}
