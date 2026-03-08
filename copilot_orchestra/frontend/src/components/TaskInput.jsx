import { useState } from "react";
import { useThemeClasses } from "../ThemeContext.jsx";

const DEFAULT_PATH = "/Users/law/workplace/GitHub/global-demographics";

/**
 * TaskInput — form for starting a review.
 *
 * Props:
 *   onSubmit(formData) — called with validated form data
 *   disabled — disable form while review is running
 */
export function TaskInput({ onSubmit, disabled }) {
  const { d } = useThemeClasses();
  const [task, setTask] = useState("");
  const [codebasePath, setCodebasePath] = useState(DEFAULT_PATH);
  const [scope, setScope] = useState("full");
  const [customPaths, setCustomPaths] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (task.trim().length < 10) {
      setError("Task description must be at least 10 characters.");
      return;
    }
    if (!codebasePath.trim()) {
      setError("Codebase path is required.");
      return;
    }
    if (scope === "custom" && !customPaths.trim()) {
      setError("Custom paths are required when scope is 'custom'.");
      return;
    }

    onSubmit({
      task: task.trim(),
      codebase_path: codebasePath.trim(),
      scope,
      custom_paths: scope === "custom"
        ? customPaths.split("\n").map((p) => p.trim()).filter(Boolean)
        : null,
    });
  }

  const inputCls = `w-full text-xs rounded px-3 py-2 font-mono focus:outline-none
    disabled:opacity-50 disabled:cursor-not-allowed ${
    d(
      "bg-gray-800 border border-gray-700 text-gray-200 focus:border-indigo-500 placeholder-gray-600",
      "bg-white border border-slate-200 text-gray-800 focus:border-indigo-400 placeholder-slate-400 shadow-sm"
    )
  }`;

  return (
    <form
      onSubmit={handleSubmit}
      className={`rounded-lg border p-4 space-y-3 ${
        d("bg-gray-900 border-gray-800", "bg-white border-slate-200 shadow-sm")
      }`}
    >
      <h3 className={`text-xs font-semibold uppercase tracking-wider ${d("text-gray-400", "text-slate-500")}`}>
        Review Task
      </h3>

      {/* Codebase path */}
      <div>
        <label className={`block text-[10px] uppercase tracking-wider mb-1 ${d("text-gray-500", "text-slate-400")}`}>
          Codebase Path
        </label>
        <input
          type="text"
          value={codebasePath}
          onChange={(e) => setCodebasePath(e.target.value)}
          disabled={disabled}
          placeholder="/path/to/codebase"
          className={inputCls}
        />
      </div>

      {/* Scope */}
      <div className="flex items-center gap-3">
        <span className={`text-[10px] uppercase tracking-wider ${d("text-gray-500", "text-slate-400")}`}>Scope</span>
        {["full", "custom"].map((s) => (
          <label key={s} className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="scope"
              value={s}
              checked={scope === s}
              onChange={() => setScope(s)}
              disabled={disabled}
              className="accent-indigo-500"
            />
            <span className={`text-xs capitalize whitespace-nowrap ${d("text-gray-300", "text-slate-600")}`}>
              {s === "full" ? "Full repo" : "Custom paths"}
            </span>
          </label>
        ))}
      </div>

      {/* Custom paths */}
      {scope === "custom" && (
        <div>
          <label className={`block text-[10px] uppercase tracking-wider mb-1 ${d("text-gray-500", "text-slate-400")}`}>
            Paths to review (one per line)
          </label>
          <textarea
            value={customPaths}
            onChange={(e) => setCustomPaths(e.target.value)}
            disabled={disabled}
            rows={3}
            placeholder={"src/auth\nsrc/api/routes.py"}
            className={`${inputCls} resize-none`}
          />
        </div>
      )}

      {/* Task description */}
      <div>
        <label className={`block text-[10px] uppercase tracking-wider mb-1 ${d("text-gray-500", "text-slate-400")}`}>
          What to review
        </label>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          disabled={disabled}
          rows={6}
          placeholder="Review for security vulnerabilities, performance bottlenecks, and maintainability issues. Focus on the authentication and data pipeline modules."
          className={`${inputCls} resize-y`}
        />
        <p className={`text-[10px] mt-1 ${d("text-gray-600", "text-slate-400")}`}>
          {task.length} / 2000 chars (min 10)
        </p>
      </div>

      {error && (
        <p className="text-red-500 text-xs">⚠ {error}</p>
      )}

      <button
        type="submit"
        disabled={disabled}
        className="w-full py-2 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold
                   rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {disabled ? "Review running..." : "Start Review"}
      </button>
    </form>
  );
}
