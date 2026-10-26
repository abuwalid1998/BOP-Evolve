import { useState, type ChangeEvent } from 'react';
import { api, ApiError, downloadCsv, postDownload, qs } from '../api/client';
import { AiPanel } from '../components/AiPanel';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, Empty, ErrorBox, Field, Kpi, Loading, PageHead, Pager, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

type Stage = 'not_invited' | 'invited' | 'activated' | 'in_progress' | 'completed';
const STAGES: Stage[] = ['not_invited', 'invited', 'activated', 'in_progress', 'completed'];
const STAGE_TONE: Record<Stage, 'neutral' | 'info' | 'warn' | 'ok' | 'brand'> = {
  not_invited: 'neutral',
  invited: 'warn',
  activated: 'info',
  in_progress: 'brand',
  completed: 'ok',
};

interface Grade {
  code: string;
  label: string;
  label_ar: string;
  role: string;
  scope: string;
}

interface Wave {
  id: string;
  name: string;
  description: string | null;
  criteria: { grades: string[]; unit_ids: string[] };
  starts_on: string;
  status: string;
  employee_count: number;
  launched_at: string | null;
  reminder_message: string | null;
  stages: Partial<Record<Stage, number>>;
  candidates: number;
}

interface ImportRef {
  id: string;
  file_name: string;
  status: 'validated' | 'committed' | 'failed';
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  created_count: number;
  updated_count: number;
  created_at: string;
  committed_at: string | null;
  errors?: { line: number; employee_number: string; field: string; code: string }[];
  summary?: {
    by_role: Record<string, number>;
    by_grade: Record<string, number>;
    by_department: Record<string, number>;
    new_units: { code: string; type: string; parent: string; name: string }[];
    new_unit_count: number;
    to_create: number;
    to_update: number;
    customer_facing: number;
  };
  preview?: { employee_number: string; full_name: string; grade: string; job_title: string; unit_code: string; role: string; scope_level: string; exists: boolean }[];
}

interface Overview {
  funnel: Record<'roster' | 'invited' | 'activated' | 'language' | 'tour' | 'policies' | 'quiz' | 'completed', number>;
  by_stage: Partial<Record<Stage, number>>;
  by_department: { unit: { id: string; code: string; name: string; name_ar: string } | null; stages: Partial<Record<Stage, number>>; total: number }[];
  by_grade: { grade: string; label: string; label_ar: string; stages: Partial<Record<Stage, number>>; total: number }[];
  daily_activations: { date: string; count: number }[];
  waves: Wave[];
  imports: ImportRef[];
  grades: Grade[];
}

interface Person {
  user_id: string;
  employee_number: string;
  name: string;
  name_ar: string | null;
  grade: string;
  job_title: string;
  unit: { id: string; code: string; name: string; name_ar: string };
  stage: Stage;
  steps: Record<string, string | null>;
  reminders_sent: number;
}

function StageBar({ stages, total }: { stages: Partial<Record<Stage, number>>; total: number }) {
  const { tx } = useI18n();
  return (
    <div className="ob-stagebar" role="img" aria-label={STAGES.map((s) => `${tx('ob.stage', s)}: ${stages[s] ?? 0}`).join(', ')}>
      {STAGES.map((s) =>
        stages[s] ? <span key={s} className={`ob-seg ${s}`} style={{ width: `${(100 * (stages[s] ?? 0)) / Math.max(total, 1)}%` }} title={`${tx('ob.stage', s)}: ${stages[s]}`} /> : null,
      )}
    </div>
  );
}

