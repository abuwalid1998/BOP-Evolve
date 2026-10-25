import { useI18n, type MessageKey } from '../i18n';

const CODES = ['G0', 'G1', 'G2', 'G3', 'G4', 'G5'];

/** Visual G0 → G5 journey; the current approved version is highlighted as Gx. */
export function GenerationTrack({ current }: { current: string | null }) {
  const { t } = useI18n();
  const idx = current ? CODES.indexOf(current) : -1;
  return (
    <ol className="gen-track" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {CODES.map((code, i) => (
        <li
          key={code}
          className={`gen-step ${i < idx ? 'done' : ''} ${i === idx ? 'current' : ''}`}
          aria-current={i === idx ? 'step' : undefined}
        >
          <div className="code">{i === idx ? `${code} · Gx` : code}</div>
          <div className="name">{t(`gen.${code}` as MessageKey)}</div>
          <div className="desc">{t(`gen.${code}.desc` as MessageKey)}</div>
        </li>
      ))}
    </ol>
  );
}

export function GenBadge({ code }: { code: string | null }) {
  const { t } = useI18n();
  if (!code) return <span className="subtle">—</span>;
  return (
    <span className="badge brand" title={t(`gen.${code}.desc` as MessageKey)}>
      {code} · {t(`gen.${code}` as MessageKey)}
    </span>
  );
}
