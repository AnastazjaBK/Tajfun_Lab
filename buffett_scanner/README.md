# Buffett Opportunity Scanner — Faza 0

Fundament pipeline'u. Pełny projekt: `docs/buffett-scanner-design-review.md`
(sekcja 15, Faza 0). Ten katalog implementuje wyłącznie: config loader,
schemat bazy (`companies`, `ticker_history`, `price_daily`, `users`),
ingest uniwersum S&P 500 i cen dla próbki tickerów, decline scanner.
Bez UI, bez auth, bez scoringu, bez LLM — to przychodzi w kolejnych fazach.

## Instalacja

```bash
pip install -r requirements.txt
```

## Klucz API

Ustaw `FMP_API_KEY` jako zmienną środowiskową (np. w lokalnym `.env`,
który jest w `.gitignore` — nigdy nie trafia do repo). Do uruchomień na
GitHub Actions: repository secret o tej samej nazwie.

## Zanim zaufasz danym z FMP

Ścieżki endpointów w `providers/fmp.py` są oparte na ogólnie znanej
strukturze API FMP, nie na bezpośrednio zweryfikowanej dokumentacji
(patrz komentarz na górze tego pliku i sekcja "FINAL PRE-IMPLEMENTATION
STATUS" w design review). Zanim zaczniesz cokolwiek ingestować na
poważnie, uruchom raz:

```bash
python -m buffett_scanner.providers.fmp_smoketest
```

i sprawdź, czy wypisany kształt odpowiedzi zgadza się z tym, czego
oczekuje kod (pola `symbol`, `name`, `cik`, `sector`, `subSector` dla
uniwersum; `cik`, `companyName`, `sector`, `industry` dla profilu;
`date`, `open/high/low/close`, `adjClose`, `volume` dla cen historycznych).

## Użycie

```bash
python -m buffett_scanner.cli init-db
python -m buffett_scanner.cli ingest-universe
python -m buffett_scanner.cli ingest-prices AAPL MSFT KO --days 400
python -m buffett_scanner.cli scan AAPL MSFT KO
```

Domyślna baza: `buffett_scanner.db` w katalogu roboczym (SQLite, w
`.gitignore`). Zmień ścieżkę flagą `--db`.

## Testy

```bash
pytest                    # jednostkowe, bez sieci i bez klucza API
pytest -m integration      # dodatkowo: 1 realne wywołanie FMP (wymaga FMP_API_KEY)
```

## Świadomie NIE ma tu (patrz plan implementacji, kolejne fazy)

Pre-filtra ilościowego, integracji z SEC EDGAR, wywołań Claude API,
scoringu, watchlisty, MY HOLDINGS, modułu BIOTECH, dashboardu,
automatyzacji na GitHub Actions. Każde z nich ma swoją fazę w
`docs/buffett-scanner-design-review.md`.
