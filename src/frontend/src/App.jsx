import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { fetchModels, startReview } from "./api/client.js";
import { AgentPanel } from "./components/AgentPanel.jsx";
import { ElapsedTime } from "./components/ElapsedTime.jsx";
import { MetricsBar } from "./components/MetricsBar.jsx";
import { ModelRouterPanel } from "./components/ModelRouterPanel.jsx";
import { SynthesisPanel } from "./components/SynthesisPanel.jsx";
import { TaskInput } from "./components/TaskInput.jsx";
import { useSSE } from "./hooks/useSSE.js";
import { ThemeProvider, useTheme, useThemeClasses } from "./ThemeContext.jsx";
import { generateReviewerNames } from "./utils/nameGenerator.js";

// ── State shape ───────────────────────────────────────────────────────────────

const AGENT_ROLES = ["reviewer_1", "reviewer_2", "reviewer_3"];

function resolveContextWindowTokens(modelId, models) {
  if (!modelId) return null;
  const model = models.find((m) => m.id === modelId);
  const n = model?.capabilities?.limits?.max_context_window_tokens;
  return Number.isFinite(n) && n > 0 ? n : null;
}

function makeAgentState() {
  return {
    status: "idle",       // idle | running | done | error
    streamText: "",
    streaming: false,
    model: null,
    toolCalls: [],
    error: null,
    plan: null,           // orchestrator only — ReviewPlan once submitted
  };
}

function makeSynthState() {
  return { status: "idle", streamText: "", streaming: false, model: null };
}

