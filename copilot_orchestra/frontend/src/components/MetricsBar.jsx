import { useThemeClasses } from "../ThemeContext.jsx";

/**
 * MetricsBar — real-time token/context/quota display.
 *
 * Aggregates metrics from all agents and shows totals.
 */
export function MetricsBar({ metrics, reviewStatus }) {
  const { d } = useThemeClasses();

  const totals = Object.values(metrics).reduce(
    (acc, m) => ({
      input: acc.input + (m.input_tokens || 0),
      output: acc.output + (m.output_tokens || 0),
      cost: acc.cost + (m.cost || 0),
    }),
    { input: 0, output: 0, cost: 0 }
  );

  // Get quota from any agent that has it
  const quota = Object.values(metrics).find((m) => m.quota?.entitlement_requests)?.quota;

  const totalTokens = totals.input + totals.output;

  return (
    <div className={`flex flex-wrap items-center gap-x-6 gap-y-1.5 px-4 py-2 border-b text-xs font-mono ${
      d("bg-gray-900 border-gray-800", "bg-white border-slate-200")
    }`}>
      {/* Status indicator */}
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${
            reviewStatus === "running"
              ? "bg-emerald-500 animate-pulse"
              : reviewStatus === "complete"
              ? "bg-blue-500"
              : reviewStatus === "error"
              ? "bg-red-500"
              : d("bg-gray-600", "bg-slate-300")
          }`}
        />
        <span className={`uppercase tracking-wider text-[10px] ${d("text-gray-400", "text-slate-500")}`}>
          {reviewStatus || "idle"}
        </span>
      </div>

      <div className={`h-4 w-px ${d("bg-gray-700", "bg-slate-200")}`} />

      {/* Token counts */}
      <MetricItem label="IN"    value={fmtTokens(totals.input)}   color={d("text-sky-400",    "text-sky-600")} />
      <MetricItem label="OUT"   value={fmtTokens(totals.output)}  color={d("text-violet-400", "text-violet-600")} />
      <MetricItem label="TOTAL" value={fmtTokens(totalTokens)}    color={d("text-gray-300",   "text-gray-700")} />

      {totals.cost > 0 && (
        <>
          <div className={`h-4 w-px ${d("bg-gray-700", "bg-slate-200")}`} />
          <MetricItem
            label="EST. COST"
            value={`$${totals.cost.toFixed(4)}`}
            color={d("text-emerald-400", "text-emerald-600")}
          />
        </>
      )}

      {quota && (
        <>
          <div className={`h-4 w-px ${d("bg-gray-700", "bg-slate-200")}`} />
          {/* Quota bar */}
          <div className="flex items-center gap-2">
            <span className={d("text-gray-500", "text-slate-400")}>QUOTA</span>
            <div className={`w-24 h-1.5 rounded-full overflow-hidden ${d("bg-gray-700", "bg-slate-200")}`}>
              <div
                className={`h-full rounded-full transition-all ${
                  quota.remaining_percentage > 50
                    ? "bg-emerald-500"
                    : quota.remaining_percentage > 20
                    ? "bg-amber-500"
                    : "bg-red-500"
                }`}
                style={{ width: `${Math.max(0, quota.remaining_percentage)}%` }}
              />
            </div>
            <span className={d("text-gray-400", "text-slate-600")}>
              {quota.remaining_percentage?.toFixed(0)}%
            </span>
            {quota.is_unlimited && (
              <span className="text-emerald-500">∞</span>
            )}
          </div>
        </>
      )}

      {/* Per-agent breakdown */}
      {Object.keys(metrics).length > 0 && (
        <>
          <div className={`h-4 w-px ${d("bg-gray-700", "bg-slate-200")}`} />
          <div className="flex items-center gap-3">
            {Object.entries(metrics).map(([agent, m]) => (
              <AgentMetric key={agent} agent={agent} tokens={(m.input_tokens || 0) + (m.output_tokens || 0)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function MetricItem({ label, value, color }) {
  const { d } = useThemeClasses();
  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-[10px] uppercase tracking-wider ${d("text-gray-500", "text-slate-400")}`}>{label}</span>
      <span className={`font-mono ${color}`}>{value}</span>
    </div>
  );
}

// Reviewer name map used in metrics bar labels
const REVIEWER_SHORT = {
  reviewer_1: "Otani",
  reviewer_2: "Ichiro",
  reviewer_3: "Matsui",
  synthesizer: "Synth",
  orchestrator: "Orch",
};

function AgentMetric({ agent, tokens }) {
  const { d } = useThemeClasses();
  const colors = {
    reviewer_1:   d("text-red-400",    "text-red-600"),
    reviewer_2:   d("text-amber-400",  "text-amber-600"),
    reviewer_3:   d("text-emerald-400","text-emerald-600"),
    synthesizer:  d("text-violet-400", "text-violet-600"),
    orchestrator: d("text-indigo-400", "text-indigo-600"),
  };
  const label = REVIEWER_SHORT[agent] ?? agent[0].toUpperCase();
  return (
    <span className={`${colors[agent] || d("text-gray-400", "text-slate-500")} text-[10px]`}>
      {label}: {fmtTokens(tokens)}
    </span>
  );
}

function fmtTokens(n) {
  if (n === 0) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
