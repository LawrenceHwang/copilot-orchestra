import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { CopyButton } from "./AgentPanel.jsx";
import { ElapsedTime } from "./ElapsedTime.jsx";
import { useThemeClasses } from "../ThemeContext.jsx";

const CONTEXT_WINDOW = 200_000;

function fmtTokens(n) {
  if (n === 0) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/**
 * SynthesisPanel — displays the synthesizer's streaming output and final report.
 */
function SynthesisUsageRow({ metrics, d }) {
  const inputTokens = metrics.input_tokens || 0;
  const outputTokens = metrics.output_tokens || 0;
  const ctxPct = Math.min(100, (inputTokens / CONTEXT_WINDOW) * 100);
  const ctxColor =
    ctxPct > 80 ? "bg-red-500" : ctxPct > 50 ? "bg-amber-500" : "bg-violet-500";

  return (
    <div className={`flex items-center gap-3 px-4 py-1.5 border-b text-[10px] font-mono ${
      d("border-gray-800 bg-gray-950/40 text-gray-500", "border-slate-100 bg-slate-50/60 text-slate-400")
    }`}>
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
      <span>IN <span className={d("text-sky-400", "text-sky-600")}>{fmtTokens(inputTokens)}</span></span>
      <span>OUT <span className={d("text-violet-400", "text-violet-600")}>{fmtTokens(outputTokens)}</span></span>
      {metrics.cost > 0 && (
        <>
          <span className={d("text-gray-700", "text-slate-300")}>|</span>
          <span className={d("text-emerald-400", "text-emerald-600")}>${metrics.cost.toFixed(4)}</span>
        </>
      )}
    </div>
  );
}

export function SynthesisPanel({ state, timer, metrics }) {
  const { d } = useThemeClasses();
  const bottomRef = useRef(null);

  useEffect(() => {
    if (state.streaming) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [state.streamText, state.streaming]);

  if (state.status === "idle" && !state.streamText) {
    return (
      <div className={`rounded-lg border-t-2 border-violet-400 min-h-[350px] flex items-center justify-center text-sm italic ${
        d("bg-gray-900 text-gray-600", "bg-white text-slate-400 border border-slate-100")
      }`}>
        Synthesis will appear here once all specialist agents have completed.
      </div>
    );
  }

  return (
    <div className={`flex flex-col rounded-lg border-t-2 border-violet-400 overflow-hidden min-h-[350px] ${
      d("bg-gray-900", "bg-white border border-slate-100")
    }`}>
      {/* Header */}
      <div className={`flex-shrink-0 flex items-center justify-between px-4 py-2 border-b ${
        d("border-gray-800", "border-slate-100")
      }`}>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
            d("bg-violet-900/40 text-violet-300", "bg-violet-50 text-violet-700")
          }`}>
            Synthesis Report
          </span>
          {state.model && (
            <span className="model-tag">{state.model.replace("claude-", "")}</span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Synthesis timer */}
          {timer?.startedAt && (
            <div className={`flex items-center gap-0.5 text-[11px] font-mono ${
              timer.doneAt
                ? d("text-gray-500", "text-slate-400")
                : "text-violet-500"
            }`}>
              <span>⏱</span>
              <ElapsedTime startedAt={timer.startedAt} doneAt={timer.doneAt} />
            </div>
          )}

          {state.status === "running" && (
            <span className="flex items-center gap-1 text-xs text-violet-500">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-500 animate-pulse" />
              Synthesizing...
            </span>
          )}
          {state.status === "done" && (
            <span className={`text-xs ${d("text-gray-500", "text-slate-400")}`}>Complete</span>
          )}
          {state.streamText && <CopyButton text={state.streamText} />}
        </div>
      </div>

      {/* Usage metrics row */}
      {metrics && (metrics.input_tokens > 0 || metrics.output_tokens > 0) && (
        <SynthesisUsageRow metrics={metrics} d={d} />
      )}

      {/* Rendered content — grows to fill, scrolls internally */}
      <div className="flex-1 overflow-y-auto p-4 min-h-0">
        {state.streaming ? (
          <pre className={`stream-text text-xs leading-relaxed whitespace-pre-wrap cursor-blink ${
            d("text-gray-200", "text-slate-800")
          }`}>
            {state.streamText}
          </pre>
        ) : (
          <div className="synthesis-markdown text-sm leading-relaxed">
            <ReactMarkdown>{state.streamText}</ReactMarkdown>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
