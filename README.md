# Portfolio-Agent

Ein selbst gehostetes Dashboard, das dein **Interactive-Brokers-Depot** (IBKR) mit KI auswertet: tägliche
Positionsanalyse mit Kauf-/Halten-/Verkaufs-Empfehlungen, Unternehmensanalysen per ISIN, Markt-Scans,
Portfolio-Risikoansicht, Terminkalender und Datenbank-Backup – alles lokal im Docker-Container.

> **Haftungsausschluss:** Dies ist ein Hobby-/Forschungsprojekt und **keine Anlageberatung**. KI-Einschätzungen
> können falsch, veraltet oder erfunden sein. Das Projekt kann echte Orders auslösen – nutze zuerst den
> Dry-Run-Modus (Standard) bzw. ein Paper-Trading-Konto und prüfe jede Order selbst. Nutzung auf eigenes Risiko.

## Funktionen

| Bereich | Was es kann |
|---|---|
| **Run** | Holt Positionen und ein Jahr Tageskurse von IBKR, berechnet Kennzahlen (Rendite, Volatilität, Abstand zum 52-Wochen-Hoch), lässt die KI jede Position bewerten und fasst das Depot zusammen. |
| **Aktionen & Orders** | Empfehlungen müssen freigegeben werden. Die Stückzahl wird aus Depotwert, Risiko-Limit, Positionslimit und Cash berechnet (Vorschau + nur Verringern erlaubt), Tageslimit für Orders, Dry-Run als Standard. |
| **Analyse (ISIN)** | Vollständige Unternehmensanalyse: News, Marktkapitalisierung, Führungswechsel, Berichte, Finanzlage, Wettbewerb, Katalysatoren, Risiken und ein **Ausblick für 1–3 / 3–6 / 6–12 Monate** mit Pfeilen. Quellenlinks (nur belegte), Vergleich mit der letzten Analyse, Zwei-Unternehmen-Vergleich, **PDF-Report**. |
| **Markt-Scan** | Universum-Analyse, KI-Discovery (Megatrends → Kandidaten) und Pennystock-Suche; Ergebnisse bleiben über Neustarts erhalten. |
| **Portfolio-Sicht** | Verteilung (Branche/Währung/Land), Konzentration, Volatilität, Beta, Korrelationen, Verlauf vs. Benchmark, Stresstest, Gebühren. |
| **Kalender** | Termine aus Analysen (Zahlen, Hauptversammlung, Dividenden-Ex-Tag) und manuell, Export als `.ics`. |
| **Backup** | Tägliche automatische Sicherung, Download, Import mit Prüfung und automatischer Sicherung vor dem Einspielen. |
| **Kennungen** | ISIN (mit Prüfsumme), WKN (bei deutschen ISINs) und IBKR-conId an Positionen, Orders und Watchlist. |

## Schnellstart (Docker)

