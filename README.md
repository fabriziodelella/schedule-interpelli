# Monitor interpelli ATP Roma

Controlla ogni ~10 minuti il feed RSS degli interpelli per supplenze docenti di ATP Roma
(<https://www.atpromaistruzione.it/atp/tag/interpelli/feed/>), invia **una sola email riepilogativa**
quando compaiono nuovi avvisi e pubblica una dashboard web per consultarli.

- **`check.py`** – script Python 3.12 eseguito da GitHub Actions: legge il feed, confronta con `data/seen.json`,
  invia l'email (Gmail) e aggiorna `data/seen.json` e `public/interpelli.json`.
- **`.github/workflows/check.yml`** – esegue `check.py` ogni 10 minuti e committa i dati se cambiati.
- **`web/`** – dashboard React (Vite + TypeScript) che legge `public/interpelli.json` direttamente da
  `raw.githubusercontent.com`: i dati si aggiornano senza rifare il deploy.
- **`.github/workflows/deploy.yml`** – pubblica la dashboard su GitHub Pages quando cambia `web/**`.

Nell'email vengono messi in evidenza (in cima) gli avvisi con i codici **ADEE, ADAA, ADMM, ADSS** nel titolo,
ma vengono comunque inviati tutti i nuovi avvisi.

## Istruzioni passo-passo

### 1. Creare il repository pubblico
1. Su GitHub: **New repository** → nome (es. `schedule-interpelli`) → visibilità **Public** → crealo
   **vuoto** (senza README, `.gitignore` o licenza).
2. Il branch principale deve chiamarsi `main`.

### 2. Push del progetto
Dalla cartella del progetto:

```bash
git init -b main
git add .
git commit -m "Primo commit"
git remote add origin https://github.com/<TUO_UTENTE>/<NOME_REPO>.git
git push -u origin main
```

> Se cambi nome al repository, nessuna modifica al codice è necessaria: owner e nome vengono letti
> automaticamente dal workflow di deploy.

### 3. Creare la password per app Gmail
Serve l'account Gmail **mittente** delle email.
1. Attiva la **verifica in due passaggi**: <https://myaccount.google.com/security>.
2. Vai su <https://myaccount.google.com/apppasswords>, crea una password per app (nome a piacere,
   es. "Interpelli") e copia il codice di 16 caratteri (gli spazi sono ininfluenti).

### 4. Impostare i Secrets
Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret      | Valore                                                                  |
|-------------|-------------------------------------------------------------------------|
| `SMTP_USER` | indirizzo Gmail mittente                                                |
| `SMTP_PASS` | password per app Gmail creata al punto 3                                |
| `MAIL_TO`   | uno o più indirizzi destinatari, separati da virgola                    |

Gli indirizzi sono solo nei Secrets: non compaiono nel codice né nei log del workflow.

### 5. Abilitare GitHub Pages
Repository → **Settings → Pages → Build and deployment → Source: GitHub Actions**.

### 6. Primo run manuale
1. **Actions → Controllo interpelli → Run workflow** (branch `main`).
   Alla prima esecuzione `data/seen.json` non esiste: lo stato viene salvato **senza inviare email** e
   viene generato `public/interpelli.json`. Il workflow committa i due file.
2. **Actions → Deploy dashboard → Run workflow** per la prima pubblicazione della dashboard
   (le volte successive parte da solo quando cambia qualcosa in `web/`).
3. La dashboard sarà su `https://<TUO_UTENTE>.github.io/<NOME_REPO>/`.

### 7. Testare l'invio dell'email
1. Apri `data/seen.json` su GitHub (icona matita) e **rimuovi uno o due link** dalla lista; salva il commit.
2. Lancia di nuovo **Controllo interpelli** manualmente: gli avvisi rimossi risultano "nuovi" e arriva
   un'email con oggetto `N nuovi interpelli ATP Roma`.
3. Se l'invio fallisce il job risulta rosso e `seen.json` non viene aggiornato: al giro successivo
   si riprova, nessun avviso va perso.

## Configurazione della dashboard (sviluppo locale)
La dashboard legge i dati da:

```
https://raw.githubusercontent.com/<VITE_GH_OWNER>/<VITE_GH_REPO>/main/public/interpelli.json
```

| Variabile        | Default (solo sviluppo locale) | Nel deploy su Pages                    |
|------------------|--------------------------------|----------------------------------------|
| `VITE_GH_OWNER`  | `tuo-utente-github`            | impostata dal workflow (proprietario)  |
| `VITE_GH_REPO`   | `schedule-interpelli`          | impostata dal workflow (nome repo)     |

Anche il `base` di Vite (`/<repo>/`) usa `VITE_GH_REPO`. Per provarla in locale:

```bash
cd web
npm install
VITE_GH_OWNER=tuo-utente VITE_GH_REPO=nome-repo npm run dev
```

(su PowerShell: `$env:VITE_GH_OWNER="tuo-utente"; $env:VITE_GH_REPO="nome-repo"; npm run dev`)

## Esecuzione locale di `check.py` (opzionale)

```bash
pip install -r requirements.txt
python check.py                      # senza variabili: va bene finché non ci sono nuovi avvisi
SMTP_USER=... SMTP_PASS=... MAIL_TO=... python check.py
```

## Note su `isNew`
In `public/interpelli.json` il flag `isNew` è `true` per gli avvisi visti per la prima volta nelle
**ultime 24 ore** (campo `firstSeen`); gli avvisi già presenti alla prima esecuzione non sono mai "nuovi".

## Limiti noti
- **Ritardi del cron**: GitHub Actions non garantisce la puntualità dei workflow schedulati; sotto carico
  l'avvio può slittare di diversi minuti (e a volte qualche esecuzione viene saltata).
- **Sospensione dopo 60 giorni**: nei repository pubblici GitHub disattiva i workflow schedulati dopo
  60 giorni senza attività. Finché ci sono nuovi avvisi i commit del bot contano come attività; se il
  feed resta fermo a lungo, riattiva il workflow da **Actions** (o fai un commit qualsiasi).
- **Cache di raw.githubusercontent.com**: la dashboard può mostrare dati vecchi fino a ~5 minuti.
- **Storico**: il feed espone solo pochi avvisi; `interpelli.json` accumula fino a 100 avvisi a partire
  dalla prima esecuzione.
- **Repository pubblico**: log, dati e commit sono visibili a tutti; per questo nei log non compaiono
  mai gli indirizzi email.
