# BUFFETT OPPORTUNITY SCANNER — Technical Design Review

**Status:** v1.1 — zaktualizowany po decyzjach właściciela dot. 5 BLOCKERÓW oraz po dodaniu wymagania MY HOLDINGS / EXIT MONITORING. Implementacja NIE została rozpoczęta.
**Data:** 2026-09-20 (v1.0), zaktualizowano tego samego dnia (v1.1)
**Zmiana względem v1.0:** (1) BLOCKER 3, 4, 5 przeszły w status rozwiązany na poziomie decyzji architektonicznej; (2) BLOCKER 1 i 2 pozostają otwarte, ale z konkretnymi, zweryfikowanymi ścieżkami rozwiązania zamiast ogólnego „do ustalenia"; (3) dodano projekt modułu MY HOLDINGS / EXIT MONITORING (schema, event model, wpływ na architekturę); (4) poprawiono identyfikację spółek w schemacie DB (CIK zamiast tickera jako klucz — patrz uzasadnienie w pkt 5) w oparciu o realne ryzyko „ticker recycling" znalezione podczas researchu do BLOCKER 2.

## Metodologia i zastrzeżenia

Jak w v1.0: rozróżniam ustalenia techniczne pewne, ustalenia zweryfikowane wyszukiwaniem (oznaczone źródłem i datą), oraz hipotezy wymagające Twojej decyzji lub kalibracji przez backtesting. W tej turze dodatkowo natrafiłem na **sprzeczne informacje między dwoma źródłami tego samego dostawcy** (EODHD — zakres historyczny „Historical Constituents") — opisuję to wprost jako DATA CONFLICT do wyjaśnienia, zamiast wybierać wersję, która wygląda korzystniej.

---

## 1. Architektura V0 — zaktualizowany schemat przepływu danych

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
     (całe uniwersum 503)                         Monitor — TYLKO tickery
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

Kluczowa zmiana architektoniczna wynikająca z MY HOLDINGS: **posiadane pozycje NIE przechodzą przez decline-scanner/pre-filter jako bramkę wejścia do LLM.** Twój wymóg („+40% nie oznacza automatycznie SELL, system musi badać aktualną wartość biznesu") oznacza, że monitoring pozycji musi działać niezależnie od tego, czy cena akurat spadła. Dodano więc osobną, równoległą ścieżkę (4b/4c) z własną, tańszą bramką deterministyczną, zamiast budowania drugiego niezależnego systemu analitycznego — zgodnie z Twoim punktem 3 (holding monitoring ma korzystać z istniejącego pipeline'u).

---

## 2–4. Stack, porównanie dostawców, koszty

Bez zmian co do rekomendacji z v1.0 (Python/YAML/SQLite→Supabase/GitHub Actions/Streamlit; FMP lub EODHD + SEC EDGAR), z dwoma uzupełnieniami wynikającymi z researchu do BLOCKER 1 i 2 (pełne szczegóły w sekcjach 13 i „OPEN BLOCKERS"):

- **FMP jest potwierdzone jako NIE dające natywnego point-in-time** — działa jako API „aktualnego widoku" (najnowsze, skorygowane dane), a egzekwowanie point-in-time to praca, którą trzeba dobudować samodzielnie. To nie dyskwalifikuje FMP jako źródła cen/fundamentów do pipeline'u produkcyjnego (tam interesuje nas aktualny stan), ale **potwierdza, że żaden z tanich dostawców nie rozwiąże BLOCKER 1 za nas** — patrz sekcja 13.
- **EODHD oferuje osobny, płatny produkt „Indices Historical Constituents Data API"** (marketplace, dostawca danych: S&P Global przez UnicornBay) — potencjalne rozwiązanie BLOCKER 2, ale ceny tego dodatku nie były dostępne w wynikach wyszukiwania i wymagają bezpośredniej weryfikacji. Dodatkowo dwa źródła EODHD podają **sprzeczny zakres historyczny** dla tego samego produktu (jedno: „survivorship-bias-free reliable from April 2012", drugie: „ponad 20 lat, dane od stycznia 2000") — to trzeba wyjaśnić bezpośrednio w dokumentacji API przed zakupem, nie zakładać korzystniejszej wersji.

Koszt: bez istotnej zmiany rzędu wielkości z v1.0 (~70–200 USD/mies. dla scannera). Dodatek dla MY HOLDINGS: przy typowej liczbie posiadanych pozycji dla inwestora indywidualnego (rząd wielkości kilku–kilkunastu spółek, nie setek), koszt dodatkowych wywołań Claude API do Exit Review jest marginalny (szacunkowo pojedyncze–kilkanaście USD/mies. przy modelu cadence z pkt 16.3), pod warunkiem przyjęcia rekomendowanego trybu „trigger-gated", nie „pełna analiza LLM codziennie dla każdej pozycji" — patrz Decyzja D13. Ewentualny koszt płatnego dodatku EODHD do historical constituents jest nieznany i wymaga wyceny przed decyzją D3.

---

## 5. Zaktualizowany database schema

### Poprawka fundamentalna: identyfikacja spółek przez CIK, nie ticker

W trakcie researchu do BLOCKER 2 potwierdzone zostało realne ryzyko „ticker recycling" — po delistingu/fuzji ticker bywa **ponownie przypisywany zupełnie innej spółce** (udokumentowany przykład: `STI` należał do SunTrust Banks przed fuzją z Truist w 2019, potem został przypisany innej spółce). Przy kluczu głównym opartym na tickerze backtest lub — gorzej — **moduł MY HOLDINGS** mógłby po latach powiązać historyczną pozycję z zupełnie inną firmą. To nie jest tylko problem backtestingu — to również ryzyko integralności danych dla realnych posiadanych pozycji. Dlatego zmieniam identyfikację spółek względem v1.0:

```sql
companies(cik PK, name, sector, industry, sub_industry,
          sector_profile ENUM('GENERAL','BANK','INSURER','REIT'),
          is_active BOOLEAN, created_at)

ticker_history(id PK, cik FK, ticker, start_date, end_date NULL)
  -- ticker jako atrybut zmienny w czasie, nie tożsamość;
  -- end_date NULL = aktualnie obowiązujący ticker dla danego CIK

universe_membership(id PK, cik FK, index_name, start_date, end_date)
  -- point-in-time przynależność do indeksu (BLOCKER 2)
```

Wszystkie pozostałe tabele z v1.0 (`price_daily`, `fundamentals_raw`, `derived_metrics`, `analyses`, `analysis_sources`, `watchlist`, `user_decisions`, `data_snapshots`, `run_log`) odwołują się teraz do `cik`, nie `ticker`. Ticker pozostaje polem wyświetlanym w UI (rozwiązywanym przez `ticker_history` na dany dzień), ale przestaje być kluczem.

### Nowe tabele — MY HOLDINGS / EXIT MONITORING

```sql
-- Pozycja = jeden "round trip" posiadania danej spółki (pozwala odróżnić
-- ponowne wejście po pełnym zamknięciu pozycji jako osobną historię)
positions(position_id PK, cik FK, status ENUM('OPEN','CLOSED'),
          opened_at, closed_at NULL, created_at, updated_at)
  -- shares_held, total_cost, avg_price, current_value, unrealized_pl,
  -- realized_pl NIE są przechowywane jako mutowalne kolumny — liczone
  -- deterministycznie z transakcji przy każdym odczycie (patrz uzasadnienie
  -- niżej), żeby wykluczyć rozjazd między "cache" a źródłem prawdy

-- Transakcje — WYŁĄCZNIE INSERT, nigdy UPDATE/DELETE (audit trail, pkt 9 Twojej wiadomości)
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
  -- analysis_id wskazuje na już-immutable wiersz w `analyses` (audit trail
  -- istnieje tam natywnie od v1.0);
  -- snapshot_json to DODATKOWO zdenormalizowana kopia kluczowych pól
  -- (total_score, component scores, intrinsic value range, MoS,
  --  fear_classification, bull_case, bear_case, thesis_invalidation,
  --  biggest_unknown, confidence, lista source_id) — żeby Purchase Thesis
  -- był czytelny i kompletny sam w sobie, niezależnie od przyszłych zmian
  -- schematu `analyses`, zgodnie z dosłownym wymogiem z pkt 2 Twojej wiadomości

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

**Dlaczego pozycje liczone „on read", a nie jako mutowalne kolumny:** przy tak małej skali danych (pojedynczy użytkownik, kilkanaście pozycji) narzut obliczeniowy jest pomijalny, a uniknięcie klasy błędów „cache się rozjechał z transakcjami" jest ważniejsze niż wydajność. To jednoznacznie lepsze rozwiązanie techniczne przy tej skali — podejmuję tę decyzję sam, nie wymaga Twojego wyboru. Jeśli w V2 pojawi się potrzeba wykresu wartości pozycji w czasie, dodać osobną tabelę `position_daily_snapshots` jako cache tylko do celów wizualizacji (nie jako źródło prawdy).

---

## 6. Zaktualizowany configuration schema

Dodatki względem v1.0 (pełny plik z v1.0 pozostaje aktualny, tu tylko przyrost):

```yaml
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

---

## 7–12. Podział odpowiedzialności, structured output, źródła, linki, wersjonowanie, sektory

Bez merytorycznych zmian względem v1.0 poza jednym uzupełnieniem: zasady z BLOCKER 3 (Zmiana #3 w v1.0 — architektoniczna bariera przed fabrykacją URL/cytatów) i BLOCKER 4 (Zmiana #1 — brak numeru strony dla HTML SEC) **obowiązują identycznie dla Exit Review** (pkt 16 niżej) — nie ma osobnego, „lżejszego" trybu weryfikacji źródeł dla posiadanych pozycji. To samo dotyczy schematu structured output z pkt 8 — Exit Review dostaje analogiczny, osobno zdefiniowany schemat (pkt 16.2) z tymi samymi regułami walidacji (`cited_source_ids` musi być podzbiorem dostarczonych źródeł, brak numeru strony dla HTML itd.).

---

## 13. Strategia backtestingu — zaktualizowana po decyzji o BLOCKER 1 i 2

### Co faktycznie ustalono

**Point-in-time fundamentals (BLOCKER 1):**
- Potwierdzone: FMP (a przypuszczalnie EODHD — podobny model) to API „aktualnego widoku" — zwraca najnowsze, skorygowane dane, nie stan wiedzy na daną historyczną datę. Egzekwowanie PIT to praca deweloperska „na wierzchu" API, nie funkcja dostawcy.
- Jedyna zidentyfikowana, darmowa i wiarygodna droga do PIT: **SEC EDGAR XBRL company-facts / frames**, gdzie każdy fakt ma pole `filed` (data faktycznego złożenia) — pozwala zapytać „jaka była ostatnia wartość X *filed* na dzień ≤ D" i odtworzyć stan wiedzy rynku na dowolny dzień historyczny, bez zgadywania.
- Prawdziwe instytucjonalne bazy point-in-time (np. LSEG/Refinitiv) istnieją, ale są rozwiązaniem klasy enterprise — nieproporcjonalnie drogie dla projektu jednego inwestora indywidualnego. Nie rekomenduję tej ścieżki.
- Ograniczenie praktyczne: obowiązkowe tagowanie XBRL dla większości emitentów SEC weszło w życie ok. 2009–2011 — przed tym okresem jakość/dostępność danych `filed` jest niepewna i nie została zweryfikowana w tym przeglądzie.

**Historyczny skład S&P 500 (BLOCKER 2):**
- Zidentyfikowane kandydackie źródła: (a) płatny dodatek EODHD „Indices Historical Constituents Data API" (S&P Global przez marketplace UnicornBay) — **dwa źródła EODHD podają sprzeczny zakres historyczny** (kwiecień 2012 vs styczeń 2000) — DATA CONFLICT wymagający bezpośredniej weryfikacji w oficjalnej dokumentacji/z supportem przed zakupem; (b) „Historical S&P 500 Companies API" w FMP, oznaczone w URL jako „Legacy" — sam ten tag jest sygnałem ostrzegawczym (możliwe wycofywanie endpointu), wymaga potwierdzenia aktualnego statusu; (c) darmowe, społecznościowo utrzymywane zbiory danych na GitHub (np. `fja05680/sp500`) sięgające 1996 — użyteczne do walidacji krzyżowej, ale bez SLA/gwarancji poprawności dostawcy komercyjnego.
- Krytyczne ryzyko techniczne potwierdzone w trakcie researchu: **ticker recycling** — ticker po delistingu bywa przypisywany innej spółce. Rozwiązane już w schemacie DB (pkt 5, wyżej) przez identyfikację po CIK, nie tickerze — to twarda konieczność techniczna, nie temat do dyskusji.

### Wniosek: ograniczony, ale metodologicznie uczciwy backtest zamiast pełnej symulacji PIT

Oba BLOCKERY zbiegają się w podobnym momencie w czasie: dojrzałość danych XBRL (~2009–2012) oraz zakres jednego z kandydackich źródeł historycznego składu indeksu (od kwietnia 2012, w wersji ostrożniejszej z dwóch sprzecznych źródeł EODHD). Rekomenduję zatem — zgodnie z Twoją instrukcją „priorytetem jest brak survivorship bias, nie maksymalna długość backtestu" — **ograniczenie okna backtestingu do ok. 2012–dziś**, z jawną adnotacją `LIMITED_BUT_HONEST` w configu i w każdym raporcie z backtestu, zamiast symulowania pełnego PIT na dłuższym okresie przy niepewnych danych.

Co można wiarygodnie przetestować przy tym oknie: reakcję systemu na spadki i wydarzenia od 2012 r., przy prawdziwym (nie dzisiejszym) składzie indeksu i prawdziwych, historycznie znanych na dany dzień danych fundamentalnych z SEC XBRL. Czego NIE można wiarygodnie przetestować bez dodatkowej, potencjalnie kosztownej inwestycji w dane: zachowania systemu na kryzysach sprzed 2012 (np. 2008–2009) oraz — jeśli konflikt EODHD rozstrzygnie się na korzyść węższego zakresu — pełnej gwarancji braku survivorship bias przed kwietniem 2012 nawet przy użyciu tamtego źródła.

Oba BLOCKERY pozostają formalnie otwarte do czasu bezpośredniej weryfikacji dokumentacji/warunków dostępu wybranego dostawcy — patrz „OPEN BLOCKERS" na końcu dokumentu.

---

## 14. Plan testów — uzupełnienie o MY HOLDINGS

Wszystkie testy z v1.0 pozostają aktualne. Dodatkowo:

- **Testy obliczeń pozycji:** liczba posiadanych akcji, średnia ważona cena zakupu, całkowity koszt, wartość bieżąca, unrealized P/L (nominalnie i %) — na zestawie transakcji z wieloma zakupami tej samej spółki po różnych cenach.
- **Testy metody cost-basis** (po decyzji D12): poprawność realized P/L przy częściowej sprzedaży dla wybranej metody (FIFO na start).
- **Test niemutowalności Purchase Thesis:** próba modyfikacji istniejącego `purchase_thesis` musi być zablokowana; korekta = nowa pozycja/transakcja, nie edycja.
- **Testy logiki exit-triggerów:** każda z 8 klas triggerów (THESIS_DETERIORATION, THESIS_INVALIDATION, STRUCTURAL_DETERIORATION, MOAT_DETERIORATION, FINANCIAL_SAFETY_DETERIORATION, MANAGEMENT_CAPITAL_ALLOCATION_CHANGE, DIVIDEND_DETERIORATION, VALUATION_REVIEW) ma osobny test jednostkowy na danych syntetycznych.
- **Test negatywny — dodatnia stopa zwrotu NIE wyzwala triggera sama w sobie:** pozycja +40% bez zmiany w fundamentach/tezie nie generuje `EXIT REVIEW REQUIRED`.
- **Test walidacji schematu Exit Review:** te same reguły co dla głównego schematu LLM (pkt 8) — zniekształcony JSON → reject, cytaty spoza dostarczonych źródeł → odrzucone/usunięte.
- **Test identyfikacji przez CIK:** symulacja ticker recyclingu (dwie różne spółki z tym samym historycznym tickerem w różnych okresach) — system musi poprawnie rozróżnić pozycje/analizy.

---

## 15. Plan implementacji — zaktualizowany

Fazy 0–6 bez zmian względem v1.0 (fundament → pre-filter → źródła → LLM → scoring → V0.5 backtesting z oknem 2012+ → V1 pełny scanner). Uzupełnienie:

**Faza 7 (po V1, w ramach V1.5/V2 — ale schema projektowana już teraz)**
7.1 Tabele `positions`, `purchase_transactions`, `sale_transactions`, `purchase_thesis` + logika BOUGHT tworząca snapshot tezy.
7.2 Deterministyczny Holdings Monitor (krok 4b/4c z architektury) — tania bramka wyzwalająca pełną reanalizę tylko przy spełnieniu warunku.
7.3 Schemat Exit Review + prompt LLM (reużywający Source Assembly Layer bez zmian).
7.4 Raport Exit Review + akcje użytkownika (HOLD/REDUCE/SOLD/REVIEW LATER).
7.5 Widok MY HOLDINGS w dashboardzie (minimalny zakres z Twojego punktu 8 — nie pełny portfolio management).

Uzasadnienie umieszczenia tabel z 7.1 w projekcie już teraz, ale implementacji dopiero w Fazie 7: unika się kosztownej migracji schematu później (np. zmiany klucza głównego spółek na CIK już teraz, zamiast robić to pod presją, gdy w bazie będą już realne dane).

---

## 16. MY HOLDINGS / EXIT MONITORING — projekt modułu

### 16.1 Purchase Transaction i Purchase Thesis

Realizacja dosłownie wg Twojej specyfikacji (pkt 1–2 wiadomości) — patrz tabele w sekcji 5. Kluczowa zasada: **kod, nigdy LLM, liczy liczby pozycji** (shares held, koszt, średnia cena, wartość, unrealized P/L) — Claude nie jest wywoływany do tego kroku w ogóle, zgodnie z Twoim „LLM NIE wykonuje tych obliczeń".

### 16.2 Schemat structured output dla Exit Review (analogiczny do pkt 8)

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

Te same reguły walidacji co w pkt 8 (cytaty tylko z dostarczonych źródeł, brak numeru strony dla HTML SEC, reject przy naruszeniu). Zauważ: to w praktyce ten sam mechanizm co „WHAT CHANGED" / Change Detection opisany już w oryginalnej specyfikacji (§29) — Exit Review to jego zastosowanie względem **zamrożonego punktu odniesienia (Purchase Thesis)** zamiast względem „poprzedniej analizy". Nie trzeba budować nowego silnika porównawczego, tylko sparametryzować istniejący innym baseline'em.

### 16.3 Cadence monitoringu (rekomendacja — pełne uzasadnienie w Decyzji D13)

Rekomendowany tryb: `TRIGGER_GATED` — codziennie, tanio, deterministycznie sprawdzane są warunki wstępne (cena vs zaktualizowana wycena, zmiana dywidendy, nowy filing, pogorszenie wskaźników zadłużenia); pełna, kosztowna analiza LLM (Exit Review) uruchamiana jest tylko gdy warunek wstępny się spełni, plus obowiązkowo po każdym nowym kwartalnym filingu (niezależnie od tego, czy coś „wygląda niepokojąco" — żeby nie przegapić cichej erozji tezy). To zachowuje zasadę „tani filtr deterministyczny najpierw, drogi LLM na końcu" (§35 oryginalnej specyfikacji) również dla holdingów, zamiast tworzyć dla nich wyjątek.

---

## 17. Wpływ MY HOLDINGS na architekturę — checklist (odpowiedź na Twój punkt 10)

| Element | Zmienia się? | Jak |
|---|---|---|
| Database schema | **Tak** | 7 nowych tabel (pkt 5) + zmiana klucza głównego spółek na CIK (wymuszona niezależnie, przez ryzyko ticker recyclingu wykryte przy BLOCKER 2) |
| Event model | **Tak** | Nowy typ zdarzenia „nowa analiza dla posiadanej pozycji" uruchamiający ocenę exit-triggerów; holdings nie czekają na wynik decline-scannera/pre-filtra |
| Scheduler | **Nie** (infrastrukturalnie) | Ten sam codzienny GitHub Actions run, dodatkowy krok w pipeline; brak potrzeby osobnego harmonogramu |
| Source pipeline | **Nie** (koncepcyjnie) | Pełne ponowne użycie Source Assembly Layer i allowlisty z BLOCKER 3 — bez wyjątków dla holdingów |
| Scoring architecture | **Częściowo** | Ten sam silnik 5-komponentowy; nowy element to porównanie do zamrożonego baseline'u (Purchase Thesis) zamiast tylko do poprzedniej analizy — rozszerzenie istniejącego mechanizmu Change Detection (§29), nie nowy silnik |
| Audit trail | **Tak** | Rozszerzony o zasadę append-only dla transakcji i tez zakupowych (pkt 5); logicznie spójny z już istniejącą zasadą niemutowalności `analyses` |
| UI architecture | **Tak (odłożone)** | Nowa sekcja MY HOLDINGS w V1.5/V2 dashboardzie — zaprojektowana (pkt 8 Twojej wiadomości), nieimplementowana teraz |
| Koszty | **Nieznacząco** | Marginalny wzrost przy trybie TRIGGER_GATED i typowej liczbie pozycji inwestora indywidualnego; brak wpływu na koszt dostawcy danych |
| Implementation phases | **Tak** | Nowa Faza 7 (pkt 15); schema projektowana teraz, implementacja logiki odłożona |
| Wcześniejsze DECISIONS REQUIRED | **Tak** | Dwie nowe decyzje (D12, D13) — patrz niżej |

---

## OPEN BLOCKERS

Te dwa BLOCKERY **pozostają formalnie otwarte** — mają zidentyfikowaną, konkretną ścieżkę rozwiązania, ale wymagają bezpośredniej weryfikacji u dostawcy/w dokumentacji przed uznaniem za zamknięte. Nie rozpoczynać Fazy 5 (backtesting) bez tego potwierdzenia.

**OPEN BLOCKER 1 — Point-in-time fundamentals.**
Ścieżka rozwiązania: własna warstwa PIT budowana na SEC EDGAR XBRL company-facts (pole `filed`), bez dodatkowego kosztu licencyjnego. Pozostaje do zrobienia: (a) prototyp ekstrakcji dla 3–5 spółek testowych i porównanie z danymi „as reported" z dokumentacji FMP/EODHD, żeby potwierdzić wykonalność przed budową pełnej warstwy; (b) potwierdzenie jakości/kompletności danych `filed` dla okresu 2009–2012 (obszar niepewny).

**OPEN BLOCKER 2 — Historyczny skład S&P 500 / survivorship bias.**
Ścieżka rozwiązania: płatny dodatek EODHD „Indices Historical Constituents" **lub** FMP „Historical S&P 500 Companies (Legacy)" **lub** walidacja krzyżowa przez darmowy zbiór społecznościowy. Pozostaje do zrobienia: (a) rozstrzygnięcie sprzeczności w dokumentacji EODHD (kwiecień 2012 vs styczeń 2000) bezpośrednio z dostawcą/supportem; (b) potwierdzenie, czy status „Legacy" endpointu FMP oznacza aktywne wsparcie czy planowane wycofanie; (c) wycena dodatku EODHD (nieznana w tym przeglądzie).

Do czasu zamknięcia obu punktów, wszelkie wyniki backtestingu muszą nosić w raporcie jawną adnotację `LIMITED_BUT_HONEST` z opisem, którego okresu/zakresu dotyczy ograniczenie.

---

## Rozwiązane na poziomie decyzji architektonicznej (BLOCKER 3, 4, 5)

Poniższe trzy punkty **nie wymagają dalszej dyskusji** — decyzje przyjęte i wbudowane w architekturę/schema powyżej.

**BLOCKER 3 — halucynacje źródeł.** Source Assembly Layer jako jedyny twórca `analysis_sources`; Claude cytuje wyłącznie po `source_id` z dostarczonej listy; deterministyczny post-processing usuwa/odrzuca każdy URL lub numer strony spoza tej listy; niezweryfikowane źródło → `SOURCE NOT VERIFIED`, nigdy nie prezentowane jako potwierdzone. Dotyczy identycznie głównego pipeline'u i Exit Review (pkt 16.2).

**BLOCKER 4 — numery stron w SEC HTML.** Numer strony wyłącznie dla źródeł z rzeczywistą paginacją (PDF). Dla SEC HTML: dokument, data filingu, typ filingu, sekcja/nota/item, krótki cytat identyfikujący miejsce, bezpośredni URL — bez wymyślonego numeru strony. Wdrożone w schemacie z pkt 8 i 16.2 (pole `page` dopuszczalne tylko przy potwierdzonej paginacji źródła).

**BLOCKER 5 — ujemny FCF.** Domyślnie FLAG FOR REVIEW, nie EXCLUDE. Hard EXCLUDE tylko jako część szerszego zestawu krytycznych problemów zdefiniowanych w hard-gate logic (np. ujemny FCF + malejące przychody + going-concern łącznie), nie sam w sobie i nie automatycznie łagodzony przez samą etykietę „growth" — każdy wyjątek musi być oparty na konkretnych danych (trend, runway płynności, dostępność finansowania) i audytowalny (zapisany w `analysis_sources`/`llm_raw_output`, nie tylko w konkluzji).

---

## IMPORTANT — bez zmian względem v1.0, plus jedno uzupełnienie

Wszystkie punkty IMPORTANT z v1.0 pozostają aktualne (źródło listy uniwersum, forward P/E, utrzymanie allowlisty IR, ścieżka błędu przy malformed JSON, brak rubryki dla confidence, granulacja klasyfikacji sektorowej, niewidoczność fałszywych negatywów pre-filtra). Dodatkowo:

- **Rekoncyliacja pozycji użytkownika z rzeczywistym rachunkiem maklerskim nie jest częścią systemu** (zgodnie z RULE 12 — brak integracji z brokerem) — oznacza to, że dane w `purchase_transactions`/`sale_transactions` są tak dobre, jak ręczne wprowadzanie przez użytkownika. Warto rozważyć w V1.5/V2 prosty mechanizm „sanity check" (np. porównanie sumy zainwestowanego kapitału z oczekiwaniem użytkownika) — nie teraz, tylko odnotowane jako ryzyko jakości danych wejściowych.

---

## LATER — bez zmian względem v1.0

(Rozszerzenie na inne indeksy/rynki, alerty e-mail/Telegram, głębsze modele wyceny, dane real-time, pełny portfolio management wykraczający poza minimalny zakres MY HOLDINGS z pkt 8 Twojej wiadomości.)

---

## DECISIONS REQUIRED FROM OWNER — zaktualizowana

Decyzje D1, D5–D11 z v1.0 pozostają aktualne bez zmian merytorycznych (tabela poniżej powtórzona dla kompletności). D2, D3, D14 zaktualizowane o wyniki researchu do BLOCKER 1/2. Dodano D12, D13 (nowe, z MY HOLDINGS). Zgodnie z Twoją instrukcją — pytam **wyłącznie** o decyzje z realnym wpływem na działanie produktu, wiarygodność analiz, koszt, zakres lub sposób korzystania z narzędzia; decyzje czysto implementacyjne z jednoznacznie lepszym rozwiązaniem technicznym (identyfikacja spółek po CIK, sposób liczenia pozycji „on read", reużycie mechanizmu Change Detection dla Exit Review, brak osobnego schedulera dla holdingów) podjąłem sam i uzasadniłem powyżej.

| # | Decyzja | Opcje | Rekomendacja | Uzasadnienie | Wpływ na koszt | Wpływ na złożoność |
|---|---|---|---|---|---|---|
| D1 | Dostawca danych finansowych | FMP / EODHD / kombinacja | FMP lub EODHD (jeden dostawca) + SEC EDGAR zawsze | Bez zmian z v1.0; dodatkowo: sprawdzić przy wyborze, który z nich oferuje **bardziej wiarygodny i aktualny** produkt historical-constituents (patrz D3) — to może przechylić wybór | 0–100 USD/mies. różnicy | Niska przy jednym dostawcy |
| D2 | Metoda point-in-time do backtestingu | (a) dane „restated" z disclaimerem, (b) własna warstwa na SEC XBRL `filed`, (c) płatny dataset instytucjonalny | **(b)**, potwierdzone jako jedyna realna darmowa ścieżka | Zgodnie z Twoją decyzją: nie akceptujesz (a); (c) nieproporcjonalnie drogie dla tej skali projektu | 0 USD (koszt czasu) | Średnia-wysoka |
| D3 | Źródło historycznego składu S&P 500 | (a) EODHD Historical Constituents (płatny dodatek), (b) FMP Legacy endpoint, (c) darmowy zbiór społecznościowy + walidacja krzyżowa | **Zweryfikować (a) i (b) bezpośrednio przed wyborem** — obecnie nie ma wystarczających danych, by rekomendować jedno; (c) jako uzupełniająca walidacja niezależnie od wyboru głównego źródła | Zależnie od wyniku weryfikacji | Nieznany dla (a) — do wyceny | Niska–średnia |
| D4 | Źródło listy aktualnego uniwersum | Wikipedia / endpoint dostawcy / ręczna lista | Endpoint dostawcy, inaczej ręczna lista kwartalna | Mniejsze ryzyko błędu niż scraping w produkcji | Zwykle brak | Niska |
| D5 | Baza danych | SQLite / od razu Postgres | SQLite w V0, Supabase od V1 | Bez zmian z v1.0 | 0 USD | Niska |
| D6 | Model Claude do warstwy jakościowej | Sonnet 5 / Opus 5 | Sonnet 5 domyślnie | Bez zmian z v1.0; dotyczy też Exit Review | Sonnet 5 tańszy | Parametr configu |
| D7 | Zakres sektorowy w V0 | Pełne wsparcie od razu / wykluczyć z V0 | Wykluczyć na start | Bez zmian z v1.0 | Brak | Obniża złożoność V0 |
| D8 | Forward P/E / estymaty analityków | Include / exclude | Exclude | Bez zmian z v1.0 | Oszczędność | Niższa |
| D9 | Skala allowlisty IR na start | Pełne 503 / mały podzbiór | Mały podzbiór, rozszerzany stopniowo | Bez zmian z v1.0 | Koszt czasu własnego | Niska |
| D10 | Hosting/scheduler | GitHub Actions / VPS | GitHub Actions | Bez zmian z v1.0 | 0 USD | Niska |
| D11 | Zakres krzyżowej weryfikacji z SEC XBRL | Każde pole / tylko kluczowe | Tylko kluczowe pola | Bez zmian z v1.0 | Brak dodatkowego kosztu API | Umiarkowana |
| **D12 (NOWA)** | **Metoda rozliczania kosztu przy częściowej sprzedaży** | FIFO / average cost (ważona średnia) / specific lot identification | **FIFO jako domyślna** — najprostsza do wdrożenia deterministycznie, najczęstszy standard | To wyłącznie wewnętrzne liczenie realized/unrealized P/L do celów decyzyjnych — **system nie jest narzędziem podatkowym**. Jeśli wynik ma też służyć jako podstawa do rozliczeń podatkowych w Polsce, zalecam potwierdzenie właściwej metody z doradcą podatkowym — nie zakładam tu żadnych konkretnych przepisów, bo nie mam co do nich pewności | Brak | Niska — jeden parametr configu, logika ta sama niezależnie od wyboru |
| **D13 (NOWA)** | **Cadence pełnej (LLM-owej) reanalizy posiadanych pozycji** | (a) codziennie pełna analiza LLM dla każdej pozycji, (b) TRIGGER_GATED — deterministyczny pre-check codziennie + pełna analiza tylko po spełnieniu warunku lub nowym filingu, (c) stały rytm (np. tygodniowy/miesięczny) niezależny od triggerów | **(b) TRIGGER_GATED** | Zgodne z zasadą „tani filtr najpierw" już przyjętą w oryginalnej specyfikacji (§35); (a) skaluje koszt liniowo z liczbą pozycji bez proporcjonalnej korzyści; (c) ryzykuje przeoczenie istotnej zmiany między cyklami | (a) najdroższe, (b)/(c) marginalne | (b) wymaga logiki pre-triggera, ale reużywa istniejący silnik wskaźników deterministycznych z pre-filtra — umiarkowana |
| **D14 (zaktualizowana)** | **Okno czasowe backtestingu** | (a) ograniczyć do ok. 2012–dziś (LIMITED_BUT_HONEST), (b) inwestycja w dodatkowe/droższe dane, by wydłużyć okno wstecz (koszt nieznany) | **(a)** na start V0.5, (b) tylko jeśli próbka z (a) okaże się statystycznie niewystarczająca | Realizuje wprost Twoją zasadę „priorytetem jest brak survivorship bias, nie maksymalna długość backtestu" | (a) bez dodatkowego kosztu; (b) nieznany, do wyceny gdyby był potrzebny | (a) brak dodatkowej złożoności |

---

## Podsumowanie zmian w tej turze

Trzy z pięciu BLOCKERÓW są zamknięte na poziomie decyzji architektonicznej i wbudowane w schema/architekturę. Dwa pozostają otwarte, ale — inaczej niż w v1.0 — mają teraz konkretną, zweryfikowaną ścieżkę zamknięcia zamiast ogólnego „do ustalenia": point-in-time fundamentals przez SEC XBRL `filed`, historyczny skład indeksu przez jeden z trzech zidentyfikowanych kandydatów (do bezpośredniej weryfikacji). Moduł MY HOLDINGS / EXIT MONITORING został w pełni zaprojektowany na poziomie schematu bazy danych, event modelu i audit trail, świadomie reużywając istniejące mechanizmy (Source Assembly Layer, Change Detection, silnik scoringu) zamiast budowania drugiego, niezależnego systemu. Przy okazji researchu do BLOCKER 2 wykryto i naprawiono realną lukę w projekcie z v1.0 (identyfikacja spółek po tickerze zamiast po CIK) — dotyczy to zarówno backtestingu, jak i integralności danych w MY HOLDINGS.

Nie rozpocząłem implementacji. Czekam na: (1) decyzje D12–D14 (pozostałe D1–D11 można uznać za potwierdzone, jeśli się z nimi zgadzasz — nie odnosiłaś się do nich w tej turze), (2) wynik bezpośredniej weryfikacji dostawców dla OPEN BLOCKER 1/2, zanim Faza 5 (backtesting) zostanie odblokowana.

---

## Sources (nowe w tej turze)

- [S&P and Dow Jones Indices Historical Constituents API | EODHD](https://eodhd.com/marketplace/unicornbay/spglobal)
- [S&P 500 Historical Constituents Data | EODHD APIs Blog](https://eodhd.com/financial-apis-blog/sp-500-historical-constituents-data)
- [[reworked] S&P 500 Historical Constituents | EODHD APIs Blog](https://eodhd.com/financial-apis-blog/reworked-sp-500-historical-constituents)
- [Historical S&P 500 Constituents API - Legacy | Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs/historical-sp-500-companies-api)
- [GitHub - fja05680/sp500: Current and Historical Lists of S&P 500 components since 1996](https://github.com/fja05680/sp500)
- [How To Get Historical S&P 500 Constituents Data For Free | IBKR Quant Blog](https://www.interactivebrokers.com/campus/ibkr-quant-news/how-to-get-historical-sp-500-constituents-data-for-free/)
- [As-Reported vs Restated Financial Data: Why the Difference Matters for Backtesting](https://dev.to/tradevodata/as-reported-vs-restated-financial-data-why-the-difference-matters-for-backtesting-1big)
- [How to Build a Point-in-Time Fundamentals Database from SEC EDGAR (and When Not To)](https://dev.to/tradevodata/how-to-build-a-point-in-time-fundamentals-database-from-sec-edgar-and-when-not-to-2gn6)
- [Point in Time Fundamentals | LSEG Data & Analytics](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/point-in-time-fundamentals)
- [SEC.gov | EDGAR Application Programming Interfaces (APIs)](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

Poprzednie źródła (cenniki FMP/EODHD/Polygon, EDGAR basics, ceny Claude API) — patrz historia dokumentu / commit v1.0.
