import { useThemeClasses } from "../ThemeContext.jsx";

/**
 * ModelRouterPanel — preset selector and per-role model overrides.
 */
export function ModelRouterPanel({ config, onChange, models, disabled, reviewerNames = [] }) {
  const roleLabels = {
    orchestrator: "Orchestrator",
    reviewer_1: reviewerNames[0] ?? "Reviewer 1",
    reviewer_2: reviewerNames[1] ?? "Reviewer 2",
    reviewer_3: reviewerNames[2] ?? "Reviewer 3",
    synthesizer: "Synthesizer",
  };
  const { d } = useThemeClasses();

  const presets = [
    {
      value: "balanced",
      label: "Balanced",
      desc: "Sensible defaults per role",
      detail: "Orchestrator & synthesizer on Sonnet, reviewers on Haiku. Good quality at reasonable cost — the right starting point for most codebases.",
    },
    {
      value: "economy",
      label: "Economy",
      desc: "Haiku for all roles",
      detail: "All five agents use Haiku — the fastest, lowest-cost model. Best for quick scans, large repos where token cost matters, or iterating on prompts.",
    },
    {
      value: "performance",
      label: "Performance",
      desc: "Opus for all roles",
      detail: "All five agents use Opus — the most capable model. Best for critical security reviews, complex architecture analysis, or when depth matters more than speed.",
    },
    {
      value: "free",
      label: "Free",
      desc: "0x models only",
      detail: "Uses only dynamically discovered 0x models from the SDK model catalog (for example GPT-4.1 when available). No model IDs are hardcoded.",
    },
    {
      value: "auto",
      label: "Auto",
      desc: "Orchestrator selects at runtime",
      detail: "The orchestrator reads the codebase first, then picks the right model for each reviewer based on the complexity it finds. Showcases the SDK's programmatic model routing capability.",
    },
  ];

  const roles = ["orchestrator", "reviewer_1", "reviewer_2", "reviewer_3", "synthesizer"];

  function handlePreset(preset) {
    onChange({ ...config, preset, overrides: {} });
  }

  function handleOverride(role, model) {
    onChange({
      ...config,
      overrides: { ...config.overrides, [role]: model || undefined },
    });
  }

  return (
    <div className={`rounded-lg border p-4 space-y-4 ${d("bg-gray-900 border-gray-800", "bg-white border-slate-200 shadow-sm")
      }`}>
      <h3 className={`text-xs font-semibold uppercase tracking-wider ${d("text-gray-400", "text-slate-500")}`}>
        Model Router
      </h3>

      {/* Preset selector */}
      <div className="grid grid-cols-2 gap-1.5">
        {presets.map((p) => (
          <button
            key={p.value}
            onClick={() => handlePreset(p.value)}
            disabled={disabled}
            title={p.desc}
            className={`px-2 py-1.5 rounded text-xs font-medium transition-colors
              disabled:opacity-50 disabled:cursor-not-allowed ${config.preset === p.value
                ? "bg-indigo-600 text-white"
                : d(
                  "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200",
                  "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-800"
                )
              }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Active preset description */}
      {(() => {
        const active = presets.find((p) => p.value === config.preset);
        return active ? (
          <p className={`text-[10px] leading-relaxed ${d("text-gray-400", "text-slate-500")}`}>
            {active.detail}
          </p>
        ) : null;
      })()}

      {/* Per-role overrides */}
      <div className="space-y-2">
        <p className={`text-[10px] uppercase tracking-wider ${d("text-gray-600", "text-slate-400")}`}>
          Per-role overrides (take highest priority)
        </p>
        {roles.map((role) => (
          <div key={role} className="flex items-center gap-2 overflow-hidden">
            <span className={`text-[10px] w-20 shrink-0 ${d("text-gray-500", "text-slate-500")}`}>
              {roleLabels[role] ?? role}
            </span>
            <select
              value={config.overrides?.[role] || ""}
              onChange={(e) => handleOverride(role, e.target.value)}
              disabled={disabled || models.length === 0}
              className={`flex-1 min-w-0 text-xs rounded px-2 py-1
                focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed ${d(
                "bg-gray-800 border border-gray-700 text-gray-300 focus:border-indigo-500",
                "bg-white border border-slate-200 text-slate-700 focus:border-indigo-400 shadow-sm"
              )
                }`}
            >
              <option value="">{models.length === 0 ? "— backend offline —" : "— preset default —"}</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name || m.id}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      {config.preset === "auto" && (
        <p className={`text-[10px] italic ${d("text-amber-600/80", "text-amber-600")}`}>
          Auto: orchestrator will select optimal models at runtime. User overrides above still apply.
        </p>
      )}
    </div>
  );
}
