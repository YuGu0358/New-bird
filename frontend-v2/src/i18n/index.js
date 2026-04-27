// i18next setup. Detects browser language, falls back to English.
// Persists user's choice in localStorage under key `lang`.

import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import en from './locales/en.json';
import zh from './locales/zh.json';
import de from './locales/de.json';
import fr from './locales/fr.json';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'zh', label: 'Chinese', native: '中文' },
  { code: 'de', label: 'German',  native: 'Deutsch' },
  { code: 'fr', label: 'French',  native: 'Français' },
];

i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
      de: { translation: de },
      fr: { translation: fr },
    },
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'lang',
      caches: ['localStorage'],
    },
  });

export default i18next;
