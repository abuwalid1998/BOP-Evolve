import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { DashboardSummary, PipelineStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { FlowCanvas } from '../components/FlowCanvas';
import { Icon } from '../components/Icon';
import { Card, LiveStatus, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

type Metric = { label: MessageKey; value: string };

interface Stage {
  n: 1 | 2 | 3 | 4 | 5;
  metrics: Metric[] | null;
  example: ReactNode;
}

const RAW_EXAMPLE = `{ "src": "QA",
  "key": "E-1001-00141",
  "type": "account_opening",
  "ts": "2026-10-24T12:27Z",
  "id_check": "after_activation" }`;

const QUESTIONS: { q: MessageKey; a: MessageKey; to: string; page: MessageKey; permissions: string[] }[] = [
  { q: 'flow.q1', a: 'flow.q1.a', to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] },
  { q: 'flow.q2', a: 'flow.q2.a', to: '/explorer', page: 'nav.explorer', permissions: ['cases.view'] },
  { q: 'flow.q3', a: 'flow.q3.a', to: '/learning', page: 'nav.learning', permissions: ['learning.view'] },
  { q: 'flow.q4', a: 'flow.q4.a', to: '/insights', page: 'nav.insights', permissions: ['insights.view'] },
  { q: 'flow.q5', a: 'flow.q5.a', to: '/scenarios', page: 'nav.scenarios', permissions: ['simulations.run'] },
  { q: 'flow.q6', a: 'flow.q6.a', to: '/health', page: 'nav.health', permissions: ['ops.view'] },
];

export default function DataFlowPage() {
  const { t, fmtNumber, fmtPercent } = useI18n();
  const { can } = useAuth();
  const summary = useApi<DashboardSummary>('/api/dashboard/summary?days=90', 15000);
  const canOps = can('ops.view');
  const pipelines = useApi<{ pipelines: PipelineStatus[] }>(canOps ? '/api/pipelines/status' : null, 10000);

  const s = summary.data;
  const num = (n: number | undefined | null) => (n === undefined || n === null ? '—' : fmtNumber(n));
  const status = s?.totals.by_status ?? {};
  const runs = (pipelines.data?.pipelines ?? []).map((p) => p.last_run).filter((r) => !!r);
  const sum = (pick: (r: NonNullable<(typeof runs)[number]>) => number) =>
    pipelines.data ? runs.reduce((total, r) => total + pick(r!), 0) : undefined;
  const connected = pipelines.data?.pipelines.filter((p) => p.source.approved && p.source.enabled).length;
  const approvedProfiles = s ? Object.values(s.generations.distribution).reduce((a, b) => a + b, 0) : undefined;

  const stages: Stage[] = [
    {
      n: 1,
      example: <pre className="flow-code mono">{RAW_EXAMPLE}</pre>,
      metrics: canOps
        ? [
            { label: 'flow.m.sources', value: connected === undefined ? '—' : `${num(connected)} / ${num(pipelines.data?.pipelines.length)}` },
            { label: 'flow.m.read', value: num(sum((r) => r.records_read)) },
          ]
        : null,
    },
    {
      n: 2,
      example: <span>{t('flow.s2.ex')}</span>,
      metrics: canOps
        ? [
            { label: 'flow.m.accepted', value: num(sum((r) => r.records_written)) },
            { label: 'flow.m.rejected', value: num(sum((r) => r.records_rejected)) },
            { label: 'flow.m.duplicates', value: num(sum((r) => r.records_duplicated)) },
          ]
        : null,
    },
    {
      n: 3,
      example: <span>{t('flow.s3.ex')}</span>,
      metrics: [
        { label: 'flow.m.reviewed', value: num(s?.totals.reviewed_interactions) },
        { label: 'flow.m.potential', value: num(s?.totals.potential_findings) },
      ],
    },
    {
      n: 4,
      example: <span>{t('flow.s4.ex')}</span>,
      metrics: [
        { label: 'flow.m.confirmed', value: num(s ? (status.CONFIRMED ?? 0) + (status.AMENDED ?? 0) : undefined) },
        { label: 'flow.m.disputed', value: num(s ? (status.DISPUTED ?? 0) : undefined) },
        { label: 'flow.m.dismissed', value: num(s ? (status.DISMISSED ?? 0) : undefined) },
        { label: 'flow.m.pending', value: num(s ? (status.POTENTIAL ?? 0) : undefined) },
      ],
    },
    {
      n: 5,
      example: <span>{t('flow.s5.ex')}</span>,
      metrics: [
        { label: 'flow.m.actions', value: fmtPercent(s?.actions.completion_rate) },
        { label: 'flow.m.recurrence', value: fmtPercent(s?.recurrence.rate, 1) },
        { label: 'flow.m.profiles', value: num(approvedProfiles) },
      ],
    },
  ];

  return (
    <>
      <PageHead
        title={t('flow.title')}
        subtitle={t('flow.subtitle')}
        actions={<LiveStatus updatedAt={summary.updatedAt} stale={summary.stale} />}
      />
      <div className="stack">
        <Card>
          <div className="flow-axis" aria-hidden="true">
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n}>{t(`flow.kind.${n}` as MessageKey)}</span>
            ))}
          </div>
          <div className="flow-bar" aria-hidden="true" />
          <div className="flow-chart" role="img" aria-label={t('flow.chartLabel')}>
            <FlowCanvas className="flow-chart-canvas" density={4.5} />
          </div>

          <ol className="flow-stages">
            {stages.map((stage) => {
              const k = (suffix: string) => `flow.s${stage.n}.${suffix}` as MessageKey;
              return (
                <li key={stage.n} className="flow-stage">
                  <article className="flow-card">
                    <header>
                      <span className="flow-num" aria-hidden="true">
                        {stage.n}
                      </span>
                      <div>
                        <div className="flow-kind">{t(`flow.kind.${stage.n}` as MessageKey)}</div>
                        <h3>{t(k('title'))}</h3>
                      </div>
                    </header>
                    <p className="flow-what">{t(k('what'))}</p>
                    <ul className="flow-items">
                      {(['i1', 'i2', 'i3'] as const).map((i) => (
                        <li key={i}>{t(k(i))}</li>
                      ))}
                    </ul>
                    <div className="flow-example">
                      <div className="flow-example-label">
                        {stage.n === 1 ? t('flow.s1.ex') : t('flow.example')}
                      </div>
                      {stage.example}
                    </div>
                    {stage.metrics ? (
                      <dl className="flow-metrics">
                        {stage.metrics.map((m) => (
                          <div key={m.label}>
                            <dt>{t(m.label)}</dt>
                            <dd>{m.value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <p className="subtle flow-ops-note">{t('flow.opsOnly')}</p>
                    )}
                    <p className="flow-guard">
                      <Icon name="check" size={14} />
                      <span>
                        <strong>{t('flow.guardrail')}:</strong> {t(k('guard'))}
                      </span>
                    </p>
                  </article>
                </li>
              );
            })}
          </ol>
          <p className="subtle" style={{ margin: '10px 0 0' }}>
            {t('flow.exampleNote')} · {t('flow.live', { window: t('overview.window', { n: s?.window_days ?? 90 }) })}
            {canOps && <> · {t('flow.lastRuns')}</>}
          </p>
        </Card>

        <Card title={t('flow.questions')} subtitle={t('flow.questionsSub')}>
          <div className="grid grid-3">
            {QUESTIONS.map((item) => {
              const allowed = can(...item.permissions);
              return (
                <div key={item.q} className="flow-question">
                  <h3>{t(item.q)}</h3>
                  <p className="muted">{t(item.a)}</p>
                  {allowed ? (
                    <Link to={item.to}>{t('flow.open', { page: t(item.page) })}</Link>
                  ) : (
                    <span className="subtle">{t('flow.noAccess')}</span>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </>
  );
}
