import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe, Check, ChevronDown } from 'lucide-react';
import { SUPPORTED_LANGUAGES } from '../i18n';
import { classNames } from '../lib/format.js';

export default function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  const current = SUPPORTED_LANGUAGES.find((l) => l.code === i18n.resolvedLanguage)
    || SUPPORTED_LANGUAGES[0];

  function pick(code) {
    i18n.changeLanguage(code);
    setOpen(false);
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="btn-ghost btn-sm inline-flex items-center gap-1.5"
        onClick={() => setOpen((v) => !v)}
        title={t('common.language')}
      >
        <Globe size={14} />
        <span className="font-medium">{current.native}</span>
        <ChevronDown size={12} className={classNames('transition duration-150', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[160px] bg-ink-900 border border-steel-400 rounded-md shadow-lg py-1">
          {SUPPORTED_LANGUAGES.map((l) => (
            <button
              key={l.code}
              type="button"
              className={classNames(
                'w-full flex items-center justify-between gap-3 px-3 h-8 text-body-sm transition duration-150',
                l.code === current.code
                  ? 'text-steel-50 bg-ink-800'
                  : 'text-steel-100 hover:bg-ink-800'
              )}
              onClick={() => pick(l.code)}
            >
              <span>{l.native}</span>
              {l.code === current.code && <Check size={12} className="text-steel-500" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
