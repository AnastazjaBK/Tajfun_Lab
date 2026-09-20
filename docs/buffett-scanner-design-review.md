# BUFFETT OPPORTUNITY SCANNER — Technical Design Review

**Status:** Review specyfikacji v1.0. Implementacja NIE została rozpoczęta.
**Data przeglądu:** 2026-09-20
**Zakres:** Odpowiedź na pytania 1–16 z briefu + krytyczny przegląd (BLOCKER/IMPORTANT/LATER) + lista decyzji właściciela.

## Metodologia i zastrzeżenia

Zgodnie z zasadą „nie zgaduj": poniżej rozróżniam trzy kategorie treści.

- **Ustalone z dokumentacji/wiedzy technicznej** — np. architektura, schematy, zasady SEC EDGAR (limit 10 req/s, brak wymogu klucza API), aktualny cennik Claude API (patrz niżej).
- **Zweryfikowane wyszukiwaniem w sieci we wrześniu 2026, ale zmienne w czasie** — cenniki dostawców danych finansowych. Oznaczone wprost jako „do potwierdzenia na stronie dostawcy przed zatwierdzeniem budżetu" wraz ze źródłem.
- **Hipotezy wymagające Twojej decyzji lub kalibracji przez backtesting** — oznaczone `UNCALIBRATED` / w sekcji „DECISIONS REQUIRED FROM OWNER".

Żadna liczba finansowa, próg ani cennik w tym dokumencie nie jest fabrykowany — tam, gdzie nie mam pewności, piszę to wprost zamiast dopowiadać.

---

## 1. Architektura V0 — schemat przepływu danych

```
[Config: universe.yaml, scoring.yaml, gates.yaml]  ← jedyne źródło progów/wag
            │
            ▼
[Scheduler]  (GitHub Actions scheduled workflow — patrz pkt 2)
            │  uruchamia daily_run.py raz dziennie, po zamknięciu rynku
            ▼
[1. Market Data Ingestion]        ← Financial Data Provider (ceny EOD, wolumen)
            │  zapis → price_daily
            ▼
[2. Decline Scanner]              ← czysty Python (pandas): %chg, drawdown,
            │                        rel. volume — bez LLM
            │  zapis → daily_scan_results
            ▼
[3. Fundamentals Ingestion]       ← Financial Data Provider (raporty finansowe)
            │  zapis → fundamentals_raw
            ▼
[4. Quantitative Pre-filter]      ← czysty Python: FCF, dźwignia, marże,
            │                        EXCLUDE / FLAG / PASS — bez LLM
            │  zapis → prefilter_results
            ▼
[5. Candidate shortlist]           (docelowo ~5–15 spółek/dzień z 503)
            │
            ▼
[6. Source Assembly]              ← SEC EDGAR (CIK lookup, lista filingów,
            │                        pełnotekstowe wyszukiwanie) + skromna
            │                        allowlista domen IR (patrz pkt 9)
            │  zapis → analysis_sources (tylko realnie pobrane, z hashem treści)
            ▼
[7. Claude API — Qualitative Research]
            │  wejście: deterministyczne wskaźniki + WYŁĄCZNIE pobrane źródła
            │  wyjście: JSON wg schematu (pkt 8), walidowany, malformed → reject
            ▼
[8. Scoring Engine]               ← czysty Python: łączy sub-wyniki
            │                        deterministyczne i jakościowe wg wag
            │                        z configu, stosuje hard gates
            │  zapis → analyses (immutable, wersjonowane)
            ▼
[9. Database]                     (SQLite w V0 → Postgres/Supabase w V1)
            │
            ▼
[10. Daily report]                (V0: plik Markdown/CLI; V1: dashboard z DB)
            │
            ▼
          [User]
```