Voraussetzungen: Docker + Docker Compose, IBKR **Trader Workstation oder IB Gateway** auf dem Host mit
aktivierter API (*Konfiguration → API → Einstellungen → „ActiveX- und Socket-Clients aktivieren"*; Port
7497 = Paper, 7496 = Live; die Docker-Adresse ggf. unter „Trusted IPs" eintragen).

```bash
git clone https://github.com/DerFips/IBKR_Portfolioagent.git && cd IBKR_Portfolioagent
cp .env.example .env
# DASHBOARD_PASSWORD in .env setzen (Pflicht!), dann:
docker compose up -d --build
```

Dashboard: <http://127.0.0.1:8888> – Benutzername beliebig, Passwort = `DASHBOARD_PASSWORD`.
Danach unter **Einstellungen → KI-Modell** einen KI-Provider wählen und mit „Verbindung testen" prüfen.

Ohne gesetztes Passwort ist das Dashboard bewusst gesperrt.

## KI-Provider

Eingestellt wird alles im Dashboard (*Einstellungen → KI-Modell*); es werden nur die Felder des gewählten Providers angezeigt.

| Provider | Eignung | Live-Daten für die Unternehmensanalyse |
|---|---|---|
| **Claude** (Anthropic API) | Beste Qualität, garantiert gültiges JSON | Ja – eigene Websuche (kostet API-Guthaben) |
| **NVIDIA NIM** ([build.nvidia.com](https://build.nvidia.com)) | OpenAI-kompatibel; welche Modelle dein Konto nutzen darf, siehe `GET /v1/models` | Nur mit Tavily-Key |
| **Ollama** (lokal) | Kostenlos, offline, Qualität modellabhängig | Nur mit Tavily-Key |
| **Hermes Agent** ([Nous Research](https://hermes-agent.nousresearch.com)) | Agent mit eigenen Tools über dessen API-Server | Ja, wenn Hermes Web-Tools hat |
| **Tavily** ([tavily.com](https://tavily.com)) | Websuche für Ollama/NVIDIA | – |

**Hermes einrichten:** In `~/.hermes/.env` `API_SERVER_ENABLED=true` und `API_SERVER_KEY=<Zufallswert>` setzen,
`hermes gateway restart`, dann in der App `HERMES_BASE_URL=http://host.docker.internal:8642/v1` und denselben Key eintragen.
Port **8642** ist der API-Server, 9119 ist nur das Hermes-Dashboard. Der Hermes-API-Server hat Terminalzugriff –
nur lokal binden und die Werkzeuge einschränken.

Hinweis: Der gewählte Provider gilt für die gesamte App (Positionsanalyse, Scans, Unternehmensanalyse).

## Konfiguration

Alle Werte stehen in `.env` (Vorlage: [`.env.example`](.env.example)) und sind – außer `DASHBOARD_PASSWORD` für den
Erststart – auch im Dashboard änderbar. Dort gespeicherte Werte haben Vorrang und überleben Neustarts.

| Variable | Standard | Bedeutung |
|---|---|---|
| `DASHBOARD_PASSWORD` | – | **Pflicht.** Zugangspasswort (HTTP-Basic) |
| `LLM_PROVIDER` | `ollama` | `ollama`, `anthropic`, `nvidia`, `hermes` |
| `IBKR_HOST` / `IBKR_PORT` / `IBKR_CLIENT_ID` | `host.docker.internal` / `7497` / `1` | TWS/Gateway-Verbindung |
| `IBKR_DRY_RUN` | `true` | `true` = Orders nur simulieren. **`false` = echte Orders!** |
| `MAX_POSITION_PCT` | `10` | Maximales Gewicht einer Position in % |
| `MAX_RISK_PCT_PER_TRADE` / `STOP_LOSS_PCT` | `1` / `10` | Stückzahl = Depot × Risiko % ÷ Stopp % (begrenzt durch Positionslimit und Cash) |
| `MAX_DAILY_TRADES` | `5` | Orders pro Tag (Dry-Run zählt mit) |
| `MIN_CONFIDENCE` | `0.65` | Aktionen darunter werden blockiert |
| `BENCHMARK_SYMBOL` | `SPY` | Vergleichs-ETF; leer = aus |
| `AGENT_SCHEDULE_ENABLED` / `AGENT_RUN_*` | `false` / `17:05`, `mon-fri` | Automatische Runs (opt-in) |
| `BACKUP_ENABLED` / `BACKUP_HOUR` / `BACKUP_KEEP` | `true` / `3` / `14` | Tägliche automatische DB-Sicherung |
| `SETTINGS_ENCRYPTION_KEY` | automatisch | Schlüssel für verschlüsselte Einstellungen (sonst `data/.settings.key`) |

Weitere Schlüssel (Modelle, Timeouts, URLs) siehe `.env.example` und `src/agent/settings.py`.
Die Felder für Telegram, E-Mail und Nextcloud sind **vorbereitet, aber noch nicht implementiert**.

## Daten & Backup

Alles liegt im Ordner `./data` (Docker-Volume): `portfolio.db` (SQLite), `backups/`, `.settings.key`.

- **API-Keys und Passwort** werden verschlüsselt in der Datenbank gespeichert. Der Schlüssel (`.settings.key`)
  ist **nicht** Teil von Backups – sichere ihn getrennt. Nach einem Import auf einem anderen Rechner Keys neu eintragen.
- **Import** ersetzt die gesamte Datenbank. Die Datei wird geprüft (Integrität, nur bekannte Tabellen, keine Trigger/Views),
  vorher wird automatisch eine Sicherung angelegt.

## Sicherheit

- Alle Routen hinter Passwortschutz (konstante Zeit, Sperre nach 5 Fehlversuchen/5 min), CSRF-Schutz über Origin-Prüfung,
  Sicherheits-Header, API-Dokumentation deaktiviert.
- Der Port ist standardmäßig nur an `127.0.0.1` gebunden. Für Fernzugriff einen **Reverse-Proxy mit HTTPS** davorschalten –
  Basic-Auth überträgt das Passwort sonst im Klartext.
- KI-Texte und Webinhalte werden als nicht vertrauenswürdig behandelt (Escaping im Dashboard, Link-Prüfung,
  Prompt-Injection-Hinweise). Das ersetzt kein Sandboxing: Ein KI-Agent mit Werkzeugen (Hermes) sollte eingeschränkt laufen.
- Container läuft ohne root, ohne zusätzliche Capabilities.
- Sicherheitslücken bitte nicht öffentlich als Issue melden, sondern per privater Nachricht an die Maintainer.

## Entwicklung

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                                   # Tests (isolierte Temp-DB, kein Netzwerk)
DASHBOARD_HOST=127.0.0.1 DASHBOARD_PASSWORD=dev DB_PATH=/tmp/pa-dev.db python -m src.agent   # http://127.0.0.1:8888
```

```
src/agent/
├── api/            FastAPI-App, Router, Zugriffsschutz, Dashboard (static/)
├── analysis/       Positionsanalyse, Unternehmensanalyse, Websuche, PDF-Report
├── analytics/      Kennzahlen (Rendite, Volatilität, Beta, Korrelation)
├── db/             SQLAlchemy-Modelle und Repository
├── ibkr/           IBKR-Client (ib_insync, eigene Threads)
├── llm.py          Provider-Schicht: Ollama, Claude, NVIDIA, Hermes
├── risk.py         Ordergröße   ·  backup.py  Sicherung/Import   ·  secrets.py  Verschlüsselung
└── scheduler.py    optionaler Zeitplan für Runs
tests/              pytest
```

CI (GitHub Actions) führt Tests, JavaScript-Syntaxprüfung und einen Docker-Build aus.

## Bekannte Grenzen

- Die IBKR-Anbindung (Kurshistorie, Branchen, ISIN-Abfrage, Orders) ist nur gegen Simulationen getestet – bitte zuerst mit Paper-Trading ausprobieren.
- Für die Kurshistorie braucht IBKR ein passendes Marktdaten-Abo; fehlt es, laufen Runs ohne Kennzahlen weiter.
- Der Verlauf „Depot vs. Benchmark" ist hypothetisch (heutige Bestände rückgerechnet).
- Dividenden, Steuer-Export und Benachrichtigungen (Telegram/E-Mail) sind nicht implementiert.

## Lizenz

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-only).

Kurz: Du darfst das Projekt frei nutzen, verändern und weitergeben. Veränderte Versionen müssen unter derselben
Lizenz stehen. Wichtig bei AGPL (§ 13): Wenn du eine **veränderte Version** als Netzwerkdienst für andere Nutzer
betreibst, musst du diesen Nutzern den Quelltext deiner Version zugänglich machen (z. B. ein Link im Dashboard
auf dein Repository). Für den rein privaten Eigengebrauch ändert sich dadurch nichts.
