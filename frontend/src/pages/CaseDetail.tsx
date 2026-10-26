import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { CaseDetail, FindingDetail } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AiPanel } from '../components/AiPanel';
import { PageBrief } from '../components/PageBrief';
import { Badge, Card, ErrorBox, Field, Loading, PageHead, StatusBadge, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

const DECISIONS = ['confirm', 'amend', 'dispute_upheld', 'dismiss'];
const FACTORS = ['individual_action', 'policy_ambiguity', 'process_design', 'system_issue', 'workload', 'undetermined'];
const AWARENESS = ['recognized', 'not_recognized', 'unsure', 'disagree'];
const CONTEXT = ['queue_pressure', 'unclear_guidance', 'system_slow', 'customer_urgency'];
const ACTION_TYPES = ['coaching', 'training', 'job_aid', 'practice', 'policy_clarification', 'system_fix'];

function useSubmit(onDone: () => void) {
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, run };
}

function TriState({ value }: { value: boolean | null }) {
  const { t } = useI18n();
  if (value === null || value === undefined) return <span className="subtle">—</span>;
  return value ? <Badge tone="ok">{t('common.yes')}</Badge> : <Badge tone="warn">{t('common.no')}</Badge>;
}

function ReviewForm({ finding, onDone }: { finding: FindingDetail; onDone: () => void }) {
  const { t, tx } = useI18n();
  const [decision, setDecision] = useState('confirm');
  const [rationale, setRationale] = useState('');
  const [factor, setFactor] = useState(finding.contributing_factor || 'undetermined');
  const [severity, setSeverity] = useState('low');
  const [policyClear, setPolicyClear] = useState(true);
  const [evidenceSupports, setEvidenceSupports] = useState(true);
  const [systemIssue, setSystemIssue] = useState(false);
  const { error, busy, run } = useSubmit(onDone);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(() =>
      api.post(`/api/findings/${finding.id}/review`, {
        decision,
        rationale,
        contributing_factor: factor,
        policy_clear: policyClear,
        evidence_supports: evidenceSupports,
        system_issue_contributed: systemIssue,
        amended_severity: decision === 'amend' ? severity : null,
      }),
    );
  };

  return (
    <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
      <h3>{t('case.reviewTitle')}</h3>
      <div className="grid grid-2">
        <Field label={t('case.decision')}>
          <select value={decision} onChange={(e) => setDecision(e.target.value)}>
            {DECISIONS.map((d) => (
              <option key={d} value={d}>
                {tx('decision', d)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('case.contributingFactor')}>
          <select value={factor} onChange={(e) => setFactor(e.target.value)}>
            {FACTORS.map((f) => (
              <option key={f} value={f}>
                {tx('factor', f)}
              </option>
            ))}
          </select>
        </Field>
        {decision === 'amend' && (
          <Field label={t('case.amendedSeverity')}>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {['low', 'medium', 'high', 'critical'].map((s) => (
                <option key={s} value={s}>
                  {tx('severity', s)}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      <div className="row" style={{ gap: 18 }}>
        <label className="check">
          <input type="checkbox" checked={policyClear} onChange={(e) => setPolicyClear(e.target.checked)} />
          {t('case.policyClear')}
        </label>
        <label className="check">
          <input type="checkbox" checked={evidenceSupports} onChange={(e) => setEvidenceSupports(e.target.checked)} />
          {t('case.evidenceSupports')}
        </label>
        <label className="check">
          <input type="checkbox" checked={systemIssue} onChange={(e) => setSystemIssue(e.target.checked)} />
          {t('case.systemIssue')}
        </label>
      </div>
      <Field label={t('case.rationale')} help={t('case.rationaleHelp')}>
        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} minLength={10} required />
      </Field>
      <ErrorBox error={error} />
      <div>
        <button className="btn primary" disabled={busy || rationale.trim().length < 10}>
          {t('common.submit')}
        </button>
      </div>
    </form>
  );
}

function ResponseForm({ finding, onDone }: { finding: FindingDetail; onDone: () => void }) {
  const { t, tx } = useI18n();
  const hasBefore = finding.responses.some((r) => r.stage === 'before_feedback');
  const hasAfter = finding.responses.some((r) => r.stage === 'after_feedback');
  const reviewed = finding.decisions.length > 0;
  const stage = !hasBefore ? 'before_feedback' : reviewed && !hasAfter ? 'after_feedback' : null;
  const [awareness, setAwareness] = useState('recognized');
  const [understood, setUnderstood] = useState(true);
  const [context, setContext] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [requestReview, setRequestReview] = useState(false);
  const { error, busy, run } = useSubmit(onDone);
  if (!stage || finding.status === 'DISMISSED') return null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(() =>
      api.post(`/api/findings/${finding.id}/employee-response`, {
        stage,
        awareness_state: stage === 'before_feedback' ? awareness : null,
        understood_after_feedback: stage === 'after_feedback' ? understood : null,
        contextual_factors: context,
        response_text: text || null,
        requested_review: requestReview,
      }),
    );
  };

  return (
    <form
      className="callout brand"
      style={{ flexDirection: 'column', alignItems: 'stretch', gap: 12 }}
      onSubmit={submit}
    >
      <h3>{t('case.respondTitle')}</h3>
      {stage === 'before_feedback' ? (
        <>
          <span>{t('case.respondBefore')}</span>
          <div className="stack" style={{ gap: 6 }}>
            {AWARENESS.map((a) => (
              <label key={a} className="check">
                <input type="radio" name={`aw-${finding.id}`} checked={awareness === a} onChange={() => setAwareness(a)} />
                {tx('awareness', a)}
              </label>
            ))}
          </div>
          <div className="row" style={{ gap: 14 }}>
            <strong className="subtle">{t('case.context')}</strong>
            {CONTEXT.map((c) => (
              <label key={c} className="check">
                <input
                  type="checkbox"
                  checked={context.includes(c)}
                  onChange={(e) => setContext(e.target.checked ? [...context, c] : context.filter((x) => x !== c))}
                />
                {tx('context', c)}
              </label>
            ))}
          </div>
          {awareness === 'disagree' && (
            <label className="check">
              <input type="checkbox" checked={requestReview} onChange={(e) => setRequestReview(e.target.checked)} />
              {t('case.requestReview')}
            </label>
          )}
        </>
      ) : (
        <>
          <span>{t('case.respondAfter')}</span>
          <div className="row">
            <label className="check">
              <input type="radio" name={`un-${finding.id}`} checked={understood} onChange={() => setUnderstood(true)} />
              {t('common.yes')}
            </label>
            <label className="check">
              <input type="radio" name={`un-${finding.id}`} checked={!understood} onChange={() => setUnderstood(false)} />
              {t('common.no')}
            </label>
          </div>
        </>
      )}
      <Field label={t('case.comment')}>
        <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} />
      </Field>
      <ErrorBox error={error} />
      <div>
        <button className="btn primary" disabled={busy}>
          {t('common.submit')}
        </button>
      </div>
    </form>
  );
}

function ActionsPanel({
  finding,
  canManage,
  canUpdateOwn,
  onDone,
}: {
  finding: FindingDetail;
  canManage: boolean;
  canUpdateOwn: boolean;
  onDone: () => void;
}) {
  const { t, tx, pick, fmtDate } = useI18n();
  const [type, setType] = useState('coaching');
  const [description, setDescription] = useState('');
  const [due, setDue] = useState(() => new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10));
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const { error, busy, run } = useSubmit(onDone);
  const canAdd = canManage && (finding.status === 'CONFIRMED' || finding.status === 'AMENDED');

  const update = (id: string, status: string) =>
    run(() => api.patch(`/api/actions/${id}`, { status, completion_evidence_ref: evidence[id] || undefined }));

  return (
    <div className="stack" style={{ gap: 10 }} data-tour="case-actions">
      <h3>{t('case.actions')}</h3>
      {finding.actions.length === 0 && <span className="subtle">{t('case.noActions')}</span>}
      {finding.actions.map((a) => (
        <div key={a.id} className="card" style={{ padding: 12, boxShadow: 'none' }}>
          <div className="row between">
            <div className="row" style={{ gap: 8 }}>
              <strong>{tx('actionType', a.action_type)}</strong>
              <StatusBadge prefix="actionStatus" value={a.status} />
              {a.overdue && <Badge tone="bad">{t('case.overdue')}</Badge>}
            </div>
            <span className="subtle">{t('case.due', { date: fmtDate(a.due_at) })}</span>
          </div>
          <div className="muted" style={{ marginTop: 4 }}>
            {a.description}
          </div>
          <div className="subtle">
            {t('case.owner')}: {a.owner ? pick(a.owner.name, a.owner.name_ar) : '—'}
            {a.completion_evidence_ref && (
              <>
                {' · '}
                <span className="mono">{a.completion_evidence_ref}</span>
              </>
            )}
          </div>
          {(canManage || canUpdateOwn) && (a.status === 'planned' || a.status === 'in_progress') && (
            <div className="row" style={{ marginTop: 8 }}>
              {a.status === 'planned' && (
                <button className="btn small" disabled={busy} onClick={() => update(a.id, 'in_progress')}>
                  {t('case.start')}
                </button>
              )}
              <input
                placeholder={t('case.evidenceRefHelp')}
                aria-label={t('case.evidenceRef')}
                value={evidence[a.id] ?? ''}
                onChange={(e) => setEvidence({ ...evidence, [a.id]: e.target.value })}
                style={{ flex: 1, minWidth: 200 }}
                dir="ltr"
              />
              <button className="btn small primary" disabled={busy || !evidence[a.id]} onClick={() => update(a.id, 'completed')}>
                {t('case.complete')}
              </button>
            </div>
          )}
        </div>
      ))}
      {canAdd && (
        <form
          className="grid grid-3"
          onSubmit={(e) => {
            e.preventDefault();
            run(() =>
              api.post(`/api/findings/${finding.id}/actions`, {
                action_type: type,
                description,
                due_at: new Date(`${due}T17:00:00`).toISOString(),
              }),
            ).then(() => setDescription(''));
          }}
        >
          <Field label={t('case.actionType')}>
            <select value={type} onChange={(e) => setType(e.target.value)}>
              {ACTION_TYPES.map((a) => (
                <option key={a} value={a}>
                  {tx('actionType', a)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('case.description')}>
            <input value={description} onChange={(e) => setDescription(e.target.value)} minLength={5} required />
          </Field>
          <Field label={t('case.dueAt')}>
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} required />
          </Field>
          <div>
            <button className="btn" disabled={busy || description.trim().length < 5}>
              {t('case.addAction')}
            </button>
          </div>
        </form>
      )}
      <ErrorBox error={error} />
    </div>
  );
}

function FindingCard({ finding, detail, onDone }: { finding: FindingDetail; detail: CaseDetail; onDone: () => void }) {
  const { t, tx, pick, fmtDate, fmtPercent } = useI18n();
  const { can } = useAuth();
  const before = [...finding.responses].reverse().find((r) => r.stage === 'before_feedback');
  const after = [...finding.responses].reverse().find((r) => r.stage === 'after_feedback');
  const lastDecision = finding.decisions[finding.decisions.length - 1];

  return (
    <Card
      title={
        <span className="row" style={{ gap: 8 }}>
          <span className="id">{finding.id}</span>
          <StatusBadge prefix="status" value={finding.status} />
          <StatusBadge prefix="severity" value={finding.severity} />
        </span>
      }
      subtitle={`${t('timeline.finding')} ${fmtDate(finding.created_at, true)}`}
    >
      <div className="stack">
        <div className="grid grid-2">
          <div className="stack" style={{ gap: 10 }} data-tour="case-why">
            <h3>{t('case.whyMistake')}</h3>
            <p style={{ margin: 0 }}>{pick(finding.explanation, finding.explanation_ar)}</p>
            {finding.matched_conditions.length > 0 && (
              <div className="matched-conditions">
                <h4>{t('case.matchedTitle', { rule: pick(finding.rule.name, finding.rule.name_ar) || finding.rule.code })}</h4>
                <table>
                  <thead>
                    <tr>
                      <th>{t('case.matchedFact')}</th>
                      <th>{t('case.matchedRule')}</th>
                      <th>{t('case.matchedObserved')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {finding.matched_conditions.map((c) => (
                      <tr key={c.field + c.op}>
                        <td>{pick(c.label, c.label_ar)}</td>
                        <td>
                          {pick(c.op_label, c.op_label_ar)} {pick(c.value_label ?? '', c.value_label_ar ?? '')}
                        </td>
                        <td>
                          <strong>{pick(c.actual_label ?? '—', c.actual_label_ar ?? '—')}</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {can('rules.view') && (
                  <Link to="/rules" className="subtle">
                    {t('case.matchedOpenRules')}
                  </Link>
                )}
              </div>
            )}
            <dl className="dl">
              <dt>{t('case.expected')}</dt>
              <dd>{pick(finding.rule.expected_action, finding.rule.expected_action_ar)}</dd>
              <dt>{t('case.observed')}</dt>
              <dd>{pick(finding.observed_action, finding.observed_action_ar)}</dd>
              <dt>{t('case.policy')}</dt>
              <dd>
                <span className="mono">
                  {finding.policy.code} v{finding.policy.version}
                </span>{' '}
                — {pick(finding.policy.title, finding.policy.title_ar)}
                <div className="subtle">{t('case.policyEffective', { from: fmtDate(finding.policy.effective_from) })}</div>
              </dd>
              <dt>{t('case.rule')}</dt>
              <dd className="mono">
                {finding.rule.code} v{finding.rule.version}
              </dd>
              <dt>{t('case.modelInfo')}</dt>
              <dd>
                {tx('method', finding.detection_method)} · {t('explorer.confidence')} {fmtPercent(finding.confidence)}
                {finding.model && (
                  <div className="subtle">
                    {finding.model.name} v{finding.model.version} · <StatusBadge prefix="model" value={finding.model.status} />
                  </div>
                )}
              </dd>
              {finding.model && (
                <>
                  <dt>{t('case.limitations')}</dt>
                  <dd className="subtle">{finding.model.limitations}</dd>
                </>
              )}
            </dl>
            <div className="callout info" style={{ padding: '8px 12px' }}>
              {t('case.advisory')}
            </div>
          </div>

          <div className="stack" style={{ gap: 10 }} data-tour="case-voice">
            <h3>{t('case.awarenessTitle')}</h3>
            <span className="subtle">{t('case.awarenessNote')}</span>
            <div className="card" style={{ padding: 12, boxShadow: 'none' }}>
              <strong>1 · {t('case.selfReported')}</strong>
              <div style={{ marginTop: 4 }}>
                {before ? (
                  <>
                    {tx('awareness', before.awareness_state)}
                    {before.contextual_factors.length > 0 && (
                      <div className="subtle">{before.contextual_factors.map((c) => tx('context', c)).join(' · ')}</div>
                    )}
                    {before.response_text && <div className="muted">“{before.response_text}”</div>}
                  </>
                ) : (
                  <span className="subtle">{t('case.notYet')}</span>
                )}
                {after && (
                  <div style={{ marginTop: 6 }}>
                    <span className="subtle">{t('stage.after_feedback')}: </span>
                    {after.understood_after_feedback ? t('case.understoodYes') : t('case.understoodNo')}
                  </div>
                )}
              </div>
            </div>
            <div className="card" style={{ padding: 12, boxShadow: 'none' }}>
              <strong>2 · {t('case.reviewerAssessment')}</strong>
              {lastDecision ? (
                <dl className="dl" style={{ marginTop: 6 }}>
                  <dt>{t('case.decision')}</dt>
                  <dd>
                    {tx('decision', lastDecision.decision)}{' '}
                    {lastDecision.reviewer && (
                      <span className="subtle">{t('case.reviewedBy', { name: pick(lastDecision.reviewer.name, lastDecision.reviewer.name_ar) })}</span>
                    )}
                  </dd>
                  <dt>{t('case.policyClear')}</dt>
                  <dd>
                    <TriState value={lastDecision.policy_clear} />
                  </dd>
                  <dt>{t('case.evidenceSupports')}</dt>
                  <dd>
                    <TriState value={lastDecision.evidence_supports} />
                  </dd>
                  <dt>{t('case.systemIssue')}</dt>
                  <dd>
                    <TriState value={lastDecision.system_issue_contributed} />
                  </dd>
                  <dt>{t('case.contributingFactor')}</dt>
                  <dd>{tx('factor', lastDecision.contributing_factor)}</dd>
                </dl>
              ) : (
                <div className="subtle" style={{ marginTop: 4 }}>
                  {t('case.notYet')}
                </div>
              )}
            </div>
            <div className="card" style={{ padding: 12, boxShadow: 'none' }}>
              <strong>3 · {t('case.demonstrated')}</strong>
              <div style={{ marginTop: 4 }}>
                {finding.follow_up ? (
                  <Badge tone={finding.follow_up.recurred ? 'warn' : 'ok'}>
                    {t('case.followUpResult', {
                      comparable: finding.follow_up.comparable_cases,
                      recurrences: finding.follow_up.recurrences,
                    })}
                  </Badge>
                ) : (
                  <span className="subtle">{t('case.followUpPending')}</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {detail.viewer.can_respond && <ResponseForm finding={finding} onDone={onDone} />}
        {can('findings.review', 'actions.manage', 'workforce.view') && !detail.viewer.is_subject && (
          <AiPanel
            key={finding.id}
            feature="case_assistant"
            title={t('case.ai.title')}
            intro={t('case.ai.intro')}
            endpoint={`/api/ai/findings/${finding.id}/assist`}
            keys={['summary', 'likely_root_cause', 'coaching_points', 'questions_for_employee', 'caution']}
          />
        )}
        {finding.can_review && !detail.viewer.is_subject && <ReviewForm finding={finding} onDone={onDone} />}

        <ActionsPanel
          finding={finding}
          canManage={detail.viewer.can_manage_actions}
          canUpdateOwn={can('actions.update_own')}
          onDone={onDone}
        />

        {finding.decisions.length > 0 && (
          <details open data-tour="case-review">
            <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
              {t('case.decisions')} ({finding.decisions.length})
            </summary>
            <ul className="timeline" style={{ marginTop: 10 }}>
              {finding.decisions.map((d) => (
                <li key={d.id}>
                  <strong>{tx('decision', d.decision)}</strong> <span className="subtle">{fmtDate(d.decided_at, true)}</span>
                  <div className="muted">{d.rationale}</div>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}

export default function CaseDetailPage() {
  const { caseId } = useParams();
  const { t, tx, pick, fmtDate } = useI18n();
  const { data, error, loading, reload } = useApi<CaseDetail>(`/api/cases/${caseId}`);
  const [toast, setToast] = useState<string | null>(null);

  const onDone = () => {
    reload();
    setToast(t('case.saved'));
    setTimeout(() => setToast(null), 2000);
  };

  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;

  return (
    <>
      <PageHead
        title={t('case.title', { id: data.id })}
        subtitle={`${tx('caseType', data.case_type)} · ${fmtDate(data.occurred_at, true)}`}
        actions={
          <Link className="btn small" to="/explorer">
            {t('common.back')}
          </Link>
        }
      />
      <PageBrief page="case" />
      <div className="stack">
        <div className="grid grid-3">
          <Card title={t('explorer.case')}>
            <dl className="dl">
              <dt>{t('case.source')}</dt>
              <dd>
                {data.source_system.name}
                <div className="subtle mono">{data.source_case_key}</div>
              </dd>
              <dt>{t('case.interaction')}</dt>
              <dd>{tx('interaction', data.interaction_type)}</dd>
              <dt>{t('case.complexity')}</dt>
              <dd>{tx('complexity', data.complexity_band)}</dd>
              <dt>{t('case.dataQuality')}</dt>
              <dd>{data.data_quality_status}</dd>
              <dt>{t('explorer.employee')}</dt>
              <dd>
                <Link to={`/learning/${data.employee.id}`} className="mono">
                  {data.employee.pseudonym}
                </Link>{' '}
                <span className="subtle">{data.employee.role_title}</span>
              </dd>
              <dt>{t('case.orgPath')}</dt>
              <dd>{data.org_path.map((u) => pick(u.name, u.name_ar)).join(' › ')}</dd>
            </dl>
          </Card>
          <Card title={t('case.evidence')} subtitle={t('case.evidenceNote')}>
            <div className="stack" style={{ gap: 8 }}>
              {data.evidence.map((e) => (
                <div key={e.id}>
                  <div className="row" style={{ gap: 6 }}>
                    <strong>{tx('evidence', e.type)}</strong>
                    {e.access_class === 'restricted' && <Badge tone="warn">{t('common.restricted')}</Badge>}
                  </div>
                  {e.restricted ? (
                    <span className="subtle">{t('case.restrictedEvidence')}</span>
                  ) : (
                    <>
                      <div className="mono subtle">{e.secure_reference}</div>
                      <div className="mono subtle" title="SHA-256">
                        #{e.content_hash?.slice(0, 16)}…
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </Card>
          <Card title={t('case.modelRuns')}>
            <div className="stack" style={{ gap: 8 }}>
              {data.model_runs.map((m) => (
                <div key={m.id}>
                  <strong>{m.model}</strong>
                  <div className="subtle">
                    {fmtDate(m.run_at, true)} · {m.latency_ms} ms · <span className="mono">{m.output_summary}</span> · {m.review_status}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
        {data.findings.map((f) => (
          <FindingCard key={f.id} finding={f} detail={data} onDone={onDone} />
        ))}
      </div>
      <Toast message={toast} />
    </>
  );
}
