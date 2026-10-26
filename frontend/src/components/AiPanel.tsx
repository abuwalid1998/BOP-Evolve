import { useState, type ReactNode } from 'react';
import { api, ApiError } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';
import { Icon } from './Icon';

export interface AiStatus {
  available: boolean;
  enabled: boolean;
  configured: boolean;
  model: string;
  provider: string;
  features: Record<string, boolean>;
}

export interface AiMeta {
  id: string;
  model: string;
  provider: string;
  generated_at: string;
  cached: boolean;
  latency_ms: number | null;
  language: string;
}

export interface AiResult<T = Record<string, unknown>> {
  output: T;
  meta: AiMeta;
}

export type AiFeature = 'policy_writing' | 'case_assistant' | 'employee_summary' | 'workplace_insights' | 'onboarding';

/** Map an assistant error to a sentence the person can act on. */
export function aiErrorText(t: (k: MessageKey) => string, err: unknown): string {
  const code = err instanceof ApiError ? (err.detail as { code?: string } | undefined)?.code : undefined;
  const known = ['not_configured', 'disabled', 'feature_disabled', 'invalid_key', 'rate_limited', 'timeout', 'invalid_output', 'provider_error'];
  if (code && known.includes(code)) return t(`ai.error.${code}` as MessageKey);
  if (err instanceof ApiError && err.status === 0) return t('auth.serverUnreachable');
  return t('ai.error.provider_error');
}

export function useAiStatus() {
  return useApi<AiStatus>('/api/ai/status');
}

export function AiMetaLine({ meta }: { meta: AiMeta }) {
  const { t, fmtDate } = useI18n();
  return (
    <p className="ai-meta subtle">
      <Icon name="spark" size={13} />
      {t('ai.meta', { model: meta.model, provider: meta.provider, time: fmtDate(meta.generated_at, true) })}
      {meta.cached && ` · ${t('ai.cached')}`}
    </p>
  );
}

/** Generic rendering of an assistant answer: strings as paragraphs, arrays as lists. */
export function AiOutput({ output, keys }: { output: Record<string, unknown>; keys: string[] }) {
  const { t, tx } = useI18n();
  return (
    <div className="ai-output">
      {keys
        .filter((k) => output[k] !== undefined && output[k] !== null && output[k] !== '')
        .map((k) => {
          const value = output[k];
          const label = t(`ai.key.${k}` as MessageKey);
          if (Array.isArray(value)) {
            return (
              <div key={k}>
                <h4>{label}</h4>
                <ul>
                  {value.map((item, i) => (
                    <li key={i}>
                      {typeof item === 'string'
                        ? item
                        : Object.entries(item as Record<string, string>)
                            .map(([ik, iv]) => (ik === 'action' ? iv : `${t(`ai.key.${ik}` as MessageKey)}: ${iv}`))
                            .join(' · ')}
                    </li>
                  ))}
                </ul>
              </div>
            );
          }
          if (k === 'likely_root_cause') {
            return (
              <div key={k}>
                <h4>{label}</h4>
                <p>
                  <strong>{tx('factor', String(value))}</strong>
                  {output.root_cause_reason ? ` — ${String(output.root_cause_reason)}` : ''}
                </p>
              </div>
            );
          }
          return (
            <div key={k}>
              <h4>{label}</h4>
              <p className={k === 'caution' ? 'subtle' : undefined}>{String(value)}</p>
            </div>
          );
        })}
    </div>
  );
}

/**
 * A card section that asks the generative assistant for a draft or an explanation.
 * Nothing is generated until the person asks; the answer is always marked as a draft.
 */
export function AiPanel<T extends Record<string, unknown>>({
  feature,
  title,
  intro,
  endpoint,
  body,
  keys,
  render,
  actionLabel,
  tour,
  compact = false,
  disabled = false,
}: {
  feature: AiFeature;
  title: string;
  intro?: string;
  endpoint: string;
  body?: Record<string, unknown>;
  keys?: string[];
  render?: (result: AiResult<T>) => ReactNode;
  actionLabel?: string;
  tour?: string;
  compact?: boolean;
  /** The caller's inputs are not ready yet (for example notes too short). */
  disabled?: boolean;
}) {
  const { t, lang } = useI18n();
  const status = useAiStatus();
  const [result, setResult] = useState<AiResult<T> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const s = status.data;
  const unavailable = s && (!s.available || !s.features[feature]);

  const run = async (refresh: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<AiResult<T>>(endpoint, { ...(body ?? {}), language: lang, refresh }));
    } catch (err) {
      setError(aiErrorText(t, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`ai-panel${compact ? ' compact' : ''}`} data-tour={tour} aria-busy={busy}>
      <div className="ai-panel-head">
        <span className="ai-chip">
          <Icon name="spark" size={14} />
          {t('ai.chip')}
        </span>
        <h3>{title}</h3>
        <div className="spacer" />
        {result ? (
          <button className="btn small" disabled={busy} onClick={() => run(true)}>
            {busy ? t('ai.working') : t('ai.regenerate')}
          </button>
        ) : (
          <button className="btn small primary" disabled={busy || !!unavailable || !s || disabled} onClick={() => run(false)}>
            <Icon name="spark" size={14} />
            {busy ? t('ai.working') : (actionLabel ?? t('ai.generate'))}
          </button>
        )}
      </div>
      {intro && !result && <p className="subtle">{intro}</p>}
      {unavailable && !result && (
        <p className="subtle">
          {!s!.configured ? t('ai.error.not_configured') : !s!.enabled ? t('ai.error.disabled') : t('ai.error.feature_disabled')}
        </p>
      )}
      {busy && !result && <div className="ai-thinking" role="status">{t('ai.thinking')}</div>}
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      {result && (
        <>
          {render ? render(result) : <AiOutput output={result.output} keys={keys ?? Object.keys(result.output)} />}
          <AiMetaLine meta={result.meta} />
          <p className="ai-disclaimer">{t('ai.disclaimer')}</p>
        </>
      )}
    </section>
  );
}
