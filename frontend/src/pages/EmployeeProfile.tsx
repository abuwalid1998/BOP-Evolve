import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { GenerationVersion, LearningHistory, Snapshot, TimelineItem } from '../api/types';
import { GenBadge, GenerationTrack } from '../components/GenerationTrack';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, ErrorBox, Field, Loading, PageHead, StatusBadge, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

const OUTCOMES = ['discussed', 'practiced', 'demonstrated', 'needs_follow_up'];

function Indicators({ snapshot }: { snapshot: Snapshot }) {
  const { t, tx, fmtPercent } = useI18n();
  return (
    <div className="stack" style={{ gap: 12 }}>
      {Object.entries(snapshot.indicators).map(([key, ind]) => (
        <div key={key}>
          <div className="row between">
            <span>
              {tx('indicator', key)} <span className="subtle">({fmtPercent(ind.weight)})</span>
            </span>
            <span className="subtle">
              {ind.value === null ? t('common.notAvailable') : fmtPercent(ind.value)} · {t('common.sample', { n: ind.n })}
            </span>
          </div>
          <Bar value={ind.value} />
        </div>
      ))}
      <span className="subtle">{t('learning.weightsNote')}</span>
      {snapshot.gaps.length > 0 && (
        <div>
          <h3>{t('learning.gaps')}</h3>
          <ul style={{ margin: '6px 0 0', paddingInlineStart: 18 }}>
            {snapshot.gaps.map((g) => (
              <li key={g}>{tx('gap', g)}</li>
            ))}
          </ul>
        </div>
      )}
      {snapshot.warnings.length > 0 && (
        <div className="row" style={{ gap: 6 }}>
          {snapshot.warnings.map((w) => (
            <Badge key={w} tone="warn">
              {tx('warning', w)}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function timelineLabel(item: TimelineItem, tx: (p: string, v: string) => string, t: (k: MessageKey) => string): string {
  switch (item.type) {
    case 'finding':
      return `${tx('caseType', String(item.category))} · ${tx('status', String(item.status))}`;
    case 'response':
      return item.stage === 'before_feedback'
        ? tx('awareness', String(item.awareness_state))
        : item.understood
          ? t('case.understoodYes')
          : t('case.understoodNo');
    case 'action_completed':
      return tx('actionType', String(item.action_type));
    case 'training':
      return `${item.course_code} · ${item.score ?? '—'}`;
    case 'coaching':
      return tx('outcome', String(item.outcome));
    case 'generation':
      return `${item.code} · ${tx('gen', String(item.code))} · ${tx('genStatus', String(item.status))}`;
    default:
      return item.type;
  }
}

export default function EmployeeProfilePage() {
  const { employeeId } = useParams();
  const { t, tx, pick, fmtDate, fmtPercent } = useI18n();
  const { data, error, loading, reload } = useApi<LearningHistory>(`/api/employees/${employeeId}/learning-history`);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [outcome, setOutcome] = useState('practiced');
  const [reflection, setReflection] = useState('');

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };
  const act = async (fn: () => Promise<string | void>) => {
    setBusy(true);
    setActionError(null);
    try {
      const msg = await fn();
      reload();
      flash(msg || t('case.saved'));
    } catch (err) {
      setActionError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const { employee, current, pending, viewer } = data;

  const decide = (g: GenerationVersion, decision: 'approve' | 'reject') =>
    act(() => api.post(`/api/learning-generations/${g.id}/decision`, { decision }).then(() => undefined));

  return (
    <>
      <PageHead
        title={`${employee.pseudonym} · ${t('learning.profile')}`}
        subtitle={`${employee.role_title} · ${employee.org_path.map((u) => pick(u.name, u.name_ar)).join(' › ')}`}
        actions={
          (viewer.can_approve || viewer.can_record_coaching) && (
            <button
              className="btn"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const res = await api.post<{ created: boolean }>(`/api/employees/${employee.id}/learning-generations/evaluate`);
                  return res.created ? t('learning.reevaluated') : t('learning.noChange');
                })
              }
            >
              {t('learning.reevaluate')}
            </button>
          )
        }
      />
      <PageBrief page="profile" />
      <div className="stack">
        <div className="callout brand">
          <div>
            <strong>{t('learning.metaphor')}</strong>
          </div>
        </div>
        <ErrorBox error={actionError} />

        <Card
          title={t('learning.journey')}
          subtitle={current ? t('learning.gx', { code: current.generation_code }) : t('learning.noGeneration')}
          actions={
            current && (
              <span className="subtle">
                {t('learning.effective')} {fmtDate(current.effective_at)} · {t('learning.score')} {fmtPercent(current.score)} ·{' '}
                {t('learning.coverage')} {fmtPercent(current.coverage)} · {t('learning.evidence')} {current.evidence_count}
              </span>
            )
          }
        >
          <div data-tour="profile-track">
            <GenerationTrack current={current?.generation_code ?? null} />
          </div>
          {pending && (
            <div className="callout" style={{ marginTop: 14 }}>
              <div style={{ flex: 1 }}>
                <strong>{t('learning.gxPending', { code: pending.generation_code })}</strong>
                <p>
                  {t('learning.effective')} {fmtDate(pending.effective_at, true)} · {t('learning.score')} {fmtPercent(pending.score)} ·{' '}
                  {pending.method_version}
                </p>
              </div>
              {viewer.can_approve && (
                <div className="row">
                  <button className="btn small primary" disabled={busy} onClick={() => decide(pending, 'approve')}>
                    {t('learning.approve')}
                  </button>
                  <button className="btn small" disabled={busy} onClick={() => decide(pending, 'reject')}>
                    {t('learning.reject')}
                  </button>
                </div>
              )}
            </div>
          )}
        </Card>

        <div className="grid grid-2">
          <Card title={t('learning.indicators')} subtitle={`${t('learning.liveVsApproved')} · ${data.live_evaluation.generation_code}`}>
            <Indicators snapshot={data.live_evaluation} />
          </Card>
          <Card title={t('learning.history')}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('learning.current')}</th>
                    <th>{t('explorer.status')}</th>
                    <th>{t('learning.effective')}</th>
                    <th>{t('learning.ended')}</th>
                    <th className="num">{t('learning.score')}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...data.versions].reverse().map((v) => (
                    <tr key={v.id}>
                      <td className="mono">{t('learning.version', { n: v.version })}</td>
                      <td>
                        <GenBadge code={v.generation_code} />
                      </td>
                      <td>
                        <StatusBadge prefix="genStatus" value={v.status} />
                      </td>
                      <td>{fmtDate(v.effective_at)}</td>
                      <td>{fmtDate(v.end_at)}</td>
                      <td className="num">{fmtPercent(v.score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="grid grid-2">
          <Card title={t('learning.categories')}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('explorer.category')}</th>
                    <th className="num">{t('learning.cases')}</th>
                    <th className="num">{t('learning.confirmed')}</th>
                    <th className="num">{t('learning.disputed')}</th>
                    <th className="num">{t('overview.dismissed')}</th>
                    <th className="num">{t('learning.pendingReview')}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.categories).map(([cat, c]) => (
                    <tr key={cat}>
                      <td>{tx('caseType', cat)}</td>
                      <td className="num">{c.cases}</td>
                      <td className="num">{c.confirmed}</td>
                      <td className="num">{c.disputed}</td>
                      <td className="num">{c.dismissed}</td>
                      <td className="num">{c.pending}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={t('learning.openActions')}>
            {data.open_actions.length === 0 ? (
              <span className="subtle">{t('common.none')}</span>
            ) : (
              <div className="stack" style={{ gap: 8 }}>
                {data.open_actions.map((a) => (
                  <div key={a.id} className="row between">
                    <div>
                      <strong>{tx('actionType', a.action_type)}</strong> <StatusBadge prefix="actionStatus" value={a.status} />
                      {a.overdue && (
                        <>
                          {' '}
                          <Badge tone="bad">{t('case.overdue')}</Badge>
                        </>
                      )}
                      <div className="subtle">{a.description}</div>
                    </div>
                    <div className="subtle" style={{ textAlign: 'end' }}>
                      {t('case.due', { date: fmtDate(a.due_at) })}
                      {a.case_id && (
                        <div>
                          <Link to={`/cases/${a.case_id}`}>{t('common.view')}</Link>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {viewer.can_record_coaching && (
              <form
                className="stack"
                style={{ gap: 10, marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  act(() =>
                    api
                      .post(`/api/employees/${employee.id}/coaching-sessions`, {
                        outcome_code: outcome,
                        reflection: reflection || null,
                      })
                      .then(() => setReflection('')),
                  );
                }}
              >
                <h3>{t('learning.recordCoaching')}</h3>
                <Field label={t('learning.outcome')}>
                  <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                    {OUTCOMES.map((o) => (
                      <option key={o} value={o}>
                        {tx('outcome', o)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t('learning.reflection')}>
                  <textarea value={reflection} onChange={(e) => setReflection(e.target.value)} maxLength={1000} />
                </Field>
                <div>
                  <button className="btn primary" disabled={busy}>
                    {t('common.save')}
                  </button>
                </div>
              </form>
            )}
          </Card>
        </div>

        <Card title={t('learning.timeline')}>
          <ul className="timeline">
            {data.timeline.slice(0, 60).map((item) => (
              <li key={`${item.type}-${item.id}`}>
                <div className="row" style={{ gap: 8 }}>
                  <strong>{tx('timeline', item.type)}</strong>
                  <span className="subtle">{fmtDate(item.at, true)}</span>
                </div>
                <div className="muted">
                  {timelineLabel(item, tx, t)}
                  {item.type === 'finding' && (
                    <>
                      {' · '}
                      <Link to={`/cases/${String(item.case_id)}`} className="mono">
                        {String(item.case_id)}
                      </Link>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Toast message={toast} />
    </>
  );
}
