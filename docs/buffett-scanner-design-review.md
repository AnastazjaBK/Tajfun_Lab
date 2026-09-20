# BUFFETT OPPORTUNITY SCANNER — Technical Design Review

**Status:** v1.3 — w pełni scalona wersja, po decyzjach właściciela wobec D1–D15. Ten plik jest samodzielny — nie wymaga sięgania do historii commitów. Implementacja NIE została rozpoczęta.
**Data:** 2026-09-20 (v1.0–v1.3, wszystkie tego samego dnia)
**Zmiana względem v1.0:** (1) BLOCKER 3, 4, 5 przeszły w status rozwiązany na poziomie decyzji architektonicznej; (2) BLOCKER 1 i 2 pozostają otwarte, ale z konkretnymi, zweryfikowanymi ścieżkami rozwiązania; (3) dodano projekt modułu MY HOLDINGS / EXIT MONITORING; (4) poprawiono identyfikację spółek w schemacie DB (CIK zamiast tickera).
**Zmiana w v1.2:** dodano projekt modułu BIOTECH: EXTERNAL VALIDATION & RESEARCH NETWORK (sekcja 18) jako jedną warstwę przyszłego pełnego modelu biotech.
**Zmiana w v1.3:** zamknięto decyzje D2, D4–D14 zgodnie z odpowiedziami właściciela (patrz sekcja DECISIONS); D1 i D3 pozostają w toku technicznej weryfikacji dostawców, z regułą wyboru już ustaloną przez właściciela; D15 rozstrzygnięte na rzecz nowej kolejności priorytetów — **BIOTECH ma wyższy priorytet niż pełne rozszerzenie BANK/INSURER/REIT**, plan implementacji (sekcja 15) i zakres modułu biotech (sekcja 18) zaktualizowane odpowiednio; dodano rejestr pełnego docelowego zakresu BIOTECH MODULE (Clinical Pipeline, Trial Quality, PoS jako zakres a nie punkt, Cash Runway, Dilution Risk, Catalyst Calendar, rNPV, biotech-specific Thesis Monitoring, integracja z MY HOLDINGS) jako scope do zaprojektowania w osobnej, przyszłej turze (nowa Faza 8 — DESIGN) — External Validation pozostaje tylko jedną z jego warstw.

## Metodologia i zastrzeżenia

Zgodnie z zasadą „nie zgaduj": poniżej rozróżniam trzy kategorie treści.

- **Ustalone z dokumentacji/wiedzy technicznej** — np. architektura, schematy, zasady SEC EDGAR (limit 10 req/s, brak wymogu klucza API), aktualny cennik Claude API.
- **Zweryfikowane wyszukiwaniem w sieci we wrześniu 2026, ale zmienne w czasie** — cenniki dostawców danych finansowych. Oznaczone wprost jako „do potwierdzenia na stronie dostawcy przed zatwierdzeniem budżetu" wraz ze źródłem.
- **Hipotezy wymagające Twojej decyzji lub kalibracji przez backtesting** — oznaczone `UNCALIBRATED` / w sekcji „DECISIONS REQUIRED FROM OWNER".

