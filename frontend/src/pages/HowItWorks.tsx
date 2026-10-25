import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { DashboardSummary, PipelineStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { ProcessMap, type MapStep, type TokenState } from '../components/ProcessMap';
import { Card, LiveStatus, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

type StepId = 'sources' | 'intake' | 'rules' | 'perspective' | 'review' | 'action' | 'followup' | 'stage' | 'mi';

interface StepDef {
  id: StepId;
  becomes: TokenState;
  exit?: 'quarantine' | 'compliant' | 'dismissed';
  link?: { to: string; page: MessageKey; permissions: string[] };
}

// Serpentine order: left to right, then back, then forward again (mirrored in Arabic).
const STEPS: StepDef[] = [
  { id: 'sources', becomes: 'raw', link: { to: '/health', page: 'nav.health', permissions: ['ops.view'] } },
  { id: 'intake', becomes: 'trusted', exit: 'quarantine', link: { to: '/health', page: 'nav.health', permissions: ['ops.view'] } },
  { id: 'rules', becomes: 'flagged', exit: 'compliant', link: { to: '/rules', page: 'nav.rules', permissions: ['rules.view'] } },
  { id: 'perspective', becomes: 'flagged', link: { to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] } },
  { id: 'review', becomes: 'confirmed', exit: 'dismissed', link: { to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] } },
  { id: 'action', becomes: 'confirmed', link: { to: '/learning', page: 'nav.learning', permissions: ['learning.view'] } },
  { id: 'followup', becomes: 'learned', link: { to: '/reports', page: 'nav.reports', permissions: ['reports.view'] } },
  { id: 'stage', becomes: 'learned', link: { to: '/learning', page: 'nav.learning', permissions: ['learning.view'] } },
  { id: 'mi', becomes: 'learned', link: { to: '/insights', page: 'nav.insights', permissions: ['insights.view'] } },
];

const GRID: Record<StepId, [number, number]> = {
  sources: [1, 1],
  intake: [2, 1],
  rules: [3, 1],
  perspective: [3, 2],
  review: [2, 2],
  action: [1, 2],
  followup: [1, 3],
  stage: [2, 3],
  mi: [3, 3],
};

const LEGEND: { state: TokenState | 'exit'; label: MessageKey }[] = [
  { state: 'raw', label: 'how.legend.raw' },
  { state: 'trusted', label: 'how.legend.trusted' },
  { state: 'flagged', label: 'how.legend.flagged' },
  { state: 'confirmed', label: 'how.legend.confirmed' },
  { state: 'learned', label: 'how.legend.learned' },
  { state: 'exit', label: 'how.legend.exit' },
];

const QUESTIONS: { q: MessageKey; a: MessageKey; to: string; page: MessageKey; permissions: string[] }[] = [
  { q: 'how.q1', a: 'how.q1.a', to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] },
  { q: 'how.q2', a: 'how.q2.a', to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] },
  { q: 'how.q3', a: 'how.q3.a', to: '/learning', page: 'nav.learning', permissions: ['learning.view'] },
  { q: 'how.q4', a: 'how.q4.a', to: '/insights', page: 'nav.insights', permissions: ['insights.view'] },
  { q: 'how.q5', a: 'how.q5.a', to: '/rules', page: 'nav.rules', permissions: ['rules.view'] },
  { q: 'how.q6', a: 'how.q6.a', to: '/scenarios', page: 'nav.scenarios', permissions: ['simulations.run'] },
  { q: 'how.q7', a: 'how.q7.a', to: '/health', page: 'nav.health', permissions: ['ops.view'] },
];

const GLOSSARY = [
  'finding',
  'rule',
  'earlyWarning',
  'policyVersion',
  'fourEyes',
  'review',
  'objection',
  'factor',
  'action',
  'followUp',
  'stage',
  'privacy',
] as const;

const SAFEGUARDS = ['human', 'voice', 'fourEyes', 'privacy', 'evidence', 'synthetic'] as const;

const TOUR_SECONDS = 8;

interface RuleLite {
  status: string;
  kind: string;
}

