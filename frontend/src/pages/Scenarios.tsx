import { useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import type { SimulationResult, UnitRef } from '../api/types';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, ErrorBox, Field, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';
import { CASE_TYPES } from './Explorer';

interface Options {
  case_types: string[];
  interventions: { code: string; reduction: [number, number]; driver: string | null }[];
  employee_level_enabled: boolean;
}

export default function ScenariosPage() {
  const { t, tx, pick, fmtPercent, fmtNumber, fmtDate } = useI18n();
  const options = useApi<Options>('/api/simulations/options');
  const units = useApi<(UnitRef & { parent_id: string | null })[]>('/api/admin/org-units');
  const history = useApi<{ id: string; created_at: string; input: { case_type: string } }[]>('/api/simulations');
  const [caseType, setCaseType] = useState('transfers');
  const [chosen, setChosen] = useState<string[]>(['coaching', 'job_aid', 'system_fix']);
  const [unit, setUnit] = useState('');
  const [horizon, setHorizon] = useState(90);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.post<SimulationResult>('/api/simulations', {
          case_type: caseType,
          interventions: chosen.length ? chosen : ['none'],
          org_unit_id: unit || null,
          horizon_days: horizon,
        }),
      );
      history.reload();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (!options.data) return options.loading ? <Loading /> : <ErrorBox error={options.error} />;
  const maxRate = Math.max(...(result?.options.map((o) => o.interval_90[1]) ?? [0.01]), 0.01);

  return (
    <>
      <PageHead title={t('scenarios.title')} subtitle={t('scenarios.subtitle')} />
      <PageBrief page="scenarios" />
      <div className="stack">
        <div className="callout">
          <div>
            <strong>{t('scenarios.illustrative')}</strong>
            <p>{t('scenarios.illustrativeBody')}</p>
          </div>
        </div>
        <div className="grid grid-3">
          <Card tour="scenarios-form">
            <form className="stack" style={{ gap: 12 }} onSubmit={run}>
              <Field label={t('scenarios.caseType')}>
                <select value={caseType} onChange={(e) => setCaseType(e.target.value)}>
                  {(options.data.case_types.length ? options.data.case_types : CASE_TYPES).map((c) => (
                    <option key={c} value={c}>
                      {tx('caseType', c)}
                    </option>
                  ))}
                </select>
              </Field>
              <fieldset className="stack" style={{ gap: 6, border: 0, padding: 0, margin: 0 }}>
                <legend className="field" style={{ marginBottom: 6 }}>
                  {t('scenarios.interventions')}
                </legend>
                {options.data.interventions
                  .filter((i) => i.code !== 'none')
                  .map((i) => (
                    <label key={i.code} className="check">
                      <input
                        type="checkbox"
                        checked={chosen.includes(i.code)}
                        onChange={(e) =>
                          setChosen(e.target.checked ? [...chosen, i.code] : chosen.filter((c) => c !== i.code))
                        }
                      />
                      {tx('intervention', i.code)}
                      <span className="subtle">
                        ({fmtPercent(i.reduction[0])}–{fmtPercent(i.reduction[1])})
                      </span>
                    </label>
                  ))}
              </fieldset>
              <Field label={t('scenarios.scope')}>
                <select value={unit} onChange={(e) => setUnit(e.target.value)}>
                  <option value="">{t('common.all')}</option>
                  {(units.data ?? [])
                    .filter((u) => u.type === 'region' || u.type === 'branch' || u.type === 'department')
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {pick(u.name, u.name_ar)}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label={t('scenarios.horizon')}>
                <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
                  {[30, 90, 180].map((d) => (
                    <option key={d} value={d}>
                      {t('common.days', { n: d })}
                    </option>
                  ))}
                </select>
              </Field>
              <label className="check" title={t('scenarios.employeeLevelDisabled')}>
                <input type="checkbox" disabled checked={false} readOnly />
                {t('scenarios.employeeLevel')}
              </label>
              <span className="subtle">{t('scenarios.employeeLevelDisabled')}</span>
              <ErrorBox error={error} />
              <button className="btn primary" disabled={busy}>
                {t('scenarios.run')}
              </button>
            </form>
          </Card>

          <Card
            className="span-2"
            title={t('scenarios.result')}
            subtitle={
              result
                ? t('scenarios.sample', {
                    cases: fmtNumber(result.sample.cases),
                    findings: fmtNumber(result.sample.confirmed_findings),
                    days: result.lookback_days,
                  })
                : undefined
            }
            actions={<Badge tone="warn">{t('scenarios.illustrative')}</Badge>}
          >
            {!result ? (
              <div className="empty">{t('scenarios.subtitle')}</div>
            ) : (
              <div className="stack">
                {result.warnings.length > 0 && (
                  <div className="row" style={{ gap: 6 }}>
                    {result.warnings.map((w) => (
                      <Badge key={w} tone="warn">
                        {tx('warning', w)}
                      </Badge>
                    ))}
                  </div>
                )}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{t('scenarios.interventions')}</th>
                        <th>{t('scenarios.estimated')}</th>
                        <th>{t('scenarios.interval')}</th>
                        <th className="num">{t('scenarios.per1000')}</th>
                        <th>{t('scenarios.band')}</th>
                        <th className="num">{t('scenarios.addressable')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.options.map((o) => (
                        <tr key={o.intervention}>
                          <td>
                            <strong>{tx('intervention', o.intervention)}</strong>
                          </td>
                          <td style={{ minWidth: 160 }}>
                            <Bar value={o.estimated_rate / maxRate} />
                            <span className="subtle">{fmtPercent(o.estimated_rate, 1)}</span>
                          </td>
                          <td className="mono">
                            {fmtPercent(o.interval_90[0], 1)} – {fmtPercent(o.interval_90[1], 1)}
                          </td>
                          <td className="num">{fmtNumber(o.expected_cases_per_1000, 1)}</td>
                          <td>
                            <Badge tone={o.risk_band === 'elevated' ? 'bad' : o.risk_band === 'moderate' ? 'warn' : 'ok'}>
                              {tx('band', o.risk_band)}
                            </Badge>
                          </td>
                          <td className="num">{fmtPercent(o.addressable_share)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="grid grid-2">
                  <div>
                    <h3>{t('scenarios.factors')}</h3>
                    <div className="stack" style={{ gap: 8, marginTop: 8 }}>
                      {Object.entries(result.contributing_factors).map(([f, share]) => (
                        <div key={f}>
                          <div className="row between">
                            <span>{tx('factor', f)}</span>
                            <span className="subtle">{fmtPercent(share)}</span>
                          </div>
                          <Bar value={share} />
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="stack" style={{ gap: 10 }}>
                    {result.recommended_next_step && (
                      <div className="callout brand">
                        <div>
                          <strong>{t('scenarios.recommended')}</strong>
                          <p>{tx('intervention', result.recommended_next_step.intervention)}</p>
                        </div>
                      </div>
                    )}
                    <div>
                      <h3>{t('scenarios.limitations')}</h3>
                      <ul style={{ margin: '6px 0 0', paddingInlineStart: 18 }} className="muted">
                        {result.limitations.map((l) => (
                          <li key={l}>{tx('limitation', l)}</li>
                        ))}
                      </ul>
                      {result.model && (
                        <p className="subtle">
                          {result.model.name} v{result.model.version} · {tx('model', result.model.status)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </Card>
        </div>
        {history.data && history.data.length > 0 && (
          <Card title={t('scenarios.history')}>
            <div className="row" style={{ gap: 8 }}>
              {history.data.map((h) => (
                <span key={h.id} className="badge">
                  {tx('caseType', h.input.case_type)} · {fmtDate(h.created_at, true)}
                </span>
              ))}
            </div>
          </Card>
        )}
      </div>
    </>
  );
}