function StageLegend() {
  const { tx } = useI18n();
  return (
    <div className="ob-legend">
      {STAGES.map((s) => (
        <span key={s}>
          <i className={`ob-seg ${s}`} /> {tx('ob.stage', s)}
        </span>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- overview
function OverviewTab({ data }: { data: Overview }) {
  const { t, tx, pick, fmtNumber, fmtPercent } = useI18n();
  const f = data.funnel;
  const steps: (keyof Overview['funnel'])[] = ['roster', 'invited', 'activated', 'language', 'tour', 'policies', 'quiz', 'completed'];
  const maxDaily = Math.max(...data.daily_activations.map((d) => d.count), 1);
  return (
    <div className="stack">
      <div className="grid grid-4" data-tour="ob-kpis">
        <Kpi label={t('ob.k.roster')} value={fmtNumber(f.roster)} foot={t('ob.k.rosterFoot', { n: fmtNumber(data.by_stage.not_invited ?? 0) })} />
        <Kpi label={t('ob.k.invited')} value={fmtNumber(f.invited)} foot={t('ob.k.invitedFoot', { p: fmtPercent(f.roster ? f.invited / f.roster : null, 1) })} />
        <Kpi label={t('ob.k.activated')} value={fmtNumber(f.activated)} foot={t('ob.k.activatedFoot', { p: fmtPercent(f.invited ? f.activated / f.invited : null, 1) })} />
        <Kpi label={t('ob.k.completed')} value={fmtNumber(f.completed)} foot={t('ob.k.completedFoot', { p: fmtPercent(f.roster ? f.completed / f.roster : null, 1) })} />
      </div>
      <Card title={t('ob.funnel.title')} subtitle={t('ob.funnel.subtitle')}>
        {f.roster === 0 ? (
          <Empty>{t('ob.funnel.empty')}</Empty>
        ) : (
          <ul className="ob-funnel" data-tour="ob-funnel">
            {steps.map((s) => (
              <li key={s}>
                <span>{t(`ob.step.${s}` as MessageKey)}</span>
                <Bar value={f[s] / Math.max(f.roster, 1)} />
                <span className="num">
                  {fmtNumber(f[s])} <small className="subtle">{fmtPercent(f.roster ? f[s] / f.roster : null, 1)}</small>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="grid grid-2">
        <Card title={t('ob.dept.title')} subtitle={t('ob.dept.subtitle')}>
          {data.by_department.length === 0 ? (
            <Empty />
          ) : (
            <>
              <StageLegend />
              <ul className="ob-rows">
                {data.by_department.map((d) => (
                  <li key={d.unit?.id ?? '-'}>
                    <span>{d.unit ? pick(d.unit.name, d.unit.name_ar) : '—'}</span>
                    <StageBar stages={d.stages} total={d.total} />
                    <span className="num">{fmtNumber(d.total)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title={t('ob.grade.title')} subtitle={t('ob.grade.subtitle')}>
          {data.by_grade.length === 0 ? (
            <Empty />
          ) : (
            <>
              <StageLegend />
              <ul className="ob-rows">
                {data.by_grade.map((g) => (
                  <li key={g.grade}>
                    <span>
                      <span className="mono">{g.grade}</span> · {pick(g.label, g.label_ar)}
                    </span>
                    <StageBar stages={g.stages} total={g.total} />
                    <span className="num">{fmtNumber(g.total)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
      <Card title={t('ob.daily.title')} subtitle={t('ob.daily.subtitle')}>
        <div className="mini-bars">
          {data.daily_activations.map((d) => (
            <div key={d.date} className="mini-bar" title={`${d.date}: ${d.count}`}>
              <span style={{ height: `${Math.max(2, (d.count / maxDaily) * 100)}%` }} />
              <small>{d.date.slice(8)}</small>
            </div>
          ))}
        </div>
      </Card>
      <Card title={t('ob.access.title')} subtitle={t('ob.access.subtitle')}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('ob.col.grade')}</th>
                <th>{t('ob.access.role')}</th>
                <th>{t('ob.access.scope')}</th>
              </tr>
            </thead>
            <tbody>
              {data.grades.map((g) => (
                <tr key={g.code}>
                  <td>
                    <span className="mono">{g.code}</span> · {pick(g.label, g.label_ar)}
                  </td>
                  <td>{tx('role', g.role)}</td>
                  <td>{tx('ob.scope', g.scope)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="subtle">{t('ob.access.note')}</p>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------- import
function ImportTab({ onChanged }: { onChanged: () => void }) {
  const { t, tx, fmtNumber } = useI18n();
  const [record, setRecord] = useState<ImportRef | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setBusy(true);
    setError(null);
    setRecord(null);
    try {
      const content = await file.text();
      setRecord(await api.post<ImportRef>('/api/onboarding/imports', { file_name: file.name, content }));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const commit = async () => {
    if (!record) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api.post<ImportRef>(`/api/onboarding/imports/${record.id}/commit`);
      setRecord(done);
      setToast(t('ob.import.committed', { c: done.created_count, u: done.updated_count }));
      setTimeout(() => setToast(null), 3000);
      onChanged();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const s = record?.summary;

  return (
    <div className="stack">
      <Card title={t('ob.import.title')} subtitle={t('ob.import.subtitle')}>
        <ol className="ob-how">
          <li>{t('ob.import.step1')}</li>
          <li>{t('ob.import.step2')}</li>
          <li>{t('ob.import.step3')}</li>
        </ol>
        <div className="row" data-tour="ob-import">
          <label className={`btn primary${busy ? ' disabled' : ''}`}>
            <Icon name="upload" size={16} /> {t('ob.import.choose')}
            <input type="file" accept=".csv,text/csv" onChange={upload} disabled={busy} hidden />
          </label>
          <button className="btn" onClick={() => downloadCsv('/api/onboarding/sample-roster?size=3400', 'bop-evolve-sample-roster-3400.csv')}>
            <Icon name="download" size={16} /> {t('ob.import.sample')}
          </button>
          {busy && <span className="subtle">{t('ob.import.working')}</span>}
        </div>
        <p className="subtle">{t('ob.import.columns')}</p>
        <ErrorBox error={error} />
      </Card>
      {record && (
        <Card
          title={t('ob.import.result', { file: record.file_name })}
          subtitle={t('ob.import.resultSub', { total: fmtNumber(record.total_rows), valid: fmtNumber(record.valid_rows), errors: fmtNumber(record.error_rows) })}
          actions={
            record.status === 'validated' ? (
              <button className="btn primary" disabled={busy} onClick={commit}>
                {t('ob.import.commit', { n: fmtNumber(record.valid_rows) })}
              </button>
            ) : (
              <Badge tone={record.status === 'committed' ? 'ok' : 'bad'}>{tx('ob.importStatus', record.status)}</Badge>
            )
          }
        >
          {s && record.status !== 'committed' && (
            <div className="grid grid-4">
              <Kpi label={t('ob.import.toCreate')} value={fmtNumber(s.to_create)} />
              <Kpi label={t('ob.import.toUpdate')} value={fmtNumber(s.to_update)} />
              <Kpi label={t('ob.import.newUnits')} value={fmtNumber(s.new_unit_count)} />
              <Kpi label={t('ob.import.customerFacing')} value={fmtNumber(s.customer_facing)} />
            </div>
          )}
          {record.status === 'committed' && (
            <div className="callout brand">{t('ob.import.committed', { c: record.created_count, u: record.updated_count })}</div>
          )}
          {s && Object.keys(s.by_role).length > 0 && (
            <div className="grid grid-2" style={{ marginTop: 12 }}>
              <div>
                <h4>{t('ob.import.byRole')}</h4>
                <ul className="ob-rows compact">
                  {Object.entries(s.by_role).map(([role, n]) => (
                    <li key={role}>
                      <span>{tx('role', role)}</span>
                      <span className="num">{fmtNumber(n)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4>{t('ob.import.byGrade')}</h4>
                <ul className="ob-rows compact">
                  {Object.entries(s.by_grade).map(([g, n]) => (
                    <li key={g}>
                      <span className="mono">{g}</span>
                      <span className="num">{fmtNumber(n)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {record.errors && record.errors.length > 0 && (
            <>
              <h4>{t('ob.import.errors')}</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th className="num">{t('ob.import.line')}</th>
                      <th>{t('ob.col.number')}</th>
                      <th>{t('ob.import.field')}</th>
                      <th>{t('ob.import.problem')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.errors.slice(0, 100).map((e, i) => (
                      <tr key={i}>
                        <td className="num">{e.line}</td>
                        <td className="mono">{e.employee_number || '—'}</td>
                        <td className="mono">{e.field}</td>
                        <td>{tx('ob.err', e.code)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {record.preview && record.preview.length > 0 && record.status === 'validated' && (
            <>
              <h4>{t('ob.import.preview')}</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t('ob.col.number')}</th>
                      <th>{t('ob.col.name')}</th>
                      <th>{t('ob.col.grade')}</th>
                      <th>{t('ob.col.title')}</th>
                      <th>{t('explorer.unit')}</th>
                      <th>{t('ob.access.role')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {record.preview.map((r) => (
                      <tr key={r.employee_number}>
                        <td className="mono">{r.employee_number}</td>
                        <td>{r.full_name}</td>
                        <td className="mono">{r.grade}</td>
                        <td>{r.job_title}</td>
                        <td className="mono">{r.unit_code}</td>
                        <td>
                          {tx('role', r.role)} <span className="subtle">· {tx('ob.scope', r.scope_level)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}
      <Toast message={toast} />
    </div>
  );
}

// ---------------------------------------------------------------- waves
function WavesTab({ data, onChanged }: { data: Overview; onChanged: () => void }) {
  const { t, tx, pick, fmtNumber, fmtDate } = useI18n();
  const units = useApi<{ id: string; code: string; type: string; name: string; name_ar: string; parent_id: string | null }[]>('/api/onboarding/units');
  const [form, setForm] = useState({ name: '', description: '', grades: [] as string[], unit_ids: [] as string[], starts_on: new Date().toISOString().slice(0, 10) });
  const [preview, setPreview] = useState<{ count: number; by_grade: Record<string, number> } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reminder, setReminder] = useState<Record<string, { en: string; ar: string }>>({});
  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3500);
  };
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  const toggleGrade = (g: string) =>
    setForm({ ...form, grades: form.grades.includes(g) ? form.grades.filter((x) => x !== g) : [...form.grades, g] });
  const unitOptions = (units.data ?? []).filter((u) => u.type === 'department' || u.type === 'region' || u.type === 'branch');

  return (
    <div className="stack">
      <Card title={t('ob.wave.new')} subtitle={t('ob.wave.newSub')}>
        <div className="grid grid-2">
          <div className="stack" style={{ gap: 10 }}>
            <Field label={t('ob.wave.name')}>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t('ob.wave.namePh')} />
            </Field>
            <Field label={t('ob.wave.description')}>
              <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Field>
            <Field label={t('ob.wave.starts')}>
              <input type="date" value={form.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} dir="ltr" />
            </Field>
          </div>
          <div className="stack" style={{ gap: 10 }}>
            <span className="subtle">{t('ob.wave.grades')}</span>
            <div className="ob-chips">
              {data.grades.map((g) => (
                <button key={g.code} className={`chip${form.grades.includes(g.code) ? ' active' : ''}`} aria-pressed={form.grades.includes(g.code)} onClick={() => toggleGrade(g.code)}>
                  <span className="mono">{g.code}</span> {pick(g.label, g.label_ar)}
                </button>
              ))}
            </div>
            <Field label={t('ob.wave.units')} help={t('ob.wave.unitsHelp')}>
              <select
                multiple
                size={6}
                value={form.unit_ids}
                onChange={(e) => setForm({ ...form, unit_ids: Array.from(e.target.selectedOptions).map((o) => o.value) })}
              >
                {unitOptions.map((u) => (
                  <option key={u.id} value={u.id}>
                    {tx('level', u.type)} · {pick(u.name, u.name_ar)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button
            className="btn"
            disabled={busy || form.name.length < 3}
            onClick={() => run(async () => setPreview(await api.post('/api/onboarding/waves/preview', form)))}
          >
            {t('ob.wave.preview')}
          </button>
          {preview && <span className="subtle">{t('ob.wave.previewN', { n: fmtNumber(preview.count) })}</span>}
          <div className="spacer" />
          <button
            className="btn primary"
            disabled={busy || form.name.length < 3}
            onClick={() =>
              run(async () => {
                await api.post('/api/onboarding/waves', form);
                setForm({ ...form, name: '', description: '' });
                setPreview(null);
                flash(t('ob.wave.created'));
                onChanged();
              })
            }
          >
            {t('ob.wave.create')}
          </button>
        </div>
        <ErrorBox error={error} />
      </Card>

      <Card title={t('ob.wave.list')} subtitle={t('ob.wave.listSub')}>
        {data.waves.length === 0 ? (
          <Empty>{t('ob.wave.none')}</Empty>
        ) : (
          <ul className="ob-waves">
            {data.waves.map((w) => {
              const total = Object.values(w.stages).reduce((a, b) => a + (b ?? 0), 0);
              return (
                <li key={w.id} className="card">
                  <div className="row between">
                    <div>
                      <strong>{w.name}</strong> <Badge tone={w.status === 'launched' ? 'info' : 'neutral'}>{tx('ob.waveStatus', w.status)}</Badge>
                      <div className="subtle">
                        {t('ob.wave.meta', { date: fmtDate(w.starts_on), invited: fmtNumber(w.employee_count), waiting: fmtNumber(w.candidates) })}
                      </div>
                      {w.description && <div className="subtle">{w.description}</div>}
                    </div>
                    <button
                      className="btn small primary"
                      disabled={busy || w.candidates === 0}
                      data-tour="ob-launch"
                      onClick={() =>
                        run(async () => {
                          const headers = await postDownload(`/api/onboarding/waves/${w.id}/launch`, `activation-codes-${w.id}.csv`);
                          flash(t('ob.wave.launched', { n: headers.get('X-Codes-Issued') ?? '?' }));
                          onChanged();
                        })
                      }
                    >
                      <Icon name="key" size={14} /> {w.launched_at ? t('ob.wave.relaunch', { n: w.candidates }) : t('ob.wave.launch', { n: w.candidates })}
                    </button>
                  </div>
                  {total > 0 && <StageBar stages={w.stages} total={total} />}
                  {w.launched_at && (
                    <div className="ob-reminder">
                      <AiPanel<{ subject: string; message_en: string; message_ar: string }>
                        compact
                        feature="onboarding"
                        title={t('ob.reminder.ai')}
                        endpoint={`/api/onboarding/waves/${w.id}/reminder-draft`}
                        render={(r) => (
                          <div className="stack" style={{ gap: 6 }}>
                            <strong>{r.output.subject}</strong>
                            <p>{r.output.message_en}</p>
                            <p dir="rtl" lang="ar">{r.output.message_ar}</p>
                            <button className="btn small" onClick={() => setReminder({ ...reminder, [w.id]: { en: r.output.message_en, ar: r.output.message_ar } })}>
                              {t('ob.reminder.use')}
                            </button>
                          </div>
                        )}
                      />
                      <Field label={t('ob.reminder.en')}>
                        <textarea rows={2} value={reminder[w.id]?.en ?? w.reminder_message ?? ''} onChange={(e) => setReminder({ ...reminder, [w.id]: { en: e.target.value, ar: reminder[w.id]?.ar ?? '' } })} />
                      </Field>
                      <Field label={t('ob.reminder.ar')}>
                        <textarea rows={2} dir="rtl" value={reminder[w.id]?.ar ?? ''} onChange={(e) => setReminder({ ...reminder, [w.id]: { en: reminder[w.id]?.en ?? '', ar: e.target.value } })} />
                      </Field>
                      <button
                        className="btn small"
                        disabled={busy || (reminder[w.id]?.en ?? '').length < 10}
                        onClick={() =>
                          run(async () => {
                            const r = await api.post<{ recipients: number }>(`/api/onboarding/waves/${w.id}/reminder`, {
                              message: reminder[w.id].en,
                              message_ar: reminder[w.id].ar || null,
                            });
                            flash(t('ob.reminder.sent', { n: r.recipients }));
                            onChanged();
                          })
                        }
                      >
                        {t('ob.reminder.send')}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p className="subtle">
          <Icon name="info" size={13} /> {t('ob.wave.codesNote')}
        </p>
      </Card>
      <Toast message={toast} />
    </div>
  );
}

// --------------------------------------------------------------- people
function PeopleTab({ waves }: { waves: Wave[] }) {
  const { t, tx, pick, fmtDate } = useI18n();
  const [stage, setStage] = useState('');
  const [wave, setWave] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const data = useApi<{ total: number; page: number; page_size: number; items: Person[] }>(
    `/api/onboarding/people${qs({ stage, wave_id: wave, q, page })}`,
  );
  return (
    <Card
      title={t('ob.people.title')}
      subtitle={t('ob.people.subtitle')}
      actions={
        <>
          <input placeholder={t('ob.people.search')} value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} style={{ width: 200 }} />
          <select value={stage} onChange={(e) => { setStage(e.target.value); setPage(1); }} aria-label={t('ob.people.stage')}>
            <option value="">{t('common.all')}</option>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {tx('ob.stage', s)}
              </option>
            ))}
          </select>
          <select value={wave} onChange={(e) => { setWave(e.target.value); setPage(1); }} aria-label={t('ob.people.wave')}>
            <option value="">{t('ob.people.allWaves')}</option>
            {waves.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </>
      }
    >
      <ErrorBox error={data.error} onRetry={data.reload} />
      {!data.data && data.loading && <Loading />}
      {data.data && data.data.items.length === 0 && <Empty />}
      {data.data && data.data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('ob.col.number')}</th>
                <th>{t('ob.col.name')}</th>
                <th>{t('ob.col.grade')}</th>
                <th>{t('explorer.unit')}</th>
                <th>{t('ob.col.stage')}</th>
                <th>{t('ob.col.last')}</th>
                <th className="num">{t('ob.col.reminders')}</th>
              </tr>
            </thead>
            <tbody>
              {data.data.items.map((p) => {
                const last = Object.values(p.steps).filter(Boolean).sort().pop() ?? null;
                return (
                  <tr key={p.user_id}>
                    <td className="mono">{p.employee_number}</td>
                    <td>
                      {pick(p.name, p.name_ar)}
                      <div className="subtle">{p.job_title}</div>
                    </td>
                    <td className="mono">{p.grade}</td>
                    <td>{pick(p.unit.name, p.unit.name_ar)}</td>
                    <td>
                      <Badge tone={STAGE_TONE[p.stage]}>{tx('ob.stage', p.stage)}</Badge>
                    </td>
                    <td>{last ? fmtDate(last) : '—'}</td>
                    <td className="num">{p.reminders_sent}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data.data && <Pager page={page} pageSize={data.data.page_size} total={data.data.total} onPage={setPage} />}
    </Card>
  );
}

// ----------------------------------------------------------------- page
type Tab = 'overview' | 'import' | 'waves' | 'people';

export default function OnboardingPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('overview');
  const { data, error, loading, reload } = useApi<Overview>('/api/onboarding/overview');
  return (
    <>
      <PageHead title={t('ob.title')} subtitle={t('ob.subtitle')} />
      <PageBrief page="onboarding" />
      <div className="callout brand ob-plan" data-tour="ob-plan">
        <strong>{t('ob.plan.title')}</strong>
        <ol>
          {(['1', '2', '3', '4', '5'] as const).map((n) => (
            <li key={n}>{t(`ob.plan.${n}` as MessageKey)}</li>
          ))}
        </ol>
      </div>
      <div className="tabs" role="tablist">
        {(['overview', 'import', 'waves', 'people'] as const).map((id) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {t(`ob.tab.${id}` as MessageKey)}
          </button>
        ))}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {!data && loading && <Loading />}
      {data && tab === 'overview' && <OverviewTab data={data} />}
      {tab === 'import' && <ImportTab onChanged={reload} />}
      {data && tab === 'waves' && <WavesTab data={data} onChanged={reload} />}
      {data && tab === 'people' && <PeopleTab waves={data.waves} />}
    </>
  );
}