Kluczowa zasada architektoniczna: **LLM nigdy nie jest wejściem do kroku 1–4 i 8** — tam wyłącznie deterministyczny kod. LLM wchodzi dopiero po redukcji zbioru przez tani filtr ilościowy (realizacja §35 spec).

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
| **Financial Modeling Prep (FMP)** | Szeroki zakres fundamentów (>30 lat, wielu rynków), EOD, dane sektorowe, ratingi. Darmowy tier: 250 wywołań/dzień (za mało na pełne 503 spółki dziennie — potrzebny płatny plan). | Brak bezpośrednich linków do konkretnych stron/sekcji filingów SEC; brak natywnej weryfikacji „point-in-time" danych fundamentalnych do celów backtestingu (do potwierdzenia w dokumentacji API — patrz BLOCKER #1); dane analityczne/estymaty zwykle w droższym tier. |
| **EODHD (EOD Historical Data)** | Podobny zakres do FMP (60+ giełd, 150k+ tickerów), osobny pakiet „Fundamentals Data Feed", relatywnie tańszy przy porównywalnym zakresie. | Te same braki co FMP: brak linkowania do konkretnych fragmentów filingów, brak gwarancji point-in-time dla backtestingu, ograniczone dane analityczne. |
| **Polygon.io (od X 2025 rebrand na „Massive")** | Bardzo dobra jakość danych cenowych/wolumenowych, WebSockety, długa historia cen w wyższych planach. | Historycznie słabszy zakres fundamentów finansowych względem FMP/EODHD (do zweryfikowania po rebrandzie — cennik i oferta były w trakcie zmiany w momencie tego przeglądu); może wymagać sparowania z drugim dostawcą tylko dla fundamentów, co podnosi koszt i złożoność integracji. Przewaga real-time nie jest potrzebna — pipeline działa raz dziennie po zamknięciu rynku. |

**Rekomendacja:** jeden dostawca (FMP lub EODHD — porównywalny zakres) do cen EOD + fundamentów, plus SEC EDGAR (darmowe) jako obowiązkowa warstwa źródeł pierwotnych. Nie rekomenduję Polygon/Massive na start — jego przewaga (real-time) nie jest wymaganiem tego produktu, a fundamenty są słabszym punktem. Ostateczny wybór między FMP a EODHD — patrz Decyzja D1.

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
| **RAZEM (orientacyjnie)** | **~70–200 USD/mies.** | Dolna granica przy tańszym dostawcy danych i darmowych tierach DB/hostingu; górna przy droższym planie danych. |

**Rekomendacja przed zatwierdzeniem budżetu:** sprawdzić aktualny cennik FMP/EODHD bezpośrednio na ich stronach (linki w Sources), bo dokładne kwoty planów płatnych nie były w pełni dostępne w wynikach wyszukiwania.

---

## 5. Proponowany database schema

```sql
-- Uniwersum i przynależność do indeksu (point-in-time, potrzebne do backtestingu)
companies(ticker PK, cik, name, sector, industry, sub_industry,
          sector_profile ENUM('GENERAL','BANK','INSURER','REIT'),
          is_active BOOLEAN, created_at)

universe_membership(id PK, ticker FK, index_name, start_date, end_date)

-- Dane rynkowe i fundamentalne (surowe, nienadpisywane)
price_daily(ticker FK, date, open, high, low, close, adj_close, volume,
            source, ingested_at, PRIMARY KEY(ticker, date))

fundamentals_raw(id PK, ticker FK, fiscal_period, period_end_date, filed_date,
                 statement_type, line_item, value, unit, source, source_doc_id,
                 ingested_at)
  -- format długi (long), żeby korekty/restatements nie nadpisywały
  -- wartości "as reported" — kluczowe dla backtestingu bez look-ahead bias

derived_metrics(id PK, ticker FK, as_of_date, metric_name, value,
                 calc_version, inputs_hash)

-- Wersjonowanie modelu scoringu
scoring_model_versions(version PK, description, weights_json, gates_json,
                        effective_from, effective_to, created_at)

-- Wyniki analiz — IMMUTABLE, nowa wersja = nowy wiersz, nigdy UPDATE
analyses(analysis_id PK, ticker FK, run_date, price_at_analysis,
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
watchlist(watchlist_id PK, ticker FK, added_date, added_price,
          current_status, last_analysis_id FK,
          next_review_trigger JSON, created_at, updated_at)

-- Decyzje użytkownika (workflow, NIE broker)
user_decisions(decision_id PK, ticker FK, analysis_id FK NULL,
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

---

## 6. Proponowany configuration schema (YAML)

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
  flag_rules: [...]       # patrz Zmiana #2 — rozróżnienie EXCLUDE/FLAG
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
  model: claude-sonnet-5
  max_output_tokens: 4000
  schema_version: "1.0"
  reject_on_schema_violation: true
  allow_citations_outside_source_packet: false   # patrz Zmiana #3

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
```

Zasada: **każdy próg ma jawne `status: UNCALIBRATED`**, dopóki backtesting (V0.5) go nie zatwierdzi — nic nie jest domyślnie „prawdą".

---

## 7. Podział odpowiedzialności

| Warstwa | Odpowiada za | NIE robi |
|---|---|---|
| **Deterministyczny Python** | Wszystkie obliczenia liczbowe (wzrosty, FCF, dźwignia, drawdown, margin of safety), arytmetyka scoringu, hard gates, logika triggerów watchlisty, budowa URL-i do SEC EDGAR, walidacja schematu JSON z LLM, zapisy do DB | Interpretacji jakościowej, oceny moatu, klasyfikacji fear/uncertain/structural |
| **Claude API** | Interpretacja modelu biznesowego, ocena dowodów na przewagę konkurencyjną, ocena capital allocation, wnioskowanie o przyczynie spadku i klasyfikacja TEMPORARY/UNCERTAIN/STRUCTURAL (na bazie dostarczonych deterministycznych danych o skali/tempie spadku), bull/bear case, thesis invalidation, dobór i cytowanie WYŁĄCZNIE z dostarczonej listy źródeł | Obliczeń, które da się policzyć deterministycznie; generowania własnych URL-i/numerów stron |
| **Dostawca danych finansowych** | Surowe ceny i dane fundamentalne | Interpretacji, linkowania do fragmentów dokumentów, weryfikacji źródeł |
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

---

## 9. Pozyskiwanie i weryfikacja źródeł pierwotnych

**SEC EDGAR (priorytet #1, zgodnie z §17):**
- Mapowanie ticker → CIK przez darmowy plik `company_tickers.json`.
- Lista filingów przez EDGAR Submissions API (`data.sec.gov`).
- Dane XBRL (company-facts / company-concept) do krzyżowej weryfikacji liczb od dostawcy danych (wykrywanie DATA CONFLICT, §24).
- Pełnotekstowe wyszukiwanie (`efts.sec.gov/LATEST/search-index`) do lokalizowania konkretnych fraz (np. „going concern") w filingach od 2001.
- Wymogi techniczne: deklarowany User-Agent z danymi kontaktowymi, limit **10 req/s**, brak wymaganego klucza API — ale wymagane cache'owanie, żeby nie przekraczać limitu przy 503 spółkach dziennie.

**Investor Relations:** SEC EDGAR nie ma odpowiednika dla dokumentów IR (prezentacje, press release). Brak scentralizowanego, weryfikowalnego indeksu → proponowana allowlista domen IR budowana ręcznie/stopniowo (patrz Decyzja D9), rozwiązywana najpierw z oficjalnej strony spółki wskazanej na stronie tytułowej 10-K, nigdy z wyników wyszukiwarki internetowej bez weryfikacji.

**Zasada nadrzędna (implementacja RULE 1 i §17):** każdy wiersz w `analysis_sources` musi odpowiadać realnie wykonanemu żądaniu HTTP z kodem 200 i zapisanym hashem treści w trakcie danego uruchomienia pipeline'u — nigdy nie jest zapisywany na podstawie samego twierdzenia LLM.

---

## 10. Tworzenie bezpośrednich linków w „WHAT YOU SHOULD VERIFY"

- URL do dokumentu SEC EDGAR jest deterministycznie budowalny z danych Submissions API: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-no-bez-myślników}/{primary-document}`. **Link buduje kod, nie LLM.**
- Numer strony: HTML 10-K/10-Q na EDGAR **nie mają natywnej paginacji** — wymuszanie numeru strony dla tych dokumentów oznacza fabrykację (patrz Zmiana #1 niżej). Numer strony podawany tylko dla źródeł PDF z potwierdzoną paginacją (np. prezentacje inwestorskie), gdzie biblioteka do ekstrakcji tekstu z PDF potwierdza pozycję dopasowanego fragmentu.
- Dla dokumentów HTML: zamiast strony — numer noty/pozycji (np. „Note 8 — Long-Term Debt", „Item 7A") plus dokładny cytat użyty do lokalizacji fragmentu przez wyszukiwanie pełnotekstowe.
- Dokumenty IR: link tylko jeśli realnie pobrany i zahashowany w danym uruchomieniu; w przeciwnym razie wyświetlić `SOURCE NOT VERIFIED` zgodnie z §17.

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

---

## 12. Sektory wymagające odmiennego traktowania

| Sektor | Problem ze standardowymi metrykami | Metryki zastępcze |
|---|---|---|
| **Banki** | Dług to „towar", nie dźwignia w zwykłym sensie — Net Debt/EBITDA, EV/EBITDA nie mają sensu | CET1/Tier 1, marża odsetkowa netto (NIM), wskaźnik efektywności kosztowej, ROTCE/ROE, P/TBV, trend rezerw na straty kredytowe |
| **Ubezpieczyciele** | Zysk netto silnie zniekształcony przez rezerwy; FCF nie jest głównym miernikiem | Combined ratio, rozwój rezerw szkodowych, float i koszt floatu, wartość księgowa na akcję, P/B, wskaźniki kapitału regulacyjnego (RBC) |
| **REIT-y** | Amortyzacja realna, ale niegotówkowa i specyficzna dla branży — zysk netto/FCF wprost mylące | FFO/AFFO zamiast zysku netto/FCF, NAV vs P/AFFO, wzrost NOI same-store, obłożenie, payout liczony względem AFFO (nie netto — inaczej payout ratio strukturalnie >100%) |
| **Spółki przedprzychodowe/biotech, wysoki wzrost reinwestujący cały FCF** | Reguła „exclude persistent negative FCF" z §7 wykluczyłaby je z definicji, mimo że mogą być wysokiej jakości biznesami | Wymaga świadomego wyjątku sektorowego lub wyłączenia z zakresu V0 (patrz BLOCKER #5 i Decyzja D7) |

**Rekomendacja V0:** pole `sector_profile` w configu (GENERAL / BANK / INSURER / REIT) przełączające zestaw metryk zasilających Financial Quality/Safety/Valuation. Domyślnie GENERAL dla ok. 440/503 spółek S&P 500; sektory specjalne dodać po ustabilizowaniu silnika na „zwykłych" spółkach (patrz Decyzja D7).

---

## 13. Strategia backtestingu bez look-ahead bias

Dwa fundamentalne ryzyka, oba oznaczone jako BLOCKER niżej:

1. **Dane fundamentalne „as reported" vs „restated".** Większość tanich API fundamentalnych zwraca najnowsze, skorygowane dane — nie to, co było wiadome w danym dniu historycznym. Jedyne wiarygodne, darmowe źródło point-in-time to SEC XBRL (company-facts), gdzie każdy fakt ma pole `filed` (data złożenia) — pozwala zrekonstruować stan wiedzy na dowolną historyczną datę, ale wymaga własnej warstwy ekstrakcji, nie jest to „gotowe" u żadnego z porównanych dostawców.
2. **Survivorship bias.** Backtest musi używać historycznego składu S&P 500 (spółka, która wypadła z indeksu z powodu problemów finansowych, musi pozostać w uniwersum na daty, gdy była członkiem) — żaden z trzech porównanych dostawców nie oferuje w oczywisty sposób czystego, historycznego API członkostwa w indeksie.

Dodatkowe zasady:
- Ceny użyte w backteście muszą być snapshotem na datę decyzji, nigdy przyszłym zamknięciem.
- Warstwa jakościowa (LLM) w backteście musi widzieć wyłącznie dokumenty złożone on/before data symulacji (filtrowanie po `filed_date` w EDGAR) — ale pełne wyeliminowanie „wiedzy z przyszłości" modelu językowego (wynikającej z jego danych treningowych) nie jest w pełni możliwe, tylko ograniczalne instrukcjami promptu. To zaakceptowane ograniczenie, nie coś do „naprawienia" w V0.5.
- Mierzyć nie tylko zwroty, ale i trafność klasyfikacji TEMPORARY vs STRUCTURAL — to jest właściwy test jakości modelu, nie sama stopa zwrotu (zgodnie z §30).

---

## 14. Plan testów dla V0

- **Testy jednostkowe obliczeń deterministycznych** — wzrosty, wskaźniki, FCF, payout ratio, drawdown %, margin of safety — na zweryfikowanych ręcznie wartościach referencyjnych dla 2–3 realnych spółek.
- **Testy arytmetyki scoringu** — sumowanie, hard gates na wartościach granicznych.
- **Testy walidacji schematu** — zniekształcony JSON z LLM (brak pola, zły typ, wynik poza zakresem) → reject, nie ciche „naprawianie".
- **Testy brakujących/sprzecznych danych** — brak wartości → `DATA UNAVAILABLE` propaguje się, nigdy nie jest traktowane jako 0; dwa źródła się różnią → `DATA CONFLICT` zapisane.
- **Testy trwałości** — niemutowalność `analyses`, logika triggerów watchlisty, przejścia statusów (WATCH→REJECT→ponowne pojawienie się z „MATERIAL CHANGE DETECTED").
- **Testy integracyjne z nagranymi fixture'ami** — nagrane raz odpowiedzi API (podejście VCR/cassette) dla 3–5 tickerów obejmujących profile GENERAL/BANK/REIT, odtwarzane w CI bez zależności od kosztu/dostępności live API.
- **Testy odporności na awarie** — API danych finansowych padło → pipeline zgłasza PARTIAL, nie fabrykuje; LLM padł/timeout → wynik ilościowy zachowany, jakościowy oznaczony jako niekompletny (§38).

---

## 15. Plan implementacji — małe etapy

**Faza 0 — fundament**
0.1 Szkielet repo, loader configu (pydantic), sekrety przez zmienne środowiskowe.
0.2 Ingest uniwersum (lista S&P 500), tabela `companies`.
0.3 Ingest cen dla 5–10 tickerów testowych, tabela `price_daily`.
0.4 Decline scanner (czysta kalkulacja, testy jednostkowe).

**Faza 1 — fundamenty i pre-filter**
1.1 Ingest fundamentów (rachunek wyników/bilans/cash flow) dla tych samych tickerów.
1.2 Silnik wskaźników deterministycznych + testy.
1.3 Logika EXCLUDE/FLAG sterowana configiem (progi `UNCALIBRATED`).

**Faza 2 — warstwa źródeł**
2.1 Mapowanie CIK + pobieranie listy filingów z EDGAR.
2.2 Budowa „source packet" (wyłącznie zweryfikowane URL-e, hash treści).
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
5.1 Rozwiązanie problemu point-in-time (BLOCKER #1/#2 niżej).
5.2 Zbiór historycznego składu S&P 500.
5.3 Harness backtestu + pierwsza kalibracja progów/wag.

**Faza 6 (= V1)** — pełny przebieg na 503 spółkach, DB na skalę produkcyjną, dashboard, watchlist, automatyzacja dzienna (zgodnie z zakresem spec).

Każda faza powinna być samodzielnie testowalna na małej próbce tickerów przed skalowaniem do pełnych 503.

---

## KRYTYCZNY PRZEGLĄD SPECYFIKACJI

### BLOCKER — do rozwiązania przed rozpoczęciem budowy

**B1. Point-in-time dane fundamentalne dla backtestingu.** Tani dostawca danych prawdopodobnie zwraca wyłącznie najnowsze, skorygowane („restated") dane finansowe, nie stan wiedzy z danego dnia historycznego. Bez tego backtesting narusza wprost wymóg §30 („no look-ahead bias"). Wymaga jawnej weryfikacji u dostawcy lub budowy własnej warstwy na SEC XBRL (więcej pracy inżynieryjnej, ale zerowy koszt krańcowy).

**B2. Historyczny skład S&P 500 (survivorship bias).** Żaden z trzech porównanych dostawców nie oferuje w oczywisty sposób czystego API historycznego członkostwa w indeksie. Backtest bez tego jest strukturalnie zniekształcony (spółki, które upadły/wypadły z indeksu, znikają z próby) — wnioski z takiego backtestu byłyby niewiarygodne, mimo pozornej poprawności metodologicznej.

**B3. LLM nie może być jedyną barierą przed fabrykacją URL-i/cytatów.** Spec polega głównie na instrukcji promptowej („must never fabricate URLs"). To za mało przy systemie, którego głównym walorem jest wiarygodność źródeł (RULE 1, RULE 5). Wymagana jest bariera architektoniczna: deterministyczny post-processing odrzucający/usuwający każdy URL lub numer strony niepochodzący z dostarczonej, zweryfikowanej listy źródeł.

**B4. Wymóg „numer strony" dla dokumentów SEC HTML jest technicznie niespełnialny.** Większość filingów 10-K/10-Q na EDGAR to HTML bez natywnej paginacji. Utrzymanie wymogu „Page: XX" jak w przykładzie §16 wymusza fabrykację przy pierwszym uruchomieniu na najważniejszym (priorytet #1) typie źródła. Patrz Zmiana #1.

**B5. Reguła automatycznego EXCLUDE dla trwałych strat/ujemnego FCF (§7) jest wewnętrznie sprzeczna z własnym zastrzeżeniem spec** („not every abnormal metric should result in automatic exclusion"), a przy dosłownym zastosowaniu systemowo wyklucza legalne modele biznesowe (reinwestujący wzrost, asset-light, wczesna faza). Patrz Zmiana #2.

### IMPORTANT — do ustalenia przed V1

- Źródło listy uniwersum S&P 500 (nie „scraping Wikipedii" w produkcji) — patrz Decyzja D4.
- Forward P/E / estymaty analityków zwykle wymagają droższego tier u dostawcy — decyzja include/exclude dla V0/V1 (rekomendacja: exclude, patrz D8).
- Utrzymanie allowlisty domen IR dla (docelowo) 503 spółek to realna, powtarzalna praca ręczna, nigdzie w spec nieadresowana wprost — wymaga decyzji o skali na start (D9).
- Ścieżka błędu przy zniekształconym JSON z LLM: spec mówi „reject", ale nie mówi, co dalej (spółka znika z raportu? oznaczona PARTIAL?). Rekomendacja: oznaczyć jako PARTIAL ANALYSIS, nie milcząco pominąć.
- Confidence (HIGH/MEDIUM/LOW) jest w spec czysto samooceną LLM, bez zdefiniowanej reguły — to dokładnie ryzyko, przed którym ostrzega sam §25 („confidence must reflect evidence quality, not rhetorical certainty"), ale bez operacyjnego testu tej reguły. Potrzebny konkretny rubryk (np. liczba niezależnie potwierdzających źródeł, zgodność z danymi deterministycznymi).
- Źródło i granulacja klasyfikacji sektorowej (GICS sub-industry vs sector) — potrzebne do przełączania logiki z pkt 12, niespecyfikowane.
- Fałszywe negatywy pre-filtra są z definicji niewidoczne (spółka odrzucona nigdy nie trafia do LLM) — potrzebny okresowy manualny audyt próbki odrzuconych spółek, niezależny od formalnego backtestingu.

### LATER — bezpieczne do odłożenia

- Rozszerzenie na Nasdaq 100/Europę/GPW — architektura już ma być config-driven, nie wymaga pracy teraz.
- Monitoring portfela / wzbogacenie statusu BOUGHT.
- Alerty e-mail/Telegram.
- Głębsze modele wyceny (analiza wrażliwości DCF) poza prostym 3-scenariuszowym intrinsic value.
- Płatne tiery danych analitycznych/estymat.
- Dane real-time/intraday — pipeline działa raz dziennie po zamknięciu rynku, płacenie za plan real-time byłoby czystym marnotrawstwem budżetu.

---

## Proponowane zmiany do specyfikacji

### Zmiana #1 — numer strony dla dokumentów SEC

**Obecne wymaganie (§16):** „Page: XX, if available" jako standardowy element pakietu weryfikacyjnego dla dokumentów SEC.

**Proponowana zmiana:** Podawać numer strony wyłącznie dla źródeł PDF z potwierdzoną paginacją (np. prezentacje inwestorskie). Dla dokumentów HTML z EDGAR (większość 10-K/10-Q) podawać zamiast tego numer/nazwę noty lub pozycji (np. „Note 8", „Item 7A") plus dokładny cytat użyty do lokalizacji fragmentu.

**Uzasadnienie:** HTML 10-K/10-Q na EDGAR nie mają natywnej paginacji — wymuszenie numeru strony zmusza system do zgadywania.

**Konsekwencje pozostawienia obecnego rozwiązania:** Presja na LLM, by podać nieistniejącą lub błędną liczbę strony w większości przypadków (bo filingi SEC to głównie HTML), co narusza RULE 1 już przy pierwszym uruchomieniu produktu.

### Zmiana #2 — automatyczne EXCLUDE dla strat/ujemnego FCF

**Obecne wymaganie (§7):** Automatyczne EXCLUDE m.in. dla „persistent net losses" / „persistent negative free cash flow" bez rozróżnienia kontekstu biznesowego.

**Proponowana zmiana:** Domyślnie traktować oba sygnały jako FLAG FOR REVIEW, nie EXCLUDE, dla spółek o wysokim wzroście przychodów i niskiej kapitałochłonności (reinwestycja w rozwój). EXCLUDE zarezerwować dla przypadków połączonych z dodatkowymi twardymi sygnałami (np. malejące przychody jednocześnie z ujemnym FCF, albo going-concern).

**Uzasadnienie:** Spec sam rozróżnia EXCLUDE od FLAG i explicite ostrzega, że „not every abnormal metric should result in automatic exclusion" — dosłowne zastosowanie progu z §7 jako twardego wykluczenia jest sprzeczne z tym własnym zastrzeżeniem.

**Konsekwencje pozostawienia:** Pre-filter może systemowo odcinać część uniwersum, zanim dotrze do etapu jakościowego — błąd niewidoczny bez dedykowanego audytu, trudny do wykrycia bez pełnego backtestingu.

### Zmiana #3 — architektoniczna bariera przed fabrykacją źródeł

**Obecne wymaganie:** Spec nie definiuje wprost mechanizmu uniemożliwiającego LLM generowanie własnych URL-i/cytatów spoza dostarczonych danych — polega głównie na instrukcji promptowej.

**Proponowana zmiana:** Wymusić to architektonicznie: Claude otrzymuje wyłącznie listę już pobranych i zweryfikowanych źródeł (ID, URL, hash treści) jako część kontekstu i może cytować wyłącznie po ID z tej listy; warstwa deterministyczna post-processuje strukturalny output i odrzuca/usuwa każdy URL lub numer strony niepochodzący z tej listy, zanim trafi do bazy/raportu.

**Uzasadnienie:** Poleganie wyłącznie na instrukcji w promptcie jako jedynej barierze przed halucynacją źródeł jest niewystarczające w systemie, którego głównym walorem jest wiarygodność źródeł.

**Konsekwencje pozostawienia:** Realne ryzyko nieistniejącego lub błędnego linku w sekcji „WHAT YOU SHOULD VERIFY" — najbardziej wrażliwej części produktu pod kątem zaufania użytkownika.

---

## DECISIONS REQUIRED FROM OWNER

| # | Decyzja | Opcje | Rekomendacja | Uzasadnienie | Wpływ na koszt | Wpływ na złożoność |
|---|---|---|---|---|---|---|
| D1 | Dostawca danych finansowych | FMP / EODHD / Polygon-Massive / kombinacja | **FMP lub EODHD** (jeden dostawca) + SEC EDGAR zawsze | Podobny zakres, mniej integracji, niższy koszt na start; real-time z Polygon niepotrzebny (uruchomienie 1×/dzień) | 0–100 USD/mies. różnicy zależnie od planu | Niska przy jednym dostawcy, wyższa przy dwóch (reconciliacja DATA CONFLICT) |
| D2 | Źródło point-in-time danych do backtestingu | (a) zaakceptować dane „restated" z disclaimerem, (b) własna warstwa na SEC XBRL, (c) płatny dataset instytucjonalny | **(b)** SEC XBRL company-facts (pole `filed`) | Jedyna opcja spójna z RULE 1 przy zerowym koszcie krańcowym | 0 USD (koszt czasu implementacji) | Średnia-wysoka — osobny moduł ekstrakcji |
| D3 | Historyczny skład S&P 500 | (a) manualne śledzenie zmian, (b) płatny dataset, (c) backtest na aktualnym składzie z jawnym disclaimerem | **(c)** na start, docelowo (a) | Zero kosztu na start, pozwala zweryfikować resztę pipeline'u zanim zainwestuje się w czyste dane historyczne | 0 USD dla (c); nieznany dla (b) | (c) najniższa |
| D4 | Źródło listy uniwersum S&P 500 | Wikipedia scrape / endpoint dostawcy / ręczna lista kwartalna | **Endpoint dostawcy** (jeśli w cenie wybranego planu), inaczej ręczna lista z kwartalnym review | Mniejsze ryzyko błędu niż scraping w produkcji | Zwykle brak dodatkowego kosztu | Niska |
| D5 | Baza danych | SQLite / od razu Postgres | **SQLite w V0, Supabase (Postgres) od V1** | Unika przedwczesnej złożoności w V0; Supabase ma darmowy tier + UI czytelny dla osoby nietechnicznej | 0 USD na obu etapach (darmowe tiery) | Niska |
| D6 | Model Claude do warstwy jakościowej | Sonnet 5 / Opus 5 | **Sonnet 5** domyślnie, ręczny re-run na Opus 5 dla granicznych finalistów jeśli backtesting pokaże potrzebę | Sonnet 5 ok. 2,5× tańszy (2/10 USD za MTok vs 5/25 USD), brak jeszcze danych o realnej różnicy jakości uzasadniającej wyższy koszt | Sonnet 5 istotnie tańszy | Brak różnicy strukturalnej — parametr configu |
| D7 | Zakres sektorowy w V0 | Pełne wsparcie banków/ubezpieczycieli/REIT-ów od razu / wykluczyć z V0 | **Wykluczyć** (osobna flaga „sector not yet supported", nie EXCLUDE z powodu jakości), dodać po ustabilizowaniu silnika na GENERAL | To ok. 60–70 spółek wymagających innej logiki; bezpieczniej dowieźć rdzeń najpierw | Brak | Istotnie obniża złożoność V0 |
| D8 | Forward P/E i estymaty analityków | Include / exclude w V0/V1 | **Exclude** | Zwykle droższy tier u dostawcy, trudniejsze do zweryfikowania pierwotnie — sprzeczne z naciskiem na źródła pierwotne | Oszczędność (unikamy droższego planu) | Niższa (mniej pól do walidacji/źródłowania) |
| D9 | Skala allowlisty domen IR na start | Pełne 503 spółki / mały podzbiór rozszerzany stopniowo | **Mały podzbiór** (np. 20–30 spółek), dla reszty tylko SEC EDGAR | Zapobiega niekontrolowanemu obciążeniu ręcznemu na starcie; EDGAR sam spełnia priorytet #1 hierarchii źródeł | Koszt czasu własnego, nie budżetu | Niska — ogranicza zakres na start |
| D10 | Hosting/scheduler | GitHub Actions / własny VPS z cron | **GitHub Actions** | Zero administracji serwera, sekrety w GitHub UI, logi bez SSH — pasuje do wymogu „obsługiwalne przez osobę nietechniczną" | 0 USD (mieści się w darmowych minutach) | Niska |
| D11 | Zakres krzyżowej weryfikacji danych z SEC XBRL | Każde pole vs tylko pola kluczowe dla scoringu/bramek | **Tylko pola kluczowe** (dług, gotówka, przychody, zysk netto, komponenty FCF) | Pełna weryfikacja każdego pola dla 503 spółek dziennie zwiększa liczbę żądań do EDGAR (limit 10 req/s) bez proporcjonalnej korzyści | Brak dodatkowego kosztu API (EDGAR darmowy), wpływa na czas wykonania | Umiarkowana, ograniczona zakresem |

---

## Podsumowanie

Rdzeń specyfikacji (rozróżnienie price decline vs value destruction, moduł anty-konfirmacyjny, hard gates niezależne od total score, wersjonowany audit trail, zasada „nic nie fabrykować") jest spójny i nie wymaga zmiany celu produktu ani metodologii scoringu. Największe ryzyko leży nie w logice scoringu, tylko w **czterech miejscach stykających się z realnym światem**: (1) jakość i point-in-time charakter danych do backtestingu, (2) egzekwowalność wymogu „bezpośredni link + strona" dla dokumentów HTML, (3) architektoniczna (nie tylko promptowa) bariera przed fabrykacją źródeł przez LLM, (4) sztywna reguła EXCLUDE dla ujemnego FCF kolidująca z realnymi modelami biznesowymi. Wszystkie cztery są zaadresowane wyżej jako BLOCKER z konkretną rekomendacją.

Nie rozpoczynam implementacji — czekam na decyzje z tabeli „DECISIONS REQUIRED FROM OWNER" oraz akceptację architektury, dostawców danych i budżetu.

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
- Ceny Claude API (Sonnet 5: 2 USD/10 USD za MTok wejście/wyjście) — wewnętrzna, aktualna tabela cennika Anthropic (cache 2026-06-24).
