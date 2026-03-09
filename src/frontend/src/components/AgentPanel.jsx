import { useEffect, useRef, useState } from "react";
import { useThemeClasses } from "../ThemeContext.jsx";
import { ElapsedTime } from "./ElapsedTime.jsx";

const ROLE_STYLE = {
  orchestrator: {
    dark: { color: "border-indigo-500", badge: "bg-indigo-900/40 text-indigo-300" },
    light: { color: "border-indigo-400", badge: "bg-indigo-100 text-indigo-700" },
  },
  reviewer_1: {
    dark: { color: "border-red-500", badge: "bg-red-900/40 text-red-300" },
    light: { color: "border-red-400", badge: "bg-red-100 text-red-700" },
  },
  reviewer_2: {
    dark: { color: "border-amber-500", badge: "bg-amber-900/40 text-amber-300" },
    light: { color: "border-amber-400", badge: "bg-amber-100 text-amber-700" },
  },
  reviewer_3: {
    dark: { color: "border-emerald-500", badge: "bg-emerald-900/40 text-emerald-300" },
    light: { color: "border-emerald-400", badge: "bg-emerald-100 text-emerald-700" },
  },
  synthesizer: {
    dark: { color: "border-violet-500", badge: "bg-violet-900/40 text-violet-300" },
    light: { color: "border-violet-400", badge: "bg-violet-100 text-violet-700" },
  },
};

const DEFAULT_CONTEXT_WINDOW = 200_000;

/**
 * ExpandButton — maximize / collapse toggle for agent panels.
 */
export function ExpandButton({ isExpanded, onToggle }) {
  const { d } = useThemeClasses();
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onToggle(); }}
      title={isExpanded ? "Collapse" : "Maximize"}
      className={`transition-colors p-1 rounded border shrink-0 ${d(
        "text-gray-500 hover:text-gray-200 border-gray-700 hover:border-gray-500",
        "text-slate-500 hover:text-slate-800 border-slate-200 hover:border-slate-400"
      )}`}
    >
      {isExpanded ? (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <line x1="2" y1="2" x2="8" y2="8" />
          <line x1="8" y1="2" x2="2" y2="8" />
        </svg>
      ) : (
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6,1 9,1 9,4" />
          <polyline points="4,9 1,9 1,6" />
          <line x1="9" y1="1" x2="5.5" y2="4.5" />
          <line x1="1" y1="9" x2="4.5" y2="5.5" />
        </svg>
      )}
    </button>
  );
}

/**
 * AgentPanel — displays one agent's streaming output, tool calls, status, and timing.
 */