const initialState = {
  reviewStatus: "idle",    // idle | running | complete | error
  sseUrl: null,
  reviewId: null,
  agents: Object.fromEntries(AGENT_ROLES.map((r) => [r, makeAgentState()])),
  orchestrator: makeAgentState(),
  synthesis: makeSynthState(),
  metrics: {},             // { [agentRole]: { input_tokens, output_tokens, turns, quota, model, context_window_tokens } }
  globalError: null,
  timers: {
    reviewStartedAt: null,   // ms — set when review is submitted
    reviewDoneAt: null,      // ms — set when stream ends
    agents: {},              // [agent]: { startedAt, doneAt }
  },
};

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state, action) {
  switch (action.type) {
    case "REVIEW_STARTED":
      return {
        ...initialState,
        reviewStatus: "running",
        sseUrl: action.sseUrl,
        reviewId: action.reviewId,
        agents: Object.fromEntries(AGENT_ROLES.map((r) => [r, makeAgentState()])),
        orchestrator: makeAgentState(),
        synthesis: makeSynthState(),
        metrics: {},
        timers: {
          reviewStartedAt: action.timestamp,
          reviewDoneAt: null,
          agents: {},
        },
      };

    case "AGENT_STARTED": {
      let next;
      if (action.agent === "synthesizer") {
        next = { ...state, synthesis: { ...state.synthesis, status: "running", model: action.model, streaming: true } };
      } else if (action.agent === "orchestrator") {
        next = { ...state, orchestrator: { ...state.orchestrator, status: "running", model: action.model } };
      } else {
        next = {
          ...state,
          agents: { ...state.agents, [action.agent]: { ...state.agents[action.agent], status: "running", model: action.model } },
        };
      }
      const prevMetrics = state.metrics[action.agent] || {};
      return {
        ...next,
        metrics: {
          ...next.metrics,
          [action.agent]: {
            input_tokens: prevMetrics.input_tokens ?? 0,
            output_tokens: prevMetrics.output_tokens ?? 0,
            turns: prevMetrics.turns ?? 0,
            quota: prevMetrics.quota ?? null,
            model: action.model || prevMetrics.model || null,
            context_window_tokens:
              action.context_window_tokens ?? prevMetrics.context_window_tokens ?? null,
          },
        },
        timers: {
          ...next.timers,
          agents: { ...next.timers.agents, [action.agent]: { startedAt: action.timestamp, doneAt: null } },
        },
      };
    }

    case "AGENT_STREAM": {
      if (action.agent === "synthesizer") {
        return {
          ...state,
          synthesis: {
            ...state.synthesis,
            streamText: state.synthesis.streamText + action.content,
            streaming: true,
          },
        };
      }
      if (action.agent === "orchestrator") {
        return {
          ...state,
          orchestrator: {
            ...state.orchestrator,
            streamText: state.orchestrator.streamText + action.content,
            streaming: true,
          },
        };
      }
      const prev = state.agents[action.agent] || makeAgentState();
      return {
        ...state,
        agents: {
          ...state.agents,
          [action.agent]: { ...prev, streamText: prev.streamText + action.content, streaming: true },
        },
      };
    }

    case "AGENT_TOOL_CALL": {
      if (!AGENT_ROLES.includes(action.agent) && action.agent !== "orchestrator") return state;
      const key = action.agent === "orchestrator" ? "orchestrator" : action.agent;
      const target = key === "orchestrator" ? state.orchestrator : state.agents[key];
      const updated = { ...target, toolCalls: [...target.toolCalls, { tool_name: action.tool_name, args: action.args }] };
      return key === "orchestrator"
        ? { ...state, orchestrator: updated }
        : { ...state, agents: { ...state.agents, [key]: updated } };
    }

    case "AGENT_DONE": {
      let next;
      if (action.agent === "synthesizer") {
        next = { ...state, synthesis: { ...state.synthesis, status: "done", streaming: false } };
      } else if (action.agent === "orchestrator") {
        next = { ...state, orchestrator: { ...state.orchestrator, status: "done", streaming: false } };
      } else {
        next = {
          ...state,
          agents: {
            ...state.agents,
            [action.agent]: { ...state.agents[action.agent], status: "done", streaming: false },
          },
        };
      }
      return {
        ...next,
        timers: {
          ...next.timers,
          agents: {
            ...next.timers.agents,
            [action.agent]: { ...(next.timers.agents[action.agent] || {}), doneAt: action.timestamp },
          },
        },
      };
    }

    case "AGENT_ERROR": {
      if (action.agent === "synthesizer") {
        return { ...state, synthesis: { ...state.synthesis, status: "error" } };
      }
      const agentToUpdate = AGENT_ROLES.includes(action.agent) ? action.agent : null;
      if (!agentToUpdate) return state;
      return {
        ...state,
        agents: {
          ...state.agents,
          [agentToUpdate]: { ...state.agents[agentToUpdate], status: "error", error: action.error },
        },
      };
    }

    case "METRICS_UPDATE": {
      const prev = state.metrics[action.agent] || {};
      return {
        ...state,
        metrics: {
          ...state.metrics,
          [action.agent]: {
            input_tokens: action.input_tokens ?? prev.input_tokens ?? 0,
            output_tokens: action.output_tokens ?? prev.output_tokens ?? 0,
            turns: action.turns ?? prev.turns ?? 0,
            quota: action.quota ?? prev.quota ?? null,
            model: action.model || prev.model || null,
            context_window_tokens:
              action.context_window_tokens ?? prev.context_window_tokens ?? null,
          },
        },
      };
    }

    case "ORCHESTRATOR_PLAN":
      return {
        ...state,
        orchestrator: { ...state.orchestrator, plan: action.plan },
      };

    case "REVIEW_COMPLETE":
      return {
        ...state,
        reviewStatus: "complete",
        timers: { ...state.timers, reviewDoneAt: state.timers.reviewDoneAt || action.timestamp },
      };

    case "REVIEW_ERROR":
      return { ...state, reviewStatus: "error", globalError: action.error };

    case "STREAM_END":
      return {
        ...state,
        reviewStatus: state.reviewStatus === "running" ? "complete" : state.reviewStatus,
        sseUrl: null,
        timers: { ...state.timers, reviewDoneAt: state.timers.reviewDoneAt || action.timestamp },
      };

    default:
      return state;
  }
}

// ── Session persistence ────────────────────────────────────────────────────────

const STORAGE_KEY = "copilot_orchestra_state";

