#!/usr/bin/env python3
"""Monitor del feed RSS degli interpelli di ATP Roma.

Cosa fa a ogni esecuzione:
  1. scarica il feed (User-Agent esplicito, timeout, retry con backoff);
  2. confronta i link con quelli già visti (`data/seen.json`);
  3. se ci sono avvisi nuovi invia UNA sola email riepilogativa via Gmail;
  4. solo dopo l'invio riuscito aggiorna `data/seen.json`;
  5. rigenera `public/interpelli.json` (usato dalla dashboard in `web/`).

Variabili d'ambiente (necessarie solo quando c'è almeno un avviso nuovo):
  SMTP_USER  indirizzo Gmail usato per l'invio
  SMTP_PASS  password per app Gmail
  MAIL_TO    uno o più destinatari separati da virgola

Exit code 0 = tutto ok, 1 = errore reale (così GitHub segnala il fallimento).
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import feedparser

# --- Configurazione -------------------------------------------------------

FEED_URL = "https://www.atpromaistruzione.it/atp/tag/interpelli/feed/"
USER_AGENT = "Mozilla/5.0 (compatible; interpelli-monitor/1.0; feed RSS personale)"
HTTP_TIMEOUT = 20  # secondi per ogni tentativo di download
HTTP_RETRIES = 4  # tentativi totali
HTTP_BACKOFF = 2  # attese: 2s, 4s, 8s...

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 30

BASE_DIR = Path(__file__).resolve().parent
SEEN_PATH = BASE_DIR / "data" / "seen.json"
OUTPUT_PATH = BASE_DIR / "public" / "interpelli.json"

MAX_ITEMS = 100  # avvisi conservati in interpelli.json
MAX_SEEN = 5000  # link conservati in seen.json
NEW_WINDOW = timedelta(hours=24)  # per quanto tempo un avviso è "nuovo" in dashboard

# Codici da mettere in evidenza nell'email.
PRIORITY_CODES = ("ADEE", "ADAA", "ADMM", "ADSS")

# Classi di concorso: ADEE/ADAA/..., A001, AB24, ecc.
CODE_RE = re.compile(r"\b(?:AD[A-Z]{2}|[A-Z]\d{3}|[A-Z]{2}\d{2})\b")

log = logging.getLogger("interpelli")


class CheckError(Exception):
    """Errore reale che deve far fallire l'esecuzione (exit code 1)."""


# --- Modello dati ---------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    title: str
    link: str
    date: datetime | None  # sempre in UTC, se disponibile
    codes: tuple[str, ...]


def extract_codes(title: str) -> tuple[str, ...]:
    """Estrae i codici (senza duplicati, nell'ordine in cui compaiono)."""
    return tuple(dict.fromkeys(CODE_RE.findall(title)))


def parse_entry(raw: Any) -> Entry | None:
    """Converte una entry di feedparser; restituisce None se priva di link."""
    link = (raw.get("link") or "").strip()
    if not link:
        return None
    title = re.sub(r"\s+", " ", raw.get("title") or "").strip() or link
    parsed = raw.get("published_parsed") or raw.get("updated_parsed")
    date = datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else None
    return Entry(title=title, link=link, date=date, codes=extract_codes(title))


# --- Download del feed ----------------------------------------------------


def fetch_feed_bytes() -> bytes:
    """Scarica il feed con timeout e retry/backoff sugli errori di rete."""
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # Errori 4xx (tranne 429) non si risolvono riprovando.
            if exc.code < 500 and exc.code != 429:
                raise CheckError(f"Il feed ha risposto HTTP {exc.code}") from exc
            last_error = exc
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            last_error = exc
        if attempt < HTTP_RETRIES:
            wait = HTTP_BACKOFF**attempt
            log.warning(
                "Download fallito (%s), tentativo %d/%d, riprovo tra %ds",
                last_error, attempt, HTTP_RETRIES, wait,
            )
            time.sleep(wait)
    raise CheckError(f"Download del feed non riuscito: {last_error}")


