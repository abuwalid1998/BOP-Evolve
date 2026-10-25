import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import ar from './ar';
import en, { type MessageKey } from './en';

export type Lang = 'en' | 'ar';
const dictionaries: Record<Lang, Record<MessageKey, string>> = { en, ar };
const STORAGE_KEY = 'bop-evolve.lang';
const DISPLAY_TZ = 'Asia/Hebron';

type Vars = Record<string, string | number>;

interface I18nValue {
  lang: Lang;
  dir: 'ltr' | 'rtl';
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, vars?: Vars) => string;
  /** Translate a dynamic enum value, e.g. tx('status', 'CONFIRMED'); falls back to the raw value. */
  tx: (prefix: string, value: string | null | undefined) => string;
  /** Pick the localised variant of a bilingual API field pair (e.g. name / name_ar). */
  pick: (enValue?: string | null, arValue?: string | null) => string;
  fmtDate: (iso?: string | null, withTime?: boolean) => string;
  fmtNumber: (n?: number | null, digits?: number) => string;
  fmtPercent: (n?: number | null, digits?: number) => string;
  fmtRelative: (iso?: string | null) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

function storedLang(): Lang | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'ar' || stored === 'en') return stored;
  } catch {
    /* storage unavailable */
  }
  return null;
}

function readStoredLang(): Lang {
  return storedLang() ?? (navigator.language?.startsWith('ar') ? 'ar' : 'en');
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang);
  const dir = lang === 'ar' ? 'rtl' : 'ltr';
  // Western digits keep IDs and technical values readable in mixed Arabic/English text.
  const locale = lang === 'ar' ? 'ar-PS-u-nu-latn' : 'en-GB';

  // Until the person picks a language, follow the default configured by the Super Admin.
  useEffect(() => {
    if (storedLang()) return;
    api
      .get<{ default_locale: string }>('/api/public/settings')
      .then((r) => {
        if (!storedLang() && (r.default_locale === 'ar' || r.default_locale === 'en')) setLangState(r.default_locale);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<I18nValue>(() => {
    const dict = dictionaries[lang];
    const t = (key: MessageKey, vars?: Vars) => {
      let text = dict[key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
      return text;
    };
    const tx = (prefix: string, raw: string | null | undefined) => {
      if (raw === null || raw === undefined || raw === '') return '—';
      const key = `${prefix}.${raw}` as MessageKey;
      return dict[key] ?? en[key] ?? raw;
    };
    const dateFmt = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: DISPLAY_TZ });
    const dateTimeFmt = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: DISPLAY_TZ });
    const relFmt = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    return {
      lang,
      dir,
      setLang,
      t,
      tx,
      pick: (enValue, arValue) => (lang === 'ar' ? arValue || enValue || '' : enValue || arValue || ''),
      fmtDate: (iso, withTime = false) => (iso ? (withTime ? dateTimeFmt : dateFmt).format(new Date(iso)) : '—'),
      fmtNumber: (n, digits = 0) =>
        n === null || n === undefined
          ? '—'
          : new Intl.NumberFormat(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(n),
      fmtPercent: (n, digits = 0) =>
        n === null || n === undefined
          ? '—'
          : new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: digits }).format(n),
      fmtRelative: (iso) => {
        if (!iso) return '—';
        const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
        const abs = Math.abs(seconds);
        if (abs < 60) return relFmt.format(seconds, 'second');
        if (abs < 3600) return relFmt.format(Math.round(seconds / 60), 'minute');
        if (abs < 86400) return relFmt.format(Math.round(seconds / 3600), 'hour');
        return relFmt.format(Math.round(seconds / 86400), 'day');
      },
    };
  }, [lang, dir, locale, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider');
  return ctx;
}

export type { MessageKey };
