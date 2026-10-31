import type {ContextUsage} from '../types';

export function ContextMeter({usage, compacting, disabled, onCompact}: {
  usage: ContextUsage | null; compacting: boolean; disabled: boolean; onCompact: () => void;
}) {
  const limit = usage?.limit_tokens || 131000;
  const used = usage?.used_tokens || 0;
  const ratio = Math.min(used / limit, 1);
  const circumference = 2 * Math.PI * 11;
  const canCompact = Boolean(usage?.can_compact) && !disabled && !compacting;
  const formatted = (value: number) => value.toLocaleString('fr-FR');
  const measured = usage?.measured_tokens || 0;
  const counting = !usage ? '' : measured ? (usage.estimated ? `Compté par Qwen, sauf ≈ ${formatted(used - measured)} tokens estimés pour les derniers messages. ` : 'Compté par Qwen. ') : '';
  const description = compacting ? 'Résumé du début en cours…' : usage ? `${usage.estimated ? 'Environ ' : ''}${formatted(used)} tokens sur ${formatted(limit)}. ${canCompact ? 'Cliquer pour résumer le début.' : 'Les messages récents seront conservés.'}` : 'Calcul du contexte…';
  return <div className="context-control">
    <button id="context-meter" type="button" className={`context-meter${compacting ? ' is-loading' : ''}${ratio > .9 ? ' is-near-limit' : ''}`}
      aria-label={`Contexte de la conversation. ${description}`} aria-describedby="context-tooltip" aria-disabled={!canCompact}
      aria-busy={compacting} onClick={() => {if (canCompact) onCompact();}}>
      <svg viewBox="0 0 30 30" aria-hidden="true" className="context-ring">
        <circle className="context-ring-track" cx="15" cy="15" r="11"/>
        <circle className="context-ring-progress" cx="15" cy="15" r="11" strokeDasharray={compacting ? '18 52' : circumference} strokeDashoffset={compacting ? 0 : circumference * (1 - ratio)}/>
      </svg>
    </button>
    <div id="context-tooltip" role="tooltip" className="context-tooltip">
      <strong>Contexte de la conversation</strong>
      <span className="context-usage">{usage?.estimated ? '≈ ' : ''}{usage ? formatted(used) : '…'} <span>/ {formatted(limit)} tokens</span></span>
      {compacting ? <p>Résumé en cours. Les messages d’origine sont conservés.</p> : <>
        <p>{counting}{usage ? `Prochaine réponse : jusqu’à ${formatted(usage.max_output_tokens)} tokens.` : 'Une réserve est gardée pour la réponse.'}</p>
        <p>{usage?.can_compact ? 'Cliquer sur le cercle résume les anciens échanges et garde les plus récents.' : 'Le résumé devient disponible après au moins deux échanges.'}</p>
        <small>Compression automatique avant saturation.</small>
      </>}
    </div>
  </div>;
}