export default function HowItWorksPage() {
  const { t, fmtNumber, fmtPercent, fmtRelative } = useI18n();
  const { can } = useAuth();
  const canDash = can('dashboard.view');
  const canOps = can('ops.view');
  const summary = useApi<DashboardSummary>(canDash ? '/api/dashboard/summary?days=90' : null, 15000);
  const pipelines = useApi<{ pipelines: PipelineStatus[] }>(canOps ? '/api/pipelines/status' : null, 10000);
  const rules = useApi<RuleLite[]>('/api/rules', 60000);
  const [selected, setSelected] = useState<number>(0);
  const [playing, setPlaying] = useState(false);
  const [touring, setTouring] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const h = window.setTimeout(() => {
      if (selected >= STEPS.length - 1) setPlaying(false);
      else setSelected(selected + 1);
    }, TOUR_SECONDS * 1000);
    return () => window.clearTimeout(h);
  }, [playing, selected]);

  const s = summary.data;
  const status = s?.totals.by_status ?? {};
  const num = (n: number | undefined | null) => (n === undefined || n === null ? '—' : fmtNumber(n));
  const runs = (pipelines.data?.pipelines ?? []).map((p) => p.last_run).filter((r): r is NonNullable<typeof r> => !!r);
  const read = runs.reduce((a, r) => a + r.records_read, 0);
  const rejected = runs.reduce((a, r) => a + r.records_rejected, 0);
  const accepted = runs.reduce((a, r) => a + r.records_written, 0);
  const duplicates = runs.reduce((a, r) => a + r.records_duplicated, 0);
  const confirmed = (status.CONFIRMED ?? 0) + (status.AMENDED ?? 0);
  const dismissed = status.DISMISSED ?? 0;
  const awarenessTotal = s ? Object.values(s.awareness).reduce((a, b) => a + b, 0) : undefined;
  const approvedProfiles = s ? Object.values(s.generations.distribution).reduce((a, b) => a + b, 0) : undefined;
  const activeRules = (rules.data ?? []).filter((r) => r.status === 'active');
  const flagRate = s && s.totals.reviewed_interactions ? s.totals.potential_findings / s.totals.reviewed_interactions : null;

  // Exit probabilities follow live data. Clean cases are thinned for the animation so that
  // findings stay visible; the true share is printed on the step.
  const mapSteps: MapStep[] = useMemo(
    () =>
      STEPS.map((step) => {
        let probability = 0;
        if (step.exit === 'quarantine') probability = read ? Math.min(0.4, rejected / read) : 0.06;
        if (step.exit === 'compliant') probability = Math.min(0.7, flagRate === null ? 0.6 : 1 - flagRate);
        if (step.exit === 'dismissed') probability = confirmed + dismissed ? dismissed / (confirmed + dismissed) : 0.15;
        return { id: step.id, becomes: step.becomes, exit: step.exit ? { id: `exit-${step.exit}`, probability } : undefined };
      }),
    [read, rejected, flagRate, confirmed, dismissed],
  );

  const metrics: Record<StepId, { label: MessageKey; value: string }[]> = {
    sources: s
      ? [
          { label: 'how.m.sources', value: `${num(s.pipelines.states.HEALTHY ?? 0)} / ${num(s.pipelines.total)}` },
          { label: 'how.m.lastIngest', value: fmtRelative(s.pipelines.last_successful_ingestion_at) },
        ]
      : [],
    intake: canOps
      ? [
          { label: 'how.m.accepted', value: num(accepted) },
          { label: 'how.m.rejected', value: num(rejected) },
          { label: 'how.m.duplicates', value: num(duplicates) },
        ]
      : [],
    rules: [
      { label: 'how.m.activeRules', value: rules.data ? num(activeRules.length) : '—' },
      ...(s
        ? [
            { label: 'how.m.assessed' as MessageKey, value: num(s.totals.reviewed_interactions) },
            { label: 'how.m.flagRate' as MessageKey, value: fmtPercent(flagRate, 1) },
          ]
        : []),
    ],
    perspective: s ? [{ label: 'how.m.responses', value: num(awarenessTotal) }] : [],
    review: s
      ? [
          { label: 'how.m.pending', value: num(status.POTENTIAL ?? 0) },
          { label: 'how.m.confirmed', value: num(confirmed) },
          { label: 'how.m.objection', value: num(status.DISPUTED ?? 0) },
        ]
      : [],
    action: s
      ? [
          { label: 'how.m.completion', value: fmtPercent(s.actions.completion_rate) },
          { label: 'how.m.overdue', value: num(s.actions.overdue) },
        ]
      : [],
    followup: s
      ? [
          { label: 'how.m.repeat', value: fmtPercent(s.recurrence.rate, 1) },
          { label: 'how.m.evaluated', value: num(s.recurrence.evaluated) },
        ]
      : [],
    stage: s
      ? [
          { label: 'how.m.profiles', value: num(approvedProfiles) },
          { label: 'how.m.awaiting', value: num(s.generations.pending_approval) },
        ]
      : [],
    mi: [{ label: 'how.m.reports', value: '8' }],
  };

  const exitCount: Record<string, string> = {
    quarantine: canOps ? num(rejected) : '',
    compliant: s ? fmtPercent(flagRate === null ? null : 1 - flagRate, 1) : '',
    dismissed: s ? num(dismissed) : '',
  };

  const current = STEPS[selected];
  const k = (id: StepId, part: string) => `how.step.${id}.${part}` as MessageKey;

  const startTour = () => {
    setTouring(true);
    setSelected(0);
    setPlaying(true);
  };

  return (
    <>
      <PageHead
        title={t('how.title')}
        subtitle={t('how.subtitle')}
        actions={canDash ? <LiveStatus updatedAt={summary.updatedAt} stale={summary.stale} /> : undefined}
      />
      <PageBrief page="how" />
      <div className="stack">
        <Card
          title={t('how.map.title')}
          subtitle={t('how.map.subtitle')}
          actions={
            <div className="row" style={{ gap: 6 }}>
              {!touring ? (
                <button className="btn small primary" onClick={startTour}>
                  <Icon name="play" size={14} /> {t('how.tour.start')}
                </button>
              ) : (
                <>
                  <button className="btn small" onClick={() => setSelected(Math.max(0, selected - 1))} disabled={selected === 0}>
                    {t('common.prev')}
                  </button>
                  <button className="btn small" onClick={() => setPlaying(!playing)} aria-pressed={playing}>
                    <Icon name={playing ? 'pause' : 'play'} size={14} /> {t(playing ? 'how.tour.pause' : 'how.tour.resume')}
                  </button>
                  <button
                    className="btn small"
                    onClick={() => setSelected(Math.min(STEPS.length - 1, selected + 1))}
                    disabled={selected === STEPS.length - 1}
                  >
                    {t('common.next')}
                  </button>
                  <button
                    className="btn small ghost"
                    onClick={() => {
                      setTouring(false);
                      setPlaying(false);
                    }}
                  >
                    {t('how.tour.exit')}
                  </button>
                </>
              )}
            </div>
          }
        >
          <ul className="how-legend" aria-label={t('how.legend.title')}>
            {LEGEND.map((l) => (
              <li key={l.state}>
                <span className={`how-dot ${l.state}`} aria-hidden="true" />
                {t(l.label)}
              </li>
            ))}
          </ul>
          <div className="how-layout">
            <ProcessMap steps={mapSteps} focus={touring ? selected : null} className="how-map" tour="how-map">
              <ol className="how-grid" aria-label={t('how.map.title')}>
                {STEPS.map((step, i) => {
                  const [col, row] = GRID[step.id];
                  return (
                    <li key={step.id} className="how-cell" style={{ gridColumn: col, gridRow: row }}>
                      <button
                        data-node={step.id}
                        className={`how-node${i === selected ? ' selected' : ''}${touring && i < selected ? ' passed' : ''}`}
                        onClick={() => {
                          setSelected(i);
                          setPlaying(false);
                        }}
                        aria-pressed={i === selected}
                      >
                        <span className="how-num">{i + 1}</span>
                        <span className="how-node-title">{t(k(step.id, 'title'))}</span>
                        <span className="how-node-short">{t(k(step.id, 'short'))}</span>
                        {metrics[step.id][0] && (
                          <span className="how-node-metric">
                            {t(metrics[step.id][0].label)}: <strong>{metrics[step.id][0].value}</strong>
                          </span>
                        )}
                      </button>
                      {step.exit && (
                        <span className="how-exit" data-node={`exit-${step.exit}`}>
                          <Icon name="logout" size={12} />
                          {t(`how.exit.${step.exit}` as MessageKey)}
                          {exitCount[step.exit] && <strong>{exitCount[step.exit]}</strong>}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </ProcessMap>
            <aside className="how-detail" aria-live="polite">
              <div className="how-detail-head">
                <span className="how-num big">{selected + 1}</span>
                <div>
                  <div className="subtle">{t('how.detail.step', { n: selected + 1, total: STEPS.length })}</div>
                  <h3>{t(k(current.id, 'title'))}</h3>
                </div>
              </div>
              {touring && (
                <div className="how-progress" aria-hidden="true">
                  <span key={`${selected}-${playing}`} className={playing ? 'run' : ''} style={{ animationDuration: `${TOUR_SECONDS}s` }} />
                </div>
              )}
              <p>{t(k(current.id, 'what'))}</p>
              <dl className="how-dl">
                <dt>{t('how.detail.who')}</dt>
                <dd>{t(k(current.id, 'who'))}</dd>
                <dt>{t('how.detail.control')}</dt>
                <dd>{t(k(current.id, 'control'))}</dd>
                <dt>{t('how.detail.output')}</dt>
                <dd>{t(k(current.id, 'output'))}</dd>
              </dl>
              <div className="how-example">
                <div className="how-example-label">
                  <Icon name="book" size={14} /> {t('how.detail.example')}
                </div>
                <p>{t(k(current.id, 'example'))}</p>
              </div>
              {metrics[current.id].length > 0 ? (
                <dl className="how-metrics">
                  {metrics[current.id].map((m) => (
                    <div key={m.label}>
                      <dt>{t(m.label)}</dt>
                      <dd>{m.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="subtle">{t('how.detail.noMetrics')}</p>
              )}
              {current.link &&
                (can(...current.link.permissions) ? (
                  <Link to={current.link.to}>{t('how.open', { page: t(current.link.page) })} →</Link>
                ) : (
                  <span className="subtle">{t('how.noAccess', { page: t(current.link.page) })}</span>
                ))}
            </aside>
          </div>
          <p className="subtle" style={{ margin: '12px 0 0', fontSize: 12 }}>
            {t('how.map.note')}
          </p>
        </Card>

        <Card title={t('how.safeguards.title')} subtitle={t('how.safeguards.subtitle')}>
          <div className="grid grid-3">
            {SAFEGUARDS.map((g) => (
              <div key={g} className="how-safeguard">
                <Icon name="check" size={16} />
                <div>
                  <h3>{t(`how.safeguard.${g}` as MessageKey)}</h3>
                  <p className="muted">{t(`how.safeguard.${g}.body` as MessageKey)}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title={t('how.questions')} subtitle={t('how.questionsSub')}>
          <div className="grid grid-3">
            {QUESTIONS.map((item) => (
              <div key={item.q} className="flow-question">
                <h3>{t(item.q)}</h3>
                <p className="muted">{t(item.a)}</p>
                {can(...item.permissions) ? (
                  <Link to={item.to}>{t('how.open', { page: t(item.page) })}</Link>
                ) : (
                  <span className="subtle">{t('how.noAccess', { page: t(item.page) })}</span>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card title={t('how.glossary.title')} subtitle={t('how.glossary.subtitle')}>
          <dl className="how-glossary">
            {GLOSSARY.map((g) => (
              <div key={g}>
                <dt>{t(`how.term.${g}` as MessageKey)}</dt>
                <dd>{t(`how.term.${g}.def` as MessageKey)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </>
  );
}
