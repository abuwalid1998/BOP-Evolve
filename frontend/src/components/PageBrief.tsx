import { useState } from 'react';
import { useI18n, type MessageKey } from '../i18n';
import { Icon } from './Icon';

export type BriefPage =
  | 'overview'
  | 'explorer'
  | 'case'
  | 'learning'
  | 'profile'
  | 'insights'
  | 'scenarios'
  | 'reports'
  | 'rules'
  | 'how'
  | 'health'
  | 'config'
  | 'admin';

const STORAGE_PREFIX = 'bop-evolve.brief.';

function readOpen(page: BriefPage): boolean {
  try {
    return localStorage.getItem(STORAGE_PREFIX + page) !== 'closed';
  } catch {
    return true;
  }
}

/**
 * Short orientation under each page title: why the page exists, what is on it, what
 * a reader can conclude from it and who it is for. Collapsing is remembered per page.
 */
export function PageBrief({ page }: { page: BriefPage }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(() => readOpen(page));
  const key = (part: string) => `brief.${page}.${part}` as MessageKey;
  const items = (part: string) =>
    t(key(part))
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(STORAGE_PREFIX + page, next ? 'open' : 'closed');
    } catch {
      /* storage unavailable */
    }
  };

  return (
    <section className={`page-brief${open ? ' open' : ''}`} aria-label={t('brief.label')}>
      <div className="page-brief-head">
        <Icon name="info" size={16} />
        <p>{t(key('purpose'))}</p>
        <button className="btn small ghost" onClick={toggle} aria-expanded={open}>
          {open ? t('brief.hide') : t('brief.show')}
        </button>
      </div>
      {open && (
        <div className="page-brief-body">
          <div>
            <h3>{t('brief.see')}</h3>
            <ul>
              {items('see').map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>{t('brief.learn')}</h3>
            <ul>
              {items('learn').map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>{t('brief.who')}</h3>
            <p>{t(key('who'))}</p>
          </div>
        </div>
      )}
    </section>
  );
}