function loadPersistedState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState;
    const saved = JSON.parse(raw);
    // SSE stream is gone after refresh — clear URL and normalise status
    saved.sseUrl = null;
    if (saved.reviewStatus === "running") saved.reviewStatus = "complete";
    // Normalise any agents that were mid-stream
    for (const role of Object.keys(saved.agents || {})) {
      if (saved.agents[role].status === "running") {
        saved.agents[role].status = "done";
        saved.agents[role].streaming = false;
      }
    }
    if (saved.synthesis?.status === "running") {
      saved.synthesis.status = "done";
      saved.synthesis.streaming = false;
    }
    // Ensure timers shape exists
    if (!saved.timers) saved.timers = initialState.timers;
    return saved;
  } catch {
    return initialState;
  }
}

// ── App shell (inner, has access to theme context) ────────────────────────────

function AppInner() {
  const { theme, toggle } = useTheme();
  const { d } = useThemeClasses();

  const [state, dispatch] = useReducer(reducer, undefined, loadPersistedState);
  const [models, setModels] = useState([]);
  const [modelConfig, setModelConfig] = useState({ preset: "balanced", overrides: {} });
  const [reviewerNames] = useState(() => generateReviewerNames(3));
  const [submitting, setSubmitting] = useState(false);
  const [connectionError, setConnectionError] = useState(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(360);
  const [isDesktop, setIsDesktop] = useState(() => window.innerWidth >= 768);
  const [expandedPanel, setExpandedPanel] = useState(null);
  const dragState = useRef({ active: false, startX: 0, startW: 0 });
  // Track which agents have received at least one agent.stream event this review.
  // Used to prevent agent.message from doubling content when the SDK emits both.
  const streamedAgentsRef = useRef(new Set());

  // Persist state to sessionStorage whenever it changes (skip idle — nothing to save)
  useEffect(() => {
    if (state.reviewStatus !== "idle") {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      } catch {
        // storage quota exceeded or private mode — silently ignore
      }
    }
  }, [state]);

  // Track desktop breakpoint
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const handler = (e) => setIsDesktop(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Resize drag handling
  useEffect(() => {
    function onMove(e) {
      if (!dragState.current.active) return;
      const w = Math.max(260, Math.min(560, dragState.current.startW + e.clientX - dragState.current.startX));
      setSidebarWidth(w);
    }
    function onUp() { dragState.current.active = false; }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function onResizeStart(e) {
    dragState.current = { active: true, startX: e.clientX, startW: sidebarWidth };
    e.preventDefault();
  }

  const [byokActive, setByokActive] = useState(false);

  // Load available models on mount
  useEffect(() => {
    fetchModels()
      .then((data) => {
        setModels(data.models || []);
        setByokActive(data.byok_active || false);
      })
      .catch(() => setModels([]));
  }, []);

  // Handle SSE events
  const handleEvent = useCallback((event) => {
    const ts = Date.now();
    switch (event.type) {
      case "agent.started":
        dispatch({
          type: "AGENT_STARTED",
          agent: event.agent,
          model: event.model,
          context_window_tokens: resolveContextWindowTokens(event.model, models),
          timestamp: ts,
        });
        break;
      case "agent.stream":
        streamedAgentsRef.current.add(event.agent);
        dispatch({ type: "AGENT_STREAM", agent: event.agent, content: event.content });
        break;
      case "agent.message":
        // Final message — fallback for non-streaming models only.
        // Skip if we already received agent.stream events for this agent to avoid doubling.
        if (!streamedAgentsRef.current.has(event.agent)) {
          dispatch({ type: "AGENT_STREAM", agent: event.agent, content: event.content });
        }
        break;
      case "agent.tool_call":
        dispatch({ type: "AGENT_TOOL_CALL", agent: event.agent, tool_name: event.tool_name, args: event.args });
        break;
      case "agent.done":
        dispatch({ type: "AGENT_DONE", agent: event.agent, timestamp: ts });
        break;
      case "agent.error":
        dispatch({ type: "AGENT_ERROR", agent: event.agent, error: event.error });
        break;
      case "metrics.update":
        dispatch({
          type: "METRICS_UPDATE",
          agent: event.agent,
          input_tokens: event.input_tokens,
          output_tokens: event.output_tokens,
          turns: event.turns,
          quota: event.quota,
          model: event.model,
          context_window_tokens:
            event.context_window_tokens ?? resolveContextWindowTokens(event.model, models),
        });
        break;
      case "orchestrator.plan":
        dispatch({ type: "ORCHESTRATOR_PLAN", plan: event.plan });
        break;
      case "review.complete":
        dispatch({ type: "REVIEW_COMPLETE", timestamp: ts });
        break;
      case "review.error":
        dispatch({ type: "REVIEW_ERROR", error: event.error });
        break;
      case "stream.end":
        dispatch({ type: "STREAM_END", timestamp: ts });
        break;
    }
  }, [models]);

  const { connected, error: sseError } = useSSE(state.sseUrl, handleEvent);

  async function handleSubmit(formData) {
    setSubmitting(true);
    setConnectionError(null);
    try {
      const payload = {
        ...formData,
        model_preset: modelConfig.preset,
        model_overrides: Object.keys(modelConfig.overrides).length > 0
          ? modelConfig.overrides
          : undefined,
      };
      const { review_id, sse_url } = await startReview(payload);
      streamedAgentsRef.current = new Set();
      dispatch({ type: "REVIEW_STARTED", reviewId: review_id, sseUrl: sse_url, timestamp: Date.now() });
    } catch (err) {
      setConnectionError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const isRunning = state.reviewStatus === "running";

  // Warn before refresh/close when a review is loaded
  useEffect(() => {
    if (state.reviewStatus === "idle") return;
    function onBeforeUnload(e) {
      sessionStorage.removeItem(STORAGE_KEY);
      e.preventDefault();
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [state.reviewStatus]);

  return (
    <div className={`h-screen flex flex-col overflow-hidden ${d("bg-gray-950", "bg-slate-50")}`}>
      {/* Top bar */}
      <header className={`flex items-center justify-between px-4 py-2 border-b ${d("bg-gray-900 border-gray-800", "bg-white border-slate-200 shadow-sm")}`}>
        <div className="flex items-center gap-3">
          <span className={`text-sm font-bold tracking-tight ${d("text-gray-100", "text-gray-900")}`}>
            Copilot Orchestra
          </span>
          <span className={`text-[10px] border px-1.5 py-0.5 rounded ${d("text-gray-300 border-gray-700", "text-slate-600 border-slate-200")}`}>
            v0.1
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Overall timer */}
          {state.timers.reviewStartedAt && (
            <div className={`flex items-center gap-1 text-xs font-mono ${d("text-gray-200", "text-slate-600")}`}>
              <span>⏱</span>
              <ElapsedTime
                startedAt={state.timers.reviewStartedAt}
                doneAt={state.timers.reviewDoneAt}
              />
            </div>
          )}

          {connected && (
            <span className="flex items-center gap-1.5 text-[10px] text-emerald-500">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Streaming
            </span>
          )}
          {sseError && (
            <span className="text-[10px] text-red-400">⚠ {sseError}</span>
          )}

          {/* Info button */}
          <div className="relative">
            <button
              onClick={() => setInfoOpen((o) => !o)}
              title="About Copilot Orchestra"
              className={`text-xs px-2.5 py-1 rounded border transition-colors ${infoOpen
                ? d("border-indigo-500 text-indigo-400", "border-indigo-400 text-indigo-600")
                : d(
                  "border-gray-700 text-gray-400 hover:text-gray-100 hover:border-gray-500",
                  "border-slate-200 text-slate-500 hover:text-slate-800 hover:border-slate-400"
                )
                }`}
            >
              ?
            </button>

            {infoOpen && (
              <>
                {/* Backdrop */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setInfoOpen(false)}
                />
                {/* Panel */}
                <div className={`absolute right-0 top-8 z-50 w-80 rounded-lg border shadow-2xl p-4 space-y-3 ${d("bg-gray-900 border-gray-700 text-gray-300", "bg-white border-slate-200 text-slate-700")
                  }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h2 className={`text-sm font-semibold ${d("text-gray-100", "text-slate-900")}`}>
                        Copilot Orchestra
                      </h2>
                      <p className={`text-[10px] mt-0.5 ${d("text-indigo-400", "text-indigo-600")}`}>
                        A GitHub Copilot SDK showcase
                      </p>
                    </div>
                    <button
                      onClick={() => setInfoOpen(false)}
                      className={`text-xs leading-none mt-0.5 ${d("text-gray-500 hover:text-gray-200", "text-slate-400 hover:text-slate-700")}`}
                    >
                      ✕
                    </button>
                  </div>

                  <p className="text-[11px] leading-relaxed">
                    The GitHub Copilot CLI is a black box — one session, one model, no visibility.
                    This app tears the lid off by using the <span className={`font-medium ${d("text-indigo-300", "text-indigo-600")}`}>Copilot SDK</span> directly
                    to run five agents simultaneously, each fully observable in real time.
                  </p>

                  <div className="space-y-2">
                    <p className={`text-[10px] font-semibold uppercase tracking-wider ${d("text-gray-500", "text-slate-400")}`}>
                      The pipeline
                    </p>
                    <ol className="space-y-1.5 text-[11px] leading-snug">
                      {[
                        ["Orchestrator", "Reads the codebase, builds a focused review plan, and — in Auto mode — selects the right model for each reviewer."],
                        ["3 Specialist reviewers", "Security, Performance, and Readability agents run in parallel. Each streams its output live."],
                        ["Synthesizer", "Combines all three reviews into one unified report."],
                      ].map(([title, body]) => (
                        <li key={title} className="flex gap-2">
                          <span className={`shrink-0 font-medium ${d("text-indigo-400", "text-indigo-600")}`}>{title}</span>
                          <span className={d("text-gray-400", "text-slate-500")}>{body}</span>
                        </li>
                      ))}
                    </ol>
                  </div>

                  <div className="space-y-2">
                    <p className={`text-[10px] font-semibold uppercase tracking-wider ${d("text-gray-500", "text-slate-400")}`}>
                      SDK capabilities on display
                    </p>
                    <ul className="space-y-1 text-[11px]">
                      {[
                        "Parallel multi-session orchestration",
                        "Real-time event streaming (tokens, tool calls, reasoning)",
                        "Programmatic tool registration with security sandboxing",
                        "Per-agent model routing and BYOK provider injection",
                        "Liveness watchdog — stuck agents are cancelled, not waited on",
                      ].map((item) => (
                        <li key={item} className={`flex gap-1.5 ${d("text-gray-400", "text-slate-500")}`}>
                          <span className={d("text-indigo-500", "text-indigo-400")}>·</span>
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <p className={`text-[10px] leading-relaxed border-t pt-2 ${d("border-gray-800 text-gray-500", "border-slate-100 text-slate-400")
                    }`}>
                    The orchestration layer is UI-agnostic — a TUI or CI integration could import it directly without touching the FastAPI layer.
                  </p>
                </div>
              </>
            )}
          </div>

          {/* Theme toggle */}
          <button
            onClick={toggle}
            title="Toggle theme"
            className={`text-xs px-2.5 py-1 rounded border transition-colors ${d(
              "border-gray-700 text-gray-200 hover:text-white hover:border-gray-500",
              "border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-400"
            )
              }`}
          >
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </header>

      {/* Metrics bar */}
      <MetricsBar metrics={state.metrics} reviewStatus={state.reviewStatus} reviewerNames={reviewerNames} models={models} byokActive={byokActive} />

      <main className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left sidebar — controls */}
        <aside
          className={`flex-shrink-0 border-b md:border-b-0 overflow-y-auto overflow-x-hidden p-3 space-y-3 max-h-[45vh] md:max-h-none w-full ${d("bg-gray-950 border-gray-800", "bg-slate-50 border-slate-200")
            }`}
          style={isDesktop ? { width: sidebarWidth } : {}}
        >
          <TaskInput onSubmit={handleSubmit} disabled={isRunning || submitting} />
          <ModelRouterPanel
            config={modelConfig}
            onChange={setModelConfig}
            models={models}
            disabled={isRunning || submitting}
            reviewerNames={reviewerNames}
          />

          {connectionError && (
            <div className={`rounded px-3 py-2 text-xs ${d("bg-red-950 border border-red-800 text-red-400", "bg-red-50 border border-red-200 text-red-600")}`}>
              ⚠ {connectionError}
            </div>
          )}

          {state.globalError && (
            <div className={`rounded px-3 py-2 text-xs ${d("bg-red-950 border border-red-800 text-red-400", "bg-red-50 border border-red-200 text-red-600")}`}>
              Review failed: {state.globalError}
            </div>
          )}
        </aside>

        {/* Resize handle — desktop only */}
        <div
          className={`hidden md:flex w-1 flex-shrink-0 cursor-col-resize transition-colors ${d("bg-gray-800 hover:bg-indigo-600", "bg-slate-200 hover:bg-indigo-400")
            }`}
          onMouseDown={onResizeStart}
        />

        {/* Main content */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3 flex flex-col">
          {/* Orchestrator panel — full-width horizontal bar above reviewers */}
          {(isRunning || state.reviewStatus === "complete") && (state.orchestrator.status !== "idle" || state.orchestrator.streamText) && (
            <AgentPanel
              role="orchestrator"
              name="Orchestrator"
              state={state.orchestrator}
              timer={state.timers.agents["orchestrator"]}
              reviewStartedAt={state.timers.reviewStartedAt}
              metrics={state.metrics["orchestrator"]}
              isExpanded={expandedPanel === "orchestrator"}
              onExpand={() => setExpandedPanel("orchestrator")}
              onCollapse={() => setExpandedPanel(null)}
              className="max-h-[260px]"
              compactWhenDone
            />
          )}

          {/* Specialist agents — responsive columns */}
          {(isRunning || state.reviewStatus === "complete") && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" style={{ minHeight: "350px" }}>
              {AGENT_ROLES.map((role, i) => (
                <AgentPanel
                  key={role}
                  role={role}
                  name={reviewerNames[i]}
                  state={state.agents[role]}
                  timer={state.timers.agents[role]}
                  reviewStartedAt={state.timers.reviewStartedAt}
                  metrics={state.metrics[role]}
                  isExpanded={expandedPanel === role}
                  onExpand={() => setExpandedPanel(role)}
                  onCollapse={() => setExpandedPanel(null)}
                />
              ))}
            </div>
          )}

          {/* Synthesis */}
          {(isRunning || state.reviewStatus === "complete") && (
            <SynthesisPanel
              state={state.synthesis}
              timer={state.timers.agents["synthesizer"]}
              metrics={state.metrics["synthesizer"]}
              isExpanded={expandedPanel === "synthesizer"}
              onExpand={() => setExpandedPanel("synthesizer")}
              onCollapse={() => setExpandedPanel(null)}
            />
          )}

          {/* Welcome screen */}
          {state.reviewStatus === "idle" && (
            <div className="flex-1 flex flex-col items-center justify-center min-h-[400px] text-center space-y-4">
              <div className="text-5xl opacity-20">🎼</div>
              <h2 className={`text-lg font-semibold ${d("text-gray-400", "text-slate-500")}`}>
                Copilot Orchestra
              </h2>
              <p className={`text-sm max-w-md ${d("text-gray-600", "text-slate-400")}`}>
                Multi-agent AI code review. Configure your task and model preset in the sidebar,
                then start a review to see three independent reviewer agents
                working in parallel, followed by a synthesizer making the final call.
              </p>
              <div className={`flex gap-2 text-xs ${d("text-gray-700", "text-slate-400")}`}>
                {["5 agents", "real-time streaming", "live metrics"].map((tag) => (
                  <span
                    key={tag}
                    className={`px-2 py-1 border rounded ${d("border-gray-800", "border-slate-200")}`}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ── Root export — wraps with ThemeProvider ────────────────────────────────────

export default function App() {
  return (
    <ThemeProvider>
      <AppInner />
    </ThemeProvider>
  );
}
