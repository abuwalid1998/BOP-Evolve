import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Bar as RBar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Card, Empty, ErrorBox, Field, Kpi, Loading, PageHead, StatusBadge, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

// ------------------------------------------------------------------- types
type FieldType = 'bool' | 'number' | 'enum';

interface CatalogueField {
  key: string;
  type: FieldType;
  label: string;
  label_ar: string;
  case_types: string[] | null;
  options: { value: string; label: string; label_ar: string }[];
  unit: string | null;
  unit_ar: string | null;
  min: number | null;
  max: number | null;
}

interface Catalogue {
  case_types: { code: string; policy_code: string; default_rule: string }[];
  fields: CatalogueField[];
  operators: { key: string; types: FieldType[]; label: string; label_ar: string }[];
  severities: string[];
  kinds: string[];
  max_conditions: number;
}

interface Condition {
  field: string;
  op: string;
  value: string | number | string[] | null;
}

interface Definition {
  match: 'all' | 'any';
  conditions: Condition[];
}

interface Person {
  id: string;
  name: string;
  name_ar: string;
}

type RuleStatus = 'draft' | 'pending_approval' | 'active' | 'retired';

interface Rule {
  id: string;
  code: string;
  version: string;
  category: string;
  kind: 'breach' | 'early_warning';
  name: string;
  name_ar: string;
  description: string;
  description_ar: string;
  expected_action: string;
  expected_action_ar: string;
  observed_action: string | null;
  observed_action_ar: string | null;
  severity: string;
  base_confidence: number;
  conditions: Definition | null;
  status: RuleStatus;
  policy: { id: string; code: string; version: string; title: string; title_ar: string; status: string } | null;
  created_by: Person | null;
  created_at: string | null;
  submitted_by: Person | null;
  submitted_at: string | null;
  approved_by: Person | null;
  approved_at: string | null;
  retired_at: string | null;
  review_note: string | null;
  stats: { findings: number; confirmed: number; dismissed: number; pending: number };
  actions: string[];
  four_eyes_blocked: boolean;
}

interface Policy {
  id: string;
  code: string;
  version: string;
  title: string;
  title_ar: string;
  summary: string;
  summary_ar: string;
  status: string;
  effective_from: string | null;
  effective_to: string | null;
  created_by: Person | null;
  submitted_by: Person | null;
  approved_by: Person | null;
  approved_at: string | null;
  review_note: string | null;
  rules: { id: string; code: string; version: string; status: string; name: string; name_ar: string; kind: string }[];
  actions: string[];
}

interface Projection {
  days: number;
  expected: number;
  low: number;
  high: number;
  expected_confirmed: number | null;
}

interface Backtest {
  days: number;
  cases_evaluated: number;
  matches: number;
  match_rate: number;
  matched_reviewed: number;
  matched_confirmed: number;
  confirm_rate: number | null;
  baseline_confirmed_rate: number;
  lift: number | null;
  condition_hits: number[];
  weekly: { week: string; matches: number }[];
  forecast: Projection[];
  samples: { case_id: string; occurred_at: string }[];
  comparison?: {
    current_matches: number;
    both: number;
    only_proposed: number;
    only_current: number;
    rule?: { id: string; code: string; version: string };
  };
}

const RULE_TONE: Record<string, 'ok' | 'info' | 'warn' | 'neutral'> = {
  draft: 'neutral',
  pending_approval: 'warn',
  active: 'ok',
  retired: 'neutral',
  superseded: 'neutral',
};

// --------------------------------------------------------------- helpers
function useCatalogueText(catalogue: Catalogue | null) {
  const { pick, fmtNumber, t } = useI18n();
  return useMemo(() => {
    const fields = new Map((catalogue?.fields ?? []).map((f) => [f.key, f]));
    const ops = new Map((catalogue?.operators ?? []).map((o) => [o.key, o]));
    const value = (field: CatalogueField | undefined, v: Condition['value']): string => {
      if (v === null || v === undefined) return '';
      if (Array.isArray(v)) return v.map((x) => value(field, x)).join(', ');
      if (field?.type === 'enum') {
        const opt = field.options.find((o) => o.value === v);
        return opt ? pick(opt.label, opt.label_ar) : String(v);
      }
      if (field?.type === 'number') {
        const unit = pick(field.unit ?? '', field.unit_ar ?? '');
        return `${fmtNumber(Number(v))}${unit ? ` ${unit}` : ''}`;
      }
      return String(v);
    };
    const sentence = (c: Condition) => {
      const field = fields.get(c.field);
      const op = ops.get(c.op);
      return [
        field ? pick(field.label, field.label_ar) : c.field,
        op ? pick(op.label, op.label_ar) : c.op,
        value(field, c.value),
      ]
        .filter(Boolean)
        .join(' ');
    };
    const joiner = (match: 'all' | 'any') => (match === 'any' ? t('rules.or') : t('rules.and'));
    return { fields, ops, sentence, joiner };
  }, [catalogue, pick, fmtNumber, t]);
}

function ConditionSentence({ definition, catalogue }: { definition: Definition | null; catalogue: Catalogue | null }) {
  const { t } = useI18n();
  const { sentence, joiner } = useCatalogueText(catalogue);
  if (!definition?.conditions?.length) return <span className="subtle">{t('rules.noConditions')}</span>;
  return (
    <ol className="rule-sentence">
      {definition.conditions.map((c, i) => (
        <li key={i}>
          {i > 0 && <span className="rule-joiner">{joiner(definition.match)}</span>}
          {sentence(c)}
        </li>
      ))}
    </ol>
  );
}

const ERROR_FIELD: Record<string, MessageKey> = {
  rule_code: 'rules.f.code',
  category: 'rules.f.category',
  kind: 'rules.f.kind',
  severity: 'rules.f.severity',
  policy_version_id: 'rules.f.policy',
  conditions: 'rules.builder.title',
  match: 'rules.builder.title',
  note: 'rules.note.required',
  policy_code: 'rules.pol.code',
  title: 'rules.pol.titleEn',
  title_ar: 'rules.pol.titleAr',
  summary: 'rules.pol.summaryEn',
  summary_ar: 'rules.pol.summaryAr',
  name: 'rules.f.name',
  name_ar: 'rules.f.nameAr',
  description: 'rules.f.description',
  description_ar: 'rules.f.descriptionAr',
  expected_action: 'rules.f.expected',
  expected_action_ar: 'rules.f.expectedAr',
  base_confidence: 'rules.f.confidence',
};

