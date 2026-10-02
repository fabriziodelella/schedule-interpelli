/** Singolo avviso, come scritto da check.py in public/interpelli.json */
export interface Interpello {
  title: string;
  link: string;
  /** Data di pubblicazione in formato ISO 8601 (UTC) */
  date: string;
  /** Codici di classe di concorso estratti dal titolo */
  codes: string[];
  /** true se l'avviso è comparso nelle ultime 24 ore */
  isNew: boolean;
}