Żadna liczba finansowa, próg ani cennik w tym dokumencie nie jest fabrykowany — tam, gdzie nie mam pewności, piszę to wprost zamiast dopowiadać. W tej turze dodatkowo natrafiłem na **sprzeczne informacje między dwoma źródłami tego samego dostawcy** (EODHD — zakres historyczny „Historical Constituents") — opisuję to wprost jako DATA CONFLICT do wyjaśnienia, zamiast wybierać wersję, która wygląda korzystniej.

---

## 1. Architektura V0 — schemat przepływu danych

```
[Config: universe.yaml, scoring.yaml, gates.yaml, holdings.yaml]
            │
            ▼
[Scheduler]  (GitHub Actions scheduled workflow)
            │  uruchamia daily_run.py raz dziennie, po zamknięciu rynku
            ▼
[1. Market Data Ingestion] → [2. Decline Scanner] → [3. Fundamentals Ingestion]
            │                                              │
            ▼                                              ▼
[4. Quantitative Pre-filter]                    [4b. Holdings Deterministic
     (całe uniwersum 503)                         Monitor — TYLKO spółki
            │                                      z otwartą pozycją,
            ▼                                      niezależnie od wyniku
[5. Candidate shortlist]                           pre-filtra/decline-scannera]
     (~5–15 spółek/dzień)                                    │
            │                                                ▼
            │                                    [4c. Exit-trigger check
            │                                      (deterministyczny) —
            │                                      czy warunek do pełnej
            │                                      reanalizy jakościowej?]
            │                                                │
            ▼                                     NIE ────────┴──── TAK
[6. Source Assembly]  ←──────────────────────────────────────┘
     (SEC EDGAR + allowlista IR, WYŁĄCZNIE realnie pobrane
      i zweryfikowane dokumenty — patrz pkt 9)
            │
            ▼
[7. Claude API — Qualitative Research / Exit Review]
     (kandydaci z kroku 5: pełna analiza wg schematu z pkt 8;
      pozycje z kroku 4c: analiza porównawcza wg schematu Exit Review — pkt 16)
     wejście: deterministyczne wskaźniki + WYŁĄCZNIE dostarczone źródła
     wyjście: JSON walidowany, malformed → reject
            ▼
[8. Scoring Engine]  (bez zmian dla nowych kandydatów;
            │         dla holdings: dodatkowo porównanie do Purchase Thesis)
            ▼
[9. Database]  (SQLite w V0 → Postgres/Supabase w V1;
     nowe tabele: positions, purchase_transactions, sale_transactions,
     purchase_thesis, exit_review_triggers, exit_review_reports,
     holding_user_actions — patrz pkt 16)
            │
            ▼
[10. Daily report]  → sekcja standardowa (nowi kandydaci)
            │        + sekcja MY HOLDINGS (jeśli jakiś EXIT REVIEW REQUIRED)
            ▼
          [User]
```

Kluczowa zasada architektoniczna: **LLM nigdy nie jest wejściem do kroku 1–4 i 8** — tam wyłącznie deterministyczny kod. LLM wchodzi dopiero po redukcji zbioru przez tani filtr ilościowy (realizacja §35 spec).

Kluczowa zmiana wynikająca z MY HOLDINGS: **posiadane pozycje NIE przechodzą przez decline-scanner/pre-filter jako bramkę wejścia do LLM.** Wymóg „+40% nie oznacza automatycznie SELL, system musi badać aktualną wartość biznesu" oznacza, że monitoring pozycji musi działać niezależnie od tego, czy cena akurat spadła. Dodano więc osobną, równoległą ścieżkę (4b/4c) z własną, tańszą bramką deterministyczną, zamiast budowania drugiego niezależnego systemu analitycznego — holding monitoring korzysta z istniejącego pipeline'u (Source Assembly Layer, silnik scoringu), nie duplikuje go.

---

## 2. Rekomendowany stack technologiczny

Kryterium: prosty, tani, **obsługiwalny przez osobę nietechniczną** (bez administrowania serwerem, z czytelnym UI tam gdzie to możliwe).

| Warstwa | Rekomendacja | Uzasadnienie |
|---|---|---|
| Język pipeline'u | Python 3.11+ (pandas, pydantic, httpx) | Standard w analizie danych finansowych, łatwy do utrzymania/rozszerzania przez Claude Code |
| Konfiguracja | YAML, walidowany pydantic-modelami | Czytelny dla człowieka, jedno źródło prawdy dla progów |
| Baza danych V0 | SQLite (plik) | Zero administracji, wystarcza do dowiedzenia działania silnika |
| Baza danych V1+ | Postgres zarządzany (Supabase lub Neon) | Darmowy tier wystarczający na lata dziennych analiz jednego użytkownika; Supabase ma graficzny UI do przeglądania tabel bez SQL — istotne dla „osoby nietechnicznej" |
| Scheduler | GitHub Actions (scheduled workflow) | Zero administracji serwera, sekrety w GitHub Secrets, logi w UI GitHub, mieści się w darmowych minutach dla repo tej skali |
| Dashboard V1 | Streamlit (Community Cloud) | Czysty Python, brak potrzeby osobnego frontendu; darmowy hosting |
| Sekrety | Zmienne środowiskowe / GitHub Secrets / Supabase secrets | Zgodnie z §34 — nigdy w kodzie |
| Monitoring błędów | Opcjonalnie Sentry (darmowy tier) | Widoczność awarii bez logowania się na serwer |

Świadomie **odradzam** na start: Kubernetes/Docker Swarm, własny VPS z ręcznym cronem, framework frontendowy (React/Next.js) do dashboardu — wszystko to podnosi koszt utrzymania bez korzyści przy wolumenie „1 użytkownik, 1 uruchomienie dziennie".

---

## 3. Porównanie dostawców danych finansowych

Trzej kandydaci sprawdzeni pod kątem wymagań specyfikacji (ceny EOD, fundamenty wieloletnie, sektor/branża, dywidendy, liczba akcji w obrocie). **Żaden z nich nie zastępuje SEC EDGAR jako źródła pierwotnego** — to osobna, obowiązkowa warstwa (patrz pkt 9).

| Dostawca | Mocne strony wg specyfikacji | Czego NIE zapewnia z wymagań spec |
|---|---|---|
| **Financial Modeling Prep (FMP)** | Szeroki zakres fundamentów (>30 lat, wielu rynków), EOD, dane sektorowe, ratingi. Darmowy tier: 250 wywołań/dzień (za mało na pełne 503 spółki dziennie — potrzebny płatny plan). | Brak bezpośrednich linków do konkretnych stron/sekcji filingów SEC; **potwierdzone researchem:** to API „aktualnego widoku" — zwraca najnowsze, skorygowane dane, a nie stan wiedzy z danej historycznej daty (egzekwowanie point-in-time to praca dobudowywana samodzielnie, nie funkcja dostawcy — patrz BLOCKER 1); dane analityczne/estymaty zwykle w droższym tier. |
| **EODHD (EOD Historical Data)** | Podobny zakres do FMP (60+ giełd, 150k+ tickerów), osobny pakiet „Fundamentals Data Feed", relatywnie tańszy przy porównywalnym zakresie. Dodatkowo oferuje osobny, płatny produkt **„Indices Historical Constituents Data API"** (marketplace, dane od S&P Global przez UnicornBay) — potencjalne rozwiązanie BLOCKER 2. | Te same braki co FMP co do linkowania fragmentów i natywnego PIT. Dodatkowo: **dwa źródła EODHD podają sprzeczny zakres historyczny** dla produktu Historical Constituents (jedno: „survivorship-bias-free reliable from April 2012", drugie: „ponad 20 lat, dane od stycznia 2000") — DATA CONFLICT do wyjaśnienia bezpośrednio w dokumentacji/z supportem przed zakupem, cena dodatku nieznana. |
| **Polygon.io (od X 2025 rebrand na „Massive")** | Bardzo dobra jakość danych cenowych/wolumenowych, WebSockety, długa historia cen w wyższych planach. | Historycznie słabszy zakres fundamentów finansowych względem FMP/EODHD (do zweryfikowania po rebrandzie — cennik i oferta były w trakcie zmiany w momencie tego przeglądu); może wymagać sparowania z drugim dostawcą tylko dla fundamentów, co podnosi koszt i złożoność integracji. Przewaga real-time nie jest potrzebna — pipeline działa raz dziennie po zamknięciu rynku. |

**Rekomendacja:** jeden dostawca (FMP lub EODHD — porównywalny zakres) do cen EOD + fundamentów, plus SEC EDGAR (darmowe) jako obowiązkowa warstwa źródeł pierwotnych. Nie rekomenduję Polygon/Massive na start. Przy wyborze między FMP a EODHD dodatkowym kryterium jest teraz to, który oferuje bardziej wiarygodny i aktualny produkt historical-constituents (patrz Decyzja D3) — to może przechylić wybór na korzyść EODHD, o ile sprzeczność w jego dokumentacji rozstrzygnie się korzystnie. Ostateczny wybór dostawcy — patrz Decyzja D1.

---

## 4. Szacunkowe koszty miesięczne

Wszystkie kwoty poniżej to **rząd wielkości**, nie oferta handlowa — źródła podane, ale cenniki dostawców danych zmieniają się często (patrz przypis o rebrandzie Polygon/Massive w pkt 3 jako dowód na to ryzyko).

| Pozycja | Szacunek | Uzasadnienie |
|---|---|---|
| Financial Data API (FMP lub EODHD, plan średni) | **~50–100 USD/mies.** | FMP: plany „Starter"/„Premium" (dokładne kwoty niedostępne w wynikach wyszukiwania — do sprawdzenia na stronie); EODHD: „Fundamentals Data Feed" ok. 60 USD/mies., „All-in-One" ok. 100 USD/mies. wg strony eodhd.com/pricing (wrzesień 2026). |
| Claude API (Sonnet 5) | **~20–80 USD/mies.** | Ceny oficjalne: 2 USD/MTok wejście, 10 USD/MTok wyjście (Sonnet 5). Przy pre-filtrze redukującym 503 spółki do ~5–15 pełnych analiz/dzień, przy ~20–35k tokenów wejścia (kontekst źródłowy) i ~2–4k tokenów wyjścia na analizę: koszt jednej analizy ≈ 0,06–0,15 USD. 15 analiz/dzień × 30 dni ≈ 450 analiz/mies. → **~30–70 USD/mies.** Zasadniczo znacznie taniej niż pełna analiza LLM 503 spółek dziennie (rząd wielkości 500–2000+ USD/mies.), co potwierdza zasadność wymogu pre-filtra z §35. |
| Hosting (scheduler + dashboard) | **0–7 USD/mies.** | GitHub Actions: darmowe minuty wystarczające dla 1 uruchomienia/dzień. Streamlit Community Cloud: darmowy tier. Ewentualnie mały Render/Fly.io jeśli dashboard wymaga czegoś więcej. |
| Baza danych | **0–25 USD/mies.** | Supabase/Neon darmowy tier (rzędu setek MB) — realistycznie wystarczy na lata danych jednego użytkownika (każda analiza to kilka–kilkanaście KB, nie duże blob-y). Płatny tier (~25 USD/mies.) dopiero przy realnym skalowaniu / wielu użytkownikach. |
| Inne (monitoring, domena) | **0–15 USD/mies.** | Sentry darmowy tier zwykle wystarczy; domena opcjonalna (~10–15 USD/rok, nie miesięcznie). |
| **MY HOLDINGS / Exit Review (dodatek)** | **~0–15 USD/mies.** | Przy typowej liczbie posiadanych pozycji inwestora indywidualnego (rząd wielkości kilku–kilkunastu spółek, nie setek) i trybie `TRIGGER_GATED` (patrz Decyzja D13) — koszt dodatkowych wywołań Claude API do Exit Review jest marginalny. Przy trybie „pełna analiza codziennie dla każdej pozycji" koszt rósłby liniowo z liczbą pozycji — stąd rekomendacja trybu trigger-gated. |
| **RAZEM (orientacyjnie)** | **~70–215 USD/mies.** | Dolna granica przy tańszym dostawcy danych i darmowych tierach DB/hostingu; górna przy droższym planie danych + aktywny moduł holdingów. Ewentualny koszt płatnego dodatku EODHD do historical constituents jest nieznany i nieuwzględniony (patrz Decyzja D3) — wymaga osobnej wyceny. |

**Rekomendacja przed zatwierdzeniem budżetu:** sprawdzić aktualny cennik FMP/EODHD bezpośrednio na ich stronach (linki w Sources), bo dokładne kwoty planów płatnych nie były w pełni dostępne w wynikach wyszukiwania.

---

## 5. Database schema

### Identyfikacja spółek: CIK, nie ticker

**Przenośność SQLite → Postgres (Decyzja D5):** schema poniżej celowo używa wyłącznie typów i konstrukcji przenośnych między SQLite a Postgres (proste kolumny, `ENUM` realizowany jako `CHECK`/tekst w SQLite i natywny typ w Postgres, `JSON` jako tekst w SQLite i `jsonb` w Postgres) — migracja V0→V1 to zmiana silnika połączenia i ewentualnie typu kolumny JSON, nie przeprojektowanie modelu danych.

W trakcie researchu do BLOCKER 2 potwierdzone zostało realne ryzyko „ticker recycling" — po delistingu/fuzji ticker bywa **ponownie przypisywany zupełnie innej spółce** (udokumentowany przykład: `STI` należał do SunTrust Banks przed fuzją z Truist w 2019, potem został przypisany innej spółce). Przy kluczu głównym opartym na tickerze backtest lub — gorzej — **moduł MY HOLDINGS** mógłby po latach powiązać historyczną pozycję z zupełnie inną firmą. To nie jest tylko problem backtestingu — to również ryzyko integralności danych dla realnych posiadanych pozycji. Dlatego wszystkie tabele poniżej identyfikują spółki po `cik`, nie po `ticker`; ticker jest atrybutem zmiennym w czasie, wyświetlanym w UI, nigdy kluczem.

```sql
-- Uniwersum, tożsamość spółek i historia tickerów
companies(cik PK, name, sector, industry, sub_industry,
          sector_profile ENUM('GENERAL','BANK','INSURER','REIT','BIOTECH'),
          is_active BOOLEAN, created_at)
  -- BIOTECH jest tu jako wartość identyfikująca spółkę, ale w V0/V1
  -- spółki z sector_profile=BIOTECH są jawnie wykluczone ze standardowego
  -- scoringu (status NOT_YET_SUPPORTED w raporcie, nie cichy błąd) —
  -- dostają własny pipeline dopiero od Fazy 8/9 (sekcja 18), inaczej niż
  -- BANK/INSURER/REIT, które współdzielą silnik GENERAL z podmienionymi
  -- metrykami (Decyzja D7, D15)

ticker_history(id PK, cik FK, ticker, start_date, end_date NULL)
  -- ticker jako atrybut zmienny w czasie, nie tożsamość;
  -- end_date NULL = aktualnie obowiązujący ticker dla danego CIK

universe_membership(id PK, cik FK, index_name, start_date, end_date)
  -- point-in-time przynależność do indeksu, potrzebna do backtestingu (BLOCKER 2)

-- Dane rynkowe i fundamentalne (surowe, nienadpisywane)
price_daily(cik FK, date, open, high, low, close, adj_close, volume,
            source, ingested_at, PRIMARY KEY(cik, date))

fundamentals_raw(id PK, cik FK, fiscal_period, period_end_date, filed_date,
                 statement_type, line_item, value, unit, source, source_doc_id,
                 ingested_at)
  -- format długi (long), żeby korekty/restatements nie nadpisywały
  -- wartości "as reported"; filed_date krytyczne dla point-in-time (§13)

derived_metrics(id PK, cik FK, as_of_date, metric_name, value,
                 calc_version, inputs_hash)

-- Wersjonowanie modelu scoringu
scoring_model_versions(version PK, description, weights_json, gates_json,
                        effective_from, effective_to, created_at)

-- Wyniki analiz — IMMUTABLE, nowa wersja = nowy wiersz, nigdy UPDATE
analyses(analysis_id PK, cik FK, run_date, price_at_analysis,
         scoring_model_version FK, input_dataset_snapshot_id FK,
         business_quality_score, moat_score, financial_quality_score,
         management_score, safety_score, valuation_score, fear_score,
         dividend_score, total_score,
         hard_flags JSON, valuation_range_low, valuation_range_base,
         valuation_range_high, margin_of_safety_pct,
         fear_classification, fear_confidence,
         llm_model_id, llm_schema_version, llm_raw_output JSON,
         created_at)

-- Źródła — WYŁĄCZNIE realnie pobrane i zweryfikowane (content hash)
analysis_sources(source_id PK, analysis_id FK,
                  source_type ENUM('SEC_FILING','IR_DOC','PRESS_RELEASE',
                                    'EARNINGS_CALL','OTHER'),
                  title, issuer, doc_date, url, accession_number,
                  section, page, content_hash, verified BOOLEAN,
                  reason, question)

-- Watchlist
watchlist(watchlist_id PK, cik FK, added_date, added_price,
          current_status, last_analysis_id FK,
          next_review_trigger JSON, created_at, updated_at)

-- Decyzje użytkownika (workflow, NIE broker)
user_decisions(decision_id PK, cik FK, analysis_id FK NULL,
               status ENUM('WATCH','REJECT','SNOOZE','BOUGHT'),
               decided_at, note, snooze_until, snooze_trigger)

-- Reprodukowalność / audit trail
data_snapshots(snapshot_id PK, run_date, provider,
                provider_response_hash, raw_payload_ref)

run_log(run_id PK, run_date, universe_size, screened_count,
        declines_flagged, prefilter_passed, full_analyses_count,
        final_candidates_count, status ENUM('COMPLETE','PARTIAL','FAILED'),
        errors JSON)
```

### MY HOLDINGS / EXIT MONITORING — nowe tabele

```sql
-- Pozycja = jeden "round trip" posiadania danej spółki (pozwala odróżnić
-- ponowne wejście po pełnym zamknięciu pozycji jako osobną historię)
positions(position_id PK, cik FK, status ENUM('OPEN','CLOSED'),
          opened_at, closed_at NULL, created_at, updated_at)
  -- shares_held, total_cost, avg_price, current_value, unrealized_pl,
  -- realized_pl NIE są przechowywane jako mutowalne kolumny — liczone
  -- deterministycznie z transakcji przy każdym odczycie (patrz uzasadnienie
  -- niżej), żeby wykluczyć rozjazd między "cache" a źródłem prawdy

-- Transakcje — WYŁĄCZNIE INSERT, nigdy UPDATE/DELETE (audit trail)
purchase_transactions(transaction_id PK, position_id FK, purchase_date,
                       shares, price_per_share, total_invested, currency,
                       fees, note, superseded_by NULL, created_at)
sale_transactions(transaction_id PK, position_id FK, sale_date,
                   shares, sale_price, currency, fees, note,
                   cost_basis_method_used, superseded_by NULL, created_at)
  -- korekta pomyłki = nowy rekord + wskazanie superseded_by na starym,
  -- NIGDY nadpisanie — inaczej audit trail traci sens

-- PURCHASE THESIS — immutable snapshot w momencie BOUGHT
purchase_thesis(thesis_id PK, position_id FK UNIQUE, analysis_id FK,
                 snapshot_json JSON, created_at)
  -- analysis_id wskazuje na już-immutable wiersz w `analyses`;
  -- snapshot_json to DODATKOWO zdenormalizowana kopia kluczowych pól
  -- (total_score, component scores, intrinsic value range, MoS,
  --  fear_classification, bull_case, bear_case, thesis_invalidation,
  --  biggest_unknown, confidence, lista source_id) — żeby Purchase Thesis
  -- był czytelny i kompletny sam w sobie, niezależnie od przyszłych zmian
  -- schematu `analyses`

-- Triggery do ponownej oceny — TYLKO EXIT REVIEW REQUIRED, nigdy SELL
exit_review_triggers(trigger_id PK, position_id FK,
    trigger_type ENUM('THESIS_DETERIORATION','THESIS_INVALIDATION',
                       'STRUCTURAL_DETERIORATION','MOAT_DETERIORATION',
                       'FINANCIAL_SAFETY_DETERIORATION',
                       'MANAGEMENT_CAPITAL_ALLOCATION_CHANGE',
                       'DIVIDEND_DETERIORATION','VALUATION_REVIEW'),
    fired_at, triggering_analysis_id FK, reasoning, status ENUM('OPEN','ACKNOWLEDGED'),
    created_at)

exit_review_reports(report_id PK, trigger_id FK, position_id FK,
    generated_at, current_analysis_id FK,
    score_at_purchase, score_current, component_score_deltas JSON,
    intrinsic_value_at_purchase JSON, intrinsic_value_current JSON,
    mos_at_purchase, mos_current,
    what_changed, thesis_still_valid BOOLEAN, invalidation_conditions_met JSON,
    bull_case, bear_case, why_holding_may_still_be_rational,
    why_reassessment_is_required, biggest_unknown, confidence,
    sources JSON, verification_items JSON, created_at)
  -- immutable; NIGDY nie zawiera pola/rekomendacji "SELL"

holding_user_actions(action_id PK, position_id FK, exit_review_report_id FK NULL,
    action ENUM('HOLD','REDUCE','SOLD','REVIEW_LATER'),
    decided_at, note, review_later_until, review_later_trigger)
```

**Tabele modułu BIOTECH (External Validation & Research Network)** — `assets`, `trials`, `persons`, `institutions`, `trial_person_roles`, `trial_institution_roles`, `partnerships`, `funding_events`, `publications`, `publication_authors`, `publication_asset_links`, `conflicts_dependencies`, `external_validation_assessments` — są opisane osobno w pkt 18.2, żeby nie przeciążać tej sekcji; dotyczą wyłącznie spółek biotech i są projektowane, ale nieimplementowane w V0/V1 (patrz 18.0).

**Dlaczego pozycje liczone „on read", a nie jako mutowalne kolumny:** przy tak małej skali danych (pojedynczy użytkownik, kilkanaście pozycji) narzut obliczeniowy jest pomijalny, a uniknięcie klasy błędów „cache się rozjechał z transakcjami" jest ważniejsze niż wydajność. To jednoznacznie lepsze rozwiązanie techniczne przy tej skali — podjęta decyzja własna, niewymagająca wyboru właściciela. Jeśli w V2 pojawi się potrzeba wykresu wartości pozycji w czasie, dodać osobną tabelę `position_daily_snapshots` jako cache tylko do celów wizualizacji (nie jako źródło prawdy).

---

## 6. Configuration schema (YAML)

```yaml
universe:
  name: sp500
  source: provider_endpoint   # patrz Decyzja D4
  refresh: weekly

decline_scanner:
  thresholds:
    daily_pct: -5.0
    week_pct: -8.0
    month_pct: -15.0
    quarter_pct: -20.0
    drawdown_from_52w_high_pct: -25.0
    relative_volume_multiple: 2.0
  status: UNCALIBRATED    # nie traktować jako reguły inwestycyjnej przed backtestingiem (§6)

prefilter:
  exclude_rules: [...]
  flag_rules: [...]       # negatywny FCF domyślnie FLAG, nie EXCLUDE — patrz BLOCKER 5
  status: UNCALIBRATED

scoring:
  version: "0.1.0-draft"
  weights:
    business_quality: 45
    financial_safety: 15
    valuation: 20
    fear_opportunity: 10
    dividend_shareholder_return: 10
  status: UNCALIBRATED

hard_gates:
  min_business_quality: null
  min_financial_safety: null
  min_margin_of_safety_pct: null
  status: UNCALIBRATED

llm:
  model: claude-sonnet-5   # zmiana modelu = zmiana configu, bez zmian w kodzie (Decyzja D6)
  escalation_model: null   # np. claude-opus-5 — ręczny re-run niejednoznacznych
                            # analiz, włączany dopiero jeśli testy pokażą realną
                            # poprawę jakości; NIE domyślny model bez dowodu (D6)
  max_output_tokens: 4000
  schema_version: "1.0"
  reject_on_schema_violation: true
  allow_citations_outside_source_packet: false   # bariera przeciw halucynacji, BLOCKER 3

data_provider:
  fundamentals_prices: fmp        # lub eodhd — Decyzja D1
  filings: sec_edgar
  api_key_env_var: FMP_API_KEY

watchlist:
  triggers: [...]

sector_overrides:
  bank: {...}
  insurer: {...}
  reit: {...}
  # BIOTECH celowo NIE ma wpisu tutaj: to nie jest zestaw podmienionych
  # metryk w tym samym silniku GENERAL/BANK/INSURER/REIT (D7), tylko
  # odrębny pipeline projektowany od Fazy 8 — patrz sekcja 18

holdings:
  monitoring_cadence: TRIGGER_GATED   # patrz Decyzja D13
  mandatory_recheck_after_new_filing: true
  deterministic_pretrigger_thresholds:
    price_above_intrinsic_value_bull_pct: null      # UNCALIBRATED
    margin_of_safety_turns_negative: true
    dividend_change_detected: true
    new_10q_or_10k_or_8k_filed: true
    leverage_ratio_deterioration_pct: null           # UNCALIBRATED
  status: UNCALIBRATED

cost_basis_method: FIFO   # patrz Decyzja D12 — wyłącznie do wewnętrznego
                           # liczenia realized/unrealized P/L, NIE narzędzie podatkowe

backtest:
  window_start: "2012-01-01"   # patrz sekcja 13 i Decyzja D14
  window_end: null              # do dziś
  status: LIMITED_BUT_HONEST    # jawna adnotacja ograniczenia zakresu
```

Zasada: **każdy próg ma jawne `status: UNCALIBRATED`**, dopóki backtesting (V0.5) go nie zatwierdzi — nic nie jest domyślnie „prawdą".

---

## 7. Podział odpowiedzialności

| Warstwa | Odpowiada za | NIE robi |
|---|---|---|
| **Deterministyczny Python** | Wszystkie obliczenia liczbowe (wzrosty, FCF, dźwignia, drawdown, margin of safety), arytmetyka scoringu, hard gates, logika triggerów watchlisty/holdingów, budowa URL-i do SEC EDGAR, walidacja schematu JSON z LLM, zapisy do DB, liczenie pozycji (shares/koszt/P&L) | Interpretacji jakościowej, oceny moatu, klasyfikacji fear/uncertain/structural |
| **Claude API** | Interpretacja modelu biznesowego, ocena dowodów na przewagę konkurencyjną, ocena capital allocation, wnioskowanie o przyczynie spadku i klasyfikacja TEMPORARY/UNCERTAIN/STRUCTURAL (na bazie dostarczonych deterministycznych danych o skali/tempie spadku), bull/bear case, thesis invalidation, dobór i cytowanie WYŁĄCZNIE z dostarczonej listy źródeł, treść Exit Review | Obliczeń, które da się policzyć deterministycznie; generowania własnych URL-i/numerów stron; liczenia pozycji/P&L |
| **Dostawca danych finansowych** | Surowe ceny i dane fundamentalne | Interpretacji, linkowania do fragmentów dokumentów, weryfikacji źródeł, point-in-time (patrz BLOCKER 1) |
| **Baza danych** | Trwałe, wersjonowane przechowywanie (system rekordu + audit trail) | Logiki biznesowej poza prostą integralnością (brak „mądrych" procedur) |

---

## 8. Structured LLM output schema

Rozszerzenie ilustracyjnego schematu ze spec (§36) o pola confidence, źródła ograniczone do dostarczonej listy oraz pełny pakiet weryfikacyjny (§16):

```json
{
  "ticker": "XYZ",
  "schema_version": "1.0",
  "business_understandability": {
    "score": 0, "max_score": 7, "confidence": "MEDIUM", "reasoning": ""
  },
  "moat": {
    "score": 0, "max_score": 12, "confidence": "MEDIUM",
    "evidence": [], "counterarguments": []
  },
  "financial_quality_commentary": {
    "confidence": "MEDIUM", "reasoning": ""
    // liczbowy score (0-16) liczony deterministycznie, LLM dostarcza tylko komentarz
  },
  "management_capital_allocation": {
    "score": 0, "max_score": 10, "confidence": "MEDIUM",
    "evidence": []
  },
  "fear_analysis": {
    "classification": "TEMPORARY|UNCERTAIN|STRUCTURAL",
    "confidence": "HIGH|MEDIUM|LOW",
    "trigger": "", "reasoning": ""
  },
  "dividend_trap_alert": { "triggered": false, "reasoning": "" },
  "bull_case": [],
  "bear_case": [],
  "why_market_may_be_right": [],
  "biggest_unknown": "",
  "thesis_invalidation": [],
  "why_this_may_not_be_a_bargain": [],
  "verification_items": [
    {
      "source_id": "ref-to-analysis_sources.source_id",
      "document": "", "section": "", "page": null,
      "reason": "", "question": ""
    }
  ],
  "cited_source_ids": ["musi być podzbiorem ID dostarczonych w source packet"],
  "hard_flag_candidates": [
    { "type": "GOING_CONCERN|COVENANT_BREACH|...", "evidence_source_id": "",
      "quoted_text": "" }
  ]
}
```

Kluczowe zasady walidacji (deterministyczny post-processing, nie ufność w prompt):
1. `cited_source_ids` i każde `source_id` w `verification_items` musi istnieć w liście źródeł przekazanej do LLM w danym wywołaniu — inaczej odrzucić cały rekord jako malformed.
2. `page` może być niepuste tylko dla źródeł oznaczonych w `analysis_sources` jako PDF z potwierdzoną paginacją.
3. Wynik liczbowy poza zakresem (np. `score > max_score`) → reject, nie clamp.

Te same reguły walidacji obowiązują dla osobnego schematu Exit Review (pkt 16.2) — nie ma „lżejszego" trybu dla posiadanych pozycji.

---

## 9. Pozyskiwanie i weryfikacja źródeł pierwotnych

**SEC EDGAR (priorytet #1, zgodnie z §17):**
- Mapowanie ticker → CIK przez darmowy plik `company_tickers.json`.
- Lista filingów przez EDGAR Submissions API (`data.sec.gov`).
- Dane XBRL (company-facts / company-concept) do krzyżowej weryfikacji liczb od dostawcy danych (wykrywanie DATA CONFLICT, §24) oraz jako podstawa warstwy point-in-time (§13).
- Pełnotekstowe wyszukiwanie (`efts.sec.gov/LATEST/search-index`) do lokalizowania konkretnych fraz (np. „going concern") w filingach od 2001.
- Wymogi techniczne: deklarowany User-Agent z danymi kontaktowymi, limit **10 req/s**, brak wymaganego klucza API — ale wymagane cache'owanie, żeby nie przekraczać limitu przy 503 spółkach dziennie.

**Investor Relations:** SEC EDGAR nie ma odpowiednika dla dokumentów IR (prezentacje, press release). Brak scentralizowanego, weryfikowalnego indeksu → allowlista domen IR budowana ręcznie/stopniowo (Decyzja D9), rozwiązywana najpierw z oficjalnej strony spółki wskazanej na stronie tytułowej 10-K, nigdy z wyników wyszukiwarki internetowej bez weryfikacji. Dodawana dla spółek, które faktycznie trafiają do głębszej analizy/watchlisty/holdings — nie z góry dla całego uniwersum.

**Projekt pod przyszłą automatyzację (D9):** wykrycie kandydata na domenę IR da się zautomatyzować bezpiecznie — kod wyciąga adres oficjalnej strony spółki z pola na stronie tytułowej 10-K (dane ustrukturyzowane, nie zgadywane), a „weryfikacja" polega na porównaniu nazwy spółki/CIK widocznych na tej stronie z rekordem w `companies`. Wynik automatycznego wykrycia i tak trafia do allowlisty jako `verified: false` do czasu jednorazowego ręcznego potwierdzenia — automatyzacja przyspiesza pozyskanie kandydata, nie zastępuje weryfikacji. Nieimplementowane w V0/V1, tylko zaprojektowane jako ścieżka rozszerzenia.

**Zasada nadrzędna (implementacja RULE 1 i §17, decyzja architektoniczna dot. BLOCKER 3):** każdy wiersz w `analysis_sources` musi odpowiadać realnie wykonanemu żądaniu HTTP z kodem 200 i zapisanym hashem treści w trakcie danego uruchomienia pipeline'u — nigdy nie jest zapisywany na podstawie samego twierdzenia LLM. Source Assembly Layer jest **jedynym** twórcą wierszy w `analysis_sources`; Claude cytuje wyłącznie po `source_id` z dostarczonej listy. Deterministyczny post-processing odrzuca/usuwa każdy URL lub numer strony niepochodzący z tej listy. Niezweryfikowane źródło → `SOURCE NOT VERIFIED`, nigdy nie prezentowane jako potwierdzone. Dotyczy identycznie głównego pipeline'u i Exit Review.

---

## 10. Tworzenie bezpośrednich linków w „WHAT YOU SHOULD VERIFY"

- URL do dokumentu SEC EDGAR jest deterministycznie budowalny z danych Submissions API: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-no-bez-myślników}/{primary-document}`. **Link buduje kod, nie LLM.**
- Numer strony: HTML 10-K/10-Q na EDGAR **nie mają natywnej paginacji** — wymuszanie numeru strony dla tych dokumentów oznacza fabrykację (decyzja dot. BLOCKER 4). Numer strony podawany tylko dla źródeł PDF z potwierdzoną paginacją (np. prezentacje inwestorskie), gdzie biblioteka do ekstrakcji tekstu z PDF potwierdza pozycję dopasowanego fragmentu.
- Dla dokumentów HTML: zamiast strony — dokument, data filingu, typ filingu, numer/nazwa noty lub pozycji (np. „Note 8 — Long-Term Debt", „Item 7A") plus dokładny krótki cytat użyty do lokalizacji fragmentu przez wyszukiwanie pełnotekstowe, plus bezpośredni URL.
- Dokumenty IR: link tylko jeśli realnie pobrany i zahashowany w danym uruchomieniu; w przeciwnym razie wyświetlić `SOURCE NOT VERIFIED` zgodnie z §17.
- Priorytetem jest szybkie dotarcie użytkownika do dokładnego miejsca zawierającego informację, nie formalne posiadanie numeru strony.

---

## 11. Wersjonowanie scoringu i audit trail

- Wersjonowanie w stylu semver: `MAJOR.MINOR.PATCH` dla całego pakietu (wagi + bramki + schemat promptu razem = jedna wersja).
  - PATCH — poprawka błędu w obliczeniach deterministycznych bez zmiany metodologii.
  - MINOR — rekalibracja progu/wagi na podstawie backtestingu.
  - MAJOR — zmiana strukturalna (nowy komponent, inna skala punktów).
- Każdy wiersz `analyses` jest **immutable** i wskazuje na zamrożony wiersz `scoring_model_versions` (snapshot wag/bramek jako JSON, nie wskaźnik na „aktualny" config) — to bezpośrednia implementacja wymogu z §21, że v1.3 nie może nadpisać wyników v1.2.
- Ponowna ocena spółki = nowy wiersz `analyses` (INSERT), nigdy UPDATE.
- Reprodukowalność: `analyses.input_dataset_snapshot_id` wskazuje na `data_snapshots` z hashem danych dostawcy i pobranych dokumentów użytych w danym uruchomieniu — odpowiedź na pytanie „dlaczego 84/100 w tym dniu" wymaga tylko odtworzenia zapisanych danych wejściowych + configu, nie danych live.
- `llm_model_id` zapisywany per analiza (np. „claude-sonnet-5") — zmiana modelu wpływa na wnioskowanie jakościowe nawet przy identycznym prompt.
- **Rozszerzenie o MY HOLDINGS:** ta sama zasada append-only obowiązuje dla `purchase_transactions`, `sale_transactions`, `purchase_thesis`, `exit_review_reports`, `holding_user_actions` — korekta błędu to zawsze nowy rekord ze wskazaniem `superseded_by`, nigdy edycja istniejącego.

---

## 12. Sektory wymagające odmiennego traktowania

| Sektor | Problem ze standardowymi metrykami | Metryki zastępcze |
|---|---|---|
| **Banki** | Dług to „towar", nie dźwignia w zwykłym sensie — Net Debt/EBITDA, EV/EBITDA nie mają sensu | CET1/Tier 1, marża odsetkowa netto (NIM), wskaźnik efektywności kosztowej, ROTCE/ROE, P/TBV, trend rezerw na straty kredytowe |
| **Ubezpieczyciele** | Zysk netto silnie zniekształcony przez rezerwy; FCF nie jest głównym miernikiem | Combined ratio, rozwój rezerw szkodowych, float i koszt floatu, wartość księgowa na akcję, P/B, wskaźniki kapitału regulacyjnego (RBC) |
| **REIT-y** | Amortyzacja realna, ale niegotówkowa i specyficzna dla branży — zysk netto/FCF wprost mylące | FFO/AFFO zamiast zysku netto/FCF, NAV vs P/AFFO, wzrost NOI same-store, obłożenie, payout liczony względem AFFO (nie netto — inaczej payout ratio strukturalnie >100%) |
| **BIOTECH** | Standardowe metryki GENERAL (P/E, FCF-jako-jakość, przychody) są bez sensu dla spółek przedklinicznych/klinicznych bez przychodu — wartość zależy od pipeline'u, prawdopodobieństwa sukcesu i kalendarza katalizatorów, nie od bieżących wyników finansowych | **Nie** metrics-swap w tym samym silniku jak BANK/INSURER/REIT — osobny pipeline (Clinical Pipeline, Trial Quality, PoS, Cash Runway, Dilution Risk, Catalyst Calendar, rNPV, External Validation — sekcja 18), traktowany priorytetowo względem pełnego BANK/INSURER/REIT (Decyzja D15) |

**Rekomendacja V0:** pole `sector_profile` w configu (GENERAL / BANK / INSURER / REIT) przełączające zestaw metryk zasilających Financial Quality/Safety/Valuation w tym samym silniku. Domyślnie GENERAL dla ok. 440/503 spółek S&P 500; BANK/INSURER/REIT dodać po ustabilizowaniu silnika na „zwykłych" spółkach (Decyzja D7). BIOTECH jest kategorią jakościowo inną — nie dostaje podmienionych wag w istniejącym silniku, tylko odrębny model (sekcja 18), rozwijany zaraz po V1 i MY HOLDINGS, przed pełnym BANK/INSURER/REIT (Decyzja D15).

---

## 13. Strategia backtestingu bez look-ahead bias

### Co faktycznie ustalono

**Point-in-time fundamentals (BLOCKER 1):**
- Potwierdzone researchem: FMP (a przypuszczalnie EODHD — podobny model) to API „aktualnego widoku" — zwraca najnowsze, skorygowane dane, nie stan wiedzy na daną historyczną datę. Egzekwowanie PIT to praca deweloperska „na wierzchu" API, nie funkcja dostawcy.
- Jedyna zidentyfikowana, darmowa i wiarygodna droga do PIT: **SEC EDGAR XBRL company-facts / frames**, gdzie każdy fakt ma pole `filed` (data faktycznego złożenia) — pozwala zapytać „jaka była ostatnia wartość X *filed* na dzień ≤ D" i odtworzyć stan wiedzy rynku na dowolny dzień historyczny, bez zgadywania.
- Prawdziwe instytucjonalne bazy point-in-time (np. LSEG/Refinitiv) istnieją, ale są rozwiązaniem klasy enterprise — nieproporcjonalnie drogie dla projektu jednego inwestora indywidualnego. Nie rekomenduję tej ścieżki.
- Ograniczenie praktyczne: obowiązkowe tagowanie XBRL dla większości emitentów SEC weszło w życie ok. 2009–2011 — przed tym okresem jakość/dostępność danych `filed` jest niepewna i nie została zweryfikowana w tym przeglądzie.

**Historyczny skład S&P 500 (BLOCKER 2):**
- Zidentyfikowane kandydackie źródła: (a) płatny dodatek EODHD „Indices Historical Constituents Data API" (S&P Global przez marketplace UnicornBay) — **dwa źródła EODHD podają sprzeczny zakres historyczny** (kwiecień 2012 vs styczeń 2000) — DATA CONFLICT wymagający bezpośredniej weryfikacji w oficjalnej dokumentacji/z supportem przed zakupem; (b) „Historical S&P 500 Companies API" w FMP, oznaczone w URL jako „Legacy" — sam ten tag jest sygnałem ostrzegawczym (możliwe wycofywanie endpointu), wymaga potwierdzenia aktualnego statusu; (c) darmowe, społecznościowo utrzymywane zbiory danych na GitHub (np. `fja05680/sp500`) sięgające 1996 — użyteczne do walidacji krzyżowej, ale bez SLA/gwarancji poprawności dostawcy komercyjnego.
- Krytyczne ryzyko techniczne potwierdzone w trakcie researchu: **ticker recycling** — ticker po delistingu bywa przypisywany innej spółce. Rozwiązane już w schemacie DB (pkt 5) przez identyfikację po CIK, nie tickerze — to twarda konieczność techniczna, nie temat do dyskusji.

### Wniosek: ograniczony, ale metodologicznie uczciwy backtest zamiast pełnej symulacji PIT

Oba BLOCKERY zbiegają się w podobnym momencie w czasie: dojrzałość danych XBRL (~2009–2012) oraz zakres jednego z kandydackich źródeł historycznego składu indeksu (od kwietnia 2012, w wersji ostrożniejszej z dwóch sprzecznych źródeł EODHD). Rekomenduję zatem — zgodnie z zasadą „priorytetem jest brak survivorship bias, nie maksymalna długość backtestu" — **ograniczenie okna backtestingu do ok. 2012–dziś**, z jawną adnotacją `LIMITED_BUT_HONEST` w configu i w każdym raporcie z backtestu, zamiast symulowania pełnego PIT na dłuższym okresie przy niepewnych danych.

Co można wiarygodnie przetestować przy tym oknie: reakcję systemu na spadki i wydarzenia od 2012 r., przy prawdziwym (nie dzisiejszym) składzie indeksu i prawdziwych, historycznie znanych na dany dzień danych fundamentalnych z SEC XBRL. Czego NIE można wiarygodnie przetestować bez dodatkowej, potencjalnie kosztownej inwestycji w dane: zachowania systemu na kryzysach sprzed 2012 (np. 2008–2009) oraz — jeśli konflikt EODHD rozstrzygnie się na korzyść węższego zakresu — pełnej gwarancji braku survivorship bias przed kwietniem 2012 nawet przy użyciu tamtego źródła.

Dodatkowe zasady metodologiczne:
- Ceny użyte w backteście muszą być snapshotem na datę decyzji, nigdy przyszłym zamknięciem.
- Warstwa jakościowa (LLM) w backteście musi widzieć wyłącznie dokumenty złożone on/before data symulacji (filtrowanie po `filed_date` w EDGAR) — ale pełne wyeliminowanie „wiedzy z przyszłości" modelu językowego (wynikającej z jego danych treningowych) nie jest w pełni możliwe, tylko ograniczalne instrukcjami promptu. To zaakceptowane ograniczenie, nie coś do „naprawienia" w V0.5.
- Mierzyć nie tylko zwroty, ale i trafność klasyfikacji TEMPORARY vs STRUCTURAL — to jest właściwy test jakości modelu, nie sama stopa zwrotu (zgodnie z §30).

Oba BLOCKERY pozostają formalnie otwarte do czasu bezpośredniej weryfikacji dokumentacji/warunków dostępu wybranego dostawcy — patrz „OPEN BLOCKERS" niżej.

---

## 14. Plan testów dla V0 (+ MY HOLDINGS)

- **Testy jednostkowe obliczeń deterministycznych** — wzrosty, wskaźniki, FCF, payout ratio, drawdown %, margin of safety — na zweryfikowanych ręcznie wartościach referencyjnych dla 2–3 realnych spółek.
- **Testy arytmetyki scoringu** — sumowanie, hard gates na wartościach granicznych.
- **Testy walidacji schematu** — zniekształcony JSON z LLM (brak pola, zły typ, wynik poza zakresem) → reject, nie ciche „naprawianie".
- **Testy brakujących/sprzecznych danych** — brak wartości → `DATA UNAVAILABLE` propaguje się, nigdy nie jest traktowane jako 0; dwa źródła się różnią → `DATA CONFLICT` zapisane.
- **Testy trwałości** — niemutowalność `analyses`, logika triggerów watchlisty, przejścia statusów (WATCH→REJECT→ponowne pojawienie się z „MATERIAL CHANGE DETECTED").
- **Testy integracyjne z nagranymi fixture'ami** — nagrane raz odpowiedzi API (podejście VCR/cassette) dla 3–5 tickerów obejmujących profile GENERAL/BANK/REIT, odtwarzane w CI bez zależności od kosztu/dostępności live API.
- **Testy odporności na awarie** — API danych finansowych padło → pipeline zgłasza PARTIAL, nie fabrykuje; LLM padł/timeout → wynik ilościowy zachowany, jakościowy oznaczony jako niekompletny (§38).
- **Test identyfikacji przez CIK:** symulacja ticker recyclingu (dwie różne spółki z tym samym historycznym tickerem w różnych okresach) — system musi poprawnie rozróżnić pozycje/analizy.

**Dodatkowo dla MY HOLDINGS:**
- **Testy obliczeń pozycji:** liczba posiadanych akcji, średnia ważona cena zakupu, całkowity koszt, wartość bieżąca, unrealized P/L (nominalnie i %) — na zestawie transakcji z wieloma zakupami tej samej spółki po różnych cenach.
- **Testy metody cost-basis** (po decyzji D12): poprawność realized P/L przy częściowej sprzedaży dla wybranej metody (FIFO na start).
- **Test niemutowalności Purchase Thesis:** próba modyfikacji istniejącego `purchase_thesis` musi być zablokowana; korekta = nowa pozycja/transakcja, nie edycja.
- **Testy logiki exit-triggerów:** każda z 8 klas triggerów (THESIS_DETERIORATION, THESIS_INVALIDATION, STRUCTURAL_DETERIORATION, MOAT_DETERIORATION, FINANCIAL_SAFETY_DETERIORATION, MANAGEMENT_CAPITAL_ALLOCATION_CHANGE, DIVIDEND_DETERIORATION, VALUATION_REVIEW) ma osobny test jednostkowy na danych syntetycznych.
- **Test negatywny — dodatnia stopa zwrotu NIE wyzwala triggera sama w sobie:** pozycja +40% bez zmiany w fundamentach/tezie nie generuje `EXIT REVIEW REQUIRED`.
- **Test walidacji schematu Exit Review:** te same reguły co dla głównego schematu LLM (pkt 8) — zniekształcony JSON → reject, cytaty spoza dostarczonych źródeł → odrzucone/usunięte.

---

## 15. Plan implementacji — małe etapy

**Faza 0 — fundament**
0.1 Szkielet repo, loader configu (pydantic), sekrety przez zmienne środowiskowe.
0.2 Ingest uniwersum (lista S&P 500), tabele `companies` + `ticker_history` (CIK jako klucz od początku).
0.3 Ingest cen dla 5–10 tickerów testowych, tabela `price_daily`.
0.4 Decline scanner (czysta kalkulacja, testy jednostkowe).

**Faza 1 — fundamenty i pre-filter**
1.1 Ingest fundamentów (rachunek wyników/bilans/cash flow) dla tych samych tickerów.
1.2 Silnik wskaźników deterministycznych + testy.
1.3 Logika EXCLUDE/FLAG sterowana configiem (progi `UNCALIBRATED`, negatywny FCF domyślnie FLAG).

**Faza 2 — warstwa źródeł**
2.1 Mapowanie CIK + pobieranie listy filingów z EDGAR.
2.2 Budowa „source packet" (wyłącznie zweryfikowane URL-e, hash treści) — architektura zapobiegająca halucynacji (BLOCKER 3/4).
2.3 Mechanizm allowlisty domen IR (seed ręczny dla tickerów testowych).

**Faza 3 — integracja LLM**
3.1 Formalny JSON Schema + wrapper klienta Claude API walidujący wyjście.
3.2 Prompt v0 z deterministycznymi wskaźnikami + source packet jako kontekst; dry-run na 2–3 tickerach, ręczna ocena jakości.
3.3 Podpięcie hard-flag/fear-classification/verification-items do silnika scoringu.

**Faza 4 — scoring i bramki**
4.1 Silnik scoringu łączący sub-wyniki deterministyczne i LLM wg wag z configu.
4.2 Hard gates (progi `UNCALIBRATED`) + wyświetlanie hard flags.
4.3 Generator raportu CLI/Markdown — **kryterium wyjścia z V0**: pełny pipeline działa end-to-end na próbce ~20–30 tickerów, generuje raport, bez dopracowanego UI.

**Faza 5 (= V0.5) — backtesting i kalibracja** (dopiero po działającym V0)
5.1 Prototyp warstwy point-in-time na SEC XBRL dla 3–5 spółek testowych, porównanie z danymi „as reported" (OPEN BLOCKER 1).
5.2 Bezpośrednia weryfikacja i wybór źródła historycznego składu S&P 500 (OPEN BLOCKER 2).
5.3 Harness backtestu z oknem 2012–dziś, jawna adnotacja `LIMITED_BUT_HONEST`; pierwsza kalibracja progów/wag.

**Faza 6 (= V1)** — pełny przebieg na 503 spółkach, DB na skalę produkcyjną, dashboard, watchlist, automatyzacja dzienna (zgodnie z zakresem spec).

**Faza 7 — MY HOLDINGS, podstawowa obsługa pozycji** (po V1)
7.1 Tabele `positions`, `purchase_transactions`, `sale_transactions`, `purchase_thesis` + logika BOUGHT tworząca snapshot tezy.
7.2 Deterministyczny Holdings Monitor (krok 4b/4c z architektury) — tania bramka wyzwalająca pełną reanalizę tylko przy spełnieniu warunku.
7.3 Schemat Exit Review + prompt LLM (reużywający Source Assembly Layer bez zmian).
7.4 Raport Exit Review + akcje użytkownika (HOLD/REDUCE/SOLD/REVIEW LATER).
7.5 Widok MY HOLDINGS w dashboardzie (minimalny zakres — nie pełny portfolio management).

**Faza 8 — BIOTECH MODULE: DESIGN** (priorytet wyższy niż pełne BANK/INSURER/REIT — Decyzja D15)
Osobna, przyszła tura projektowa o tym samym rygorze co niniejszy dokument, obejmująca **cały** model biotech, nie tylko External Validation: Clinical Pipeline, Clinical Trial Quality, Clinical Evidence, Probability of Success (jako zakres z base rate + czynniki modyfikujące, nie punktowa liczba), Regulatory Status, Catalyst Calendar, Cash Runway, Dilution Risk, Pipeline Concentration, Competitive Landscape, risk-adjusted NPV/rNPV, External Validation & Research Network (już zaprojektowany — sekcja 18 — jako jedna z warstw), biotech-specific Thesis Monitoring, integracja z MY HOLDINGS/EXIT MONITORING (biotech-specific Purchase Thesis fields + Biotech Thesis Review). Pełny zarejestrowany zakres tej fazy — pkt 18.7. **Nie rozpoczynać implementacji przed ukończeniem tej fazy projektowej**, dokładnie tak jak V0 scannera nie zaczęło się bez tego dokumentu.

**Faza 9 — BIOTECH MODULE: IMPLEMENTACJA**
Wdrożenie osobnego pipeline'u/silnika scoringu dla spółek biotech na bazie projektu z Fazy 8, w tym warstwy External Validation z sekcji 18 jako jednego z komponentów. Reużywa Source Assembly Layer, wzorzec audytowalności i CIK-owy schemat tożsamości spółek z rdzenia — nie duplikuje tej infrastruktury.

**Faza 10 (LATER, opcjonalnie) — pełne rozszerzenie BANK/INSURER/REIT**
Tylko jeśli okaże się rzeczywiście potrzebne — **nie blokuje ani nie jest blokowane przez Fazę 8/9**; kolejność Faza 8/9 przed Fazą 10 wynika wprost z Decyzji D15 (biotech ma wyższy priorytet produktowy niż pełne pokrycie tych trzech sektorów).

Każda faza powinna być samodzielnie testowalna na małej próbce tickerów/spółek przed skalowaniem. Uzasadnienie umieszczenia tabel MY HOLDINGS i BIOTECH (External Validation) w projekcie już teraz, ale implementacji dopiero w odpowiednich fazach: unika się kosztownej migracji schematu później (np. zmiany klucza głównego spółek na CIK już teraz, zamiast robić to pod presją, gdy w bazie będą już realne dane).

---

## 16. MY HOLDINGS / EXIT MONITORING — projekt modułu

### 16.1 Purchase Transaction i Purchase Thesis

Po wybraniu BOUGHT użytkownik zapisuje: ticker/spółkę, datę zakupu, liczbę akcji, cenę zakupu, całkowitą zainwestowaną kwotę, walutę, opcjonalne prowizje, opcjonalną notatkę — wiele zakupów tej samej spółki jako osobne rekordy (patrz tabele w pkt 5). Kluczowa zasada: **kod, nigdy LLM, liczy liczby pozycji** (shares held, koszt, średnia cena, wartość, unrealized P/L) — Claude nie jest wywoływany do tego kroku w ogóle.

W momencie oznaczenia zakupu system automatycznie zapisuje **immutable snapshot** istniejącej analizy — Purchase Thesis: scoring version, total score, component scores, market price, intrinsic value range, Margin of Safety, Business Quality, Financial Safety, Fear Classification, Bull Case, Bear Case, Biggest Unknown, Thesis Invalidation Conditions, główne ryzyka, wykorzystane źródła, confidence. Ten rekord nie może zostać później nadpisany — umożliwia porównanie „WHAT WE BELIEVED AT PURCHASE" vs „WHAT WE KNOW NOW".

### 16.2 Schemat structured output dla Exit Review

```json
{
  "position_id": "...",
  "schema_version": "1.0",
  "report_type": "EXIT_REVIEW",
  "score_comparison": {
    "at_purchase": 0, "current": 0,
    "component_deltas": { "business_quality": 0, "financial_safety": 0,
                            "valuation": 0, "fear_opportunity": 0,
                            "dividend_shareholder_return": 0 }
  },
  "valuation_comparison": {
    "intrinsic_value_at_purchase": {}, "intrinsic_value_current": {},
    "margin_of_safety_at_purchase": 0, "margin_of_safety_current": 0
  },
  "what_changed": "",
  "thesis_still_valid": true,
  "invalidation_conditions_status": [
    { "condition": "", "met": false, "evidence_source_id": null }
  ],
  "bull_case": [], "bear_case": [],
  "why_holding_may_still_be_rational": [],
  "why_reassessment_is_required": [],
  "biggest_unknown": "", "confidence": "MEDIUM",
  "verification_items": [ { "source_id": "", "document": "", "section": "",
                              "page": null, "reason": "", "question": "" } ],
  "cited_source_ids": []
}
```

Te same reguły walidacji co w pkt 8 (cytaty tylko z dostarczonych źródeł, brak numeru strony dla HTML SEC, reject przy naruszeniu). To w praktyce ten sam mechanizm co „WHAT CHANGED" / Change Detection z oryginalnej specyfikacji (§29) — Exit Review to jego zastosowanie względem **zamrożonego punktu odniesienia (Purchase Thesis)** zamiast względem „poprzedniej analizy". Nie trzeba budować nowego silnika porównawczego, tylko sparametryzować istniejący innym baseline'em.

System **nie generuje automatycznego SELL** — wyłącznie `EXIT REVIEW REQUIRED`. Po jego wygenerowaniu użytkownik wybiera: HOLD, REDUCE, SOLD lub REVIEW LATER — żaden status nie wykonuje transakcji u brokera. Sprzedaż zapisywana jest ręcznie (data, liczba akcji, cena, waluta, opcjonalne opłaty/notatka), kod deterministycznie aktualizuje pozostałe akcje, wartość pozycji, historię transakcji i realized/unrealized P/L.

### 16.3 Cadence monitoringu

Rekomendowany tryb: `TRIGGER_GATED` — codziennie, tanio, deterministycznie sprawdzane są warunki wstępne (cena vs zaktualizowana wycena, zmiana dywidendy, nowy filing, pogorszenie wskaźników zadłużenia); pełna, kosztowna analiza LLM (Exit Review) uruchamiana jest tylko gdy warunek wstępny się spełni, plus obowiązkowo po każdym nowym kwartalnym filingu (niezależnie od tego, czy coś „wygląda niepokojąco" — żeby nie przegapić cichej erozji tezy). To zachowuje zasadę „tani filtr deterministyczny najpierw, drogi LLM na końcu" (§35 oryginalnej specyfikacji) również dla holdingów, zamiast tworzyć dla nich wyjątek. Pełne uzasadnienie — Decyzja D13.

### 16.4 MY HOLDINGS — widok (przyszły UI, zakres minimalny)

Sekcja MY HOLDINGS w przyszłym dashboardzie: spółka, ticker, liczba posiadanych akcji, średnia cena zakupu, cena bieżąca, zainwestowana kwota, wartość bieżąca, unrealized P/L, aktualny wynik, wynik przy zakupie, status tezy, data ostatniej analizy, aktywne ostrzeżenie/trigger, `EXIT REVIEW REQUIRED` jeśli występuje. Nie buduje się teraz pełnego systemu portfolio management.

---

## 17. Wpływ MY HOLDINGS na architekturę — checklist

| Element | Zmienia się? | Jak |
|---|---|---|
| Database schema | **Tak** | 7 nowych tabel (pkt 5) + zmiana klucza głównego spółek na CIK (wymuszona niezależnie, przez ryzyko ticker recyclingu wykryte przy BLOCKER 2) |
| Event model | **Tak** | Nowy typ zdarzenia „nowa analiza dla posiadanej pozycji" uruchamiający ocenę exit-triggerów; holdings nie czekają na wynik decline-scannera/pre-filtra |
| Scheduler | **Nie** (infrastrukturalnie) | Ten sam codzienny GitHub Actions run, dodatkowy krok w pipeline; brak potrzeby osobnego harmonogramu |
| Source pipeline | **Nie** (koncepcyjnie) | Pełne ponowne użycie Source Assembly Layer i allowlisty z BLOCKER 3 — bez wyjątków dla holdingów |
| Scoring architecture | **Częściowo** | Ten sam silnik 5-komponentowy; nowy element to porównanie do zamrożonego baseline'u (Purchase Thesis) zamiast tylko do poprzedniej analizy — rozszerzenie istniejącego mechanizmu Change Detection (§29), nie nowy silnik |
| Audit trail | **Tak** | Rozszerzony o zasadę append-only dla transakcji i tez zakupowych; logicznie spójny z już istniejącą zasadą niemutowalności `analyses` |
| UI architecture | **Tak (odłożone)** | Nowa sekcja MY HOLDINGS w V1.5/V2 dashboardzie — zaprojektowana (pkt 16.4), nieimplementowana teraz |
| Koszty | **Nieznacząco** | Marginalny wzrost przy trybie TRIGGER_GATED i typowej liczbie pozycji inwestora indywidualnego; brak wpływu na koszt dostawcy danych |
| Implementation phases | **Tak** | Nowa Faza 7 (pkt 15); schema projektowana teraz, implementacja logiki odłożona |
| Wcześniejsze DECISIONS REQUIRED | **Tak** | Dwie nowe decyzje (D12, D13) |

---

## 18. BIOTECH MODUŁ — EXTERNAL VALIDATION & RESEARCH NETWORK

### 18.0 Status i zakres

**External Validation & Research Network to JEDNA WARSTWA przyszłego pełnego BIOTECH MODULE, nie cały model.** Pełny zakres docelowy (Clinical Pipeline, Trial Quality, Clinical Evidence, Probability of Success, Regulatory Status, Catalyst Calendar, Cash Runway, Dilution Risk, Pipeline Concentration, Competitive Landscape, rNPV, External Validation, biotech-specific Thesis Monitoring, integracja z MY HOLDINGS) jest zarejestrowany w pkt 18.7 jako scope dla **Fazy 8 — osobnej, przyszłej tury projektowej**, nie zaprojektowany tutaj w całości. Ten moduł dotyczy wyłącznie spółek biotech; biotech jest świadomie **wykluczony z zakresu V0** (Decyzja D7 — GENERAL najpierw), ale — po decyzji D15 — ma **wyższy priorytet niż pełne rozszerzenie BANK/INSURER/REIT** w kolejności: V0 → V0.5 → V1 → MY HOLDINGS (Faza 7) → BIOTECH design + implementacja (Fazy 8–9) → BANK/INSURER/REIT pełne (Faza 10, opcjonalnie). External Validation jest **projektowany teraz** (ta sekcja: schema, źródła, structured output), ale **implementowany dopiero** w Fazie 9, jako jeden z komponentów pełnego modelu zaprojektowanego w Fazie 8. Nie zastępuje Clinical Evidence, Trial Quality, Probability of Success, Cash Runway, Regulatory Analysis, Competitive Landscape ani rNPV — to dodatkowa warstwa odpowiadająca na pytanie „kto poza samą spółką jest zaangażowany w ten program, w jaki sposób, i jak silnym sygnałem jest to zaangażowanie".

### 18.1 Dodatkowe źródła danych

| Źródło | Status | Co dostarcza | Uwagi |
|---|---|---|---|
| **ClinicalTrials.gov API v2** (`data-api.clinicaltrials.gov`) | Darmowe, bez klucza — potwierdzone researchem | `protocolSection.sponsorCollaboratorsModule` (lead sponsor, collaborators) — **potwierdzona struktura**; role indywidualnych badaczy (Principal Investigator/Study Chair/Study Director) istnieją w API, prawdopodobnie w `contactsLocationsModule.overallOfficials[].role`, ale **dokładna ścieżka/nazewnictwo pola nie zostało potwierdzone w tym przeglądzie** — do zweryfikowania bezpośrednio w dokumentacji API przed implementacją, nie zakładam tego jako pewnik. Lokalizacje ośrodków klinicznych (`locations[]`) — dane do sekcji Institutional Validation dla clinical sites. | Główne, ustrukturyzowane źródło dla sekcji 1 (Research Network) i częściowo 4 (kliniczne ośrodki). |
| **OpenAlex API** (`openalex.org`) | Darmowe, **bez limitu zapytań** — potwierdzone researchem | `/authors` — zdisambiguowane rekordy osób powiązane z ORCID gdzie dostępne; `/institutions` — powiązane z ROR ID; dane o publikacjach z afiliacjami autorów, czerpane m.in. z PubMed/Crossref. | Rekomendowany jako **główne** źródło do rozróżniania osób/instytucji (sekcje 3, 7) — ORCID/ROR realnie redukuje ryzyko pomylenia dwóch badaczy o tym samym nazwisku, czego surowy string afiliacji z PubMed nie gwarantuje. |
| PubMed/PMC (NCBI E-utilities) | Darmowe, limity zapytań (wymaga throttlingu, zalecany klucz API dla wyższych limitów) | MeSH terms, abstrakty, dodatkowe metadane publikacji | Źródło **drugorzędne** względem OpenAlex — brak natywnej disambiguacji autorów. |
| SEC EDGAR (już warstwa podstawowa systemu) | Darmowe | 8-K, 10-K, umowy licencyjne/collaboration w exhibitach | Źródło materialności partnerstw/finansowania — tylko dla spółek notowanych i zarejestrowanych w SEC (część mikro-cap biotech może nie być). |
| Allowlista IR / press release (już istniejący mechanizm) | — | Konkretne kwoty upfront/milestone payments | Często jedyne miejsce z faktycznymi liczbami — SEC filings bywają ogólnikowe. |
| ROR — Research Organization Registry (`ror.org`) | Darmowe | Kanoniczne identyfikatory instytucji | Do deduplikacji „University X"/„Univ. of X"/pełna nazwa pod jednym rekordem `institutions`. |

Wszystkie powyższe źródła podlegają **tej samej zasadzie co BLOCKER 3**: rekord relacji (osoba/instytucja/publikacja/partnerstwo) powstaje wyłącznie z realnie pobranych danych z konkretnym `source_id`; jeśli relacji nie da się zweryfikować → `UNVERIFIED`. Claude nie tworzy takich relacji z własnej wiedzy.

### 18.2 Database schema — relacje COMPANY → ASSET → TRIAL → PERSON → INSTITUTION → PUBLICATION → PARTNERSHIP → FUNDING

**Czy potrzebna jest graph database?** Nie. Przy tej skali (pojedynczy użytkownik, kilka–kilkanaście spółek biotech w polu uwagi, po kilka assetów/trial/osób na spółkę) liczba relacji jest ograniczona i w pełni obsługiwalna przez zwykłe tabele łącznikowe (many-to-many) w tej samej relacyjnej bazie (SQLite→Postgres), bez dodatkowej technologii. Graph DB (np. Neo4j) dodałby operacyjną złożoność sprzeczną z zasadą „tanie w utrzymaniu, obsługiwalne przez osobę nietechniczną" bez korzyści przy tym wolumenie danych — świadomie odradzam.

```sql
assets(asset_id PK, cik FK, name, modality, indication, development_stage,
       created_at)

trials(trial_id PK, asset_id FK, nct_id UNIQUE, title, phase, status,
       source_id FK, ingested_at)

persons(person_id PK, full_name, orcid NULL, current_institution_id FK NULL,
        specialization, disambiguation_confidence ENUM('HIGH_ORCID_MATCH',
        'MEDIUM_NAME_PLUS_AFFILIATION','LOW_NAME_ONLY'), source_id FK)

institutions(institution_id PK, name, ror_id NULL,
             type ENUM('ACADEMIC_MEDICAL_CENTER','UNIVERSITY',
                        'RESEARCH_INSTITUTE','GOVERNMENT','PHARMA',
                        'BIOTECH','HOSPITAL','OTHER'), source_id FK)

trial_person_roles(id PK, trial_id FK, person_id FK,
    role ENUM('PRINCIPAL_INVESTIGATOR','STUDY_CHAIR','STUDY_DIRECTOR',
               'INVESTIGATOR','OTHER'),
    since_date NULL, source_id FK, verified BOOLEAN)

trial_institution_roles(id PK, trial_id FK, institution_id FK,
    role ENUM('LEAD_SPONSOR','COLLABORATOR','CLINICAL_SITE','FUNDER',
               'ACADEMIC_PARTNER','OTHER'),
    since_date NULL, source_id FK, verified BOOLEAN)

partnerships(partnership_id PK, asset_id FK, partner_institution_id FK,
    role ENUM('LICENSING_PARTNER','CO_DEVELOPMENT_PARTNER',
               'MANUFACTURING_PARTNER','FUNDER','COMMERCIAL_PARTNER','OTHER'),
    since_date, what_exactly_contributed TEXT, source_id FK, verified BOOLEAN)

funding_events(funding_id PK, asset_id FK, partnership_id FK NULL,
    type ENUM('UPFRONT_PAYMENT','MILESTONE_PAYMENT','RESEARCH_FUNDING',
               'GRANT','EQUITY_INVESTMENT','OTHER'),
    amount NULL, currency NULL,   -- NULL to poprawny, częsty stan (kwoty
                                   -- transakcji biotech bywają nieujawnione —
                                   -- to NIE jest DATA UNAVAILABLE/błąd)
    disclosed_date, source_id FK, verified BOOLEAN)

publications(publication_id PK, title, journal_or_conference,
    publication_date, doi NULL, openalex_id NULL, source_url,
    study_type ENUM('TRIAL_RESULTS','MECHANISM_OF_ACTION','REVIEW',
                      'CONFERENCE_ABSTRACT','OTHER'),
    concerns_actual_product BOOLEAN,   -- rozróżnienie z pkt 7: mechanizm
                                        -- vs faktyczny produkt
    evidence_origin ENUM('COMPANY_GENERATED','COLLABORATOR_GENERATED',
                           'INDEPENDENT_ACADEMIC','PEER_REVIEWED',
                           'REGULATORY','OTHER'),
    source_id FK)

publication_authors(id PK, publication_id FK, person_id FK, author_order,
                     affiliation_institution_id FK NULL)

publication_asset_links(id PK, publication_id FK, asset_id FK,
                         trial_id FK NULL, relation_note)

conflicts_dependencies(id PK, asset_id FK, person_id FK NULL,
    institution_id FK NULL,
    type ENUM('EMPLOYED_BY_COMPANY','CONSULTING_FOR_COMPANY',
               'COMPANY_FUNDED_RESEARCH','COMPANY_SPONSORED_TRIAL',
               'LICENSING_RELATIONSHIP','EQUITY_FINANCIAL_RELATIONSHIP'),
    disclosed BOOLEAN, source_id FK)

-- Wynik syntezy — immutable, wersjonowane jak `analyses`
external_validation_assessments(assessment_id PK, asset_id FK,
    analysis_id FK, key_people JSON, key_institutions JSON,
    commercial_partners JSON, independent_evidence JSON,
    dependencies_conflicts JSON,
    assessment ENUM('STRONG','MODERATE','LIMITED','INSUFFICIENT_DATA'),
    confidence ENUM('HIGH','MEDIUM','LOW'), why TEXT, created_at)
```

Uwaga projektowa: `evidence_origin` jest kolumną wprost na `publications` (i analogicznie mogłaby być na `funding_events`/`partnerships`), zamiast jednej generycznej tabeli polimorficznej „evidence_provenance" — czytelniejsze i prostsze w relacyjnej bazie, ta sama informacja, mniej pośredniej złożoności. Wszystkie tabele relacyjne (`trial_person_roles`, `trial_institution_roles`, `partnerships`, `funding_events`, `publications`, `conflicts_dependencies`) mają `source_id FK` → `analysis_sources` i `verified BOOLEAN` — dokładnie ten sam mechanizm co reszta systemu (BLOCKER 3), rozszerzony z „dokumentów" na „relacje między encjami".

### 18.3 Structured LLM output — External Validation Assessment

Osobny schemat per kluczowy asset, budowany na bazie już zebranych (deterministycznie, z CT.gov/OpenAlex/EDGAR/IR) rekordów — LLM syntetyzuje i interpretuje fakty, nie ustala ich istnienia:

```json
{
  "asset_id": "...",
  "schema_version": "1.0",
  "report_type": "EXTERNAL_VALIDATION",
  "key_people": [
    { "person_id": "", "name": "", "role": "PRINCIPAL_INVESTIGATOR",
      "relevance_to_indication": "", "confidence": "MEDIUM",
      "source_ids": [] }
  ],
  "key_institutions": [
    { "institution_id": "", "name": "", "role": "LEAD_SPONSOR",
      "since": null, "what_exactly_contributed": "", "source_ids": [] }
  ],
  "commercial_development_partners": [
    { "institution_id": "", "role": "LICENSING_PARTNER",
      "material_resources_committed": true, "source_ids": [] }
  ],
  "independent_evidence": [
    { "publication_id": "", "evidence_origin": "INDEPENDENT_ACADEMIC",
      "concerns_actual_product": false, "source_ids": [] }
  ],
  "dependencies_conflicts": [
    { "type": "COMPANY_SPONSORED_TRIAL", "description": "", "source_ids": [] }
  ],
  "external_validation": "LIMITED",
  "confidence": "MEDIUM",
  "why": "",
  "notable_external_validation": false
}
```

Reguły walidacji — identyczne z pkt 8: każdy `source_ids` musi być podzbiorem realnie dostarczonych źródeł; brak numeru strony dla HTML; reject przy naruszeniu. Dodatkowo dwie reguły specyficzne dla tego modułu, wymuszane w post-processingu, nie tylko w prompt:
1. Sam fakt wystąpienia osoby/instytucji w rekordzie CT.gov/publikacji **nie** podnosi automatycznie `external_validation` — ocena STRONG/MODERATE/LIMITED/INSUFFICIENT_DATA musi jawnie odróżniać „NAME APPEARS IN STUDY" od „ORGANIZATION COMMITTED MATERIAL RESOURCES" (pkt 5 wymagania) — deterministyczna reguła pomocnicza może np. wymagać, żeby STRONG wymagało co najmniej jednego rekordu `partnerships`/`funding_events` z `material_resources_committed: true`, nie tylko obecności w `trial_institution_roles`.
2. Publikacja dotycząca mechanizmu działania (`study_type: MECHANISM_OF_ACTION`) nigdy nie może być jedynym uzasadnieniem oceny wyższej niż LIMITED bez dodatkowej publikacji z `concerns_actual_product: true`.

### 18.4 Integralność z resztą architektury

Moduł w całości reużywa istniejące mechanizmy zamiast budować nowy system: Source Assembly Layer (BLOCKER 3) rozszerzony o nowe typy źródeł (CT.gov, OpenAlex, ROR); ten sam wzorzec `verified`/`UNVERIFIED`; ten sam wzorzec confidence HIGH/MEDIUM/LOW z tym samym, już zidentyfikowanym w IMPORTANT braki rubryki (patrz niżej); ten sam mechanizm wersjonowania/immutability co `analyses`. **Istotna, korzystna właściwość architektoniczna:** większość danych z sekcji 1, 4, 7 (kto, jaka rola, jaka instytucja, jaka publikacja) da się pozyskać **w pełni deterministycznie** z CT.gov/OpenAlex/ROR bez udziału LLM — Claude potrzebny jest dopiero do syntezy/interpretacji (pkt 18.3, reguły 1–2) i do jakościowej oceny relevance badacza do wskazania medycznego (pkt 3 wymagania — „czy badacz ma istotne doświadczenie bezpośrednio związane z tym problemem"). To utrzymuje koszt pod kontrolą i zmniejsza powierzchnię ryzyka halucynacji, bo LLM operuje na już ustalonych faktach, nie ustala ich sam.

### 18.5 Nowe ryzyka (uzupełnienie do IMPORTANT, patrz też sekcja niżej)

- **Disambiguacja osób o tym samym nazwisku** (typowa w dużych bazach badaczy medycznych) — zmitygowane architektonicznie przez wymóg dopasowania ORCID/ROR (OpenAlex) jako warunku `disambiguation_confidence: HIGH_ORCID_MATCH`; dopasowanie po samym nazwisku+afiliacji ląduje jako `MEDIUM`/`LOW`, nigdy nie jest cicho podnoszone do pewności bez podstawy źródłowej.
- **Ten sam brak rubryki dla confidence**, już zidentyfikowany w ogólnej sekcji IMPORTANT, dotyczy teraz też oceny `external_validation` (STRONG/MODERATE/LIMITED/INSUFFICIENT_DATA) — nie tworzę tu osobnego punktu, tylko rozszerzam istniejący.
- **Koszt:** ograniczony przez to, że większość ekstrakcji jest deterministyczna (pkt 18.4); LLM wywoływany per kluczowy asset (nie per wszystkie programy spółki) — zgodnie z zasadą „kluczowy program/istotny asset" ze specyfikacji, nie każdy wpis w pipeline spółki. Nie wymaga osobnej decyzji właściciela — operacjonalizuję to jako „asset napędzający tezę inwestycyjną (zwykle najbardziej zaawansowany kliniczne)", konfigurowalne później.

### 18.6 Wpływ na plan implementacji

Implementacja tej warstwy to część **Fazy 9 — BIOTECH MODULE: IMPLEMENTACJA** (patrz sekcja 15), poprzedzonej **Fazą 8 — BIOTECH MODULE: DESIGN** (pełny zakres w pkt 18.7). W ramach Fazy 9, ta warstwa obejmuje:
9.1 Ingest ClinicalTrials.gov API v2 dla spółek biotech w uniwersum (po potwierdzeniu dokładnej struktury pól ról badaczy).
9.2 Integracja OpenAlex/ROR do disambiguacji osób/instytucji i pozyskiwania publikacji.
9.3 Tabele z pkt 18.2 + reużycie Source Assembly Layer dla nowych typów źródeł.
9.4 Schemat External Validation Assessment (pkt 18.3) + reguły post-processingu (1–2).
9.5 Integracja z candidate card / raportem — sekcja EXTERNAL VALIDATION jako dodatek do (nie zamiennik) pozostałych sekcji biotech-specyficznych zaprojektowanych w Fazie 8.

### 18.7 Pełny docelowy zakres BIOTECH MODULE — zarejestrowany scope dla Fazy 8 (NIE zaprojektowany w tej turze)

Poniższe to zapis wymagań produktowych przekazanych przez właściciela, żeby nic nie zostało utracone — **projekt techniczny tych elementów (schema, structured output, źródła danych) powstanie dopiero w Fazie 8**, jako osobna tura o rygorze analogicznym do niniejszego dokumentu.

**Cel produktowy:** wyszukiwać spółki rozwijające nowe leki, terapie biologiczne/genowe/komórkowe i inne innowacyjne terapie, identyfikować programy zbliżające się do istotnego clinical/regulatory catalyst, i odpowiadać na 15 pytań: co dokładnie spółka rozwija; na jakim etapie jest program; jak wyglądają dotychczasowe wyniki; jak dobre jakościowo jest badanie; jaki jest kolejny catalyst i kiedy oczekiwany; jakie jest historyczne/base-rate probability of success dla tego typu programu; jak konkretne dane o programie powinny zmienić ten base rate; jakie są najważniejsze ryzyka; czy spółka ma wystarczający cash runway do catalystu; jak duże jest dilution risk; jak bardzo wartość spółki zależy od jednego assetu; jak wygląda konkurencja; jaka może być risk-adjusted wartość programu; kto poza samą spółką jest zaangażowany (= External Validation, już zaprojektowane).

**Komponenty pełnego modelu (do zaprojektowania w Fazie 8):** Clinical Pipeline; Clinical Trial Quality; Clinical Evidence; Probability of Success; Regulatory Status; Catalyst Calendar; Cash Runway; Dilution Risk; Pipeline Concentration; Competitive Landscape; risk-adjusted NPV/rNPV; External Validation & Research Network (już zaprojektowane — sekcja 18.1–18.6); biotech-specific Thesis Monitoring; integracja z MY HOLDINGS/EXIT MONITORING.

**Probability of Success — zasada nadrzędna dla Fazy 8:** żadna fałszywa precyzja. Historyczne phase-transition probabilities służą jako **base rate**, aktualizowany na podstawie m.in. indication, modality, mechanism, previous trial results, endpoint, trial design, sample size, safety, regulatory feedback, competitive evidence, external validation. Wynik to zawsze **zakres** (np. „25–40%"), nigdy pojedyncza arbitralna liczba (np. „63.7%"), i musi pokazywać: base rate; evidence increasing probability; evidence decreasing probability; biggest unknown; confidence; sources.

**BIOTECH + MY HOLDINGS (do zaprojektowania w Fazie 8, jako rozszerzenie schematu z sekcji 16):** przy zakupie spółki biotech Purchase Thesis musi dodatkowo zamrozić: key asset(s); phase at purchase; clinical evidence available at purchase; probability range at purchase; expected catalyst; expected catalyst date/range; cash runway; dilution risk; rNPV assumptions; external validation status; binary-event risk; biotech-specific thesis invalidation conditions. Po nowych wynikach system wykonuje **BIOTECH THESIS REVIEW** — analogicznie do Exit Review z sekcji 16.2, ale z dodatkowymi polami biotech-specyficznymi — porównujący „WHAT WE BELIEVED AT PURCHASE" vs „WHAT ACTUALLY HAPPENED". To rozszerzenie istniejącego mechanizmu Exit Review/Change Detection, nie nowy silnik — ta sama zasada reużycia co w resztą modułu.

---

## OPEN BLOCKERS

Te dwa BLOCKERY **pozostają formalnie otwarte** — mają zidentyfikowaną, konkretną ścieżkę rozwiązania, ale wymagają bezpośredniej weryfikacji u dostawcy/w dokumentacji przed uznaniem za zamknięte. **Nie blokują rozpoczęcia Fazy 0–4 (budowa V0)** — dotyczą wyłącznie backtestingu. **Muszą** zostać rozwiązane przed rozpoczęciem Fazy 5 (V0.5 — właściwy backtesting).

**OPEN BLOCKER 1 — Point-in-time fundamentals.**
Tani dostawca danych prawdopodobnie zwraca wyłącznie najnowsze, skorygowane („restated") dane finansowe, nie stan wiedzy z danego dnia historycznego — potwierdzone researchem dla FMP. Bez tego backtesting narusza wprost wymóg §30 („no look-ahead bias"). Ścieżka rozwiązania: własna warstwa PIT budowana na SEC EDGAR XBRL company-facts (pole `filed`), bez dodatkowego kosztu licencyjnego. Pozostaje do zrobienia: (a) prototyp ekstrakcji dla 3–5 spółek testowych i porównanie z danymi „as reported" z dokumentacji FMP/EODHD, żeby potwierdzić wykonalność przed budową pełnej warstwy; (b) potwierdzenie jakości/kompletności danych `filed` dla okresu 2009–2012 (obszar niepewny).

**OPEN BLOCKER 2 — Historyczny skład S&P 500 / survivorship bias.**
Żaden z trzech porównanych dostawców nie oferuje w oczywisty sposób czystego, historycznego API członkostwa w indeksie. Backtest bez tego jest strukturalnie zniekształcony (spółki, które upadły/wypadły z indeksu, znikają z próby) — wnioski z takiego backtestu byłyby niewiarygodne, mimo pozornej poprawności metodologicznej. Ścieżka rozwiązania: płatny dodatek EODHD „Indices Historical Constituents" **lub** FMP „Historical S&P 500 Companies (Legacy)" **lub** walidacja krzyżowa przez darmowy zbiór społecznościowy. Pozostaje do zrobienia: (a) rozstrzygnięcie sprzeczności w dokumentacji EODHD (kwiecień 2012 vs styczeń 2000) bezpośrednio z dostawcą/supportem; (b) potwierdzenie, czy status „Legacy" endpointu FMP oznacza aktywne wsparcie czy planowane wycofanie; (c) wycena dodatku EODHD (nieznana w tym przeglądzie).

Do czasu zamknięcia obu punktów, wszelkie wyniki backtestingu muszą nosić w raporcie jawną adnotację `LIMITED_BUT_HONEST` z opisem, którego okresu/zakresu dotyczy ograniczenie.

---

## Rozwiązane na poziomie decyzji architektonicznej (BLOCKER 3, 4, 5)

Poniższe trzy punkty **nie wymagają dalszej dyskusji** — decyzje przyjęte i wbudowane w architekturę/schema powyżej. Poniżej pełna treść pierwotnie proponowanych zmian wraz z uzasadnieniem, dla kompletności dokumentu.

### BLOCKER 3 — halucynacje/nieprawidłowe URL-e źródeł — ROZWIĄZANY

**Pierwotny problem:** Spec nie definiowała wprost mechanizmu uniemożliwiającego LLM generowanie własnych URL-i/cytatów spoza dostarczonych danych — polegała głównie na instrukcji promptowej („must never fabricate URLs"), co jest niewystarczające w systemie, którego głównym walorem jest wiarygodność źródeł (RULE 1, RULE 5).

**Przyjęte rozwiązanie:** Source Assembly Layer / kod pozyskuje źródła, przechowuje canonical URL, sprawdza domenę, sprawdza dostępność dokumentu, identyfikuje dokument, przekazuje Claude'owi już zidentyfikowane źródła, waliduje źródła przed pokazaniem ich użytkownikowi. Claude cytuje wyłącznie po `source_id` z dostarczonej listy; deterministyczny post-processing usuwa/odrzuca każdy URL lub numer strony niepochodzący z tej listy. Dla źródeł primary stosowana jest allowlista (SEC, oficjalne Investor Relations, oficjalne regulatory/exchange sources). Jeżeli URL lub dokument nie przejdzie walidacji → `SOURCE NOT VERIFIED`, nigdy nie prezentowane jako potwierdzone źródło. Claude może analizować zawartość dostarczonych źródeł, ale nie jest źródłem prawdy dla istnienia dokumentu lub URL. Dotyczy identycznie głównego pipeline'u i Exit Review (pkt 16.2).

### BLOCKER 4 — numery stron w SEC HTML — ROZWIĄZANY

**Pierwotny problem:** Wymóg „Page: XX, if available" jako standardowy element pakietu weryfikacyjnego dla dokumentów SEC jest technicznie niespełnialny — większość filingów 10-K/10-Q na EDGAR to HTML bez natywnej paginacji, więc utrzymanie tego wymogu wymusza fabrykację przy pierwszym uruchomieniu na najważniejszym (priorytet #1) typie źródła.

**Przyjęte rozwiązanie:** Dla dokumentów posiadających rzeczywistą paginację (np. PDF): document, section/note, page, direct URL. Dla SEC HTML bez paginacji: document, filing date, filing type, section/item/note, krótki fragment pozwalający zidentyfikować właściwe miejsce, direct URL — system NIE wymyśla numeru strony, jeśli źródło go nie posiada. Priorytetem jest szybkie dotarcie użytkownika do dokładnego miejsca zawierającego informację, a nie formalne posiadanie numeru strony. Wdrożone w schemacie z pkt 8 i 16.2 (pole `page` dopuszczalne tylko przy potwierdzonej paginacji źródła).

### BLOCKER 5 — ujemny FCF — ROZWIĄZANY

**Pierwotny problem:** Automatyczne EXCLUDE (§7) dla m.in. „persistent net losses" / „persistent negative free cash flow" bez rozróżnienia kontekstu biznesowego jest wewnętrznie sprzeczne z własnym zastrzeżeniem spec („not every abnormal metric should result in automatic exclusion") i systemowo wykluczałoby legalne modele biznesowe (reinwestujący wzrost, asset-light, wczesna faza).

**Przyjęte rozwiązanie:** Ujemny FCF sam w sobie NIE jest automatycznym EXCLUDE. Domyślnie: NEGATIVE FCF → FLAG FOR REVIEW. System uwzględnia model biznesowy, fazę rozwoju spółki, skalę reinwestycji, historyczny FCF, trend, dostępność finansowania, zadłużenie, liquidity runway, przyczynę ujemnego FCF. Hard EXCLUDE stosowany dopiero, gdy ujemny FCF jest częścią szerszego zestawu krytycznych problemów określonych przez hard-gate logic (np. ujemny FCF + malejące przychody + going-concern łącznie) — nigdy sam w sobie i nigdy automatycznie łagodzony wyłącznie przez etykietę „growth". Każdy wyjątek musi być oparty na konkretnych danych i audytowalny (zapisany w `analysis_sources`/`llm_raw_output`, nie tylko w konkluzji).

---

## IMPORTANT — do ustalenia przed V1

Właściciel zaakceptował jako zobowiązania (nie tylko rekomendacje): stworzenie operacyjnej rubryki confidence zamiast pozostawienia jej jako czystej samooceny LLM (dwa punkty niżej), oraz okresowy audyt próbki spółek odrzuconych przez pre-filter (false negatives) — oba do zaprojektowania szczegółowo w Fazie 4/5, nie tylko odnotowane jako ryzyko.

- Źródło listy uniwersum S&P 500 (nie „scraping Wikipedii" w produkcji) — patrz Decyzja D4.
- Forward P/E / estymaty analityków zwykle wymagają droższego tier u dostawcy — decyzja include/exclude dla V0/V1 (rekomendacja: exclude, patrz D8).
- Utrzymanie allowlisty domen IR dla (docelowo) 503 spółek to realna, powtarzalna praca ręczna, nigdzie w spec nieadresowana wprost — wymaga decyzji o skali na start (D9).
- Ścieżka błędu przy zniekształconym JSON z LLM: spec mówi „reject", ale nie mówi, co dalej (spółka znika z raportu? oznaczona PARTIAL?). Rekomendacja: oznaczyć jako PARTIAL ANALYSIS, nie milcząco pominąć.
- Confidence (HIGH/MEDIUM/LOW) jest w spec czysto samooceną LLM, bez zdefiniowanej reguły — to dokładnie ryzyko, przed którym ostrzega sam §25 („confidence must reflect evidence quality, not rhetorical certainty"), ale bez operacyjnego testu tej reguły. Potrzebny konkretny rubryk (np. liczba niezależnie potwierdzających źródeł, zgodność z danymi deterministycznymi).
- Źródło i granulacja klasyfikacji sektorowej (GICS sub-industry vs sector) — potrzebne do przełączania logiki z pkt 12, niespecyfikowane.
- Fałszywe negatywy pre-filtra są z definicji niewidoczne (spółka odrzucona nigdy nie trafia do LLM) — potrzebny okresowy manualny audyt próbki odrzuconych spółek, niezależny od formalnego backtestingu.
- **(Nowe, z MY HOLDINGS) Rekoncyliacja pozycji użytkownika z rzeczywistym rachunkiem maklerskim nie jest częścią systemu** (zgodnie z RULE 12 — brak integracji z brokerem) — dane w `purchase_transactions`/`sale_transactions` są tak dobre, jak ręczne wprowadzanie przez użytkownika. Warto rozważyć w V1.5/V2 prosty mechanizm „sanity check" (np. porównanie sumy zainwestowanego kapitału z oczekiwaniem użytkownika) — nie teraz, tylko odnotowane jako ryzyko jakości danych wejściowych.
- **(Nowe, z modułu BIOTECH External Validation) Brak rubryki dla confidence dotyczy teraz też oceny STRONG/MODERATE/LIMITED/INSUFFICIENT_DATA** (pkt 18.3–18.5) — ten sam brak operacyjnego testu „confidence odzwierciedla jakość dowodów, nie retorykę", tylko w nowym kontekście; jedna rubryka do zaprojektowania powinna objąć oba przypadki.
- **(Nowe, z modułu BIOTECH) Dokładna struktura pól ról badaczy w ClinicalTrials.gov API v2** (Principal Investigator/Study Chair/Study Director) nie została potwierdzona w tym przeglądzie — do zweryfikowania w oficjalnej dokumentacji przed implementacją Fazy 8, nie zakładać na pewno ścieżki pola.

---

## LATER — bezpieczne do odłożenia

- Rozszerzenie na Nasdaq 100/Europę/GPW — architektura już ma być config-driven, nie wymaga pracy teraz.
- Alerty e-mail/Telegram.
- Głębsze modele wyceny (analiza wrażliwości DCF) poza prostym 3-scenariuszowym intrinsic value.
- Płatne tiery danych analitycznych/estymat.
- Dane real-time/intraday — pipeline działa raz dziennie po zamknięciu rynku, płacenie za plan real-time byłoby czystym marnotrawstwem budżetu.
- Pełny portfolio management wykraczający poza minimalny zakres MY HOLDINGS (pkt 16.4) — np. alokacja, rebalancing, wielowalutowa konsolidacja portfela.

---

## DECISIONS — STATUS PO TURZE WŁAŚCICIELA (2026-09-20)

13 z 15 decyzji są **ZAMKNIĘTE** — poniższa tabela zawiera już nie „rekomendację", tylko dosłowną decyzję właściciela, z uzasadnieniem i wpływem na koszt/złożoność zachowanym dla kontekstu. D1 i D3 są **W TRAKCIE TECHNICZNEJ WERYFIKACJI** — reguła wyboru jest już ustalona przez właściciela (patrz kolumna „Decyzja właściciela"), pozostaje wyłącznie wykonanie researchu i zastosowanie tej reguły, nie kolejna decyzja właściciela. Lista decyzji **wciąż wymagających wyboru** — na samym końcu dokumentu.

| # | Decyzja | Status | Decyzja właściciela | Uzasadnienie / kontekst | Wpływ na koszt | Wpływ na złożoność |
|---|---|---|---|---|---|---|
| D1 | Dostawca danych finansowych | **W TRAKCIE WERYFIKACJI** | Jeszcze nie wybrany. Wykonać bezpośrednią weryfikację FMP i EODHD pod kątem: jakości danych, pokrycia, historycznego składu S&P 500 (D3), stabilności API, kosztu, prostoty architektury. Jeden główny dostawca + SEC EDGAR zawsze — **nie** integrować dwóch płatnych providerów bez konieczności. Jeżeli EODHD rozwiązuje jednocześnie bieżące dane finansowe i historical constituents w akceptowalnej cenie → **EODHD**; jeśli nie → **FMP**. Polygon/Massive odrzucone na V0/V1, chyba że podczas implementacji pojawi się konkretny problem, którego FMP/EODHD nie rozwiązują. | Reguła wyboru już ustalona — pozostaje wykonanie researchu | 0–100 USD/mies. różnicy zależnie od planu | Niska przy jednym dostawcy |
| D2 | Metoda point-in-time do backtestingu | **ZAMKNIĘTA — decyzja B** | Budujemy własną warstwę PIT na SEC XBRL `filed`. Nie akceptujemy backtestu na restated fundamentals udającym rzeczywisty stan wiedzy z historycznej daty. Nie kupujemy instytucjonalnego datasetu PIT na tym etapie. Przed pełną warstwą — prototyp dla 3–5 spółek (patrz Faza 5.1). | Jedyna opcja spójna z zasadą braku fabrykacji, przy zerowym koszcie licencyjnym | 0 USD (koszt czasu implementacji) | Średnia-wysoka — osobny moduł ekstrakcji |
| D3 | Źródło historycznego składu S&P 500 | **W TRAKCIE WERYFIKACJI** | Najpierw zweryfikować EODHD Historical Constituents oraz aktualny status FMP Legacy endpoint. Kolejność preferencji: (1) komercyjne, utrzymywane API przy rozsądnym koszcie; (2) drugie niezależne źródło jako cross-check; (3) darmowy zbiór społecznościowy wyłącznie jako dodatkowa walidacja, nigdy jedyne źródło prawdy. Jeżeli EODHD daje wiarygodny dataset od ok. 2012 lub wcześniej przy rozsądnym koszcie → preferować EODHD. Nie wydłużać backtestu kosztem survivorship bias. | Reguła wyboru już ustalona — pozostaje wykonanie researchu | Zależnie od wyniku weryfikacji; nieznany dla płatnego dodatku — do wyceny | Niska–średnia |
| D4 | Źródło listy aktualnego uniwersum S&P 500 | **ZAMKNIĘTA** | Endpoint wybranego dostawcy danych. Jeśli niedostępny w planie — najprostsze wiarygodne rozwiązanie zastępcze. Nie produkcyjny scraping Wikipedii jako podstawowe źródło. | Mniejsze ryzyko błędu niż scraping w produkcji | Zwykle brak dodatkowego kosztu | Niska |
| D5 | Baza danych | **ZAMKNIĘTA** | Zgodnie z rekomendacją: SQLite w V0, Supabase/Postgres w V1. Schema projektowana od początku pod migrację bez przebudowy modelu danych (patrz nota o przenośności w sekcji 5). | Unika przedwczesnej złożoności w V0; Supabase ma darmowy tier + UI czytelny dla osoby nietechnicznej | 0 USD na obu etapach (darmowe tiery) | Niska |
| D6 | Model Claude do warstwy jakościowej | **ZAMKNIĘTA** | Claude Sonnet 5 jako domyślny. Architektura umożliwia zmianę modelu przez config bez zmian w kodzie (patrz `llm.model`/`llm.escalation_model` w sekcji 6). Dopuszczony późniejszy re-run szczególnie niejednoznacznych analiz na mocniejszym modelu, wyłącznie jeśli testy pokażą realną poprawę jakości — nie domyślnie bez dowodu. | Sonnet 5 ok. 2,5× tańszy (2/10 USD za MTok vs 5/25 USD) | Sonnet 5 istotnie tańszy | Brak różnicy strukturalnej — parametr configu |
| D7 | Zakres sektorowy V0 | **ZAMKNIĘTA** | GENERAL w pierwszym V0. Banki, ubezpieczyciele i REIT-y czekają na osobne profile sektorowe (Faza 10). **BIOTECH traktowany osobno** — nie przepuszczany przez standardowy GENERAL scoring, dostaje odrębny model (patrz D15, sekcja 18). | To ok. 60–70 spółek BANK/INSURER/REIT wymagających innej logiki; bezpieczniej dowieźć rdzeń najpierw | Brak | Istotnie obniża złożoność V0 |
| D8 | Forward P/E i estymaty analityków | **ZAMKNIĘTA** | Exclude z V0/V1. Nie płacimy za droższe dane ani nie zwiększamy zależności od konsensusu analityków na tym etapie. Możliwy powrót później, jeśli okaże się, że wnosi istotną wartość. | Zwykle droższy tier u dostawcy, trudniejsze do zweryfikowania pierwotnie | Oszczędność (unikamy droższego planu) | Niższa (mniej pól do walidacji/źródłowania) |
| D9 | Skala allowlisty domen IR na start | **ZAMKNIĘTA** | Mały podzbiór rozwijany stopniowo. Nie tworzymy ręcznie allowlisty 503 spółek przed uruchomieniem. SEC EDGAR jest podstawą; IR dodawany dla spółek, które faktycznie trafiają do głębszej analizy/watchlisty/holdings. Zaprojektowana ścieżka późniejszej automatyzacji bezpiecznego wykrywania/weryfikacji domeny IR (patrz sekcja 9). | Zapobiega niekontrolowanemu obciążeniu ręcznemu na starcie | Koszt czasu własnego, nie budżetu | Niska — ogranicza zakres na start |
| D10 | Hosting/scheduler | **ZAMKNIĘTA** | GitHub Actions. Brak własnego VPS ani ręcznej administracji serwerem. | Zero administracji serwera, sekrety w GitHub UI, logi bez SSH | 0 USD (mieści się w darmowych minutach) | Niska |
| D11 | Zakres krzyżowej weryfikacji z SEC XBRL | **ZAMKNIĘTA** | Tylko pola kluczowe dla scoringu i hard gates: revenue, cash, debt, net income, kluczowe elementy FCF, oraz inne pola bezpośrednio uruchamiające hard gate. Nie cross-checkujemy każdego pola tylko dlatego, że jest to technicznie możliwe. | Pełna weryfikacja każdego pola zwiększyłaby liczbę żądań do EDGAR (limit 10 req/s) bez proporcjonalnej korzyści | Brak dodatkowego kosztu API (EDGAR darmowy) | Umiarkowana, ograniczona zakresem |
| D12 | Metoda rozliczania kosztu przy częściowej sprzedaży | **ZAMKNIĘTA** | FIFO jako domyślna metoda wewnętrzna. Wyłącznie do analizy inwestycji i prezentowania wyniku pozycji — **nie do generowania deklaracji podatkowej**. `cost_basis_method` jako parametr konfiguracyjny, zmienny później bez przebudowy systemu (już tak zaprojektowane — sekcja 6). | To wyłącznie wewnętrzne liczenie realized/unrealized P/L; system nie jest narzędziem podatkowym | Brak | Niska — jeden parametr configu |
| D13 | Cadence monitoringu MY HOLDINGS | **ZAMKNIĘTA** | TRIGGER_GATED. Codziennie tani deterministyczny monitoring; pełna analiza Claude uruchamia się po istotnym triggerze, po nowym istotnym filingu, lub po zdarzeniu mogącym zmienić Purchase Thesis. System **nie może polegać wyłącznie na zmianie ceny jako triggerze** (już tak zaprojektowane — `deterministic_pretrigger_thresholds` w sekcji 6 zawiera triggery niezależne od ceny: dywidenda, filing, dźwignia). | Nie chcemy codziennie płacić za pełną analizę LLM każdej posiadanej spółki | (a) najdroższe, (b) marginalne | Umiarkowana — logika pre-triggera reużywa silnik z pre-filtra |
| D14 | Okno czasowe backtestingu | **ZAMKNIĘTA** | Ok. 2012 → dziś, status LIMITED_BUT_HONEST. Nie wydłużamy sztucznie, jeśli wymagałoby to danych powodujących survivorship bias lub look-ahead bias. Powrót do decyzji możliwy później, jeśli pojawi się wiarygodne źródło w rozsądnej cenie. | Realizuje zasadę „priorytetem jest brak survivorship bias, nie maksymalna długość backtestu" | Bez dodatkowego kosztu teraz | Brak dodatkowej złożoności |
| D15 | Miejsce modułu BIOTECH w harmonogramie | **ZAMKNIĘTA — nowy wariant: CORE FIRST, BIOTECH SECOND** | Kolejność: (1) V0 GENERAL core, (2) V0.5 backtesting/kalibracja core, (3) V1 daily scanner/dashboard/watchlist GENERAL, (4) MY HOLDINGS podstawowa obsługa, (5) BIOTECH MODULE — osobny pipeline/scoring (Fazy 8–9), (6) dopiero później pełne BANK/INSURER/REIT (Faza 10), jeśli w ogóle potrzebne. BIOTECH **nie jest** uzależniony od ukończenia BANK/INSURER/REIT — ma wyższy priorytet produktowy. External Validation (sekcja 18.1–18.6) to tylko jedna warstwa pełnego modelu; reszta zakresu zarejestrowana w 18.7 jako scope dla Fazy 8 (design), niezaprojektowana w tej turze. | Biotech jest istotnym elementem docelowego produktu; jednocześnie V0 nie ma budować dwóch silników naraz | Brak dodatkowego kosztu teraz; Faza 8/9 poniesie koszt integracji CT.gov/OpenAlex/ROR gdy do niej dojdzie | Plan implementacji zaktualizowany (sekcja 15): Faza 7 MY HOLDINGS → Faza 8 BIOTECH design → Faza 9 BIOTECH implementacja → Faza 10 BANK/INSURER/REIT (opcjonalnie) |

---

## Podsumowanie

Rdzeń specyfikacji (rozróżnienie price decline vs value destruction, moduł anty-konfirmacyjny, hard gates niezależne od total score, wersjonowany audit trail, zasada „nic nie fabrykować") jest spójny i nie wymagał zmiany celu produktu ani metodologii scoringu. Trzy z pięciu pierwotnych BLOCKERÓW są zamknięte na poziomie decyzji architektonicznej i wbudowane w schema/architekturę (fabrykacja źródeł, numery stron SEC HTML, automatyczny EXCLUDE dla ujemnego FCF). Dwa pozostają otwarte, ale mają teraz konkretną, zweryfikowaną ścieżkę zamknięcia zamiast ogólnego „do ustalenia": point-in-time fundamentals przez SEC XBRL `filed`, historyczny skład indeksu przez jeden z trzech zidentyfikowanych kandydatów (do bezpośredniej weryfikacji).

Moduł MY HOLDINGS / EXIT MONITORING został w pełni zaprojektowany na poziomie schematu bazy danych, event modelu i audit trail, świadomie reużywając istniejące mechanizmy (Source Assembly Layer, Change Detection, silnik scoringu) zamiast budowania drugiego, niezależnego systemu. Przy okazji researchu do BLOCKER 2 wykryto i naprawiono realną lukę w pierwotnym projekcie (identyfikacja spółek po tickerze zamiast po CIK) — dotyczy to zarówno backtestingu, jak i integralności danych w MY HOLDINGS.

W tej turze zaprojektowano dodatkowo moduł BIOTECH: EXTERNAL VALIDATION & RESEARCH NETWORK (sekcja 18) — relacje COMPANY→ASSET→TRIAL→PERSON→INSTITUTION→PUBLICATION→PARTNERSHIP→FUNDING w zwykłej relacyjnej bazie (graph DB świadomie odrzucona jako nieproporcjonalna do skali), nowe źródła (ClinicalTrials.gov API v2, OpenAlex, ROR), oraz structured output wymuszający rozróżnienie „obecność w badaniu" od „zaangażowanie materialnych zasobów" i „publikacja o mechanizmie" od „dowód skuteczności produktu" — dokładnie te rozróżnienia, o które proszono. Moduł w całości reużywa Source Assembly Layer i wzorzec `verified`/`UNVERIFIED` z BLOCKER 3, zamiast tworzyć osobny system źródeł.

**W tej turze (v1.3) właściciel przejrzał i rozstrzygnął 15 decyzji.** 13 zamknięte bezpośrednio; D1 i D3 przechodzą w status „w trakcie technicznej weryfikacji" z regułą wyboru już ustaloną. Najważniejsza zmiana merytoryczna: **D15 odrzuca pierwotną rekomendację** („biotech po pełnym BANK/INSURER/REIT") na rzecz „CORE FIRST, BIOTECH SECOND" — BIOTECH MODULE ma wyższy priorytet produktowy niż pełne pokrycie sektorów specjalnych i nie jest uzależniony od ich ukończenia. Plan implementacji (sekcja 15) przebudowany: Faza 7 (MY HOLDINGS) → Faza 8 (BIOTECH MODULE — DESIGN, pełny zakres zarejestrowany w 18.7, nieszczegółowy) → Faza 9 (BIOTECH MODULE — IMPLEMENTACJA, obejmująca External Validation z sekcji 18.1–18.6 jako jeden komponent) → Faza 10 (BANK/INSURER/REIT pełne, opcjonalnie, jeśli w ogóle potrzebne).

Nie rozpoczęto implementacji.

---

## DECYZJE WCIĄŻ WYMAGAJĄCE TWOJEGO WYBORU

**Zero.** Po tej turze nie ma otwartej decyzji, która czeka na Twój osąd.

D1 (dostawca danych) i D3 (źródło historycznego składu S&P 500) pozostają formalnie „w trakcie" — ale to zadanie badawcze do wykonania przeze mnie (bezpośrednia weryfikacja FMP/EODHD wg kryteriów z D1 i D3), nie kolejne pytanie do Ciebie. Regułę wyboru już ustaliłaś: preferencja dla jednego dostawcy + SEC EDGAR, EODHD jeśli rozwiąże jednocześnie dane bieżące i historyczny skład w rozsądnej cenie, inaczej FMP; dla D3 kolejność komercyjne→cross-check→społecznościowe, priorytet dla braku survivorship bias nad długością backtestu. Gdy wrócę z wynikami weryfikacji, zastosuję tę regułę i pokażę wynik — zapytam ponownie tylko, jeśli research da wynik niejednoznaczny w sposób, którego Twoja reguła nie pokrywa (np. oba źródła równie dobre i równie drogie).

Jedyny kolejny naturalny krok wymagający Twojej zgody, nie wyboru: czy mam teraz przejść do wykonania tej weryfikacji dostawców (D1/D3), czy wolisz najpierw przejrzeć samą zaktualizowaną roadmapę powyżej.

---

## Sources

- [Pricing Plans - Financial Modeling Prep API | FMP](https://site.financialmodelingprep.com/pricing-plans)
- [Pricing Plans - Affordable Financial Data API | FMP](https://site.financialmodelingprep.com/developer/docs/pricing)
- [Free and paid plans for Historical Prices and Fundamental Financial Data API | EODHD](https://eodhd.com/pricing)
- [Historical Prices and Fundamental Financial Data API | EODHD](https://eodhd.com/commercial-pricing)
- [12 Best Financial Market APIs for Real-Time Data in 2026](https://blog.apilayer.com/12-best-financial-market-apis-for-real-time-data-in-2026/)
- [Polygon.io Review 2026 — Pricing, Features, Pros & Cons](https://tradingtoolshub.com/review/polygon-io/)
- [SEC.gov | Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC.gov | EDGAR Application Programming Interfaces (APIs)](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [S&P and Dow Jones Indices Historical Constituents API | EODHD](https://eodhd.com/marketplace/unicornbay/spglobal)
- [S&P 500 Historical Constituents Data | EODHD APIs Blog](https://eodhd.com/financial-apis-blog/sp-500-historical-constituents-data)
- [[reworked] S&P 500 Historical Constituents | EODHD APIs Blog](https://eodhd.com/financial-apis-blog/reworked-sp-500-historical-constituents)
- [Historical S&P 500 Constituents API - Legacy | Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs/historical-sp-500-companies-api)
- [GitHub - fja05680/sp500: Current and Historical Lists of S&P 500 components since 1996](https://github.com/fja05680/sp500)
- [How To Get Historical S&P 500 Constituents Data For Free | IBKR Quant Blog](https://www.interactivebrokers.com/campus/ibkr-quant-news/how-to-get-historical-sp-500-constituents-data-for-free/)
- [As-Reported vs Restated Financial Data: Why the Difference Matters for Backtesting](https://dev.to/tradevodata/as-reported-vs-restated-financial-data-why-the-difference-matters-for-backtesting-1big)
- [How to Build a Point-in-Time Fundamentals Database from SEC EDGAR (and When Not To)](https://dev.to/tradevodata/how-to-build-a-point-in-time-fundamentals-database-from-sec-edgar-and-when-not-to-2gn6)
- [Point in Time Fundamentals | LSEG Data & Analytics](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/point-in-time-fundamentals)
- [ClinicalTrials.gov API v2 Reference](https://conorscode.github.io/clinicaltrials-api-reference/)
- [ClinicalTrials.gov API — Search Areas | ClinicalTrials.gov](https://clinicaltrials.gov/data-api/about-api/search-areas)
- [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api)
- [Authors Overview | OpenAlex Help Center](https://help.openalex.org/data/authors/)
- [API reference | OpenAlex Help Center](https://developers.openalex.org/api-reference/introduction)
- Ceny Claude API (Sonnet 5: 2 USD/10 USD za MTok wejście/wyjście) — wewnętrzna, aktualna tabela cennika Anthropic (cache 2026-06-24).
