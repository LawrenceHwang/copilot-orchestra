import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { CopyButton } from "./AgentPanel.jsx";
import { ElapsedTime } from "./ElapsedTime.jsx";
import { useThemeClasses } from "../ThemeContext.jsx";

/**
 * SynthesisPanel — displays the synthesizer's streaming output and final report.
 */
export function SynthesisPanel({ state, timer }) {
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
