import { Component, type ErrorInfo, type ReactNode, useEffect, useState } from "react";

type DebugEntry = {
  at: string;
  level: "error" | "warn" | "info";
  message: string;
};

const MAX = 40;

const mountedTabs = new Set<string>();
let origError: typeof console.error | null = null;
let origWarn: typeof console.warn | null = null;

function pushEntry(tab: string, level: DebugEntry["level"], message: string) {
  const key = `ofdd-tab-debug-${tab}`;
  let entries: DebugEntry[] = [];
  try {
    entries = JSON.parse(localStorage.getItem(key) || "[]") as DebugEntry[];
  } catch {
    entries = [];
  }
  entries.unshift({ at: new Date().toISOString(), level, message });
  localStorage.setItem(key, JSON.stringify(entries.slice(0, MAX)));
}

function installConsoleCapture() {
  if (origError != null) return;
  origError = console.error.bind(console);
  origWarn = console.warn.bind(console);
  console.error = (...args: unknown[]) => {
    const message = args.map(String).join(" ");
    for (const tab of mountedTabs) pushEntry(tab, "error", message);
    origError!(...args);
  };
  console.warn = (...args: unknown[]) => {
    const message = args.map(String).join(" ");
    for (const tab of mountedTabs) pushEntry(tab, "warn", message);
    origWarn!(...args);
  };
}

function uninstallConsoleCapture() {
  if (mountedTabs.size > 0 || origError == null || origWarn == null) return;
  console.error = origError;
  console.warn = origWarn;
  origError = null;
  origWarn = null;
}

export function useTabDebug(tab: string) {
  const [entries, setEntries] = useState<DebugEntry[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const key = `ofdd-tab-debug-${tab}`;
    const load = () => {
      try {
        setEntries(JSON.parse(localStorage.getItem(key) || "[]") as DebugEntry[]);
      } catch {
        setEntries([]);
      }
    };
    load();

    mountedTabs.add(tab);
    installConsoleCapture();

    const onError = (ev: ErrorEvent) => {
      pushEntry(tab, "error", ev.message || "window error");
      load();
    };
    const onRejection = (ev: PromiseRejectionEvent) => {
      const msg = ev.reason instanceof Error ? ev.reason.message : String(ev.reason);
      pushEntry(tab, "error", `unhandled: ${msg}`);
      load();
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
      mountedTabs.delete(tab);
      uninstallConsoleCapture();
    };
  }, [tab]);

  function logInfo(message: string) {
    pushEntry(tab, "info", message);
    setEntries(JSON.parse(localStorage.getItem(`ofdd-tab-debug-${tab}`) || "[]"));
  }

  function clear() {
    localStorage.removeItem(`ofdd-tab-debug-${tab}`);
    setEntries([]);
  }

  return { entries, open, setOpen, logInfo, clear };
}

type PanelProps = {
  tab: string;
};

export function TabDebugPanel({ tab }: PanelProps) {
  const { entries, open, setOpen, clear } = useTabDebug(tab);
  const errors = entries.filter((e) => e.level === "error").length;

  return (
    <div className="tab-debug">
      <button type="button" className="secondary-btn tab-debug-toggle" onClick={() => setOpen(!open)}>
        Debug {errors ? `(${errors} err)` : ""}
      </button>
      {open ? (
        <div className="tab-debug-body">
          <div className="row">
            <span className="muted">Console capture for {tab}</span>
            <button type="button" className="secondary-btn" onClick={clear}>
              Clear
            </button>
          </div>
          {entries.length ? (
            <ul className="tab-debug-list">
              {entries.map((e, i) => (
                <li key={`${e.at}-${i}`} className={e.level === "error" ? "error" : e.level === "warn" ? "muted" : ""}>
                  <time>{e.at.slice(11, 19)}</time> [{e.level}] {e.message}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No captured errors yet.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

type BoundaryProps = {
  tab: string;
  children: ReactNode;
};

type BoundaryState = { error: string | null };

export class TabErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    pushEntry(this.props.tab, "error", `${error.message} ${info.componentStack?.slice(0, 200) || ""}`);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel error">
          <strong>{this.props.tab} crashed:</strong> {this.state.error}
          <div className="toolbar" style={{ marginTop: "0.75rem" }}>
            <button type="button" className="secondary-btn" onClick={() => this.setState({ error: null })}>
              Retry tab
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function logTabInfo(tab: string, message: string) {
  pushEntry(tab, "info", message);
}
