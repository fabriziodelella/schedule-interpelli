import { useCallback, useEffect, useMemo, useState } from "react";
import type { Interpello } from "./types";

// Owner e repo sono configurabili con VITE_GH_OWNER / VITE_GH_REPO.
// Nel deploy su GitHub Pages li imposta il workflow; questi sono i default per lo sviluppo locale.
const OWNER = import.meta.env.VITE_GH_OWNER || "tuo-utente-github";
const REPO = import.meta.env.VITE_GH_REPO || "schedule-interpelli";
const DATA_URL = `https://raw.githubusercontent.com/${OWNER}/${REPO}/main/public/interpelli.json`;

const MAIN_CODES = ["ADEE", "ADAA", "ADMM", "ADSS"] as const;
type Filter = "TUTTI" | (typeof MAIN_CODES)[number] | "ALTRI";
const FILTERS: Filter[] = ["TUTTI", ...MAIN_CODES, "ALTRI"];

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Interpello[] };

const dateFormat = new Intl.DateTimeFormat("it-IT", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "data non disponibile" : dateFormat.format(d);
}

function timestamp(iso: string): number {
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}

/** true se l'avviso rientra nel filtro scelto */
function matchesFilter(item: Interpello, filter: Filter): boolean {
  const isMain = item.codes.some((c) => (MAIN_CODES as readonly string[]).includes(c));
  if (filter === "TUTTI") return true;
  if (filter === "ALTRI") return !isMain;
  return item.codes.includes(filter);
}

function filterLabel(filter: Filter): string {
  if (filter === "TUTTI") return "Tutti";
  if (filter === "ALTRI") return "Altri";
  return filter;
}

export default function App() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [filter, setFilter] = useState<Filter>("TUTTI");
  const [query, setQuery] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setState({ status: "loading" });
    try {
      const res = await fetch(DATA_URL, { signal, cache: "no-cache" });
      if (!res.ok) throw new Error(`Risposta HTTP ${res.status}`);
      const data: unknown = await res.json();
      if (!Array.isArray(data)) throw new Error("Formato dei dati non valido");
      const items = (data as Interpello[]).slice().sort((a, b) => timestamp(b.date) - timestamp(a.date));
      setState({ status: "ok", items });
    } catch (err) {
      if (signal?.aborted) return;
      const message = err instanceof Error ? err.message : "Errore sconosciuto";
      setState({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const items = state.status === "ok" ? state.items : [];

  // Numero di avvisi per ogni chip (rispetto a tutto l'elenco)
  const counts = useMemo(() => {
    const result = {} as Record<Filter, number>;
    for (const f of FILTERS) result[f] = items.filter((i) => matchesFilter(i, f)).length;
    return result;
  }, [items]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter(
      (i) =>
        matchesFilter(i, filter) &&
        (q === "" || i.title.toLowerCase().includes(q) || i.codes.some((c) => c.toLowerCase().includes(q))),
    );
  }, [items, filter, query]);

  return (
    <main className="container">
      <header>
        <h1>Interpelli ATP Roma</h1>
        <p className="subtitle">Ultimi avvisi per supplenze docenti, aggiornati automaticamente.</p>
      </header>

      <div className="toolbar">
        <input
          type="search"
          className="search"
          placeholder="Cerca per titolo o codice…"
          aria-label="Cerca avvisi"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="chips" role="group" aria-label="Filtra per codice">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              className={`chip${filter === f ? " active" : ""}`}
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
            >
              {filterLabel(f)}
              {state.status === "ok" && <span className="count">{counts[f]}</span>}
            </button>
          ))}
        </div>
      </div>

      {state.status === "loading" && <p className="status">Caricamento in corso…</p>}

      {state.status === "error" && (
        <div className="status error" role="alert">
          <p>Impossibile caricare gli avvisi ({state.message}).</p>
          <button type="button" className="retry" onClick={() => void load()}>
            Riprova
          </button>
        </div>
      )}

      {state.status === "ok" && visible.length === 0 && (
        <p className="status">Nessun avviso corrisponde ai filtri selezionati.</p>
      )}

      {state.status === "ok" && visible.length > 0 && (
        <ul className="list">
          {visible.map((item) => (
            <li key={item.link} className="card">
              <div className="meta">
                <time dateTime={item.date}>{formatDate(item.date)}</time>
                {item.isNew && <span className="badge">Nuovo</span>}
              </div>
              <a href={item.link} target="_blank" rel="noopener noreferrer" className="title">
                {item.title}
              </a>
              {item.codes.length > 0 && (
                <div className="codes">
                  {item.codes.map((c) => (
                    <span key={c} className="code">
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <footer>
        Fonte:{" "}
        <a href="https://www.atpromaistruzione.it/atp/tag/interpelli/" target="_blank" rel="noopener noreferrer">
          ATP Roma
        </a>
      </footer>
    </main>
  );
}