export function AgentPanel({ role, name, state, timer, reviewStartedAt, metrics, isExpanded, onExpand, onCollapse, className, compactWhenDone }) {
  const { theme, d } = useThemeClasses();
  const bottomRef = useRef(null);
  const panelRef = useRef(null);

  const isReviewer = role.startsWith("reviewer_");
  const label = name ?? (isReviewer ? role : role.charAt(0).toUpperCase() + role.slice(1));
  const sublabel = isReviewer ? role : null;

  const styleEntry = ROLE_STYLE[role] ?? {
    dark: { color: "border-gray-500", badge: "bg-gray-900/40 text-gray-300" },
    light: { color: "border-gray-400", badge: "bg-gray-100 text-gray-600" },
  };
  const colors = styleEntry[theme] ?? styleEntry.dark;

  const waitSecs = timer?.startedAt && reviewStartedAt
    ? ((timer.startedAt - reviewStartedAt) / 1000).toFixed(1)
    : null;

  useEffect(() => {
    if (state.streaming) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [state.streamText, state.streaming]);

  // Close on click outside when expanded
  useEffect(() => {
    if (!isExpanded) return;
    function handleClick(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        onCollapse?.();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [isExpanded, onCollapse]);

  const panel = (
    <div ref={panelRef} className={`flex flex-col rounded-lg border-t-2 overflow-hidden ${colors.color} ${d("bg-gray-900", "bg-white border border-slate-200 shadow-sm")
      } ${isExpanded ? "max-h-[80vh]" : "min-h-[140px]"} ${className ?? ""}`}>

      {/* Header row 1 — identity + status */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
        {/* Left: name badge + sublabel */}
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold shrink-0 ${colors.badge}`}>
            {label}
          </span>
          {sublabel && (
            <span className={`text-[10px] font-mono ${d("text-gray-300", "text-slate-600")}`}>
              {sublabel}
            </span>
          )}
        </div>

        {/* Right: timer + status indicator */}
        <div className="flex items-center gap-2 shrink-0">
          {timer?.startedAt && (
            <span className={`text-[11px] font-mono tabular-nums ${timer.doneAt
              ? d("text-gray-300", "text-slate-600")
              : "text-emerald-500 font-semibold"
              }`}>
              ⏱ <ElapsedTime startedAt={timer.startedAt} doneAt={timer.doneAt} />
            </span>
          )}
          {state.status === "running" && (
            <span className="flex items-center gap-1 text-[11px] text-emerald-500">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Working
            </span>
          )}
          {state.status === "done" && (
            <span className={`text-[11px] ${d("text-gray-300", "text-slate-600")}`}>Done</span>
          )}
          {state.status === "error" && (
            <span className="text-[11px] text-red-500">Error</span>
          )}
        </div>
      </div>

      {/* Header row 2 — model · tools · wait · actions */}
      <div className={`flex items-center justify-between px-3 pb-2 border-b ${d("border-gray-800", "border-slate-100")
        }`}>
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          {state.model && (
            <span className="model-tag">{shortModel(state.model)}</span>
          )}
          {state.toolCalls.length > 0 && (
            <span className={`text-[10px] ${d("text-gray-300", "text-slate-600")}`}>
              {state.toolCalls.length} tool{state.toolCalls.length !== 1 ? "s" : ""}
            </span>
          )}
          {timer?.doneAt && waitSecs !== null && (
            <span className={`text-[10px] ${d("text-gray-300", "text-slate-600")}`}>
              · +{waitSecs}s wait
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {state.streamText && <CopyButton text={state.streamText} />}
          <ExpandButton isExpanded={isExpanded} onToggle={() => isExpanded ? onCollapse?.() : onExpand?.()} />
        </div>
      </div>

      {/* Tool call badges */}
      {state.toolCalls.length > 0 && (
        <div className={`flex flex-wrap gap-1 px-3 py-1.5 border-b ${d("border-gray-800/40", "border-slate-100")
          }`}>
          {state.toolCalls.slice(-6).map((tc, i) => (
            <ToolBadge key={i} call={tc} />
          ))}
        </div>
      )}

      {/* Usage metrics row */}
      {metrics && (
        <AgentUsageRow metrics={metrics} />
      )}

      {/* Stream content */}
      <div className="flex-1 overflow-y-auto p-3 min-h-[80px]">
        {!state.streamText && state.status === "idle" && (
          <p className={`text-xs italic ${d("text-gray-300", "text-slate-600")}`}>
            Waiting to start...
          </p>
        )}

        {state.streamText && (
          <pre className={`stream-text ${state.streaming ? "cursor-blink" : ""} ${d("text-gray-300", "text-slate-800")
            }`}>
            {state.streamText}
          </pre>
        )}

        {state.plan && <ReviewPlanView plan={state.plan} />}

        {state.status === "error" && state.error && (
          <p className="text-red-500 text-xs mt-2">⚠ {state.error}</p>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );

  if (isExpanded) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/50 backdrop-blur-sm">
        <div className="w-full max-w-4xl h-[80vh]">
          {panel}
        </div>
      </div>
    );
  }

  // Compact summary bar — shown when the agent is done and compactWhenDone is set.
  // Keeps the orchestrator from dominating the layout after its planning phase ends.
  if (compactWhenDone && state.status === "done") {
    const planSummary = state.plan
      ? (() => {
          const fileCount = state.plan.reviewer_1.files.length;
          const focus = state.plan.reviewer_1.focus;
          return `${fileCount} file${fileCount !== 1 ? "s" : ""} · ${focus}`;
        })()
      : (state.streamText?.split("\n").find((l) => l.trim()) ?? "");
    return (
      <div
        className={`flex items-center justify-between rounded-lg border-t-2 px-3 py-2 gap-3 cursor-pointer ${colors.color} ${d("bg-gray-900 hover:bg-gray-800/60", "bg-white hover:bg-slate-50 border border-slate-200 shadow-sm")}`}
        onClick={() => onExpand?.()}
        title="Click to expand plan"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold shrink-0 ${colors.badge}`}>
            {label}
          </span>
          {state.model && (
            <span className="model-tag shrink-0">{shortModel(state.model)}</span>
          )}
          {state.toolCalls.length > 0 && (
            <span className={`text-[10px] shrink-0 ${d("text-gray-400", "text-slate-500")}`}>
              {state.toolCalls.length} tools
            </span>
          )}
          {timer?.startedAt && waitSecs !== null && (
            <span className={`text-[10px] shrink-0 ${d("text-gray-400", "text-slate-500")}`}>
              · +{waitSecs}s wait
            </span>
          )}
          {planSummary && (
            <span className={`text-[10px] truncate ${state.plan ? d("text-indigo-400", "text-indigo-600") : d("text-gray-400", "text-slate-500")}`}>
              · {planSummary.slice(0, 120)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {timer?.startedAt && (
            <span className={`text-[11px] font-mono tabular-nums ${d("text-gray-300", "text-slate-500")}`}>
              ⏱ <ElapsedTime startedAt={timer.startedAt} doneAt={timer.doneAt} />
            </span>
          )}
          <span className={`text-[11px] ${d("text-gray-300", "text-slate-600")}`}>Done</span>
          <ExpandButton isExpanded={false} onToggle={() => onExpand?.()} />
        </div>
      </div>
    );
  }

  return panel;
}

function AgentUsageRow({ metrics }) {
  const { d } = useThemeClasses();
  const inputTokens = metrics.input_tokens || 0;
  const outputTokens = metrics.output_tokens || 0;
  const contextWindow = metrics.context_window_tokens || DEFAULT_CONTEXT_WINDOW;
  const ctxPct = Math.min(100, (inputTokens / contextWindow) * 100);
  const ctxColor =
    ctxPct > 80 ? "bg-red-500" : ctxPct > 50 ? "bg-amber-500" : "bg-sky-500";

  return (
    <div className={`flex items-center gap-3 px-3 py-1.5 border-b text-[10px] font-mono ${d("border-gray-800/40 bg-gray-950/40 text-gray-500", "border-slate-100 bg-slate-50/60 text-slate-400")
      }`}>
      {/* Context window bar */}
      <div className="flex items-center gap-1.5">
        <span>CTX</span>
        <div className={`w-14 h-1 rounded-full overflow-hidden ${d("bg-gray-700", "bg-slate-200")}`}>
          <div
            className={`h-full rounded-full transition-all duration-500 ${ctxColor}`}
            style={{ width: `${ctxPct}%` }}
          />
        </div>
        <span className={d("text-gray-200", "text-slate-600")}>{ctxPct.toFixed(1)}%</span>
        <span className={d("text-gray-300", "text-slate-500")}>of {fmtWindow(contextWindow)}</span>
      </div>

      <span className={d("text-gray-500", "text-slate-300")}>|</span>

      {/* Token counts */}
      <span>
        IN <span className={d("text-sky-400", "text-sky-600")}>{fmtTokens(inputTokens)}</span>
      </span>
      <span>
        OUT <span className={d("text-violet-400", "text-violet-600")}>{fmtTokens(outputTokens)}</span>
      </span>
    </div>
  );
}

function ToolBadge({ call }) {
  const icons = {
    read_file: "📄",
    list_directory: "📁",
    grep_codebase: "🔍",
    git_diff: "🔀",
    git_diff_file: "🔀",
    submit_plan: "📋",
  };
  const icon = icons[call.tool_name] || "🔧";
  const path = call.args?.path
    ? call.args.path.split("/").slice(-2).join("/")
    : call.tool_name;

  return (
    <span className="tool-badge" title={JSON.stringify(call.args, null, 2)}>
      <span>{icon}</span>
      <span className="truncate max-w-[120px]">{path}</span>
    </span>
  );
}

function shortModel(model) {
  return model.replace("claude-", "").replace(/-(\d+)-(\d+)/, "-$1.$2");
}

function fmtTokens(n) {
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}m`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtWindow(n) {
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

const REVIEWER_COLORS = {
  reviewer_1: {
    dark: "text-red-400 border-red-800 bg-red-950/30",
    light: "text-red-700 border-red-200 bg-red-50",
  },
  reviewer_2: {
    dark: "text-amber-400 border-amber-800 bg-amber-950/30",
    light: "text-amber-700 border-amber-200 bg-amber-50",
  },
  reviewer_3: {
    dark: "text-emerald-400 border-emerald-800 bg-emerald-950/30",
    light: "text-emerald-700 border-emerald-200 bg-emerald-50",
  },
};

function ReviewPlanView({ plan }) {
  const { theme, d } = useThemeClasses();
  const reviewers = ["reviewer_1", "reviewer_2", "reviewer_3"];

  return (
    <div className={`mt-3 rounded border ${d("border-gray-700/60 bg-gray-800/40", "border-slate-200 bg-slate-50")}`}>
      <div className={`flex items-center gap-1.5 px-3 py-1.5 border-b text-[10px] font-semibold uppercase tracking-wide ${d("border-gray-700/60 text-gray-500", "border-slate-200 text-slate-400")}`}>
        <span>📋</span>
        <span>Review Plan</span>
      </div>
      <div className="divide-y divide-gray-700/40 dark:divide-gray-700/40">
        {reviewers.map((r) => {
          const rPlan = plan[r];
          if (!rPlan) return null;
          const colors = REVIEWER_COLORS[r]?.[theme] ?? REVIEWER_COLORS[r]?.dark;
          return (
            <div key={r} className="px-3 py-2 flex flex-col gap-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${colors}`}>
                  {r}
                </span>
                <span className={`text-[10px] font-mono ${d("text-gray-400", "text-slate-500")}`}>
                  {rPlan.files.length} file{rPlan.files.length !== 1 ? "s" : ""}
                </span>
                <span className={`text-[10px] truncate ${d("text-gray-300", "text-slate-700")}`} title={rPlan.focus}>
                  {rPlan.focus}
                </span>
              </div>
              {rPlan.files.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-0.5">
                  {rPlan.files.map((f, i) => (
                    <span key={i} className={`text-[9px] font-mono px-1 py-0.5 rounded ${d("bg-gray-700/60 text-gray-400", "bg-slate-200 text-slate-600")}`}>
                      {f.split("/").slice(-2).join("/")}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {plan.rationale && (
        <div className={`px-3 py-2 border-t text-[10px] italic ${d("border-gray-700/60 text-gray-500", "border-slate-200 text-slate-400")}`}>
          {plan.rationale}
        </div>
      )}
    </div>
  );
}

export function CopyButton({ text }) {
  const { d } = useThemeClasses();
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <button
      onClick={handleCopy}
      title="Copy to clipboard"
      className={`text-[10px] transition-colors px-1.5 py-0.5 rounded border shrink-0 ${d(
        "text-gray-500 hover:text-gray-200 border-gray-700 hover:border-gray-500",
        "text-slate-500 hover:text-slate-800 border-slate-200 hover:border-slate-400"
      )
        }`}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