def load_entries() -> list[Entry]:
    """Scarica e interpreta il feed. Feed vuoto o illeggibile => errore."""
    parsed = feedparser.parse(fetch_feed_bytes())
    entries: dict[str, Entry] = {}
    for raw in parsed.entries:
        entry = parse_entry(raw)
        if entry and entry.link not in entries:
            entries[entry.link] = entry
    if not entries:
        reason = getattr(parsed, "bozo_exception", None)
        raise CheckError(f"Il feed non contiene avvisi leggibili ({reason or 'vuoto'})")
    if parsed.bozo:
        # Feed non perfettamente conforme ma utilizzabile: si prosegue.
        log.warning("Feed malformato ma interpretabile: %s", parsed.bozo_exception)
    return list(entries.values())


# --- Lettura / scrittura file --------------------------------------------


def load_seen() -> list[str] | None:
    """Restituisce i link già visti, o None se è la prima esecuzione."""
    if not SEEN_PATH.exists():
        return None
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Non si tratta lo stato corrotto come "prima esecuzione": si fermerebbe
        # silenziosamente l'invio. Meglio fallire e farlo notare.
        raise CheckError(f"Impossibile leggere {SEEN_PATH.name}: {exc}") from exc
    if not isinstance(data, list):
        raise CheckError(f"{SEEN_PATH.name} deve contenere una lista di link")
    return [str(item) for item in data]


def load_previous_records() -> list[dict[str, Any]]:
    """Legge lo storico di interpelli.json; se manca o è rotto riparte da zero."""
    if not OUTPUT_PATH.exists():
        return []
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s illeggibile, lo storico verrà ricostruito: %s", OUTPUT_PATH.name, exc)
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict) and r.get("link")]


def write_json_atomic(path: Path, data: Any) -> None:
    """Scrive il JSON su file temporaneo e poi lo sostituisce (scrittura atomica)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, path)
    except OSError as exc:
        raise CheckError(f"Scrittura di {path.name} non riuscita: {exc}") from exc


# --- Email ----------------------------------------------------------------


def format_date(date: datetime | None) -> str:
    """Data leggibile in fuso orario italiano (UTC se tzdata non è disponibile)."""
    if date is None:
        return "data non disponibile"
    try:
        date = date.astimezone(ZoneInfo("Europe/Rome"))
    except ZoneInfoNotFoundError:
        pass
    return date.strftime("%d/%m/%Y %H:%M")


def build_message(new: list[Entry], sender: str, recipients: list[str]) -> EmailMessage:
    """Costruisce l'unica email riepilogativa (testo + HTML)."""
    highlighted = [e for e in new if any(c in PRIORITY_CODES for c in e.codes)]
    count = len(new)

    # Versione testuale
    lines: list[str] = []
    if highlighted:
        lines.append(f"*** IN EVIDENZA ({', '.join(PRIORITY_CODES)}) ***")
        for e in highlighted:
            lines += [f"- {e.title}", f"  {e.link}", f"  Pubblicato: {format_date(e.date)}"]
        lines.append("")
    lines.append(f"Tutti i nuovi avvisi ({count}):")
    for e in new:
        lines += [f"- {e.title}", f"  {e.link}", f"  Pubblicato: {format_date(e.date)}"]

    # Versione HTML
    def item_html(e: Entry) -> str:
        return (
            f'<li style="margin-bottom:10px"><a href="{escape(e.link, quote=True)}">'
            f"{escape(e.title)}</a><br>"
            f'<small style="color:#555">Pubblicato: {escape(format_date(e.date))}</small></li>'
        )

    html = ['<div style="font-family:Arial,sans-serif;font-size:14px">']
    if highlighted:
        html.append(
            '<div style="background:#fff3cd;border-left:4px solid #e0a800;'
            'padding:8px 14px;margin-bottom:16px">'
            f"<strong>In evidenza ({escape(', '.join(PRIORITY_CODES))})</strong><ul>"
        )
        html += [item_html(e) for e in highlighted]
        html.append("</ul></div>")
    html.append(f"<h3>Tutti i nuovi avvisi ({count})</h3><ul>")
    html += [item_html(e) for e in new]
    html.append("</ul></div>")

    msg = EmailMessage()
    msg["Subject"] = f"{count} nuovi interpelli ATP Roma"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    msg.add_alternative("\n".join(html), subtype="html")
    return msg