/** Turn an API validation error into a readable sentence ("Condition 2 · value: out of range"). */
function errorText(err: unknown, t: (k: MessageKey, v?: Record<string, string | number>) => string): string | null {
  if (!err) return null;
  if (err instanceof ApiError) {
    const detail = err.detail as { errors?: Record<string, string> } | string | undefined;
    if (detail && typeof detail === 'object' && detail.errors) {
      return Object.entries(detail.errors)
        .map(([where, code]) => {
          const m = /^conditions\.(\d+)/.exec(where);
          const place = m ? t('rules.error.condition', { n: Number(m[1]) + 1 }) : ERROR_FIELD[where] ? t(ERROR_FIELD[where]) : where;
          return `${place}: ${t(`rules.error.${code}` as MessageKey)}`;
        })
        .join(' · ');
    }
    if (Array.isArray(detail)) {
      // FastAPI field validation: [{ loc: ['body', 'summary'], msg: '...' }]
      return (detail as { loc?: (string | number)[]; msg?: string }[])
        .map((d) => {
          const where = String(d.loc?.[d.loc.length - 1] ?? '');
          return `${ERROR_FIELD[where] ? t(ERROR_FIELD[where]) : where}: ${d.msg ?? ''}`;
        })
        .join(' · ');
    }
    if (typeof detail === 'string') return detail;
    return err.message;
  }
  return (err as Error).message;
}

