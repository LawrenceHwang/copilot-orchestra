import { useEffect, useState } from "react";

/**
 * Displays elapsed time since startedAt, ticking live until doneAt is set.
 * @param {number} startedAt  - ms timestamp when timing began
 * @param {number|null} doneAt - ms timestamp when timing ended (null = still running)
 * @param {string} className  - extra Tailwind classes
 */
export function ElapsedTime({ startedAt, doneAt, className = "" }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!startedAt || doneAt) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [startedAt, doneAt]);

  if (!startedAt) return null;

  const secs = ((doneAt || now) - startedAt) / 1000;
  return <span className={className}>{secs.toFixed(1)}s</span>;
}