def send_email(new: list[Entry]) -> None:
    """Invia l'email riepilogativa via Gmail (SMTP_SSL)."""
    user = os.environ.get("SMTP_USER", "").strip()
    # Le password per app Gmail vengono mostrate a gruppi separati da spazi.
    password = os.environ.get("SMTP_PASS", "").replace(" ", "")
    recipients = [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]
    missing = [
        name
        for name, value in (("SMTP_USER", user), ("SMTP_PASS", password), ("MAIL_TO", recipients))
        if not value
    ]
    if missing:
        raise CheckError(
            f"Ci sono {len(new)} nuovi avvisi ma mancano le variabili: {', '.join(missing)}"
        )

    message = build_message(new, user, recipients)
    try:
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=SMTP_TIMEOUT
        ) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise CheckError(f"Invio email non riuscito: {exc}") from exc
    # Nei log (pubblici) non si scrivono mai gli indirizzi.
    log.info("Email inviata (%d avvisi, %d destinatari)", len(new), len(recipients))


# --- Costruzione di interpelli.json --------------------------------------


def iso(date: datetime) -> str:
    return date.astimezone(timezone.utc).isoformat(timespec="seconds")


def build_records(
    entries: list[Entry],
    previous: list[dict[str, Any]],
    new_links: set[str],
    now: datetime,
) -> list[dict[str, Any]]:
    """Unisce feed e storico, ordina per data decrescente e calcola `isNew`.

    `firstSeen` è il momento in cui l'avviso è comparso per la prima volta;
    resta null per gli avvisi presenti già alla prima esecuzione (baseline).
    `isNew` è true se l'avviso è stato visto per la prima volta nelle ultime 24 ore,
    così il badge non sparisce dopo pochi minuti.
    """
    merged: dict[str, dict[str, Any]] = {r["link"]: dict(r) for r in previous}
    for e in entries:
        old = merged.get(e.link, {})
        if e.date is not None:
            date = iso(e.date)
        else:
            date = old.get("date") or iso(now)
        first_seen = old.get("firstSeen")
        if e.link not in merged and e.link in new_links:
            first_seen = iso(now)
        merged[e.link] = {
            "title": e.title,
            "link": e.link,
            "date": date,
            "codes": list(e.codes),
            "firstSeen": first_seen,
        }

    records = sorted(merged.values(), key=lambda r: str(r.get("date", "")), reverse=True)
    records = records[:MAX_ITEMS]
    for r in records:
        r["isNew"] = _is_recent(r.get("firstSeen"), now)
        r.setdefault("codes", [])
        r.setdefault("firstSeen", None)
    return records


def _is_recent(first_seen: Any, now: datetime) -> bool:
    if not first_seen:
        return False
    try:
        return now - datetime.fromisoformat(str(first_seen)) < NEW_WINDOW
    except ValueError:
        return False


# --- Programma principale -------------------------------------------------


def run() -> None:
    now = datetime.now(timezone.utc)
    entries = load_entries()
    log.info("Feed letto: %d avvisi", len(entries))

    seen = load_seen()
    first_run = seen is None
    seen_list = seen or []
    seen_set = set(seen_list)

    if first_run:
        new: list[Entry] = []
        log.info("Prima esecuzione: salvo lo stato di partenza senza inviare email")
    else:
        new = [e for e in entries if e.link not in seen_set]
        log.info("Nuovi avvisi: %d", len(new))

    # 1) Email: se fallisce si esce con errore SENZA toccare lo stato.
    if new:
        send_email(new)

    # 2) Stato aggiornato solo dopo l'invio riuscito (prima di tutto il resto,
    #    così un errore successivo non provoca email duplicate).
    updated_seen = seen_list + [e.link for e in entries if e.link not in seen_set]
    if first_run or new:
        write_json_atomic(SEEN_PATH, updated_seen[-MAX_SEEN:])

    # 3) Dati per la dashboard.
    records = build_records(entries, load_previous_records(), {e.link for e in new}, now)
    write_json_atomic(OUTPUT_PATH, records)
    log.info("Scritti %d avvisi in %s", len(records), OUTPUT_PATH.name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run()
    except CheckError as exc:
        log.error("%s", exc)
        return 1
    except Exception:  # noqa: BLE001 - qualsiasi imprevisto deve far fallire il job
        log.exception("Errore imprevisto")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