// ------------------------------------------------------------- backtest
function BacktestView({
  result,
  catalogue,
  definition,
  compact = false,
}: {
  result: Backtest;
  catalogue: Catalogue | null;
  definition?: Definition | null;
  compact?: boolean;
}) {
  const { t, fmtNumber, fmtPercent, fmtDate, dir, lang } = useI18n();
  const tick = useMemo(
    () => new Intl.DateTimeFormat(lang === 'ar' ? 'ar-PS-u-nu-latn' : 'en-GB', { day: 'numeric', month: 'short' }),
    [lang],
  );
  const { can } = useAuth();
  const { sentence } = useCatalogueText(catalogue);
  const [next30, next90] = result.forecast;
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className={`grid ${compact ? 'grid-2' : 'grid-4'}`}>
        <Kpi
          label={t('rules.bt.matches', { days: result.days })}
          value={fmtNumber(result.matches)}
          foot={t('rules.bt.matchRate', { rate: fmtPercent(result.match_rate, 1), n: fmtNumber(result.cases_evaluated) })}
        />
        <Kpi
          label={t('rules.bt.confirmRate')}
          value={fmtPercent(result.confirm_rate)}
          foot={t('rules.bt.confirmRateFoot', { c: fmtNumber(result.matched_confirmed), r: fmtNumber(result.matched_reviewed) })}
        />
        <Kpi
          label={t('rules.bt.lift')}
          value={result.lift !== null ? `×${fmtNumber(result.lift, 1)}` : '—'}
          foot={t('rules.bt.liftFoot', { base: fmtPercent(result.baseline_confirmed_rate, 1) })}
        />
        <Kpi
          label={t('rules.bt.forecast30')}
          value={fmtNumber(next30.expected, 0)}
          foot={t('rules.bt.range', { low: fmtNumber(next30.low), high: fmtNumber(next30.high) })}
        />
      </div>
      <div className={compact ? 'stack' : 'grid grid-3'}>
        <div className={compact ? '' : 'span-2'}>
          <h4 style={{ margin: '0 0 6px' }}>{t('rules.bt.weekly')}</h4>
          <div style={{ height: 180 }} dir="ltr">
            <ResponsiveContainer>
              <BarChart data={result.weekly} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="week"
                  tickFormatter={(v: string) => tick.format(new Date(v))}
                  tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                  reversed={dir === 'rtl'}
                  minTickGap={28}
                />
                <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-3)' }} orientation={dir === 'rtl' ? 'right' : 'left'} />
                <Tooltip
                  contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}
                  labelFormatter={(v: string) => t('rules.bt.weekOf', { date: fmtDate(v) })}
                  formatter={(v: number) => [fmtNumber(v), t('rules.bt.flagged')]}
                />
                <RBar dataKey="matches" fill="var(--brand)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="stack" style={{ gap: 8 }}>
          <h4 style={{ margin: 0 }}>{t('rules.bt.outlook')}</h4>
          {[next30, next90].map((p) => (
            <div key={p.days} className="rule-forecast">
              <strong>{t('rules.bt.nextDays', { days: p.days })}</strong>
              <span>
                {t('rules.bt.expected', { n: fmtNumber(p.expected, 0), low: fmtNumber(p.low), high: fmtNumber(p.high) })}
              </span>
              {p.expected_confirmed !== null && (
                <span className="subtle">{t('rules.bt.expectedConfirmed', { n: fmtNumber(p.expected_confirmed, 0) })}</span>
              )}
            </div>
          ))}
          <p className="subtle" style={{ margin: 0, fontSize: 12 }}>
            {t('rules.bt.method')}
          </p>
        </div>
      </div>
      {result.comparison && (
        <div className="callout info">
          <Icon name="info" />
          <div>
            <strong>
              {t('rules.bt.compareTitle', {
                rule: result.comparison.rule ? `${result.comparison.rule.code} v${result.comparison.rule.version}` : '',
              })}
            </strong>
            <p>
              {t('rules.bt.compareBody', {
                both: fmtNumber(result.comparison.both),
                added: fmtNumber(result.comparison.only_proposed),
                dropped: fmtNumber(result.comparison.only_current),
                current: fmtNumber(result.comparison.current_matches),
              })}
            </p>
          </div>
        </div>
      )}
      {definition && definition.conditions.length > 1 && (
        <div>
          <h4 style={{ margin: '0 0 6px' }}>{t('rules.bt.conditionHits')}</h4>
          <ul className="rule-hits">
            {definition.conditions.map((c, i) => (
              <li key={i}>
                <span>{sentence(c)}</span>
                <span className="subtle">
                  {fmtNumber(result.condition_hits[i] ?? 0)} · {fmtPercent(result.cases_evaluated ? (result.condition_hits[i] ?? 0) / result.cases_evaluated : 0, 1)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {can('cases.view') && result.samples.length > 0 && (
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <span className="subtle">{t('rules.bt.samples')}</span>
          {result.samples.map((s) => (
            <Link key={s.case_id} to={`/cases/${s.case_id}`} className="mono">
              {s.case_id}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function SavedBacktest({ rule, catalogue }: { rule: Rule; catalogue: Catalogue | null }) {
  const { t } = useI18n();
  const [days, setDays] = useState(90);
  const { data, error, loading } = useApi<Backtest>(`/api/rules/${rule.id}/backtest?days=${days}`);
  return (
    <Card
      title={t('rules.bt.title')}
      subtitle={t(rule.kind === 'early_warning' ? 'rules.bt.subtitleWarning' : 'rules.bt.subtitle')}
      actions={
        <div className="segmented" role="group" aria-label={t('common.window')}>
          {[90, 180, 365].map((d) => (
            <button key={d} className={d === days ? 'active' : ''} onClick={() => setDays(d)} aria-pressed={d === days}>
              {t('common.days', { n: d })}
            </button>
          ))}
        </div>
      }
    >
      <ErrorBox error={error} />
      {data ? <BacktestView result={data} catalogue={catalogue} definition={rule.conditions} /> : loading && <Loading />}
    </Card>
  );
}

// ------------------------------------------------------------- note modal
function NoteModal({
  title,
  body,
  required,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  required: boolean;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: (note: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div className="modal card" role="dialog" aria-modal="true" aria-labelledby="note-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="note-title">{title}</h2>
        <p className="muted">{body}</p>
        <Field label={t(required ? 'rules.note.required' : 'rules.note.optional')}>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} autoFocus />
        </Field>
        {err !== null && <div className="error-box">{errorText(err, t)}</div>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn" onClick={onCancel}>
            {t('common.cancel')}
          </button>
          <button
            className="btn primary"
            disabled={busy || (required && note.trim().length < 5)}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await onConfirm(note.trim());
              } catch (e) {
                setErr(e);
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

interface PendingAction {
  kind: 'approve' | 'reject' | 'retire';
  path: string;
  label: string;
}

function useWorkflow(onDone: (message: string) => void) {
  const { t } = useI18n();
  const [pending, setPending] = useState<PendingAction | null>(null);
  const modal = pending && (
    <NoteModal
      title={t(`rules.wf.${pending.kind}.title` as MessageKey, { item: pending.label })}
      body={t(`rules.wf.${pending.kind}.body` as MessageKey)}
      required={pending.kind !== 'approve'}
      confirmLabel={t(`rules.wf.${pending.kind}` as MessageKey)}
      onCancel={() => setPending(null)}
      onConfirm={async (note) => {
        await api.post(pending.path, { note: note || null });
        setPending(null);
        onDone(t(`rules.wf.${pending.kind}.done` as MessageKey, { item: pending.label }));
      }}
    />
  );
  return { modal, ask: setPending };
}

// --------------------------------------------------------------- editor
interface Draft {
  id?: string;
  from_rule_id?: string | null;
  rule_code: string;
  category: string;
  policy_version_id: string;
  kind: 'breach' | 'early_warning';
  name: string;
  name_ar: string;
  description: string;
  description_ar: string;
  expected_action: string;
  expected_action_ar: string;
  observed_action: string;
  observed_action_ar: string;
  severity: string;
  base_confidence: number;
  conditions: Definition;
  compare_rule_id?: string | null;
}

function draftFrom(rule: Rule, mode: 'edit' | 'version'): Draft {
  return {
    id: mode === 'edit' ? rule.id : undefined,
    from_rule_id: mode === 'version' ? rule.id : null,
    rule_code: rule.code,
    category: rule.category,
    policy_version_id: rule.policy?.id ?? '',
    kind: rule.kind,
    name: rule.name,
    name_ar: rule.name_ar,
    description: rule.description,
    description_ar: rule.description_ar,
    expected_action: rule.expected_action,
    expected_action_ar: rule.expected_action_ar,
    observed_action: rule.observed_action ?? '',
    observed_action_ar: rule.observed_action_ar ?? '',
    severity: rule.severity,
    base_confidence: rule.base_confidence,
    conditions: rule.conditions ?? { match: 'all', conditions: [] },
    compare_rule_id: mode === 'version' && rule.status === 'active' ? rule.id : null,
  };
}

function defaultValue(field: CatalogueField | undefined, op: string): Condition['value'] {
  if (!field || field.type === 'bool') return null;
  if (field.type === 'number') return field.min ?? 0;
  if (op === 'in' || op === 'not_in') return field.options.slice(0, 1).map((o) => o.value);
  return field.options[0]?.value ?? null;
}

function ConditionBuilder({
  catalogue,
  category,
  value,
  onChange,
}: {
  catalogue: Catalogue;
  category: string;
  value: Definition;
  onChange: (next: Definition) => void;
}) {
  const { t, pick } = useI18n();
  const fields = catalogue.fields.filter((f) => !f.case_types || f.case_types.includes(category));
  const opsFor = (type: FieldType) => catalogue.operators.filter((o) => o.types.includes(type));
  const update = (i: number, patch: Partial<Condition>) =>
    onChange({ ...value, conditions: value.conditions.map((c, j) => (j === i ? { ...c, ...patch } : c)) });

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
        <span>{t('rules.builder.flagWhen')}</span>
        <div className="segmented" role="group">
          {(['all', 'any'] as const).map((m) => (
            <button key={m} className={value.match === m ? 'active' : ''} aria-pressed={value.match === m} onClick={() => onChange({ ...value, match: m })} type="button">
              {t(m === 'all' ? 'rules.builder.all' : 'rules.builder.any')}
            </button>
          ))}
        </div>
        <span>{t('rules.builder.ofTheseHold')}</span>
      </div>
      {value.conditions.map((c, i) => {
        const field = fields.find((f) => f.key === c.field);
        const ops = field ? opsFor(field.type) : [];
        return (
          <div key={i} className="cond-row">
            <span className="rule-joiner">{i === 0 ? t('rules.builder.if') : value.match === 'all' ? t('rules.and') : t('rules.or')}</span>
            <select
              aria-label={t('rules.builder.fact')}
              value={c.field}
              onChange={(e) => {
                const next = fields.find((f) => f.key === e.target.value);
                const op = next ? opsFor(next.type)[0]?.key ?? 'eq' : 'eq';
                update(i, { field: e.target.value, op, value: defaultValue(next, op) });
              }}
            >
              {fields.map((f) => (
                <option key={f.key} value={f.key}>
                  {pick(f.label, f.label_ar)}
                </option>
              ))}
            </select>
            <select
              aria-label={t('rules.builder.operator')}
              value={c.op}
              onChange={(e) => update(i, { op: e.target.value, value: defaultValue(field, e.target.value) })}
            >
              {ops.map((o) => (
                <option key={o.key} value={o.key}>
                  {pick(o.label, o.label_ar)}
                </option>
              ))}
            </select>
            {field?.type === 'number' && (
              <span className="row" style={{ gap: 6 }}>
                <input
                  type="number"
                  aria-label={t('rules.builder.value')}
                  value={typeof c.value === 'number' ? c.value : 0}
                  min={field.min ?? undefined}
                  max={field.max ?? undefined}
                  onChange={(e) => update(i, { value: Number(e.target.value) })}
                  dir="ltr"
                  style={{ width: 120 }}
                />
                <span className="subtle">{pick(field.unit ?? '', field.unit_ar ?? '')}</span>
              </span>
            )}
            {field?.type === 'enum' && (c.op === 'in' || c.op === 'not_in') && (
              <span className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                {field.options.map((o) => {
                  const list = Array.isArray(c.value) ? c.value : [];
                  return (
                    <label key={o.value} className="check">
                      <input
                        type="checkbox"
                        checked={list.includes(o.value)}
                        onChange={(e) =>
                          update(i, { value: e.target.checked ? [...list, o.value] : list.filter((v) => v !== o.value) })
                        }
                      />
                      {pick(o.label, o.label_ar)}
                    </label>
                  );
                })}
              </span>
            )}
            {field?.type === 'enum' && c.op !== 'in' && c.op !== 'not_in' && (
              <select aria-label={t('rules.builder.value')} value={String(c.value ?? '')} onChange={(e) => update(i, { value: e.target.value })}>
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {pick(o.label, o.label_ar)}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="btn small ghost"
              aria-label={t('rules.builder.remove')}
              onClick={() => onChange({ ...value, conditions: value.conditions.filter((_, j) => j !== i) })}
            >
              <Icon name="cross" size={14} />
            </button>
          </div>
        );
      })}
      <div>
        <button
          type="button"
          className="btn small"
          disabled={value.conditions.length >= catalogue.max_conditions || fields.length === 0}
          onClick={() => {
            const f = fields[0];
            const op = opsFor(f.type)[0].key;
            onChange({ ...value, conditions: [...value.conditions, { field: f.key, op, value: defaultValue(f, op) }] });
          }}
        >
          + {t('rules.builder.add')}
        </button>
      </div>
    </div>
  );
}

function RuleEditor({
  initial,
  catalogue,
  policies,
  onClose,
  onSaved,
}: {
  initial: Draft;
  catalogue: Catalogue;
  policies: Policy[];
  onClose: () => void;
  onSaved: (rule: Rule, message: string) => void;
}) {
  const { t, tx, pick } = useI18n();
  const [draft, setDraft] = useState<Draft>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [preview, setPreview] = useState<Backtest | null>(null);
  const [previewErr, setPreviewErr] = useState<unknown>(null);
  const isNew = !draft.id && !draft.from_rule_id;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const usablePolicies = policies.filter((p) => p.status === 'active' || p.status === 'draft' || p.status === 'pending_approval');

  // Live impact preview: replay the conditions on history while the author edits them.
  const conditionsKey = JSON.stringify([draft.category, draft.conditions]);
  useEffect(() => {
    if (!draft.conditions.conditions.length) {
      setPreview(null);
      return;
    }
    const handle = window.setTimeout(() => {
      api
        .post<Backtest>('/api/rules/backtest', {
          category: draft.category,
          conditions: draft.conditions,
          days: 180,
          compare_rule_id: draft.compare_rule_id ?? null,
        })
        .then((r) => {
          setPreview(r);
          setPreviewErr(null);
        })
        .catch((e) => setPreviewErr(e));
    }, 500);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conditionsKey, draft.compare_rule_id]);

  const save = async (submit: boolean) => {
    setBusy(true);
    setErr(null);
    const body = {
      from_rule_id: draft.from_rule_id ?? null,
      rule_code: isNew ? draft.rule_code : undefined,
      category: draft.category,
      policy_version_id: draft.policy_version_id,
      kind: draft.kind,
      name: draft.name,
      name_ar: draft.name_ar,
      description: draft.description,
      description_ar: draft.description_ar,
      expected_action: draft.expected_action,
      expected_action_ar: draft.expected_action_ar,
      observed_action: draft.observed_action || null,
      observed_action_ar: draft.observed_action_ar || null,
      severity: draft.severity,
      base_confidence: draft.base_confidence,
      conditions: draft.conditions,
    };
    try {
      let rule = draft.id ? await api.put<Rule>(`/api/rules/${draft.id}`, body) : await api.post<Rule>('/api/rules', body);
      if (submit) rule = await api.post<Rule>(`/api/rules/${rule.id}/submit`);
      onSaved(rule, t(submit ? 'rules.saved.submitted' : 'rules.saved.draft', { item: `${rule.code} v${rule.version}` }));
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };

  const title = draft.id
    ? t('rules.editor.editTitle', { item: `${draft.rule_code}` })
    : draft.from_rule_id
      ? t('rules.editor.versionTitle', { item: draft.rule_code })
      : t('rules.editor.newTitle');

  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal card rule-editor" role="dialog" aria-modal="true" aria-labelledby="rule-editor-title">
        <div className="row between">
          <h2 id="rule-editor-title" style={{ margin: 0 }}>
            {title}
          </h2>
          <button className="btn small ghost" onClick={onClose} aria-label={t('common.cancel')}>
            <Icon name="cross" size={16} />
          </button>
        </div>
        <p className="subtle">{t('rules.editor.intro')}</p>
        <div className="rule-editor-body">
          <div className="stack" style={{ gap: 12 }}>
            <div className="grid grid-2">
              {isNew && (
                <Field label={t('rules.f.code')} help={t('rules.f.codeHelp')}>
                  <input value={draft.rule_code} onChange={(e) => set('rule_code', e.target.value.toUpperCase())} dir="ltr" maxLength={40} />
                </Field>
              )}
              <Field label={t('rules.f.category')}>
                <select
                  value={draft.category}
                  disabled={!isNew}
                  onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value, conditions: { match: d.conditions.match, conditions: [] } }))}
                >
                  {catalogue.case_types.map((c) => (
                    <option key={c.code} value={c.code}>
                      {tx('caseType', c.code)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('rules.f.kind')} help={t(draft.kind === 'breach' ? 'rules.kind.breach.help' : 'rules.kind.early_warning.help')}>
                <select value={draft.kind} onChange={(e) => set('kind', e.target.value as Draft['kind'])}>
                  {catalogue.kinds.map((k) => (
                    <option key={k} value={k}>
                      {tx('rules.kind', k)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('rules.f.policy')} help={t('rules.f.policyHelp')}>
                <select value={draft.policy_version_id} onChange={(e) => set('policy_version_id', e.target.value)}>
                  <option value="">—</option>
                  {usablePolicies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} v{p.version} · {pick(p.title, p.title_ar)} ({tx('rules.status', p.status)})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('rules.f.severity')}>
                <select value={draft.severity} onChange={(e) => set('severity', e.target.value)}>
                  {catalogue.severities.map((s) => (
                    <option key={s} value={s}>
                      {tx('severity', s)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('rules.f.confidence')} help={t('rules.f.confidenceHelp')}>
                <input
                  type="number"
                  min={0.05}
                  max={0.99}
                  step={0.01}
                  value={draft.base_confidence}
                  onChange={(e) => set('base_confidence', Number(e.target.value))}
                  dir="ltr"
                />
              </Field>
            </div>
            <div className="grid grid-2">
              <Field label={t('rules.f.name')}>
                <input value={draft.name} onChange={(e) => set('name', e.target.value)} dir="ltr" />
              </Field>
              <Field label={t('rules.f.nameAr')}>
                <input value={draft.name_ar} onChange={(e) => set('name_ar', e.target.value)} dir="rtl" lang="ar" />
              </Field>
              <Field label={t('rules.f.description')} help={t('rules.f.descriptionHelp')}>
                <textarea rows={2} value={draft.description} onChange={(e) => set('description', e.target.value)} dir="ltr" />
              </Field>
              <Field label={t('rules.f.descriptionAr')}>
                <textarea rows={2} value={draft.description_ar} onChange={(e) => set('description_ar', e.target.value)} dir="rtl" lang="ar" />
              </Field>
              <Field label={t('rules.f.expected')} help={t('rules.f.expectedHelp')}>
                <textarea rows={2} value={draft.expected_action} onChange={(e) => set('expected_action', e.target.value)} dir="ltr" />
              </Field>
              <Field label={t('rules.f.expectedAr')}>
                <textarea rows={2} value={draft.expected_action_ar} onChange={(e) => set('expected_action_ar', e.target.value)} dir="rtl" lang="ar" />
              </Field>
              <Field label={t('rules.f.observed')} help={t('rules.f.observedHelp')}>
                <textarea rows={2} value={draft.observed_action} onChange={(e) => set('observed_action', e.target.value)} dir="ltr" />
              </Field>
              <Field label={t('rules.f.observedAr')}>
                <textarea rows={2} value={draft.observed_action_ar} onChange={(e) => set('observed_action_ar', e.target.value)} dir="rtl" lang="ar" />
              </Field>
            </div>
            <Card title={t('rules.builder.title')} subtitle={t('rules.builder.subtitle')}>
              <ConditionBuilder catalogue={catalogue} category={draft.category} value={draft.conditions} onChange={(v) => set('conditions', v)} />
            </Card>
          </div>
          <div className="stack" style={{ gap: 12 }}>
            <Card title={t('rules.editor.impact')} subtitle={t('rules.editor.impactSub')}>
              {previewErr !== null && <div className="error-box">{errorText(previewErr, t)}</div>}
              {preview ? <BacktestView result={preview} catalogue={catalogue} definition={draft.conditions} compact /> : <Empty>{t('rules.editor.impactEmpty')}</Empty>}
            </Card>
          </div>
        </div>
        {err !== null && <div className="error-box" role="alert">{errorText(err, t)}</div>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
          <span className="subtle" style={{ marginInlineEnd: 'auto' }}>
            {t('rules.editor.fourEyes')}
          </span>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn" disabled={busy} onClick={() => save(false)}>
            {t('rules.editor.saveDraft')}
          </button>
          <button className="btn primary" disabled={busy} onClick={() => save(true)}>
            {t('rules.editor.saveSubmit')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- detail
function WorkflowTrail({ item }: { item: Pick<Rule, 'created_by' | 'created_at' | 'submitted_by' | 'submitted_at' | 'approved_by' | 'approved_at' | 'review_note'> }) {
  const { t, pick, fmtDate } = useI18n();
  const who = (p: Person | null) => (p ? pick(p.name, p.name_ar) : t('rules.trail.system'));
  return (
    <ul className="timeline">
      {item.created_at && (
        <li>
          <strong>{t('rules.trail.drafted')}</strong> · {who(item.created_by)} · <span className="subtle">{fmtDate(item.created_at)}</span>
        </li>
      )}
      {item.submitted_at && (
        <li>
          <strong>{t('rules.trail.submitted')}</strong> · {who(item.submitted_by)} · <span className="subtle">{fmtDate(item.submitted_at)}</span>
        </li>
      )}
      {item.approved_at && (
        <li>
          <strong>{t('rules.trail.approved')}</strong> · {who(item.approved_by)} · <span className="subtle">{fmtDate(item.approved_at)}</span>
        </li>
      )}
      {item.review_note && (
        <li>
          <strong>{t('rules.trail.note')}</strong> · {item.review_note}
        </li>
      )}
    </ul>
  );
}

function RuleDetail({
  rule,
  versions,
  catalogue,
  onEdit,
  onVersion,
  onDone,
  onSelect,
}: {
  rule: Rule;
  versions: Rule[];
  catalogue: Catalogue | null;
  onEdit: () => void;
  onVersion: () => void;
  onDone: (message: string) => void;
  onSelect: (id: string) => void;
}) {
  const { t, tx, pick, fmtNumber, fmtPercent } = useI18n();
  const label = `${rule.code} v${rule.version}`;
  const { modal, ask } = useWorkflow(onDone);
  const [err, setErr] = useState<unknown>(null);
  const has = (a: string) => rule.actions.includes(a);
  const simple = async (path: string, message: MessageKey, method: 'post' | 'del' = 'post') => {
    setErr(null);
    try {
      if (method === 'del') await api.del(path);
      else await api.post(path);
      onDone(t(message, { item: label }));
    } catch (e) {
      setErr(e);
    }
  };

  return (
    <div className="stack">
      {modal}
      <Card
        title={
          <span className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {pick(rule.name, rule.name_ar) || rule.code}
            <Badge tone={RULE_TONE[rule.status]}>{tx('rules.status', rule.status)}</Badge>
            <Badge tone={rule.kind === 'breach' ? 'brand' : 'info'} icon={rule.kind === 'breach' ? 'warn' : 'clock'}>
              {tx('rules.kind', rule.kind)}
            </Badge>
          </span>
        }
        subtitle={
          <span className="mono">
            {label} · {tx('caseType', rule.category)}
            {rule.policy ? ` · ${rule.policy.code} v${rule.policy.version}` : ''}
          </span>
        }
        actions={
          <>
            {has('edit') && (
              <button className="btn small" onClick={onEdit}>
                {t('rules.act.edit')}
              </button>
            )}
            {has('submit') && (
              <button className="btn small primary" onClick={() => simple(`/api/rules/${rule.id}/submit`, 'rules.saved.submitted')}>
                {t('rules.act.submit')}
              </button>
            )}
            {has('delete') && (
              <button className="btn small danger" onClick={() => simple(`/api/rules/${rule.id}`, 'rules.saved.deleted', 'del')}>
                {t('rules.act.delete')}
              </button>
            )}
            {has('approve') && (
              <button className="btn small primary" onClick={() => ask({ kind: 'approve', path: `/api/rules/${rule.id}/approve`, label })}>
                {t('rules.wf.approve')}
              </button>
            )}
            {has('reject') && (
              <button className="btn small" onClick={() => ask({ kind: 'reject', path: `/api/rules/${rule.id}/reject`, label })}>
                {t('rules.wf.reject')}
              </button>
            )}
            {has('new_version') && (
              <button className="btn small" onClick={onVersion}>
                {t('rules.act.newVersion')}
              </button>
            )}
            {has('retire') && (
              <button className="btn small danger" onClick={() => ask({ kind: 'retire', path: `/api/rules/${rule.id}/retire`, label })}>
                {t('rules.wf.retire')}
              </button>
            )}
          </>
        }
      >
        {err !== null && <div className="error-box">{errorText(err, t)}</div>}
        {rule.four_eyes_blocked && (
          <div className="callout" style={{ marginBottom: 12 }}>
            <Icon name="warn" />
            <div>{t('rules.fourEyesBlocked')}</div>
          </div>
        )}
        <div className="grid grid-2">
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <h4 className="rule-h">{t('rules.d.conditions')}</h4>
              <ConditionSentence definition={rule.conditions} catalogue={catalogue} />
            </div>
            <div>
              <h4 className="rule-h">{t('rules.d.risk')}</h4>
              <p style={{ margin: 0 }}>{pick(rule.description, rule.description_ar)}</p>
            </div>
          </div>
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <h4 className="rule-h">{t('rules.d.expected')}</h4>
              <p style={{ margin: 0 }}>{pick(rule.expected_action, rule.expected_action_ar)}</p>
            </div>
            {(rule.observed_action || rule.observed_action_ar) && (
              <div>
                <h4 className="rule-h">{t('rules.d.observed')}</h4>
                <p style={{ margin: 0 }}>{pick(rule.observed_action, rule.observed_action_ar)}</p>
              </div>
            )}
            <dl className="dl">
              <dt>{t('explorer.severity')}</dt>
              <dd>
                <StatusBadge prefix="severity" value={rule.severity} />
              </dd>
              <dt>{t('rules.f.confidence')}</dt>
              <dd>{fmtPercent(rule.base_confidence)}</dd>
              <dt>{t('rules.d.findings')}</dt>
              <dd>
                {t('rules.d.findingsValue', {
                  n: fmtNumber(rule.stats.findings),
                  c: fmtNumber(rule.stats.confirmed),
                  d: fmtNumber(rule.stats.dismissed),
                  p: fmtNumber(rule.stats.pending),
                })}
              </dd>
            </dl>
          </div>
        </div>
        <div className="grid grid-2" style={{ marginTop: 12 }}>
          <div>
            <h4 className="rule-h">{t('rules.d.governance')}</h4>
            <WorkflowTrail item={rule} />
          </div>
          <div>
            <h4 className="rule-h">{t('rules.d.versions')}</h4>
            <ul className="rule-versions">
              {versions.map((v) => (
                <li key={v.id}>
                  <button className={`linklike${v.id === rule.id ? ' current' : ''}`} onClick={() => onSelect(v.id)}>
                    v{v.version}
                  </button>
                  <Badge tone={RULE_TONE[v.status]}>{tx('rules.status', v.status)}</Badge>
                  <span className="subtle">{v.policy ? `${v.policy.code} v${v.policy.version}` : ''}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
      {rule.conditions && <SavedBacktest rule={rule} catalogue={catalogue} />}
    </div>
  );
}

// -------------------------------------------------------------- policies
interface PolicyDraft {
  id?: string;
  from_policy_id?: string | null;
  policy_code: string;
  title: string;
  title_ar: string;
  summary: string;
  summary_ar: string;
  effective_from: string;
}

function PolicyEditor({ initial, onClose, onSaved }: { initial: PolicyDraft; onClose: () => void; onSaved: (message: string) => void }) {
  const { t } = useI18n();
  const [d, setD] = useState(initial);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const isNew = !d.id && !d.from_policy_id;
  const set = <K extends keyof PolicyDraft>(k: K, v: PolicyDraft[K]) => setD((x) => ({ ...x, [k]: v }));
  const save = async (submit: boolean) => {
    setBusy(true);
    setErr(null);
    const body = {
      from_policy_id: d.from_policy_id ?? null,
      policy_code: isNew ? d.policy_code : undefined,
      title: d.title,
      title_ar: d.title_ar,
      summary: d.summary,
      summary_ar: d.summary_ar,
      effective_from: d.effective_from || null,
    };
    try {
      const saved = d.id
        ? await api.put<Policy>(`/api/rules/policies/${d.id}`, body)
        : await api.post<Policy>('/api/rules/policies', body);
      if (submit) await api.post(`/api/rules/policies/${saved.id}/submit`);
      onSaved(t(submit ? 'rules.saved.submitted' : 'rules.saved.draft', { item: `${saved.code} v${saved.version}` }));
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal card" style={{ maxWidth: 760 }} role="dialog" aria-modal="true" aria-labelledby="policy-editor-title">
        <h2 id="policy-editor-title">
          {d.id ? t('rules.pol.editTitle', { item: d.policy_code }) : d.from_policy_id ? t('rules.pol.versionTitle', { item: d.policy_code }) : t('rules.pol.newTitle')}
        </h2>
        <p className="subtle">{t('rules.pol.intro')}</p>
        <div className="grid grid-2">
          {isNew && (
            <Field label={t('rules.pol.code')} help={t('rules.pol.codeHelp')}>
              <input value={d.policy_code} onChange={(e) => set('policy_code', e.target.value.toUpperCase())} dir="ltr" />
            </Field>
          )}
          <Field label={t('rules.pol.effective')} help={t('rules.pol.effectiveHelp')}>
            <input type="date" value={d.effective_from} onChange={(e) => set('effective_from', e.target.value)} dir="ltr" />
          </Field>
          <Field label={t('rules.pol.titleEn')}>
            <input value={d.title} onChange={(e) => set('title', e.target.value)} dir="ltr" />
          </Field>
          <Field label={t('rules.pol.titleAr')}>
            <input value={d.title_ar} onChange={(e) => set('title_ar', e.target.value)} dir="rtl" lang="ar" />
          </Field>
          <Field label={t('rules.pol.summaryEn')} help={t('rules.pol.summaryHelp')}>
            <textarea rows={4} value={d.summary} onChange={(e) => set('summary', e.target.value)} dir="ltr" />
          </Field>
          <Field label={t('rules.pol.summaryAr')}>
            <textarea rows={4} value={d.summary_ar} onChange={(e) => set('summary_ar', e.target.value)} dir="rtl" lang="ar" />
          </Field>
        </div>
        {err !== null && <div className="error-box">{errorText(err, t)}</div>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn" disabled={busy} onClick={() => save(false)}>
            {t('rules.editor.saveDraft')}
          </button>
          <button className="btn primary" disabled={busy} onClick={() => save(true)}>
            {t('rules.editor.saveSubmit')}
          </button>
        </div>
      </div>
    </div>
  );
}

function PoliciesTab({ policies, onChanged }: { policies: Policy[]; onChanged: (message: string) => void }) {
  const { t, tx, pick, fmtDate } = useI18n();
  const { can } = useAuth();
  const [editing, setEditing] = useState<PolicyDraft | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const { modal, ask } = useWorkflow((m) => onChanged(m));
  const today = new Date().toISOString().slice(0, 10);
  return (
    <Card
      title={t('rules.pol.title')}
      subtitle={t('rules.pol.subtitle')}
      actions={
        can('rules.author') && (
          <button
            className="btn small primary"
            onClick={() => setEditing({ policy_code: '', title: '', title_ar: '', summary: '', summary_ar: '', effective_from: today })}
          >
            + {t('rules.pol.new')}
          </button>
        )
      }
    >
      {modal}
      {editing && (
        <PolicyEditor
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={(m) => {
            setEditing(null);
            onChanged(m);
          }}
        />
      )}
      {err !== null && <div className="error-box">{errorText(err, t)}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('rules.pol.policy')}</th>
              <th>{t('rules.col.status')}</th>
              <th>{t('rules.pol.inForce')}</th>
              <th>{t('rules.pol.rules')}</th>
              <th>{t('rules.col.governance')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {policies.map((p) => {
              const label = `${p.code} v${p.version}`;
              return (
                <tr key={p.id}>
                  <td>
                    <span className="mono">{label}</span>
                    <div>
                      <strong>{pick(p.title, p.title_ar)}</strong>
                    </div>
                    <div className="subtle" style={{ maxWidth: 420 }}>
                      {pick(p.summary, p.summary_ar)}
                    </div>
                  </td>
                  <td>
                    <Badge tone={RULE_TONE[p.status] ?? 'neutral'}>{tx('rules.status', p.status)}</Badge>
                  </td>
                  <td>
                    {fmtDate(p.effective_from)} → {p.effective_to ? fmtDate(p.effective_to) : t('rules.pol.open')}
                  </td>
                  <td>
                    {p.rules.length === 0 && <span className="subtle">—</span>}
                    {p.rules.map((r) => (
                      <div key={r.id} className="row" style={{ gap: 6 }}>
                        <span className="mono">
                          {r.code} v{r.version}
                        </span>
                        <Badge tone={RULE_TONE[r.status]}>{tx('rules.status', r.status)}</Badge>
                      </div>
                    ))}
                  </td>
                  <td className="subtle">
                    {p.approved_by ? t('rules.pol.approvedBy', { name: pick(p.approved_by.name, p.approved_by.name_ar) }) : p.submitted_by ? t('rules.pol.submittedBy', { name: pick(p.submitted_by.name, p.submitted_by.name_ar) }) : p.created_by ? t('rules.pol.draftedBy', { name: pick(p.created_by.name, p.created_by.name_ar) }) : '—'}
                    {p.review_note && <div>“{p.review_note}”</div>}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      {p.actions.includes('edit') && (
                        <button
                          className="btn small"
                          onClick={() =>
                            setEditing({
                              id: p.id,
                              policy_code: p.code,
                              title: p.title,
                              title_ar: p.title_ar,
                              summary: p.summary,
                              summary_ar: p.summary_ar,
                              effective_from: (p.effective_from ?? today).slice(0, 10),
                            })
                          }
                        >
                          {t('rules.act.edit')}
                        </button>
                      )}
                      {p.actions.includes('submit') && (
                        <button
                          className="btn small primary"
                          onClick={async () => {
                            setErr(null);
                            try {
                              await api.post(`/api/rules/policies/${p.id}/submit`);
                              onChanged(t('rules.saved.submitted', { item: label }));
                            } catch (e) {
                              setErr(e);
                            }
                          }}
                        >
                          {t('rules.act.submit')}
                        </button>
                      )}
                      {p.actions.includes('approve') && (
                        <button className="btn small primary" onClick={() => ask({ kind: 'approve', path: `/api/rules/policies/${p.id}/approve`, label })}>
                          {t('rules.wf.approve')}
                        </button>
                      )}
                      {p.actions.includes('reject') && (
                        <button className="btn small" onClick={() => ask({ kind: 'reject', path: `/api/rules/policies/${p.id}/reject`, label })}>
                          {t('rules.wf.reject')}
                        </button>
                      )}
                      {p.actions.includes('new_version') && p.status === 'active' && (
                        <button
                          className="btn small"
                          onClick={() =>
                            setEditing({
                              from_policy_id: p.id,
                              policy_code: p.code,
                              title: p.title,
                              title_ar: p.title_ar,
                              summary: p.summary,
                              summary_ar: p.summary_ar,
                              effective_from: today,
                            })
                          }
                        >
                          {t('rules.act.newVersion')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ page
type Tab = 'rules' | 'policies' | 'approvals';
type Filter = 'current' | 'open' | 'retired';

const BLANK_DEFINITION: Definition = { match: 'all', conditions: [] };

export default function RulesPage() {
  const { t, tx, pick } = useI18n();
  const { can } = useAuth();
  const rules = useApi<Rule[]>('/api/rules');
  const policies = useApi<Policy[]>('/api/rules/policies');
  const catalogue = useApi<Catalogue>('/api/rules/catalogue');
  const [tab, setTab] = useState<Tab>('rules');
  const [filter, setFilter] = useState<Filter>('current');
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const h = window.setTimeout(() => setToast(null), 3500);
    return () => window.clearTimeout(h);
  }, [toast]);

  const all = rules.data ?? [];
  const byCode = useMemo(() => {
    const map = new Map<string, Rule[]>();
    for (const r of all) map.set(r.code, [...(map.get(r.code) ?? []), r]);
    return map;
  }, [all]);

  // One row per rule code: the active version (or latest), plus its open draft/pending version.
  const rows = useMemo(() => {
    const out: { head: Rule; open: Rule | null }[] = [];
    for (const versions of byCode.values()) {
      const sorted = [...versions].sort((a, b) => Number(b.version) - Number(a.version));
      const active = sorted.find((v) => v.status === 'active') ?? null;
      const open = sorted.find((v) => v.status === 'draft' || v.status === 'pending_approval') ?? null;
      const head = active ?? open ?? sorted[0];
      if (filter === 'current' && !active && !open) continue;
      if (filter === 'open' && !open) continue;
      if (filter === 'retired' && (active || open)) continue;
      out.push({ head, open: open && open.id !== head.id ? open : null });
    }
    return out.sort((a, b) => a.head.category.localeCompare(b.head.category) || a.head.code.localeCompare(b.head.code));
  }, [byCode, filter]);

  const current = all.find((r) => r.id === selected) ?? rows[0]?.head ?? null;
  const pendingRules = all.filter((r) => r.status === 'pending_approval');
  const pendingPolicies = (policies.data ?? []).filter((p) => p.status === 'pending_approval');
  const refresh = (message: string) => {
    setToast(message);
    rules.reload();
    policies.reload();
  };

  const loading = !rules.data || !policies.data || !catalogue.data;
  const firstPolicy = (policies.data ?? []).find((p) => p.status === 'active');

  return (
    <>
      <PageHead
        title={t('rules.title')}
        subtitle={t('rules.subtitle')}
        actions={
          can('rules.author') &&
          catalogue.data && (
            <button
              className="btn primary"
              onClick={() =>
                setEditing({
                  rule_code: '',
                  category: catalogue.data!.case_types[0].code,
                  policy_version_id: firstPolicy?.id ?? '',
                  kind: 'breach',
                  name: '',
                  name_ar: '',
                  description: '',
                  description_ar: '',
                  expected_action: '',
                  expected_action_ar: '',
                  observed_action: '',
                  observed_action_ar: '',
                  severity: 'medium',
                  base_confidence: 0.8,
                  conditions: BLANK_DEFINITION,
                })
              }
            >
              + {t('rules.new')}
            </button>
          )
        }
      />
      <PageBrief page="rules" />
      <Toast message={toast} />
      <ErrorBox error={rules.error ?? policies.error ?? catalogue.error} />
      {editing && catalogue.data && policies.data && (
        <RuleEditor
          initial={editing}
          catalogue={catalogue.data}
          policies={policies.data}
          onClose={() => setEditing(null)}
          onSaved={(rule, message) => {
            setEditing(null);
            setSelected(rule.id);
            setFilter('current');
            refresh(message);
          }}
        />
      )}
      <div className="tabs" role="tablist">
        {(['rules', 'policies', 'approvals'] as const).map((id) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {t(`rules.tab.${id}` as MessageKey)}
            {id === 'approvals' && pendingRules.length + pendingPolicies.length > 0 && (
              <span className="tab-count">{pendingRules.length + pendingPolicies.length}</span>
            )}
          </button>
        ))}
      </div>
      {loading ? (
        <Loading />
      ) : tab === 'rules' ? (
        <div className="rules-layout">
          <Card className="rules-list">
            <div className="segmented" role="group" style={{ marginBottom: 10 }}>
              {(['current', 'open', 'retired'] as const).map((f) => (
                <button key={f} className={filter === f ? 'active' : ''} aria-pressed={filter === f} onClick={() => setFilter(f)}>
                  {t(`rules.filter.${f}` as MessageKey)}
                </button>
              ))}
            </div>
            {rows.length === 0 && <Empty />}
            <ul>
              {rows.map(({ head, open }) => (
                <li key={head.code}>
                  <button className={`rule-item${current?.code === head.code ? ' selected' : ''}`} onClick={() => setSelected(head.id)}>
                    <span className="row between" style={{ gap: 6 }}>
                      <strong>{pick(head.name, head.name_ar) || head.code}</strong>
                      <Badge tone={RULE_TONE[head.status]}>{tx('rules.status', head.status)}</Badge>
                    </span>
                    <span className="subtle mono">
                      {head.code} v{head.version}
                    </span>
                    <span className="subtle">
                      {tx('caseType', head.category)} · {tx('rules.kind', head.kind)}
                    </span>
                    {open && (
                      <span className="rule-open">
                        <Icon name="clock" size={12} /> {t('rules.openVersion', { v: open.version, status: tx('rules.status', open.status) })}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div>
            {current ? (
              <RuleDetail
                key={current.id}
                rule={current}
                versions={[...(byCode.get(current.code) ?? [])].sort((a, b) => Number(b.version) - Number(a.version))}
                catalogue={catalogue.data}
                onEdit={() => setEditing(draftFrom(current, 'edit'))}
                onVersion={() => setEditing(draftFrom(current, 'version'))}
                onDone={refresh}
                onSelect={setSelected}
              />
            ) : (
              <Empty />
            )}
          </div>
        </div>
      ) : tab === 'policies' ? (
        <PoliciesTab policies={policies.data!} onChanged={refresh} />
      ) : (
        <Card title={t('rules.queue.title')} subtitle={t('rules.queue.subtitle')}>
          {pendingRules.length + pendingPolicies.length === 0 && <Empty>{t('rules.queue.empty')}</Empty>}
          <ul className="rule-queue">
            {pendingPolicies.map((p) => (
              <li key={p.id}>
                <Badge tone="info">{t('rules.queue.policy')}</Badge>
                <span className="mono">
                  {p.code} v{p.version}
                </span>
                <span>{pick(p.title, p.title_ar)}</span>
                <span className="subtle">{p.submitted_by ? t('rules.pol.submittedBy', { name: pick(p.submitted_by.name, p.submitted_by.name_ar) }) : ''}</span>
                <button className="btn small" onClick={() => setTab('policies')}>
                  {t('rules.queue.review')}
                </button>
              </li>
            ))}
            {pendingRules.map((r) => (
              <li key={r.id}>
                <Badge tone="brand">{t('rules.queue.rule')}</Badge>
                <span className="mono">
                  {r.code} v{r.version}
                </span>
                <span>{pick(r.name, r.name_ar)}</span>
                <span className="subtle">
                  {r.submitted_by ? t('rules.pol.submittedBy', { name: pick(r.submitted_by.name, r.submitted_by.name_ar) }) : ''}
                  {r.four_eyes_blocked ? ` · ${t('rules.queue.yours')}` : ''}
                </span>
                <button
                  className="btn small"
                  onClick={() => {
                    setSelected(r.id);
                    setFilter('open');
                    setTab('rules');
                  }}
                >
                  {t('rules.queue.review')}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
