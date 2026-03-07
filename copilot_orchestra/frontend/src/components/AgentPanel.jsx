import { useEffect, useRef, useState } from "react";
import { ElapsedTime } from "./ElapsedTime.jsx";
import { useThemeClasses } from "../ThemeContext.jsx";

const ROLE_STYLE = {
  orchestrator: {
    dark:  { color: "border-indigo-500", badge: "bg-indigo-900/40 text-indigo-300" },
    light: { color: "border-indigo-400", badge: "bg-indigo-100 text-indigo-700" },
  },
  reviewer_1: {
    dark:  { color: "border-red-500",    badge: "bg-red-900/40 text-red-300" },
    light: { color: "border-red-400",    badge: "bg-red-100 text-red-700" },
  },
  reviewer_2: {
    dark:  { color: "border-amber-500",  badge: "bg-amber-900/40 text-amber-300" },
    light: { color: "border-amber-400",  badge: "bg-amber-100 text-amber-700" },
  },
  reviewer_3: {
    dark:  { color: "border-emerald-500", badge: "bg-emerald-900/40 text-emerald-300" },
    light: { color: "border-emerald-400", badge: "bg-emerald-100 text-emerald-700" },
  },
  synthesizer: {
    dark:  { color: "border-violet-500", badge: "bg-violet-900/40 text-violet-300" },
    light: { color: "border-violet-400", badge: "bg-violet-100 text-violet-700" },
  },
};

// All current Claude models have a 200K token context window.
const CONTEXT_WINDOW = 200_000;

/**
 * AgentPanel — displays one agent's streaming output, tool calls, status, and timing.
 */
export function AgentPanel({ role, name, state, timer, reviewStartedAt, metrics }) {
  const { theme, d } = useThemeClasses();
  const bottomRef = useRef(null);

  const isReviewer = role.startsWith("reviewer_");
  const label = name ?? (isReviewer ? role : role.charAt(0).toUpperCase() + role.slice(1));
  const sublabel = isReviewer ? role : null;

  const styleEntry = ROLE_STYLE[role] ?? {
    dark:  { color: "border-gray-500", badge: "bg-gray-900/40 text-gray-300" },
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

  return (
    <div className={`flex flex-col rounded-lg border-t-2 overflow-hidden ${colors.color} ${
      d("bg-gray-900", "bg-white border border-slate-200 shadow-sm")
    }`}>

      {/* Header row 1 — identity + status */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1">
        {/* Left: name badge + sublabel */}
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold shrink-0 ${colors.badge}`}>
            {label}
          </span>
          {sublabel && (
            <span className={`text-[10px] font-mono ${d("text-gray-600", "text-slate-400")}`}>
              {sublabel}
            </span>
          )}
        </div>

        {/* Right: timer + status indicator */}
        <div className="flex items-center gap-2 shrink-0">
          {timer?.startedAt && (
            <span className={`text-[11px] font-mono tabular-nums ${
              timer.doneAt
                ? d("text-gray-500", "text-slate-500")
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
            <span className={`text-[11px] ${d("text-gray-500", "text-slate-400")}`}>Done</span>
          )}
          {state.status === "error" && (
            <span className="text-[11px] text-red-500">Error</span>
          )}
        </div>
      </div>

      {/* Header row 2 — model · tools · wait · copy */}
      <div className={`flex items-center justify-between px-3 pb-2 border-b ${
        d("border-gray-800", "border-slate-100")
      }`}>
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          {state.model && (
            <span className="model-tag">{shortModel(state.model)}</span>
          )}
          {state.toolCalls.length > 0 && (
            <span className={`text-[10px] ${d("text-gray-600", "text-slate-500")}`}>
              {state.toolCalls.length} tool{state.toolCalls.length !== 1 ? "s" : ""}
            </span>
          )}
          {timer?.doneAt && waitSecs !== null && (
            <span className={`text-[10px] ${d("text-gray-600", "text-slate-500")}`}>
              · +{waitSecs}s wait
            </span>
          )}
        </div>
        {state.streamText && <CopyButton text={state.streamText} />}
      </div>

      {/* Tool call badges */}
      {state.toolCalls.length > 0 && (
        <div className={`flex flex-wrap gap-1 px-3 py-1.5 border-b ${
          d("border-gray-800/40", "border-slate-100")
        }`}>
          {state.toolCalls.slice(-6).map((tc, i) => (
            <ToolBadge key={i} call={tc} />
          ))}
        </div>
      )}

      {/* Usage metrics row */}
      {metrics && (metrics.input_tokens > 0 || metrics.output_tokens > 0) && (
        <AgentUsageRow metrics={metrics} />
      )}

      {/* Stream content */}
      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        {!state.streamText && state.status === "idle" && (
          <p className={`text-xs italic ${d("text-gray-600", "text-slate-400")}`}>
            Waiting to start...
          </p>
        )}

        {state.streamText && (
          <pre className={`stream-text ${state.streaming ? "cursor-blink" : ""} ${
            d("text-gray-300", "text-slate-800")
          }`}>
            {state.streamText}
          </pre>
        )}

        {state.status === "error" && state.error && (
          <p className="text-red-500 text-xs mt-2">⚠ {state.error}</p>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function AgentUsageRow({ metrics }) {
  const { d } = useThemeClasses();
  const inputTokens = metrics.input_tokens || 0;
  const outputTokens = metrics.output_tokens || 0;
  const ctxPct = Math.min(100, (inputTokens / CONTEXT_WINDOW) * 100);
  const ctxColor =
    ctxPct > 80 ? "bg-red-500" : ctxPct > 50 ? "bg-amber-500" : "bg-sky-500";

  return (
    <div className={`flex items-center gap-3 px-3 py-1.5 border-b text-[10px] font-mono ${
      d("border-gray-800/40 bg-gray-950/40 text-gray-500", "border-slate-100 bg-slate-50/60 text-slate-400")
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
        <span className={d("text-gray-400", "text-slate-500")}>{ctxPct.toFixed(1)}%</span>
      </div>

      <span className={d("text-gray-700", "text-slate-300")}>|</span>

      {/* Token counts */}
      <span>
        IN <span className={d("text-sky-400", "text-sky-600")}>{fmtTokens(inputTokens)}</span>
      </span>
      <span>
        OUT <span className={d("text-violet-400", "text-violet-600")}>{fmtTokens(outputTokens)}</span>
      </span>

      {metrics.cost > 0 && (
        <>
          <span className={d("text-gray-700", "text-slate-300")}>|</span>
          <span className={d("text-emerald-400", "text-emerald-600")}>${metrics.cost.toFixed(4)}</span>
        </>
      )}
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
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
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
      className={`text-[10px] transition-colors px-1.5 py-0.5 rounded border shrink-0 ${
        d(
          "text-gray-500 hover:text-gray-200 border-gray-700 hover:border-gray-500",
          "text-slate-500 hover:text-slate-800 border-slate-200 hover:border-slate-400"
        )
      }`}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
