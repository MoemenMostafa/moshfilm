// Live events from the server (Server-Sent Events: a one-way stream the browser keeps open).
export type EventName = "film" | "proposals" | "queue" | "scene" | "voice" | "activity" | "history";
export type Handlers = Partial<Record<EventName, (data: any) => void>>;

const NAMES: EventName[] = ["film", "proposals", "queue", "scene", "voice", "activity", "history"];
const RECONNECT_MS = 2000;

/** Opens /api/events, calls the matching handler per event, reconnects after 2 s. Returns an unsubscribe. */
export function subscribe(handlers: Handlers): () => void {
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  function open(): void {
    source = new EventSource("/api/events");
    for (const name of NAMES) {
      source.addEventListener(name, (ev) => {
        let data: unknown = {};
        try {
          data = JSON.parse((ev as MessageEvent).data);
        } catch {
          /* an event without a JSON body still counts */
        }
        handlers[name]?.(data);
      });
    }
    source.onerror = () => {
      source?.close();
      source = null;
      if (!closed && timer === null) {
        timer = setTimeout(() => {
          timer = null;
          if (!closed) open();
        }, RECONNECT_MS);
      }
    };
  }

  open();
  return () => {
    closed = true;
    if (timer !== null) clearTimeout(timer);
    source?.close();
  };
}
