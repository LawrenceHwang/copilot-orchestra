import { useEffect, useRef, useState } from "react";

/**
 * Subscribe to an SSE stream and return all received events.
 *
 * @param {string | null} url - SSE endpoint URL, or null to not connect
 * @param {(event: object) => void} onEvent - called for every event received
 * @returns {{ connected: boolean, error: string | null }}
 */
export function useSSE(url, onEvent) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const esRef = useRef(null);
  const onEventRef = useRef(onEvent);

  // Keep the callback ref current without re-opening the connection
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!url) return;

    const es = new EventSource(url);
    esRef.current = es;
    setConnected(false);
    setError(null);

    es.onopen = () => {
      setConnected(true);
      setError(null);
    };

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        onEventRef.current(event);
        // Close when backend signals end
        if (event.type === "stream.end") {
          es.close();
          setConnected(false);
        }
      } catch {
        // Ignore malformed events (heartbeat comments are handled by browser)
      }
    };

    es.onerror = () => {
      setError("Connection lost");
      setConnected(false);
      es.close();
    };

    return () => {
      es.close();
      setConnected(false);
    };
  }, [url]);

  return { connected, error };
}
