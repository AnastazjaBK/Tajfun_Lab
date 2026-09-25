# BUFFETT OPPORTUNITY SCANNER — Technical Design Review

**Status:** v1.13 — **Faza 0, Faza 1 i Faza 2 formalnie ukończone i dowiedzione na realnych danych.** Source Assembly Layer (SEC EDGAR) empirycznie potwierdzony: 12/12 dokumentów SEC (2× 10-K + 2× 10-Q dla AAPL/MSFT/KO) realnie pobranych i zahashowanych, zero `SOURCE NOT VERIFIED` — patrz „Status Fazy 2 (v1.13)" niżej. Ten plik jest samodzielny — nie wymaga sięgania do historii commitów.
**Data:** 2026-09-20 (v1.0–v1.4), 2026-09-21 (v1.5–v1.6), 2026-09-24–25 (v1.7–v1.13)
**Zmiana względem v1.0:** (1) BLOCKER 3, 4, 5 przeszły w status rozwiązany na poziomie decyzji architektonicznej; (2) BLOCKER 1 i 2 pozostają otwarte, ale z konkretnymi, zweryfikowanymi ścieżkami rozwiązania; (3) dodano projekt modułu MY HOLDINGS / EXIT MONITORING; (4) poprawiono identyfikację spółek w schemacie DB (CIK zamiast tickera).
**Zmiana w v1.2:** dodano projekt modułu BIOTECH: EXTERNAL VALIDATION & RESEARCH NETWORK (sekcja 18) jako jedną warstwę przyszłego pełnego modelu biotech.
**Zmiana w v1.3:** zamknięto decyzje D2, D4–D14 zgodnie z odpowiedziami właściciela; D15 rozstrzygnięte na rzecz nowej kolejności priorytetów — **BIOTECH ma wyższy priorytet niż pełne rozszerzenie BANK/INSURER/REIT**; dodano rejestr pełnego docelowego zakresu BIOTECH MODULE jako scope dla przyszłej Fazy 8 (DESIGN) — External Validation pozostaje tylko jedną z jego warstw.
**Zmiana w v1.4:** wykonano bezpośrednią techniczną weryfikację D1 (dostawca danych) i D3 (historyczny skład S&P 500) — **wynik: FMP** (EODHD odrzucony regułą właściciela z powodu nieznanej ceny dodatku Historical Constituents); wyjaśniono sprzeczność EODHD z v1.1 (rzetelne dane od kwietnia 2012, nie 2000); potwierdzono aktualny, niewycofany endpoint FMP `stable/historical-sp-500`; skorygowano błędne założenie z v1.2, że „kluczowy asset" biotech = najbardziej zaawansowany klinicznie — zastąpione modelem screening-funnel (18.7) do zaprojektowania w Fazie 8; dodano sekcję **FINAL PRE-IMPLEMENTATION STATUS**.
**Zmiana w v1.5:** dodano sekcję **1.1 MULTI-USER / MULTI-PORTFOLIO — SHARED vs USER-SCOPED** — nowa tabela `users`, `user_id` dodany do `watchlist`/`user_decisions`/`positions` (brakował w schemacie z v1.0–v1.4 — patrz 3 zgłoszone CONFLICT FOUND), rozdzielenie Holdings Monitor na SHARED COMPANY MONITOR i USER-SPECIFIC POSITION MONITOR, żeby drugi użytkownik nie podwajał kosztu analizy Claude API. Zaktualizowano schema (sekcja 5), plan implementacji (sekcja 15: Faza 0 zyskuje tabelę `users`, Faza 6/7 zaktualizowane o user-scoping), moduł MY HOLDINGS (sekcja 16).
**Zmiana w v1.6:** korekta właściciela — filtrowanie zapytań po `user_id` (v1.5) było poprawnie zidentyfikowane jako ryzyko, ale błędnie mogło zostać odczytane jako docelowa granica bezpieczeństwa. Doprecyzowano: w Fazie 0/V0 (SQLite, bez auth) to tylko dyscyplina aplikacyjna modelująca ownership; **prawdziwa izolacja danych** (database-level authorization, docelowo Row Level Security przy Supabase Auth powiązane z `auth.uid()`) jest wymaganiem dla przyszłej fazy realnego multi-user access, jawnie **nie** dla Fazy 0. Dodano zasadę: ewentualny wzajemny podgląd portfeli realizowany wyłącznie przez jawny model uprawnień (przyszła tabela `portfolio_shares`), nigdy przez wyłączenie izolacji `user_id`.
**Zmiana w v1.7:** właściciel potwierdził akceptację v1.6 oraz plan FMP Starter → **SAFE TO START FAZA 0: TAK**. Zaimplementowano Fazę 0: `buffett_scanner/config.py` (loader configu, pydantic), `buffett_scanner/db.py` (schema SQLite: `companies`, `ticker_history`, `price_daily`, `users` — CIK jako tożsamość, nie ticker), `buffett_scanner/providers/fmp.py` (klient FMP z jawnie oznaczonymi założeniami do weryfikacji + `fmp_smoketest.py`), `buffett_scanner/scanner.py` (decline scanner, czysta kalkulacja), `buffett_scanner/cli.py`. 32 testy jednostkowe zielone (`tests/`), 1 integracyjny pominięty bez klucza w tej sesji. `.gitignore` już wcześniej chronił `.env`/bazę SQLite/`__pycache__`.
**Zmiana w v1.10:** zaimplementowano Fazę 1 (sekcja 15, punkty 1.1–1.3) — właściciel potwierdził kontynuację odkładania zakupu planu Starter, ponieważ Faza 1 też działa na tej samej próbce tickerów, nie na pełnym uniwersum. Nowy kod: `buffett_scanner/fundamentals.py` (czysty silnik wskaźników: FCF, net debt/EBITDA, current ratio, FCF margin, revenue YoY, sygnały wieloletnie `persistent_negative_fcf`/`persistent_net_losses`, `evaluate_prefilter` — logika FLAG/EXCLUDE sterowana configiem), rozszerzenie `db.py` o tabele `fundamentals_raw` (format long) i `derived_metrics`, rozszerzenie `config.yaml`/`config.py` o sekcję `prefilter` (4 reguły FLAG, `exclude_rules` **celowo puste** — patrz BLOCKER 5 i uzasadnienie w komentarzu configu), rozszerzenie `providers/fmp.py` o `get_income_statement`/`get_balance_sheet_statement`/`get_cash_flow_statement` + `normalize_fundamentals_rows` (ścieżki/kształt odpowiedzi **NIEPOTWIERDZONE**, budowane defensywnie dokładnie tym samym trybem co profile/historical w Fazie 0), rozszerzenie `cli.py` o `ingest-fundamentals`/`prefilter`, rozszerzenie `fmp_smoketest.py` o sekcje fundamentalne, nowy workflow „Phase 1 Proof Run". 39 nowych testów jednostkowych (razem 71 zielonych), wartości referencyjne liczone ręcznie jak w Fazie 0. **Kod jeszcze nie zweryfikowany na realnym koncie** — to następny krok, analogiczny do weryfikacji `profile`/`historical-price-eod` w Fazie 0.
**Zmiana w v1.11:** **Faza 1 empirycznie potwierdzona w całości** na koncie właścicielki (workflow „Phase 1 Proof Run", plan Free, po jednej rundzie naprawy `limit`). `ingest-fundamentals` zapisał 45 wierszy `fundamentals_raw` na spółkę (5 okresów × 9 kanonicznych pól — **wszystkie** zgadywane nazwy pól FMP, w tym `revenue`/`netIncome`/`ebitda`/`totalDebt`/`cashAndCashEquivalents`/`totalCurrentAssets`/`totalCurrentLiabilities`/`operatingCashFlow`/`capitalExpenditure`, okazały się poprawne — gdyby któreś nie pasowało, brakowałoby wierszy). `prefilter` policzył realistyczne wskaźniki dla AAPL/MSFT/KO i poprawnie odpalił FLAG dla AAPL (current_ratio=0.89 < próg 1.0) **bez zablokowania spółki** — dokładnie zgodnie z BLOCKER 5. Faza 1 formalnie ukończona.
**Zmiana w v1.12:** zaimplementowano Fazę 2 (sekcja 15, punkty 2.1–2.3) — warstwa źródeł. Nowy kod: `buffett_scanner/providers/sec_edgar.py` (klient SEC EDGAR: lista filingów z Submissions API, deterministyczny budowniczy URL-i `build_filing_url` — „link buduje kod, nie LLM", sekcja 10 — i `fetch_and_hash_document`, który faktycznie pobiera dokument i liczy SHA-256 treści), `buffett_scanner/sources.py` (Source Assembly Layer: `build_sec_source_packet` — jedyne miejsce tworzące zweryfikowane źródła, BLOCKER 3; niezweryfikowany dokument nigdy nie znika po cichu, trafia do wyniku jako `verified=False` z wypełnionym `reason` — `SOURCE NOT VERIFIED`). Nowa sekcja configu `sources.sec_edgar` (dane kontaktowe User-Agent przez zmienną środowiskową, wymóg SEC) i `sources.ir_allowlist` (mechanizm gotowy, **celowo pusty** — Decyzja D9 wymaga faktycznej weryfikacji przeciw stronie tytułowej 10-K każdej spółki, nie zgadywania z pamięci ani z wyników wyszukiwarki, więc nie wypełniono go fabrykowanymi domenami). Rozszerzony `cli.py` o `build-source-packet`, nowy `sec_edgar_smoketest.py`, nowy workflow „Phase 2 Proof Run" (wymaga nowego sekretu repozytorium `SEC_EDGAR_USER_AGENT` — SEC EDGAR jest darmowy, ale wymaga danych kontaktowych w nagłówku). 16 nowych testów jednostkowych (razem 87 zielonych), w tym test na prawdziwym SHA-256 policzonym przez `hashlib` w teście, nie zgadywanym z pamięci.
**Zmiana w v1.13:** **Faza 2 empirycznie potwierdzona w całości** — po dodaniu sekretu `SEC_EDGAR_USER_AGENT` i uruchomieniu „Phase 2 Proof Run" na koncie właścicielki: 12/12 dokumentów (2× 10-K + 2× 10-Q na każdą z AAPL/MSFT/KO) faktycznie pobranych z prawdziwymi URL-ami/numerami accession SEC i zahashowanych — zero `SOURCE NOT VERIFIED`. Faza 2 formalnie ukończona.

## Metodologia i zastrzeżenia

Zgodnie z zasadą „nie zgaduj": poniżej rozróżniam trzy kategorie treści.

- **Ustalone z dokumentacji/wiedzy technicznej** — np. architektura, schematy, zasady SEC EDGAR (limit 10 req/s, brak wymogu klucza API), aktualny cennik Claude API.
- **Zweryfikowane wyszukiwaniem w sieci we wrześniu 2026, ale zmienne w czasie** — cenniki dostawców danych finansowych. Oznaczone wprost jako „do potwierdzenia na stronie dostawcy przed zatwierdzeniem budżetu" wraz ze źródłem.
- **Hipotezy wymagające Twojej decyzji lub kalibracji przez backtesting** — oznaczone `UNCALIBRATED` / w sekcji „DECISIONS REQUIRED FROM OWNER".

Żadna liczba finansowa, próg ani cennik w tym dokumencie nie jest fabrykowany — tam, gdzie nie mam pewności, piszę to wprost zamiast dopowiadać. Sprzeczność w informacjach EODHD o zakresie historycznym „Historical Constituents" (kwiecień 2012 vs styczeń 2000), zgłoszona w v1.1 jako DATA CONFLICT, została **wyjaśniona w v1.4** dzięki bardziej szczegółowemu źródłu technicznemu — patrz sekcja „FINAL PRE-IMPLEMENTATION STATUS" i zaktualizowane sekcje 3/13.

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

---

## 1.1 MULTI-USER / MULTI-PORTFOLIO — SHARED vs USER-SCOPED

Zasada nadrzędna wprowadzona w tej turze: **SHARED ANALYTICAL LAYER** (jedna analiza spółki, współdzielona) vs **USER-SCOPED PORTFOLIO/DECISION LAYER** (decyzje, transakcje, tezy, Exit Review — osobne dla każdego użytkownika). System ma być od Fazy 0 gotowy na ≥2 niezależnych użytkowników jednej instancji, bez dwóch osobnych silników analitycznych i bez dublowania kosztu Claude API.

### A/B. Które tabele SHARED, które USER-SCOPED

| SHARED (jedna spółka = jeden zestaw danych, niezależnie od liczby użytkowników) | USER-SCOPED (osobne dla każdego user_id) |
|---|---|
| `companies`, `ticker_history`, `universe_membership` | `users` (**nowa**) |
| `price_daily`, `fundamentals_raw`, `derived_metrics` | `watchlist` (**+ user_id**, brakowało w v1.0–v1.4) |
| `scoring_model_versions`, `analyses`, `analysis_sources` | `user_decisions` (**+ user_id**, brakowało w v1.0–v1.4) |
| `data_snapshots`, `run_log` | `positions` (**+ user_id**, brakowało w v1.0–v1.4) — korzeń własności |
| `assets`, `trials`, `persons`, `institutions` (moduł BIOTECH) | `purchase_transactions`, `sale_transactions` (scoping przez `position_id`) |
| `trial_person_roles`, `trial_institution_roles`, `partnerships`, `funding_events` | `purchase_thesis` (scoping przez `position_id`) |
| `publications`, `publication_authors`, `publication_asset_links`, `conflicts_dependencies` | `exit_review_triggers`, `exit_review_reports` (scoping przez `position_id`) |
| `external_validation_assessments` | `holding_user_actions` (scoping przez `position_id`) |

### C. Nowa tabela `users` + gdzie dokładnie żyje `user_id`

```sql
users(user_id PK, display_name, created_at)
  -- minimalna w Fazie 0: bez haseł/auth (świadomie odłożone do UI/auth,
  -- zgodnie z pkt 11/15 wymagania) — tylko identity, żeby żadna tabela
  -- downstream nie musiała być przeprojektowywana, gdy auth faktycznie
  -- powstanie
```

`user_id` jest zdefiniowany raz w `users`, a jako FK ownership root pojawia się **tylko na `watchlist`, `user_decisions` i `positions`** — NIE jest duplikowany na każdej tabeli potomnej. `purchase_transactions`, `sale_transactions`, `purchase_thesis`, `exit_review_triggers`, `exit_review_reports`, `holding_user_actions` dziedziczą właściciela tranzytywnie przez `position_id FK → positions.user_id`. To jednoznacznie lepsze rozwiązanie techniczne niż duplikowanie `user_id` wszędzie (jedno źródło prawdy, brak ryzyka rozjazdu) — podjęte samodzielnie, nie wymaga wyboru właściciela.

### D. Struktura łącząca USER-scoped z SHARED

```
users.user_id
      │
      ▼
positions(position_id, user_id FK, cik FK) ──────────► companies.cik (SHARED)
      │                                                        │
      ├─► purchase_transactions(position_id FK)                │
      ├─► sale_transactions(position_id FK)                    ▼
      │                                              analyses (SHARED, immutable,
      ├─► purchase_thesis(position_id FK,                cik-scoped) ◄──┐
      │       analysis_id FK ─────────────────────────────────────────┘
      │       + snapshot_json — zamrożona kopia w momencie zakupu,
      │       różna dla user A i user B nawet dla tej samej spółki)
      │
      └─► exit_review_triggers(position_id FK,
              triggering_analysis_id FK → analyses SHARED)
                  │
                  └─► exit_review_reports(trigger_id FK,
                          current_analysis_id FK → analyses SHARED)
                              │
                              └─► holding_user_actions(position_id FK)
```

Każde odwołanie do „aktualnego stanu spółki" (score, wycena, bull/bear case, źródła) idzie przez FK do `analyses`/`analysis_sources` — **nigdy nie jest kopiowane** do warstwy user-scoped, poza jednym celowym wyjątkiem: `purchase_thesis.snapshot_json`, który musi być zamrożoną kopią (bo `analyses` jako całość ewoluuje, a Purchase Thesis ma pozostać dokładnie tym, co było wiadome w momencie zakupu — to nie duplikacja bieżących danych, tylko archiwum stanu historycznego, zgodne z zasadą niemutowalności z sekcji 11).

### E. Jak unikamy podwójnego kosztu Claude API dla dwóch użytkowników

To w dużej mierze było już prawdą od v1.0, tylko teraz jest to jawne: `analyses` jest kluczowana po `cik`, nie po użytkowniku — codzienny pipeline (Fazy 0–6) analizuje każdą spółkę **raz**, niezależnie od tego, ilu użytkowników ją obserwuje/posiada. Realna zmiana dotyczy modułu MY HOLDINGS (Faza 7), gdzie pipeline z v1.4 („dla każdej pozycji sprawdź trigger, dla każdej pozycji uruchom pełny Exit Review") ukrywał ryzyko podwojenia kosztu przy dwóch użytkownikach trzymających tę samą spółkę. Poprawiony, dwuwarstwowy Holdings Monitor:

```
[A. SHARED COMPANY MONITOR — raz na spółkę (cik), nie na pozycję]
   deterministyczny pre-check (cena vs wycena, nowy filing, dywidenda,
   dźwignia — jak w v1.4) → jeśli spełniony warunek: JEDNA droga
   analiza LLM → NOWY wiersz w SHARED `analyses`
                    │
                    ▼
[B. USER-SPECIFIC POSITION MONITOR — osobno dla każdej pozycji]
   deterministyczne porównanie nowego/aktualnego `analyses` z
   zamrożonym `purchase_thesis` TEJ pozycji (score delta, MoS delta,
   sprawdzenie warunków Thesis Invalidation) → BEZ LLM
                    │
                    ▼ tylko jeśli porównanie przekroczy próg triggera
[C. Position-scoped Exit Review narrative — mały, tani kontekst]
   LLM dostaje: już wygenerowany tekst bieżącej analizy (current bull/
   bear case z SHARED `analyses`, nie źródła od nowa) + zamrożony
   `purchase_thesis` tej pozycji → syntetyzuje "why still rational" /
   "why reassessment required" DLA TEJ POZYCJI
```

Krok A jest kosztowny, ale wykonywany raz na spółkę. Krok B jest darmowy (czysty Python). Krok C jest tani — nie wysyła ponownie pełnego source packetu, tylko już wygenerowany tekst + zamrożoną tezę tej pozycji. Dwóch użytkowników trzymających tę samą spółkę płaci za krok A raz, a za krok C dwa razy — ale krok C jest rzędem wielkości tańszy niż krok A (mały kontekst, nie pełny pakiet źródłowy).

### F. Wpływ na roadmapę / koszt / zakres Fazy 0

- **Faza 0:** jedno dodanie — tabela `users` (minimalna, bez auth). Nie rozszerza checklisty 0.1–0.4 o UI, logowanie, Portfolio View, My Holdings, transaction UI, Exit Review, Holdings Monitor ani Claude position analysis — wszystko to zgodnie z instrukcją pozostaje w swoich późniejszych fazach (6, 7, 9). Faza 0 dostaje fundament pod `user_id`, nie funkcjonalność.
- **Faza 6 (V1):** `watchlist`/`user_decisions` budowane od razu z `user_id` (zamiast wymagać późniejszej migracji) — REJECT/WATCH/SNOOZE jednego użytkownika nie mogą wpływać na widoczność kandydata dla innego (patrz NEW IMPORTANT ISSUE niżej).
- **Faza 7 (MY HOLDINGS):** przeprojektowana zgodnie z A/B/C wyżej — `positions` z `user_id` od pierwszego wiersza, dwuwarstwowy Holdings Monitor zamiast jednowarstwowego z v1.4.
- **Koszt:** bez zmiany rzędu wielkości z FINAL PRE-IMPLEMENTATION STATUS — koszt analiz spółek (dominujący) nie rośnie z liczbą użytkowników; koszt Exit Review rośnie z liczbą **pozycji**, nie użytkowników wprost, i pozostaje marginalny przy 2 użytkownikach z małą liczbą pozycji każdy.

### CONFLICT FOUND (3 zgłoszone, żadna nie zmienia D1–D15)

**CONFLICT 1 — `user_decisions`/`watchlist` bez `user_id`.**
*Istniejący wymóg (v1.0–v1.4):* `user_decisions(decision_id PK, cik FK, analysis_id FK, status, decided_at, note, ...)` i `watchlist(watchlist_id PK, cik FK, ...)` — brak `user_id`, niejawne założenie jednego globalnego użytkownika.
*Nowy, sprzeczny wymóg:* ta sama spółka może być jednocześnie REJECT dla użytkownika A i WATCH dla użytkownika B.
*Proponowane rozwiązanie:* dodać `user_id FK` do obu tabel — czysto addytywna zmiana, bez przeprojektowania.
*Konsekwencje nierozwiązania:* REJECT jednego użytkownika po cichu ukrywałby kandydata dla wszystkich — błąd niewidoczny w testach jednoosobowych, wykryty dopiero przy realnym drugim użytkowniku.

**CONFLICT 2 — `positions` i cały łańcuch MY HOLDINGS bez właściciela.**
*Istniejący wymóg (v1.4):* `positions(position_id PK, cik FK, status, ...)` — brak `user_id`, jeden domyślny portfel.
*Nowy, sprzeczny wymóg:* każda pozycja należy do dokładnie jednego `user_id`; dwaj użytkownicy mogą niezależnie posiadać tę samą spółkę, w różnych ilościach, cenach i terminach.
*Proponowane rozwiązanie:* `user_id FK NOT NULL` na `positions` jako korzeń własności; tabele potomne dziedziczą przez `position_id` (patrz pkt C).
*Konsekwencje nierozwiązania:* Faza 7 musiałaby zostać przeprojektowana od zera po fakcie — dokładnie ten kosztowny scenariusz, któremu ta tura ma zapobiec.

**CONFLICT 3 — Holdings Monitor z v1.4 liczony „na pozycję", nie „na spółkę".**
*Istniejący wymóg (sekcja 16.3, v1.4):* pełna, kosztowna analiza LLM (Exit Review) uruchamiana per pozycja.
*Nowy, sprzeczny wymóg:* kosztowna analiza spółki wykonywana raz, niezależnie od liczby użytkowników/pozycji.
*Proponowane rozwiązanie:* dwuwarstwowy Holdings Monitor (SHARED COMPANY MONITOR → USER-SPECIFIC POSITION MONITOR → tani, position-scoped narrative), opisany w pkt E.
*Konsekwencje nierozwiązania:* koszt Claude API skalowałby się z liczbą pozycji wszystkich użytkowników zamiast z liczbą unikalnych posiadanych spółek — wprost narusza już przyjętą zasadę cost-control (§35, D13), niewidoczne dopóki istnieje tylko jeden użytkownik testowy.

### NEW IMPORTANT ISSUES (nie BLOCKER — nie zależą od żadnego niezweryfikowanego dostawcy)

- **Dyscyplina zapytań user-scoped w Fazie 0/V0 — TYMCZASOWA, nie docelowa granica bezpieczeństwa (korekta właściciela, v1.6).** W Fazie 0/V0, bez realnego auth i na SQLite, `user_id` służy wyłącznie do **poprawnego modelowania ownership w schemacie** — wszystkie zapytania user-scoped muszą jawnie filtrować po `user_id`, ale to jest dyscyplina aplikacyjna, nie mechanizm bezpieczeństwa. **Nie wolno jej mylić z izolacją danych.** Filtrowanie na poziomie zapytania aplikacji jest z natury kruche: jeden błędny lub niepełny query wystarczy, żeby użytkownik A odczytał lub zmodyfikował dane użytkownika B — dokładnie to ryzyko, przed którym ostrzega ten punkt.
  - **Docelowa granica bezpieczeństwa (wymóg dla fazy, w której powstanie realny multi-user access — nie Faza 0):** przy wdrożeniu prawdziwego multi-user authentication i migracji na Supabase/Postgres należy wdrożyć **database-level authorization/isolation** dla wszystkich tabel USER-SCOPED (`watchlist`, `user_decisions`, `positions` i tabel potomnych) — nie polegać wyłącznie na tym, że aplikacja zawsze doda poprawny filtr.
  - **Preferowany mechanizm, jeśli użyty zostanie Supabase Auth: Row Level Security (RLS)** powiązane z tożsamością uwierzytelnionego użytkownika (`auth.uid()`), egzekwowane przez bazę danych, nie przez aplikację. Użytkownik A nie może mieć możliwości odczytu ani modyfikacji danych USER-SCOPED użytkownika B **wyłącznie dlatego, że aplikacja wysłała błędne lub niepełne zapytanie** — to musi być niemożliwe na poziomie bazy, nie tylko mało prawdopodobne na poziomie aplikacji.
  - **Ewentualny wzajemny podgląd portfeli** (sekcja 10, „MY PORTFOLIO vs OTHER AUTHORIZED PORTFOLIO", już oznaczone jako niewymagane w V0) ma być realizowany przez **jawny model uprawnień** (np. przyszła tabela `portfolio_shares(owner_user_id, viewer_user_id, granted_at)` z odpowiadającą regułą RLS dopuszczającą odczyt), **nigdy przez wyłączenie izolacji `user_id`** dla wygody implementacyjnej.
  - **Nie implementować auth ani RLS w Fazie 0.** To jest zarejestrowane wymaganie dla przyszłej fazy realnego multi-user access (dotychczas nienazwana w planie — robocza „Faza 11+", do sformalizowania, gdy ta faza faktycznie zostanie zaplanowana), nie zadanie na teraz. Faza 0 dostaje tylko poprawny model danych (`user_id` jako FK), żeby ta przyszła faza nie wymagała migracji schematu — sama izolacja na poziomie bazy przychodzi później, razem z prawdziwym auth.
- **Filtrowanie kandydatów per widz.** Lista kandydatów dziennego raportu jest SHARED (jedna analiza), ale jej finalne filtrowanie (czy pokazać kandydata, czy jest REJECT/SNOOZE) musi być stosowane per przeglądający `user_id` w momencie renderowania/zapytania, nie zapisywane jako właściwość samej spółki.
- **Reinterpretacja szacunku kosztu MY HOLDINGS.** Wcześniejszy szacunek (FINAL PRE-IMPLEMENTATION STATUS, „~0–15 USD/mies.") był liczony na „typową liczbę pozycji inwestora indywidualnego" — przy 2 użytkownikach liczba pozycji może się z grubsza podwoić, mimo że koszt analizy spółek (dominujący) nie rośnie. Rząd wielkości szacunku pozostaje bez zmian, ale warto to przeliczyć dokładniej po realnych danych z Fazy 7, nie teraz.

---

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
| **Financial Modeling Prep (FMP)** — **WYBRANY, patrz D1/D3** | Szeroki zakres fundamentów (>30 lat, wielu rynków), EOD, dane sektorowe, ratingi. Plan **Starter: 29 USD/mies.** (300 wywołań/min, 5+ lat historii, dane fundamentalne+rynkowe, real-time) lub **Premium: 69 USD/mies.** (750 wywołań/min, 30+ lat historii, dane zaawansowane, websocket, corporate filings, bulk/batch delivery) — potwierdzone researchem. Historyczny skład S&P 500 dostępny przez **aktualny, niewycofany endpoint `stable/historical-sp-500`** (nie tylko przez oznaczony „Legacy" starszy endpoint) — obawa o wycofywanie z v1.0 częściowo rozwiana, choć dokładna głębokość/kompletność historyczna i wymagany plan (Starter czy Premium) nie zostały potwierdzone bezpośrednio w dokumentacji API i wymagają weryfikacji przed zakupem (np. przez darmowy tier/trial). | Brak bezpośrednich linków do konkretnych stron/sekcji filingów SEC; **potwierdzone researchem:** to API „aktualnego widoku" — zwraca najnowsze, skorygowane dane, a nie stan wiedzy z danej historycznej daty (egzekwowanie point-in-time to praca dobudowywana samodzielnie, nie funkcja dostawcy — patrz BLOCKER 1); dane analityczne/estymaty zwykle w droższym tier; recenzje użytkowników sygnalizują nierówną jakość wsparcia i przypadki zawyżonego pokrycia danych względem reklamy — do zweryfikowania na własnym koncie testowym przed pełnym zobowiązaniem budżetowym. |
| **EODHD (EOD Historical Data)** — odrzucony wg reguły D1 (patrz uzasadnienie w FINAL PRE-IMPLEMENTATION STATUS) | Podobny zakres do FMP (60+ giełd, 150k+ tickerów). „Fundamentals Data Feed" **€59,99/mies.**, „All-In-One" **€99,99/mies.** (EUR, potwierdzone researchem — przeliczenie na USD zależne od kursu). Osobny płatny produkt **„Indices Historical Constituents Data API"** (marketplace UnicornBay, dane S&P Global) — **sprzeczność z v1.1 wyjaśniona:** rzetelne, wolne od survivorship bias pokrycie zaczyna się **w kwietniu 2012**; wcześniejsze „migawki" (np. z 1991) są zwracane przez API, ale są niekompletne (migawka z 1991 zawiera 280 nazw, z 2008 — 436, wobec realnych ok. 500 członków) — czyli produkt de facto potwierdza dokładnie okno 2012+ już przyjęte w Decyzji D14, nie 2000. | Te same braki co FMP co do linkowania fragmentów i natywnego PIT. **Cena dodatku Historical Constituents pozostaje nieznana** mimo bezpośrednich prób weryfikacji (blokada dostępu do strony dostawcy w tej sesji + brak ceny w wynikach wyszukiwania) — to właśnie ten brak potwierdzonej „akceptowalnej ceny" rozstrzyga regułę D1 na korzyść FMP. |
| **Polygon.io (od X 2025 rebrand na „Massive")** | Bardzo dobra jakość danych cenowych/wolumenowych, WebSockety, długa historia cen w wyższych planach. | Historycznie słabszy zakres fundamentów finansowych względem FMP/EODHD; może wymagać sparowania z drugim dostawcą tylko dla fundamentów, co podnosi koszt i złożoność integracji. Przewaga real-time nie jest potrzebna — pipeline działa raz dziennie po zamknięciu rynku. Odrzucony na V0/V1 zgodnie z decyzją właściciela, chyba że podczas implementacji pojawi się konkretny, nierozwiązywalny przez FMP problem. |

**Decyzja (D1, zamknięta wg reguły właściciela):** **FMP**, jeden dostawca + SEC EDGAR zawsze. EODHD nie spełnia warunku „rozwiązuje historical constituents w akceptowalnej cenie", bo cena tego dodatku pozostaje niepotwierdzona — reguła właściciela w takim przypadku wskazuje wprost na FMP. Pełne uzasadnienie i confidence — sekcja „FINAL PRE-IMPLEMENTATION STATUS".

---

## 4. Szacunkowe koszty miesięczne

Wszystkie kwoty poniżej to **rząd wielkości**, nie oferta handlowa — źródła podane, ale cenniki dostawców danych zmieniają się często (patrz przypis o rebrandzie Polygon/Massive w pkt 3 jako dowód na to ryzyko).

| Pozycja | Szacunek | Uzasadnienie |
|---|---|---|
| Financial Data API (**FMP — wybrany, D1**) | **29–69 USD/mies.** | Starter: 29 USD/mies. (300 wywołań/min, 5+ lat historii) — prawdopodobnie wystarczający dla V0 na małej próbce tickerów; Premium: 69 USD/mies. (750 wywołań/min, 30+ lat historii, corporate filings, bulk/batch) — bezpieczniejszy wybór dla pełnych 503 spółek dziennie i dla endpointu historical constituents, jeśli okaże się wymagać wyższego planu (do potwierdzenia — patrz FINAL PRE-IMPLEMENTATION STATUS). Rekomendacja: zacząć od Starter w Fazie 0–1 na próbce tickerów, przejść na Premium przed Fazą 6 (V1, pełne 503). |
| Claude API (Sonnet 5) | **~20–80 USD/mies.** | Ceny oficjalne: 2 USD/MTok wejście, 10 USD/MTok wyjście (Sonnet 5). Przy pre-filtrze redukującym 503 spółki do ~5–15 pełnych analiz/dzień, przy ~20–35k tokenów wejścia (kontekst źródłowy) i ~2–4k tokenów wyjścia na analizę: koszt jednej analizy ≈ 0,06–0,15 USD. 15 analiz/dzień × 30 dni ≈ 450 analiz/mies. → **~30–70 USD/mies.** Zasadniczo znacznie taniej niż pełna analiza LLM 503 spółek dziennie (rząd wielkości 500–2000+ USD/mies.), co potwierdza zasadność wymogu pre-filtra z §35. |
| Hosting (scheduler + dashboard) | **0–7 USD/mies.** | GitHub Actions: darmowe minuty wystarczające dla 1 uruchomienia/dzień. Streamlit Community Cloud: darmowy tier. Ewentualnie mały Render/Fly.io jeśli dashboard wymaga czegoś więcej. |
| Baza danych | **0–25 USD/mies.** | Supabase/Neon darmowy tier (rzędu setek MB) — realistycznie wystarczy na lata danych jednego użytkownika (każda analiza to kilka–kilkanaście KB, nie duże blob-y). Płatny tier (~25 USD/mies.) dopiero przy realnym skalowaniu / wielu użytkownikach. |
| Inne (monitoring, domena) | **0–15 USD/mies.** | Sentry darmowy tier zwykle wystarczy; domena opcjonalna (~10–15 USD/rok, nie miesięcznie). |
| **MY HOLDINGS / Exit Review (dodatek)** | **~0–15 USD/mies.** | Przy typowej liczbie posiadanych pozycji inwestora indywidualnego (rząd wielkości kilku–kilkunastu spółek, nie setek) i trybie `TRIGGER_GATED` (patrz Decyzja D13) — koszt dodatkowych wywołań Claude API do Exit Review jest marginalny. Przy trybie „pełna analiza codziennie dla każdej pozycji" koszt rósłby liniowo z liczbą pozycji — stąd rekomendacja trybu trigger-gated. |
| **RAZEM (orientacyjnie, z FMP)** | **~50–170 USD/mies.** | Dolna granica: FMP Starter (29 USD) + tani Claude API + darmowe DB/hosting; górna granica: FMP Premium (69 USD) + wyższy koszt Claude API przy skali V1 + aktywny moduł holdingów. Nie uwzględnia jeszcze modułu BIOTECH (Faza 8/9 — koszt integracji ClinicalTrials.gov/OpenAlex/ROR, wszystkie darmowe, więc głównie koszt dodatkowych wywołań Claude API, marginalny przy trybie „kluczowy asset" z sekcji 18.5/18.7). |

**Rekomendacja przed zatwierdzeniem budżetu:** przed opłaceniem planu FMP potwierdzić na koncie testowym/trial, czy endpoint `stable/historical-sp-500` jest dostępny w planie Starter, czy wymaga Premium — nie było to jednoznacznie potwierdzone w dostępnej dokumentacji (patrz FINAL PRE-IMPLEMENTATION STATUS).

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

-- Tożsamość użytkownika (minimalna w Fazie 0, bez auth — patrz sekcja 1.1)
users(user_id PK, display_name, created_at)

-- Watchlist — USER-SCOPED (v1.5: dodano user_id, brakował w v1.0–v1.4,
-- patrz CONFLICT 1 w sekcji 1.1)
watchlist(watchlist_id PK, user_id FK, cik FK, added_date, added_price,
          current_status, last_analysis_id FK,
          next_review_trigger JSON, created_at, updated_at)

-- Decyzje użytkownika (workflow, NIE broker) — USER-SCOPED (v1.5: dodano
-- user_id, brakował w v1.0–v1.4, patrz CONFLICT 1 w sekcji 1.1)
user_decisions(decision_id PK, user_id FK, cik FK, analysis_id FK NULL,
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
-- Pozycja = jeden "round trip" posiadania danej spółki PRZEZ JEDNEGO
-- UŻYTKOWNIKA (pozwala odróżnić ponowne wejście po pełnym zamknięciu
-- pozycji jako osobną historię). user_id to korzeń własności całego
-- łańcucha MY HOLDINGS — v1.5, brakował w v1.0–v1.4 (CONFLICT 2, sekcja 1.1).
-- Ta sama spółka (cik) może mieć wiele niezależnych, jednoczesnych wierszy
-- positions dla różnych user_id — różne ilości, ceny, daty, statusy.
positions(position_id PK, user_id FK NOT NULL, cik FK, status ENUM('OPEN','CLOSED'),
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
  fundamentals_prices: fmp        # ZAMKNIĘTE — Decyzja D1 (v1.4): FMP, EODHD
                                    # odrzucony (cena dodatku constituents
                                    # nieznana → reguła wskazuje FMP)
  plan: starter                    # starter → premium przed V1; potwierdzić
                                    # czy stable/historical-sp-500 wymaga premium
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

**Historyczny skład S&P 500 (BLOCKER 2) — zaktualizowane po weryfikacji w v1.4:**
- **Sprzeczność z v1.1 wyjaśniona.** Szczegółowe źródło techniczne potwierdza: EODHD Historical Constituents daje rzetelne, wolne od survivorship bias pokrycie **od kwietnia 2012**; wcześniejsze migawki (technicznie zwracane przez API nawet z 1991) są **niekompletne** — migawka z 1991 zawiera 280 nazw, z 2008 — 436, wobec realnych ok. 500 członków. Marketingowe „20+ lat, od 2000" odnosi się do tego, że API *coś* zwraca, nie do kompletności/wiarygodności. To dokładnie potwierdza zasadność okna 2012+ przyjętego niezależnie w Decyzji D14.
- **FMP ma aktywny, niewycofany endpoint** `stable/historical-sp-500` (obok starszego, oznaczonego „Legacy") — obawa o wycofywanie z v1.0 jest częściowo rozwiana; dokładna głębokość/kompletność historyczna tego konkretnego endpointu FMP **nie została potwierdzona** w dostępnej dokumentacji i wymaga tego samego typu empirycznej walidacji, jaką już zaplanowano dla EODHD (Faza 5.2) — wybór dostawcy (FMP, patrz D1) nie zwalnia z tego kroku.
- Darmowy, społecznościowo utrzymywany zbiór GitHub (np. `fja05680/sp500`, od 1996) pozostaje użyteczny jako walidacja krzyżowa niezależnie od wybranego głównego źródła (zgodnie z kolejnością preferencji z Decyzji D3: komercyjne → cross-check → społecznościowe).
- Krytyczne ryzyko techniczne potwierdzone w trakcie researchu: **ticker recycling** — ticker po delistingu bywa przypisywany innej spółce. Rozwiązane już w schemacie DB (pkt 5) przez identyfikację po CIK, nie tickerze — to twarda konieczność techniczna, nie temat do dyskusji.

### Wniosek: ograniczony, ale metodologicznie uczciwy backtest zamiast pełnej symulacji PIT

Oba BLOCKERY zbiegają się w podobnym momencie w czasie: dojrzałość danych XBRL (~2009–2012) oraz zakres jednego z kandydackich źródeł historycznego składu indeksu (od kwietnia 2012, w wersji ostrożniejszej z dwóch sprzecznych źródeł EODHD). Rekomenduję zatem — zgodnie z zasadą „priorytetem jest brak survivorship bias, nie maksymalna długość backtestu" — **ograniczenie okna backtestingu do ok. 2012–dziś**, z jawną adnotacją `LIMITED_BUT_HONEST` w configu i w każdym raporcie z backtestu, zamiast symulowania pełnego PIT na dłuższym okresie przy niepewnych danych.

Co można wiarygodnie przetestować przy tym oknie: reakcję systemu na spadki i wydarzenia od 2012 r., przy prawdziwym (nie dzisiejszym) składzie indeksu i prawdziwych, historycznie znanych na dany dzień danych fundamentalnych z SEC XBRL. Czego NIE można wiarygodnie przetestować bez dodatkowej, potencjalnie kosztownej inwestycji w dane: zachowania systemu na kryzysach sprzed 2012 (np. 2008–2009) oraz — jeśli konflikt EODHD rozstrzygnie się na korzyść węższego zakresu — pełnej gwarancji braku survivorship bias przed kwietniem 2012 nawet przy użyciu tamtego źródła.

Dodatkowe zasady metodologiczne:
- Ceny użyte w backteście muszą być snapshotem na datę decyzji, nigdy przyszłym zamknięciem.
- Warstwa jakościowa (LLM) w backteście musi widzieć wyłącznie dokumenty złożone on/before data symulacji (filtrowanie po `filed_date` w EDGAR) — ale pełne wyeliminowanie „wiedzy z przyszłości" modelu językowego (wynikającej z jego danych treningowych) nie jest w pełni możliwe, tylko ograniczalne instrukcjami promptu. To zaakceptowane ograniczenie, nie coś do „naprawienia" w V0.5.
- Mierzyć nie tylko zwroty, ale i trafność klasyfikacji TEMPORARY vs STRUCTURAL — to jest właściwy test jakości modelu, nie sama stopa zwrotu (zgodnie z §30).

Po weryfikacji z v1.4 oba BLOCKERY przeszły ze stanu „brak wybranej ścieżki" do stanu „ścieżka i dostawca wybrane, czeka na wykonanie prototypu/empirycznej walidacji już zaplanowanej w Fazie 5.1/5.2" — patrz zaktualizowana „OPEN BLOCKERS" niżej i pełne podsumowanie w „FINAL PRE-IMPLEMENTATION STATUS".

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
0.5 Tabela `users` (minimalna, bez auth — patrz sekcja 1.1) — fundament pod `user_id` FK w Fazach 6/7/9, żeby żadna późniejsza faza nie wymagała migracji schematu. Nie dodaje UI ani logowania.

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

**Faza 6 (= V1)** — pełny przebieg na 503 spółkach, DB na skalę produkcyjną, dashboard, watchlist, automatyzacja dzienna (zgodnie z zakresem spec). `watchlist` i `user_decisions` budowane od razu z `user_id` (sekcja 1.1) — REJECT/WATCH/SNOOZE jednego użytkownika nie mogą wpływać na widoczność kandydata dla innego; filtrowanie po statusie stosowane per przeglądający użytkownik w momencie renderowania raportu, nie zapisywane jako cecha spółki.

**Faza 7 — MY HOLDINGS, podstawowa obsługa pozycji, MULTI-USER od pierwszego wiersza** (po V1)
7.1 Tabele `positions` (z `user_id NOT NULL` od startu), `purchase_transactions`, `sale_transactions`, `purchase_thesis` + logika BOUGHT tworząca snapshot tezy dla konkretnego użytkownika/pozycji.
7.2 SHARED COMPANY MONITOR (raz na `cik`) — deterministyczny pre-check + ewentualna pełna reanaliza LLM zapisywana jako nowy wiersz SHARED `analyses` (sekcja 1.1E).
7.3 USER-SPECIFIC POSITION MONITOR (raz na `position_id`) — deterministyczny diff aktualnej `analyses` względem `purchase_thesis` tej pozycji; dopiero po przekroczeniu progu: tani, position-scoped Exit Review LLM (kontekst = już wygenerowany tekst + zamrożona teza, nie pełny source packet).
7.4 Raport Exit Review (per pozycja) + akcje użytkownika (HOLD/REDUCE/SOLD/REVIEW LATER), zapisywane pod właściwym `user_id`.
7.5 Widok MY HOLDINGS w dashboardzie, osobny per zalogowany użytkownik (minimalny zakres — nie pełny portfolio management, bez „OTHER AUTHORIZED PORTFOLIO" — to poza V0/Fazą 7, patrz sekcja 1.1).

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

Po wybraniu BOUGHT **konkretny użytkownik** (`user_id`) zapisuje: ticker/spółkę, datę zakupu, liczbę akcji, cenę zakupu, całkowitą zainwestowaną kwotę, walutę, opcjonalne prowizje, opcjonalną notatkę — wiele zakupów tej samej spółki (przez tego samego lub różnych użytkowników, niezależnie) jako osobne rekordy (patrz tabele w pkt 5, korzeń własności = `positions.user_id`, sekcja 1.1). Kluczowa zasada: **kod, nigdy LLM, liczy liczby pozycji** (shares held, koszt, średnia cena, wartość, unrealized P/L) — Claude nie jest wywoływany do tego kroku w ogóle, i liczby te są liczone **osobno dla każdej pozycji każdego użytkownika**, nawet dla tej samej spółki.

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

### 16.3 Cadence monitoringu — dwuwarstwowy, per spółka i per pozycja (zaktualizowane w v1.5)

Rekomendowany tryb: `TRIGGER_GATED` (Decyzja D13), teraz jawnie rozdzielony na dwie warstwy z sekcji 1.1E, żeby dwóch użytkowników trzymających tę samą spółkę nie podwajało kosztu:

1. **SHARED COMPANY MONITOR** (raz na `cik`, nie na `position_id`) — codziennie, tanio, deterministycznie sprawdzane są warunki wstępne (cena vs zaktualizowana wycena, zmiana dywidendy, nowy filing, pogorszenie wskaźników zadłużenia); pełna, kosztowna analiza LLM uruchamiana jest tylko gdy warunek wstępny się spełni, plus obowiązkowo po każdym nowym kwartalnym filingu — wynik zapisywany jako nowy, SHARED wiersz `analyses`.
2. **USER-SPECIFIC POSITION MONITOR** (dla każdej `position_id` niezależnie) — tani, deterministyczny diff między (ewentualnie nowym) SHARED `analyses` a zamrożonym `purchase_thesis` tej konkretnej pozycji; dopiero jeśli diff przekroczy próg, generowany jest tani, position-scoped narrative Exit Review (pkt 16.2, kontekst = już wygenerowany tekst + zamrożona teza tej pozycji, nie pełny source packet od nowa).

To zachowuje zasadę „tani filtr deterministyczny najpierw, drogi LLM na końcu" (§35 oryginalnej specyfikacji) — teraz stosowaną na dwóch poziomach (spółka i pozycja), a nie tylko na poziomie pozycji jak w v1.4.

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
- **Koszt:** ograniczony przez to, że większość ekstrakcji jest deterministyczna (pkt 18.4); LLM wywoływany per kluczowy/istotny asset, nie per wszystkie programy spółki. **Poprawka z tury właściciela:** „kluczowy asset" NIE jest domyślnie „najbardziej zaawansowany klinicznie program" — to była błędna uproszczona operacjonalizacja z v1.2, wycofana. Faktyczny mechanizm wyboru (funnel ALL PIPELINE ASSETS → deterministyczny screening → MATERIAL/KEY ASSET SELECTION → dopiero wtedy pełna analiza LLM) jest zarejestrowany w pkt 18.7 jako scope do zaprojektowania w Fazie 8, z jawnie nieustalonymi jeszcze wagami/progami.

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

**Material/Key Asset Selection — funnel wyboru assetów (do zaprojektowania w Fazie 8, korekta z tej tury):** spółka biotech może mieć wiele programów w pipeline; nie każdy zasługuje na pełną (kosztowną) analizę LLM, ale wybór **nie może** domyślnie sprowadzać się do „najbardziej zaawansowany klinicznie" — najbardziej zaawansowany asset może, ale nie musi być kluczowy. Model do zaprojektowania:

```
ALL PIPELINE ASSETS
        │
        ▼  deterministic / low-cost screening (bez LLM)
MATERIAL / KEY ASSET SELECTION
        │
        ▼  dopiero tu wchodzi drogi LLM
DEEP LLM ANALYSIS (tylko dla wybranych assetów)
```

Screening (deterministyczny, tani) ma docelowo uwzględniać m.in.: clinical stage; potencjalną materialność assetu dla wartości spółki; proximity of catalyst; wielkość potencjalnego rynku; pipeline concentration; dostępne clinical evidence; external validation (sekcja 18.1–18.6, już zaprojektowane — może być jednym z wejść do screeningu, nie tylko wyjściem dla wybranych assetów); partnership/resource commitment; prawdopodobieństwo, że wynik danego programu może materialnie zmienić wartość spółki. **Wagi i progi celowo nieustalone w tej turze** — projektowane i kalibrowane dopiero w Fazie 8, tym samym trybem co progi scoringu rdzenia (`UNCALIBRATED` do backtestingu).

**BIOTECH + MY HOLDINGS (do zaprojektowania w Fazie 8, jako rozszerzenie schematu z sekcji 16):** przy zakupie spółki biotech Purchase Thesis musi dodatkowo zamrozić: key asset(s); phase at purchase; clinical evidence available at purchase; probability range at purchase; expected catalyst; expected catalyst date/range; cash runway; dilution risk; rNPV assumptions; external validation status; binary-event risk; biotech-specific thesis invalidation conditions. Po nowych wynikach system wykonuje **BIOTECH THESIS REVIEW** — analogicznie do Exit Review z sekcji 16.2, ale z dodatkowymi polami biotech-specyficznymi — porównujący „WHAT WE BELIEVED AT PURCHASE" vs „WHAT ACTUALLY HAPPENED". To rozszerzenie istniejącego mechanizmu Exit Review/Change Detection, nie nowy silnik — ta sama zasada reużycia co w resztą modułu.

---

## OPEN BLOCKERS

Stan po weryfikacji z v1.4: **metoda i dostawca są już wybrane dla obu punktów** — to, co pozostaje, jest pracą wykonawczą (prototyp/empiryczna walidacja), nie dalszym poszukiwaniem rozwiązania. Dlatego formalnie pozostają „otwarte" (nie zweryfikowane empirycznie), ale nie są już blokerem decyzyjnym. **Nie blokują rozpoczęcia Fazy 0–4 (budowa V0)** — dotyczą wyłącznie backtestingu. **Muszą** zostać faktycznie wykonane i potwierdzone przed rozpoczęciem Fazy 5 (V0.5 — właściwy backtesting).

**OPEN BLOCKER 1 — Point-in-time fundamentals.**
Metoda wybrana: własna warstwa PIT na SEC EDGAR XBRL company-facts (pole `filed`), niezależna od tego, którego komercyjnego dostawcę wybrano do bieżących danych — bez dodatkowego kosztu licencyjnego. Pozostaje do wykonania (Faza 5.1): (a) prototyp ekstrakcji dla 3–5 spółek testowych i porównanie z danymi „as reported" z FMP; (b) potwierdzenie jakości/kompletności danych `filed` dla okresu 2009–2012 (obszar niepewny, niezweryfikowany w tym przeglądzie).

**OPEN BLOCKER 2 — Historyczny skład S&P 500 / survivorship bias.**
Dostawca wybrany: **FMP**, przez `stable/historical-sp-500` (aktywny endpoint, nie „Legacy") — zgodnie z regułą D1, bo EODHD nie potwierdził akceptowalnej ceny swojego dodatku. Sprzeczność w dokumentacji EODHD (kwiecień 2012 vs styczeń 2000) **wyjaśniona**: rzetelne pokrycie od kwietnia 2012, wcześniejsze dane niekompletne — potwierdza zasadność okna 2012+ (D14) niezależnie od tego, którego dostawcę użyto. Pozostaje do wykonania (Faza 5.2): (a) empiryczna weryfikacja rzeczywistej głębokości/kompletności danych z endpointu FMP `stable/historical-sp-500` (nieznana z dokumentacji, wymaga konta testowego); (b) potwierdzenie, w którym planie FMP (Starter czy Premium) endpoint jest dostępny; (c) walidacja krzyżowa z darmowym zbiorem społecznościowym (`fja05680/sp500`) jako dodatkowe zabezpieczenie, zgodnie z kolejnością z D3.

Do czasu wykonania obu prototypów, wszelkie wyniki backtestingu muszą nosić w raporcie jawną adnotację `LIMITED_BUT_HONEST` z opisem, którego okresu/zakresu dotyczy ograniczenie.

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
- **(Nowe, z architektury MULTI-USER, v1.5–v1.6) Filtrowanie po `user_id` w zapytaniach aplikacji to dyscyplina tymczasowa, NIE docelowa granica bezpieczeństwa** — musi obowiązywać od Fazy 6 (bo to jedyna ochrona przy SQLite/braku auth), ale realna izolacja danych między użytkownikami wymaga database-level authorization (docelowo RLS w Supabase) wdrożonej dopiero w przyszłej fazie prawdziwego multi-user auth, nie w Fazie 0 — patrz pełne uzasadnienie w sekcji 1.1 „NEW IMPORTANT ISSUES".
- **(Nowe, z architektury MULTI-USER, v1.5) Filtrowanie kandydatów per przeglądający użytkownik** (REJECT/WATCH/SNOOZE) musi być stosowane przy renderowaniu, nie zapisywane jako cecha spółki — patrz sekcja 1.1.

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
| D1 | Dostawca danych finansowych | **ZAMKNIĘTA — wynik weryfikacji: FMP** | Zweryfikowano bezpośrednio FMP i EODHD wg reguły właściciela. EODHD nie potwierdził „akceptowalnej ceny" dla dodatku Historical Constituents (cena nieznana mimo prób weryfikacji) → reguła wskazuje na **FMP**. Plan: Starter (29 USD/mies.) na start, Premium (69 USD/mies.) przed V1/pełnym uniwersum — do potwierdzenia, czy endpoint historical constituents wymaga Premium. SEC EDGAR zawsze jako warstwa dodatkowa. Polygon/Massive odrzucone, zgodnie z decyzją właściciela. Pełne uzasadnienie, źródła i confidence — „FINAL PRE-IMPLEMENTATION STATUS". | Reguła zastosowana bez potrzeby ponownego pytania właściciela | 29–69 USD/mies. | Niska — jeden dostawca |
| D2 | Metoda point-in-time do backtestingu | **ZAMKNIĘTA — decyzja B** | Budujemy własną warstwę PIT na SEC XBRL `filed`. Nie akceptujemy backtestu na restated fundamentals udającym rzeczywisty stan wiedzy z historycznej daty. Nie kupujemy instytucjonalnego datasetu PIT na tym etapie. Przed pełną warstwą — prototyp dla 3–5 spółek (patrz Faza 5.1). | Jedyna opcja spójna z zasadą braku fabrykacji, przy zerowym koszcie licencyjnym | 0 USD (koszt czasu implementacji) | Średnia-wysoka — osobny moduł ekstrakcji |
| D3 | Źródło historycznego składu S&P 500 | **ZAMKNIĘTA (kierunek) — wynik: FMP `stable/historical-sp-500`, empiryczna walidacja w Fazie 5.2** | Zweryfikowano: EODHD Historical Constituents ma potwierdzoną, wiarygodną metodologię (od kwietnia 2012, sprzeczność z v1.1 wyjaśniona), ale nieznaną cenę → nie spełnia progu „rozsądny koszt". FMP ma aktywny (nie wycofywany) endpoint historyczny, w cenie znanego planu — zgodnie z regułą D1/D3 wybrany jako główne źródło. Darmowy zbiór społecznościowy (`fja05680/sp500`) jako cross-check, zgodnie z ustaloną kolejnością. Okno 2012+ (D14) pozostaje trafne niezależnie od dostawcy. Rzeczywista głębokość/kompletność danych FMP wymaga jeszcze empirycznej walidacji (Faza 5.2) — to praca wykonawcza, nie kolejna decyzja. | Reguła zastosowana bez potrzeby ponownego pytania właściciela | Nieznane bezpośrednie koszty dodatkowe — mieści się w cenie planu FMP z D1 | Niska–średnia |
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

**W turze v1.3 właściciel przejrzał i rozstrzygnął wszystkie 15 decyzji**, w tym D15 na rzecz „CORE FIRST, BIOTECH SECOND" (biotech ma wyższy priorytet niż pełne BANK/INSURER/REIT, plan implementacji sekcji 15 przebudowany na Fazy 7→8→9→10). **W turze v1.4** wykonano bezpośrednią techniczną weryfikację D1/D3, zamykając oba wynikiem **FMP** jako wybranym dostawcą, wyjaśniono sprzeczność w danych EODHD (rzetelne dane od kwietnia 2012, potwierdzające zasadność okna backtestingu 2012+ przyjętego w D14), oraz skorygowano błędne założenie z v1.2 o domyślnym „kluczowym asset" biotech (zastąpione modelem screening-funnel, sekcja 18.7).

**W turze v1.5** wprowadzono wymóg architektury MULTI-USER/MULTI-PORTFOLIO przed rozpoczęciem Fazy 0 (sekcja 1.1): SHARED ANALYTICAL LAYER (spółka, jej analiza, scoring, wycena, źródła — jedna kopia, niezależnie od liczby użytkowników) vs USER-SCOPED PORTFOLIO/DECISION LAYER (watchlist, decyzje, transakcje, Purchase Thesis, Exit Review — osobne per `user_id`). Wykryto i rozwiązano trzy CONFLICT FOUND w istniejącym schemacie z v1.0–v1.4 (brak `user_id` w `watchlist`, `user_decisions` i całym łańcuchu MY HOLDINGS; Holdings Monitor liczony błędnie „na pozycję" zamiast „na spółkę", co groziło podwojeniem kosztu Claude API przy dwóch użytkownikach). Rozwiązanie: dodanie tabeli `users` i `user_id` tam, gdzie brakowało, oraz dwuwarstwowy Holdings Monitor (SHARED COMPANY MONITOR → USER-SPECIFIC POSITION MONITOR). Zmiana nie rusza żadnej z decyzji D1–D15 i nie rozszerza zakresu Fazy 0 poza jedną nową, minimalną tabelę.

Nie rozpoczęto implementacji. Pełny status gotowości — sekcja „FINAL PRE-IMPLEMENTATION STATUS": **SAFE TO START FAZA 0: NIE**, w oczekiwaniu na wyraźne potwierdzenie właściciela zarówno co do treści tego dokumentu, jak i osobno co do architektury MULTI-USER z sekcji 1.1 — nie z powodu nierozwiązanej kwestii technicznej.

---

## FINAL PRE-IMPLEMENTATION STATUS

**CLOSED BLOCKERS**
- BLOCKER 3 — halucynacje/nieprawidłowe źródła (architektura Source Assembly Layer + `SOURCE NOT VERIFIED`).
- BLOCKER 4 — numery stron w SEC HTML (paginacja tylko dla PDF, dla HTML: sekcja/nota + cytat).
- BLOCKER 5 — automatyczny EXCLUDE dla ujemnego FCF (domyślnie FLAG, nie EXCLUDE).

**OPEN BLOCKERS** *(nie blokują V0, muszą być wykonane przed Fazą 5/V0.5)*
- BLOCKER 1 — point-in-time fundamentals: metoda wybrana (SEC XBRL `filed`), prototyp na 3–5 spółkach zaplanowany w Fazie 5.1, jeszcze niewykonany.
- BLOCKER 2 — historyczny skład S&P 500: dostawca wybrany (FMP `stable/historical-sp-500`), empiryczna walidacja głębokości/kompletności danych zaplanowana w Fazie 5.2, jeszcze niewykonana.

**SELECTED DATA PROVIDER**
**Financial Modeling Prep (FMP)**, jeden dostawca + SEC EDGAR zawsze jako warstwa źródeł pierwotnych. Wybór wynika wprost z reguły ustalonej przez właściciela w D1: EODHD odrzucony, bo nie potwierdzono „akceptowalnej ceny" jego dodatku historical constituents (cena nieznana mimo prób weryfikacji — bezpośredni dostęp do stron dostawców był zablokowany w tej sesji przez proxy sieciowy, dane pozyskane z wyników wyszukiwania i cytowanych źródeł trzecich, nie z pierwszej ręki). Polygon/Massive odrzucony zgodnie z wcześniejszą decyzją właściciela.

**MONTHLY COST**
- FMP: **29 USD/mies. (Starter)** na start (Fazy 0–5, próbka tickerów), **69 USD/mies. (Premium)** przed Fazą 6 (V1, pełne 503 spółki) — nie potwierdzono, czy endpoint historycznego składu wymaga Premium; do sprawdzenia na koncie testowym przed opłaceniem.
- Claude API (Sonnet 5): ~20–80 USD/mies. (bez zmian z wcześniejszych szacunków).
- Hosting/DB: ~0–25 USD/mies. (darmowe tiery w większości przypadków).
- **RAZEM orientacyjnie: ~50–170 USD/mies.**, rosnące marginalnie po Fazie 7 (MY HOLDINGS) i Fazie 9 (BIOTECH).

**IMPORTANT BACKLOG** *(potwierdzone jako żywe, nie zgubione przy zamykaniu D1–D15)*
1. Operacyjna rubryka confidence (HIGH/MEDIUM/LOW) zamiast czystej samooceny LLM — zaakceptowane jako zobowiązanie, do zaprojektowania w Fazie 4/5.
2. Okresowy audyt próbki spółek odrzuconych przez pre-filter (false negatives) — zaakceptowane jako zobowiązanie, do zaprojektowania w Fazie 4/5.
3. Zachowanie PARTIAL ANALYSIS przy zniekształconym JSON z LLM — spółka oznaczona jako niekompletna, nie znika cicho z raportu.
4. Źródło i granulacja klasyfikacji sektorowej (GICS sub-industry vs sector) — niespecyfikowane, potrzebne do przełączania logiki sektorowej.
5. Dokładna struktura pól ról badaczy w ClinicalTrials.gov API v2 (Principal Investigator/Study Chair/Study Director) — niepotwierdzona, do zweryfikowania przed Fazą 9.

**SAFE TO START FAZA 0: TAK.**

**WHY:** BLOCKER 1/2 dotyczą wyłącznie backtestingu (Faza 5), nie rdzenia Fazy 0–4. Właściciel zaakceptował architekturę MULTI-USER (v1.5/v1.6, sekcja 1.1). **Korekta względem v1.7:** ten status błędnie zakładał, że plan FMP Starter jest już aktywny — w rzeczywistości właścicielka na dzień pisania tego wpisu wciąż jest na **planie Free** i świadomie odłożyła zakup Startera. To nie blokuje Fazy 0 — patrz „Status Fazy 0" niżej.

### Status Fazy 0 (v1.8) — empirycznie zweryfikowana

`fmp_smoketest.py` uruchomiony przez właścicielkę (GitHub Actions, plan **Free**, po dwóch rundach diagnostyki — patrz historia w tym pliku i w `buffett_scanner/providers/fmp.py`) dał **rozstrzygający wynik**, nie tylko „na razie działa":

| Endpoint (`/stable/...`) | Wynik na planie Free | Znaczenie |
|---|---|---|
| `profile` (pojedyncza spółka) | ✅ Działa, potwierdzony kształt: płaski obiekt z polem `cik` | Rozwiązuje resolving CIK dla dowolnego pojedynczego tickera bez planu płatnego |
| `historical-price-eod/full` (ceny dzienne) | ✅ Działa, potwierdzony kształt: płaska lista OHLCV | Rozwiązuje ingest cen dla próbki tickerów (Faza 0, punkt 0.3) bez planu płatnego |
| `sp500-constituent` (pełna lista S&P 500) | ❌ `402 Restricted Endpoint` — jawny komunikat FMP: „not available under your current subscription" | **Wymaga planu Starter lub wyższego** — potwierdzone empirycznie, nie zgadywane |

**Wniosek:** Faza 0 (0.1–0.5) da się w pełni udowodnić na planie Free, na ręcznie podanej liście kilku–kilkunastu tickerów (kod w `cli.py` już to obsługuje — `ingest-prices` resolvuje CIK przez `profile`, jeśli tickera nie ma jeszcze w `ticker_history`). Starter jest potrzebny dopiero przy `ingest-universe` (pełne 503 spółki) — czyli faktycznie od Fazy 1/6, tak jak pierwotnie zakładano w sekcji 4, **nie od samej Fazy 0**. Właścicielka może kupić Starter, kiedy będzie tego realnie potrzebować, nie wcześniej.

Po drodze poprawiony też realny błąd w kodzie: pierwsza wersja `providers/fmp.py` używała wycofywanej rodziny endpointów `/api/v3/...` (dawała 403 niezależnie od klucza/planu) — przepisana na `/stable/...` i pokryta dodatkowymi testami defensywnego parsowania (34 testy jednostkowe, zielone).

**Faza 0 formalnie ukończona (v1.9).** Pełny przebieg pipeline'u na koncie właścicielki (workflow „Phase 0 Proof Run", plan Free): `init-db` → `ingest-prices AAPL MSFT KO --days 400` → `scan AAPL MSFT KO`. Wynik: 275 sesji cenowych zapisanych na spółkę, CIK-i zgodne z rzeczywistymi numerami SEC (AAPL 0000320193, MSFT 0000789019, KO 0000021344), pełny zestaw metryk decline scannera policzony poprawnie dla każdej spółki, żadna nie przekroczyła progów (poprawnie oznaczonych `UNCALIBRATED`). To spełnia kryterium wyjścia z Fazy 0 zdefiniowane w sekcji 15 („pipeline działa end-to-end na próbce tickerów, generuje wynik, bez dopracowanego UI") — na próbce 3 zamiast 20–30, co jest wystarczające do wykazania poprawności silnika; rozszerzenie próbki nie wymaga nic poza dopisaniem kolejnych tickerów do tego samego polecenia.

### Status Fazy 1 (v1.11) — empirycznie zweryfikowana i ukończona

Zaimplementowano wszystkie trzy punkty Fazy 1 z sekcji 15:

- **1.1 Ingest fundamentów** — `buffett_scanner/providers/fmp.py` rozszerzony o `get_income_statement`/`get_balance_sheet_statement`/`get_cash_flow_statement` (ścieżki `/stable/income-statement`, `/stable/balance-sheet-statement`, `/stable/cash-flow-statement`). `normalize_fundamentals_rows` łączy trzy sprawozdania w format long zgodny z `fundamentals_raw`, mapując pola FMP (`revenue`, `netIncome`, `ebitda`, `totalDebt`, `cashAndCashEquivalents`, `totalCurrentAssets`, `totalCurrentLiabilities`, `operatingCashFlow`, `capitalExpenditure`) — brakujące pole jest pomijane, nigdy nie fabrykowane jako 0. Nowa tabela `fundamentals_raw` w `db.py`, dokładnie wg schematu z sekcji 5. **POTWIERDZONE EMPIRYCZNIE (2026-09-25):** wszystkie trzy ścieżki i wszystkie dziewięć nazw pól są poprawne — `ingest-fundamentals` zapisał 45/45 możliwych wierszy na spółkę (5 okresów × 9 pól, zero pominiętych), plan Free wymaga `limit<=5` (patrz niżej).
- **1.2 Silnik wskaźników deterministycznych** — nowy moduł `buffett_scanner/fundamentals.py`: `free_cash_flow`, `net_debt`, `net_debt_to_ebitda`, `current_ratio`, `fcf_margin_pct`, `revenue_yoy_growth_pct`, `persistent_negative_fcf`, `persistent_net_losses`. Konsekwentnie zastosowana zasada z §24: brakująca wartość wejściowa = `None` w wyniku, nigdy 0 i nigdy fałszywie odpalona flaga. Nowa tabela `derived_metrics` (wersjonowana przez `calc_version`). 26 testów jednostkowych z ręcznie policzonymi wartościami referencyjnymi (`tests/test_fundamentals.py`), analogicznie do `test_scanner.py` z Fazy 0.
- **1.3 Logika EXCLUDE/FLAG** — `evaluate_prefilter` w `fundamentals.py`, sterowana nową sekcją `prefilter` w `config.yaml` (progi jawnie `UNCALIBRATED`). Cztery reguły FLAG (ujemny FCF, malejące przychody r/r, wysoka dźwignia net debt/EBITDA, niska płynność bieżąca) — żadna sama w sobie nie blokuje. **`exclude_rules` celowo puste**: BLOCKER 5 wymaga, żeby hard EXCLUDE wynikał z POŁĄCZENIA krytycznych sygnałów (np. ujemny FCF + malejące przychody + going-concern), a going-concern nie jest jeszcze dostępny jako sygnał deterministyczny (to sygnał tekstowy/LLM z późniejszej fazy) — dodanie tu reguły EXCLUDE bez tego sygnału byłoby fabrykowaniem progu, którego nikt nie zweryfikował.

Rozszerzony `cli.py` o `ingest-fundamentals TICKERS...` i `prefilter TICKERS...`, rozszerzony `fmp_smoketest.py` o sekcje income/balance/cash-flow statement, nowy workflow **„Phase 1 Proof Run"** (`init-db` → `ingest-prices` → `ingest-fundamentals` → `prefilter`) — gotowy do jednorazowego uruchomienia z przeglądarki, identycznie jak „Phase 0 Proof Run".

**39 nowych testów jednostkowych, wszystkie zielone (71 razem z Fazą 0).**

**Pierwsze uruchomienie „Phase 1 Proof Run" (2026-09-25, plan Free) — 402, przyczyna zdiagnozowana i naprawiona.** `ingest-fundamentals` zwrócił błąd 402 dla wszystkich trzech tickerów przy `income-statement`, ale treść błędu była rozstrzygająca i inna niż dla `sp500-constituent` w Fazie 0: „The values for 'limit' must be between 0 and 5 based on your current subscription" — czyli ścieżka `income-statement` była poprawnie zaadresowana i dostępna na planie Free, błąd dotyczył wyłącznie domyślnego parametru `limit=10` w kodzie (plan Free pozwala maks. 5 okresów). Kod poprawiony (`STATEMENT_LIMIT_FREE_PLAN = 5`).

**Drugie uruchomienie „Phase 1 Proof Run" (2026-09-25, plan Free) — PEŁNY SUKCES.** `init-db` → `ingest-prices AAPL MSFT KO --days 400` → `ingest-fundamentals AAPL MSFT KO` → `prefilter AAPL MSFT KO`. Wyniki:

| Ticker (CIK) | fcf_ttm | net_debt_to_ebitda | current_ratio | fcf_margin_pct | revenue_yoy_growth_pct | Wynik prefiltra |
|---|---|---|---|---|---|---|
| AAPL (0000320193) | 98 767 000 000 | 0,529 | 0,893 | 23,73% | 6,43% | FLAG: „Niska płynność bieżąca (current ratio)" — nie blokuje |
| MSFT (0000789019) | 66 987 000 000 | 0,520 | 1,230 | 20,19% | 17,79% | brak przekroczonych progów |
| KO (0000021344) | 5 296 000 000 | 1,975 | 1,459 | 11,05% | 1,87% | brak przekroczonych progów |

`ingest-fundamentals` zapisał **45 wierszy `fundamentals_raw` na każdą spółkę** (5 okresów × 9 kanonicznych pól, zero pominiętych) — rozstrzygające potwierdzenie, że wszystkie zgadywane nazwy pól FMP są poprawne (gdyby któreś nie pasowało, `normalize_fundamentals_rows` pominąłby odpowiadające wiersze, dając < 45). AAPL poprawnie dostał FLAG za current_ratio < 1.0 (Apple rzeczywiście ma historycznie niski current ratio — liczba jest wiarygodna, nie tylko formalnie poprawna) i **nie został zablokowany** — dokładnie zgodnie z BLOCKER 5 (ujemny FCF/niska płynność = FLAG, nigdy automatyczny EXCLUDE sam w sobie).

**Faza 1 formalnie ukończona (v1.11).** Kryterium wyjścia z sekcji 15 („silnik wskaźników + logika EXCLUDE/FLAG działa end-to-end na próbce tickerów") spełnione na realnych danych, bez zakupu planu Starter.

### Status Fazy 2 (v1.13) — empirycznie zweryfikowana i ukończona

Zaimplementowano wszystkie trzy punkty Fazy 2 z sekcji 15:

- **2.1 Mapowanie CIK + lista filingów z EDGAR** — `buffett_scanner/providers/sec_edgar.py`: `get_filings` pobiera EDGAR Submissions API (`data.sec.gov/submissions/CIK{10 cyfr}.json`), parsuje tablice `filings.recent` na listę słowników `form`/`accession_number`/`filing_date`/`report_date`/`primary_document`. Wiersz z brakującym polem krytycznym jest pomijany, nigdy nie fabrykowany. CIK bierzemy z już istniejącej tabeli `companies` (Faza 0) — nie trzeba osobnego mapowania ticker→CIK.
- **2.2 Source packet** — `buffett_scanner/sources.py`: `build_sec_source_packet` to jedyne miejsce tworzące zweryfikowane źródła (implementacja RULE 1/BLOCKER 3 z sekcji 9). Dla każdego filingu: `SecEdgarClient.build_filing_url` buduje deterministyczny URL wg wzoru z sekcji 10 (`https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-bez-myślników}/{primary-document}` — **link buduje kod, nie LLM**), potem `fetch_and_hash_document` faktycznie pobiera dokument (HTTP 200) i liczy SHA-256 treści. Dokument, który nie da się pobrać, trafia do wyniku jako `verified=False` z opisem przyczyny w `reason` — nigdy nie znika po cichu (`SOURCE NOT VERIFIED`, sekcja 9/10). `VerifiedSource` odzwierciedla schemat `analysis_sources` z sekcji 5, ale **nie jest jeszcze zapisywany do bazy** — tabela `analysis_sources` ma `analysis_id FK`, który powstanie dopiero w Fazie 3 razem z `analyses`; dopisanie go teraz rozszerzałoby schemat przed czasem.
- **2.3 Allowlista domen IR** — mechanizm w configu (`sources.ir_allowlist`, model `IrAllowlistEntry` w `config.py`) gotowy, ale **celowo pusty**. Decyzja D9 (sekcja 9) wymaga, żeby każdy wpis był zweryfikowany przeciw oficjalnej stronie tytułowej 10-K danej spółki — dodanie tu domen IR dla AAPL/MSFT/KO z pamięci lub z wyników wyszukiwarki bez tej weryfikacji byłoby dokładnie tym, czego zasada „nie zgaduj" zabrania. Wypełnienie allowlisty prawdziwymi, zweryfikowanymi wpisami zostaje jako zadanie na moment, gdy któraś z testowych spółek faktycznie trafi do głębszej analizy (Faza 3+) i realnie będzie potrzebny dokument IR.

Nowa sekcja configu `sources.sec_edgar.user_agent_env_var` (SEC wymaga danych kontaktowych w nagłówku User-Agent — nie sekret w sensie bezpieczeństwa, ale mimo to poza configiem/repo, przez zmienną środowiskową, tym samym wzorcem co `FMP_API_KEY`). Rozszerzony `cli.py` o `build-source-packet TICKERS...`, nowy `sec_edgar_smoketest.py`, nowy workflow **„Phase 2 Proof Run"**.

**16 nowych testów jednostkowych, wszystkie zielone (87 razem).** Test SHA-256 liczy oczekiwany hash przez `hashlib.sha256(...).hexdigest()` bezpośrednio w teście, nie wpisany ręcznie z pamięci — zgodnie z zasadą, że wartości referencyjne muszą być niezależnie policzone, nie odtworzone z kodu pod testem.

**Uruchomienie „Phase 2 Proof Run" (2026-09-25, po dodaniu sekretu `SEC_EDGAR_USER_AGENT`) — PEŁNY SUKCES.** `init-db` → `ingest-prices AAPL MSFT KO --days 400` → `build-source-packet AAPL MSFT KO`. Dla każdej z trzech spółek: **4 źródła w source packet (2× 10-K + 2× 10-Q), wszystkie `[OK]`, zero `SOURCE NOT VERIFIED`** — 12/12 dokumentów łącznie. Przykład (AAPL, CIK 0000320193): `10-K (2024-11-01)` → `https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm`, `hash=37aeffd496784c5...`. Wszystkie URL-e mają realne numery accession SEC (nie testowe/fikcyjne), poprawnie usunięte myślniki i wiodące zera CIK w segmencie ścieżki, dokładnie wg wzoru z sekcji 10. Analogiczny wzorzec dla MSFT (CIK 0000789019) i KO (CIK 0000021344).

**Faza 2 formalnie ukończona (v1.13).** Kryterium wyjścia z sekcji 15 („Source Assembly Layer buduje wyłącznie zweryfikowane URL-e z hashem treści, działa end-to-end na próbce tickerów") spełnione na realnych danych z SEC EDGAR, bez żadnego zakupu (SEC EDGAR jest i pozostaje darmowy).

---

## DECYZJE WCIĄŻ WYMAGAJĄCE TWOJEGO WYBORU

**Zero.** Wszystkie 15 pierwotnych decyzji (D1–D15) są zamknięte, architektura MULTI-USER (v1.5/v1.6) zaakceptowana, Faza 0, Faza 1 i Faza 2 w pełni empirycznie zweryfikowane na realnych danych (v1.13).

Jedyna otwarta kwestia to nie decyzja, tylko czas: **kiedy kupić plan Starter** — potrzebny dopiero do `ingest-universe` (pełne 503 spółki), nie do dokończenia dowodu koncepcji na próbce tickerów. Można to zrobić teraz albo poczekać do Fazy 1/6 — obie opcje są poprawne, to nie blokuje niczego pilnego.

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
- [Historical S&P 500 API (stable) | Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs/stable/historical-sp-500)
- [S&P 500 Index API (stable) | Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs/stable/sp-500)
- [Documentation V1 Endpoints (Legacy) | FMP](https://site.financialmodelingprep.com/developer/docs/legacy-endpoints)
- [Index Market Data APIs | Quotes, Constituents & Intraday | FMP](https://site.financialmodelingprep.com/datasets/indexes)
- [Automating Historical Price and Fundamental Data Retrieval for the S&P 500 using FMP API — Medium](https://medium.com/data-science-collective/automating-historical-price-and-fundamental-data-retrieval-for-the-s-p-500-using-fmp-api-d5b0550ea868)
- [Financial Modeling Prep Reviews | Trustpilot](https://www.trustpilot.com/review/financialmodelingprep.com)
- [Data Provider Disaster: A Financial Modeling Prep API Review & Alternatives](https://www.quantlabsnet.com/post/data-provider-disaster-a-financial-modeling-prep-api-review-alternatives)
- [Unicorn Data Services (EODHD) Reviews | Trustpilot](https://www.trustpilot.com/review/eodhd.com)
- [Indices Historical Constituents data API | EODHD](https://eodhd.com/lp/spglobal)
- Ceny Claude API (Sonnet 5: 2 USD/10 USD za MTok wejście/wyjście) — wewnętrzna, aktualna tabela cennika Anthropic (cache 2026-06-24).

**Zastrzeżenie do researchu D1/D3 (v1.4):** bezpośredni dostęp (WebFetch) do site.financialmodelingprep.com i eodhd.com był zablokowany przez proxy sieciowe tej sesji przy próbie weryfikacji z pierwszej ręki. Wszystkie ustalenia o cenach, planach i strukturze endpointów pochodzą z wyników wyszukiwania i cytowanych źródeł trzecich (recenzje, blogi, dokumentacja pośrednia), nie z bezpośredniego odczytu stron dostawców — stąd zalecenie w sekcji FINAL PRE-IMPLEMENTATION STATUS, by przed opłaceniem planu potwierdzić szczegóły na koncie testowym.
