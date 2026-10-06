# BUFFETT OPPORTUNITY SCANNER — Technical Design Review

**Status:** v1.65 — **Faza 6h: TARGETED FIELD REPAIR dla `thesis_invalidation`, zastępuje full-response retry (2026-10-06).** Po DRUGIM LIVE VALIDATION TEST (po `bdfcc92`, `run_id=validation-6g-2026-10-06T135943366372Z`) full-response retry z jawnym feedbackiem (Faza 6g) **NADAL dał tylko 1/5 COMPLETE, 4/5 FAILED** z identycznym powodem (`thesis_invalidation` semantycznie pusty) — 10 pełnych Claude calls dla 5 analiz. Właścicielka uznała full-analysis retry za **niewłaściwy mechanizm naprawczy dla pojedynczego brakującego pola** i zażądała zastąpienia go **TARGETED FIELD REPAIR**: maksymalnie 1 full analysis call + (TYLKO gdy JEDYNYM naruszeniem walidacji jest semantycznie pusty `thesis_invalidation`) 1 dodatkowy, minimalny repair call zwracający WYŁĄCZNIE to pole (nowy schemat `ThesisInvalidationRepair`), scalony w analizę i ponownie zwalidowany W CAŁOŚCI — każdy inny błąd walidacji (strukturalny LUB inne pole semantycznie puste, w tym `thesis_invalidation` + inne pole naraz) idzie prosto do FAILED, zero repair, bez generalizacji poza dowiedziony przypadek. Usunięto `MAX_ANALYSIS_ATTEMPTS`/`_append_validation_retry_feedback` (Faza 6f/6g, empirycznie nieskuteczne). Nowe: `analysis_schema.py` (`ThesisInvalidationRepair`, `is_only_thesis_invalidation_semantically_empty` — sprawdza WSZYSTKIE 6 wymaganych pól niezależnie, nie tylko pierwsze naruszenie); `prompt.py` (`build_thesis_invalidation_repair_prompt` — minimalny kontekst, BEZ źródeł/cytowań, współdzielona stała `_THESIS_INVALIDATION_REQUIREMENT` z głównym promptem, żeby wymóg kardynalności nigdy nie dryfował w dwóch kopiach); `providers/claude.py` (`_parse` wydzielony jako generyczny rdzeń współdzielony przez `generate_analysis`/nowy `repair_thesis_invalidation`, nowy `ClaudeRepairResult`); `db.py` (7 nowych nullable kolumn `llm_repair_*` na `analyses`/`live_scan_candidates`, ODRĘBNE od `llm_*` — audyt rozróżnia full_analysis_call od thesis_invalidation_repair_call, nigdy scalone w jedną liczbę); `cli.py` (`_analyze_shortlist_and_report` przepisany: 1 full call → walidacja → jeśli jedyny problem to `thesis_invalidation` → 1 repair call → merge → pełna re-walidacja → COMPLETE/FAILED). Semantic-empty threshold (15 znaków), scoring/wagi/hard gates/DCF/growth caps/decline screening/ranking/TOP-20/modelu Claude/`thinking` — **NIETKNIĘTE**. 20 nowych/rozszerzonych testów (`test_analysis_schema.py`, `test_prompt.py`, `test_claude_client.py`, `test_cli.py`, pokrycie scenariuszy A-I ze specyfikacji właścicielki), pełny zestaw: **673 passed, 1 skipped** (było 655). Zero płatnych wywołań Claude API w tej fazie — implementacja + testy lokalne WYŁĄCZNIE. Historyczne runy (`live-scan-2026-10-06T083825543395Z`, `validation-6f-2026-10-06T110249722378Z`, `validation-6g-2026-10-06T135943366372Z`) nietknięte. Zero pełnego live runu, zero V1 — decyzja o LIVE VALIDATION TEST tego mechanizmu należy do właścicielki. Poprzedni status (v1.64): **Faza 6g: ROOT CAUSE AUDIT + fix `thesis_invalidation` semantycznie pusty (2026-10-06), po LIVE VALIDATION TEST Fazy 6f.** LIVE VALIDATION TEST (5 historycznych finalistów, `run_id=validation-6f-2026-10-06T110249722378Z`) wykazał **1/5 COMPLETE (INTU), 4/5 FAILED** (CBOE/DECK/ACN/PAYX) — NIE spełnia kryterium 5/5. Wszystkie 4 FAILED: identyczny powód na OBU próbach retry — `thesis_invalidation` semantycznie pusty. Właścicielka zażądała audytu PRZED jakąkolwiek zmianą kodu. **Audyt ujawnił jednoznaczny, dwuczęściowy root cause:** (1) instrukcja promptu dla `thesis_invalidation` opisywała tylko JAKOŚĆ treści, nigdy nie mówiła wprost "musisz podać co najmniej jeden" — w przeciwieństwie do `why_market_may_be_right`/`why_this_may_not_be_a_bargain`, które mają explicite fallback dla niskiej pewności ("jeśli nie widzisz dobrego argumentu, napisz to wprost"); ogólna zasada anty-halucynacyjna promptu prawdopodobnie była nadinterpretowana jako "zwróć pustą listę" dla TEGO JEDNEGO pola bez niego. (2) **Retry (Faza 6f) był ślepym powtórzeniem IDENTYCZNEGO promptu** — zero informacji o tym, co konkretnie zawiodło, więc druga próba miała szansę powodzenia tylko z czystego losu próbkowania, nie z korekty systematycznej tendencji — co w pełni wyjaśnia 100% powtarzalność (4/4, identyczny powód na obu próbach). Minimalny fix (dokładnie per preferowana architektura właścicielki): `prompt.py` — jawny wymóg ">=1" + przykładowe kategorie warunków + jawny zakaz wymyślonych progów liczbowych, ZERO zmiany schematu JSON/typu pola; `cli.py` — nowa `_append_validation_retry_feedback`, retry teraz dostaje treść `AnalysisValidationError` z poprzedniej próby + żądanie poprawionej odpowiedzi, `MAX_ANALYSIS_ATTEMPTS` zostaje `2`. `analysis_schema.py` (semantic validator, próg 15 znaków) **NIETKNIĘTY**. 4 nowe/rozszerzone testy, pełny zestaw: **655 passed, 1 skipped**. Zero zmian scoringu/metodologii/modelu/`thinking`. Historyczne runy (`live-scan-2026-10-06T083825543395Z`, `validation-6f-...`) nietknięte. Zero nowych wywołań Claude w tej fazie. Decyzja o ponownym LIVE VALIDATION TEST (czy fix realnie poprawia wskaźnik COMPLETE) należy do właścicielki. Pełne szczegóły: patrz „Faza 6g" niżej. Poprzedni status (v1.62): **Faza 6f: BUGFIX V0 OUTPUT CONTRACT (2026-10-06), po przeglądzie FINAL FULL LIVE MVP RUN (`live-scan-2026-10-06T083825543395Z`, commit `c6706442bfa6e20954516ceeeeaeb1c4663d778a`).** Właścicielka znalazła 2 realne problemy jakościowe w kontrakcie analizy LLM, WYRAŹNIE sklasyfikowane jako bugfix, NIE kolejna kalibracja/zmiana metodologii. **Problem 1 — Claude nie znał danych, które pipeline już policzył:** Claude wielokrotnie pisał "nie dysponuję danymi o aktualnej cenie/Margin of Safety" (np. INTU: current_price=284.68, BASE IV=1817.83, BASE MoS=84.3% — wszystko już policzone przez `valuation.compute_valuation`, Stage 1, zero LLM) — **PRAWDZIWE stwierdzenie**, bo `prompt.py` nigdy nie przekazywał current_price/DCF/MoS/decline context modelowi, mimo że pipeline je miał. Root cause zweryfikowany przez odczyt `build_analysis_prompt` (tylko `metrics`/`prefilter_flags`/`sources`, zero ceny/wyceny). Naprawione: nowa sekcja promptu "KONTEKST CENY I WYCENY" przekazuje current_price + DCF BEAR/BASE/BULL (intrinsic value/akcję + MoS) + decline snapshot (1D/1T/1M/1Q/YTD/1R/drawdown/wolumen) jako dane JUŻ POLICZONE przez kod (`compute_valuation`/`compute_price_changes`, te same frozen funkcje co Stage 1 — zero nowej metodologii, zero nowych growth caps, zero nowych market multiples) — z jawną instrukcją "NIE przeliczaj DCF samodzielnie" i jawnym "NIEDOSTĘPNA w tym wywołaniu" gdy dane faktycznie nie istnieją (np. `cmd_analyze` dry-run bez pobranej ceny, albo sektor BANK/INSURER/REIT NOT_YET_IMPLEMENTED). **Problem 2 — COMPLETE nie oznaczało rzeczywistej kompletności:** CBOE/DECK/INTU/ACN (4 z 5 finalnych kandydatów) miały semantycznie pusty `thesis_invalidation=[]` i `biggest_unknown=""` mimo poprawnego kształtu JSON — walidacja sprawdzała tylko KSZTAŁT (sekcja 8), nigdy TREŚĆ. Naprawione: nowa heurystyczna (jawnie udokumentowana jako przybliżenie, nie NLU) `_is_semantically_empty` w `analysis_schema.py` odrzuca `""`/`null`/`[]`/placeholder-blocklist (`"brak"`/`"N/A"`/`"nie wiadomo"` itd.)/zbyt krótkie treści dla 6 wymaganych pól (`bull_case`/`bear_case`/`why_market_may_be_right`/`why_this_may_not_be_a_bargain`/`thesis_invalidation`/`biggest_unknown`) — wpięta do istniejącego `validate_analysis_output`, więc automatycznie obowiązuje wszędzie (`cmd_analyze`/`cmd_score`/live-scan). W Stage 2 live-scanu (`_analyze_shortlist_and_report`) dodany bounded retry (`MAX_ANALYSIS_ATTEMPTS=2` — 1 oryginalna próba + 1 retry, NIGDY nieskończona pętla): błąd walidacji (strukturalny lub semantic completeness) retry'uje wywołanie Claude, błąd API (`ClaudeError`) zachowuje istniejący fail-fast bez retry; po wyczerpaniu prób status jest `FAILED`, NIGDY `COMPLETE` — usage WSZYSTKICH prób jest sumowany (telemetria nigdy nie zaniża realnego kosztu retry'owanego kandydata). Historyczny run `live-scan-2026-10-06T083825543395Z` pozostaje NIETKNIĘTY (immutable audit artifact — bugfix dotyczy wyłącznie przyszłych analiz, zero migracji/backfillu istniejących danych). Zero zmian scoringu/wag/hard gates/decline screening/deterministic ranking/shortlist TOP-20/DCF methodology/growth assumptions/source hierarchy/modelu Claude/konfiguracji `thinking` — potwierdzone diffem (3 pliki produkcyjne: `analysis_schema.py`, `cli.py`, `prompt.py` + 3 pliki testowe). 37 nowych/rozszerzonych testów, pełny zestaw: **653 passed, 1 skipped**, zero płatnych wywołań Claude API w tej fazie. Decyzja właścicielki: STOP po implementacji, czeka na review — pełny live run NIE wznowiony w tej fazie. Pełne szczegóły: patrz „Faza 6f" niżej. Poprzedni status (v1.61): **Faza 6e: TELEMETRIA Anthropic API usage WPROWADZONA (2026-10-06), przed kolejnym pełnym live runem.** Decyzja właścicielki po COST AUDIT (Faza 6d): "nie będziemy dalej szacować kosztu na podstawie rozmiaru `llm_raw_output` — wprowadź telemetrię Anthropic API usage, WYŁĄCZNIE tę jedną zmianę." Krok 0 (wymagany przez właścicielkę przed jakimkolwiek kodem): zweryfikowano przez inspekcję zainstalowanego SDK (`anthropic==1.8.0`, `anthropic.types.Usage`/`Message`/`ParsedMessage`) realny, dokładny zestaw pól — NIE zakładany z pamięci/dokumentacji nowszej generacji. `response.usage` realnie zawiera: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cache_creation` (rozbicie po TTL), `output_tokens_details.thinking_tokens`, `server_tool_use`, `service_tier`, `inference_geo`; `response` (Message/ParsedMessage) dodatkowo `model`/`id`/`stop_reason`. **To bezpośrednio odpowiada na hipotezę "niewidocznych tokenów adaptive thinking" z Fazy 6d** — `output_tokens_details.thinking_tokens` JEST realnym, zwracanym polem (jeśli serwer je wypełni) — od tej zmiany każde kolejne wywołanie Claude będzie je realnie mierzyć, nie zgadywać. Implementacja: `ClaudeClient.generate_analysis` zwraca teraz `ClaudeAnalysisResult(output, usage)`; `ClaudeError` niesie `.usage` TYLKO gdy API faktycznie odpowiedziało (refusal/nie-sparsowalny JSON) — `None` dla błędów bez odpowiedzi (APIStatusError/APIConnectionError, np. wyczerpany kredyt — nigdy nie wymyślony koszt dla niewykonanego wywołania). Persystencja: nowe nullable kolumny usage na `analyses` (per faktycznie zapisana analiza — obejmuje `cmd_score` ORAZ live-scan) i na `live_scan_candidates` (per-kandydat, per PRÓBA w TYM `run_id` — FAILED z realną odpowiedzią ma usage, FAILED bez odpowiedzi i CACHE HIT mają `NULL`, nigdy nie przypisane jako nowy koszt), z migracją kolumn (`_COLUMN_MIGRATIONS`, ten sam mechanizm co `overlap_merge_note`) dla już istniejących artefaktów DB. Nowa funkcja `get_live_scan_run_usage_summary` — płaski `SUM` po `live_scan_candidates` danego `run_id` (bez JOIN-a do `analyses`, więc cache hit nigdy nie jest liczony jako nowy koszt tego runu), wypisywana w CLI po tabeli statusu shortlisty. **Zero wyliczonego kosztu $** — brak dziś zweryfikowanego cennika per-token (patrz COST AUDIT, Faza 6d), więc raportowane są WYŁĄCZNIE realne surowe liczby tokenów, nigdy szacunek. Zero zmian promptu/modelu/konfiguracji `thinking`/schematu JSON `AnalysisOutput`/wag scoringu/logiki shortlisty/source assembly/metodologii inwestycyjnej — potwierdzone diffem (3 pliki produkcyjne: `cli.py`, `db.py`, `providers/claude.py` + 3 pliki testowe). 13 nowych/rozszerzonych testów, pełny zestaw: **616 passed, 1 skipped**, **zero płatnych wywołań Claude API w tej fazie**. Decyzja właścicielki: STOP przed jakimkolwiek live runem (próbkowym czy pełnym) do jej przeglądu. Pełne szczegóły: patrz „Faza 6e" niżej. Poprzedni status (v1.60): **Faza 6d (uzupełnienie): REALNA STAWKA KOSZTU POTWIERDZONA (2026-10-06).** Właścicielka potwierdziła: pierwsze doładowanie ($5) wystarczyło na tygodnie wcześniejszych prac, drugie ($20) zostało w CAŁOŚCI zużyte przez 175 udanych analiz (56+119) w jeden dzień — co zmienia empiryczną stawkę $20/175=$0,1143/call z hipotezy na **potwierdzony fakt**. Dokładny rozkład znaków promptu: **86% inputu (JSON output schema 64% + statyczne instrukcje anti-bias/zasady 22%) jest identyczne co wywołanie, dla każdego tickera, nigdy cache'owane** — fundamentals/metryki to tylko 4%, treść dokumentów SEC/IR nie jest wysyłana wcale (tylko metadane, 7%). Wniosek: koszt wynika GŁÓWNIE z liczby wywołań (175 w jeden dzień vs nieliczne testy przez tygodnie wcześniej), ale realna stawka per-call (~$0,114) jest ~3x wyższa niż sam widoczny JSON-output (~$0,035) — zgodne z hipotezą niewidocznych tokenów adaptive thinking z poprzedniej wersji audytu. Prompt caching NIE jest używany (potwierdzone), potencjał zidentyfikowany (blok zasad+anti-bias, 1731 znaków) ale **nic nie wdrożone**. Koszt nowej architektury (shortlist) na realnej stawce: TOP5=$0,57, TOP10=$1,14, TOP15=$1,71, TOP20=$2,29. Zero nowych wywołań Claude w tej fazie. Pełne szczegóły: patrz „Faza 6d", punkt 7 niżej. Poprzedni status (v1.59): **Faza 6d: COST AUDIT ZAKOŃCZONY (2026-10-06), przed decyzją właścicielki o kolejnym doładowaniu Anthropic.** Po pierwszej małej próbce dwustopniowego pipeline'u (GH Actions run [37424219308](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37424219308)) — zadziałał poprawnie, ale Claude API dalej zwracało `credit balance too low` (konto bez środków) — właścicielka zażądała audytu kosztów PRZED kolejnym doładowaniem: "Nie chcę ponownie doładowywać konta bez poznania rzeczywistego kosztu pipeline." Audyt (jednorazowy skrypt, zero sieci/nowych wywołań Claude, usunięty po użyciu) odczytał REALNE dane z artefaktów Run 1 (56 udanych analiz) i Run 3 (119 udanych analiz): **żadne `response.usage` (tokeny) nigdy nie było zapisywane** — `ClaudeClient` nigdy go nie odczytuje — więc rzeczywisty koszt per-call NIE jest zmierzony i nie dał się odtworzyć dokładnie; stwierdzone wprost, nie zgadywane. Co jest realne: rozmiar `llm_raw_output` (JSON wyniku) dla obu prób niemal identyczny (mean~10500 znaków, n=56 i n=119 — silnie zgodne niezależne próbki), model=`claude-sonnet-5`, zero prompt caching (strukturalnie potwierdzone), prompt NIE zawiera pełnej treści dokumentów SEC (tylko metadane). Szacowany koszt per analizę z samej widocznej treści JSON: ~$0,03–0,05 — ale **175 udanych analiz × ten szacunek ≈ $6, nie $20**, co jest realną, zmierzoną rozbieżnością. Najbardziej prawdopodobne (nieudowodnione) wyjaśnienie: `claude-sonnet-5` uruchamia adaptive thinking domyślnie (`ClaudeClient` nigdy nie ustawia `thinking`), a tokeny thinking są billowane jako output, ale nigdy zapisywane w `llm_raw_output` — całkowicie niewidoczne w danych projektu. Oszacowany koszt TOP 5/10/15/20 w dwóch reżimach (JSON-only ~$0,18–$0,70; empiryczny implied rate ~$0,57–$2,28) — nawet górny reżim to rząd $2–3 dla pełnego runu z shortlistą 20, nie $20. Zero zmian promptu/kodu/metodologii w tej fazie — czysty audyt. Pełne szczegóły: patrz „Faza 6d" niżej. Poprzedni status (v1.58): **Faza 6c: DWUSTOPNIOWY PIPELINE (deterministic ranking + shortlist, OPCJA 3) ZAKOŃCZONY (2026-10-06).** Po 3 live runach na aktualnym rynku (Faza 6b): Run 1 (150/501 wytypowanych, 94 nieudane — wyczerpanie limitu Anthropic w połowie, czysty alfabetyczny cutoff FICO-ZTS) i Run 3 (156/501, 37 nieudane — PONOWNIE wyczerpanie limitu, cutoff PYPL-ZTS, mimo uzupełnienia kredytu) ujawniły systematyczny selection bias w finalnym top-5 (zależny od kolejności alfabetycznej, nie od jakości kandydata); Run 2 ujawnił dodatkowo, że pełna sekwencyjna analiza >150 kandydatów przekracza nawet podniesiony limit czasu (180→350 min). Decyzja właścicielki: **OPCJA 3** — dodanie warstwy operacyjnej (NIE zmiana metodologii scoringu): etap 1 = deterministic ranking WSZYSTKICH screened kandydatów (zero LLM, reużywa zamrożony `backtest_harness.compute_deterministic_score`/`evaluate_deterministic_hard_gates` z Fazy 5.3, żaden nowy proxy score), etap 2 = pełna analiza Claude WYŁĄCZNIE dla shortlisty (TOP 20 + remisy, operacyjny/kosztowy budget, NIE próg inwestycyjny), z resumable per-kandydat stanem (PENDING/COMPLETE/FAILED) i cache po (cik, data_timestamp, config_version, prompt_schema_version, source_fingerprint). Finalny raport generowany TYLKO, gdy CAŁA shortlist jest COMPLETE — inaczej status `INCOMPLETE_LLM_ANALYSIS`, nigdy partial top-N. GAP/FEASIBILITY CHECK potwierdził: safety/valuation/dividend (50 z 100 pkt) są w pełni deterministyczne, tylko business_quality/fear wymagają LLM — `deterministic_score_pct` już istniał i był używany przez całą Fazę 5.3-5.6, zero nowej metryki. Nowy command `analyze-live-scan-shortlist --run-id` do wznowienia. 26 nowych testów (612 passed, 1 skipped łącznie). Zero zmian scoring weights/valuation mechanics/hard gates/decline thresholds/prefilter rules/PIT methodology. Pełne szczegóły: patrz „Faza 6c" niżej. Poprzedni status (v1.56): **Faza 6: DOMKNIĘCIE MVP V0 — trwałe ograniczenie metodologiczne zapisane + GAP ANALYSIS + implementacja ZAKOŃCZONA (2026-10-05).** Decyzja właścicielki po zamknięciu Fazy 5.4/5.6 (klasyfikacja holdoutu B): final holdout NIE uzasadnia tuningu/reweight/usunięcia valuation — zapisane jako trwałe ograniczenie metodologiczne (4 punkty, patrz „Faza 6" niżej), Scanner V0 = decision-support/opportunity-screening system, NIE validated alpha model. GAP ANALYSIS istniejącego pipeline'u (Fazy 0-4) względem docelowego live flow (CURRENT MARKET → current universe → fundamentals → decline screening → scoring+hard gates → valuation → Claude qualitative → anti-confirmation-bias → source assembly → final report): **3 realne gapy** znalezione i naprawione — (1) anti-confirmation-bias layer miał wymuszony KSZTAŁT pól (`AnalysisOutput`), ale prompt nigdy nie instruował modelu co do TREŚCI — naprawione w `prompt.py`; (2) `render_markdown_report` nigdy nie wypisywał decline trigger/bull-bear/why-market-right/thesis-invalidation/źródeł mimo że dane już istniały — naprawione w `report.py` (3 nowe opcjonalne parametry, zero zmiany zachowania bez nich); (3) brak orkiestracji end-to-end na CAŁYM aktualnym uniwersum (każdy istniejący command wymagał jawnej listy tickerów) — naprawione nowym commandem `run-live-scan` (`live_scan.py`) + workflow `phase6-live-scan.yml`. Wszystkie inne elementy flow (current universe/fundamentals/decline scanner/scoring/hard gates/valuation DCF/Claude schema/source assembly) już istniały i zostały użyte 1:1, bez przeprojektowania. 14 nowych testów, pełny zestaw: 587 passed, 1 skipped. Następny krok: pierwszy LIVE END-TO-END RUN na aktualnym rynku — wynik w sekcji „Faza 6b" (do uzupełnienia po realnym uruchomieniu). Pełne szczegóły: patrz „Faza 6" niżej. Poprzedni status (v1.55): **Faza 5.6: FINAL HOLDOUT EVALUATION ZAKOŃCZONA, jednorazowe otwarcie 2022–2026 (2026-10-05).** Holdout run (GH Actions [37346815021](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37346815021)): 58 decision dates, 615 CIK, coverage 98,11%, 7809 kandydatów, **0 zero-candidate dates**. **Primary metric (median excess 6m vs equal_weighted_pit_universe) = −2,30%** (n=6689) — ZMIANA ZNAKU względem kalibracji wewnętrznej (+0,76%, n=5834). Hit rate <50% na każdym horyzoncie względem obu benchmarków. **WSZYSTKIE 5 lat holdoutu ujemne** (vs mieszany wzorzec +/− w kalibracji) — 3 z 5 lat (2024/2025/2026) wykraczają poza najgorszy rok kalibracyjny. Spearman(score,excess) na pełnej populacji zachowuje znak i rząd wielkości (0,058 vs 0,074 w kalibracji) — nie odwrócony. Na **complete-valuation subset** (n=1429, paired): Spearman WITH valuation=0,031 vs WITHOUT valuation=0,135 na 6m — **walidacja WITHOUT > WITH na WSZYSTKICH 4 horyzontach**, wzmacniająca znalezisko Round 2B na niewidzianych danych. **Klasyfikacja: B — WEAK/INCONCLUSIVE GENERALIZATION** (mieszane sygnały: pooled wynik w granicach własnego historycznego szumu systemu, Spearman pełnej populacji nieodwrócony — ale konsystentnie ujemny rok-do-roku, odwrócenie znaku primary metric, wyraźnie słabszy Spearman na complete-valuation subset). Zero zmian configu/kodu w wyniku tego raportu — **STOP**, decyzja o dalszych krokach należy do właścicielki. Pełny 10-punktowy raport: patrz „Faza 5.6" niżej. Poprzedni status (v1.54): **Faza 5.5: FINAL PRE-HOLDOUT CONFIG ZAMROŻONY (2026-10-05).** Decyzja właścicielki: OPCJA A zatwierdzona (Round 3 nie wykazał problemu metodologicznego). `FINAL_PRE_HOLDOUT_CONFIG_v1` = `config_hash=config.yaml:9553e5c9f27ac673`, commit SHA `f20efe94675eca8fbda15699f6ffa8048497e7e8` — **identyczny z configiem sprzed Fazy 5.4** (zero zmian po Round 1+2A+2B+3). Jawne stwierdzenie wymagane przez protokół: holdout oceni oryginalną metodologię wybraną niezależnie od danych 2022–2026, nie "model po kalibracji". Od tego punktu żadna zmiana parametrów na podstawie wyników holdoutu nie jest dozwolona. Pełna specyfikacja: patrz „Faza 5.5" niżej. Następny krok: FINAL HOLDOUT EVALUATION (Faza 5.6), jednorazowe otwarcie 2022–2026. Poprzedni status (v1.53): **Faza 5.4d: ROUND 3 jako VALUATION ROBUSTNESS/SENSITIVITY (nie optimization) ZAKOŃCZONY (2026-10-05).** Decyzja właścicielki: Round 3 zmienia cel z parameter search na sprawdzenie, czy silnik wyceny jest stabilny przy rozsądnych zmianach `mos_pct_for_full_score` (35/50/65) i growth caps (15,-3 / 20,-5 / 25,-7) — zamrożona siatka 5 kandydatów (`calibration_round3.py`), bez wyboru "zwycięzcy" po forward returns. Wyniki na pełnym 615-CIK universe, complete-valuation subset n=1460 (pełne okno 2012–2021): **A) score stability** — Spearman(`valuation_score` vs default)=0,97–0,99 we wszystkich 4 wariantach, mediana zmiany=0, "duże zmiany" (>2pkt, próg opisowy) 4–23% obserwacji. **B) rank stability** — mediana rankingu per decision_date ~0,999–1,000, NAJGORSZA data dla NAJGORSZEGO wariantu wciąż 0,92 (brak zapadnięcia). **C) classification stability** — próg MoS≤0: 0,0% przekroczeń dla obu wariantów `mos_pct_for_full_score` (architektonicznie gwarantowane, potwierdzone empirycznie), 0,55–2,33% dla growth caps. **D) valuation-output stability** — median zmiany intrinsic value/MoS = 0% we wszystkich wariantach/scenariuszach (zmiana wiąże tylko mniejszość spółek z ekstremalną CAGR, zgodnie z projektem "pasa bezpieczeństwa"). **Forward-return diagnostics (TYLKO diagnostyczne)** — pooled Spearman w wąskim paśmie 0,073–0,077 (full population) i 0,113–0,126 (complete-valuation subset) we wszystkich 5 wariantach — wniosek Round 2B pozostaje jakościowo stabilny. **Brak anomalii/błędu implementacyjnego.** Rekomendacja (nie decyzja): Opcja A — domyślna mechanika wyceny bezpieczna do zamrożenia jako final config przed holdoutem. Holdout 2022–2026 nietknięty, final holdout evaluation NIE uruchomiony. Pełne tabele i metodologia: patrz „Faza 5.4d" niżej. Poprzedni status (v1.52): **Faza 5.4c: ROUND 2A/2B ZAMKNIĘTE (2026-10-05).** Epsilon_2A=0,046617 (pstdev fold-Spearmanów `2a_default`, populacja FULL_PARTIAL_MODEL n=5834) i epsilon_2B=0,140350 (pstdev fold-Spearmanów `2b_default`, populacja COMPLETE_VALUATION_SUBSET n=1111) zamrożone PRZED porównaniem pozostałych kandydatów każdej podrundy. **Round 2A** (financial_safety/dividend_shareholder_return split): wszystkie 3 warianty (`2a_safety_heavy` 20/5, `2a_dividend_heavy` 10/15, `2a_balanced` 12,5/12,5) statystycznym remisem z `2a_default` (15/10) na pooled Spearman — **zwycięzca = `2a_default`**. **Round 2B** (valuation weight na complete-valuation subset): wszystkie 3 warianty (`2b_valuation_0` CONTROL, `2b_valuation_low`, `2b_valuation_high`) remisem z `2b_default` (waga=20) — pooled Spearman monotonicznie rośnie z wagą (0,062→0,117), ale różnica mieści się w epsilon_2B (populacja mała i niestabilna między latami: 2016/2017 silnie ujemne, 2020/2021 silnie dodatnie) — **zwycięzca = `2b_default`**. **Cała Faza 5.4 (Round 1+2A+2B) kończy się zerem zmian parametrów produkcyjnych** — `config_hash=config.yaml:9553e5c9f27ac673` identyczny z configem sprzed kalibracji. Zero anomalii PIT/identity — pooled n invariant względem wag w obu podrundach (sanity check potwierdzający, że wagi nigdy nie filtrują populacji). Round 3 NIE rozpoczęty (instrukcja właścicielki: STOP po Round 2). Holdout 2022–2026 nietknięty. Pełne wyniki, tabele foldów, config hash i auditability: patrz „Faza 5.4c" niżej. Poprzedni status (v1.51): **Faza 5.4b: korekta metodologii Round 2, PRZED uruchomieniem jakiegokolwiek kandydata (2026-10-05).** Znalezisko (zweryfikowane empirycznie na produkcyjnej `evaluate_candidate_at_date`, zgłoszone właścicielce przed napisaniem kodu Round 2): primary metric Round 1 (pooled median excess return) jest matematycznie niezależna od wag scoringu w obecnym harnessie, bo wagi nigdy nie filtrują populacji funnela — tylko `hard_gates` to robią, a te są zamrożone na `None` (zwycięzca Round 1). **Decyzja właścicielki:** primary metric dla Round 2A/2B zmieniona na Spearman correlation(`deterministic_score_pct`, 6m forward excess return vs equal_weighted_pit_universe) — stara metryka zostaje jako diagnostic. Nowy, osobny epsilon "practical tie" dla skali Spearman (metoda zamrożona, wartości liczbowe po runie kandydatów `default` każdej podrundy, przed porównaniem pozostałych). Zamrożone siatki: **Round 2A** (`financial_safety`/`dividend_shareholder_return`, suma=25: `2a_default` 15/10, `2a_safety_heavy` 20/5, `2a_dividend_heavy` 10/15, `2a_balanced` 12,5/12,5) i **Round 2B** (`valuation` na complete-valuation subset, budżet kompensowany WYŁĄCZNIE przez `business_quality`: `2b_valuation_0` 0/65, `2b_valuation_low` 10/55, `2b_default` 20/45, `2b_valuation_high` 30/35; `financial_safety`/`dividend_shareholder_return`/`fear_opportunity` przypięte 15/10/10 przez całą Round 2B). Round 1 pozostaje zamknięty i niezmieniony (`baseline` zwycięzca). Holdout 2022–2026 nietknięty. Następny krok: implementacja (`calibration.py`/`calibration_round2a.py`/`calibration_round2b.py`/testy), potem uruchomienie — patrz Faza 5.4c. Poprzedni status (v1.50): **Faza 5.4a ROUND 1 (SELECTION MECHANICS) ZAMKNIĘTY (2026-10-05).** `practical tie rule` epsilon zamrożony na 2,1819 pp (pstdev 6 fold medians baseline, 6m vs equal_weighted_pit_universe, PRZED porównaniem jakiegokolwiek kandydata). 5 kandydatów uruchomionych równolegle na pełnym 615-CIK universe, okno 2012–2021 (120 decision dates), holdout 2022–2026 nietknięty: `baseline` (pooled median_excess=0,7608%, n=5834), `stricter_decline` (1,8875%, n=3124), `hard_gate_safety_floor` (0,7608%, n=2660), `prefilter_excludes` (1,1523%, n=4563), `combo_decline_and_prefilter` (1,6936%, n=2453). **WSZYSTKIE 4 warianty są statystycznym remisem z `baseline`** (|Δ|<epsilon) na primary metric — **zwycięzca ROUND 1 = `baseline`** (reguła "prostsza konfiguracja przy remisie"). Zero zmian parametrów produkcyjnych wynikających z tej rundy. Pełne wyniki, tabela foldów, obserwacje drugorzędne (fold-stability `stricter_decline` lepsza, ale nie użyta do zmiany decyzji) i auditability: patrz „Faza 5.4a" niżej. Następny krok: ROUND 2 (COMPONENT WEIGHTS — wagi safety/dividend, wpływ valuation testowany osobno na complete-valuation subsecie), może ruszyć bez dodatkowego pytania o zgodę per zatwierdzony protokół. Poprzedni status (v1.49): **Faza 5.3 BASELINE COMPLETE (2026-10-05).** 189 "rozbieżności" valuation z v1.48 WYJAŚNIONE i ZWERYFIKOWANE: `implemented=True` nie implikuje `valuation_score != None` (ujemna equity_value → `margin_of_safety_pct=None` dla BASE, zachowanie zamierzone, nie błąd); 189/189 rerunów CAŁEJ produkcyjnej ścieżki (`evaluate_candidate_at_date`) potwierdziło persisted `None` — **v1.48 pozostaje poprawny, niezmieniony**. Dwa nowe testy regresyjne (invariant: `implemented` ≠ "ma score", jedna kanoniczna ścieżka `compute_deterministic_score`, nigdy dwie niezależne implementacje logiki valuation). Trzy udokumentowane, metodologicznie zamrożone ograniczenia valuation coverage: non-positive FCF (29,8% z `valuation=None`), insufficient FCF history dla CAGR (18,2%), excluded sector methodology BANK/INSURER/REIT (11,6%). Nie zwiększamy dalej `total_debt`/valuation coverage teraz. Następny krok: Faza 5.4 — projekt protokołu kalibracji (train/holdout split, metryki, zabezpieczenia przed overfittingiem) do zatwierdzenia PRZED jakąkolwiek zmianą parametrów. Poprzedni status (v1.48): **Faza 5.3g (POST-DEBT / PARTIAL-VALUATION baseline, run `walk-forward-baseline-2026-10-05T062554Z`, artefakt GH Actions run [37272173706](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37272173706)): ZAKOŃCZONA.** Ten sam baseline co v1.45 (178 decision dates, 615 CIK, 15 656 kandydatów — funnel IDENTYCZNY, bo total_debt nie wpływa na decline scanner/prefilter/hard gates, wszystkie nieaktywne w tym configu), tylko z realnym total_debt/valuation. **Realny total_debt coverage: 38,36%** (29 265/76 292 obs., TIER_1=36,3%, TIER_2=2,1%) — zmierzony na `periods[-1]` każdej obserwacji (zakotwiczone do balance-sheet instant tego okresu), nieco inny od diagnostycznego ~40,9% z próbki 2026-10-05 (metodologia tam mierzyła "najnowszy dostępny instant jako-of decision_date", nie okres roczny zakotwiczony do net_income/revenue — oczekiwana, udokumentowana różnica). **Valuation coverage WŚRÓD KANDYDATÓW: tylko 18,5%** (2889/15 656) — niżej niż 38,36%, bo valuation wymaga DODATKOWO: dodatniego najnowszego `owner_earnings_proxy_fcf` (3805 kandydatów nie przechodzi), ≥2 okresów z dodatnim FCF do CAGR (2322), zaimplementowanej metody dla sector_profile (1475 BANK/INSURER/REIT, poza zakresem Fazy 10), diluted shares (90). **26,1% kandydatów z valuation=None MA high-confidence total_debt mimo to — total_debt NIE jest już głównym bottleneckiem, jest nim teraz ujemny/brakujący FCF.** **PAIRED porównanie WITH vs WITHOUT valuation na dokładnie tym samym complete-valuation subsecie (2889 obs.): brak jednoznacznej poprawy selekcji** — korelacja Spearmana score-vs-forward-return bliska zera dla OBU wariantów (0,03–0,09 na wszystkich horyzontach 1m/3m/6m/12m), hit rate top-half WITHOUT valuation nieznacznie WYŻSZY niż WITH na 3 z 4 horyzontów (1m/6m/12m), top/bottom spread mieszany (WITH lepszy na 1m/12m, WITHOUT lepszy na 3m/6m). Na tym (małym, nielosowym) subsecie dodanie valuation nie poprawia wykrywalnie jakości rankingu względem modelu safety+dividend. Nie kalibrować na podstawie tego wyniku — sample mały i systematycznie nielosowy (selection bias: tylko spółki GENERAL z dodatnim FCF i pełną historią). Pełny raport: patrz „Faza 5.3f/5.3g — implementacja + POST-DEBT baseline" niżej. Poprzedni status (v1.47): **Faza 5.3e (diagnostyka coverage gap total_debt, 2026-10-05) + Decyzja F ZAKOŃCZONE.** Diagnostyka na pełnym 615-CIK zbiorze: Tier 2a "CURRENT_PLUS_NONCURRENT_JOINT_INSTANT" (dopasowanie do wspólnego instant niezależnie wybieranego per tag) **ODRZUCONY** — staleness mediana 883 dni, >2 lata dla 54,9% przypadków, systematycznie pogarszający się w czasie (mediana 397 dni w 2012 → 1735 dni w 2026); formalna zgodność PIT nie wystarcza, gdy instant jest ekonomicznie nieaktualny. Tier 2 "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM" **ZAAKCEPTOWANY** — wyłącznie dla CIK, które nigdy w całej historii Company Facts nie raportowały `LongTermDebtCurrent` (zero ryzyka aliasu z konstrukcji; diagnostyka pokazała, że `DebtCurrent` jest w >50% przypadków współwystępowania dosłownym aliasem `LongTermDebtCurrent`). **Faza 5.3f (implementacja): ZAKOŃCZONA** — `total_debt.py` rozszerzony o Tier 2 + pełną provenance (`debt_resolution_method`/`confidence_tier`/`component_tags`/`component_values`/`component_provenance`/`balance_sheet_instant`), wpięty do `pit_fundamentals.py` z `target_end=end` (total_debt każdego rocznego okresu dotyczy WYŁĄCZNIE jego własnego balance-sheet instant, ta sama zasada "ten sam instant" co EBITDA) — `total_debt` NIE jest już jawnie `None`. Oczekiwane high-confidence coverage po Tier 2: ~40,90% (zmierzone na próbce diagnostycznej 2026-10-05; **realny** pomiar po tej implementacji — patrz sekcja „Faza 5.3e/5.3f" niżej). Zero zmian scoring weights/thresholds/hard gates/decline thresholds/valuation assumptions — to domknięcie danych wejściowych, nie kalibracja. Następny krok: Proof Run + ponowny ten sam baseline walk-forward (POST-DEBT / PARTIAL-VALUATION), porównanie paired z v1.45 na identycznych obserwacjach. Poprzedni status (v1.46): **Faza 5.3d (diagnostyka SEC XBRL debt tags, przed implementacją): ZAKOŃCZONA.** 10 spółek (AAPL/MSFT/KO + TERADYNE/JABIL [proste] + PG&E/Constellation Energy/EQT/DOW [złożone] + Realty Income [REIT]). Znaleziska: brak wiarygodnego pojedynczego aggregate tagu (`DebtLongtermAndShorttermCombinedAmount` użyty tylko przez MSFT, tylko 2014-2015; `DebtInstrumentCarryingAmount` obecny u wszystkich, ale semantycznie niewiarygodny — instrument-level, nie company-level); najczęstszy wzorzec `LongTermDebtCurrent+LongTermDebtNoncurrent` (zweryfikowana identyczność z `LongTermDebt` u 4/6 prostych przypadków); **realna niejednoznaczność metodologiczna u PG&E** — `LongTermDebt` tam = alias `LongTermDebtNoncurrent`, NIE suma current+noncurrent, wymaga decyzji przed implementacją; potwierdzony konkretny mechanizm double-counting (`...AndCapitalLeaseObligations` już zawiera leasing, nie dodawać osobno `FinanceLeaseLiability`); Realty Income (REIT) nie używa rodziny `LongTermDebt*` wcale, dominujący tag to `NotesPayable`. **Reguła total_debt NIE zaimplementowana** — diagnostyka ujawniła niejednoznaczność wymagającą decyzji właścicielki (patrz „Faza 5.3d" niżej, sekcja „Pozostałe otwarte pytania"). Poprzedni status (v1.45): Wszystkie Fazy 0–4 formalnie ukończone i dowiedzione na realnych danych. Faza 5.1 empirycznie potwierdzona i formalnie ukończona.** **Faza 5.2 (historyczny skład S&P 500, OPEN BLOCKER 2): EMPIRYCZNIE ZWALIDOWANA.** **Faza 5.3a (rozwiązanie ticker→CIK dla rename, LIMITED_BUT_HONEST): ZAMKNIĘTA (2026-10-01)** — kuratorowana allowlista 7 przypadków produkcyjnie wpięta, finalny coverage CIK 626/815 = 76.81%, 189 jawnie `CIK_UNRESOLVED`. **Faza 5.3b (dependency audit + backfill 615 CIK): ZAKOŃCZONA SUKCESEM, LIMITED_BUT_HONEST (2026-10-04)** — fundamentals 614/615 COMPLETE (99,8%), ceny 587/615 COMPLETE (95,4%), 13 PARTIAL + 15 FAILED (w tym BRK.B/BF.B zablokowane przez FMP "Special Endpoint"). **Faza 5.3c (REALNY pełny BASELINE walk-forward): ZAKOŃCZONA SUKCESEM (2026-10-04, run 37208774401)** — po naprawie realnego błędu identity/PIT znalezionego w trakcie tego runu (overlapping dual-class share intervals — GOOGL/GOOG, UAA/UA, NWSA/NWS, FOXA/FOX — w `universe_membership`, patrz sekcja niżej), 178 decision dates/615 CIK/2012-2026, 15 656 kandydatów, dualny benchmark (equal_weighted_pit_universe + SPY), zero kalibracji. Najważniejsze znalezisko: `valuation_score` niedostępny dla 100% kandydatów (`total_debt` zawsze `None`, znana, odłożona luka z Fazy 5.3b — skala wpływu zmierzona teraz po raz pierwszy). Hit rate kandydatów vs oba benchmarki <50% na każdym horyzoncie (1m/3m/6m/12m) — oczekiwany wynik niekalibrowanego modelu, nie dowód braku działania scannera. Pełny 10-punktowy raport: patrz „Faza 5.3c — REALNY pełny BASELINE walk-forward, wynik i raport 10-punktowy, v1.45" niżej. Ten plik jest samodzielny — nie wymaga sięgania do historii commitów.
**Data:** 2026-09-20 (v1.0–v1.4), 2026-09-21 (v1.5–v1.6), 2026-09-24–29 (v1.7–v1.33), 2026-09-30–10-04 (v1.37–v1.46)
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
**Zmiana w v1.14:** zaimplementowano Fazę 3 (sekcja 15, punkty 3.1–3.2) — integracja Claude API. Nowy kod: `buffett_scanner/analysis_schema.py` (pydantic `AnalysisOutput` odzwierciedlający dokładnie schemat z sekcji 8 + `validate_analysis_output` — reguły relacyjne, których nie wymusza sam JSON Schema: `cited_source_ids`/`verification_items`/`hard_flag_candidates` muszą być podzbiorem dostarczonej listy źródeł, `page` tylko dla potwierdzonego PDF z paginacją — BLOCKER 4, `score > max_score` → reject nie clamp), `buffett_scanner/prompt.py` (`build_analysis_prompt` — łączy wskaźniki z Fazy 1 + tylko ZWERYFIKOWANE źródła z Fazy 2 w kontekst, jawnie instruuje model, żeby nie cytował spoza listy i nie zgadywał), `buffett_scanner/providers/claude.py` (`ClaudeClient` — **oficjalne SDK `anthropic`, nie httpx**, zgodnie z zasadą „nie odtwarzaj protokołu, gdy dostawca ma oficjalne SDK"; wymusza strukturalny JSON przez `output_format=AnalysisOutput`/`client.messages.parse`, więc API samo gwarantuje zgodność kształtu — walidacja pydantic nigdy nie odrzuca z powodu złego JSON; `stop_reason == "refusal"` i pusty `parsed_output` traktowane jako błąd, nigdy jako cichy pusty wynik). Nowa sekcja configu `llm.api_key_env_var` (sekret przez zmienną środowiskową, ten sam wzorzec co `FMP_API_KEY`/`SEC_EDGAR_USER_AGENT`). Rozszerzony `cli.py` o `analyze TICKERS...` (diagnostyczny dry-run — **nie zapisuje jeszcze do `analyses`/`analysis_sources`**, te tabele powstaną dopiero w Fazie 4 razem z silnikiem scoringu, który faktycznie ich potrzebuje), nowy workflow „Phase 3 Proof Run" (domyślnie 1 ticker, żeby dry-run kosztował grosze — pierwsza faza z realnym kosztem API). Nowa zależność: `anthropic>=1.8,<2` (oficjalne SDK). 27 nowych testów jednostkowych (razem 114 zielonych). **Kod jeszcze nie zweryfikowany na realnym koncie** — wymaga nowego sekretu `ANTHROPIC_API_KEY`.
**Zmiana w v1.15:** **Faza 3 empirycznie potwierdzona w całości.** Pierwsze uruchomienie na koncie właścicielki ujawniło ucinanie odpowiedzi przez `max_output_tokens=4000` — naprawione (16000 + jawna obsługa błędu w `ClaudeClient`). Drugie uruchomienie: pełny sukces pipeline'u na AAPL, ale ujawniło realny błąd jakości danych — model po cichu przyjmował własną skalę punktową (np. `9/10`) zamiast stałych wag rubryki z sekcji 8 (`max_score` ma być zawsze `7`/`12`/`10`), czego dotychczasowa walidacja nie łapała, bo porównywała `score` względem `max_score` podanego przez sam model, nie względem prawdziwej stałej. Naprawione u źródła: `max_score` w trzech sekcjach zmienione z `int` na `Literal[7]`/`Literal[12]`/`Literal[10]` — wymuszone już na poziomie JSON Schema przekazanego do Claude API, model fizycznie nie może zwrócić innej wartości. Faza 3 formalnie ukończona.
**Zmiana w v1.16:** zaimplementowano Fazę 4 (sekcja 15, punkty 4.1–4.3) — silnik scoringu. Przed implementacją zidentyfikowano i przedstawiono do zatwierdzenia dwie realne luki specyfikacji: (1) `valuation` (waga 20) wymagało metodologii wyceny nigdzie w dokumencie nieustalonej, (2) `dividend_shareholder_return` (waga 10) wymagało danych, których Faza 1 nie pobierała. Właściciel zatwierdził pełny design (2026-09-25, patrz sekcja poniżej) z czterema korektami: payout ratio liczony względem FCF z jawnym `NOT_MEANINGFUL` gdy FCF≤0 (nie mylącą wartością ujemną), hard gate `min_margin_of_safety_pct` sprawdzany względem scenariusza BASE (nie BEAR — BEAR/BULL zostają jako dodatkowe wskaźniki widoczne w raporcie), Owner Earnings jawnie nazwane `owner_earnings_proxy_fcf` (uproszczenie = FCF, nie pełna klasyczna koncepcja), wszystkie parametry wyceny konfigurowalne/wersjonowane/`UNCALIBRATED`.

Nowy kod: rozszerzenie `FundamentalsPeriod`/`fundamentals_raw`/`normalize_fundamentals_rows` o 3 pola (`dividends_paid`, `share_buybacks`, `diluted_shares_outstanding` — **niepotwierdzone** nazwy pól FMP, jak pierwotne 9 w Fazie 1, do weryfikacji kolejnym `ingest-fundamentals`); `buffett_scanner/valuation.py` (DCF na Owner Earnings proxy, tempo wzrostu DERIVED z historycznej CAGR FCF spółki, nie zgadywane, ograniczone sufitem/podłogą z configu; dyskonto/terminal growth WYŁĄCZNIE z configu; walidator configu wymuszający `terminal_growth < discount_rate` — wymóg matematyczny wzoru Gordona, nie preferencja; `NOT_YET_IMPLEMENTED` z jawnym `reason`, gdy dane nie wystarczają — nigdy liczba "na oko"); `buffett_scanner/shareholder_returns.py` (dividend/shareholder yield, `_no_dividend_cut`/`share_count_trend` jako `bool|None`/`Literal|None` — rozróżniają "potwierdzone dobrze" od "nie wiadomo", żeby brak danych nigdy nie fabrykował kredytu punktowego); `buffett_scanner/scoring.py` (orkiestrator: `financial_quality_score` 0-16 deterministyczny, `business_quality_score` liniowe skalowanie 29→45, hard gates, `total_score` — `None`+`is_partial=True` gdy jakikolwiek komponent niepoliczalny, nigdy fałszywie kompletna suma); `buffett_scanner/report.py` (generator raportu Markdown, punkt 4.3). Nowe tabele DB `scoring_model_versions`/`analyses`/`analysis_sources` (IMMUTABLE — INSERT-only, nigdy UPDATE, sekcja 11) — domyka lukę z Fazy 2, gdzie `VerifiedSource` nie miał gdzie trafić. Rozszerzony `cli.py` o `score TICKERS... [--markdown-out DIR]`, nowy workflow „Phase 4 Proof Run". 57 nowych testów jednostkowych (razem 172, w tym 1 pominięty integracyjny), w tym niezależny hand-check poprawności wzoru DCF (perpetuita: enterprise_value = OE/discount_rate przy zerowym wzroście — nie tylko re-uruchomienie tej samej formuły). **Kod jeszcze nie zweryfikowany na realnym koncie.**
**Zmiana w v1.17:** **Faza 4 empirycznie potwierdzona w całości** — Phase 4 Proof Run na AAPL ujawnił, że `dividends_paid`<-`dividendsPaid` było błędne (pole nie istnieje w odpowiedzi FMP); naprawione na `commonDividendsPaid` (potwierdzone surowym JSON-em, workflow „FMP Smoke Test"). `share_buybacks`/`diluted_shares_outstanding` były poprawne za pierwszym razem. Po naprawie: realistyczne liczby dla AAPL (DPS≈1.03 USD, payout ratio≈15.6%, shareholder yield≈2.1%). Silnik DCF na prawdziwych danych: BASE MoS=-271.5% — oczekiwany skrajny wynik dla `UNCALIBRATED` parametrów, nie błąd. Faza 4 formalnie ukończona.
**Zmiana w v1.18:** zaimplementowano Fazę 5.1 (sekcja 15, punkt 5.1 — OPEN BLOCKER 1). Nowy kod: `SecEdgarClient.get_company_facts` (nowy endpoint SEC EDGAR XBRL company-facts API, każdy fakt z polem `filed`); `buffett_scanner/point_in_time.py` — `extract_fact_history`/`find_first_matching_tag` (defensywne dopasowanie kandydujących tagów XBRL per koncept — różne spółki tagują ten sam koncept różnymi tagami, np. `Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax`, jawnie raportowane który zadziałał) i `value_as_of` — rdzeń PIT: "jaka była ostatnia wartość X *filed* na dzień <= D". Kluczowy test demonstruje dokładnie mechanizm eliminujący look-ahead bias: symulowany restatement (ta sama wartość zgłoszona dwukrotnie z różnymi `filed`) poprawnie zwraca oryginalną wartość dla zapytań sprzed korekty i skorygowaną dla zapytań po niej. Rozszerzony `cli.py` o `pit-prototype TICKERS... [--as-of DATE]` — pobiera realną historię XBRL i porównuje najnowszą wartość PIT z danymi "as reported" z FMP (Faza 1) jako sanity-check rzędu wielkości. Nowy workflow „Phase 5.1 Proof Run" — nie wymaga żadnego nowego sekretu. 14 nowych testów (186 razem). **Kod jeszcze nie zweryfikowany na realnym koncie.**
**Zmiana w v1.19:** **Pierwsze uruchomienie „Phase 5.1 Proof Run" (2026-09-25) na AAPL/MSFT/KO ujawniło realny błąd w `value_as_of`.** Dowód: dla wszystkich trzech spółek zwrócony fakt miał `end` nawet ~2 lata starszy niż `filed` (np. MSFT: `end=2024-06-30`, `filed=2026-07-29`) — anomalia, bo 10-K/10-Q musi trafić do SEC w ciągu maksymalnie ~60–90 dni od `end`, nigdy lat. Przyczyna: `max(eligible, key=lambda f: f.filed)` przy REMISIE na `filed` (bardzo częsty przypadek — jeden 10-K/10-Q zawsze zawiera też dane porównawcze z 1–2 poprzednich lat/kwartałów, złożone tego samego dnia co bieżący okres) zwracał pierwszy napotkany fakt w kolejności z JSON-a SEC (stary okres porównawczy), nie okres z najnowszym `end`. Hipoteza zweryfikowana niezależnie od realnego przebiegu: syntetyczny test ze starym kodem na danych ułożonych dokładnie jak w scenariuszu MSFT zwrócił **dokładnie tę samą wartość co w realnym uruchomieniu** (88136000000) — potwierdzenie przyczyny, nie zgadywanie. Naprawione: remis na `filed` rozstrzygany teraz na korzyść najnowszego `end` (`key=lambda f: (f.filed, f.end)`). Nowy test regresyjny `test_value_as_of_breaks_filed_tie_by_latest_end_not_json_order` odtwarza dokładnie ten scenariusz z realnych danych MSFT. 187 testów razem (186 passed + 1 integracyjny pominięty), wszystkie zielone po naprawie. **Kod naprawiony, oczekuje ponownego uruchomienia workflow na realnym koncie.**
**Zmiana w v1.20:** **Drugie uruchomienie „Phase 5.1 Proof Run" (2026-09-25) na naprawionym kodzie — sukces.** Dla wszystkich trzech spółek `end` jest teraz w rozsądnej odległości od `filed` (27–34 dni, zgodne z terminami SEC), nie lata jak przed naprawą. **MSFT dał dokładne (co do dolara) potwierdzenie krzyżowe:** PIT z SEC XBRL (net_income=133749000000, revenue=331839000000, 10-K FY2026) identyczne z danymi „as reported" z FMP dla tego samego okresu — niezależny dowód poprawności obu ścieżek danych. Dla AAPL/KO porównanie pozostaje rzędu wielkości (KO ~26–30% wartości rocznej, zgodne z jednym kwartałem; AAPL ~88–91%, sugerujące że fakt XBRL może być skumulowany od początku roku fiskalnego, nie pojedynczy kwartał — `PitFact` nie przechowuje obecnie `start` kontekstu XBRL, więc nie rozróżnia duration; udokumentowane jako ograniczenie do adresowania w Fazie 5.3, nie blokuje zamknięcia prototypu). **Faza 5.1 formalnie ukończona.**
**Zmiana w v1.21:** na wyraźną prośbę właściciela, przed jakimkolwiek kodem: pełne porównanie źródeł danych do historycznego składu S&P 500 (OPEN BLOCKER 2, Faza 5.2), oparte na realnym sprawdzeniu w tej sesji (dokumentacja FMP, repozytorium `fja05680/sp500` — README, format plików, przykładowe wiersze), nie na pamięci. Ustalenia: (1) FMP `stable/historical-sp-500` to log zdarzeń zmian (nie snapshoty), głębokość historyczna i wymagany tier planu wciąż **NIEPOTWIERDZONE** (strona FMP zablokowana przez proxy sieciowy w tym środowisku); (2) `fja05680/sp500` (plik „Updated") to pełne snapshoty per data zmiany, zakres 1996–dziś, z jawnie przyznanym przez autora ryzykiem niekompletności pierwszych ~5 lat, i z tym, że część 2019+ pochodzi z Wikipedii (nie w pełni niezależna od niej jako trzeciego źródła); (3) oba źródła identyfikują spółki wyłącznie przez ticker, nie CIK — centralne ryzyko techniczne do rozwiązania przez `ticker_history`, z zasadą `CIK_UNRESOLVED` zamiast zgadywania; (4) schemat `universe_membership(cik, index_name, start_date, end_date)` **już istnieje** w projekcie od v1.0 — Faza 5.2 buduje adaptery do niego, nie nowy schemat; (5) trzecie pełne źródło (Norgate, ETF holdings) odłożone — Wikipedia służy tylko jako tani sanity-check „skład na dziś". Przedstawione konkretne otwarte pytania do decyzji właściciela. **Zero kodu napisanego, implementacja wstrzymana do zatwierdzenia.**
**Zmiana w v1.22:** właściciel zatwierdził plan z trzema decyzjami (zacząć krok 2 teraz; zaakceptować `CIK_UNRESOLVED`; rekonstruować produkcyjnie tylko okno 2012+). Zaimplementowano krok 2: `buffett_scanner/universe_history.py` (parser CSV, budowanie okna od cutoff, diff snapshotów → przedziały członkostwa per ticker, rozwiązanie ticker→CIK bez zgadywania), `providers/sp500_history.py` (transport fja05680), `SecEdgarClient.get_company_tickers()` (mapowanie SEC), CLI `analyze-sp500-history`, workflow „Phase 5.2 Proof Run". **Realne pobranie pliku `fja05680/sp500` w tej sesji ujawniło, że wcześniejsze wtórne źródło (WebFetch summary z v1.21, „ostatnia aktualizacja maj 2021") było błędne** — plik faktycznie sięga do 2026-08-18 (zawiera TSLA/SMCI/TKO i inne spółki dodane długo po 2021), złapane przez bezpośrednią weryfikację surowych danych. Wyniki na oknie 2012+: 918 wierszy, 815 dystynktywnych tickerów, 831 przedziałów członkostwa (16 z ponownym wejściem), 503 wciąż otwartych (zgodne z aktualnym rozmiarem indeksu — sanity-check przeszedł). Obserwacja jakości: liczba zmian/rok spada z ~105–130 (2012–2018) do ~13–19 (2019+), zgodnie ze strukturą źródła opisaną w jego README — sugeruje możliwe zawyżenie liczby zdarzeń w latach 2012–2018 przez konflację zmian tickera ze zmianami składu. **Rozwiązanie ticker→CIK: kod gotowy, ale realne liczby jeszcze nieuzyskane** — `sec.gov` zablokowany przez politykę sieciową tej interaktywnej sesji (potwierdzone, nie zgadywane), wymaga uruchomienia nowego workflow na koncie właścicielki. 25 nowych testów (206 razem). **Brak decyzji o finalnym zapisie do `universe_membership`.**
**Zmiana w v1.23:** pierwsze uruchomienie „Phase 5.2 Proof Run" na koncie właścicielki dało realne liczby: **RESOLVED 617/815 (75,7%), CIK_UNRESOLVED 198/815 (24,3%)**. Przegląd nierozwiązanych tickerów (wiedza ogólna o historii spółek, nie ponowna weryfikacja JSON SEC) pokazał, że większość to prawdziwe zdarzenia korporacyjne (przejęcia, fuzje, bankructwa, zmiany tickera jak FB→META) — oczekiwane, nie błąd. Znaleziono i naprawiono jeden konkretny, naprawialny przypadek: BRK.B/BF.B (obie aktywne dziś) nie rozwiązywały się przez format zapisu klasy akcji (kropka vs myślnik). `resolve_tickers_to_cik` dostał drugi przebieg (wariant formatu, jawnie raportowany, nigdy nie ukrywający że to nie bezpośrednie dopasowanie) — świadomie NIE naprawia zmian nazwy (FB→META, inny problem). Dodano rozbicie `CIK_UNRESOLVED` na wciąż-aktywne vs tylko-historyczne dla oceny wpływu na pokrycie backtestu. 5 nowych testów (210 razem). Czeka na drugie uruchomienie workflow, żeby potwierdzić zawężoną liczbę.
**Zmiana w v1.24:** **Drugie uruchomienie „Phase 5.2 Proof Run" (2026-09-25), z naprawą — potwierdza hipotezę w 100%.** RESOLVED: 619/815 (617 bezpośrednio + dokładnie 2 przez wariant formatu: `BF.B→BF-B`, `BRK.B→BRK-B`, zgodnie z przewidywaniem). CIK_UNRESOLVED: 196/815. **Kluczowy wynik: 0 nierozwiązanych wśród 503 dzisiejszych aktywnych spółek — cała niepewność (196/312, 62,8%) dotyczy wyłącznie spółek, które opuściły indeks w oknie 2012+** (potwierdza hipotezę: przejęcia/fuzje/bankructwa/zmiany nazwy, nie defekt kodu). Krok 2 Fazy 5.2 formalnie zakończony, empirycznie potwierdzony. Pozostają: krok 1 (test FMP), krok 3 (porównanie krzyżowe), decyzja o zapisie do `universe_membership` — żadne jeszcze niewykonane.
**Zmiana w v1.25:** zaimplementowano krok 1 (FMP Smoke Test), na wyraźne zastrzeżenie właściciela: bez zakupu/założenia żadnego płatnego planu, bez zakładania z góry maksymalnego dostępnego zakresu historycznego. Nowa metoda `FMPClient.get_historical_sp500_constituents()` — nazwa endpointu niepotwierdzona w dokumentacji, próbuje dwóch kandydatów po kolei (`historical-sp500-constituent`, `historical-sp-500`), jawnie raportuje który zadziałał (wzorzec identyczny z `find_first_matching_tag`, Faza 5.1). Rozszerzony `fmp_smoketest.py` o blok wypisujący zakres dat i jawne sprawdzenie „sięga do 2012-01-01: True/False". 3 nowe testy (213 razem). Żaden nowy sekret/workflow — istniejący „FMP Smoke Test" uruchomi się na kodzie branchu. **Kod gotowy, jeszcze nie uruchomiony na realnym koncie.**
**Zmiana w v1.26:** pierwsze uruchomienie „FMP Smoke Test" dało niejednoznaczny wynik — kod raportował tylko błąd OSTATNIEGO kandydata (404 dla `historical-sp-500`), ukrywając wynik pierwszego kandydata (`historical-sp500-constituent`, prawdopodobnie właściwa nazwa wg dodatkowego WebSearch, choć bez potwierdzonego przykładu `curl`). Naprawione: `get_historical_sp500_constituents()` zwraca teraz wynik KAŻDEGO kandydata z osobna (402 „wymaga planu" vs 404 „zła ścieżka" to różne wnioski), `fmp_smoketest.py` wypisuje obie próby jawnie. 1 nowy test regresyjny + korekta 2 istniejących pod nowy kształt zwracanej krotki. 214 testów razem. Czeka na drugie uruchomienie.
**Zmiana w v1.27:** drugie uruchomienie „FMP Smoke Test" dało jednoznaczny wynik — `historical-sp500-constituent` (bez myślnika) potwierdzony jako prawdziwy endpoint (402 „Restricted Endpoint", ten sam wzorzec co `sp500-constituent`), `historical-sp-500` (z myślnikiem, wcześniejszy trop z docs-page slug) potwierdzony jako fałszywy (404). Dokładny wymagany tier planu NIEUSTALONY — komunikat 402 nie nazywa konkretnego planu, strona cennika FMP zablokowana w tej sesji, dodatkowy WebSearch nie znalazł wiarygodnego potwierdzenia. Krok 1 Fazy 5.2 formalnie zakończony: nie da się ocenić proporcjonalności kosztu FMP bez zakupu. Właściciel zdecydowała: NIE kupować, szukać niezależnego darmowego/taniego trzeciego źródła zamiast tego. Research (WebSearch/WebFetch, zero kodu): najsilniejszy znaleziony kandydat to **historyczne holdingi ETF iShares IVV** (`ishares.com`, parametr `asOfDate=YYYYMMDD`) — potwierdzone dwoma niezależnymi narzędziami trzecimi (GitHub `talsan/ishares`, PyPI `etf-scraper`): zakres ~2006–2010+ (pokrywa 2012+), darmowe, bezpośredni snapshot realnego portfela (nie log zdarzeń), pełna niezależność od fja05680/Wikipedii. Odrzucone: SPY/SSGA (tylko najnowsze holdingi, brak archiwum), Vanguard/Invesco (tylko ostatni miesiąc), Norgate/CRSP (płatne/instytucjonalne, nie badane wobec darmowej opcji). **`ishares.com` zablokowany w tej sesji (jak `sec.gov`) — dokładny kształt CSV/kolumn NIEZWERYFIKOWANY, wymaga empirycznego testu przed jakimkolwiek kodem parsującym.** Rekomendacja przedstawiona, zero kodu, zero decyzji o `universe_membership`.
**Zmiana w v1.28:** właściciel zatwierdziła minimalny Proof Run dla IVV przez GitHub Actions. Nowy kod: `providers/ivv_holdings.py` (transport, parametr `asOfDate`), `ivv_holdings_parse.py` (parser defensywny — nigdy nie zakłada stałej liczby wierszy preambuły; realny błąd znaleziony w trakcie pisania testów: wiersz stopki bez przecinków mapował się cały do pola `Ticker` przez `csv.DictReader`, naprawione wymogiem kompletności wiersza `None not in r.values()`), `universe_history.tickers_as_of`/`compare_ticker_sets` (porównanie z fja05680), `ivv_holdings_smoketest.py` (Proof Run na 3 celowo wybranych datach: 2012-01-31, 2018-12-31, 2026-09-22 — surowy podgląd, sprawdzenie czy `asOfDate` realnie różnicuje wynik, porównanie z fja05680). Nowy workflow „Phase 5.2 IVV Proof Run" — zero sekretów, zero kosztu. 16 nowych testów (227 razem). Cały skrypt zweryfikowany lokalnie end-to-end na syntetycznym fixture przed pushem — potwierdza brak błędów integracyjnych, NIE zastępuje testu na realnych danych IVV. **Kod gotowy, jeszcze nie uruchomiony na realnym koncie.**
**Zmiana w v1.29:** **uruchomienie „Phase 5.2 IVV Proof Run" na koncie właścicielki — wynik NEGATYWNY, jednoznaczny.** Wszystkie 3 zapytane daty (2012-01-31, 2018-12-31, 2026-09-22) zwróciły identyczną stronę HTML produktu, nie CSV — mechanizm `asOfDate` opisywany przez dwa niezależne narzędzia trzecie (`talsan/ishares`, `etf-scraper`) **nie działa na obecnej wersji ishares.com** (prawdopodobna zmiana struktury strony od czasu powstania tych narzędzi — typowe ryzyko scraperów, nie oficjalnych API). Parser zadziałał defensywnie poprawnie: zgłosił „NIEROZPOZNANA STRUKTURA", nie fabrykował danych. Wartościowe uboczne znalezisko: strona sama podaje w JSON-LD prawdziwy, potwierdzony URL CSV — `.../latest-holdings.csv` — ale nazwa („latest") silnie sugeruje wyłącznie bieżący skład, nie historyczny. **IVV istotnie osłabiony jako kandydat na niezależne źródło walidacji 2012+** — wciąż potencjalnie użyteczny jako tani sanity-check „na dziś", ale nie jako drugie niezależne źródło historyczne bez dalszego researchu (możliwe archiwum Wayback Machine lub inny nieodkryty mechanizm — niezbadane). Decyzja o dalszym kierunku wymaga wyboru właścicielki.
**Zmiana w v1.30:** właścicielka zatwierdziła wynik negatywny i formalnie **odrzuciła IVV jako kandydata na niezależną walidację historyczną** — bez dalszego reverse-engineeringu iShares ani poszukiwania nieoficjalnych mechanizmów dostępu (Wayback Machine, inne endpointy). Zamiast tego kontaktuje się z supportem FMP w sprawie: dostępu do `historical-sp500-constituent`, zakresu co najmniej 2012+, i opcji wykupienia Premium na jeden okres rozliczeniowy z późniejszym downgrade'em do Starter. **OPEN BLOCKER 2 pozostaje formalnie otwarty. Sesja wstrzymana do czasu odpowiedzi FMP** — zero kodu, zero dalszego researchu, zero decyzji o `universe_membership` do tego czasu.
**Zmiana w v1.31:** właścicielka aktywowała plan **FMP Premium** i wznowiła krok 1. Rozszerzony `fmp_smoketest.py`: blok `historical-sp500-constituent` teraz zbiera klucze widoczne w CAŁYM zbiorze (nie tylko pierwszym wierszu — różne rekordy mogą mieć różny kształt), liczy niepuste/unikalne wartości pól `symbol`/`removedTicker` (dwa pola nazwane w candydacie z researchu v1.21, jeszcze niepotwierdzone bezpośrednim widokiem realnej odpowiedzi), sumę unikalnych tickerów (`symbol ∪ removedTicker`), wiersze bez `date` (anomalia), wiersze bez żadnego tickera (anomalia), dokładne duplikaty `(date, symbol, removedTicker)`. Zweryfikowane offline na syntetycznych danych z celowo wstrzykniętymi anomaliami (brakująca data, duplikat, brak tickera) — logika poprawnie je wykrywa, zero crashy. **Kod gotowy, jeszcze nie uruchomiony na koncie Premium.** Żaden nowy sekret/workflow — istniejący „FMP Smoke Test" uruchomi się na kodzie branchu.
**Zmiana w v1.32:** **uruchomienie „FMP Smoke Test" na koncie Premium (2026-09-26) — endpoint DZIAŁA.** `historical-sp500-constituent`: 1528 wierszy, zakres dat **1957-03-03 do 2026-09-21** (daleko poza wymagane 2012+). Pola potwierdzone bezpośrednio: `date`, `dateAdded`, `symbol` (dodany ticker), `addedSecurity`, `removedTicker`, `removedSecurity`, `reason`. Zero wierszy bez daty, zero bez tickera, zero dokładnych duplikatów wg zaimplementowanych sprawdzeń. **Realna anomalia znaleziona ręcznie w przykładowych wierszach:** dla najstarszego wiersza `date='1957-03-03'` a `dateAdded='March 04, 1957'` — rozjazd o 1 dzień (dla najnowszego wiersza oba pola się zgadzają) — potwierdza zasadę „nie zakładać poprawności danych tylko dlatego, że pochodzą z FMP".

**Zmiana w v1.33:** **uruchomienie „Phase 5.2 FMP vs fja05680 Comparison" na pełnych danych (2026-09-26) — krok 3 zakończony.** Systematyczne sprawdzenie: 171/1528 (11,2%) wierszy FMP ma rozjazd `date`/`dateAdded`, z tego 17 w oknie 2012+. Dokładne dopasowanie zdarzeń (date+ticker+action) dało pozornie słaby wynik (108/613 FMP, 108/662 fja05680) — **zdiagnozowane jako artefakt metody, nie realna rozbieżność**: te same zdarzenia korporacyjne zapisane z przesunięciem 1–3 dni między źródłami (potwierdzone na konkretnych przykładach: FOSL/MHS, PSX/SVU, ALXN/EP/KMI). Porównanie luźniejsze (same tickery, bez daty) dało 96,5%/87,3% zgodności. **Rekonstrukcja na 3 datach pokazała kluczowy, jednoznaczny wzorzec: zgodność rośnie monotonicznie ku teraźniejszości — 92,9% (2012-01-31) → 93,7% (2018-12-31) → 99,6% (2026-09-01, po uwzględnieniu już znanej różnicy formatu BF.B/BRK.B).** To bezpośrednia konsekwencja metody rekonstrukcji wstecznej FMP (więcej zdarzeń po drodze = więcej okazji na przesunięcia dat). **Znaleziony realny problem strukturalny:** część tickerów „tylko w FMP" przy starszych datach (BBWI, ELV, CTRA, COR, GEN, BKR) to spółki, które zmieniły ticker bez opuszczenia indeksu — FMP nie zawsze notuje to jako zdarzenie, więc rekonstrukcja wsteczna (zaczynająca od dzisiejszego tickera) błędnie projektuje go w przeszłość. To ograniczenie metody diagnostycznej (ticker jako klucz), nie błąd danych FMP — dokładnie ten sam problem, dla którego projekt od v1.0 używa CIK. **Rekomendacja: fja05680 (snapshot, architektonicznie zgodny z `universe_membership`) jako podstawowe źródło, FMP jako niezależny walidator, CIK jako obowiązkowy klucz identyfikacji.** 5 pozostałych ryzyk zidentyfikowanych i spisanych (CIK dla strony FMP niewykonany, brak reguły rozstrzygania rozbieżności, tolerancja dat, wewnętrzna niespójność FMP, okno 1996–2011 poza zakresem). **Zatrzymano przed implementacją `universe_membership`.**

Krok 1 Fazy 5.2 formalnie zakończony (empirycznie potwierdzony). Zaimplementowano krok 3 (walidacja krzyżowa): nowy moduł `buffett_scanner/fmp_sp500_events.py` — `parse_fmp_events` (defensywny parser, pusty string w `removedTicker`/`removedSecurity` → `None`), `find_date_added_mismatches` (systematyczne sprawdzenie anomalii date/dateAdded na CAŁYM zbiorze, nie tylko przykładach — odtwarza dokładnie realne znalezisko z 1957 jako test regresyjny), `reconstruct_membership_backward` (FMP daje LOG ZDARZEŃ, nie snapshoty jak fja05680 — rekonstrukcja składu na dowolną datę wymaga punktu odniesienia; jedynym pewnym jest DZISIEJSZY potwierdzony skład z `sp500-constituent`, więc rekonstrukcja idzie wstecz, odwracając kolejne zdarzenia), `fmp_change_events`/`compare_change_events` (dokładne porównanie zdarzeń date+ticker+ADD/REMOVE między źródłami). Nowy skrypt `fmp_sp500_comparison_smoketest.py` — pełny raport: anomalie FMP, porównanie zdarzeń (dokładne i „luźniejsze" — same tickery dotknięte, odporne na rozbieżności formatu daty), rekonstrukcja składu na 3 próbnych datach (2012-01-31, 2018-12-31, 2026-09-01) obiema metodami z bezpośrednim porównaniem. Nowy workflow „Phase 5.2 FMP vs fja05680 Comparison" (wymaga `FMP_API_KEY`, już istnieje). 10 nowych testów jednostkowych — w tym niezależnie ręcznie zweryfikowana matematyka `reconstruct_membership_backward` (cofanie zdarzeń krok po kroku sprawdzone na papierze, nie tylko odtworzenie tej samej logiki w teście). **Realny błąd integracyjny złapany przez offline dry-run przed pushem:** skrypt używał nieistniejących atrybutów `only_a`/`only_b` zamiast prawdziwych `only_in_a`/`only_in_b` z `TickerSetComparison` (Faza 5.2 krok 2) — naprawione, cały skrypt ponownie zweryfikowany end-to-end na syntetycznych danych z prawdziwym plikiem fja05680, wynik rekonstrukcji ręcznie sprawdzony na papierze. 237 testów razem (236 passed + 1 integracyjny pominięty). **Kod gotowy, jeszcze nie uruchomiony na realnych pełnych danych FMP.**

---

### Minimalny Proof Run: IVV jako niezależne źródło (v1.28–v1.29) — mechanizm asOfDate NIE DZIAŁA, ustalenie negatywne

Właściciel zatwierdziła empiryczną weryfikację IVV przez GitHub Actions, analogicznie do wcześniejszych Proof Runów, z jawnym zastrzeżeniem: **minimalny test, bez budowy finalnego adaptera, bez zapisu do `universe_membership`.**

**Nowy kod (pokryty testami, hand-verified na syntetycznych przykładach; realny kształt CSV wciąż niezweryfikowany bezpośrednim testem — kod pisany defensywnie z tego powodu):**
- `buffett_scanner/providers/ivv_holdings.py` — `fetch_ivv_holdings_csv(as_of_date)`: transport (GET `ishares.com` z parametrem `asOfDate=YYYYMMDD`), zero logiki parsującej. Nagłówek `User-Agent` ustawiony defensywnie (NIEPOTWIERDZONE, czy jest wymagany).
- `buffett_scanner/ivv_holdings_parse.py` — `parse_ivv_holdings_csv`: **defensywny parser, nigdy nie zakłada stałej liczby wierszy preambuły** — lokalizuje wiersz nagłówka po obecności kolumny `Ticker`, odrzuca wiersze niepełne (mniej pól niż nagłówek — `None` w `DictReader`, odróżnione od pola obecnego-ale-pustego = `''`). **Realny błąd złapany w trakcie budowy testów, nie w produkcji:** wiersz stopki/disclaimeru bez przecinków („The content contained herein is proprietary to BlackRock...") mapował się przez `csv.DictReader` w całości do pola `Ticker` (pierwsza kolumna) — naprawione przez wymóg `None not in r.values()`, czyli że wiersz musi mieć KOMPLETNĄ liczbę pól, nie tylko niepuste pole `Ticker`.
- `buffett_scanner/universe_history.py` — dodano `tickers_as_of(rows, date)` (ten sam wzorzec co `value_as_of` z Fazy 5.1: najnowszy wiersz fja05680 z datą ≤ zadana) i `compare_ticker_sets(a, b)` (czyste liczenie części wspólnej/różnic, bez interpretacji przyczyn — to wymaga kontekstu biznesowego po zobaczeniu realnych danych).
- `buffett_scanner/providers/ivv_holdings_smoketest.py` — skrypt Proof Run (wzorzec identyczny z `fmp_smoketest.py`/`sec_edgar_smoketest.py`): dla trzech celowo wybranych dat (`2012-01-31` — blisko początku okna 2012+, `2018-12-31` — okres środkowy, `2026-09-22` — data współczesna) pobiera holdingi IVV, wypisuje surowy podgląd (15 pierwszych linii — do ręcznej inspekcji realnego kształtu), lokalizuje linię „as of" w metadanych (sprawdzenie, czy `asOfDate` faktycznie zmienia zwracane dane, nie tylko zwraca bieżący plik), porównuje wynikowy zbiór tickerów z `fja05680/sp500` na tę samą datę (liczebności, część wspólna, różnice w obie strony), i na końcu jawnie sprawdza, czy wszystkie trzy zapytane daty dały ten sam zbiór tickerów (sygnał, że `asOfDate` mógłby być ignorowany, gdyby tak się stało).
- Nowy workflow **„Phase 5.2 IVV Proof Run"** — żaden sekret, żaden koszt (oba źródła darmowe, bez autoryzacji).
- 16 nowych testów jednostkowych (razem 227, w tym 1 integracyjny pominięty), wszystkie zielone.

**Weryfikacja lokalna przed pushem (offline dry-run):** uruchomiono cały skrypt lokalnie z prawdziwym plikiem `fja05680/sp500` (ten sam pobrany w Fazie 5.2 krok 2) i syntetycznym, spreparowanym CSV IVV — potwierdzono, że cała logika (parsowanie, porównanie zbiorów, wykrywanie „identycznego wyniku dla różnych dat") działa end-to-end bez błędów. To NIE jest weryfikacja realnych danych IVV (syntetyczny fixture, celowo identyczny dla wszystkich dat) — tylko potwierdzenie, że kod nie ma oczywistych błędów integracyjnych przed pierwszym realnym uruchomieniem.

**Kod gotowy, jeszcze nie uruchomiony na realnym koncie.** Czeka na zatwierdzenie pushu workflow na `main` i uruchomienie przez właścicielkę.

**Uruchomienie na realnym koncie (2026-09-26) — wynik negatywny, jednoznaczny.** Wszystkie trzy zapytane daty (`2012-01-31`, `2018-12-31`, `2026-09-22`) zwróciły **dokładnie tę samą** odpowiedź: standardową stronę HTML produktu IVV (`<!DOCTYPE html>...`), nie CSV. Parser poprawnie zadziałał defensywnie — zgłosił „NIEROZPOZNANA STRUKTURA" zamiast crashować lub fabrykować dane. Krok C (sprawdzenie, czy `asOfDate` różnicuje wynik) wykazał **0 różnych zbiorów tickerów wśród 3 dat** — nie dlatego, że dane się nie zmieniają, tylko dlatego, że URL w ogóle nie zwraca CSV holdingów, tylko generyczną stronę produktu, identyczną niezależnie od parametru.

**Wniosek: mechanizm `asOfDate` na starym URL-u `.../1467271812596.ajax?fileType=csv&...` opisywany przez dwa niezależne narzędzia trzecie (GitHub `talsan/ishares`, PyPI `etf-scraper`) NIE DZIAŁA na obecnej wersji strony ishares.com** — najprawdopodobniej iShares zmienił strukturę strony od czasu, gdy te narzędzia powstały (typowe dla scraperów stron webowych, nie oficjalnych API — nie ma kontraktu stabilności). To nie błąd naszego kodu ani złej implementacji — realna, potwierdzona zmiana po stronie źródła.

**Konkretne, wartościowe znalezisko z treści zwróconej strony:** w osadzonym JSON-LD (`schema.org/DataDownload`) strona sama podaje aktualny, prawdziwy link do CSV:
```
"contentUrl":"https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/latest-holdings.csv"
```
Nazwa pliku — **„latest-holdings"** — silnie sugeruje, że ten confirmed URL daje wyłącznie BIEŻĄCY skład, bez parametryzacji historyczną datą. Strona JSON-LD podaje też `"dateModified":"Sep 24, 2026"` — zgodne z „bieżący, aktualizowany codziennie", nie archiwum.

**Decyzja właściciela (2026-09-26): IVV ODRZUCONY jako kandydat na niezależną walidację historyczną w obecnej formie.** Zatwierdzony wynik negatywny — **żadnego dalszego reverse-engineeringu ani poszukiwania nieoficjalnych sposobów dostępu do historycznych holdingów iShares** (np. Wayback Machine, inne nieudokumentowane endpointy). Potwierdzony `latest-holdings.csv` pozostaje wyłącznie jako potencjalny tani sanity-check „na dziś" (razem z Wikipedią), nie jako źródło historyczne — do rozważenia dopiero jako osobna, mniejsza decyzja, nie teraz.

**OPEN BLOCKER 2 pozostaje otwarty. Właścicielka kontaktuje się z supportem FMP w sprawie:** (a) dostępu do `historical-sp500-constituent`, (b) zakresu co najmniej 2012+, (c) możliwości wykupienia planu Premium na jeden okres rozliczeniowy z późniejszym downgrade'em do Starter. **Zatrzymuję się do czasu otrzymania odpowiedzi FMP** — żadnych dalszych kroków w Fazie 5.2 (research, kod, decyzja o `universe_membership`) bez tej odpowiedzi.

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
Metoda wybrana: własna warstwa PIT na SEC EDGAR XBRL company-facts (pole `filed`), niezależna od tego, którego komercyjnego dostawcę wybrano do bieżących danych — bez dodatkowego kosztu licencyjnego. **Stan v1.20: prototyp empirycznie potwierdzony na realnym koncie (AAPL/MSFT/KO) — po naprawie tie-breakingu w `value_as_of` (v1.19) `end` faktów jest w rozsądnej odległości od `filed`, a MSFT dał dokładne potwierdzenie krzyżowe z FMP (identyczne wartości net_income/revenue z dwóch niezależnych źródeł). Faza 5.1 formalnie ukończona.** Pozostaje do wykonania w kolejnych fazach: (a) rozróżnianie duration kontekstu XBRL (kwartalny vs YTD skumulowany), potrzebne dopiero przy budowie właściwego silnika backtestu (Faza 5.3), nie blokuje dalszych kroków; (b) potwierdzenie jakości/kompletności danych `filed` dla okresu 2009–2012 (obszar niepewny, niezweryfikowany w tym przeglądzie, do sprawdzenia przy właściwym backteście).

**OPEN BLOCKER 2 — Historyczny skład S&P 500 / survivorship bias. Stan v1.36: EMPIRYCZNIE ZWALIDOWANA (2 uruchomienia GitHub Actions, 2026-09-30), projekt `universe_membership` zatwierdzony i zaimplementowany. Pozostaje: jeden realny build przez GitHub Actions (`cli.py build-universe-membership`) na realnych danych, zanim blocker formalnie się zamknie.** Patrz „Wyniki empirycznej walidacji (v1.35)" i „Finalny projekt `universe_membership` (v1.35, zatwierdzony) — implementacja (v1.36)".

**Krok 1 (FMP) zakończony (v1.26–v1.32):** prawdziwa nazwa endpointu — `historical-sp500-constituent` (bez myślnika, wcześniejsze `stable/historical-sp-500` z v1.4 było błędne). Po aktywacji planu Premium przez właścicielkę: endpoint DZIAŁA, 1528 zdarzeń, zakres 1957-03-03 do 2026-09-21 (pokrywa 2012+ z dużym zapasem).

**Krok 2 (fja05680/sp500) zakończony (v1.22–v1.24):** parser + rozwiązanie ticker→CIK przez SEC — 619/815 tickerów rozwiązanych, **100% dzisiejszych 503 aktywnych spółek** rozwiązuje się bezbłędnie.

**Krok 3 (walidacja krzyżowa) zakończony (v1.28–v1.33):** próba z IVV ODRZUCONA (mechanizm `asOfDate` niedziałający, v1.28–v1.30). **Walidacja krzyżowa FMP vs fja05680 wykonana na pełnych danych (v1.33): zgodność 92,9%→99,6%, rosnąca ku teraźniejszości, rozbieżności skoncentrowane w wyjaśnialnych przypadkach (przesunięcia dat 1–3 dni, format tickera, zmiany tickera bez opuszczenia indeksu — nie losowy szum).** Rekomendacja: fja05680 jako podstawowe źródło (snapshot, architektonicznie zgodny z docelową tabelą), FMP jako niezależny walidator, CIK jako obowiązkowy klucz identyfikacji — patrz pełne wyniki w „Krok 3 Fazy 5.2 (v1.33)".

**Domknięcie 5 ryzyk (v1.34) + finalny projekt/implementacja (v1.35/v1.36):** rozwiązanie ticker→CIK dla FMP (z wykrywaniem recyklingu tickerów), reguła kanoniczne(fja05680)/walidator(FMP) w pełni audytowalna, wersjonowana reguła tolerancji dat, empiryczne porównanie pól `date`/`dateAdded` — wszystko EMPIRYCZNIE ZWALIDOWANE na realnych danych (2 uruchomienia GitHub Actions, 2026-09-30; po drodze naprawione 2 błędy w samym skrypcie diagnostycznym, opisane w „Wyniki empirycznej walidacji (v1.35)"). Finalny projekt `universe_membership` (z `validation_rule_version`) zatwierdzony i zaimplementowany (`universe_membership_build.py`, tabele w `db.py`, `cli.py build-universe-membership`, 78 nowych testów). **Brakuje jeszcze:** jednego realnego builda przez GitHub Actions na danych 2012+ (workflow do przygotowania) — dopiero po nim formalne domknięcie Fazy 5.2.

---

## Faza 5.3 — rozwiązanie ticker→CIK dla rename (LIMITED_BUT_HONEST), v1.37

**Odkrycie (2026-09-30, podczas budowy backtest harness):** `resolve_tickers_to_cik` rozwiązuje tickery WYŁĄCZNIE względem dzisiejszej mapy SEC (`company_tickers.json`). Spółka, która zmieniła ticker w oknie 2012+ bez opuszczenia indeksu (np. Anthem→Elevance Health: ANTM→ELV 2022-06-28; Facebook→Meta: FB→META 2022-06-09), ma swój STARY ticker trwale `CIK_UNRESOLVED` — `universe_membership` dla takiej spółki zaczynał się dopiero od daty zmiany tickera, nie od ~2012, mimo że spółka była w indeksie od początku okna. Potwierdzone empirycznie przez dedykowaną diagnostykę (`universe_membership_rename_diagnosis.py`, realny build): dla obu przypadków `earliest_start_date` w zbudowanej bazie = data zmiany tickera, nie 2012. Pole `reason` w logu zdarzeń FMP `historical-sp500-constituent` NIE zawiera użytecznego mapowania stary→nowy ticker (sprawdzone wprost — tylko fałszywe trafienia ze starszych, niezwiązanych zdarzeń).

**Proof Run 1 — zero-gap adjacency (`ticker_adjacency_proof_run.py`, realny, 2026-09-30):** dla wszystkich 196 ówczesnych `CIK_UNRESOLVED` tickerów zbadano, czy przedział tickera kończy/zaczyna się dokładnie tam, gdzie przedział innego, już rozwiązanego tickera (`analyze_ticker_adjacency`, `universe_ticker_adjacency.py`). Wynik: 43 bez żadnego kandydata (prawdopodobnie realne wyjścia z indeksu), 107 strukturalnie jednoznacznych (dokładnie jeden kandydat CIK), 46 niejednoznacznych (wiele kandydatów — realne dni wielokrotnego rebalansu indeksu, np. 2017-06-19). **Kluczowe zastrzeżenie właścicielki, empirycznie potwierdzone:** sama strukturalna jednoznaczność NIE jest dowodem tożsamości spółki — może to być TICKER RENAME SAME COMPANY albo INDEX REPLACEMENT DIFFERENT COMPANY (przypadkowa podmiana 1-do-1 tego samego dnia). Przykłady z realnej tabeli 107 "jednoznacznych" kandydatów, biznesowo ewidentnie niepowiązane: `EA→FERG`, `HOLX→CASY`. Próba weryfikacji przez SEC `formerNames` (nowe pole w `SecEdgarClient`, odczytywane dotąd ale odrzucane przez `get_filings`) ze stałą tolerancją 3 dni dała 0/107 korroboracji — **łącznie ze znanym prawdziwym przypadkiem ANTM/ELV** (różnica była tylko 4 dni, o 1 dzień za ciasna tolerancja). Diagnostyka surowych danych (Krok 5) ujawniła przyczynę: odstęp między prawną zmianą nazwy w SEC a faktyczną zmianą tickera w indeksie wynosi od ~4 dni (ANTM) do ~225 dni (FB/META) w dwóch znanych przypadkach — **żadna stała tolerancja dat nie rozwiązuje tego poprawnie** (wystarczająco szeroka, by złapać FB, złapałaby też przypadkowe, niezwiązane zmiany nazw).

**Decyzja właścicielki (2026-09-30): podejście LIMITED_BUT_HONEST.** NIE implementujemy ogólnej automatycznej reguły `INFERRED_VIA_ADJACENT_TICKER`. Zamiast tego:
1. **Kuratorowana allowlista** (`universe_ticker_rename_allowlist.py`, `CURATED_ALLOWLIST_SEED`) — 2 przypadki ręcznie potwierdzone wielokrotnie, niezależnie, w tej sesji: ANTM→ELV (CIK 1156039), FB→META (CIK 1326801).
2. **Reguła wielosygnałowa** (`evaluate_rename_signals`) do PRÓBY rozszerzenia allowlisty — nigdy pojedynczy sygnał: wymaga >=2 z 3 (FMP `get_company_profile`, FMP nazwa z logu zdarzeń vs SEC/FMP nazwa sąsiada przez `names_plausibly_match`, SEC `formerNames` w szerokiej tolerancji 400 dni — tylko do raportowania odległości, nie jako twardy próg). Jawna sprzeczność w `get_company_profile` (FMP dziś kojarzy stary ticker z INNYM CIK — recykling) dyskwalifikuje kandydata natychmiast, niezależnie od pozostałych sygnałów.
3. Ocena **per kandydat, nie per ticker** (`ticker_rename_multi_signal_verification.py`) — naprawia wadę architektoniczną z Proof Run 1 (agregacja per-ticker myliła jednoznaczną granicę wyjścia z niezwiązaną niejednoznaczną granicą wejścia, np. dla FB).

**Proof Run 2 — wielosygnałowa weryfikacja (realny, 2026-10-01).** Z 151 tickerów z >=1 kandydatem (poza już zaseedowanymi ANTM/FB): **+5 nowo odzyskanych** (BK→BNY, DISCK→WBD, FI→FISV [BŁĘDNY KIERUNEK, patrz niżej], MMC→MRSH, SATS→ECHO, wszystkie przez 2/3 sygnałów: profil FMP + nazwa), 0 nadal niejednoznacznych mimo sygnałów, **74 DISCONFIRMED** (profil FMP dziś jawnie wskazuje na INNY CIK niż jakikolwiek strukturalny kandydat — w tym poprawnie: `EA`, `BBBY`, `TWTR`, potwierdzając wcześniejsze podejrzenie, że to realne przejęcia/upadłości/delisting, nie rename), **72 z niewystarczającymi dowodami** (pozostają `CIK_UNRESOLVED`).

**Błąd kierunku znaleziony i zgłoszony przez właścicielkę (2026-10-01):** niezależna weryfikacja w źródłach pierwotnych wykazała, że prawdziwy kierunek to `FISV → FI` (Fiserv notowany jako FISV na Nasdaq, przeniesiony na NYSE pod `FI` 2023-06-07), nie `FI → FISV` jak zwrócił skrypt. **Przyczyna (zdiagnozowana):** kod zawsze etykietował `old_ticker` = ticker nierozwiązany wg DZISIEJSZEJ mapy SEC — myląc to z "chronologicznie starszy w fja05680". To dwie niezależne rzeczy: dla tego kandydata DZISIEJSZA mapa SEC rozwiązuje `FISV` (CHRONOLOGICZNIE STARSZY ticker), nie `FI` (nowszy) — strukturalny `direction` (`RESOLVED_ENDS_UNRESOLVED_STARTS`) był poprawny od początku, tylko kod go ignorował przy budowie rekordu. **Naprawione:** nowa czysta funkcja `chronological_order()` (`universe_ticker_adjacency.py`, 2 nowe testy) wyprowadza old_ticker/new_ticker WYŁĄCZNIE ze strukturalnego kierunku, nigdy ze statusu resolved/unresolved; skrypt teraz jawnie wypisuje `direction` dla każdego kandydata w każdej tabeli. **Ponowny realny run (2026-10-01) z poprawką:** poprawnie pokazuje `FISV → FI` — zgodne z weryfikacją właścicielki. Sprawdzenie pozostałych 4: tylko FISV/FI miał kierunek `RESOLVED_ENDS_UNRESOLVED_STARTS` (ten podatny na błąd) — BK→BNY, DISCK→WBD, MMC→MRSH, SATS→ECHO miały zawsze kierunek `UNRESOLVED_ENDS_RESOLVED_STARTS` (nigdy nie odwracany), więc nie wymagały korekty. Liczby zbiorcze (5/0/74/72, coverage) niezmienione przez fix — błąd dotyczył wyłącznie ETYKIETY w obrębie już potwierdzonych rekordów, nie samej klasyfikacji.

Niezależna kontrola (wiedza spoza narzędzia, ograniczona do zdarzeń sprzed stycznia 2026): `DISCK→WBD` (Discovery→Warner Bros. Discovery, fuzja z WarnerMedia, kwiecień 2022) zgadza się z publicznie znaną historią. Właścicielka niezależnie potwierdziła w źródłach SEC: `SATS→ECHO`, `MMC→MRSH`. `BK→BNY` nie ma jeszcze jej osobistej niezależnej kontroli (tylko sygnały automatyczne + poprawiony kierunek strukturalny).

**Finalny coverage CIK (okno 2012+, 815 tickerów):** 619 (baseline SEC-only) + 2 (allowlista) + 5 (wielosygnałowa weryfikacja) = **626/815 = 76.81%**. Pozostaje **189 jawnie `CIK_UNRESOLVED`** (23.19%) — w większości tickery z `DISCONFIRMED` (realne przejęcia/delisting, potwierdzone niezależnym sygnałem FMP) lub bez żadnego/wystarczającego sygnału (`NO_CANDIDATE`/`INSUFFICIENT_EVIDENCE`), spójne z hipotezą, że to w większości realne historyczne wyjścia z indeksu, nie przeoczone rename.

**v1.39/v1.40 — produkcyjne wpięcie i zamknięcie Fazy 5.3 (2026-10-01).** Właścicielka niezależnie zweryfikowała w źródłach SEC `BK→BNY`, `DISCK→WBD`, `FISV→FI` (dodatkowo do wcześniej potwierdzonych `SATS→ECHO`, `MMC→MRSH`) i zatwierdziła finalną allowlistę WSZYSTKICH 7 przypadków do produkcyjnego wpięcia, z wymogiem zachowania pełnego provenance i jawnego `cik_resolution_method` per rekord.

Implementacja: `apply_curated_allowlist()` (krzyżowo sprawdza KAŻDY rekord z aktualnym stanem SEC — nigdy ślepe zaufanie, nigdy nie nadpisuje już rozwiązanego tickera); `MembershipInterval.cik_resolution_note` (nowe pole, pełna ścieżka dowodowa) i nowa wartość `cik_resolution_method='CURATED_ALLOWLIST'` (priorytet nad FORMAT_VARIANT/DIRECT); `db.py` CHECK rozszerzony, nowa nullable kolumna `cik_resolution_note`. Allowlista stosowana WYŁĄCZNIE w Kroku 5 (budowa przedziałów CIK-poziomu) — celowo NIE w Kroku 3/4 (FMP reconciliation), żeby nie zniekształcić empirycznie wybieranej krzywej tolerancji dla całego builda.

**Dwa dodatkowe błędy znalezione i naprawione podczas pierwszych realnych buildów produkcyjnych** (ten sam rodzaj pomyłki co błąd kierunku — mylenie "nierozwiązany dziś wg SEC" z rolą w parze): (1) `apply_curated_allowlist` zakładała, że `old_ticker` jest zawsze nierozwiązany, a `new_ticker` zawsze kotwicą — dla FISV→FI jest odwrotnie, rekord był całkowicie pomijany (6/7 zamiast 7/7 w pierwszym realnym buildzie). (2) Po naprawie (1), scalanie przedziałów nadal fałszywie etykietowało wynik jako `DIRECT` zamiast `CURATED_ALLOWLIST` dla tej pary, bo brało provenance zawsze z pierwszego (wcześniejszego) przedziału, a dla FISV/FI to kotwica (FISV) jest pierwsza. Naprawione: `CURATED_ALLOWLIST` wygrywa niezależnie od pozycji w scaleniu; reguła "z pierwszego" dla zwykłego DIRECT/FORMAT_VARIANT pozostaje niezmieniona (kontrola nieregresji, osobny test). Oba błędy złapane przez offline dry-run PRZED realnym buildem, dla drugiego dopiero po dodaniu syntetycznego odpowiednika FISV/FI do testu.

**Finalny realny build (3. próba, GitHub Actions, 2026-10-01):** `Allowlista: +7 tickerów odzyskanych (['ANTM', 'BK', 'DISCK', 'FB', 'FI', 'MMC', 'SATS'])`. 634 przedziałów członkostwa (642 przed scaleniem, 8 par scalonych — zdiagnozowane i w pełni wyjaśnione: 6 CIK-ów z 1 scaleniem + CIK 798354 (Fiserv) z 2, bo ma 3 segmenty: FISV(2012–2023)→FI(2023–2025)→FISV(2025–nadal) — drugie przejście to zwykły DIRECT+DIRECT rename niezależny od allowlisty, poprawnie scalony w jeden ciągły przedział z `cik_resolution_method='CURATED_ALLOWLIST'`). **Zero scaleń poza 7 CIK-ami allowlisty** — potwierdzone dedykowaną diagnostyką w dwóch kolejnych runach. Konflikty FMP (79: 45 ONLY_CANONICAL/34 ONLY_VALIDATOR) i wybrana tolerancja (6 dni, pole `dateAdded`) **identyczne** we wszystkich 3 realnych buildach — potwierdza, że allowlista nie zniekształciła walidacji FMP. **Finalny coverage CIK: 626/815 = 76.81%**, identyczny z Proof Run. 189 tickerów pozostaje jawnie `CIK_UNRESOLVED` (`LIMITED_BUT_HONEST`) — zgodnie z decyzją właścicielki, bez dalszego automatycznego rozwiązywania.

**FAZA 5.3 ZAMKNIĘTA.** Pełny test suite (361 passed/1 skipped) + 3 realne buildy produkcyjne bez nierozwiązanych problemów wpływających na poprawność backtestu. Kontynuacja zgodnie z roadmapem: deterministyczny walk-forward harness (2012+, miesięczna częstotliwość skanowania, LLM walidowany osobno na kuratorowanym zbiorze, nie do kalibracji tysięcy obserwacji historycznych).

Testy: 45 nowych w tej fazie (4 `test_sec_edgar.py` dla `get_former_names`, 17 `test_universe_ticker_adjacency.py` w tym `chronological_order`, 15 `test_universe_ticker_rename_allowlist.py` w tym `apply_curated_allowlist`, 4 `test_universe_membership_build.py` dla `CURATED_ALLOWLIST`, 1 `test_db.py`, reszta konfiguracja `BacktestConfig`), wszystkie hand-verified, 361 passed / 1 skipped łącznie w całym projekcie.

Do czasu wykonania obu prototypów, wszelkie wyniki backtestingu muszą nosić w raporcie jawną adnotację `LIMITED_BUT_HONEST` z opisem, którego okresu/zakresu dotyczy ograniczenie.

---

## Deterministyczny walk-forward backtest harness (sekcja 13), v1.41

Zaprojektowany i zatwierdzony przez właścicielkę 2026-10-01, z jej doprecyzowaniami: **bez pełnego LLM** (`full_score` zawsze `None`, `business_quality`/`fear` zawsze `None`, brak gate'u `min_business_quality` — nie ma historycznego LLM output dla tysięcy obserwacji 2012+), jawny **`deterministic_score_pct`** (punkty zdobyte / maksimum DOSTĘPNYCH komponentów * 100 — techniczna normalizacja istniejącego scoringu, nie nowa metodologia; komponent niepoliczalny np. `valuation` dla sektora bez zaimplementowanej metody jest wyłączony Z OBU stron ułamka, nigdy liczony jako 0), **forward returns wyłącznie jako outcome labels** (liczone w osobnej funkcji `attach_forward_returns`, wywoływanej PO sfinalizowaniu kandydata — strukturalnie niemożliwe, by wpłynęły na decyzję).

**Implementacja** (3 nowe moduły, 56 nowych testów): `backtest_harness.py` (czysta logika: `generate_rebalance_dates`, `compute_forward_returns`, `compute_deterministic_score`, nowa `evaluate_deterministic_hard_gates` — NIE modyfikacja `scoring.evaluate_hard_gates`, pomija `min_business_quality`, `evaluate_candidate_at_date` — pełny funnel decline scanner → prefilter → score → hard gates → candidate); `pit_fundamentals.py` (budowa `FundamentalsPeriod` z realnych danych SEC XBRL, celowo ograniczona do okresów rocznych — unika niejednoznaczności duration kwartalnych faktów XBRL); `providers/walk_forward_proof_run.py` (mały Proof Run na 3 stabilnych tożsamościowo spółkach — AAPL/MSFT/KO — × 6 dat na znanym okresie zmienności rynku, z programową asercją braku naruszeń point-in-time).

**Błąd point-in-time znaleziony i naprawiony w trakcie Proof Run (2026-10-01, realny run #1):** pierwsza wersja `pit_fundamentals.py` filtrowała okresy roczne po `fp == 'FY'` (pole SEC XBRL) — dało to periods=42-54 zamiast oczekiwanych ~10. **Surowa diagnostyka (Krok 2a, dodana po tym znalezisku) potwierdziła przyczynę**: realny wpis AAPL miał `fp='FY'`, ale `start='2014-12-28'`..`end='2015-03-28'` (90 dni — kwartał), a drugi, późniejszy wpis dla TEJ SAMEJ daty `end` miał pole `frame='CY2015Q1'`, jawnie potwierdzające kwartał mimo `fp='FY'`. **Pole `fp` SEC XBRL nie jest wiarygodnym wskaźnikiem rzeczywistego czasu trwania faktu** — gdyby to przepuszczono dalej, kwartalny net_income trafiłby do porównań rok-do-roku obok prawdziwych rocznych wartości, fałszywie zniekształcając `revenue_yoy_growth_pct`/`no_persistent_losses`. **Naprawione:** `PitFact` zyskało pole `start` (SEC je zwraca, dotąd odrzucane), filtr liczy teraz rzeczywisty czas trwania (`end-start`, pasmo 350-380 dni, z zapasem na lata fiskalne 52/53-tygodniowe jak Apple — `2019-09-28` jako koniec FY2019 AAPL zgadza się z publicznie znaną konwencją). Nowy test regresyjny odtwarza dokładnie znaleziony wpis.

**Realny run #2 (po naprawie, 2026-10-01):** periods=12-15 na spółkę (zgodne z ~8-17 latami danych XBRL od początku obowiązkowego taggingu ~2009-2011). Niezależna kontrola: `positive_revenue_growth` dla AAPL@2020-04-01 zmieniło się z `True` (błędny run, zanieczyszczony danymi kwartalnymi) na `False` (poprawiony run) — oczekiwany efekt naprawy. Funnel: 13 `NO_DECLINE_SIGNAL`, 0 `EXCLUDED_BY_PREFILTER`, 0 `HARD_GATE_FAILED`, 5 `CANDIDATE` (naturalnie z krachu COVID 2020 i bessy 2022, bez fabrykowania danych). Zero naruszeń point-in-time (asercja programowa, nie tylko log) na 18 parach (ticker, data). Forward returns 1m/3m/6m/12m policzone poprawnie dla wszystkich 5 kandydatów. Pełny decision snapshot (decline_flags, PIT fundamentals reference, breakdown, scores, hard gates, config/scoring version, run_id) zapisany dla każdego.

**PROOF RUN ZAKOŃCZONY SUKCESEM** — bez nowego problemu dotyczącego point-in-time (poza znalezionym i naprawionym), look-ahead, survivorship bias ani identity/data coverage. Celowo wąski zakres danych fundamentalnych (tylko net_income/revenue z rocznych SEC XBRL — reszta pól `None`) oznacza, że scores w tym Proof Run są systematycznie niższe niż będą po pełnym backfillu — to ograniczenie zakresu tego etapu, nie ocena jakości spółek.

**Oczekuje na decyzję właścicielki:** zakres i uruchomienie pełnego backfillu (ceny + fundamentals dla całego uniwersum `universe_membership`, 2012+) — jedyny pozostały krok przed pełnym walk-forward runem.

Testy: 56 nowych (25 `test_backtest_harness.py`, 7+2 `test_pit_fundamentals.py`/`test_point_in_time.py` w tym regresja `fp` vs rzeczywisty czas trwania), wszystkie hand-verified, 397 passed / 1 skipped łącznie w całym projekcie.

---

## Faza 5.3b — dependency audit, rozszerzony XBRL mapping, sec_company_facts_cache, backfill 626 CIK, v1.42

**Dependency audit (2026-10-01/02):** inspekcja `compute_metrics`/`financial_quality_score`/`compute_valuation`/`evaluate_dividend_shareholder_return` ustaliła dokładny zestaw 12 pól `FundamentalsPeriod` wymaganych przez istniejący deterministic pipeline. Przed audytem XBRL mapping (`point_in_time.CANDIDATE_TAGS`) pokrywał tylko 2 z 12 (`net_income`, `revenue`).

**Rozszerzenie mappingu na 11/12 pól** — rozróżnienie konceptów *duration* (walidacja rzeczywistego czasu trwania 350-380 dni, ten sam mechanizm co naprawiony błąd `fp=='FY'` z Proof Run #1) od *instant* (bilansowe, bez `start`, bez walidacji duration — pomylenie tych dwóch byłoby nowym błędem PIT). **EBITDA jako kompozyt PIT** dwóch niezależnych faktów (`OperatingIncomeLoss` + D&A), zgodnie z 5 zasadami zatwierdzonymi przez właścicielkę 2026-10-02: niezależny PIT lookup obu składników, ta sama walidacja duration, dopasowanie WYŁĄCZNIE po tym samym `period_end` (nigdy różnych lat fiskalnych), kandydackie tagi D&A próbowane po kolei (nigdy sumowane — ryzyko double counting), którykolwiek składnik `None` → `ebitda=None`, zero fallbacku/substytutu. `total_debt` pozostaje jawnie `None` — SEC XBRL nie ma jednego uniwersalnego tagu (current/noncurrent/short-term borrowings dzielone różnie między spółkami), decyzja o kompozycie **jawnie odłożona**, zgłoszona, nie rozstrzygana przy okazji backfillu.

**Realny Proof Run #1 po rozszerzeniu (2026-10-02) ujawnił 2 błędy:**
1. **`diluted_shares_outstanding` systematycznie `ŻADEN_KANDYDAT` dla WSZYSTKICH trzech spółek** (AAPL/MSFT/KO) — nie przypadek braku danych, ale błąd mechanizmu: `find_first_matching_tag` zakładało globalnie `units["USD"]`, a liczba akcji w SEC XBRL to fakt niepieniężny, leżący pod `units["shares"]`. **Naprawione:** nowa mapa `CONCEPT_UNITS` (domyślnie `"USD"`, override `"shares"` dla `diluted_shares_outstanding`), rozwiązywana w `find_first_matching_tag` — zero konwersji wartości, wyłącznie odczyt z właściwej jednostki. Realny run #2 potwierdził poprawne, zgodne z publicznymi raportami wartości (AAPL=16 864 919 000, MSFT=7 540 000 000, KO=4 340 000 000) z zachowanym strict PIT.
2. **MSFT nie ma jednego tagu D&A** — surowa diagnostyka (Krok 2c, dodana po tym znalezisku, dump wszystkich tagów us-gaap semantycznie zawierających Depreciation/Depletion/Amortization) ujawniła rozłączne `Depreciation` (~12,6 mld FY2022) i `AmortizationOfIntangibleAssets` (~2,0 mld), plus kilka tagów schedule/future disclosure (`FutureAmortizationExpenseYear*`, `FiniteLivedIntangibleAssetsAmortizationExpenseYear*`) — NIGDY nie reprezentujących rzeczywistego wydatku okresu, tylko prognozę na przyszłe lata. Zgodnie z zasadą "brak odpowiedniego standardowego faktu → `None`, zero estymacji": `ebitda` pozostaje `None` dla MSFT, nic nie dodano do `CANDIDATE_TAGS`. Odłożone (razem z `total_debt`) jako temat do osobnej decyzji o kompozycie, nieblokujący backfillu.

**`sec_company_facts_cache` — nowa tabela (db.py), WYŁĄCZNIE source data.** Przed backfillem sprawdzono, czy istniejąca `fundamentals_raw` może służyć jako cache — **nie może**: `insert_fundamentals_rows` robi UPSERT po `(cik, fiscal_period, statement_type, line_item, source)` z `DO UPDATE SET value=excluded.value`, nadpisując poprzednią wartość i `filed_date` przy każdym fetchu; `get_fundamentals_periods` zwraca jedną wartość per okres — "to, co wiadomo dziś", nigdy "to, co było wiadomo na dzień D". Użycie jej do cache'owania SEC XBRL zniszczyłoby PIT globalnie (dokładnie look-ahead bias, który Faza 5.1 miała eliminować) — ta tabela słusznie służy innemu celowi (żywy skan FMP, `source="fmp"`, Faza 0-4), zostaje nietknięta. Nowa `sec_company_facts_cache(cik, raw_json, source, payload_sha256, fetched_at)` przechowuje WYŁĄCZNIE surowy `company_facts` JSON as-is — zero wyliczonych historycznych fundamentals/snapshotów `as_of`. `fetched_at` opisuje wyłącznie moment pobrania kopii, nigdy dostępność historycznego faktu (ta wynika z `filed`, przez niezmienioną logikę `point_in_time.py`/`pit_fundamentals.py`). Test integracyjny potwierdza: `build_annual_fundamentals_periods_as_of()` na JSON bezpośrednio z SEC (A) i na tym samym JSON po zapisie+odczycie z cache (B) daje identyczny wynik, przed i po restatement — cache nie wprowadza żadnego look-ahead.

**Retry/backoff (`providers/retry.py`).** Decyzja właścicielki 2026-10-03 (plan FMP Premium: 750 calls/min, 50 GB/30 dni — ale jawnie NIE wykorzystywać agresywnie): 429/5xx i błędy sieciowe ponawiane z wykładniczym backoffem (max 5 prób domyślnie, `Retry-After` honorowany, gdy obecny), 402/404 i inne stałe błędy wracają od razu (ponawianie ich tylko traciłoby limit). Wbudowane w `SecEdgarClient`/`FMPClient._get` — zero zmiany zachowania dla istniejących sukcesów/błędów stałych.

**Backfill 626 CIK / 2012+ — projekt zatwierdzony 2026-10-03, zaimplementowany.** Nowy moduł `backfill.py`: `derive_price_fetch_ticker_universe` (odtwarza `(ticker_intervals, resolved)` identycznie jak Krok 1-2 + allowlista `cmd_build_universe_membership`, restricted do CIK już w zbudowanym `universe_membership` — zero nowej logiki identity, ta tabela tylko czytana); `classify_price_coverage`/`classify_fundamentals_coverage` (jawne COMPLETE/PARTIAL/FAILED/NOT_ATTEMPTED — Decyzja właścicielki: obecność wierszy w `price_daily`/cache NIE jest dowodem kompletności; COMPLETE dla cen wymaga ZARAZEM pokrycia brzegowego i >=80% oczekiwanych dni roboczych); `should_fetch` (resumability: tylko COMPLETE pomijane bez `--refresh`); `backfill_prices_for_cik`/`backfill_fundamentals_for_cik` (orkiestracja — ceny przez już zwalidowany `price_history_plan.py`, merge po `(cik,date)`, jawne konflikty nigdy cichy wybór; fundamentals przez `sec_company_facts_cache`). Nowa tabela `backfill_status(cik, task_type, status, detail, run_id)` — najnowszy status per (CIK, task), nadpisywany, nie historia. CLI: `backfill-walk-forward-data [--target prices|fundamentals|both] [--cutoff] [--refresh] [--sample CIK1,CIK2,...]`. Workflow `phase5-3b-backfill-walk-forward-data.yml`: najpierw `build-universe-membership` (idempotentny, przygotowuje 626 zresolved CIK), potem backfill na tym samym pliku DB; wejście `resume_from_run_id` pozwala pobrać artefakt przerwanego uruchomienia i wznowić bez ponownego pobierania CIK już COMPLETE. 55 nowych testów (`test_retry.py`, `test_backfill.py`, rozszerzenia `test_db.py`/`test_sec_edgar.py`/`test_fmp_client.py`, `test_sec_company_facts_cache_pit_integration.py`) + offline dry-run (syntetyczne dane, zero sieci) potwierdzający pełny cykl CLI: pierwszy backfill → COMPLETE, wznowienie bez `--refresh` → zero wywołań sieciowych, `--refresh` → ponowne pobranie, `--sample` → ograniczenie zakresu. 474 passed / 1 skipped po dependency audit, dalsze testy backfillu podnoszą tę liczbę.

**Świadomie odłożone, nietykane przy tej pracy** (Decyzja właścicielki 2026-10-03): pozostałych 189 CIK_UNRESOLVED, metodologia D&A dla spółek typu MSFT, metodologia `total_debt` — backfill gromadzi source data, nie rozstrzyga tych pytań.

**Kolejność wykonania (zatwierdzona, nie wymaga ponownej zgody między krokami B→C, jeśli brak nowego problemu systemowego):** (A) offline dry-run — ZAKOŃCZONY SUKCESEM; (B) mały realny Proof Run na 10 CIK (mix DIRECT + wszystkie 7 CURATED_ALLOWLIST) — ZAKOŃCZONY SUKCESEM 2026-10-04; (C) pełny backfill 615/626 CIK — **ZAKOŃCZONY SUKCESEM 2026-10-04, status LIMITED_BUT_HONEST** (patrz niżej).

---

## Faza 5.3b — backfill 615 CIK, wynik finalny, LIMITED_BUT_HONEST (2026-10-04)

**Wykonanie:** build-universe-membership + backfill (prices + fundamentals) w jednym workflow run, ~5min50s łącznie, bez potrzeby wznawiania (`resume_from_run_id`).

**Universe:** 615 unikalnych CIK (626 rozwiązanych tickerów minus ~11 zwiniętych par rename/format-variant do tego samego CIK — zgodne matematycznie, nie regresja), 189 CIK_UNRESOLVED (nietknięte, zgodnie z decyzją).

**Fundamentals (SEC company_facts → `sec_company_facts_cache`): 614 COMPLETE, 1 PARTIAL (99,8%).** Jedyny PARTIAL: CIK=1650107 — poprawny JSON z SEC, ale zero faktów us-gaap (rzadki, realny przypadek, jawnie oznaczony, nic nie fabrykowane).

**Ceny (`price_daily`): 587 COMPLETE, 13 PARTIAL, 15 FAILED (95,4% pełnych).** Dwa jasne wzorce w FAILED/PARTIAL, oba będące dowodem poprawnego działania mechanizmu (nigdy cichego zgadywania), nie defektem kodu:
1. **BRK.B (CIK 1067983) i BF.B (CIK 14693) — FAILED.** FMP zwraca 402 "Special Endpoint" nawet na planie Premium — ograniczenie zewnętrznego dostawcy specyficzne dla tickerów klasy B z kropką w symbolu, nie błąd zapytania. Pełna treść błędu zapisana, nic nie ukryte.
2. **13 CIK PARTIAL — konflikty merge przy zmianie tickera** (dokładnie mechanizm z małej próbki: FB/META 320 konfliktów, DISCK/WBD 1933 konfliktów) **plus luki brzegowe/za mało wierszy bez konfliktów** (np. FMP po prostu nie ma wcześniejszej historii dla danego tickera) — `merge_ticker_price_rows` poprawnie odmawia zgadywania, zamiast tego raportuje PARTIAL z pełnym provenance. Reszta FAILED (13 CIK) to "zero wierszy po próbie pobrania" — głównie spółki o wysokich numerach CIK (stosunkowo niedawne IPO/rejestracje), brak historii u FMP dla tego okresu.

**Decyzja właścicielki (2026-10-04):** backfill uznany za zakończony sukcesem w trybie LIMITED_BUT_HONEST. 15 FAILED + 13 PARTIAL + BRK.B/BF.B + pozostałe historyczne braki **świadomie NIE naprawiane teraz** — do rewizji tylko, jeśli podczas walk-forward okażą się materialnie wpływać na wynik. **Ważne doprecyzowanie właścicielki, wbudowane w architekturę coverage reportingu niżej:** brak danych cenowych nie powoduje fabrykowania kandydatów ani look-ahead bias, ale MOŻE powodować selection/coverage bias (missingness nie musi być losowy) — stąd pełny walk-forward mierzy i raportuje coverage jawnie per decision_date, nie tylko liczbę kandydatów.

---

## Faza 5.3c — infrastruktura pełnego BASELINE walk-forward, v1.43

Zatwierdzona przez właścicielkę 2026-10-04, zero zmiany scoring weights/thresholds/decline thresholds/hard gates/valuation assumptions/`deterministic_score_pct` methodology — to jest BASELINE przed kalibracją, nie optymalizacja.

**Coverage reporting per decision_date — jawne rozróżnienie, nie tylko liczba kandydatów** (Decyzja właścicielki: missingness nie musi być losowy → selection/coverage bias). Nowe:
- `backtest_harness.classify_data_sufficiency(bars, periods) -> (bool, bool)` — czy w ogóle da się uruchomić decline scanner / odczytać PIT fundamentals dla (CIK, D), NIEZALEŻNIE od `evaluate_candidate_at_date` (ta konfliduje oba braki w jeden `NO_FUNDAMENTALS`, za mało granularne do coverage per przyczynę). Zero zmiany istniejącego funnela — czysta, dodatkowa klasyfikacja obok niego.
- `walk_forward_coverage.py` (nowy moduł): `CoverageSnapshot` (7 miar wymaganych przez właścicielkę: `pit_universe_count`, `sufficient_price_count`, `sufficient_fundamentals_count`, `scanned_count`, `coverage_pct`, `excluded_missing_price_count`, `excluded_missing_fundamentals_count`, plus rozbicie funnela) i `aggregate_coverage()` (overall coverage ważony obserwacjami, min/median/p10/p25/p75/p90/max w czasie, 10 najgorzej pokrytych dat — żeby było wiadomo, czy starsze lata są istotnie słabiej pokryte).
- Nowe tabele `backtest_coverage`/`backtest_candidates` (db.py) — jeden wiersz coverage per decision_date, jeden wiersz per (decision_date, CIK) który osiągnął `CANDIDATE`, z dołączonymi forward returns. `full_score` celowo nie jest kolumną — zawsze `None` w tym trybie.

**CLI `run-baseline-walk-forward`** (`cli.py`) — orkiestracja WYŁĄCZNIE już istniejących, przetestowanych funkcji z `backtest_harness.py`, zero sieci (czyta tylko z `--db`, wczytuje ceny/SEC cache per CIK RAZ, potem w pamięci truncates do każdej `decision_date` — 615 CIK × ~178 miesięcy to ~108K par (CIK,D), ale bez I/O per parę). `sector_profile` czytane z `companies` (obecnie zawsze `'GENERAL'` — patrz otwarta decyzja niżej). `ticker_as_of_date` w `BacktestCandidate` ustawiane na sam CIK (nie na realny symbol) — `universe_membership` nie przechowuje tickerów per datę (tylko CIK-poziomowe przedziały, patrz Faza 5.2), a odtwarzanie tego wymagałoby ponownego sieciowego fetchu fja05680/SEC tylko dla kosmetycznej etykiety; świadomie pominięte, bez wpływu na żadną decyzję/scoring.

Workflow `phase5-3c-baseline-walk-forward.yml`: pobiera artefakt z konkretnego, już zakończonego runu "Phase 5.3b Backfill" (`backfill_run_id`), kopiuje bazę (source data z backfillu zostaje nietknięta), uruchamia pełny walk-forward, uploaduje wynik jako osobny artefakt.

Offline dry-run (3 syntetyczne CIK — jeden z pełnymi danymi + realnym krachem cenowym, jeden z cenami ale bez fundamentals, jeden z fundamentals ale bez cen, zmieniające się PIT membership w czasie) potwierdza: PIT universe poprawnie się zmienia (nowy CIK wchodzi/wychodzi z poprawną datą), CIK bez fundamentals NIGDY nie trafia do `scanned`/kandydatów, CIK bez cen analogicznie, kandydat powstaje tylko dla spółki z pełnymi danymi i realnym spadkiem ceny, coverage/funnel/agregacja liczą się poprawnie. 22 nowe testy jednostkowe (`test_walk_forward_coverage.py` + rozszerzenia `test_backtest_harness.py`/`test_db.py`), 491 passed / 1 skipped razem w projekcie.

**Dwie otwarte decyzje przed realnym uruchomieniem na pełnym 615-CIK datasecie** (zgłoszone zgodnie z zasadą "zatrzymaj się przed interpretacją wyników"):

1. **`sector_profile` nigdy nie było klasyfikowane — wszystkie 615 CIK mają domyślne `'GENERAL'`.** `compute_valuation` routinguje WSZYSTKIE spółki (w tym realne banki jak BK/BNY, ubezpieczycieli jak Marsh McLennan) przez metodę `dcf_owner_earnings` zaprojektowaną dla zwykłych spółek — DCF na operacyjnym FCF nie ma sensu dla instytucji finansowych (ich "FCF" zdominowane jest przez zmiany depozytów/kredytów, nie operacyjną działalność). To NIE jest nowy błąd kodu — `config.valuation.method_by_sector_profile` od dawna poprawnie mapuje `BANK/INSURER/REIT -> null` (`NOT_YET_IMPLEMENTED`), ale ten gate nigdy wcześniej się nie uruchomił na żadnej realnej spółce finansowej (mała próbka AAPL/MSFT/KO, 3 CIK bez nikogo finansowego). Skutek przy BASELINE: `hard_gates.min_margin_of_safety_pct` jest obecnie `null` (nieaktywny) — więc bezsensowna wycena NIE blokuje ani nie przepuszcza kandydatów przez hard gate, tylko zniekształca wartość `valuation_score`/`margin_of_safety_base_pct` WYŚWIETLANĄ dla faktycznie finansowych spółek. Opcje: (a) uruchomić BASELINE jak jest, z jawnym zastrzeżeniem w raporcie, że `valuation_score` dla spółek finansowych jest niewiarygodny — zero nowego kodu; (b) szybka klasyfikacja sektorowa z już dostępnego pola SEC Submissions API `sic`/`sicDescription` (ten sam endpoint, co `get_former_names`, nie nowy provider) wg standardowych zakresów SIC (6020-6036/6060-6062/6080-6082 banki, 6300-6411 ubezpieczenia, 6500/6798 REIT) — poprawnie routingowałoby te spółki na `NOT_YET_IMPLEMENTED` zamiast fabrykowanej wyceny, mały, odrębny skrypt zapisujący `companies.sector_profile`, bez zmiany logiki walk-forward.
2. **Benchmark (punkt 7 raportu) wymaga decyzji metodologicznej** — patrz opcje w wiadomości do właścicielki.

## Faza 5.3c — obie otwarte decyzje domknięte: SIC sector_profile + dualny benchmark, v1.44

Decyzje właścicielki 2026-10-04: (1) sector_profile — opcja (b) powyżej, szybka klasyfikacja z SIC; (2) benchmark — dualny, PRIMARY `equal_weighted_pit_universe` (średni forward return WSZYSTKICH spółek z PIT universe z wystarczającymi cenami, nie tylko kandydatów — jawnie NIE nazywany "S&P 500 return", bo nie jest cap-weighted) + SECONDARY SPY price return (ta sama konwencja forward_return_pct bez dywidend co kandydaci). Oba raportowane osobno. Zero zmiany scoringu/wag/thresholds/hard gates/valuation w związku z benchmarkiem.

**SIC → sector_profile (`sector_classification.py`, nowy moduł, czysta funkcja):** `classify_sic_to_sector_profile(sic)` mapuje kod SIC na BANK (6020-6036/6060-6062/6080-6082) / INSURER (6300-6411) / REIT (6500/6798) / GENERAL (wszystko inne, brak kodu, format niepoprawny — nigdy nie zgadywane). Zakres wyłącznie BANK/INSURER/REIT, BIOTECH poza zakresem tej zmiany (odrębna, nie zaimplementowana ścieżka). `SecEdgarClient.get_sic_classification(cik)` — nowa metoda, ten sam Submissions API endpoint co `get_filings`/`get_former_names` (zero nowego providera), zwraca `{sic, sic_description}`, `None` jeśli SEC nie ma pola. Nowa CLI `classify-sector-profiles [--sample ...]`: czyta CIK z `universe_membership`, woła SEC per CIK, mapuje, zapisuje WYŁĄCZNIE kolumnę `sector_profile` przez nowe `db.update_company_sector_profile()` (celowo NIE `upsert_company` — to nadpisałoby `name`/`sector`/`industry` na NULL, bo `ON CONFLICT DO UPDATE` ustawia je na przekazane wartości).

**Dualny benchmark (`benchmark.py`, nowy moduł, czysta funkcja):** `compute_benchmark_snapshot()` — jedna migawka per decision_date, oba benchmarki w jednym obiekcie (wzorzec `CoverageSnapshot`). PRIMARY liczony z CIK-ów, które `classify_data_sufficiency` już oznaczył jako `has_price=True` dla tej daty (nie nowa, osobna definicja "wystarczających cen"), decision_price per CIK = ten sam "ostatni bar ≤ D" co dla kandydatów — benchmark i kandydaci używają identycznej konwencji ceny bazowej. SECONDARY (SPY) używa **tej samej** `forward_return_pct()` z `backtest_harness.py` — zero duplikacji konwencji zwrotu. Oba `None` tam, gdzie brak danych (nigdy nie ekstrapolowane). Nowa tabela `backtest_benchmark` (db.py) — jeden wiersz per (run_id, decision_date), 4 horyzonty × (return_pct + n dla PRIMARY, return_pct dla SECONDARY) w osobnych kolumnach, nigdy zmieszane.

**SPY — realne dane, nie syntetyczne:** nowa CLI `fetch-spy-benchmark-prices [--cutoff ...]` — CIK SPY rozwiązany przez SEC `company_tickers.json` (nigdy nie hardkodowany z pamięci, zgodnie z zasadą "tożsamość = CIK, nigdy ticker", sekcja 5), zapisany w `ticker_history` (nowa funkcja odczytu `db.get_cik_for_active_ticker()`, rzuca błąd przy niejednoznaczności zamiast cichego wyboru), ceny pobrane z FMP `historical-price-eod/full` i zapisane do `price_daily` pod tym CIK. SPY NIE jest i nie staje się częścią `universe_membership`/PIT universe. `run-baseline-walk-forward` odczytuje SPY CIK zero-sieciowo (z `ticker_history`) — jeśli nieznaleziony (SPY jeszcze nie pobrany w tym `--db`), SECONDARY jest po prostu `None` dla każdej daty, run się nie przerywa.

**Workflow (`phase5-3c-baseline-walk-forward.yml`):** dwa nowe kroki przed analizą — `classify-sector-profiles` (wymaga `SEC_EDGAR_USER_AGENT`) i `fetch-spy-benchmark-prices --cutoff <window_start>` (wymaga `FMP_API_KEY`+`SEC_EDGAR_USER_AGENT`) — jedyne miejsca z realnym dostępem do sieci w tym workflow; sama analiza nadal zero-sieciowa.

**Weryfikacja:** 25 nowych testów jednostkowych (`test_sector_classification.py`, `test_benchmark.py`, rozszerzenia `test_sec_edgar.py`/`test_db.py`) — 516 passed / 1 skipped razem w projekcie. Offline dry-run (fake SEC/FMP, monkeypatch `cli.SecEdgarClient`/`cli.FMPClient`, bez sieci) na 4 syntetycznych CIK (GENERAL/BANK/INSURER/REIT po jednym) potwierdza: SIC mapuje się na właściwy `sector_profile`; `fetch-spy-benchmark-prices` poprawnie rozwiązuje CIK i zapisuje ceny; `run-baseline-walk-forward` z aktywnym SPY poprawnie liczy SECONDARY benchmark (niepusty `spy_return_1m_pct`), a spółka z `sector_profile='BANK'` ma `valuation_score=None` z przyczyny `NOT_YET_IMPLEMENTED` (potwierdzone bezpośrednim wywołaniem `compute_valuation('BANK', ...)` → `implemented=False, reason="Brak zaimplementowanej metody wyceny dla sector_profile='BANK'"`), NIE z braku danych — odróżnione od analogicznego przypadku GENERAL, gdzie `implemented=False` wynika z niewystarczających danych FCF w syntetycznym przykładzie, nie z routingu.

Obie otwarte decyzje z poprzedniej sekcji są teraz zamknięte. Przed realnym uruchomieniem pełnego BASELINE walk-forward na 615 CIK pozostaje: (a) uruchomić `classify-sector-profiles` i `fetch-spy-benchmark-prices` na realnej, zabackfillowanej bazie (Faza 5.3b), (b) uruchomić `run-baseline-walk-forward` na pełnym oknie 2012+, (c) przedstawić raport wg 10 punktów zatwierdzonych przez właścicielkę 2026-10-04 — włącznie z coverage, oboma benchmarkami, rozkładami score'ów i forward returns, bez kalibracji.

## Faza 5.3c — REALNY pełny BASELINE walk-forward, wynik i raport 10-punktowy, v1.45

Uruchomiony i zakończony sukcesem 2026-10-04 (GH Actions run [37208774401](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37208774401), branch `claude/buffett-scanner-design-review-mrud89`, `run_id` backtestu = `walk-forward-baseline-2026-10-04T142105Z`). 615 CIK, monthly, 2012-01-01 → 2026-10-04. **Zero zmiany scoring weights/thresholds/decline thresholds/hard gates/valuation assumptions/`deterministic_score_pct` methodology względem już zatwierdzonej konfiguracji — potwierdzone (punkt 10).**

### Realny problem znaleziony i naprawiony PRZED tym runem (identity/PIT, zgłoszony i rozstrzygnięty w trakcie tej sesji)

Pierwsza próba realnego uruchomienia (run `37203999911`) padła na `sqlite3.IntegrityError: UNIQUE constraint failed` w `backtest_candidates`. Diagnoza: 4 CIK (Alphabet, Under Armour, News Corp, Fox Corp) mają **dual-class share tickery** (GOOGL/GOOG, UAA/UA, NWSA/NWS, FOXA/FOX) — `fja05680` traktuje obie klasy jako odrębne tickery S&P 500, oba poprawnie rozwiązują się do TEGO SAMEGO CIK, ale `merge_adjacent_same_cik_intervals` scalała tylko sąsiadujące (zero-gap) przedziały, nie nakładające się — jej własny docstring to explicite zakładał jako „poza zakresem". Efekt: `get_universe_membership_as_of()` zwracało ten sam CIK dwa razy dla 150/178 decision dates. **Decyzja właścicielki: naprawić builder, nie query layer.** `merge_adjacent_same_cik_intervals` przepisana na jedną, ogólną regułę interval-union (`next.start_date <= current.end_date`, adjacency jako szczególny przypadek), z audytowalną notą (`overlap_merge_note`) i sanity checkiem po scaleniu (FAIL FAST, jeśli jakakolwiek para nadal się nakłada). Nowa defensywna asercja w `run-baseline-walk-forward`: `universe_membership_as_of(D)` nigdy nie może zwrócić duplikatu CIK — FAIL FAST, nigdy cichy `DISTINCT`. Po dwóch dodatkowych technicznych (nie-danych) poprawkach — brakująca migracja kolumny `overlap_merge_note` w `init_db` dla reużywanego pliku DB (SQLite nie wspiera `ALTER TABLE ADD COLUMN IF NOT EXISTS`, zweryfikowane empirycznie) — trzecia próba (`37208774401`) przeszła w całości, z sanity checkiem potwierdzającym **0 nakładających się par po scaleniu** dla wszystkich 615 CIK. 31 nowych testów jednostkowych pokrywa przypadki B/C/D/E ze specyfikacji właścicielki (dual-class overlap, partial overlap, open-ended overlap, genuine exit/re-entry) — 526 passed/1 skipped.

### 1. Decision dates i obserwacje

178 decision dates (miesięcznie, 2012-01-01..2026-10-04). Company-date observations: **76 292** w PIT universe, **71 467** faktycznie przeskanowanych (93,68% ważone obserwacjami).

### 2. Pełny funnel (suma po wszystkich decision dates × CIK)

| Etap | Liczba | % PIT universe |
|---|---|---|
| PIT universe | 76 292 | 100% |
| sufficient price data | 74 400 | 97,5% |
| sufficient PIT fundamentals | 72 381 | 94,9% |
| **scanned** (oba warunki) | **71 467** | **93,7%** |
| wykluczeni: missing price | 1 892 | 2,5% |
| wykluczeni: missing fundamentals | 3 911 | 5,1% |
| NO_DECLINE_SIGNAL | 55 811 | 73,2% |
| EXCLUDED_BY_PREFILTER | 0 | 0% |
| HARD_GATE_FAILED | 0 | 0% |
| **CANDIDATE** | **15 656** | **20,5%** |

`EXCLUDED_BY_PREFILTER=0` i `HARD_GATE_FAILED=0` to oczekiwany stan tej konfiguracji (`exclude_rules` puste od Fazy 1/BLOCKER 5, `hard_gates.min_margin_of_safety_pct=null`, `UNCALIBRATED`) — **nie** wynik modelu "nic nie wykluczającego z zasady". Każda spółka z wykrytym sygnałem spadku automatycznie staje się kandydatem w tym baseline.

### 3. Coverage w czasie

Overall coverage_pct (ważony obserwacjami): **93,68%**. Rozkład w czasie: min/p10/p25/median/p75/p90/max = **0,0 / 86,9 / 89,4 / 95,8 / 97,7 / 98,4 / 99,0**. `min=0,0%` to wyłącznie pierwsza decision date (2012-01-01) — strukturalny artefakt (decline scanner wymaga historii cenowej *przed* datą decyzji, której przy pierwszym dniu okna z definicji nie ma dla nikogo) — nie błąd, nie reprezentatywne.

**Starsze lata są istotnie słabiej pokryte**, zgodnie z przewidywaniem: 10 najgorzej pokrytych dat to wyłącznie 2012 i wczesny 2013 (82,6%–85,9%, pomijając artefakt 0,0%), podczas gdy 2019+ utrzymuje 96–99%. To systematyczna, nie losowa, różnica w czasie — potencjalny selection/coverage bias we wczesnym okresie backtestu, zgodnie z zasadą, że missingness nie musi być losowe.

### 4. Kandydaci w czasie

Łącznie: **15 656**. Mediana na miesiąc: **70,5**. Miesięcy z 0 kandydatów: **1** (2012-01-01 — ten sam strukturalny artefakt co w punkcie 3).

| Rok | Kandydaci | Rok | Kandydaci |
|---|---|---|---|
| 2012 | 431 | 2020 | 2 179 |
| 2013 | 319 | 2021 | 605 |
| 2014 | 316 | 2022 | 2 162 |
| 2015 | 705 | 2023 | 1 454 |
| 2016 | 900 | 2024 | 1 084 |
| 2017 | 514 | 2025 | 1 689 |
| 2018 | 774 | 2026* | 1 420 |
| 2019 | 1 104 | | |

*2026: tylko 9 miesięcy (do 2026-10-01). Duże wahania rok-do-roku (316 → 2 179) odzwierciedlają zmienność rynku (2020 COVID, 2022 bear market) wykrywaną przez decline scanner — nieoczekiwane przy nieaktywnych hard gates.

### 5. Rozkład `deterministic_score_pct` i komponentów (n=15 656)

| Metryka | n | min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|---|---|
| `deterministic_score_pct` | 15 656 | 0,00 | 30,00 | 45,50 | 58,75 | 88,75 | 46,00 |
| `safety_score` | 15 656 | 0,00 | 4,69 | 6,56 | 9,38 | 12,19 | 6,52 |
| `dividend_score` | 15 656 | 0,00 | 2,00 | 5,00 | 8,00 | 10,00 | 4,98 |
| `valuation_score` | **0** | — | — | — | — | — | — |

**Najważniejsze znalezisko tego punktu: `valuation_score`/`margin_of_safety_base_pct` niedostępne dla 100% kandydatów (0/15 656).** `available_components` = `"safety,dividend"` dla WSZYSTKICH 15 656 wierszy, bez wyjątku. Zdiagnozowane u źródła (nie zgaduję): `compute_valuation`'s `dcf_owner_earnings` wymaga `net_debt()`, a `net_debt()` wymaga `period.total_debt` — pole świadomie, jawnie ustawione na `None` dla KAŻDEGO okresu w `pit_fundamentals.py` od Fazy 5.3b (decyzja odłożona: "kompozyt current/noncurrent jeszcze nierozstrzygnięty"). To było już wcześniej dokumentowane jako znana, odłożona luka (11/12 pól), ale **skala jej wpływu — 100% w realnym 15-letnim backteście na 615 spółkach — nie była wcześniej zmierzona**. Konsekwencja: `deterministic_score_pct` w CAŁYM tym baseline jest de facto sumą WYŁĄCZNIE safety+dividend (waga valuation = 20pkt nigdy nie przyznana, nigdy przetestowana). To nie jest błąd obliczeń — gate `NOT_YET_IMPLEMENTED` działa zgodnie z projektem (nigdy nie fabrykuje wyceny) — ale to materialne ograniczenie interpretacji wyników tego baseline, wymagające wyraźnego zastrzeżenia (patrz punkt 9).

### 6. Forward returns kandydatów (bez interpretacji jako dowód przewagi)

| Horyzont | n | min | p25 | median | p75 | max | mean |
|---|---|---|---|---|---|---|---|
| 1m | 15 350 | -74,37% | -5,39% | 1,37% | 8,26% | 181,41% | 1,98% |
| 3m | 14 892 | -84,86% | -6,90% | 3,98% | 14,93% | 214,67% | 5,02% |
| 6m | 14 255 | -94,90% | -8,69% | 6,72% | 23,23% | 738,10% | 9,51% |
| 12m | 13 177 | -99,11% | -8,94% | 13,50% | 39,62% | 996,23% | 20,34% |

`n` spada z horyzontem, bo najnowsze decision dates (2025–2026) jeszcze nie mają pełnej przyszłości — dla 12m dostępne dla 84% kandydatów. Rozkłady są silnie prawostronnie skośne (ekstremalne maksima, np. 996% na 12m) — `mean` nie jest reprezentatywne dla typowego wyniku, `median` jest właściwszą miarą centralną. Same dodatnie `mean`/`median` nie dowodzą niczego o przewadze scannera — potrzebne jest porównanie z benchmarkiem (punkt 8).

### 7. Benchmark — dualna implementacja (zrealizowana bez nowego stopu metodologicznego)

Zaimplementowane zgodnie ze specyfikacją właścicielki z poprzedniej tury (`benchmark.py`, tabela `backtest_benchmark`): **PRIMARY** `equal_weighted_pit_universe` (średni forward return WSZYSTKICH spółek z PIT universe z wystarczającymi cenami na danej decision_date, nie tylko kandydatów) i **SECONDARY** realny SPY (ta sama konwencja `forward_return_pct`, bez dywidend, co kandydaci). SPY CIK rozwiązany przez SEC `company_tickers.json` (884394), 3 709 realnych barów cenowych z FMP. Implementacja nie ujawniła problemu z dostępnością/konwencją danych — run przeszedł bezpośrednio do pełnego baseline, zgodnie z instrukcją.

### 8. Wyniki względem benchmarku

| Horyzont | n | hit rate vs EW | mean excess vs EW | median excess vs EW | hit rate vs SPY | mean excess vs SPY | median excess vs SPY |
|---|---|---|---|---|---|---|---|
| 1m | 15 350 | 49,0% | +0,49pp | -0,21pp | 49,3% | +0,44pp | -0,14pp |
| 3m | 14 892 | 49,5% | +0,77pp | -0,17pp | 49,1% | +0,61pp | -0,27pp |
| 6m | 14 255 | 47,9% | +1,52pp | -1,03pp | 47,1% | +0,90pp | -1,51pp |
| 12m | 13 177 | 47,9% | +3,61pp | -1,55pp | 46,3% | +2,70pp | -2,81pp |

(hit rate = % kandydatów z return > return benchmarku tej samej decision_date; excess = return kandydata − return benchmarku; pp = punkty procentowe)

**Odczyt, bez nadinterpretacji:** hit rate jest **poniżej 50% na każdym horyzoncie, wobec obu benchmarków** — większość kandydatów radzi sobie gorzej niż przeciętna spółka z PIT universe / SPY w tym samym okresie. `mean excess` jest lekko pozytywny, ale to efekt ciągnięty przez rzadkie, bardzo duże dodatnie wartości odstające (zgodnie z rozkładem z punktu 6) — `median excess` jest **ujemny na 3 z 4 horyzontów wobec obu benchmarków**, co jest właściwszym odczytem typowego przypadku. Dokładnie to, czego należy oczekiwać od NIEKALIBROWANEGO modelu bez komponentu valuation i bez aktywnych hard gates — **to nie jest dowód, że scanner nie działa**, to jest dowód, że ten konkretny baseline (safety+dividend, zero wykluczeń) nie wybiera systematycznie lepszych spółek niż przeciętna. Kalibracja (waga valuation, hard gates, thresholds) może to zmienić — ale to już następny krok, nie ten raport.

### 9. Ograniczenia i braki danych (jawnie)

- **Zawężone PIT universe:** 626/815 unikalnych tickerów z fja05680 w oknie 2012+ rozwiązanych do CIK (76,8%); **189 CIK_UNRESOLVED nigdy nie wchodzi do PIT universe** — to systematyczne zawężenie uniwersum (nie losowe missingness), więc "PIT universe" w tym backteście to ≈77% prawdziwego historycznego składu S&P 500, nie 100%. Potwierdzone ponownie w tym runie: `Unresolved (fja05680, nie generują wiersza): 189`.
- **28 CIK z niepełnymi cenami** z 615 w backfillu: 15 FAILED (w tym BRK.B/BF.B, zablokowane przez FMP „Special Endpoint" mimo planu Premium) + 13 PARTIAL (głównie konflikty merge przy zmianie tickera, np. FB/META, DISCK/WBD) + 1 FUNDAMENTALS PARTIAL. Włączone do walk-forward z dostępnymi danymi tam, gdzie istnieją — classify_data_sufficiency poprawnie wyklucza daty bez wystarczających cen (patrz punkt 2), nigdy nie fabrykuje.
- **Coverage NIE jest stała w czasie** — 82–86% w 2012–2013 vs 96–99% od 2019 (punkt 3). Starsze lata systematycznie słabiej pokryte.
- **`valuation_score` niedostępny dla 100% kandydatów** (punkt 5) — `deterministic_score_pct` w tym baseline mierzy wyłącznie safety+dividend, nie pełną zatwierdzoną rubrykę (waga valuation 20pkt nigdy przyznana).
- **Hard gates i prefilter nieaktywne w tej konfiguracji** (0 wykluczeń na 71 467 scanned) — `UNCALIBRATED`, nie wynik modelu uznającego wszystko za bezpieczne.
- **Forward returns 12m dostępne dla 84% kandydatów** (najnowsze decyzje nie mają jeszcze pełnej przyszłości) — rozkład z punktu 6 oparty na mniejszej, starszej podpróbce niż 1m/3m.
- **Oba benchmarki (PRIMARY i SECONDARY) są liczone względem tego samego, zawężonego PIT universe** (626/815 CIK) — nie są to niezależne, pełne 100% S&P 500 punkty odniesienia.
- **Sektor finansowy:** SIC-based klasyfikacja (Faza 5.3c, v1.44) poprawnie routinguje 20 BANK + 35 INSURER + 33 REIT na `NOT_YET_IMPLEMENTED` — te spółki nigdy nie miały fabrykowanej wyceny w tym baseline (ale jak wyżej, GENERALNE spółki też nie mają wyceny, z innej przyczyny: `total_debt`).

### 10. Brak kalibracji — potwierdzone

Scoring weights, thresholds, decline thresholds, hard gates, valuation assumptions i `deterministic_score_pct` methodology **nie zostały zmienione** względem konfiguracji zatwierdzonej w Fazie 4/5.3. Ten baseline nie został użyty do dostrajania żadnego parametru. Jedyne zmiany kodu w tej turze dotyczyły: (a) naprawy realnego błędu identity/PIT (overlapping dual-class intervals, sekcja wyżej) — poprawka struktury danych, nie modelu; (b) SIC sector_profile + dualny benchmark (Faza 5.3c v1.44) — infrastruktura pomiaru, nie parametry scoringu.

**Wniosek:** baseline jest kompletny, zweryfikowany (0 nakładających się przedziałów membership, testy jednostkowe zielone, offline dry-run potwierdzony wcześniej), i jawnie udokumentowany wraz z ograniczeniami. Najważniejszy fakt do uwzględnienia przy ewentualnej decyzji o kalibracji: **w tym baseline `deterministic_score_pct` nigdy nie zawierał komponentu valuation** — jakakolwiek przyszła kalibracja progu/wag powinna albo rozwiązać `total_debt` najpierw, albo jawnie uznać, że kalibruje tylko safety+dividend.

**v1.45 zachowany jako immutable pre-valuation baseline** (Decyzja właścicielki 2026-10-04) — `run_id=walk-forward-baseline-2026-10-04T142105Z`, artefakt GH Actions run [37208774401](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37208774401). Nie nadpisywać, nie kalibrować dalej na jego podstawie — służy jako punkt odniesienia do zmierzenia wpływu samego domknięcia `total_debt` (sekcja niżej), przed jakąkolwiek kalibracją scoring weights/thresholds/hard gates/decline thresholds/valuation assumptions/candidate selection.

## Faza 5.3d — diagnostyka SEC XBRL debt tags (przed implementacją `total_debt`), v1.46

Decyzja właścicielki po v1.45: najważniejsze znalezisko baseline (`valuation_score=None` dla 100% kandydatów) wymaga domknięcia `total_debt`. **Przed implementacją** — diagnostyka na realnych danych, zero sumowania, zero kodu produkcyjnego. Próbka: AAPL/MSFT/KO (wymagane) + TERADYNE/JABIL (hipoteza: prosty profil) + PG&E Corp/Constellation Energy/EQT Corp/DOW Inc (hipoteza: złożony profil, utilities/energy/chemicals) + Realty Income/O (REIT, sale-leaseback). Źródło: `sec_company_facts_cache` z już zbackfillowanej bazy (run `37188908038`), odczyt przez już przetestowaną `point_in_time.extract_fact_history` — zero nowego fetchu z SEC, zero nowej logiki PIT. Pełne surowe fakty (tag/value/unit/end/filed/form/fy/fp/accn) w logu GH Actions run `37214819897`.

### Co faktycznie znaleziono

**1. Pojedynczy aggregate debt fact — NIE istnieje wiarygodnie.**
- `DebtLongtermAndShorttermCombinedAmount` (teoretycznie dokładnie taki agregat): użyty **wyłącznie przez MSFT**, i tylko w starych filingach 2014–2015 (6 wpisów, ostatni `end=2015-03-31`) — potem MSFT przestał go raportować. Zero innych spółek w próbce go używa. **Nieużywalny jako ogólna reguła.**
- `Debt` (goły tag): zero wpisów u wszystkich 10 spółek.
- `DebtCurrent`: obecny tylko u TERADYNE i JABIL, ale **identyczny co do wartości** z ich `LongTermDebtCurrent` w tym samym `end_date` — to alias/duplikat tego samego faktu pod innym tagiem rozszerzenia filera, nie osobny agregat.
- `DebtInstrumentCarryingAmount`: obecny u **wszystkich 10 spółek**, ale semantycznie **niewiarygodny jako total firmy** — to tag INSTRUMENT-poziomu (jedna emisja/nota), nie company-level. Dowód: u EQT wartość = `0` wielokrotnie mimo realnego długu >5 mld USD; u Realty Income = `165 927 000`, podczas gdy ich rzeczywisty dług (suma `NotesPayable`) to >25 mld USD — **ten tag nie może być traktowany jako total**, mimo że istnieje u każdej spółki.

**2. Najczęstszy wzorzec: `LongTermDebtCurrent` + `LongTermDebtNoncurrent`, z `LongTermDebt` jako (zazwyczaj, nie zawsze) ich sumą.** Potwierdzona dobra PIT availability (dziesiątki-setki wpisów, 30-70 unikalnych `end_date`, konsystentne `filed`) u AAPL/MSFT/KO/JABIL/EQT/PG&E/Constellation (częściowo). Zweryfikowana identyczność `LongTermDebt = LongTermDebtCurrent + LongTermDebtNoncurrent` w TEJ SAMEJ dacie/filingu: **dokładna** u KO, MSFT, EQT, JABIL; **drobna niezgodność** u AAPL (82 300 000 000 vs suma 82 347 000 000 — różnica 47 mln, ~0,06%, ten sam `accn`) i Constellation Energy (różnica ~61 mln, ~0,8%).

**3. Znalezisko wymagające decyzji metodologicznej — PG&E Corp.** W **tym samym filingu** (10-K, `accn=0001004980-26-000009`, `end=2025-12-31`): `LongTermDebt=57 387 000 000`, `LongTermDebtNoncurrent=57 387 000 000` (**identyczne**), `LongTermDebtCurrent=821 000 000` (**osobno, nie odjęte**). U PG&E `LongTermDebt` NIE jest sumą current+noncurrent — jest **aliasem samego `LongTermDebtNoncurrent`**. To oznacza: reguła "`LongTermDebt` = total, nie dodawaj nic więcej" byłaby błędna dla KO/MSFT/EQT (zaniżyłaby dług, bo `LongTermDebt` już jest sumą — nie, raczej byłaby OK, bo jest sumą), ale reguła "zawsze preferuj sumę Current+Noncurrent, ignoruj `LongTermDebt`" jest bezpieczniejsza — **ale tylko jeśli oba komponenty są rzeczywiście obecne i semantycznie rozłączne**, co u PG&E akurat jest prawdą (Current i Noncurrent się nie nakładają, mimo że samodzielny tag `LongTermDebt` jest zwodniczy). **To jest realna niejednoznaczność, nie assumption do zrobienia bez decyzji** — znaczenie gołego tagu `LongTermDebt` nie jest spójne między filerami.

**4. Double-counting risk — potwierdzony, konkretny mechanizm.** Tagi z sufiksem `AndCapitalLeaseObligations`/`AndFinanceLeaseObligations` (np. `LongTermDebtAndCapitalLeaseObligations`, używany przez KO, TERADYNE, JABIL, DOW) to **skumulowane koncepty** — zawierają JUŻ w sobie leasing. U DOW widać przejście w czasie: `LongTermDebt` (goły) ma ostatni wpis `end=2024-12-31`, podczas gdy `LongTermDebtAndCapitalLeaseObligations` ma dane do `end=2026-03-31` — filer **przełączył się** z gołego `LongTermDebt` na skumulowany tag. Osobno raportowany `FinanceLeaseLiability`/`FinanceLeaseLiabilityNoncurrent` u tej samej spółki w tym samym okresie to **PODZBIÓR** już zawarty w `LongTermDebtAndCapitalLeaseObligations` — zsumowanie obu podwójnie liczyłoby leasing. Reguła musi wybrać JEDNĄ rodzinę (goły `LongTermDebt(+Current/Noncurrent)` ALBO skumulowany `...AndCapitalLeaseObligations(+Current/Noncurrent)`), nigdy obie naraz dla tej samej spółki/okresu.

**5. Różnice między prostym i złożonym profilem — potwierdzone, ale nie tak, jak zakładały hipotezy.** TERADYNE (hipoteza: prosty) okazał się mieć **najmniej stabilny** profil tagowania w próbce: `LongTermDebt` martwy od 2014 (ostatnia realna wartość, potem `0`), `DebtCurrent` i `ConvertibleDebtNoncurrent` pojawiają się/znikają w różnych okresach (zmiana struktury kapitałowej — konwertowalne obligacje). Realty Income (REIT) nie używa RODZINY `LongTermDebt` wcale dla ostatnich lat — dominujący tag to `NotesPayable` (>25 mld USD, zgodnie z modelem REIT finansowanego obligacjami) + `CommercialPaper` + `FinanceLeaseLiability`, bez żadnego podziału current/noncurrent. EQT/PG&E/Constellation (złożone profile) faktycznie mają WIĘCEJ tagów (`SeniorNotes`, `LinesOfCreditCurrent`, `CapitalLeaseObligationsCurrent/Noncurrent`), ale te okazują się być **szczegółowymi podzbiorami** `LongTermDebtNoncurrent` (np. u EQT `SeniorNotes=6 933 209 000` < `LongTermDebtNoncurrent=7 293 209 000` — różnica to inne, niewyszczególnione komponenty), nie dodatkowym, osobnym długiem do zsumowania.

### Proponowana hierarchia (DO DECYZJI, nie zaimplementowana)

1. **PIERWSZEŃSTWO:** `LongTermDebtCurrent + LongTermDebtNoncurrent` (obie wartości z TEGO SAMEGO `end_date`/filingu) — najbardziej rozłączne, najlepsza PIT availability, zweryfikowana semantyka u 4/6 prostych przypadków.
2. **FALLBACK, gdy tylko jeden z dwóch komponentów istnieje:** `LongTermDebt` sam, **TYLKO jeśli** żaden z `LongTermDebtCurrent`/`LongTermDebtNoncurrent` nie istnieje w tym `end_date` (żeby nigdy nie zgadywać, który wariant semantyczny — total czy noncurrent-only — reprezentuje u danego filera, per znalezisko PG&E).
3. **Rodzina `...AndCapitalLeaseObligations`/`...AndFinanceLeaseObligations`** traktowana jako ALTERNATYWNA, nie dodatkowa, do rodziny z punktu 1/2 — wybór między nimi per spółka/okres, nigdy suma obu rodzin.
4. **`ShortTermBorrowings`/`CommercialPaper`/`NotesPayableCurrent`** — do zbadania, czy to składniki ODDZIELNE od `LongTermDebtCurrent` (krótkoterminowy dług operacyjny, np. linia kredytowa, osobna od raty długu długoterminowego) czy czasem alias — próbka pokazuje różne spółki różnie (np. u MSFT `ShortTermBorrowings`/`CommercialPaper` = 0 w ostatnich latach, ale niezerowe historycznie).
5. **`NotesPayable`** (bez sufiksu Current/Noncurrent) jako GŁÓWNY tag u REIT/spółek bez podziału current/noncurrent (Realty Income) — wymaga osobnej ścieżki, nie tylko fallbacku.
6. **`FinanceLeaseLiability(Current/Noncurrent)`** — do decyzji: czy leasing finansowy liczy się jako "dług" w sensie `net_debt`/DCF tej metodologii, czy nie (semantycznie bliższy zobowiązaniu operacyjnemu niż typowemu długowi odsetkowemu — `OperatingLeaseLiability` zdecydowanie NIE powinien, ale `FinanceLeaseLiability` jest przedmiotem debaty w praktyce analitycznej).
7. **`DebtInstrumentCarryingAmount`** — WYKLUCZYĆ z reguły total (punkt 1 diagnostyki) — niewiarygodny cross-company.
8. **Brak żadnego z powyższych w danym `end_date`** → `total_debt=None` (zgodnie z zasadą "nigdy nie zgaduj/imputuj").

### Pozostałe otwarte pytania (metodologiczne, nie techniczne)

- Czy punkt 2 (fallback na goły `LongTermDebt`) jest bezpieczny, czy ryzyko PG&E-podobnej niejednoznaczności jest zbyt wysokie, żeby ufać gołemu tagowi bez komponentu current/noncurrent do porównania?
- Czy `FinanceLeaseLiability` wchodzi do `total_debt` tej metodologii?
- Czy `ShortTermBorrowings`/`CommercialPaper` dodają się DO `LongTermDebtCurrent`, czy bywają aliasem tego samego faktu (wymaga dalszej próbki/sprawdzenia per-filing)?
- Jak traktować spółki jak Realty Income, gdzie cała rodzina `LongTermDebt*` jest nieaktywna — osobna ścieżka per `NotesPayable`, czy `None`?

### Coverage na próbce (jakiś tag z rodziny LongTermDebt/NotesPayable aktywny na najnowszą datę)

10/10 spółek miało PRZYNAJMNIEJ jeden wiarygodny kandydacki tag na najnowszą dostępną datę. 0/10 miało pojedynczy, uniwersalny aggregate tag. 2/10 (PG&E, Constellation) wykazały realną niejednoznaczność semantyczną `LongTermDebt` wymagającą decyzji. 1/10 (Realty Income) nie używa rodziny `LongTermDebt*` wcale dla ostatnich lat.

### Testy potrzebne przed wdrożeniem

1. Czysta funkcja `compute_total_debt(period_facts_as_of_date) -> float | None` z jawną hierarchią (po decyzji metodologicznej powyżej), analogiczna do istniejącego stylu `net_debt`/`owner_earnings_proxy_fcf` — nigdy nie sumuje ciche, nigdy nie imputuje.
2. Testy regresyjne na dokładnie tych przypadkach: KO/MSFT/EQT/JABIL (Current+Noncurrent=total, prosty przypadek), AAPL/Constellation (drobna niezgodność — reguła musi dać deterministyczny, przewidywalny wynik, nie przypadkowo wybrany), PG&E (`LongTermDebt` jako alias Noncurrent — reguła NIE może przez przypadek zsumować i podwoić), DOW (przełączenie między `LongTermDebt` i `...AndCapitalLeaseObligations` w czasie — reguła musi wybrać jedną rodzinę per okres, nie obie), Realty Income (`NotesPayable`-only, zero `LongTermDebt*` — musi dać realną wartość, nie `None` z powodu nieobsłużonej ścieżki).
3. Test PIT: ta sama spółka, dwie `as_of_date` przed/po restatement długu — `total_debt` musi się zmienić zgodnie z `filed`, nie z `end` (ten sam wzorzec co istniejące testy `value_as_of`).
4. Test na pełnym 615-CIK zbiorze (nie tylko próbce 10) — pomiar: ile CIK dostaje `total_debt` != None na reprezentatywnych datach, rozkład tego, które ścieżki hierarchii (1-8) faktycznie się uruchamiają.
5. Po implementacji: ponowny pełny Proof Run + pomiar coverage `total_debt`/`valuation_score` na całym 615-CIK backteście + ponowne uruchomienie TEGO SAMEGO baseline walk-forward (te same decision dates, bez zmiany innych parametrów) — porównanie z v1.45 jako pre-valuation baseline.

## Faza 5.3e — diagnostyka coverage gap total_debt + Decyzja F, v1.47

Po v1.46 (Tier 1 CURRENT_PLUS_NONCURRENT/NOTES_PAYABLE_ONLY, coverage 38,71% na pełnym 615-CIK/76 292-obserwacji zbiorze), właścicielka zleciła diagnostykę: czy da się zbudować bezpieczny Tier 2 bez imputacji/zgadywania/double-countingu. Diagnostyka (2026-10-05, run jednorazowego workflow `diag-total-debt-coverage-gap.yml`, usunięty po wykorzystaniu) objęła pięć części:

**A. END_DATE_MISMATCH (13 082 obs., 28% całego None).** 0% przypadków ma różnicę end_date 0-31 dni — 88,1% to >100 dni (mediana 639, p90 2919 dni). W 94,9% przypadków istnieje w pełnej eligible historii WSPÓLNY instant dla current/noncurrent, którego `value_as_of()` nie wybrał (bo maksymalizuje `(filed,end)` niezależnie per tag) — **ale** zmierzony staleness tego wspólnego instant względem `decision_date` ma medianę 883 dni, >2 lata dla 54,9% przypadków, i **systematycznie się pogarsza w czasie** (mediana 397 dni w 2012 → 1735 dni w 2026, p90 2026 = 4923 dni). Zgłoszone właścicielce jako problem metodologiczny (nie techniczny), zgodnie z instrukcją „zgłoś problem przed zmianą kodu".

**B. MISSING ONE COMPONENT.** Dokładnie-jeden-brakuje: 3138 (NONCURRENT present/CURRENT missing) + 7780 (CURRENT present/NONCURRENT missing) = 10 918 obs. Większość "kandydatów" współdzielących `end` to koncepty cash-flow/harmonogramu zapadalności (`RepaymentsOfLongTermDebt`, `LongTermDebtMaturitiesRepaymentsOfPrincipalInYear*`), nie balance-sheet instant — wykluczone od razu jako semantycznie niekompatybilne. Realni kandydaci: `DebtCurrent` (31,3%), `ShortTermBorrowings` (21,9%), `CommercialPaper` (7,3%), `NotesPayableCurrent` (1,8%).

**C. Relacja kandydatów do Tier 1.** `DebtCurrent` jest w >50% przypadków współwystępowania z `LongTermDebtCurrent` dosłownym aliasem (ratio≈1,0, 1148/2139 near-equal) — automatyczne dodanie jako niezależny składnik groziłoby double countingiem u większości spółek. `ShortTermBorrowings` (13,6% near-equal) i `CommercialPaper` (6,6% near-equal, ratio median 0,615) wyglądają bezpieczniej, ale nie da się tego dowieść wyłącznie z zagregowanych `company_facts` (identyczny wniosek jak diagnostyka AAPL w v1.46).

**D/E. Warianty Tier 2 + symulacja coverage.** Tier 2a "CURRENT_PLUS_NONCURRENT_JOINT_INSTANT": +16,27 pkt proc. (38,71%→54,98%) — ale to właśnie ten wariant niesie staleness z Części A. Tier 2 "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM" (tylko CIK nigdy nie raportujące `LongTermDebtCurrent`): +2,19 pkt proc. (38,71%→40,90%), zero overlap z Tier 2a, zero double countingu z konstrukcji.

**Decyzja F (właścicielka, 2026-10-05):** Tier 2a **ODRZUCONY** — „formalna zgodność PIT nie wystarcza, jeśli wykorzystywany balance-sheet instant jest ekonomicznie nieaktualny względem decision_date"; brak arbitralnego progu staleness (365/180 dni) „żeby nie tworzyć kolejnego parametru wymagającego kalibracji". Tier 2 "NONCURRENT_PLUS_DEBTCURRENT_SYNONYM" **ZAAKCEPTOWANY** z rygorystycznym warunkiem wyłączności. **Decyzja architektoniczna:** nie podnosimy już coverage przez coraz agresywniejsze mapowanie SEC XBRL — ~40,90% jest traktowane jako HIGH-CONFIDENCE DEBT COVERAGE, praktyczny limit tej metody przy wymaganiach PIT correctness/aktualność/semantyczna spójność/zero double counting/zero imputacji, nie błąd do dalszego "naprawiania".

**Implementacja (Faza 5.3f):** `total_debt.py` rozszerzony o `NONCURRENT_PLUS_DEBTCURRENT_SYNONYM` (confidence_tier=TIER_2) + pełną provenance (`component_tags`/`component_values`/`component_provenance`/`balance_sheet_instant`) na WSZYSTKICH wariantach (też Tier 1, retroaktywnie) + parametr `target_end` (filtruje wszystkie komponenty do konkretnego balance-sheet instant PRZED PIT lookup — wymagane do poprawnego wpięcia per-`FundamentalsPeriod`, inaczej total_debt obliczony dla "najnowszego dostępnego" mógłby nie odpowiadać instant konkretnego okresu, do którego jest przypisywany). `pit_fundamentals.build_annual_fundamentals_periods_as_of` wywołuje `compute_total_debt_as_of(company_facts, as_of_date, target_end=end)` dla KAŻDEGO rocznego okresu niezależnie (ta sama zasada "ten sam instant", która już chroni EBITDA) — `total_debt` NIE jest już jawnie `None`. `FundamentalsPeriod` zyskał `total_debt_resolution_method`/`total_debt_confidence_tier` (podsumowanie do agregacji coverage w walk-forward; pełna provenance per-komponent zostaje w `TotalDebtResult`). Zero zmian w `scoring.py`/`backtest_harness.py`/`valuation.py` — architektura `deterministic_score_pct`/`available_components`/`missing_components`/`is_partial` już poprawnie obsługiwała "brak valuation ≠ 0" (zweryfikowane przy przeglądzie kodu, nie wymagało naprawy).

## Faza 5.3g — POST-DEBT / PARTIAL-VALUATION baseline, wynik, v1.48

Po implementacji (Faza 5.3f): Proof Run (AAPL/MSFT/KO, run GH Actions [37272033701](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37272033701)) potwierdził `total_debt` liczony realnie (Tier 1 u wszystkich trzech, zero naruszeń PIT na 18 parach) i poprawne zachowanie "brak valuation ≠ 0" (AAPL: `valuation=None` mimo Tier 1 total_debt — inny bottleneck; MSFT/KO: `valuation=0.0`, realny ujemny margin of safety). Następnie TEN SAM baseline walk-forward co v1.45 (`backfill_run_id=37188908038`, identyczne `window_start`, zero zmian scoring weights/thresholds/hard gates/decline thresholds/valuation assumptions) — `run_id=walk-forward-baseline-2026-10-05T062554Z`, artefakt [37272173706](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37272173706). v1.45 zachowany jako immutable pre-valuation baseline, NIE nadpisany.

**Funnel identyczny co do liczby** (178 decision dates, 76 292 obs. PIT universe, 71 467 scanned, NO_DECLINE_SIGNAL=55 811, CANDIDATE=15 656) — oczekiwane, bo `total_debt`/valuation nie wpływają na decline scanner/prefilter/hard gates (wszystkie trzy hard gates `null` w obecnym configu, status UNCALIBRATED).

**Część 1 — realny total_debt coverage** (rekomputacja `periods[-1]` dla każdej z 76 292 obserwacji PIT universe × decision_date, niezależnie od decline scanera — total_debt liczony dla każdego scanned obs., nie tylko kandydatów):
- Overall: **38,36%** (29 265/76 292). Per rok: rosnący z 33,9% (2012) do ~40% (2020+), płasko od tego momentu — NIE monotonicznie rosnący jak w surowej diagnostyce 2026-10-05, bo tu total_debt jest zakotwiczony do konkretnego `period_end` (najnowszy roczny okres), nie do "najnowszego dostępnego instant jako-of decision_date" — udokumentowana, oczekiwana różnica metodologii (patrz docstring `total_debt.py`, sekcja `target_end`).
- Rozkład: `CURRENT_PLUS_NONCURRENT` 35,6%, `NONCURRENT_PLUS_DEBTCURRENT_SYNONYM` (Tier 2) 2,1%, `NOTES_PAYABLE_ONLY` 0,6%, `INSUFFICIENT_DATA` 56,5%, `NO_ANNUAL_PERIOD` 5,1% (spółki bez żadnego rocznego net_income/revenue okresu w tej dacie — osobna kategoria od "ma okres, ale brak total_debt").
- Confidence tier: TIER_1 36,3%, TIER_2 2,1%, brak 61,6%. Per-CIK: 354/614 (57,7%) — identyczne jak w surowej diagnostyce, mimo różnicy w per-observation %.

**Część 2 — valuation coverage + bottleneck wśród 15 656 kandydatów** (valuation liczony WYŁĄCZNIE dla kandydatów — decline scanner odcina resztę przed policzeniem score, architektura niezmieniona):
- `valuation_score != None`: **2889 (18,5%)** kandydatów — NIŻEJ niż ogólny total_debt coverage (38,36%), bo valuation wymaga DODATKOWO zdrowego FCF/CAGR/sector_profile/diluted_shares.
- Confidence tier total_debt wśród kandydatów: TIER_1 37,9%, TIER_2 1,8%, brak 60,3%.
- **26,1% kandydatów z `valuation=None` MA high-confidence total_debt mimo to (3332/12 767)** — total_debt NIE jest już głównym bottleneckiem dla tej podgrupy.
- Przyczyny `valuation=None` (rekomputacja `compute_valuation`, rozbicie `reason`): 4286 "brak kompletnych danych bilansowych" (total_debt i/lub cash), **3805 najnowszy owner_earnings_proxy_fcf None/ujemny — NOWY, realny bottleneck, odsłonięty po domknięciu total_debt**, 2322 niewystarczająca historia do CAGR, 1475 sector_profile BANK/INSURER/REIT (poza zakresem, zgodne z projektem), 90 brak diluted shares. Oczekiwane u spółek ze scannera spadków — ujemny/zerowy FCF jest częsty u spółek w realnym spadku, to nie błąd, to charakter próbki.
- **189 "rozbieżności" (1,5% z `valuation=None`) — WYJAŚNIONE (2026-10-05), ZWERYFIKOWANE rerunem całej produkcyjnej ścieżki, PRODUKCJA BYŁA SPÓJNA przez cały czas.** Przyczyna: `ValuationResult.implemented=True` NIE implikuje `margin_of_safety_pct is not None` — gdy `net_debt` jest na tyle duży, że `equity_value` (a więc `intrinsic_value_per_share` scenariusza BASE) jest ≤0, pole `margin_of_safety_pct` tego scenariusza jest jawnie `None` (ujemna wycena equity nie ma sensownego "marginesu bezpieczeństwa" — zachowanie udokumentowane już w `ScenarioValuation.margin_of_safety_pct`, nie nowe). `compute_deterministic_score` poprawnie to propaguje: `mos_base=None` → `valuation_score=None`, mimo `implemented=True`. Pomocniczy skrypt raportujący mylił `implemented=True` z "ma użyteczny score" (wywoływał `compute_valuation()` wprost zamiast kanonicznej `compute_deterministic_score()`). **Weryfikacja: dla WSZYSTKICH 189 przypadków ponownie uruchomiono CAŁĄ produkcyjną ścieżkę (`evaluate_candidate_at_date`, identyczne periods/bars/sector_profile/config z tego samego artefaktu, config_version zweryfikowany identyczny) — 189/189 (100%) rerunów POTWIERDZIŁO persisted `valuation_score=None`, zero sprzeczności.** v1.48 (`walk-forward-baseline-2026-10-05T062554Z`) pozostaje poprawny, nie wymaga ponownego runu. Dodane dwa stałe testy regresyjne (`tests/test_valuation.py::test_compute_valuation_implemented_true_but_base_margin_of_safety_none_when_negative_equity`, `tests/test_backtest_harness.py::test_compute_deterministic_score_implemented_true_but_valuation_score_none_on_negative_equity`) jako invariant: żaden przyszły kod analityczny nie może wnioskować `valuation_score` z samego `implemented` — musi iść przez `compute_deterministic_score` (jedyna kanoniczna ścieżka), nigdy przez dwie niezależne implementacje logiki valuation.

**Faza 5.3 — BASELINE COMPLETE (2026-10-05).** Trzy główne, metodologicznie zamrożone ograniczenia valuation coverage (18,5% wśród kandydatów) — nie "błędy do naprawienia", tylko udokumentowane granice obecnego zakresu:
1. **Non-positive FCF** (3805 kandydatów, 29,8% z `valuation=None`) — najnowszy `owner_earnings_proxy_fcf` ≤0; oczekiwane u spółek ze scannera spadków.
2. **Insufficient FCF history** (2322, 18,2%) — brak ≥2 okresów z jednoznacznie dodatnim FCF do policzenia CAGR bez zgadywania.
3. **Excluded sector methodology** (1475, 11,6%: 808 REIT + 683 INSURER + 584 BANK — suma >1475 bo zaokrąglenia; dokładnie: BANK/INSURER/REIT razem) — `dcf_owner_earnings` zaimplementowany tylko dla GENERAL, zgodnie z Decyzją D7 (Faza 10, poza obecnym zakresem).
Pozostałe: brak diluted shares (90, 0,7%) i obecnie wyjaśnione 189 (1,5%, patrz wyżej — NIE jest to realny "missing data reason", tylko poprawnie policzona ujemna wycena equity). Nie zwiększamy dalej coverage `total_debt` (Decyzja F, 2026-10-05) ani nie rozszerzamy zakresu valuation teraz — Faza 5.3 zamknięta, następny krok to Faza 5.4 (projekt protokołu kalibracji, patrz niżej).

**Część 3 — PAIRED porównanie WITH vs WITHOUT valuation, dokładnie ten sam complete-valuation subset (2889 obs., 18,5% kandydatów)** — nigdy nie porównane z całym universe, żeby uniknąć selection/coverage bias:

| Horyzont | WITH: spearman(score,return) | WITHOUT: spearman | WITH: hit rate top-half | WITHOUT: hit rate top-half | WITH: top−bottom spread | WITHOUT: top−bottom spread |
|---|---|---|---|---|---|---|
| 1m | 0,034 | 0,032 | 56,2% | 56,9% | 1,87pp | 1,42pp |
| 3m | 0,040 | 0,054 | 58,9% | 61,8% | 2,24pp | 2,57pp |
| 6m | 0,064 | 0,076 | 63,1% | 64,8% | 3,17pp | 4,16pp |
| 12m | 0,084 | 0,085 | 67,5% | 69,3% | 5,36pp | 3,51pp |

**Wniosek: na tym subsecie dodanie valuation NIE poprawia wykrywalnie jakości rankingu/selekcji względem modelu safety+dividend.** Korelacje są blisko zera dla OBU wariantów (0,03–0,09 — poziom szumu, nie sygnału), hit rate top-half jest WYŻSZY bez valuation na 3 z 4 horyzontów, spread top-bottom mieszany (WITH lepszy na 1m/12m, WITHOUT lepszy na 3m/6m). Excess returns vs oba benchmarki (equal_weighted_pit_universe i SPY) są praktycznie IDENTYCZNE między wariantami na każdym horyzoncie (różnice <0,1pp) — bo to te SAME surowe forward returns, tylko inaczej ranked wewnątrz tego samego zbioru.

**Interpretacja, nie kalibracja:** sample jest mały (2889/15 656 = 18,5%) i systematycznie nielosowy — tylko spółki GENERAL z dodatnim historycznym FCF, pełną historią ≥2 okresów i znaną liczbą akcji trafiają do tego subsetu. To NIE jest dowód, że DCF-owa wycena "nie działa" ogólnie — to dowód, że na WĄSKIM, selekcjonowanym podzbiorze obecnego baseline (bez kalibracji wag/progów) nie widać mierzalnej przewagi. Właścicielka zdecyduje, czy to wystarczający dowód do zmiany architektury, czy wymaga dalszej analizy przed jakąkolwiek kalibracją (zgodnie z jej instrukcją: "Nie interpretuj poprawy/pogorszenia jako podstawy do kalibracji przed obejrzeniem całego raportu").

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

## Faza 5.4 — Protokół kalibracji (ZATWIERDZONY WARUNKOWO, Decyzja właścicielki 2026-10-05, z poprawkami wbudowanymi niżej)

Zatwierdzony z poprawkami. Zero zmian parametrów przed zamrożeniem `practical tie rule` (punkt 9) — od momentu zamrożenia, ROUND 1 rusza bez dodatkowego pytania o zgodę, ale holdout 2022–2026 pozostaje zablokowany aż do punktu 10.

### 1. Train/calibration period vs FINAL holdout (nie "holdout per runda")

**Calibration window: 2012-01-01 → 2021-12-01** (120 decision dates). **Holdout: 2022-01-01 → 2026-10-01** (58 decision dates), fizycznie/logicznie niedostępny dla procesu wyboru parametrów przez CAŁY proces kalibracji (Round 1–3), nie "raz na rundę".

**Zasada sztywna (poprawka właścicielki):** holdout używany dokładnie RAZ, dopiero po zakończeniu WSZYSTKICH rund, wyborze finalnej konfiguracji i jej zamrożeniu. Po zobaczeniu wyniku holdoutu NIE WOLNO: zmienić parametrów, zmienić metryki, zmienić progów, wybrać innej konfiguracji, rozpocząć kolejnej rundy kalibracji na podstawie wyniku holdoutu. Słaby wynik holdoutu jest raportowany jako słaby wynik — nie jest powodem powrotu do 2012–2021.

Z logów v1.48: `candidates_total` na koniec 2021-12 = 7847, na koniec runu = 15 656 → holdout ma 7809 kandydatów (49,9%) mimo 33% dat — realna moc statystyczna. Rozkład complete-valuation subset między oknami zmierzony dokładnie przy starcie Round 1, nie szacowany.

### 2. Walk-forward / out-of-sample evaluation WEWNĄTRZ okna kalibracyjnego

Expanding-window, roczne kroki: 2012–2015→OOS 2016; 2012–2016→OOS 2017; ...; 2012–2020→OOS 2021. Każdy rok testowy jest OOS względem konfiguracji wybieranej na wcześniejszych latach. **Wyniki każdego foldu zachowywane osobno** (nie tylko zagregowane) — persystowane w `calibration_runs` per kandydat.

Operacjonalizacja (bo nie ma tu literalnego "fitowania" na danych, tylko wybór dyskretnych wartości parametrów): KAŻDY kandydat konfiguracji jest uruchamiany JEDNYM pełnym walk-forward na 2012–2021 (harness już jest PIT-poprawny z konstrukcji — "expanding window" nie zmienia tego, co widzi silnik, tylko jak dzielimy OUTCOME na foldy raportowania). Kandydaci 2012–2015 nigdy nie są rokiem testowym żadnego foldu — służą wyłącznie jako historia/rozgrzewka (CAGR, decline lookback), nie wchodzą do primary metric.

### 3. Benchmarki

PRIMARY `equal_weighted_pit_universe`, SECONDARY `SPY` — bez zmian.

### 4. Primary evaluation metric (ZATWIERDZONA)

**Primary: mediana 6m excess return (kandydat − equal_weighted_pit_universe).** Raportowana DWOMA sposobami (poprawka właścicielki — żeby jeden wyjątkowo dobry rok nie decydował):
- **A. Pooled OOS** — mediana wszystkich OOS candidate excess returns ze WSZYSTKICH foldów razem (2016–2021 połączone).
- **B. Fold stability** — mediana osobno per rok (2016, 2017, ..., 2021), plus: mediana z 6 fold-medians, min/max fold median, liczba foldów z dodatnią medianą, sample size per fold.

SECONDARY (raportowane, NIGDY nie wybierają konfiguracji): hit rate per horyzont, excess vs SPY, Spearman(score, forward_return) per horyzont, 1m/3m/12m.

### 5. Miesiące z zero kandydatów

Liczone i raportowane jawnie (nigdy ukryte), wnoszą 0 obserwacji do poolingu na poziomie kandydata (metoda PRIMARY). Equal-weighted-per-month jako diagnostyka dodatkowa, nie optymalizowana.

### 6. Sample size — LOW_SAMPLE flag, bez automatycznego odrzucania

Fold/horyzont z **n < 30** oznaczany jawnie jako `LOW_SAMPLE` w raporcie. **Pozostaje w raporcie, nie jest usuwany, nie przesądza samodzielnie o wyborze konfiguracji.** Brak dodatkowego arbitralnego progu do automatycznego odrzucania — liczebność i stabilność są pokazywane, nie optymalizowane.

### 7. Które parametry wolno kalibrować — PODZIELONE NA 3 SEKWENCYJNE RUNDY

**ROUND 1 — SELECTION MECHANICS** (cel: czy scanner sensownie zawęża universe; wagi = default, valuation mechanics zamrożone):
- `decline_scanner.thresholds`
- `prefilter` rules/thresholds
- `hard_gates` (obecnie wszystkie `null`, status UNCALIBRATED)

**ROUND 2 — COMPONENT WEIGHTS** (dopiero po zamrożeniu Round 1):
- `scoring.weights.financial_safety`
- `scoring.weights.dividend_shareholder_return`
- `scoring.weights.valuation` — testowane OSOBNO na complete-valuation subset (nie na całym universe — tam większość obserwacji i tak nie ma valuation)
- Zmiany wag NIE MOGĄ kompensować złych gates/prefilteru z Round 1 — Round 1 pozostaje zamrożony podczas Round 2.

**ROUND 3 — VALUATION SENSITIVITY** (dopiero po zamrożeniu Round 1–2):
- `dcf_owner_earnings.mos_pct_for_full_score`
- `dcf_owner_earnings.max_projected_growth_rate_pct` / `.min_projected_growth_rate_pct`
- Mała, jawna siatka ekonomicznie sensownych wartości — NIE continuous parameter search.

Po każdej rundzie: wybór i zamrożenie zwycięskiej konfiguracji PRZED przejściem do następnej rundy, używając wyłącznie calibration data 2012–2021 + wewnętrznych OOS foldów 2016–2021.

### 8. Które zasady pozostają metodologicznie ZAMROŻONE (nigdy nie podlegają kalibracji)

- Cała hierarchia `total_debt` (Tier 1/Tier 2, Decyzja F 2026-10-05).
- Mechanizm PIT (`value_as_of`, `filed<=as_of_date`) i dyscyplina "nigdy nie zgaduj/imputuj".
- Konstrukcja `universe_membership` (w tym allowlista rename).
- Definicja kompozytu EBITDA.
- Architektura modelu DCF (formuła Gordona/perpetuity) — PARAMETRY kalibrowalne w Round 3, STRUKTURA nie.
- **`dcf_owner_earnings.discount_rate_pct` / `.terminal_growth_rate_pct`** — założenia inwestora/modelu wyceny, NIE parametry predykcyjne do data-miningu na historycznych returns. Zmieniane wyłącznie jawną decyzją inwestycyjną właścicielki, nigdy optymalizacją.
- Definicje benchmarków i konwencja `forward_return_pct` (bez dywidend, baza = decision_price).
- Routing `sector_profile` (GENERAL jedyny zaimplementowany — Decyzja D7, Faza 10).
- `deterministic_score_pct` — normalizacja tylko po DOSTĘPNYCH komponentach (architektura, nie parametr).

### 9. Zabezpieczenia przed overfittingiem + PRACTICAL TIE RULE (zamrożona PRZED pierwszym search runem)

1. Holdout fizycznie nietknięty do finalnej walidacji (punkt 1 i 10).
2. Nested expanding-window CV (punkt 2), raportowanie pooled + per-fold (punkt 4).
3. Sekwencyjne rundy (punkt 7) — max 2–3 parametry naraz, zamrożenie przed następną rundą.
4. Primary metric zamrożona (punkt 4) — zero metric shopping.
5. KAŻDA przetestowana konfiguracja logowana w `calibration_runs` i raportowana, przegrywające NIE są usuwane.
6. Sanity bounds: żaden parametr nie wychodzi poza ekonomicznie sensowny zakres (np. gate nie wyklucza >90% universe bez jawnego uzasadnienia).
7. **Practical tie rule (ZAMROŻONA, patrz wyprowadzenie liczby w Faza 5.4a niżej):** Konfiguracja B nie jest uznana za lepszą od A wyłącznie dlatego, że jej pooled-OOS primary metric jest wyższa o mniej niż epsilon. Epsilon wyprowadzony z WŁASNEJ zmienności fold-to-fold baseline (nieskalibrowanego configu) na tych samych 6 foldach — czyli z poziomu szumu, jaki system ma i bez żadnej kalibracji — zmierzony RAZ, PRZED pierwszym kandydatem w Round 1, i zamrożony. Gdy różnica < epsilon → remis praktyczny → wybierana PROSTSZA konfiguracja (mniej zmienionych parametrów względem obecnego default/UNCALIBRATED stanu).
8. Finalna walidacja na holdout = porównanie do ORIGINAL UNCALIBRATED BASELINE + obu benchmarków, nie ocena w próżni.
9. Holdout użyty RAZ, po wszystkich rundach (nie raz na rundę — poprawka punktu 1).

### 10. Porównanie partial (pełny funnel) vs complete-valuation subset

Populacje NIE są mieszane. **FULL/PARTIAL MODEL:** cały dostępny GENERAL universe, z jawnie brakującymi komponentami (jak dotychczas, `available_components`/`missing_components`). **COMPLETE-VALUATION SUBSET:** osobna analiza, tylko obserwacje z pełnym valuation. Wpływ valuation oceniany WYŁĄCZNIE przez paired comparison (te same company-date observations, WITHOUT vs WITH valuation — metodologia z raportu POST-DEBT, Część 3), nigdy przez porównanie całego universe z subsetem (to by pomieszało wpływ valuation z selection/coverage bias).

### 11. Auditability

Każda próba kalibracyjna (`calibration_runs`, patrz `db.py`) zapisuje: config (JSON), config hash, calibration round, candidate name, training window, OOS fold lata, sample size (pooled + per fold), primary metric (pooled + per-fold + fold-stability), secondary metrics, timestamp/run_id. Proces odtwarzalny — żadna przegrywająca konfiguracja nie jest usuwana.

### 12. Status

Protokół zatwierdzony z poprawkami wbudowanymi wyżej. `practical tie rule` — metodologia zamrożona w punkcie 9.7, KONKRETNA liczba epsilon wyprowadzona i zamrożona w Faza 5.4a (pomiar szumu baseline) PRZED pierwszym kandydatem Round 1. Po zamrożeniu epsilon, ROUND 1 rusza bez dodatkowego pytania o zgodę. Holdout 2022–2026 pozostaje zablokowany.

---

## Faza 5.4a — ROUND 1 (SELECTION MECHANICS): epsilon zamrożony, wyniki, decyzja, v1.50

**Wykonanie:** 5 dispatchów `phase5-4-calibration-candidate.yml` (2026-10-05, ~12:58–13:10 UTC), pełny 615-CIK universe, okno kalibracyjne HARDKODOWANE 2012-01-01→2021-12-01 (120 decision dates), holdout 2022–2026 fizycznie niedostępny z tego workflow (okno wpisane w `calibration.py`, nie przyjmowane jako input). Wszystkie 5 statusów GitHub Actions = `success`. Każdy kandydat operuje na WŁASNEJ kopii bazy backfillu (Faza 5.3b) — zero współdzielonego stanu między kandydatami.

Jeden dodatkowy, wcześniejszy dispatch (run [37312834803](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37312834803), `--sample=320193,789019,21344`) był resztką testową z 3 CIK — WYKLUCZONY z Round 1 (pooled n=25, wszystkie foldy `low_sample=True`, nie reprezentuje pełnego universe). Nie liczy się do decyzji.

### 1. Epsilon — zamrożony PRZED porównaniem jakiegokolwiek kandydata (protokół punkt 9.7)

`derive_practical_tie_epsilon` = odchylenie standardowe populacyjne (`statistics.pstdev`) 6 medianowych wyników foldów BASELINE (6m, vs `equal_weighted_pit_universe`), policzone wyłącznie z wyniku kandydata `baseline` — zanim porównano jakikolwiek inny kandydat:

| Fold (OOS rok) | n | median_excess_6m_vs_ew |
|---|---|---|
| 2016 | 879 | 3,0576% |
| 2017 | 481 | −0,7274% |
| 2018 | 741 | −1,2632% |
| 2019 | 1042 | −2,4346% |
| 2020 | 2113 | 3,3329% |
| 2021 | 578 | −0,6028% |

**epsilon = 2,1819 pp — ZAMROŻONE.** (zweryfikowane bezpośrednio funkcją produkcyjną `calibration.derive_practical_tie_epsilon`/`practical_tie`, nie przeliczone ręcznie poza kodem).

### 2. Pełne wyniki Round 1 (5 kandydatów, PRIMARY = pooled OOS + fold stability, 6m vs equal_weighted_pit_universe)

| Kandydat | calibration_run_id | n (pełny funnel, 2012–2021) | Pooled OOS n | Pooled median_excess | low_sample | n_positive_folds | median_of_fold_medians | min fold | max fold |
|---|---|---|---|---|---|---|---|---|---|
| `baseline` | calib-r1-baseline-2026-10-05T130103Z | 7847 | 5834 | 0,7608% | False | 2/6 | −0,6651% | −2,4346% | 3,3329% |
| `stricter_decline` | calib-r1-stricter_decline-2026-10-05T130103Z | 4151 | 3124 | 1,8875% | False | 4/6 | 0,9801% | −4,4428% | 5,1649% |
| `hard_gate_safety_floor` | calib-r1-hard_gate_safety_floor-2026-10-05T130055Z | 3511 | 2660 | 0,7608% | False | 3/6 | −0,1985% | −3,6430% | 4,1301% |
| `prefilter_excludes` | calib-r1-prefilter_excludes-2026-10-05T130103Z | 6354 | 4563 | 1,1523% | False | 2/6 | −0,9212% | −2,6507% | 4,4127% |
| `combo_decline_and_prefilter` | calib-r1-combo_decline_and_prefilter-2026-10-05T130117Z | 3367 | 2453 | 1,6936% | False | 3/6 | 0,4894% | −4,3714% | 5,2730% |

Pełne foldy per kandydat (6m vs equal_weighted_pit_universe), z GitHub Actions run logs (run ID w nagłówku kolumny):

| Fold | baseline (n / median) [37313299445] | stricter_decline (n / median) [37313302649] | hard_gate_safety_floor (n / median) [37313307388] | prefilter_excludes (n / median) [37313310977] | combo (n / median) [37313315244] |
|---|---|---|---|---|---|
| 2016 | 879 / 3,0576% | 463 / 3,6125% | 313 / 1,7247% | 743 / 2,8867% | 398 / 1,8214% |
| 2017 | 481 / −0,7274% | 232 / 1,9311% | 198 / −0,4068% | 384 / −0,8341% | 194 / 2,3035% |
| 2018 | 741 / −1,2632% | 317 / −1,8425% | 288 / 0,0097% | 559 / −1,1296% | 245 / −2,5234% |
| 2019 | 1042 / −2,4346% | 533 / −4,4428% | 536 / −3,1101% | 832 / −2,6507% | 428 / −4,3714% |
| 2020 | 2113 / 3,3329% | 1377 / 5,1649% | 1012 / 4,1301% | 1594 / 4,4127% | 1028 / 5,2730% |
| 2021 | 578 / −0,6028% | 202 / 0,0290% | 313 / −3,6430% | 451 / −1,0082% | 160 / −0,8426% |

Secondary diagnostics (hit rate, spearman score-vs-return, horyzonty 1m/3m/6m/12m — nigdy nie decydują o wyborze) policzone i zapisane w każdym `calibration_result.db`, pominięte tu dla czytelności — dostępne w logach GitHub Actions podanych run ID.

### 3. Decyzja — zastosowanie zamrożonej `practical tie rule`

|Δ pooled median_excess vs `baseline`| policzone funkcją produkcyjną `practical_tie(baseline, candidate, epsilon=2,1819)`:

| Kandydat | Δ vs baseline (pp) | Wynik `practical_tie` |
|---|---|---|
| `stricter_decline` | 1,1267 | **TIE** (< 2,1819) |
| `hard_gate_safety_floor` | 0,0000 | **TIE** |
| `prefilter_excludes` | 0,3915 | **TIE** |
| `combo_decline_and_prefilter` | 0,9328 | **TIE** |

**WSZYSTKIE 4 testowane warianty selection mechanics są statystycznym remisem z `baseline`** na PRIMARY metric w granicach zamrożonego epsilon — żaden nie przekracza szumu fold-to-fold samego baseline. Per protokół punkt 8 ("w razie remisu preferuj prostszą konfigurację"): **ZWYCIĘZCA ROUND 1 = `baseline`** (brak zmian `decline_scanner.thresholds` / `hard_gates` / `prefilter`).

### 4. Obserwacje drugorzędne (raportowane dla przejrzystości, NIE użyte do zmiany decyzji — unikanie kryterium wymyślonego po zobaczeniu wyniku)

- `stricter_decline` ma zauważalnie lepszą fold-stability (4/6 dodatnich foldów, `median_of_fold_medians`=0,98%) niż `baseline` (2/6, −0,67%), mimo remisu na pooled metric. To jest zanotowane jako kierunkowa obserwacja do rozważenia w kontekście przyszłych rund — **nie zmienia decyzji Round 1**, bo `practical tie rule` została zamrożona PRZED zobaczeniem wyników i dotyczy pooled OOS, nie fold-stability z osobna.
- `hard_gate_safety_floor` ma pooled median_excess IDENTYCZNY z `baseline` do 13 cyfr znaczących (0,7607722688193741%), mimo n=2660 vs n=5834. To nie jest błąd ani przypadek wymagający alarmu: `hard_gate_safety_floor` jest ścisłym PODZBIOREM `baseline` (ten sam decline/prefilter, dodatkowy hard gate tylko usuwa kandydatów, nigdy nie dodaje) — mediana podzbioru trafiająca dokładnie na tę samą wartość co mediana zbioru pełnego jest statystycznie zgodna z istnieniem duplikatów/skupień w rozkładzie forward excess returns (wiele obserwacji dzieli tę samą cenę/okres). Brak znaleziska PIT/kalkulacyjnego.
- Żaden z 5 kandydatów nie przekroczył 4/6 dodatnich foldów na horyzoncie 6m — oczekiwane dla rundy testującej wyłącznie selection mechanics (wagi i valuation nietestowane jeszcze).

### 5. Auditability (protokół punkt 11)

Każdy z 5 realnych runów (+ wykluczony smoke-test) ma własny, niezmienny `calibration_result.db` artefakt (retencja 30 dni) z wierszem w `calibration_runs` (`status='candidate'`), zawierającym config (JSON), config hash, round=1, candidate_name, training_window, fold lata, sample size pooled+per-fold, primary+secondary metrics, timestamp/run_id — nic nie usunięte. Ponieważ każdy kandydat operuje na OSOBNEJ kopii bazy (brak jednej współdzielonej, działającej `calibration_runs` między runami), autorytatywnym, trwałym rekordem decyzji Round 1 jest TEN dokument + niezmienne logi GitHub Actions (run ID w tabelach wyżej) — `mark_calibration_winner` nie jest wywoływany na żadnym artefakcie (nie ma jednej bazy do zapisania flagi zwycięzcy; flaga zwycięzcy = ten zapis w design review).

GitHub Actions run ID → artifact (pełne logi, pełny `calibration_result.db` do pobrania):
- `baseline`: run [37313299445](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37313299445)
- `stricter_decline`: run [37313302649](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37313302649)
- `hard_gate_safety_floor`: run [37313307388](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37313307388)
- `prefilter_excludes`: run [37313310977](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37313310977)
- `combo_decline_and_prefilter`: run [37313315244](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37313315244)
- (wykluczony smoke-test, 3 CIK): run [37312834803](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37312834803)

### 6. ROUND 1 ZAMROŻONY

Zwycięzca: **`baseline`** (bez zmian). Żaden z testowanych wariantów selection mechanics (zaostrzone progi decline, hard gate na financial safety, promocja prefilter FLAG→EXCLUDE, ich kombinacja) nie pokonał baseline poza szumem fold-to-fold. Per protokół, ROUND 2 (COMPONENT WEIGHTS) może zacząć się teraz, bez dodatkowego pytania o zgodę. Holdout 2022–2026 pozostaje zablokowany.

---

## Faza 5.4b — ROUND 2: korekta metodologii primary metric (przed uruchomieniem jakiegokolwiek kandydata), zamrożone siatki wag, v1.51

**Zgoda właścicielki na start Round 2:** 2026-10-05. Zwycięzca Round 1 formalnie potwierdzony: `baseline` (zero zmian decline thresholds/hard gates/prefilter). `stricter_decline` (4/6 positive folds) zachowany w audycie jako obserwacja diagnostyczna — NIE wykorzystany w Round 2, nie zmienia decyzji Round 1. Run 37312834803 (`--sample=3`, smoke-test) pozostaje trwale wykluczony z każdej agregacji kalibracyjnej.

### 0. Znalezisko PRZED napisaniem jakiegokolwiek kodu Round 2 (zweryfikowane empirycznie, nie tylko przez czytanie kodu)

Primary metric Round 1 (`pooled_median_excess_return_pct` + fold stability, liczone WYŁĄCZNIE z `forward_returns`/`decision_date` kandydatów na etapie `CANDIDATE`) jest **matematycznie niezależny od wag scoringu** w obecnym harnessie — wagi (`financial_safety`/`dividend_shareholder_return`/`valuation`) nigdy nie filtrują, kto wchodzi do funnela; jedynym mechanizmem, przez który mogłyby to robić, są `hard_gates`, a te są zamrożone na `None` (zwycięzca Round 1). Zweryfikowane empirycznie na produkcyjnej `evaluate_candidate_at_date` (3 warianty wag safety/dividend: 15/10, 23/2, 2/23) — `stage`/`decision_price` identyczne we wszystkich trzech, różnią się wyłącznie wartości score. Zgłoszone właścicielce PRZED napisaniem kodu Round 2A/2B (nie uruchomiono żadnego kandydata) — decyzja: **zmiana primary metric WYŁĄCZNIE dla Round 2A/2B**, nie dotyka Round 1 (tam primary metric poprawnie reagowała na testowane parametry, bo decline/prefilter/hard gates REALNIE zmieniają populację funnela).

### 1. Nowa PRIMARY metric dla Round 2A i 2B (zastępuje `pooled_median_excess_return_pct` TYLKO w tych rundach)

**Spearman correlation: `deterministic_score_pct` vs forward excess return (6m, vs `equal_weighted_pit_universe`)**, liczona na obserwacjach OOS (2016–2021), tą samą populacją kandydatów dla wszystkich wariantów wag w danym foldzie. Interpretacja: wyższy score powinien wiązać się z wyższym przyszłym excess return. Raportowane: (A) pooled OOS Spearman, (B) Spearman per fold rok, (C) median fold Spearman, (D) min/max fold Spearman, (E) positive folds/total, (F) n pooled, (G) n per fold. Dotychczasowa metryka (`pooled_median_excess_return_pct`) nadal liczona i raportowana jako DIAGNOSTIC — nie decyduje o wyborze wag w Round 2.

Implementacja: `calibration.evaluate_candidate_configuration_spearman` (nowa funkcja, zero zmiany istniejącej `evaluate_candidate_configuration` używanej przez Round 1) — reużywa istniejące `_spearman_rho` (już używane jako SECONDARY diagnostic w Round 1, teraz staje się PRIMARY wyłącznie dla Round 2A/2B) i generyczną `practical_tie(a, b, epsilon)`.

### 2. Spearman practical-tie epsilon — metoda zamrożona TU, wartość zamrożona PO runie `default` każdej podrundy, PRZED porównaniem jakiegokolwiek innego kandydata

Epsilon Round 1 (2,1819 pp, skala median excess return) **NIE jest przenoszony** — inna metryka, inna skala. Metoda (analogiczna do Round 1, zastosowana do nowej metryki): `derive_practical_tie_epsilon_spearman` = `statistics.pstdev` Spearman-ów z 6 foldów OOS (2016–2021) kandydata `default` DANEJ PODRUNDY, policzone PRZED porównaniem jakiegokolwiek innego kandydata tej podrundy. Dwa osobne epsilony (różne populacje → różny poziom szumu):
- **epsilon_2A** — z `2a_default` (safety=15/dividend=10, pełna populacja partial model, jak Round 1).
- **epsilon_2B** — z `2b_default` (valuation_weight=20, WYŁĄCZNIE complete-valuation subset).

Wartości liczbowe obu epsilonów zostaną udokumentowane w kolejnym wpisie (Faza 5.4c), natychmiast po runie kandydatów `default`, PRZED spojrzeniem na wyniki pozostałych kandydatów — ta sama dyscyplina co w Round 1.

### 3. ROUND 2A — SAFETY + DIVIDEND/SHAREHOLDER RETURN, siatka ZAMROŻONA

Populacja: pełny partial model (ta sama co Round 1 — decline/prefilter/hard gates = zwycięzca Round 1, bez zmian). Zmieniana WYŁĄCZNIE relacja `financial_safety`/`dividend_shareholder_return`, suma stała = 25 (obecny budżet obu komponentów). `business_quality`=45, `valuation`=20, `fear_opportunity`=10 — przypięte do wartości domyślnych przez CAŁĄ Round 2A (zero zmiany valuation mechanics/DCF/MoS/growth caps/PIT/benchmarków — zgodnie z instrukcją).

| Kandydat | financial_safety | dividend_shareholder_return | Uzasadnienie |
|---|---|---|---|
| `2a_default` | 15 | 10 | obecna/domyślna konfiguracja (wymagana jako punkt odniesienia) |
| `2a_safety_heavy` | 20 | 5 | mocny przechył w stronę bezpieczeństwa finansowego (80/20 w ramach 25 pkt) |
| `2a_dividend_heavy` | 10 | 15 | mocny przechył w stronę dywidendy/zwrotu dla akcjonariuszy (40/60) |
| `2a_balanced` | 12,5 | 12,5 | punkt środkowy (50/50) |

### 4. ROUND 2B — VALUATION WEIGHT, siatka ZAMROŻONA

Populacja: WYŁĄCZNIE complete-valuation subset (`margin_of_safety_base_pct is not None`) — identyczna dla każdego wariantu wag w tej podrundzie (dostępność wyceny jest własnością DANYCH, nie wagi — zweryfikowane: `valuation_weight` skaluje wynik, nie bramkuje dostępności). `financial_safety`=15, `dividend_shareholder_return`=10 przypięte do wartości domyślnych przez CAŁĄ Round 2B (żeby zmiana wagi valuation nie mieszała się nierozłącznie ze zmianą znaczenia safety/dividend). Punkty oddawane/pobierane WYŁĄCZNIE z `business_quality` (komponent inercyjny w trybie deterministycznym/backtest — `business_quality`/`fear` są zawsze `None` bez LLM, więc nie wchodzą do `deterministic_score_pct` ani jego mianownika; przesunięcie budżetu między `valuation` a `business_quality` nie zmienia rankingu w tej rundzie, ale zachowuje inwariant `ScoringWeights` sumujący się do 100 — wymóg pydantic). `fear_opportunity`=10 przypięte bez zmian.

| Kandydat | valuation | business_quality (kompensuje) | financial_safety | dividend_shareholder_return | fear_opportunity |
|---|---|---|---|---|---|
| `2b_valuation_0` (CONTROL) | 0 | 65 | 15 | 10 | 10 |
| `2b_valuation_low` | 10 | 55 | 15 | 10 | 10 |
| `2b_default` | 20 | 45 | 15 | 10 | 10 |
| `2b_valuation_high` | 30 | 35 | 15 | 10 | 10 |

Najważniejsze porównanie: `2b_valuation_0` vs `2b_default` (i pozostałe >0) na DOKŁADNIE tych samych company-date observations — odpowiada na pytanie, czy włączenie valuation do score poprawia uporządkowanie kandydatów względem późniejszego wyniku, względem samego safety+dividend. Nigdy nie porównywane z pełnym partial universe (to pomieszałoby efekt valuation z selection/coverage bias — zasada z punktu 10 głównego protokołu).

### 5. Zasady decyzyjne (niezmienione z zatwierdzonego protokołu, zastosowane do nowej metryki)

Decyzje 2A i 2B podejmowane OSOBNO (zero mieszania populacji/wyników). W obu: `practical_tie(default, candidate, epsilon_2X)` na pooled Spearman; remis → wygrywa prostsza konfiguracja (= `default`, czyli brak zmiany wag). Epsilon nie jest przeliczany po zobaczeniu wyników pozostałych kandydatów. Hard gates NIE wracają jako sposób na nadanie wagom wpływu na starą metrykę — Round 1 pozostaje zamknięty bez zmian.

### 6. Status

Primary metric zmieniona (punkt 1), metoda epsilon zamrożona (punkt 2, wartości liczbowe w Faza 5.4c), siatki 2A i 2B zamrożone (punkty 3–4) — WSZYSTKIE PRZED uruchomieniem jakiegokolwiek kandydata Round 2. Holdout 2022–2026 nietknięty. Implementacja (kod + testy) i uruchomienie — patrz Faza 5.4c.

---

## Faza 5.4c — ROUND 2A/2B: epsilon zamrożony, wyniki, decyzje, v1.52

**Wykonanie:** implementacja (`calibration.evaluate_candidate_configuration_spearman`/`derive_practical_tie_epsilon_spearman`, `calibration_round2a.py`, `calibration_round2b.py`, rozszerzenie `db.py`/`cli.py`/workflow) — 16 nowych testów, 573 passed, zero regresji Round 1 (zweryfikowane lokalnym smoke testem `--round 1` przed pushem). 8 dispatchów `phase5-4-calibration-candidate.yml` (2026-10-05, ~14:07–14:19 UTC), pełny 615-CIK universe, okno kalibracyjne HARDKODOWANE 2012-01-01→2021-12-01, holdout 2022–2026 fizycznie niedostępny z tego workflow. Wszystkie 8 statusów = `success`.

### 1. Epsilon_2A i epsilon_2B — zamrożone z `default` KAŻDEJ podrundy, PRZED porównaniem pozostałych kandydatów tej podrundy

**epsilon_2A** = `pstdev` 6 fold-Spearmanów `2a_default` (populacja FULL_PARTIAL_MODEL, pooled n=5834 — identyczne z pooled n baseline Round 1, potwierdza że populacja jest niezależna od wag, zgodnie z Faza 5.4b punkt 0):

| Fold | n | Spearman |
|---|---|---|
| 2016 | 879 | −0,06255 |
| 2017 | 481 | 0,06794 |
| 2018 | 741 | 0,00053 |
| 2019 | 1042 | 0,04185 |
| 2020 | 2113 | 0,07586 |
| 2021 | 578 | 0,03338 |

**epsilon_2A = 0,046617 — ZAMROŻONE.**

**epsilon_2B** = `pstdev` 6 fold-Spearmanów `2b_default` (populacja COMPLETE_VALUATION_SUBSET, pooled n=1111 — identyczne dla wszystkich 4 kandydatów 2B, potwierdza że dostępność wyceny jest własnością danych, nie wagi):

| Fold | n | Spearman |
|---|---|---|
| 2016 | 177 | −0,16878 |
| 2017 | 108 | −0,12912 |
| 2018 | 138 | −0,03401 |
| 2019 | 229 | 0,08490 |
| 2020 | 365 | 0,13285 |
| 2021 | 94 | 0,22119 |

**epsilon_2B = 0,140350 — ZAMROŻONE.** (znacznie większy niż epsilon_2A — mniejsza populacja (n≈1111 vs 5834) i dużo większa rozpiętość fold-to-fold: skrajnie ujemne 2016/2017 vs skrajnie dodatnie 2020/2021, patrz punkt 5).

Oba zweryfikowane bezpośrednio funkcją produkcyjną `derive_practical_tie_epsilon_spearman`.

### 2. Pełne wyniki Round 2A (PRIMARY: Spearman(deterministic_score_pct, forward return 6m), populacja FULL_PARTIAL_MODEL, n pooled=5834 dla WSZYSTKICH 4 kandydatów)

| Kandydat | financial_safety/dividend | Pooled Spearman | n_positive_folds | median_of_fold_spearman | min/max fold |
|---|---|---|---|---|---|
| `2a_default` | 15/10 | 0,07348 | 5/6 | 0,03762 | −0,06255 / 0,07586 |
| `2a_safety_heavy` | 20/5 | 0,05644 | 3/6 | 0,01597 | −0,08896 / 0,08998 |
| `2a_dividend_heavy` | 10/15 | 0,08000 | 4/6 | 0,05061 | −0,03796 / 0,10460 |
| `2a_balanced` | 12,5/12,5 | 0,07965 | 5/6 | 0,05367 | −0,04476 / 0,07542 |

### 3. Decyzja Round 2A

|Δ pooled Spearman vs `2a_default`| vs epsilon_2A=0,046617, funkcją produkcyjną `practical_tie`:

| Kandydat | Δ vs default | `practical_tie` |
|---|---|---|
| `2a_safety_heavy` | 0,017037 | **TIE** |
| `2a_dividend_heavy` | 0,006523 | **TIE** |
| `2a_balanced` | 0,006173 | **TIE** |

**WSZYSTKIE 3 warianty są statystycznym remisem z `2a_default`.** Per zamrożona reguła ("remis → wygrywa prostsza konfiguracja" = brak zmiany względem obecnej produkcyjnej wagi): **ZWYCIĘZCA ROUND 2A = `2a_default`** (`financial_safety`=15/`dividend_shareholder_return`=10, bez zmian).

### 4. Pełne wyniki Round 2B (PRIMARY: Spearman(deterministic_score_pct, forward return 6m), populacja COMPLETE_VALUATION_SUBSET, n pooled=1111 dla WSZYSTKICH 4 kandydatów)

| Kandydat | valuation/business_quality | Pooled Spearman | n_positive_folds | median_of_fold_spearman | min/max fold |
|---|---|---|---|---|---|
| `2b_valuation_0` (CONTROL) | 0/65 | 0,06152 | 1/6 | −0,03418 | −0,14213 / 0,22563 |
| `2b_valuation_low` | 10/55 | 0,10720 | 3/6 | 0,00095 | −0,19727 / 0,21308 |
| `2b_default` | 20/45 | 0,11308 | 3/6 | 0,02544 | −0,16878 / 0,22119 |
| `2b_valuation_high` | 30/35 | 0,11656 | 3/6 | 0,03990 | −0,14642 / 0,20534 |

### 5. Decyzja Round 2B

|Δ pooled Spearman vs `2b_default`| vs epsilon_2B=0,140350:

| Kandydat | Δ vs default | `practical_tie` |
|---|---|---|
| `2b_valuation_0` | 0,051563 | **TIE** |
| `2b_valuation_low` | 0,005882 | **TIE** |
| `2b_valuation_high` | 0,003478 | **TIE** |

**WSZYSTKIE 3 warianty (w tym CONTROL `valuation_0`) są statystycznym remisem z `2b_default`.** Mimo że pooled Spearman monotonicznie rośnie z wagą valuation (0,062 → 0,107 → 0,113 → 0,117), różnica nawet między skrajami (0→30) jest mniejsza niż epsilon_2B — **nie da się odróżnić tego trendu od szumu fold-to-fold na tej populacji (n=1111, silnie niestabilnej między latami, patrz punkt 1)**. Per zamrożona reguła: **ZWYCIĘZCA ROUND 2B = `2b_default`** (`valuation`=20/`business_quality`=45, bez zmian). Uwaga terminologiczna: "prostsza konfiguracja" = brak zmiany względem obecnej produkcyjnej wagi (konwencja ustalona w Round 1 i 2A) — NIE `2b_valuation_0`, bo aktywne wyzerowanie wagi jest modyfikacją, nie stanem bazowym.

**Odpowiedź na pytanie Round 2B** ("czy valuation poprawia uporządkowanie kandydatów względem późniejszego wyniku"): na obecnej próbie (n=1111, 2016–2021) — **nie w sposób odróżnialny od szumu**, choć kierunek obserwacji (wyższa waga → wyższy pooled Spearman) jest spójny z hipotezą, że valuation niesie pewien sygnał. Nie jest to potwierdzenie ani zaprzeczenie — jest to brak mocy statystycznej do rozstrzygnięcia na tym etapie.

### 6. Finalny config hash po Round 2

Zwycięzcy obu podrund (`2a_default`, `2b_default`) oznaczają **zero zmian** względem configu produkcyjnego sprzed Round 2 (identycznego z configem Round 1 — `baseline` tam też nie zmienił wag). Finalna, efektywna konfiguracja po Round 1+2A+2B = **dokładnie `config/config.yaml` bez modyfikacji**:

`config_hash = config.yaml:9553e5c9f27ac673` (SHA256[:16] treści pliku na dysku w momencie tego zapisu — ta sama wartość co w `calibration_runs.config_hash` dla wszystkich 13 kandydatów Round 1+2A+2B, bo żaden kandydat nie modyfikuje pliku na dysku, tylko głęboką kopię w pamięci).

### 7. Anomalie / coverage issues

- **Brak anomalii PIT/identity/double-counting.** `n_total_candidates`=7847 identyczne dla wszystkich 8 runów (ten sam funnel co Round 1 `baseline`) — oczekiwane, bo Round 2 nie zmienia `decline_scanner`/`prefilter`/`hard_gates`.
- **Pooled n invariant względem wag w obu podrundach** (5834 dla 2A, 1111 dla 2B) — to NIE jest błąd, to oczekiwany, zweryfikowany skutek architektury (Faza 5.4b punkt 0): wagi scoringu nigdy nie filtrują populacji, tylko ją opisują/rankują. Pozytywny sanity check: gdyby te liczby różniły się między kandydatami tej samej podrundy, byłby to sygnał błędu w izolacji configu.
- **COMPLETE_VALUATION_SUBSET (n=1111) to 19,04% populacji FULL_PARTIAL_MODEL (n=5834)** na obserwacjach OOS 2016–2021 — rząd wielkości zgodny z wcześniej zmierzonym ~18,5% (Faza 5.3g, cały backtest 2012–2026) — brak rozbieżności wymagającej wyjaśnienia.
- **Duża rozpiętość fold-to-fold w Round 2B** (2016/2017 silnie ujemne [−0,13 do −0,20] vs 2020/2021 silnie dodatnie [0,09 do 0,22], w KAŻDYM z 4 wariantów wagi) — to dlatego epsilon_2B (0,140) jest ~3x większy niż epsilon_2A (0,047). Zanotowane jako obserwacja do rozważenia w przyszłości (np. czy to efekt reżimu rynkowego, czy małej próby per rok) — **nie zmienia decyzji Round 2B**, bo epsilon został zamrożony z dokładnie tych danych PRZED porównaniem innych kandydatów.
- Wszystkie foldy (2A i 2B, wszyscy kandydaci) mają `low_sample=False` (najmniejszy fold: 2021 w 2B, n=94 ≥ 30) — brak kandydatów do automatycznego odrzucenia, zgodnie z zasadą "LOW_SAMPLE nigdy nie odrzuca automatycznie" (tu nawet nieaktywowane).

### 8. Auditability

Jak w Round 1 (protokół punkt 11) — każdy z 8 runów ma własny `calibration_result.db` artefakt (retencja 30 dni) z wierszem w `calibration_runs` (kolumny `subround`/`population`/`pooled_spearman`/fold-spearman stats, `status='candidate'`), nic nie usunięte. `mark_calibration_winner` nie wywoływany z tego samego powodu co w Round 1 (brak jednej współdzielonej bazy między runami) — ten zapis w design review jest autorytatywnym rekordem.

GitHub Actions run ID → artifact:
- `2a_default`: run [37322125873](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322125873)
- `2a_safety_heavy`: run [37322134009](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322134009)
- `2a_dividend_heavy`: run [37322139428](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322139428)
- `2a_balanced`: run [37322145672](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322145672)
- `2b_valuation_0`: run [37322149954](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322149954)
- `2b_valuation_low`: run [37322154697](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322154697)
- `2b_default`: run [37322159064](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322159064)
- `2b_valuation_high`: run [37322163268](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37322163268)

### 9. ROUND 2 ZAMROŻONY

Zwycięzcy: **`2a_default`** i **`2b_default`** — zero zmian wag scoringu względem produkcyjnego configu. Połączone z zamrożonym Round 1 (`baseline`): **cała Faza 5.4 (Round 1+2A+2B) nie zmieniła żadnego parametru produkcyjnego** — każda testowana interwencja (selection mechanics, safety/dividend split, valuation weight) okazała się nieodróżnialna od szumu fold-to-fold na danych kalibracyjnych 2012–2021. Zgodnie z instrukcją właścicielki: **Round 3 NIE jest rozpoczynany w tym kroku.** Holdout 2022–2026 pozostaje całkowicie zablokowany.

---

## Faza 5.4d — ROUND 3: VALUATION ROBUSTNESS / SENSITIVITY ANALYSIS (nie optimization), v1.53

**Zmiana celu Round 3 (decyzja właścicielki 2026-10-05, formalnie zatwierdzona po zamknięciu Round 2 "zero zmian"):** Round 3 NIE jest parameter search po forward returns. Cel: sprawdzić, czy silnik wyceny (`mos_pct_for_full_score`, growth caps) jest STABILNY przy rozsądnych, z góry zamrożonych zmianach założeń — nie znaleźć wartości maksymalizujące historyczny wynik. `discount_rate`/`terminal_growth`/`historical_growth_multiplier`/`projection_years`/scoring weights/selection mechanics/hard gates/PIT/total_debt methodology — wszystkie nietknięte.

### 1. Zamrożona siatka (PRZED jakimkolwiek runem, `buffett_scanner.calibration_round3.ROUND_3_CANDIDATES`, TRWAŁY zapis audytowy)

| Kandydat | mos_pct_for_full_score | max/min growth cap | Uzasadnienie |
|---|---|---|---|
| `3_default` | 50,0 | 20,0 / −5,0 | obecna/domyślna — punkt odniesienia w środku siatki |
| `3_mos_low` | 35,0 | 20,0 / −5,0 (bez zmian) | domyślne −15pp |
| `3_mos_high` | 65,0 | 20,0 / −5,0 (bez zmian) | domyślne +15pp |
| `3_caps_narrow` | 50,0 (bez zmian) | 15,0 / −3,0 | węższy pas bezpieczeństwa projekcji wzrostu |
| `3_caps_wide` | 50,0 (bez zmian) | 25,0 / −7,0 | szerszy pas bezpieczeństwa projekcji wzrostu |

Wykonanie: jednorazowy skrypt diagnostyczny (`scripts/diag_round3_valuation_sensitivity.py`, usunięty po wyciągnięciu wyników — ten sam wzorzec co wcześniejsze diagnostyki w tym projekcie), jeden run GitHub Actions na pełnym 615-CIK universe, okno kalibracyjne 2012-01-01→2021-12-01, holdout 2022–2026 fizycznie niedostępny. Funnel (decline/prefilter/hard gates) policzony RAZ pod `3_default` — zweryfikowane, że nie czyta `valuation.dcf_owner_earnings` (ta sama architektura co w Faza 5.4b/5.4c dla wag scoringu) — pozostałe 4 warianty liczone WYŁĄCZNIE przez kanoniczną `compute_deterministic_score` na tych samych periods/cenie. `n_total_candidates`=7847 (identyczne z Round 1/2A) — potwierdza niezależność populacji od valuation sub-configu. Complete-valuation subset (pełne okno 2012–2021) = **1460** obserwacji.

Score/rank/classification/valuation-output stability (punkty 2–5 niżej) liczone na **PEŁNYM** oknie kalibracyjnym 2012–2021 (nie tylko OOS 2016–2021) — to diagnostyka silnika wyceny, nie wybór konfiguracji po forward returns, więc większa próbka jest właściwsza. Forward-return diagnostics (punkt 6) pozostają restricted do OOS 2016–2021, zgodnie z konwencją reszty projektu.

### 2. A. Score stability (`valuation_score` vs `3_default`, complete-valuation subset, n=1460)

| Kandydat | Spearman(default,variant) | median \|Δ\| | p50/p75/p90/p95/max | % obs. z \|Δ\|>2,0 pkt |
|---|---|---|---|---|
| `3_mos_low` | 0,9740 | 0,0 | 0,0 / 0,12 / 4,00 / 5,12 / 5,99 | 18,0% |
| `3_mos_high` | 0,9857 | 0,0 | 0,0 / 1,51 / 3,54 / 4,07 / 4,61 | 22,7% |
| `3_caps_narrow` | 0,9756 | 0,0 | 0,0 / 0,0 / 0,0 / 5,68 / 17,06 | 7,7% |
| `3_caps_wide` | 0,9812 | 0,0 | 0,0 / 0,0 / 0,0 / 0,64 / 19,20 | 4,2% |

Korelacja rang bardzo wysoka (0,97–0,99) we wszystkich 4 wariantach. Mediana zmiany = 0 (większość obserwacji ma MoS albo ≤0 — score=0 w obu — albo powyżej `mos_pct_for_full_score` — score=max w obu, więc zmiana parametru nic nie zmienia). Udział "dużych zmian" (próg opisowy, NIE decyzyjny: >2,0 pkt = 10% budżetu wagi valuation=20) wyższy dla `mos_pct_for_full_score` (18–23%, bo skaluje WSZYSTKIE przypadki pośrednie) niż dla growth caps (4–8%, bo wiążą tylko dla mniejszości spółek z CAGR poza pasem) — kierunkowo zgodne z mechanizmem konstrukcji, nie anomalia.

### 3. B. Rank stability (`deterministic_score_pct` ranking per decision_date vs `3_default`, pełne okno, 119 dat z ≥3 kandydatami)

| Kandydat | median | min | max | najbardziej niestabilna data |
|---|---|---|---|---|
| `3_mos_low` | 0,9986 | 0,9838 | 1,0000 | 2018-01-01 |
| `3_mos_high` | 0,9987 | 0,9893 | 1,0000 | 2012-02-01 |
| `3_caps_narrow` | 1,0000 | 0,9195 | 1,0000 | 2017-01-01 |
| `3_caps_wide` | 1,0000 | 0,9489 | 1,0000 | 2016-06-01 |

Mediana rankingu praktycznie niezmieniona (0,999–1,000) we wszystkich 4 wariantach. **Nawet najgorsza data dla najgorszego wariantu (`3_caps_narrow`, 2017-01-01) ma Spearman=0,9195** — silna korelacja, nie zapadnięcie rankingu. Brak dowodu niestabilności.

### 4. C. Classification stability (próg MoS≤0 → `valuation_score`=0, complete-valuation subset, n=1460)

Uwaga: `hard_gates.min_margin_of_safety_pct`=`None` (nieaktywny) w produkcyjnym configu — jedyny ŻYWY próg to floor MoS≤0 w `valuation_score`.

| Kandydat | przekroczeń progu | % |
|---|---|---|
| `3_mos_low` | 0/1460 | 0,0% |
| `3_mos_high` | 0/1460 | 0,0% |
| `3_caps_narrow` | 34/1460 | 2,33% |
| `3_caps_wide` | 8/1460 | 0,55% |

**0,0% dla obu wariantów `mos_pct_for_full_score`** — zgodne z architekturą z konstrukcji: ten parametr skaluje mapowanie MoS→punkty, nigdy nie zmienia samego MoS (zweryfikowane empirycznie, dokładnie jak przewidziano przed runem — pozytywny sanity check, nie znalezisko). Growth caps mają niewielki, ale niezerowy wpływ (2,33%/0,55%) — zwężenie pasa (silniejsza ingerencja w ekstremalne projekcje) powoduje więcej przekroczeń niż rozszerzenie, kierunkowo sensowne.

### 5. D. Valuation-output stability (bear/base/bull intrinsic value + MoS, complete-valuation subset, pełne okno)

We WSZYSTKICH 4 wariantach i WSZYSTKICH 3 scenariuszach: **median_|Δintrinsic_value|%=0,0 i median_|ΔMoS|_pp=0,0** — dla typowej (medianowej) obserwacji growth caps/`mos_pct_for_full_score` nie zmieniają wyceny wcale. Zgodne z punktem 2: zmiana wiąże tylko dla mniejszości spółek (ogon rozkładu, patrz percentyle w punkcie 2) — to zamierzone zachowanie "pasa bezpieczeństwa", nie usterka. 35/1460 obserwacji ma scenariusz BEAR z nie-dodatnim intrinsic value pod `3_default` (poprawnie wykluczone z % calc, nie dzielenie przez zero/ujemną liczbę).

### 6. Forward-return diagnostics (TYLKO diagnostyczne — NIGDY nie użyte do wyboru parametrów, OOS 2016–2021)

| Kandydat | Spearman (full population, n=5834) | Spearman (complete-valuation subset, n=1111) | median_excess (diagnostic) |
|---|---|---|---|
| `3_default` | 0,0735 | 0,1131 | 0,7608% |
| `3_mos_low` | 0,0741 | 0,1194 | 0,7608% |
| `3_mos_high` | 0,0745 | 0,1167 | 0,7608% |
| `3_caps_narrow` | 0,0769 | 0,1258 | 0,7608% |
| `3_caps_wide` | 0,0734 | 0,1130 | 0,7608% |

Wszystkie 5 wariantów w wąskim paśmie (full population: 0,073–0,077; complete-valuation: 0,113–0,126) — **wniosek Round 2B ("trend nieodróżnialny od szumu na n=1111") jest jakościowo STABILNY pod rozsądnymi zmianami założeń wyceny — żaden wariant nie wypycha korelacji poza zakres zaobserwowany w Round 2B, żaden nie zmienia znaku.** `median_excess_return_pct` identyczny (0,7608%) we wszystkich 5 — oczekiwane: ta metryka zależy wyłącznie od tego, KTO przechodzi funnel (niezmienne) i cen (niezależne od valuation sub-configu), nie od indywidualnych score'ów.

### 7. Anomalie

Brak znaleziska wymagającego naprawy. Wszystkie obserwowane wzorce są wewnętrznie spójne z udokumentowaną architekturą silnika:
- `mos_pct_for_full_score` wpływa WYŁĄCZNIE na `valuation_score` (potwierdzone: 0% przekroczeń progu MoS, 0% zmiany intrinsic value/MoS) — nigdy na samą wycenę.
- Growth caps wpływają na obie warstwy (score i wycenę), proporcjonalnie do rozmiaru interwencji i tylko dla mniejszości spółek z ekstremalną historyczną CAGR.
- Żaden pojedynczy parametr nie dominuje nieproporcjonalnie — efekty są ograniczone budżetem punktowym (score) i logiką Gordona (wycena), zgodnie z projektem.
- Brak nieciągłości, brak "skoków" rankingu, brak przypadków nielogicznego zachowania (np. zwiększenie `mos_pct_for_full_score` nigdy nie zwiększa score'u — sprawdzone pośrednio przez monotoniczność kierunku zmian).

### 8. Rekomendacja (do decyzji właścicielki — nie zmieniam configu produkcyjnego)

Na podstawie score/rank/classification/valuation-output stability (punkty 2–5) oraz jakościowej stabilności forward-return diagnostics (punkt 6): **Opcja A — domyślna mechanika wyceny (`mos_pct_for_full_score`=50, growth caps=20/−5) wydaje się bezpieczna do zamrożenia jako final config przed holdoutem.** Nie znaleziono: ekstremalnej niestabilności (najgorszy przypadek rank correlation = 0,92, nie zapadnięcie), nieciągłości scoringu, nielogicznego zachowania, błędu implementacyjnego, ani nieproporcjonalnej dominacji jednego parametru. To obserwacja z tej analizy, nie decyzja — decyzję o zamrożeniu finalnego configu i otwarciu holdoutu podejmuje właścicielka.

Holdout 2022–2026 pozostaje całkowicie zablokowany. Final holdout evaluation NIE jest uruchomiony w tym kroku.

---

## Faza 5.5 — FINAL PRE-HOLDOUT CONFIG (ZAMROŻONY, przed otwarciem holdoutu), v1.54

**Decyzja właścicielki (2026-10-05): OPCJA A zatwierdzona.** Round 3 nie wykazał problemu metodologicznego uzasadniającego zmianę default valuation mechanics. Niniejszym zamrażam konfigurację produkcyjną jako FINAL PRE-HOLDOUT CONFIG — **od tego momentu żaden parametr nie może być zmieniony na podstawie wyników holdoutu 2022–2026.**

**Oznaczenie jednoznaczne:** `FINAL_PRE_HOLDOUT_CONFIG_v1` — wybrana i zamrożona PRZED jakimkolwiek spojrzeniem na dane 2022–2026.

- **Wersja dokumentu:** v1.54
- **Config hash:** `config.yaml:9553e5c9f27ac673`
- **Commit SHA (branch `claude/buffett-scanner-design-review-mrud89`):** `f20efe94675eca8fbda15699f6ffa8048497e7e8`
- **Data zamrożenia:** 2026-10-05

**Pełna specyfikacja (= dokładnie `config/config.yaml` bez modyfikacji, wynik Round 1+2A+2B+3 = zero zmian):**

| Sekcja | Parametr | Wartość |
|---|---|---|
| `decline_scanner.thresholds` | daily/week/month/quarter/drawdown/volume | −5,0 / −8,0 / −15,0 / −20,0 / −25,0 / 2,0x (Round 1 `baseline`) |
| `prefilter` | exclude_rules | `[]` (tylko FLAG rules, Round 1 `baseline`) |
| `hard_gates` | min_business_quality / min_financial_safety / min_margin_of_safety_pct | `None` / `None` / `None` (wszystkie nieaktywne) |
| `scoring.weights` | business_quality / financial_safety / valuation / fear_opportunity / dividend_shareholder_return | 45 / 15 / 20 / 10 / 10 (Round 2A/2B `default`) |
| `valuation.dcf_owner_earnings` | discount_rate_pct (bear/base/bull) | 11,0 / 9,0 / 7,0 (nietknięte, założenia inwestora) |
| `valuation.dcf_owner_earnings` | terminal_growth_rate_pct (bear/base/bull) | 1,0 / 2,5 / 3,5 (nietknięte) |
| `valuation.dcf_owner_earnings` | historical_growth_multiplier (bear/base/bull) | 0,5 / 1,0 / 1,3 (nietknięte) |
| `valuation.dcf_owner_earnings` | max/min_projected_growth_rate_pct (growth caps) | 20,0 / −5,0 (Round 3 `3_default`) |
| `valuation.dcf_owner_earnings` | mos_pct_for_full_score | 50,0 (Round 3 `3_default`) |

**Jawne stwierdzenie wymagane przez protokół:** FINAL PRE-HOLDOUT CONFIG jest **identyczny** z configiem, który istniał PRZED rozpoczęciem Fazy 5.4 (przed Round 1). Trzy pełne rundy kalibracji (selection mechanics, component weights, valuation sensitivity) **nie zmieniły ani jednego parametru produkcyjnego** — każda testowana interwencja okazała się albo statystycznym remisem z domyślną konfiguracją (Round 1/2A/2B, w granicach zamrożonych epsilon), albo nie wykazała problemu metodologicznego uzasadniającego zmianę (Round 3). Holdout 2022–2026 oceni więc **oryginalną metodologię, wybraną niezależnie od danych holdoutu** — nie "model po kalibracji". Interpretacja wyniku holdoutu musi to odzwierciedlać: `calibration did not justify changing the original model; holdout evaluates the original methodology selected independently of holdout data.`

**Od tego punktu:** żadna zmiana `weights`/`hard_gates`/`prefilter`/`decline_scanner.thresholds`/`mos_pct_for_full_score`/growth caps/DCF assumptions/benchmark definitions/selection mechanics nie jest dozwolona na podstawie wyników holdoutu. Holdout 2022–2026 otwierany **JEDNORAZOWO**, bez żadnego searchu/kalibracji na tych danych — patrz Faza 5.6 (FINAL HOLDOUT EVALUATION).

---

## Faza 5.6 — FINAL HOLDOUT EVALUATION (2022–2026, JEDNORAZOWE OTWARCIE), v1.55

**To jest jedyne spojrzenie na dane 2022–2026 w całym procesie.** Wykonane RAZ, bez żadnego searchu/kalibracji/wyboru konfiguracji na tych danych. Po tym raporcie: STOP — zero zmian kodu scoringu/wyceny/configu, zero nowej rundy kalibracji (punkt 10).

### 1. Data / integrity

- **Final config hash:** `config.yaml:9553e5c9f27ac673` (identyczny z `FINAL_PRE_HOLDOUT_CONFIG_v1`, Faza 5.5).
- **Commit SHA:** `c6d7e357e63fd5508e994e3009a3a3df7f4a22a1` (commit, który zamroził final config — checked out dla tego runu).
- **Zakres dat holdoutu:** 2022-01-01 → 2026-10-01 (window_end=dziś, zgodnie z `HOLDOUT_WINDOW_END=None` z `calibration.py`).
- **Liczba decision dates:** 58 (miesięczne).
- **PIT integrity:** ten sam, już zweryfikowany silnik walk-forward (`run-baseline-walk-forward`, Faza 5.3c) — zero zmian logiki PIT względem Round 1–3.
- **Universe coverage:** 615 CIK, suma obserwacji PIT universe=27 887, przeskanowanych=27 361, coverage=**98,11%** (min/median/max per-date: 97,2% / 97,9% / 99,0%).
- **Candidate count:** **7809** (funnel: NO_DECLINE_SIGNAL=19 552, EXCLUDED_BY_PREFILTER=0, HARD_GATE_FAILED=0, CANDIDATE=7809 — zero wykluczeń przez prefilter/hard gates, zgodnie z zamrożoną konfiguracją Round 1 `baseline`).
- **Potwierdzenie braku użycia danych 2022–2026 w kalibracji:** `calibration.py` hardkoduje `CALIBRATION_WINDOW_END="2021-12-01"` — fizycznie niedostępne z `run-calibration-candidate` (Round 1/2A/2B). Round 3 (robustness analysis) również ograniczony do okna 2012–2021. Ten holdout run (GitHub Actions [37346815021](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37346815021)) jest PIERWSZYM i JEDYNYM dotknięciem danych 2022–2026 w tym procesie.

### 2. Full/partial population — final frozen model

| Horyzont | n (vs EW) | median excess vs EW | median excess vs SPY | hit rate vs EW | hit rate vs SPY | Spearman(score, excess vs EW) |
|---|---|---|---|---|---|---|
| 1m | 7602 | −0,55% | −0,48% | 47,13% | 47,50% | 0,0191 |
| 3m | 7222 | −0,59% | −1,03% | 48,53% | 47,43% | 0,0312 |
| **6m (PRIMARY)** | 6689 | **−2,30%** | −4,19% | 45,24% | 42,53% | 0,0582 |
| 12m | 5814 | −3,30% | −8,49% | 45,61% | 39,31% | 0,0500 |

**Per rok (6m vs EW):**

| Rok | n | median excess | hit rate | Spearman |
|---|---|---|---|---|
| 2022 | 2130 | −1,38% | 46,71% | 0,0860 |
| 2023 | 1404 | −1,47% | 46,51% | 0,0421 |
| 2024 | 1043 | −4,43% | 40,75% | 0,0203 |
| 2025 | 1632 | −2,57% | 46,14% | 0,0681 |
| 2026* | 480 | −5,89% | 41,67% | 0,0137 |

*2026 częściowy (do 2026-10-01).

### 3. Complete-valuation subset — paired WITHOUT vs WITH valuation (identyczne n=1429 obserwacji)

**B) final score WITH valuation (produkcyjny, persystowany):**

| Horyzont | n | median excess vs EW | median excess vs SPY | hit rate vs EW | hit rate vs SPY | Spearman WITH |
|---|---|---|---|---|---|---|
| 1m | 1373 | −0,23% | −0,03% | 48,94% | 49,89% | 0,0161 |
| 3m | 1291 | +0,03% | −0,39% | 50,12% | 48,72% | 0,0299 |
| **6m** | 1188 | −0,29% | −2,12% | 49,49% | 45,85% | **0,0311** |
| 12m | 1032 | +0,12% | −4,45% | 50,10% | 43,91% | 0,0203 |

**A) score WITHOUT valuation (identyczne obserwacje, tylko safety+dividend, czysta arytmetyka z persystowanych pól — zero ponownego liczenia pipeline'u):**

| Horyzont | n | Spearman WITHOUT |
|---|---|---|
| 1m | 1373 | 0,0532 |
| 3m | 1291 | 0,1057 |
| **6m** | 1188 | **0,1347** |
| 12m | 1032 | 0,1153 |

**Na WSZYSTKICH 4 horyzontach, na identycznych obserwacjach: Spearman WITHOUT valuation > Spearman WITH valuation.** Per rok (6m): WITHOUT (2022=0,217 / 2023=0,064 / 2024=−0,071 / 2025=0,169 / 2026=0,188) vs WITH (2022=−0,005 / 2023=0,023 / 2024=−0,011 / 2025=0,123 / 2026=−0,053) — WITHOUT wyższy lub porównywalny w 4 z 5 lat. **Wniosek czystego OOS testu na niewidzianych danych: valuation NIE wnosi informacji rankingowej na holdoucie — wręcz jej nieznacznie zmniejsza, konsystentnie z (i silniej niż) znaleziskiem Round 2B na danych kalibracyjnych.**

### 4. Original uncalibrated baseline

**Jawne stwierdzenie wymagane przez protokół:** final frozen config jest **identyczny** z configiem sprzed Fazy 5.4 (zero zmian po Round 1+2A+2B+3, Faza 5.5). Nie istnieje osobny "model po kalibracji" do porównania — ten holdout run OCENIA ORYGINALNĄ METODOLOGIĘ, wybraną niezależnie od danych holdoutu. Prawidłowa interpretacja: **calibration did not justify changing the original model; holdout evaluates the original methodology selected independently of holdout data.** Żadna narracja o "poprawie po kalibracji" nie ma zastosowania — nie była tworzona.

### 5. Benchmarki

Oba zamrożone benchmarki użyte bez zmiany konwencji: **PRIMARY** `equal_weighted_pit_universe` (średnia forward return wszystkich spółek PIT universe z wystarczającymi cenami danego dnia), **SECONDARY** `SPY` (ta sama konwencja forward price return bez dywidend co kandydaci). Candydaci radzą sobie SŁABIEJ względem SPY niż względem EW na każdym horyzoncie (np. 6m: −4,19% vs SPY, −2,30% vs EW) — SPY wyraźnie przewyższał zarówno kandydatów, jak i szerokie PIT universe w tym okresie.

### 6. Calibration internal OOS (2016–2021) vs Final Holdout (2022–2026) — opisowo, NIE do ponownego strojenia

| Metryka | Calibration OOS 2016–2021 | Holdout 2022–2026 |
|---|---|---|
| Pooled median excess (6m vs EW) | **+0,76%** (n=5834) | **−2,30%** (n=6689) |
| Pooled Spearman, full population (6m) | 0,0735 (n=5834) | 0,0582 (n=6689) |
| Pooled Spearman, complete-valuation subset (6m) | 0,1131 (n=1111) | 0,0311 (n=1188) |
| Fold/rok median excess (6m vs EW), min…max | −2,43% … +3,33% (3 ujemne, 3 dodatnie z 6 lat) | −5,89% … −1,38% (**5 ujemnych z 5 lat, ZERO dodatnich**) |

**Kierunek:** primary metric (median excess 6m vs EW) zmienia znak z dodatniego na ujemny. **Wielkość:** zmiana ~3 pp, w kierunku gorszym. **Stabilność między latami:** w kalibracji rok-do-roku wynik był MIESZANY (na przemian dodatni/ujemny — stąd sens reguły "practical tie" na szumie fold-to-fold); w holdoucie wynik jest SYSTEMATYCZNIE ujemny we WSZYSTKICH 5 latach — jakościowo inny wzorzec, nie tylko gorsza wartość. **Czy wynik mieści się w zakresie obserwowanym wcześniej:** pooled holdout (−2,30%) mieści się w granicach zakresu fold-to-fold zmierzonego w kalibracji (−2,43%…+3,33%) — NIE jest bezprecedensowym outlierem względem własnego szumu systemu. Jednak **3 z 5 lat holdoutu (2024: −4,43%, 2025: −2,57% blisko granicy, 2026: −5,89%) WYKRACZAJĄ poza najgorszy rok kalibracyjny** (2019: −2,43%) — część holdoutu jest gorsza niż jakikolwiek pojedynczy rok widziany w kalibracji. Spearman (zdolność rankingowa) na pełnej populacji jest w podobnym porządku wielkości (0,058 vs 0,074) — NIE odwrócony, łagodnie słabszy. Na complete-valuation subset Spearman jest WYRAŹNIE słabszy (0,031 vs 0,113, ~1/3 siły) — to jest najbardziej wyraźny sygnał "performance decay" w tym zestawieniu.

### 7. Zero-candidate periods

**0 z 58 decision dates miało zero kandydatów (0,00%).** Scanner znajdował przynajmniej jednego kandydata w KAŻDYM miesiącu holdoutu — mechanicznie działał zgodnie z projektem przez cały okres. Nie ma obserwacji do ukrycia/wyjaśnienia w tej sekcji.

### 8. Negative result is valid

Holdout pokazuje: **brak przewagi** na primary metric (median excess 6m vs EW = −2,30%, ujemny), **hit rate <50%** na każdym horyzoncie względem OBU benchmarków, **Spearman bliski zera** (0,02–0,06, słaby, choć nie odwrócony), **konsystentną ujemną wartość we WSZYSTKICH 5 latach holdoutu** (różne od mieszanego wzorca kalibracyjnego), oraz **pogorszenie Spearmana na complete-valuation subset** względem kalibracji (0,031 vs 0,113). Raportuję to bez zmiany metodologii, bez próby "uratowania" modelu, bez nowego searchu, bez tworzenia nowych wariantów configu, bez powrotu do okresu kalibracyjnego w poszukiwaniu konfiguracji lepiej pasującej do holdoutu. Ten wynik jest prawidłowym, kompletnym wynikiem ewaluacji.

### 9. Interpretacja

**Klasyfikacja: B — WEAK / INCONCLUSIVE GENERALIZATION.**

Uzasadnienie (opisowe, bez post-hoc progu statystycznego nieobecnego w protokole):

*Przeciw "A — GENERALIZATION SUPPORTED":* primary metric (median excess 6m vs EW) zmienia znak z +0,76% na −2,30%; hit rate <50% względem obu benchmarków na każdym horyzoncie; WSZYSTKIE 5 lat holdoutu ujemne (vs mieszany wzorzec kalibracyjny); Spearman na complete-valuation subset spada ~3x (0,113→0,031); candidate underperformuje SPY silniej niż EW na każdym horyzoncie.

*Przeciw "C — GENERALIZATION NOT SUPPORTED" (pełne odrzucenie):* pooled holdout (−2,30%) mieści się w granicach WŁASNEGO zmierzonego szumu fold-to-fold systemu z okresu kalibracyjnego (−2,43%…+3,33%) — nie jest bezprecedensowym, niemożliwym do wyjaśnienia szumem systemu outlierem; Spearman na pełnej populacji zachowuje ten sam znak i podobny rząd wielkości (0,058 vs 0,074) — zdolność rankingowa NIE odwróciła się; hit rate (42–49%) jest słaby, ale nie katastrofalny (nie np. 20–30%) — wzorzec zgodny z "sygnał zgubiony w szumie", nie z "aktywnie przeciw-predykcyjny".

Mieszanka tych sygnałów — częściowa zgodność ze wzorcem kalibracyjnym (Spearman pełnej populacji, pooled wynik w granicach historycznego zakresu) razem z realną, konsystentną rozbieżnością (odwrócenie znaku primary metric, systematycznie ujemne wszystkie lata, wyraźnie słabszy Spearman na complete-valuation subset) — uzasadnia klasyfikację **B**, nie **A** ani **C**.

### 10. STOP

Raport zakończony. **Zero zmian kodu scoringu/wyceny/configu. Zero nowej rundy kalibracji. Zero automatycznego przejścia do następnej fazy.** Holdout 2022–2026 został otwarty jednorazowo i pozostaje w tym stanie — kolejne kroki wymagają decyzji właścicielki.

---

## Faza 6 — DOMKNIĘCIE MVP V0: trwałe ograniczenie metodologiczne + GAP ANALYSIS + implementacja, v1.56

**Decyzja właścicielki 2026-10-05 (po zamknięciu Fazy 5.4):** Final holdout (klasyfikacja B) NIE uzasadnia tuningu/reweight/usunięcia valuation ani powrotu do kalibracji. Zapisane jako **trwałe ograniczenie metodologiczne** (nie do podważenia bez nowej, niezależnej rundy kalibracji z nowym holdoutem):

1. Final holdout nie wykazał przewagi inwestycyjnej modelu: median 6m excess vs EW PIT universe = −2,30%, wszystkie 5 lat holdoutu ujemne, 6m hit rate <50%.
2. Ranking score zachował słabą dodatnią informację: 6m Spearman (pełna populacja) = 0,058.
3. Valuation wymaga szczególnej ostrożności: na identycznym complete-valuation subset, WITH valuation Spearman = 0,031 vs WITHOUT valuation Spearman = 0,135 — **to NIE upoważnia do usunięcia/reweight valuation po zobaczeniu holdoutu**; jest to limitation/research finding do przyszłej NIEZALEŻNEJ wersji metodologii (nowy protokół, nowy holdout), nie do akcji na obecnym configu.
4. `total_score` NIE jest przedstawiany jako zwalidowany predyktor market outperformance. **Scanner V0 jest decision-support / opportunity-screening system, nie validated alpha model.**

Zero zmian `config/config.yaml` wynikających z Fazy 5.4/5.6/6 — wszystkie wagi/progi/parametry wyceny pozostają identyczne z `FINAL_PRE_HOLDOUT_CONFIG_v1` (Faza 5.5).

### 1. GAP ANALYSIS — istniejący V0 pipeline vs docelowy live flow

Docelowy flow (Decyzja właścicielki): CURRENT MARKET → current universe → fundamentals → decline/opportunity screening → deterministic scoring + hard gates → valuation → Claude qualitative analysis → anti-confirmation-bias layer → source assembly/validation → final candidate report (0–5 kandydatów lub "No qualifying opportunities today").

| Element flow | Status PRZED Fazą 6 | Szczegóły |
|---|---|---|
| Current universe | ✅ Zaimplementowane | `ingest-universe` (Faza 0) — FMP `get_sp500_constituents` → `companies`/`ticker_history`. |
| Fundamentals | ✅ Zaimplementowane | `ingest-fundamentals` (Faza 1) — `fundamentals_raw`, `fundamentals.compute_metrics`. |
| Decline/opportunity screening | ✅ Zaimplementowane, ale TYLKO per jawna lista tickerów | `scan` (Faza 0) + `scanner.py` (`compute_price_changes`/`evaluate_decline_flags`) — silnik gotowy, ale żaden command nie uruchamiał go automatycznie na całym uniwersum. |
| Deterministic scoring + hard gates | ✅ Zaimplementowane | `scoring.py` (`compute_score`/`evaluate_hard_gates`), Faza 4. |
| Valuation | ✅ Zaimplementowane | `valuation.py` — DCF na Owner Earnings (proxy FCF), scenariusze bear/base/bull, Margin of Safety. |
| Claude qualitative analysis | ✅ Zaimplementowane | `analyze`/`score` (Faza 3/4) + `providers/claude.py` + `analysis_schema.py` (schema już miała pola bull_case/bear_case/fear_analysis/biggest_unknown/thesis_invalidation/why_market_may_be_right/why_this_may_not_be_a_bargain/verification_items/hard_flag_candidates od Fazy 3). |
| **Anti-confirmation-bias layer** | ⚠️ **CZĘŚCIOWO** — kształt pól wymuszony schematem (Claude API `output_format`), ale `prompt.py` NIGDY nie instruował modelu, czym te pola są i czego wymagamy co do TREŚCI. `output_format` gwarantuje poprawny JSON, nie jakość/rygor argumentacji. | **GAP naprawiony w tej fazie** (patrz punkt 2). |
| Source assembly/validation | ✅ Zaimplementowane | `sources.py` (`build_sec_source_packet`), jawny `verified=False`+`reason` (SOURCE NOT VERIFIED), Faza 2. |
| **Final candidate report** | ⚠️ **CZĘŚCIOWO** — `report.render_markdown_report` istniał (Faza 4), ale NIGDY nie wypisywał: decline trigger/why surfaced, bull_case/bear_case/why_market_may_be_right/why_this_may_not_be_a_bargain/thesis_invalidation, verification_items, ani listy źródeł (verified/SOURCE NOT VERIFIED) — mimo że wszystkie te dane już istniały w `AnalysisOutput`/source packet, po prostu nie trafiały do renderera. | **GAP naprawiony w tej fazie** (patrz punkt 3). |
| **Orkiestracja end-to-end na CAŁYM aktualnym uniwersum** | ❌ **BRAK** — każdy istniejący command (`scan`/`ingest-fundamentals`/`score`/`analyze`) wymaga JAWNEJ listy tickerów jako argumentu; nie istniał żaden command, który: (a) weźmie całe aktualne S&P 500, (b) przefiltruje przez decline screening, (c) przefiltruje przez prefilter, (d) uruchomi Claude + scoring TYLKO dla przeżywających, (e) zrankuje i obetnie do 0–5 kandydatów, (f) zwróci jeden skonsolidowany raport. | **GAP naprawiony w tej fazie** (patrz punkt 4 — `run-live-scan`). |
| GitHub Actions workflow dla live runu | ❌ BRAK | Istniały tylko "proof run" workflowy per-faza (jawna lista tickerów) i workflowy backtestu/kalibracji (okno kalibracyjne, zero LLM na pełnym uniwersum). **GAP naprawiony** — `.github/workflows/phase6-live-scan.yml`. |
| `list_active_tickers` (DB) | ❌ BRAK | Żadna funkcja nie zwracała "aktualnego uniwersum" bez jawnej listy od wołającego. **GAP naprawiony** — `db.list_active_tickers`. |

**Nie zaprojektowano ponownie żadnego elementu, który już istniał** — DCF/scoring/hard gates/prefilter/source assembly/Claude schema zostały użyte 1:1 bez zmian. Zmiany ograniczone do: (1) treści instrukcji w prompcie (nie kształtu schematu), (2) renderera raportu (nowe opcjonalne sekcje, zero zmiany istniejących przy braku nowych parametrów), (3) nowej orkiestracji łączącej istniejące cegiełki, (4) nowego workflow GH Actions.

### 2. Naprawa anti-confirmation-bias layer (`prompt.py`)

Dodana sekcja "ANTI-CONFIRMATION-BIAS (nieprzekraczalne)" w `build_analysis_prompt`: jawne instrukcje, że `bear_case`/`why_market_may_be_right`/`why_this_may_not_be_a_bargain` muszą być TAK SAMO rygorystyczne jak `bull_case` — model ma aktywnie argumentować PRZECIW własnej tezie inwestycyjnej, nie ograniczać się do ogólników. `thesis_invalidation` musi być konkretne/obserwowalne, `biggest_unknown` musi wskazać realną niewiadomą. Zero zmiany `AnalysisOutput`/`output_format` (Faza 3) — tylko treść instrukcji tekstowych.

### 3. Rozszerzenie finalnego raportu (`report.py`)

`render_markdown_report` rozszerzony o 3 OPCJONALNE parametry (`decline_snapshot`/`triggered_decline_flags`/`source_packet`, domyślnie `None` — zero zmiany zachowania dla istniejących callerów bez nowych argumentów, zweryfikowane testem regresyjnym): nowe sekcje "Dlaczego spółka została wytypowana (decline trigger)", "Analiza jakościowa — anti-confirmation-bias" (Bull/Bear/Why Market May Be Right/Why Current Price May NOT Be an Opportunity/Thesis Invalidation/Biggest Unknown/verification_items), "Źródła" (verified z URL+hash, niezweryfikowane z jawnym **SOURCE NOT VERIFIED** + reason). `cmd_score` (Faza 4) zaktualizowany, by przekazywać już posiadany `source_packet`.

### 4. Nowa orkiestracja: `run-live-scan` (`live_scan.py` + `cli.cmd_run_live_scan`)

Pipeline: current universe (`ingest-universe` logic, opcjonalnie pomijane przez `--skip-universe-refresh`) → `list_active_tickers` → ceny + decline scanner dla KAŻDEGO aktywnego tickera → surfaced = `>=1` przekroczony próg (UNCALIBRATED, jak `scan`) → fundamentals + prefilter TYLKO dla surfaced (EXCLUDE → pominięty, zliczony w audit trail, NIGDY cicho) → source packet + Claude + deterministic scoring + hard gates + valuation TYLKO dla survivors prefiltra → `rank_candidates` (kompletny `total_score` przed PARTIAL, wyżej=lepiej, **nigdy nie dopełnia listy sztucznie** — 0 kandydatów jest prawidłowym wynikiem) → `render_live_scan_report` (audit trail: wielkość uniwersum, liczba surfaced, liczba wykluczonych prefiltrem, liczba nieudanych analiz, finalni kandydaci — "No qualifying opportunities today" explicite, gdy 0). Każdy finalny kandydat persystowany identycznie jak `score` (Faza 4: `analyses`/`analysis_sources`, IMMUTABLE, append-only). `--sample` ogranicza zakres do małego testu przed pełnym runem na całym S&P 500 (ten sam wzorzec co `--sample` w Fazie 5.3b/5.4).

### 5. Testy

14 nowych testów: `list_active_tickers` (2, `test_db.py`), anti-bias instrukcje w prompcie (1, `test_prompt.py`), nowe sekcje raportu + regresja "brak nowych parametrów = brak zmiany zachowania" (6, `test_report.py`), ranking + raport live scanu w tym explicite "0 kandydatów" (5, `test_live_scan.py`). Pełny zestaw: **587 passed, 1 skipped**.

### 6. Status po implementacji

Implementacja zamknięta i przetestowana. Następny krok: pierwszy LIVE END-TO-END RUN na aktualnym rynku (GitHub Actions, `phase6-live-scan.yml`).

---

## Faza 6b — pierwsze 3 live runy na aktualnym rynku: dwa realne znaleziska operacyjne, v1.57

**Żadna zmiana configu/metodologii w tej sekcji — wyłącznie infrastruktura/operacje.**

### 1. Run 1 (GH Actions [37355677202](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37355677202), pełne uniwersum, 79 min, SUCCESS)

501 tickerów, **150 wytypowanych** przez decline screening (głównie `drawdown_from_52w_high`) — znacznie więcej niż mały test (10 tickerów) sugerował. **94/150 nieudanych** — wszystkie z identycznym błędem `Claude API: Your credit balance is too low`, czysty alfabetyczny cutoff od `FICO` do `ZTS` (konto Anthropic wyczerpało limit w połowie runu, nigdy się nie zresetowało). Finalne top-5 pochodziło tylko z 56 alfabetycznie pierwszych kandydatów (A-F) — **systematyczny, nielosowy selection bias**, zgłoszony właścicielce przed jakimkolwiek dalszym krokiem (zero interpretacji top-5 jako wyniku pełnego runu).

### 2. Decyzja właścicielki: "Uzupełnione. Powtórz pełny run."

### 3. Run 2 (GH Actions [37372436386](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37372436386), pełne saldo Anthropic, CANCELLED)

156/501 wytypowanych (rynek się nieznacznie przesunął). Tym razem limit Anthropic WYSTARCZYŁ na cały run (zero błędów kredytowych) — ale główny krok został **ucięty dokładnie na starym job-level `timeout-minutes: 180`** (179m54s, potwierdzone przez `list_workflow_jobs` step timing). Realny, odkryty operacyjnie fakt: pełna sekwencyjna analiza Claude dla 150+ kandydatów trwa dłużej niż 180 minut. (Osobny Run 1.5, [37353678323](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37353678323) na małej próbce 10 tickerów, posłużył tylko do weryfikacji poprawkowego bugfixu `upsert_scoring_model_version` przed FOREIGN KEY — patrz commit `88ac2ce`.)

### 4. Fix: `timeout-minutes: 180 -> 350` (`phase6-live-scan.yml`, commit `cf9eb08`)

Czysto infrastrukturalna poprawka (ten sam limit już używany w `phase5-3c-baseline-walk-forward.yml` dla analogicznie długich pełnych runów) — zero zmiany kodu/metodologii.

### 5. Run 3 (GH Actions [37391647355](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37391647355), 350 min timeout, SUCCESS po 2h53m)

156/501 wytypowanych, 0 wykluczonych prefiltrem. **Tym razem 37/156 nieudanych** — PONOWNIE identyczny błąd `credit balance too low`, czysty cutoff od `PYPL` do `ZTS` (119/156 przeanalizowanych, A-P). Uzupełnienie kredytu z Run 1 wystarczyło na WIĘCEJ (119 vs 56), ale wciąż nie na całość. **Ten sam systematyczny alfabetyczny selection bias**, zgłoszony właścicielce.

### 6. Decyzja właścicielki: OPCJA 3 (2026-10-06)

**Nie akceptuję** 119/156 (A-P) jako pełnego LIVE MVP RUN — cutoff zależy od kolejności tickerów, nie może być podstawą top-5. **Nie uruchamiaj ponownie 156 pełnych analiz Claude.** Diagnoza: architektura MVP brakuje warstwy, która ogranicza KOSZTOWNĄ analizę LLM do deterministycznie wybranej podgrupy — patrz Faza 6c niżej.

---

## Faza 6c — DWUSTOPNIOWY PIPELINE (deterministic ranking + shortlist, OPCJA 3), v1.58

**Decyzja właścicielki 2026-10-06.** Cel: `501 current universe → decline/opportunity screening → deterministic evaluation/ranking WSZYSTKICH screened candidates → deterministic shortlist → full Claude qualitative analysis ONLY for shortlist → gates/qualitative review/source validation → final 0-5 candidates`. Jawny wymóg: **TO NIE JEST post-hoc zmiana metodologii scoringu** — scoring weights/valuation mechanics/hard gates/decline thresholds/prefilter rules/PIT methodology pozostają identyczne z `FINAL_PRE_HOLDOUT_CONFIG_v1` (Faza 5.5).

### 1. GAP/FEASIBILITY CHECK (wykonany PRZED jakąkolwiek implementacją)

**Pytanie 1: Czy `deterministic_score_pct` dla wszystkich screened candidates da się policzyć BEZ Claude?** TAK — i to NIE nowy proxy score: `backtest_harness.compute_deterministic_score`/`evaluate_deterministic_hard_gates` istnieją i są ZAMROŻONE od Fazy 5.3 (sekcja 13), używane przez CAŁĄ kalibrację/holdout (Round 1-3, Faza 5.6) WYŁĄCZNIE na danych bez LLM. Reużyte tu 1:1, zero nowego kodu scoringu.

**Pytanie 2: Które komponenty total_score wymagają LLM?** `business_quality_score` (45 pkt, z `analysis.business_understandability`/`moat`/`management_capital_allocation` — oceny LLM) i `fear_opportunity_raw_points` (10 pkt, z `analysis.fear_analysis.classification`/`confidence` — klasyfikacja LLM). `financial_safety` (15 pkt, `financial_quality_score`), `valuation` (20 pkt, `compute_valuation` — DCF na danych fundamentalnych, zero LLM) i `dividend_shareholder_return` (10 pkt, `evaluate_dividend_shareholder_return`) są W PEŁNI deterministyczne — to jest dokładnie to, co `compute_deterministic_score` liczy (suma dostępnych komponentów / suma dostępnych maksimów × 100).

**Pytanie 3: Zero nowego proxy score** — potwierdzone: `RankedCandidate`/`rank_all_candidates`/`select_shortlist` (nowy kod, `live_scan_pipeline.py`) są WYŁĄCZNIE orkiestracją/sortowaniem/obcinaniem wokół już istniejącego `DeterministicScoreResult` — nie liczą niczego nowego.

**Pytanie 4: Czy `deterministic_score_pct` jest porównywalny między kandydatami?** Tak, w sensie już ustalonym przez Fazę 5.4 (ta sama metryka była podstawą Spearman correlation w Round 2A/2B) — normalizacja względem DOSTĘPNYCH komponentów (np. spółka bez wyceny: suma/maks liczone tylko z safety+dividend, maks=25 nie 45). To NIE jest nowe ograniczenie wprowadzone tu — jest to udokumentowana, zaakceptowana właściwość metryki z Fazy 5.3.

### 2. Shortlist — operacyjny/kosztowy budget, nie próg inwestycyjny

TOP `--shortlist-limit` (domyślnie **20**) po `deterministic_score_pct`, z zachowaniem WSZYSTKICH kandydatów remisujących z pozycją 20 (`select_shortlist`, nigdy nie obcina remisu arbitralnie). Wartość 20 ustalona PRZED jakimkolwiek wynikiem (nie strojona na podstawie tego, jakie spółki się w niej znalazły danego dnia) — jawnie opisana w kodzie/komunikatach CLI jako "operacyjny/kosztowy budget warstwy research, NIE próg inwestycyjny i NIE element zwalidowanej metodologii alpha".

### 3. Implementacja

- **`backtest_harness.py`**: ZERO zmian (reużyty 1:1).
- **`live_scan_pipeline.py`** (nowy): `RankedCandidate`, `rank_all_candidates`, `select_shortlist` (TOP N + remisy), `source_fingerprint`/`build_cache_key` (cache po cik/data_timestamp/config_version/prompt_schema_version/source_fingerprint), `render_full_ranking_table`/`render_shortlist_status_table`.
- **`db.py`**: nowe tabele `live_scan_runs` (status RANKED/INCOMPLETE_LLM_ANALYSIS/COMPLETE) i `live_scan_candidates` (pełny deterministyczny ranking + `llm_status` PENDING/COMPLETE/FAILED/NOT_SHORTLISTED, `cache_key`, `analysis_id` FK do `analyses`) + gettery `get_analysis`/`get_analysis_sources` (rekonstrukcja `AnalysisOutput`/`VerifiedSource` z już zapisanych wierszy — niezbędne do resume/cache bez ponownego odpytywania SEC/Claude).
- **`cli.py`**: `cmd_run_live_scan` przepisany na dwa etapy (etap 1: deterministic ranking + persist + shortlist select, ZERO LLM; etap 2: `_analyze_shortlist_and_report`, pełna analiza Claude WYŁĄCZNIE dla shortlisty). Nowy command `analyze-live-scan-shortlist --run-id <id>` — wznawia etap 2 na istniejącym `run_id` (ta sama baza), analizuje TYLKO `PENDING`/`FAILED`, nigdy ponownie `COMPLETE`.

### 4. Failure handling (wymóg właścicielki)

Błąd Claude API (insufficient credits/rate limit/transient — nieodróżnialne strukturalnie przez SDK, więc traktowane jednolicie jako `ClaudeError`) na KTÓRYMKOLWIEK kandydacie shortlisty → ten kandydat `FAILED` + **STOP dalszych NOWYCH wywołań w tym przebiegu** (pozostali zostają `PENDING`, nie dotykani — fail-fast, zamiast powtarzać gwarantowaną porażkę na każdym kolejnym, co obserwowano w Run 1/3). Błąd walidacji deterministycznej (`AnalysisValidationError`) albo brak zweryfikowanych źródeł jest PER-KANDYDAT (dane tej spółki, nie zdrowie API) — oznacza `FAILED`, ale NIE zatrzymuje reszty. **Finalny raport (0-N) generowany TYLKO, gdy CAŁA shortlist ma status `COMPLETE`** — w przeciwnym razie status `INCOMPLETE_LLM_ANALYSIS` z pełnym rozbiciem per-kandydat (`render_shortlist_status_table`), nigdy partial top-N.

### 5. Resume + cache

**Resume**: `analyze-live-scan-shortlist --run-id <id>` na tej samej bazie (w GitHub Actions: pobranie artefaktu poprzedniego runu, `phase6b-analyze-live-scan-shortlist.yml`) odpytuje WYŁĄCZNIE wiersze `PENDING`/`FAILED` tego `run_id` — `COMPLETE` nigdy nie jest dotykane, zero powtórnej płatności za Claude.

**Cache**: `cache_key = sha256(cik|data_timestamp|config_version|prompt_schema_version|source_fingerprint)`, gdzie `data_timestamp` łączy `run_date` + PIT fundamentals `period_end_date`/`filed_date` (pełny fingerprint danych wejściowych specyficznych dla tej daty), `config_version` to hash `config.yaml` (ten sam wzorzec co `config_hash` w kalibracji), `prompt_schema_version` to `config.llm.schema_version`, `source_fingerprint` to hash posortowanych `content_hash` zweryfikowanych źródeł SEC (zmiana TREŚCI dokumentu unieważnia cache, zmiana samego URL-a nie). `find_cached_live_scan_analysis` szuka trafienia z JAKIEGOKOLWIEK poprzedniego `run_id` — identyczne wejście nigdy nie płaci za Claude drugi raz, niezależnie od tego, w którym przebiegu zostało już przeanalizowane.

### 6. Testy

26 nowych testów: `live_scan_pipeline.py` (10, `test_live_scan_pipeline.py` — ranking/shortlist/remisy/cache key/fingerprint), nowe tabele `live_scan_runs`/`live_scan_candidates` + `get_analysis`/`get_analysis_sources` (9, `test_db.py`), pełny dwustopniowy pipeline z fejkowymi providerami — `--rank-only`, obcięcie shortlisty, `INCOMPLETE_LLM_ANALYSIS` bez partial top-N, resume (TYLKO PENDING/FAILED, nie ponownie COMPLETE), cache hit (zero nowego wywołania Claude) (7, `test_cli.py`, w tym regresja dla realnego bugu run_id collision przy sekundowej precyzji timestampu, znalezionego podczas pisania tych testów). Pełny zestaw: **612 passed, 1 skipped**.

### 7. Status

Implementacja zamknięta i przetestowana. Pierwsza mała próbka dwustopniowego pipeline'u (GH Actions run [37424219308](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37424219308), 10 tickerów, 1 wytypowany — PYPL) zadziałała poprawnie end-to-end, ALE Claude API zwróciło ten sam błąd `credit balance too low` co w Fazie 6b — konto Anthropic było dalej bez środków. Pipeline poprawnie: oznaczył kandydata `FAILED`, zatrzymał się (fail-fast), wypisał `STATUS: INCOMPLETE_LLM_ANALYSIS (0/1 COMPLETE)`, **nie wygenerował żadnego partial raportu** — dokładnie zgodnie z projektem. Decyzja właścicielki: **STOP przed kolejnym doładowaniem — najpierw COST AUDIT** (patrz „Faza 6d" niżej) — pełny live run z dwustopniowym pipeline'em na aktualnym rynku jeszcze NIE wykonany.

---

## Faza 6d — COST AUDIT (przed decyzją o kolejnym doładowaniu Anthropic), v1.59

**Decyzja właścicielki 2026-10-06:** "Nie chcę ponownie doładowywać konta bez poznania rzeczywistego kosztu pipeline." Audyt wykonany WYŁĄCZNIE przez odczyt już istniejących artefaktów (zero sieci, zero nowych wywołań Claude API) — jednorazowy skrypt `scripts/diag_cost_audit.py` (usunięty po użyciu, jak każda diagnostyka w tym projekcie) czytający `llm_raw_output` z `analyses` w artefaktach Run 1 (GH Actions [37355677202](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37355677202)) i Run 3 ([37391647355](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/37391647355)).

### 1. Co jest NAPRAWDĘ zapisane/odtwarzalne — i czego NIE

**NIE istnieje gdziekolwiek** (ani w DB, ani w logach GH Actions, ani w logach aplikacji): `response.usage` (input/output/cache tokens) per wywołanie. `ClaudeClient.generate_analysis` (`providers/claude.py`) nigdy nie odczytuje, nie loguje i nie zapisuje `response.usage` — zwraca tylko `response.parsed_output`. Żaden request_id poza tymi widocznymi w treści błędów 400 (np. `req_011CfkWpxTCpymPXrwrkH311`) nie jest zapisany w sposób umożliwiający zapytanie do Anthropic post-hoc. Nie mam też dostępu do konsoli/billing dashboardu Anthropic właścicielki. **Nie zgaduję tych liczb — nie istnieją w żadnej dostępnej mi formie.**

**Co jest REALNE i zmierzone** (nie oszacowane): liczba UDANYCH Claude calls per run (`COUNT(*)` z `analyses`) — Run 1 = **56**, Run 3 = **119**, mały test PYPL = **0** (failed na pierwszym wywołaniu). Model użyty: **`claude-sonnet-5`** (jedyny, potwierdzone w obu artefaktach). Schema version: `1.0`. **Zero prompt caching** — potwierdzone strukturalnie (nie zmierzone pośrednio): `ClaudeClient` nigdy nie ustawia `cache_control` na żadnym blocku, więc `cache_read_input_tokens`/`cache_creation_input_tokens` są strukturalnie zawsze 0, niezależnie od tego, czy to zmierzyliśmy.

**Rozmiar `llm_raw_output`** (pełny JSON `AnalysisOutput.model_dump()`, dokładnie zapisany dla każdej udanej analizy) — **realne dane, ZNAKI nie tokeny**:

| Run | n | min | median | mean | max |
|---|---|---|---|---|---|
| Run 1 (56/150) | 56 | 7527 | 10543 | 10553 | 13240 |
| Run 3 (119/156) | 119 | 7677 | 10652 | 10459 | 13085 |

Dwie niezależne próbki (56 i 119) są bardzo zgodne (mean ~10500, median ~10600 w obu) — silny sygnał, że to stabilna, powtarzalna charakterystyka tego promptu/modelu, nie przypadek.

### 2. Rekonstrukcja promptu (strukturalnie identyczna z produkcyjną, wartości metryk SYNTETYCZNE — nigdy nie zalogowaliśmy dokładnego promptu historycznego)

Realne wywołanie `build_analysis_prompt` z reprezentatywnymi metrykami i 4 źródłami SEC: **2793 znaków / 334 słowa**. `AnalysisOutput.model_json_schema()` (wysyłany jako `output_format`, też liczy się do kosztu requestu): **4869 znaków**. Łącznie ~**7662 znaki "widocznego" inputu** per wywołanie — **żadna pełna treść dokumentów SEC NIE jest wysyłana do Claude** (tylko metadane: tytuł/wystawca/URL, max 4 źródła) — to ważne ustalenie: duże dokumenty 10-K/10-Q nie są kosztem inputu w tym pipeline.

### 3. Szacowany koszt per COMPLETE analysis (JSON-widoczny content, NIGDY nie zmierzony realnie)

Konwersja znaki→tokeny: **szacunkowa, nie zmierzona** (brak dostępu do `messages.count_tokens` Anthropic z tej sesji — inny klucz API, inne konto). Zakres 3–4 znaki/token (treść głównie polska, mniej efektywna tokenizacyjnie niż angielska ~4 znaki/token). Ceny `claude-sonnet-5`: $2.00/MTok input, $10.00/MTok output (potwierdzone w aktualnym cenniku Anthropic).

| | Input (tok, szac.) | Output (tok, szac.) | Koszt/call |
|---|---|---|---|
| **Expected** (median) | ~1900–2600 | ~2600–3500 | **~$0,030–$0,040** |
| **Conservative upper** (max obs.) | ~1900–2600 | ~3300–4400 | **~$0,038–$0,049 (~$0,05)** |

### 4. KRYTYCZNE ustalenie — ten szacunek NIE wyjaśnia realnego zużycia $20

175 udanych wywołań (56+119) × ~$0,035 (expected) ≈ **$6,1** — a NIE $20. Nieudane wywołania (37+94=131) były odrzucane na poziomie walidacji requestu (HTTP 400 "credit balance too low") PRZED generowaniem — koszt ~$0, potwierdzone: wszystkie zebrane komunikaty błędów w obu runach miały identyczną treść (wyczerpanie kredytu), zero komunikatów o ucięciu przez `max_output_tokens` (co by wskazywało na kosztowne częściowe generacje przed porażką).

**Najbardziej prawdopodobne wyjaśnienie (nie potwierdzone, ale oparte na udokumentowanym zachowaniu modelu, nie zgadywane z próżni):** `claude-sonnet-5` z domyślnym (nieustawionym explicite) `thinking` **uruchamia adaptive thinking automatycznie** — `ClaudeClient.generate_analysis` NIGDY nie ustawia parametru `thinking`, więc model myśli adaptacyjnie przy KAŻDYM wywołaniu. **Tokeny thinking są billowane jako output tokens, ale NIE są zapisywane w `llm_raw_output`** (który zawiera tylko `response.parsed_output`, nigdy blocki `thinking`) — więc są całkowicie niewidoczne w naszych danych. To w pełni wyjaśniłoby 2–4x rozbieżność między szacunkiem JSON-only (~$6) a realnym zużyciem (~$20/175≈$0,114 per call, JEŚLI całe $20 poszło na ten projekt — tego też nie mogę potwierdzić).

**Nie mogę potwierdzić tej hipotezy bez prawdziwych danych `response.usage`** — zgłaszam ją jako najbardziej prawdopodobne wyjaśnienie znalezionej rozbieżności, nie jako fakt.

### 5. Szacowany koszt TOP 5/10/15/20 (dwa reżimy, bo nie wiadomo, który bliższy prawdzie)

| Shortlist | JSON-only expected (~$0,035/call) | JSON-only conservative (~$0,05/call) | Empiryczny implied rate (~$0,114/call, przy założeniu że całe $20 poszło na ten projekt) |
|---|---|---|---|
| TOP 5 | $0,18 | $0,25 | $0,57 |
| TOP 10 | $0,35 | $0,50 | $1,14 |
| TOP 15 | $0,53 | $0,75 | $1,71 |
| TOP 20 | $0,70 | $1,00 | $2,28 |

Nawet najwyższy (empiryczny) reżim implikuje, że sam koszt tokenów analizy jednego live runu z shortlistą 20 to rząd **$2–3**, nie $20 — co jest zgodne z tym, że $20 kredytu wystarczyło na 175 udanych analiz w poprzedniej architekturze (bez shortlisty).

### 6. Największe źródła INPUT TOKEN COST (zidentyfikowane, NIE zoptymalizowane — zgodnie z instrukcją)

1. **Stały blok instrukcji ANTI-CONFIRMATION-BIAS + ZASADY** — identyczny tekst przy KAŻDYM wywołaniu (żadna treść specyficzna dla tickera) — kandydat do prompt caching, ale **nie wdrażam tego teraz**.
2. **JSON Schema `AnalysisOutput`** (~4869 znaków, wysyłana jako `output_format` przy każdym wywołaniu) — również identyczna przy każdym wywołaniu.
3. Lista źródeł (`ŹRÓDŁA DOSTĘPNE DO CYTOWANIA`) — mała (metadane, nie treść dokumentów), rośnie liniowo z liczbą źródeł (max 4 w configu).
4. Metryki deterministyczne — najmniejszy składnik, kilkanaście par klucz:wartość.

**Żadna pełna treść dokumentu SEC nie jest wysyłana** — potwierdzone czytając `prompt.py`: `build_analysis_prompt` wypisuje tylko `title`/`issuer`/`url` per źródło, nigdy treść pobranego dokumentu. To obala wcześniejsze przypuszczenie, że duże dokumenty 10-K/10-Q mogłyby dominować koszt inputu.

### 7. Doładowanie 2 ($5 → wystarczyło tygodniami; $20 → wyczerpane w jeden dzień) i dokładny rozkład input tokens, v1.60

**Dodatkowy kontekst od właścicielki:** pierwsze doładowanie ($5) wystarczało przez wszystkie wcześniejsze prace aż do uruchomienia masowych live runów — $20 zostało w całości zużyte przez: Run 1 (~56 analiz), Run 3 (~119 analiz), test nowej architektury (0 analiz, od razu brak środków). To **potwierdza** (nie tylko zakłada), że $20 ÷ 175 udanych analiz = **$0,1143/analizę — realna, potwierdzona empiryczna stawka**, nie hipoteza.

**Dokładny rozkład znaków promptu** (rekonstrukcja strukturalna, realny `build_analysis_prompt` z 4 źródłami):

| Komponent | Znaki | % całości | Stały/zmienny |
|---|---|---|---|
| JSON Schema `AnalysisOutput` (`output_format`) | 4869 | 64% | **STAŁY** (identyczny co call) |
| Blok ANTI-CONFIRMATION-BIAS | 1176 | 15% | **STAŁY** |
| Lista źródeł (tylko metadane: tytuł/wystawca/URL) | 518 | 7% | zmienny (0-4 źródła) |
| Blok ZASADY | 555 | 7% | **STAŁY** |
| Metryki deterministyczne (6-15 par klucz:wartość) | 285 | 4% | zmienny |
| Nagłówek (nazwa tickera w pierwszym zdaniu) | 259 | 3% | zmienny |
| **STAŁE razem** | **6600** | **86%** | |
| **ZMIENNE razem (per ticker)** | **1062** | **14%** | |

**Odpowiedzi na konkretne pytania właścicielki:**

1. **Czy koszt wynika z liczby wywołań, czy pojedyncze calle są drogie?** GŁÓWNIE z liczby wywołań — $5 wystarczyło na tygodnie pracy (nieliczne pojedyncze testy Faz 0-4, Faza 5 kalibracja/backtest NIE wywołuje Claude wcale), $20 skonsumowane w jeden dzień przez 175 wywołań naraz. Ale jest też drugorzędny efekt: realna stawka $0,1143/call jest ~3x wyższa niż szacunek z samej widocznej treści JSON (~$0,035) — pojedyncze wywołania SĄ droższe niż "wyglądają", najprawdopodobniej przez niewidoczne tokeny adaptive thinking (patrz punkt 4 wyżej). Oba efekty są realne: wolumen dominuje, ale jest też realna, niewyjaśniona nadwyżka per-call.
2. **Średni koszt jednej analizy:** **$0,1143** (realne, potwierdzone: $20 ÷ 175).
3. **Co dominuje input tokens:** JSON Schema struktury wyjścia (64%) i statyczne instrukcje anti-bias/zasady (22%) — razem **86% inputu jest identyczne co wywołanie**, nie ma nic wspólnego z konkretną spółką. Fundamentals/metryki deterministyczne to tylko 4%. **Treść dokumentów SEC/IR nie jest wysyłana wcale** — tylko metadane (7%).
4. **Czy ten sam duży kontekst jest wysyłany ponownie przy każdym tickerze?** TAK — 6600 z 7662 znaków (86%) jest bitowo identyczne w KAŻDYM wywołaniu, dla KAŻDEGO tickera, w KAŻDYM runie — wysyłane od nowa, nigdy nie cache'owane.
5. **Czy prompt caching jest używany?** NIE (potwierdzone strukturalnie — zero `cache_control` w kodzie). **Potencjał (nie wdrożony):** blok ZASADY+ANTI-CONFIRMATION-BIAS (1731 znaków, statyczny) mógłby być cache'owany (`cache_control: ephemeral`, ~90% taniej za odczyt) — ale wymagałoby to przebudowy promptu, bo obecnie nagłówek specyficzny dla tickera jest PIERWSZYM zdaniem (przerywa dowolny prefiks cache'a, który musi zaczynać się od treści stałej). Cache'owalność samej JSON Schema (`output_format`, przekazywanej jako parametr strukturalny API, nie tekst promptu) nie jest czymś, co mogę potwierdzić z dostępnej mi dokumentacji. **Nic z tego nie wdrażam teraz.**
6. **Koszt nowej architektury (shortlist) na podstawie REALNEGO usage** ($0,1143/call, nie szacunek JSON-only):

| Shortlist | Koszt (realna stawka $0,1143/call) |
|---|---|
| TOP 5 | **$0,57** |
| TOP 10 | **$1,14** |
| TOP 15 | **$1,71** |
| TOP 20 | **$2,29** |

(Szacunek JSON-only z punktu 5 wyżej, $0,035-0,05/call, pozostaje jako dolna granica/sanity-check — realna stawka jest wiarygodniejsza, bo oparta na POTWIERDZONYM przez właścicielkę pełnym zużyciu $20 przez te konkretne 175 wywołań.)

### 8. STOP

Zero zmian promptu/metodologii/kodu w tej fazie — wyłącznie audyt. Zero nowych (płatnych) wywołań Claude API. Decyzja o kolejnym doładowaniu Anthropic i o uruchomieniu pierwszego pełnego live runu z dwustopniowym pipeline'em należy do właścicielki.

---

## Faza 6e — TELEMETRIA Anthropic API usage, v1.61

**Decyzja właścicielki 2026-10-06:** "Cost audit zaakceptowany. Wniosek: nie będziemy dalej szacować kosztu na podstawie rozmiaru `llm_raw_output`. Przed kolejnym pełnym live runem wprowadź WYŁĄCZNIE telemetrię Anthropic API usage" — per-kandydat i per-run agregat, koszt $ raportowany TYLKO jeśli wiarygodnie policzalny (inaczej surowe tokeny bez wymyślonego kosztu), nigdy nie przypisuj kosztu do niewykonanego wywołania (400 insufficient-credit), zachowaj resume behavior. Explicite zakazane w tej fazie: zmiana promptu, modelu, konfiguracji `thinking`, schematu JSON, scoringu, logiki shortlisty, source assembly, jakiejkolwiek metodologii inwestycyjnej. Wymóg: zweryfikować realne pola SDK przez inspekcję, nie zgadywać z dokumentacji nowszej generacji modeli. Testy WYŁĄCZNIE lokalne/jednostkowe, zero nowych płatnych wywołań Claude, STOP przed jakimkolwiek live runem.

### 1. Krok 0 — realne pola zainstalowanego SDK (zweryfikowane przez inspekcję, nie zgadywane)

`pip show anthropic` → **`anthropic==1.8.0`** (pinned `anthropic>=1.8,<2` w `requirements.txt`) — starsza generacja SDK niż referencja ogólnej dokumentacji modeli najnowszej generacji, więc żadna nazwa pola nie została przeniesiona z pamięci. Inspekcja `anthropic.types.Usage`/`Message`/`anthropic.types.parsed_message.ParsedMessage` (`ParsedMessage(Message)`, `messages.parse(...)` zwraca `ParsedMessage[ResponseFormatT]`) na realnie zainstalowanym pakiecie:

- `response.usage.input_tokens: int`, `response.usage.output_tokens: int` — zawsze obecne.
- `response.usage.cache_creation_input_tokens: int | None`, `response.usage.cache_read_input_tokens: int | None` — płaskie liczniki (plus zagnieżdżone `cache_creation: CacheCreation | None` z rozbiciem `ephemeral_1h_input_tokens`/`ephemeral_5m_input_tokens` — nieużywane tutaj, płaskie liczniki wystarczają).
- `response.usage.output_tokens_details: OutputTokensDetails | None` → `.thinking_tokens: int` — **realne, zwracane pole dla tokenów wewnętrznego rozumowania, zawarte w `output_tokens` (billing), ale rozłączne do obserwowalności.** To bezpośrednio odpowiada na hipotezę "niewidocznych tokenów adaptive thinking" z Fazy 6d (COST AUDIT): tokeny thinking SĄ widoczne przez SDK, po prostu nigdy nie były odczytywane przez `ClaudeClient` — nie są one niewidoczne z zasady.
- `response.usage.service_tier: Literal["standard","priority","batch"] | None`, `response.usage.inference_geo: str | None`, `response.usage.server_tool_use: ServerToolUsage | None` (web_fetch/web_search requests — nieużywane, ten scanner nie używa server tools).
- `response.model: str` (realny `model` zwrócony przez API — ground truth, odrębny od skonfigurowanego `config.llm.model`), `response.id`, `response.stop_reason` — już używane przez istniejący kod (`stop_reason == "refusal"`).

### 2. Implementacja (3 pliki produkcyjne, zero innych)

- **`providers/claude.py`**: nowy `ClaudeUsage` (frozen dataclass, pola 1:1 z powyższej listy, `from_response(response)`) i `ClaudeAnalysisResult(output, usage)`. `generate_analysis` zwraca teraz `ClaudeAnalysisResult` (nie goły `AnalysisOutput`). `ClaudeError.__init__` przyjmuje opcjonalny `usage` — **obecny TYLKO gdy API faktycznie zwróciło odpowiedź** (refusal, nie-sparsowalny JSON), **`None` gdy nie istniał żaden `response`** (`APIStatusError`/`APIConnectionError`, np. wyczerpany kredyt — ten sam przypadek co Run 1/3 z Fazy 6b) — nigdy nie wymyślony koszt/token dla niewykonanego wywołania.
- **`db.py`**: nowe nullable kolumny usage (`llm_response_model`, `llm_input_tokens`, `llm_output_tokens`, `llm_cache_creation_input_tokens`, `llm_cache_read_input_tokens`, `llm_thinking_tokens`, `llm_service_tier`) na `analyses` (per faktycznie zapisana, udana analiza — obejmuje `cmd_score` ORAZ live-scan, ten sam `insert_analysis(**fields)` co wcześniej) i na `live_scan_candidates` (per-kandydat, per PRÓBA wywołania w TYM `run_id` — źródło agregatu per-run). `update_live_scan_candidate_llm_status` przyjmuje opcjonalny `usage: ClaudeUsage | None`: realny usage dla sukcesu i dla FAILED-z-realną-odpowiedzią, `None` dla FAILED-bez-odpowiedzi i dla CACHE HIT (COMPLETE bez nowego wywołania w TYM runie — zero nowego kosztu). Nowa `get_live_scan_run_usage_summary(conn, run_id)`: płaski `SUM`/`COUNT` po `live_scan_candidates` dla `run_id` — **NIE JOIN do `analyses`** (cache hit miałby tam usage z INNEGO, wcześniejszego `run_id`, co błędnie policzyłoby go jako nowy koszt TEGO runu). Migracja kolumn dodana do `_COLUMN_MIGRATIONS` (ten sam mechanizm co `overlap_merge_note`, Faza 5.2) — reużywany artefakt `live_scan_result.db` z poprzednich faz dostaje nowe kolumny bez odtwarzania bazy.
- **`cli.py`**: `_run_llm_analysis` (współdzielone przez `analyze`/`score`) i `_analyze_shortlist_and_report` (Stage 2 live-scan) przekazują `usage` do `insert_analysis`/`update_live_scan_candidate_llm_status` na każdej ścieżce (sukces, refusal/nie-sparsowalny JSON, błąd walidacji deterministycznej, 400/sieć, cache hit). Po tabeli statusu shortlisty CLI wypisuje agregat per-run (`calls_with_usage`/`cache_hits`/`failed`, sumy input/output/cache/thinking tokens) z jawną notatką "brak wyliczonego kosztu $ — brak dziś zweryfikowanego cennika per-token".

### 3. Koszt $ — jawnie NIE liczony

Żadna wartość $ nie jest wyliczana w kodzie. Powód: COST AUDIT (Faza 6d) nie potwierdził żadnego zweryfikowanego, jednoznacznego cennika per-token dla `claude-sonnet-5` — jedyna wiarygodna liczba to empiryczna stawka per-call ($20/175=$0,1143), nie per-token. Wymyślanie kursu $/token teraz byłoby zgadywaniem — zamiast tego: surowe, realne liczby tokenów są persystowane i raportowane, $ zostaje policzony dopiero gdy właścicielka potwierdzi wiarygodny cennik.

### 4. Testy

13 nowych/rozszerzonych testów, zero sieci/płatnych wywołań Claude: `test_claude_client.py` (fake `response.usage`/`response.model`, realny kształt zweryfikowany w punkcie 1 — sukces z realnym usage, `thinking_tokens` gdy obecny, refusal/`parsed_output=None` z `.usage` NIE-None, 400/sieć/truncated-JSON z `.usage is None`); `test_db.py` (persist realnego usage na sukcesie, agregat per-run z poprawnym rozdzieleniem nowych wywołań/cache hit/FAILED, migracja kolumn na symulowanym "starym" plikcie DB); `test_cli.py` (rozszerzone istniejące testy end-to-end o asercje na zapisanych kolumnach usage w `analyses`/`live_scan_candidates` i na wypisanym agregacie CLI, oraz NULL usage dla symulowanego 400 insufficient-credit). Pełny zestaw: **616 passed, 1 skipped**.

### 5. STOP

Zero zmian promptu/modelu/konfiguracji `thinking`/schematu JSON/scoringu/shortlisty/source assembly/metodologii. Zero nowych (płatnych) wywołań Claude API w tej fazie. Decyzja o kolejnym live runie (próbkowym czy pełnym) należy do właścicielki — od tego runu telemetria będzie zawierać PIERWSZE realne dane (w tym, czy `thinking_tokens` faktycznie jest niezerowy, co po raz pierwszy zweryfikuje/sfalsyfikuje hipotezę adaptive-thinking z Fazy 6d na realnych danych, nie estymacji).

---

## Faza 6f — BUGFIX V0 OUTPUT CONTRACT, v1.62

**Decyzja właścicielki 2026-10-06** (po przeglądzie FINAL FULL LIVE MVP RUN, `run_id=live-scan-2026-10-06T083825543395Z`, `commit=c6706442bfa6e20954516ceeeeaeb1c4663d778a`): "To jest BUGFIX V0 OUTPUT CONTRACT. NIE jest to kolejna kalibracja ani zmiana metodologii." Explicite zakazane: zmiana scoringu/wag/hard gates/decline screening/deterministic ranking/shortlist TOP-20/DCF methodology/growth assumptions/caps/source hierarchy/modelu Claude/konfiguracji `thinking`. Historyczny run pozostaje immutable audit artifact — bugfix dotyczy wyłącznie przyszłych analiz.

### 1. Root cause — Claude nie znał current_price/DCF/MoS

Odczyt `build_analysis_prompt` (`prompt.py`, przed tą fazą) potwierdził: prompt budowany był WYŁĄCZNIE z `metrics` (fundamentals-derived), `prefilter_flags` i `sources` — **nigdy** z `current_price`, decline snapshot czy wyceny DCF. Jednocześnie `backtest_harness.compute_deterministic_score` (Stage 1 live-scanu, zero LLM) już liczy pełny `DeterministicScoreResult.valuation_result: ValuationResult` (BEAR/BASE/BULL `intrinsic_value_per_share`/`margin_of_safety_pct`, z `valuation.compute_valuation` — czysta, deterministyczna funkcja `(sector_profile, periods, current_price, config)`) — ale tylko skalarny `valuation_score`/`margin_of_safety_base_pct` trafiał do `live_scan_candidates`, nigdy do promptu Stage 2. Claude mówiąc "nie znam ceny/MoS" był więc **dosłownie prawdomówny** względem tego, co dostał — bug był w pipeline, nie w modelu.

### 2. Co dodano do input context (i co NIE)

- `prompt.py`: `build_analysis_prompt` przyjmuje teraz opcjonalne `current_price: float | None`, `decline_snapshot: PriceChangeSnapshot | None`, `valuation_result: ValuationResult | None`. Nowa sekcja "KONTEKST CENY I WYCENY" wypisuje: aktualną cenę; DCF BEAR/BASE/BULL (`intrinsic_value_per_share`/Margin of Safety) gdy `valuation_result.implemented`, albo jawny powód gdy nie (`NOT_YET_IMPLEMENTED` dla BANK/INSURER/REIT, ujemny FCF, itd.); decline snapshot (1D/1T/1M/1Q/YTD/1R/drawdown/wolumen względny, pole-po-polu `None`→`"N/A"`, nigdy zgadywane 0.0 — `PriceChangeSnapshot` ma zasadę DATA UNAVAILABLE = `None`, nie 0). Jawna instrukcja: "Powyższe dane są JUŻ POLICZONE przez pipeline... NIE przeliczaj DCF samodzielnie... Inne wskaźniki rynkowe (P/E, EV/EBITDA...), których tu NIE podano, rzeczywiście nie są dostępne — napisz to wprost jako ograniczenie/unknown." Brak któregokolwiek z trzech argumentów → sekcja wypisuje "NIEDOSTĘPNA/NIEDOSTĘPNY w tym wywołaniu" (np. `cmd_analyze` dry-run bez pobranej ceny) — nigdy nie udaje dostępności, której nie ma.
- `cli.py`: `_analyze_shortlist_and_report` (live-scan Stage 2) liczy `valuation_result`/`decline_snapshot` PRZED wywołaniem Claude, reużywając 1:1 te same frozen funkcje (`compute_valuation`/`compute_price_changes`) co Stage 1/final report — zero nowej logiki wyceny, tylko wcześniejsze wywołanie. `_run_llm_analysis` (współdzielone przez `cmd_analyze`/`cmd_score`) dostało te same opcjonalne parametry; `cmd_score` (ma już pobraną cenę) je wypełnia, `cmd_analyze` (prawdziwy dry-run bez ceny) poprawnie przekazuje `None` → jawne "NIEDOSTĘPNE".
- NIE dodano: żadnych nowych źródeł danych, market multiples (P/E, EV/EBITDA), ani jakiejkolwiek nowej logiki wyceny — wyłącznie przekazanie już policzonych wartości wcześniej w tym samym pipeline.

### 3. Semantic completeness validation

`analysis_schema.py`: nowa `_is_semantically_empty(text)` — heurystyka (jawnie udokumentowana jako przybliżenie, NIE analiza NLU): odrzuca znormalizowany tekst należący do blocklisty placeholderów (`""`, `"brak"`, `"n/a"`, `"brak danych"`, `"nie wiadomo"`, `"unknown"`, `"-"` itd.) albo krótszy niż 15 znaków. Wymagane SEMANTYCZNIE niepuste: `bull_case`, `bear_case`, `why_market_may_be_right`, `why_this_may_not_be_a_bargain`, `thesis_invalidation` (listy — co najmniej jeden niepusty element) i `biggest_unknown` (string). Sprawdzenie dopisane na końcu istniejącego `validate_analysis_output` (ten sam `AnalysisValidationError`, ta sama ścieżka wywołania co reguły sekcji 8) — automatycznie obowiązuje wszędzie, gdzie ta funkcja jest już wołana (`cmd_analyze`, `cmd_score`, live-scan Stage 2), zero nowego call-site do pamiętania.

### 4. COMPLETE = rzeczywista kompletność (bounded retry)

`_analyze_shortlist_and_report`: nowy `MAX_ANALYSIS_ATTEMPTS = 2` (1 oryginalna próba + 1 retry, nigdy nieskończona pętla). `AnalysisValidationError` (strukturalna LUB semantic completeness) na próbie < 2 → retry (nowe realne wywołanie Claude, ten sam prompt). `ClaudeError` (błąd API — insufficient credits/rate limit/transient) na KTÓREJKOLWIEK próbie → **bez retry**, natychmiastowy fail-fast, identyczny z istniejącym zachowaniem Fazy 6c (błędy API są systemowe/uniform, nie per-próba — retry tylko gwarantowanie powtórzyłby porażkę). Po wyczerpaniu `MAX_ANALYSIS_ATTEMPTS` prób bez poprawnej odpowiedzi → status `FAILED`, NIGDY `COMPLETE`. Nowa `_sum_claude_usage` sumuje `ClaudeUsage` WSZYSTKICH realnych prób (nie tylko ostatniej) przed persystencją — telemetria (Faza 6e) nigdy nie zaniża realnego kosztu retry'owanego kandydata.

### 5. Testy

37 nowych/rozszerzonych testów, zero sieci/płatnych wywołań Claude:
- `test_prompt.py`: kontekst ceny/DCF/decline przekazywany gdy dostępny (odtwarza realny przykład INTU: current_price=284.68, BASE IV=1817.83, MoS=84.3%); jawne "NIEDOSTĘPNA/NIEDOSTĘPNY" gdy brak; powód gdy `implemented=False`; `None`-pole-po-polu w decline snapshot nie rzuca i nie zgaduje 0.0 (testy A/B ze specyfikacji właścicielki).
- `test_analysis_schema.py`: odrzucenie `""`/`null`/`[]`/placeholderów (`"brak"`/`"N/A"`/`"nie wiadomo"` itd.) dla każdego z 6 wymaganych pól (sparametryzowane); akceptacja konkretnego, uczciwego "nie wiadomo X" (przykład właścicielki); akceptacja odpowiedzi podobnej do PAYX (jedyny shortlist candidate z realnego runu, który poprawnie wygenerował oba pola) (testy C/D/E/F).
- `test_cli.py`: fake Claude, który ZAWSZE zwraca semantycznie pustą odpowiedź → dokładnie `MAX_ANALYSIS_ATTEMPTS` wywołań, status `FAILED` (nie `COMPLETE`), `analyses` pozostaje bez nowego wiersza, usage obu prób zsumowany w telemetrii; regresja na istniejącym scenariuszu Fazy 6c (fail-fast na 400, resume TYLKO PENDING/FAILED, agregat telemetrii) potwierdzająca, że nic z tego nie zepsuł bugfix (test G).

Pełny zestaw: **653 passed, 1 skipped** (było 616 przed tą fazą).

### 6. STOP

Zero zmian scoringu/wag/hard gates/decline screening/deterministic ranking/shortlist TOP-20/DCF methodology/growth assumptions/source hierarchy/modelu Claude/konfiguracji `thinking` — potwierdzone diffem (3 pliki produkcyjne: `analysis_schema.py`, `cli.py`, `prompt.py`). Historyczny run `live-scan-2026-10-06T083825543395Z` nietknięty. Zero nowych (płatnych) wywołań Claude API w tej fazie. Zero ponownego pełnego live runu — decyzja o nim należy do właścicielki, po jej review tego bugfixu.

---

## Faza 6f (uzupełnienie) — LIVE VALIDATION TEST wyniku bugfixu, v1.63

**Decyzja właścicielki 2026-10-06:** ograniczony test operacyjny poprawionego Stage 2 WYŁĄCZNIE dla 5 historycznych finalistów (CBOE/PAYX/DECK/INTU/ACN) z `live-scan-2026-10-06T083825543395Z` — cel: zweryfikować kontrakt LLM, NIE ponownie wybierać kandydatów ani kalibrować model.

**Mechanika (jednorazowa diagnostyka, usunięta po użyciu):** nowy, osobny `run_id` (prefix `validation-6f-`, `run_date` z jawnym sufiksem `-validation6f` żeby `cache_key` nie trafił w cache historycznych analiz) seedowany kopiując 1:1 JUŻ POLICZONE deterministyczne wartości (current_price/decline flags/DCF/MoS/hard gates) z historycznego `run_id` — zero decline screeningu, zero rankingu, zero nowego TOP-20 — potem niezmieniony `analyze-live-scan-shortlist`. Historyczny run tylko odczytany.

**Wynik: 1/5 COMPLETE (INTU), 4/5 FAILED (CBOE/DECK/ACN/PAYX)** — **NIE spełnia kryterium 5/5** ustalonego przed testem. Wszystkie 4 FAILED mają identyczny powód na OBU próbach: `thesis_invalidation jest semantycznie pusty`. **Claude calls: 9** (1 dla INTU + 2×4 dla resztу), **retry: 4**. Telemetria: input_tokens=51554, output_tokens=86237, thinking_tokens=40783, cache=0.

**Dowód, że Problem 1 (price/valuation context) z Fazy 6f jest naprawiony** (jedyna zachowana treść — FAILED nie persystuje `llm_raw_output`): INTU-owa odpowiedź dosłownie cytuje `current_price=284.68`, BASE IV=1817.83, MoS=84.3%, i pełny rozstrzał scenariuszy DCF (654/1818/3499 USD/akcję) w `why_this_may_not_be_a_bargain` — Claude nigdzie nie twierdzi, że nie znał ceny/MoS. Dla 4 FAILED nie da się bezpośrednio zacytować treści (nie persystowana), ale strukturalnie wiadomo, że `bull_case`/`bear_case`/`why_market_may_be_right`/`why_this_may_not_be_a_bargain` przeszły walidację na obu próbach (błąd nazwałby wcześniejsze pole, gdyby zawiodło) — zawodziło konsekwentnie TYLKO `thesis_invalidation`.

Mechanika bugfixu (semantic completeness gate, bounded retry, FAILED≠COMPLETE, telemetria, nietkniętość historycznego runu) zadziałała dokładnie zgodnie z projektem — zero fałszywego COMPLETE. Zero tuningu na podstawie treści tych 5 analiz. Pełne szczegóły: patrz „Faza 6g" niżej (ROOT CAUSE AUDIT + fix tego konkretnego problemu).

---

## Faza 6g — ROOT CAUSE AUDIT + fix: thesis_invalidation semantycznie pusty, v1.64

**Decyzja właścicielki 2026-10-06:** najpierw audyt BEZ zmian kodu, fix tylko jeśli root cause jest jednoznaczny (nie zgadywany). Explicite zakazane: poluzowanie semantic completeness/progu 15 znaków, zmiana MAX_ANALYSIS_ATTEMPTS (zostaje 2), zmiana metodologii/scoringu/DCF/modelu/thinking.

### 1. Audyt (KROK 1) — jednoznaczny, dwuczęściowy root cause

**A/C** `thesis_invalidation: list[str] = Field(default_factory=list)` (`analysis_schema.py`) — schemat JSON (`output_format`) NIE ma `min_length`/`minItems`, więc strukturalnie dopuszcza `[]` jako w pełni poprawną odpowiedź.

**B/E** Instrukcja promptu (przed fixem) opisywała tylko JAKOŚĆ treści ("konkretne, obserwowalne warunki... nie ogólne 'jeśli sytuacja się pogorszy'") — **nigdy nie mówiła wprost "musisz podać co najmniej jeden"**. Dla kontrastu, `why_market_may_be_right`/`why_this_may_not_be_a_bargain` (też `list[str]`, też wymagane) mają explicite fallback: "Jeśli nie widzisz dobrego argumentu, napisz to wprost" — instrukcję, co zrobić pod niepewnością, zamiast zwrócić pustą listę. `thesis_invalidation` takiego fallbacku nie miało.

**F** Ogólna zasada anty-halucynacyjna w ZASADACH ("Jeśli czegoś nie wiesz z dostarczonych danych, napisz to wprost... zamiast zgadywać") jest słuszna i wartościowa dla innych pól, ale bez pola-specyficznego override dla `thesis_invalidation` prawdopodobnie była nadinterpretowana jako "zwróć pustą listę" dla TEGO JEDNEGO pola — stąd 100% powtarzalność problemu w 4/4 przypadkach.

**D** Niespójność: schemat JSON (dopuszcza `[]`) + instrukcja promptu (opisuje jakość, nie kardynalność, bez fallbacku) + semantic validator (Faza 6f, jedyne miejsce wymuszające >=1, ale POST-HOC) — trzy warstwy nigdy nie mówiły modelowi tego samego w PRZÓD.

**G — retry był ŚLEPYM powtórzeniem.** Odczyt `_analyze_shortlist_and_report` (przed fixem): `prompt` budowany RAZ przed pętlą retry, identyczny `prompt` przekazywany do `generate_analysis` na KAŻDEJ próbie (1 i 2) — zero informacji o tym, co konkretnie zawiodło. Jedyna szansa powodzenia drugiej próby to czysty los próbkowania modelu, nie korekta systematycznej tendencji — co w pełni wyjaśnia 100% powtarzalność (4/4 FAILED z identycznym powodem na OBU próbach, nie losowo różnym).

**Wniosek:** root cause jest JEDNOZNACZNY (potwierdzony przez bezpośredni odczyt kodu + 100% powtarzalność w realnym teście) — dwuczęściowy: (1) brak jawnego wymogu kardynalności + fallbacku w instrukcji promptu, (2) retry bez informacji zwrotnej.

### 2. Minimalny fix (KROK 2)

- **`prompt.py`**: instrukcja `thesis_invalidation` rozszerzona o jawny wymóg "MUSISZ podać co najmniej JEDEN" + przykładowe kategorie (utrata moat, pogorszenie FCF/marży, ryzyko regulacyjne, nieudana integracja, utrata klienta/udziału, pogorszenie KPI) + jawny zakaz wymyślonych progów liczbowych ("jeśli dane nie uzasadniają konkretnego progu, sformułuj warunek jakościowo"). Zero zmiany schematu JSON/typu pola (zostaje `list[str]`, zero `min_length`) — fix WYŁĄCZNIE tekstowy.
- **`cli.py`**: nowa `_append_validation_retry_feedback(prompt, validation_error)` — na próbie > 1 dołącza do promptu treść `AnalysisValidationError` z próby poprzedniej (ta sama wiadomość, która już nazywa zawodzące pole) + jawne żądanie poprawionej, kompletnej odpowiedzi. `MAX_ANALYSIS_ATTEMPTS` pozostaje `2`. Semantic validator (`analysis_schema.py`, próg 15 znaków) — **nietknięty**.

### 3. Testy

4 nowe/rozszerzone testy: prompt jawnie wymaga >=1 warunku + zakazu wymyślonych progów (`test_prompt.py`); `_append_validation_retry_feedback` niesie konkretny powód i NIE jest identyczny z oryginałem (`test_cli.py`, bezpośredni test funkcji); rozszerzony test retry z Fazy 6f potwierdza na żywym przebiegu: 2 realne prompty różne, drugi zawiera dokładny komunikat błędu z pierwszego, `MAX_ANALYSIS_ATTEMPTS==2`, status FAILED po wyczerpaniu prób, telemetria obu prób zsumowana. Pełny zestaw: **655 passed, 1 skipped** (było 653).

### 4. STOP

Zero zmian scoringu/wag/hard gates/DCF/growth caps/decline screening/prefilter/deterministic ranking/TOP-20/final selection/modelu Claude/`thinking`/progu semantic-empty (15 znaków)/source methodology — potwierdzone diffem (2 pliki produkcyjne: `cli.py`, `prompt.py`; `analysis_schema.py` NIETKNIĘTY). Historyczne runy `live-scan-2026-10-06T083825543395Z` i `validation-6f-2026-10-06T110249722378Z` nietknięte. Zero nowych (płatnych) wywołań Claude API w tej fazie. Zero pełnego live runu, zero V1 — decyzja o ponownym LIVE VALIDATION TEST (sprawdzenie, czy fix realnie poprawia wskaźnik COMPLETE) należy do właścicielki.

---

## Faza 6g (uzupełnienie) — DRUGI LIVE VALIDATION TEST po fixie `bdfcc92`, v1.65

**Decyzja właścicielki 2026-10-06:** po akceptacji implementacji `bdfcc92` (Faza 6g fix: jawny wymóg >=1 w promptcie + retry z konkretnym feedbackiem), jeden LIVE VALIDATION TEST tych samych 5 finalistów (CBOE/PAYX/DECK/INTU/ACN), cel: operacyjna walidacja fixu. Ta sama mechanika jednorazowej diagnostyki co pierwszy test (osobny `run_id`, prefix `validation-6g-`, `run_date` z sufiksem `-validation6g` żeby `cache_key` nie trafił w cache — `run_id=validation-6g-2026-10-06T135943366372Z`), historyczny run tylko odczytany.

**Wynik: NADAL tylko 1/5 COMPLETE, 4/5 FAILED** — identyczny symptom co w pierwszym teście (`thesis_invalidation` semantycznie pusty), tym razem na obu próbach retry mimo konkretnego feedbacku o tym, które pole zawiodło. **10 pełnych Claude calls dla 5 analiz** (1 lub 2 na kandydata, jak w pierwszym teście) — innymi słowy fix z Fazy 6g (jawny wymóg kardynalności w promptcie + retry z feedbackiem) **nie poprawił wskaźnika COMPLETE względem pierwszego testu**, mimo że oba elementy audytu (brak jawnego wymogu, ślepy retry) zostały poprawione dokładnie zgodnie z preferowaną architekturą właścicielki. Które konkretne tickery przeszły/zawiodły różniło się między dwoma testami (nie te same 4 za każdym razem) — ale symptom (pusty `thesis_invalidation`) pozostał identyczny w 100% niepowodzeń w obu testach.

**Wniosek architektoniczny właścicielki:** dwa niezależne, realne testy empiryczne (różne konkretne tickery, ten sam symptom) wystarczają, by uznać **full-analysis retry za niewłaściwy mechanizm naprawczy dla pojedynczego brakującego pola** — ani ślepy retry (Faza 6f), ani retry z konkretnym feedbackiem o zawodzącym polu (Faza 6g) nie rozwiązuje problemu niezawodnie. Zamiast kolejnej iteracji na tym samym mechanizmie: zastąpienie go TARGETED FIELD REPAIR — patrz „Faza 6h" niżej. Zero zmian kodu w ramach samego testu — fix dopiero w Fazie 6h, po tym wyniku.

---

## Faza 6h — TARGETED FIELD REPAIR dla `thesis_invalidation`, v1.65

**Decyzja właścicielki 2026-10-06** (po drugim LIVE VALIDATION TEST wyżej): "full-analysis retry jest niewłaściwym mechanizmem naprawczym dla pojedynczego brakującego pola." Zamiast kolejnej zmiany promptu/retry: TARGETED FIELD REPAIR — wąsko-zakresowy, dodatkowy call naprawiający WYŁĄCZNIE `thesis_invalidation`, z twardym limitem 1 full call + 1 repair call na ticker, bez generalizacji na inne pola. Explicite zakazane: zmiana semantic-empty threshold (15 znaków), metodologii/scoringu/wag/hard gates/DCF/growth caps/decline screening/prefiltra/deterministic ranking/TOP-20/modelu Claude/`thinking`. Przed implementacją oceniono koszt wdrożenia (wymóg właścicielki, punkt 6 specyfikacji): wzorzec (nowe nullable kolumny DB + migracje, nowe dataclassy mirror'ujące istniejące, nowe funkcje budujące prompt) jest już 3-krotnie ustalony w projekcie — mała, lokalna zmiana, nie przebudowa persistence/cache/schema — więc zaimplementowano od razu, bez zatrzymywania się.

### 1. Nowy flow

Stage 2 (`_analyze_shortlist_and_report`): (1) dokładnie 1 pełne wywołanie `generate_analysis`. (2) Walidacja pełnym, istniejącym `validate_analysis_output`. (3) Przechodzi od razu → `COMPLETE`. (4) Nie przechodzi, ale `is_only_thesis_invalidation_semantically_empty(result)` (nowa funkcja, `analysis_schema.py`) zwraca `True` — czyli WSZYSTKIE pozostałe wymagane pola (`bull_case`/`bear_case`/`why_market_may_be_right`/`why_this_may_not_be_a_bargain`/`biggest_unknown`) są semantycznie niepuste, zawodzi WYŁĄCZNIE `thesis_invalidation` — → dokładnie 1 dodatkowe wywołanie `repair_thesis_invalidation` z minimalnym promptem (`build_thesis_invalidation_repair_prompt`: ticker, istniejąca treść `bull_case`/`bear_case`/`biggest_unknown`/`why_market_may_be_right`/`why_this_may_not_be_a_bargain`, deterministyczne metrics/current_price/decline/valuation — **bez** źródeł/cytowań, bo `thesis_invalidation` nie ma wymogu cytowania). (5) Repaired `thesis_invalidation` scalone w ORYGINALNĄ analizę przez `model_copy(update={"thesis_invalidation": ...})` — żadne inne pole nie jest dotykane. (6) Pełny `validate_analysis_output` uruchomiony PONOWNIE na scalonym obiekcie — dopiero to decyduje o `COMPLETE`/`FAILED`, nigdy sam fakt wykonania repair. (7) Repair też zwraca semantycznie pustą wartość → `FAILED`, **bez drugiego repair**. (8) Każdy INNY błąd walidacji (strukturalny, LUB jakiekolwiek inne pole semantycznie puste, w tym `thesis_invalidation` + inne pole naraz) → **zero repair, prosto do `FAILED`** — `is_only_thesis_invalidation_semantically_empty` sprawdza wszystkie 6 pól niezależnie (nie zatrzymuje się na pierwszym naruszeniu jak `validate_analysis_output`), więc nigdy nie przepuszcza wieloproblemowego przypadku do repair. Twardy limit: maksymalnie 1 full call + 1 repair call na ticker, zawsze.

### 2. Co usunięto/zastąpiono

Usunięto całkowicie (Faza 6f/6g, empirycznie nieskuteczne na dwóch niezależnych realnych testach): `MAX_ANALYSIS_ATTEMPTS` (pętla retry pełnej analizy), `_append_validation_retry_feedback` (dołączanie feedbacku do pełnego promptu), `_sum_claude_usage` (sumowanie usage wielu prób pełnej analizy — niepotrzebne, skoro pełna analiza to teraz zawsze dokładnie 1 wywołanie). Zastąpione przez: dokładnie 1 full call, warunkowo dokładnie 1 repair call, telemetria obu WYRAŹNIE rozdzielona (nie sumowana w jedną liczbę).

### 3. Schema targeted repair

`analysis_schema.py`: nowy, minimalny pydantic model `ThesisInvalidationRepair(BaseModel)` — WYŁĄCZNIE jedno pole `thesis_invalidation: list[str] = Field(default_factory=list)`, bez `verification_items`/`cited_source_ids`/żadnego innego pola `AnalysisOutput`. Wymuszone strukturalnie przez `output_format=ThesisInvalidationRepair` (`client.messages.parse`) — repair call fizycznie nie może zwrócić/zmienić żadne inne pole. Nowa funkcja `is_only_thesis_invalidation_semantically_empty(result: AnalysisOutput) -> bool` decyduje, czy repair jest w ogóle zasadny (patrz punkt 1, krok 8).

### 4. Merge + final validation

`cli.py`: `generated.output.model_copy(update={"thesis_invalidation": repaired.output.thesis_invalidation})` — pydantic `model_copy` tworzy nowy obiekt z JEDNYM polem podmienionym, wszystkie pozostałe pola (w tym zagnieżdżone sekcje `ScoredSection`/`MoatSection`/itd.) pozostają bajt-identyczne z oryginalnej pełnej analizy. Scalony obiekt przechodzi przez TEN SAM `validate_analysis_output`, który sprawdza WSZYSTKIE reguły (strukturalne i semantic completeness) od nowa na całości — repair nie ma specjalnej ścieżki walidacji, więc nie może "oszukać" kontraktu.

### 5. Audyt/telemetria repair call

`db.py`: 7 nowych nullable kolumn `llm_repair_response_model`/`llm_repair_input_tokens`/`llm_repair_output_tokens`/`llm_repair_cache_creation_input_tokens`/`llm_repair_cache_read_input_tokens`/`llm_repair_thinking_tokens`/`llm_repair_service_tier` na `analyses` i `live_scan_candidates` (ten sam wzorzec `_COLUMN_MIGRATIONS` co Faza 6e, 3. użycie), ODRĘBNE od istniejących `llm_*` (usage pełnego call) — `NULL`, gdy repair nie był potrzebny/wywołany. `update_live_scan_candidate_llm_status` dostał nowy opcjonalny parametr `repair_usage`. `get_live_scan_run_usage_summary` liczy i raportuje `repair_calls`/`total_repair_input_tokens`/`total_repair_output_tokens`/itd. ODDZIELNIE od `calls_with_usage`/`total_input_tokens`/itd. — CLI wypisuje obie linie telemetrii osobno ("Telemetria Anthropic API usage" + "Targeted repair calls (thesis_invalidation): N, repair input_tokens: X, repair output_tokens: Y"), nigdy scalone w jedną liczbę, żeby audyt zawsze mógł odróżnić full_analysis_call od thesis_invalidation_repair_call.

### 6. Testy

20 nowych/rozszerzonych testów, zero sieci/płatnych wywołań Claude:
- `test_analysis_schema.py`: `is_only_thesis_invalidation_semantically_empty` — `True` dla izolowanego przypadku (tylko thesis_invalidation puste), `False` gdy już poprawne, `False` gdy KTÓREKOLWIEK inne wymagane pole (sparametryzowane po wszystkich 4 pozostałych list-fields) LUB `biggest_unknown` też puste (Test D), `True` dla placeholder-only; `ThesisInvalidationRepair` akceptuje minimalny payload.
- `test_prompt.py`: repair prompt niesie istniejącą treść analizy + ten sam jawny wymóg kardynalności (współdzielona stała) + te same deterministyczne dane cenowe/wyceny co pełny prompt; NIGDY nie wspomina źródeł/cytowań; jawne "NIEDOSTĘPNA" gdy brak kontekstu.
- `test_claude_client.py`: `repair_thesis_invalidation` zwraca `ClaudeRepairResult` z realnym usage, przekazuje `output_format=ThesisInvalidationRepair` (nigdy `AnalysisOutput`), dzieli identyczną obsługę błędów (`_parse`) z `generate_analysis` (refusal z realnym usage, itd.).
- `test_cli.py`: Testy A (czysta analiza → 0 repair calls), B (izolowany pusty thesis_invalidation → 1 full + 1 repair call, merge poprawny, COMPLETE, telemetria obu rozróżnialna: 950/140 full + 300/40 repair), C (repair też pusty → FAILED, bez drugiego repair, telemetria obu wywołań mimo FAILED zapisana), D (thesis_invalidation + biggest_unknown oba puste → ZERO repair calls, prosto FAILED), H (repair prompt niesie KONTEKST CENY I WYCENY, bez sekcji źródeł) — plus regresja potwierdzająca, że istniejące failure/resume/cache/telemetry testy (Faza 6c/6e/6f) pozostają zielone bez zmian.

Pełny zestaw: **673 passed, 1 skipped** (było 655).

### 7. STOP

Zero zmian scoringu/wag/hard gates/DCF/growth caps/decline screening/prefiltra/deterministic ranking/TOP-20/final selection/modelu Claude/`thinking`/progu semantic-empty (15 znaków)/source methodology/wartości i logiki samego `thesis_invalidation` (zmienia się WYŁĄCZNIE mechanizm techniczny uzyskania tego pola) — potwierdzone diffem (5 plików produkcyjnych: `analysis_schema.py`, `prompt.py`, `providers/claude.py`, `db.py`, `cli.py`). Historyczne runy `live-scan-2026-10-06T083825543395Z`, `validation-6f-2026-10-06T110249722378Z`, `validation-6g-2026-10-06T135943366372Z` nietknięte — nowy mechanizm obowiązuje wyłącznie przyszłe analizy. Zero nowych (płatnych) wywołań Claude API w tej fazie — implementacja + testy lokalne WYŁĄCZNIE. Zero pełnego live runu, zero V1 — decyzja o LIVE VALIDATION TEST tego mechanizmu należy do właścicielki.

---

## Faza 7 — UI + PORTFOLIO V0, v1.66 (w budowie)

**Decyzja właścicielki 2026-10-06:** Buffett Opportunity Scanner przestaje być tylko projektem technicznym — potrzebny prosty, praktyczny interfejs (Streamlit) do codziennego podejmowania decyzji przez właścicielkę i jej męża, plus minimalny multi-user portfolio tracking (transakcje/pozycje/decyzje), bez auth, bez zmiany metodologii inwestycyjnej. Pełny audyt (stan obecny, proponowana architektura, data model, multi-user, brokers, currencies, current prices, pliki, implementation plan, blokery) wykonany i zaakceptowany PRZED implementacją — patrz transkrypt sesji; nie duplikowany tu w całości. Zaakceptowane korekty właścicielki do audytu: `run_id LIKE 'live-scan-%'` (ignorując `validation-*`) jako jedyna reguła wyboru "ostatniego właściwego skanu" na V0 (bez nowej kolumny `run_type`); UI pokazuje najnowszy właściwy live-scan niezależnie od jego `status` (COMPLETE/INCOMPLETE_LLM_ANALYSIS), per-kandydat "Analiza jakościowa niekompletna" dla FAILED, nigdy jako ocena spółki; `purchase_transactions`/`sale_transactions` (NIE jedna tabela `transactions`) + nowe `broker`/`acquisition_type`; shares liczone per (user, position, broker) PRZED agregacją do łącznej ekspozycji (SELL na jednym brokerze nigdy nie tworzy ujemnej subpozycji na innym); `positions.cik` NULLABLE (portfel nie jest ograniczony do SEC/S&P500); `users` NIE jest automatycznie seedowane "Anastazja"/"Mąż" — jawny, prosty setup.

### KROK 0 — Streamlit tabs spike (empirycznie zweryfikowany, 2026-10-06)

Zainstalowano `streamlit==1.65.0` + jednorazowo `playwright` (tylko do tego testu, odinstalowany po użyciu — nie jest zależnością aplikacji) i realny headless Chromium z tego środowiska. Zbudowano minimalny, jednorazowy spike (`st.tabs()` zagnieżdżone: zakładka zewnętrzna PORTFEL → zakładki wewnętrzne PODSUMOWANIE/AAPL/GSK + przycisk w zakładce wewnętrznej + przycisk na poziomie strony poza zakładkami) i sterowano nim realnym Chromium przez Playwright (klik, nie zgadywanie z dokumentacji/pamięci modelu — API Streamlit zmienia się między wersjami).

**Wynik — WSZYSTKIE 3 testowane scenariusze potwierdzają stabilność natywnych zagnieżdżonych `st.tabs()`:**
1. Zagnieżdżone `st.tabs()` (taby w tabie) renderują się i są klikalne bez błędu.
2. Kliknięcie przycisku WEWNĄTRZ zagnieżdżonej zakładki (AAPL) → rerun skryptu → zakładka AAPL **pozostaje aktywna** (nie resetuje się do pierwszej).
3. Kliknięcie przycisku POZA wszystkimi zakładkami (pełny rerun strony) → zarówno zakładka zewnętrzna (CBOE), jak i zagnieżdżona (AAPL) **pozostają aktywne**.

**Decyzja:** używamy natywnego `st.tabs()`, zagnieżdżonego dwupoziomowo ([PORTFEL/kandydaci] → [PODSUMOWANIE/pozycje]), zgodnie z pierwotnym planem UI. Fallback na `st.radio(horizontal=True)` NIE jest potrzebny — historyczne ograniczenie Streamlit (resetowanie zakładek przy rerunie) nie reprodukuje się w `1.65.0`. Spike usunięty po użyciu (katalog `/tmp`, nigdy niecommitowany) — jedyny trwały artefakt to ta notatka + nowa zależność `streamlit>=1.65,<2` w `requirements.txt`.

Zero zmian kodu produkcyjnego scanner'a w tym kroku. Zero nowych wywołań Claude API. Zero zmian danych.

### KROK 1 — data model (zrobiony)

Nowe tabele `user_decisions`/`positions`/`purchase_transactions`/`sale_transactions`/`purchase_thesis`/`holding_user_actions`, dokładnie schemat z sekcji 1.1/16 wyżej, z dwoma zatwierdzonymi rozszerzeniami: `broker` (`TRADE_REPUBLIC`/`REVOLUT`/`OTHER`) na obu tabelach transakcji, `acquisition_type` (`BUY`/`BONUS`) na `purchase_transactions`, `positions.cik` NULLABLE. `watchlist` celowo nieimplementowane w V0 (`user_decisions` w pełni pokrywa decyzje kandydatów — brak dziś realnej potrzeby `added_price`/`next_review_trigger`). `sale_transactions.cost_basis_method_used` zarezerwowane (zgodność ze schematem docelowym), NIE czytane przez V0 — `ui/portfolio.py` liczy cost basis wyłącznie metodą average-cost. 13 nowych testów `test_db.py`. Pełny zestaw: **686 passed, 1 skipped** (było 673).

### KROK 2 — read-only queries + liczenie pozycji "on-read" (zrobiony)

`buffett_scanner/ui/portfolio.py` (zero I/O, czyste funkcje): `compute_broker_currency_subpositions` grupuje transakcje po (broker, currency) i przetwarza je **chronologicznie** (scalony, sortowany po dacie stream zakupów+sprzedaży — nie "najpierw wszystkie zakupy, potem wszystkie sprzedaże"), żeby sprzedaż zawsze redukowała `invested` względem bazy akcji posiadanej W MOMENCIE sprzedaży (average cost), nigdy względem późniejszych zakupów. SELL na jednym brokerze nigdy nie dotyka subpozycji innego brokera (Decyzja właścicielki, Faza 7 pkt 4) — potwierdzone testem z BONUS na Trade Republic nietkniętym przez SELL na Revolut. Waluty nigdy sumowane — wszystkie pieniężne wyniki to słowniki `{currency: value}` (`merge_currency_dicts`).

`buffett_scanner/ui/queries.py`: `get_latest_live_scan_run` — `run_id LIKE 'live-scan-%'`, ignoruje `validation-*` (potwierdzone testem z "nowszym" wpisem walidacyjnym, który mimo to NIE jest wybierany). `get_synthesis_rows` — jeden wiersz per finalista shortlisty niezależnie od `llm_status` (FAILED zachowuje deterministyczne dane/cenę/wycenę, tylko pola jakościowe są `None`). `get_current_price_for_position` — ostatni dzienny close z `price_daily` dla pozycji z `cik`; `(None, None)` dla pozycji bez `cik` (np. Schneider Electric) — nigdy zgadywana cena. 16 nowych testów (`test_ui_portfolio.py`, `test_ui_queries.py`), w tym test na nieprawidłową (purchases-then-sales) kolejność, który by wykrył błąd w average-cost, gdyby się wkradł. Pełny zestaw: **702 passed, 1 skipped** (było 686).

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
- **2.2 Source packet** — `buffett_scanner/sources.py`: `build_sec_source_packet` to jedyne miejsce tworzące zweryfikowane źródła (implementacja RULE 1/BLOCKER 3 z sekcji 9). Dla każdego filingu: `SecEdgarClient.build_filing_url` buduje deterministyczny URL wg wzoru z sekcji 10 (`https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-bez-myślników}/{primary-document}` — **link buduje kod, nie LLM**), potem `fetch_and_hash_document` faktycznie pobiera dokument (HTTP 200) i liczy SHA-256 treści. Dokument, który nie da się pobrać, trafia do wyniku jako `verified=False` z opisem przyczyny w `reason` — nigdy nie znika po cichu (`SOURCE NOT VERIFIED`, sekcja 9/10). `VerifiedSource` odzwierciedla schemat `analysis_sources` z sekcji 5, ale **nie jest jeszcze zapisywany do bazy** — tabela `analysis_sources` ma `analysis_id FK`, który powstanie dopiero w Fazie 4 razem z `analyses` (silnikiem scoringu, który faktycznie potrzebuje trwałego przechowywania wyników); dopisanie go teraz rozszerzałoby schemat przed czasem. **Korekta względem pierwotnego zapisu w tym akapicie:** Faza 3 (patrz niżej) okazała się dry-runem diagnostycznym, tak jak faktycznie opisuje ją sekcja 15 — `analyses`/`analysis_sources` nadal nie istnieją po Fazie 3, dopiero Faza 4 je tworzy.
- **2.3 Allowlista domen IR** — mechanizm w configu (`sources.ir_allowlist`, model `IrAllowlistEntry` w `config.py`) gotowy, ale **celowo pusty**. Decyzja D9 (sekcja 9) wymaga, żeby każdy wpis był zweryfikowany przeciw oficjalnej stronie tytułowej 10-K danej spółki — dodanie tu domen IR dla AAPL/MSFT/KO z pamięci lub z wyników wyszukiwarki bez tej weryfikacji byłoby dokładnie tym, czego zasada „nie zgaduj" zabrania. Wypełnienie allowlisty prawdziwymi, zweryfikowanymi wpisami zostaje jako zadanie na moment, gdy któraś z testowych spółek faktycznie trafi do głębszej analizy (Faza 3+) i realnie będzie potrzebny dokument IR.

Nowa sekcja configu `sources.sec_edgar.user_agent_env_var` (SEC wymaga danych kontaktowych w nagłówku User-Agent — nie sekret w sensie bezpieczeństwa, ale mimo to poza configiem/repo, przez zmienną środowiskową, tym samym wzorcem co `FMP_API_KEY`). Rozszerzony `cli.py` o `build-source-packet TICKERS...`, nowy `sec_edgar_smoketest.py`, nowy workflow **„Phase 2 Proof Run"**.

**16 nowych testów jednostkowych, wszystkie zielone (87 razem).** Test SHA-256 liczy oczekiwany hash przez `hashlib.sha256(...).hexdigest()` bezpośrednio w teście, nie wpisany ręcznie z pamięci — zgodnie z zasadą, że wartości referencyjne muszą być niezależnie policzone, nie odtworzone z kodu pod testem.

**Uruchomienie „Phase 2 Proof Run" (2026-09-25, po dodaniu sekretu `SEC_EDGAR_USER_AGENT`) — PEŁNY SUKCES.** `init-db` → `ingest-prices AAPL MSFT KO --days 400` → `build-source-packet AAPL MSFT KO`. Dla każdej z trzech spółek: **4 źródła w source packet (2× 10-K + 2× 10-Q), wszystkie `[OK]`, zero `SOURCE NOT VERIFIED`** — 12/12 dokumentów łącznie. Przykład (AAPL, CIK 0000320193): `10-K (2024-11-01)` → `https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm`, `hash=37aeffd496784c5...`. Wszystkie URL-e mają realne numery accession SEC (nie testowe/fikcyjne), poprawnie usunięte myślniki i wiodące zera CIK w segmencie ścieżki, dokładnie wg wzoru z sekcji 10. Analogiczny wzorzec dla MSFT (CIK 0000789019) i KO (CIK 0000021344).

**Faza 2 formalnie ukończona (v1.13).** Kryterium wyjścia z sekcji 15 („Source Assembly Layer buduje wyłącznie zweryfikowane URL-e z hashem treści, działa end-to-end na próbce tickerów") spełnione na realnych danych z SEC EDGAR, bez żadnego zakupu (SEC EDGAR jest i pozostaje darmowy).

### Status Fazy 3 (v1.15) — empirycznie zweryfikowana i ukończona

Zaimplementowano oba punkty Fazy 3 z sekcji 15 (3.3 — podpięcie do silnika scoringu — należy właściwie do Fazy 4, bo silnik scoringu jeszcze nie istnieje):

- **3.1 Formalny JSON Schema + wrapper klienta Claude API** — `buffett_scanner/analysis_schema.py` definiuje `AnalysisOutput` jako pydantic model 1:1 ze schematem z sekcji 8 (business_understandability, moat, financial_quality_commentary — celowo bez pola `score`, bo to liczone deterministycznie w Fazie 4 — management_capital_allocation, fear_analysis, dividend_trap_alert, bull/bear case, verification_items, cited_source_ids, hard_flag_candidates). `buffett_scanner/providers/claude.py` (`ClaudeClient`) używa **oficjalnego SDK `anthropic`** (nie httpx — w przeciwieństwie do FMP/SEC EDGAR, które nie mają oficjalnego SDK, Anthropic ma, więc go używamy zamiast odtwarzać protokół) i wymusza kształt wyjścia przez `output_format=AnalysisOutput` (`client.messages.parse`) — to gwarantuje ze strony API, że JSON jest zgodny ze schematem; nigdy nie trzeba "naprawiać" źle sformatowanej odpowiedzi. `validate_analysis_output` sprawdza osobno trzy reguły relacyjne z sekcji 8, których sam schemat JSON nie wymusza: (1) `cited_source_ids` i każdy `source_id` w `verification_items`/`hard_flag_candidates` musi być podzbiorem listy źródeł faktycznie dostarczonej modelowi w tym wywołaniu, (2) `page` niepuste tylko dla źródła jawnie oznaczonego jako PDF z potwierdzoną paginacją (BLOCKER 4 — SEC HTML nigdy nim nie jest), (3) `score > max_score` lub `score < 0` → reject, nigdy clamp. Naruszenie którejkolwiek reguły odrzuca cały rekord (`AnalysisValidationError`), zgodnie z `config.llm.reject_on_schema_violation: true`.
- **3.2 Prompt v0 + dry-run** — `buffett_scanner/prompt.py` (`build_analysis_prompt`) łączy deterministyczne wskaźniki z Fazy 1 (`fundamentals.compute_metrics` + flagi prefiltra) i **wyłącznie zweryfikowane** źródła z Fazy 2 (niezweryfikowane nigdy nie trafiają do promptu — nie istnieją z perspektywy modelu, BLOCKER 3) w jeden tekst z jawnymi zasadami: cytuj tylko po `source_id` z listy, `page` zawsze `null` dla źródeł SEC HTML, nie zgaduj. `cli.py` dostał komendę `analyze TICKERS...`, która spina cały pipeline end-to-end: `ingest-fundamentals`+`prefilter` (Faza 1) → `build-source-packet` (Faza 2) → prompt → `ClaudeClient.generate_analysis` → `validate_analysis_output` → wydruk wyniku. To jest dosłownie "dry-run na 2-3 tickerach, ręczna ocena jakości" z sekcji 15 — diagnostyczny, **nie zapisuje jeszcze do bazy**.

Nowa sekcja configu `llm.api_key_env_var: ANTHROPIC_API_KEY` (ten sam wzorzec sekretu przez zmienną środowiskową co `FMP_API_KEY`/`SEC_EDGAR_USER_AGENT`). Nowa zależność `anthropic>=1.8,<2` w `requirements.txt` — pierwsza zależność zewnętrzna dodana od Fazy 0, uzasadniona tym, że Anthropic ma oficjalne, w pełni udokumentowane SDK (w przeciwieństwie do FMP, gdzie dokumentacja była niedostępna przez zablokowany WebFetch, więc surowe httpx + defensywne parsowanie było jedyną opcją). Nowy workflow **„Phase 3 Proof Run"**, domyślnie na **1 tickerze** (nie 3 jak poprzednie fazy) — to pierwsza faza, która realnie kosztuje (Claude API), więc dry-run celowo minimalizuje koszt pierwszego uruchomienia.

**27 nowych testów jednostkowych, wszystkie zielone (114 razem).** Klient Claude testowany przez podmianę `client._client.messages.parse` (ten sam wzorzec mockowania co FMP/SEC EDGAR — bez sieci, bez realnego kosztu API w testach jednostkowych).

**Zanim da się uruchomić „Phase 3 Proof Run": potrzebny nowy sekret repozytorium `ANTHROPIC_API_KEY`** (Settings → Secrets and variables → Actions → New repository secret) — klucz z [console.anthropic.com](https://console.anthropic.com), z aktywnym billingiem (to pierwsza faza z realnym kosztem, rzędu pojedynczych centów za dry-run na 1 tickerze przy `claude-sonnet-5`). Bez tego sekretu `analyze` zwróci czytelny błąd, dokładnie jak brak `FMP_API_KEY`/`SEC_EDGAR_USER_AGENT` we wcześniejszych fazach.

**Pierwsze uruchomienie „Phase 3 Proof Run" (2026-09-25, po dodaniu sekretu) — błąd, przyczyna zdiagnozowana i naprawiona.** Po realnym wywołaniu Claude API dla AAPL, `analyze` rzucił nieobsłużony wyjątek pydantic: `Invalid JSON: EOF while parsing a string at line 1 column 4832`. Przyczyna: `max_output_tokens: 4000` (wartość ilustracyjna z sekcji 6, nigdy nie przetestowana na realnej odpowiedzi) okazało się za mało — model nie zdążył dokończyć generowania pełnego JSON-a zgodnego ze schematem sekcji 8 (evidence lists, reasoning, bull/bear case itd. to sporo tekstu) w tym limicie, więc SDK dostał ucięty tekst i nie mógł go sparsować. To nie błąd konfiguracji sekretu ani kodu logiki — czysto kwestia zbyt ciasnego budżetu tokenów wyjściowych. Naprawione dwutorowo: (1) `llm.max_output_tokens` podniesione z 4000 do 16000 w `config.yaml`, (2) `ClaudeClient.generate_analysis` dostał dodatkowy `except Exception` łapiący dokładnie ten przypadek (SDK rzuca to jako błąd walidacji pydantic, nie `APIStatusError`/`APIConnectionError` — nie był wcześniej łapany przez żaden z dwóch obsługiwanych wyjątków) z czytelnym komunikatem po polsku zamiast surowego tracebacku. Nowy test (`test_generate_analysis_wraps_truncated_json_parse_failure`) odtwarza dokładnie ten błąd.

**Drugie uruchomienie „Phase 3 Proof Run" (2026-09-25) — sukces pipeline'u, ale znaleziony i naprawiony błąd jakości danych.** Po naprawie `max_output_tokens` cały pipeline zadziałał end-to-end na AAPL: `ingest-fundamentals` → `analyze` → poprawnie zwalidowana analiza. Treść merytorycznie mocna i konkretna (np. `fear_analysis`: UNCERTAIN, trafnie wskazane realne czynniki — spowolnienie wzrostu przychodów 6,4% r/r, presja regulacyjna App Store/antymonopol, pozycja w wyścigu AI; `cited_source_ids` użyło wszystkich 4 dostarczonych źródeł; `hard_flag_candidates: 0` — sensowne dla spółki bez oznak dystresu). **Ale:** `business_understandability` wróciło jako `9/10`, `moat` jako `8/10`, `management_capital_allocation` jako `7/10` — model po cichu przyjął własną skalę 1-10 zamiast stałych wag rubryki z sekcji 8 (`max_score` ma być zawsze 7/12/10, nie coś do wyboru przez model). To realny błąd, nie kwestia gustu: `9/10` dla business_understandability to w rzeczywistości `9 > 7`, czyli złamanie zakresu rubryki, którego moja własna walidacja (`validate_analysis_output`) nie złapała — sprawdzałam `score <= max_score`, ale porównywałam względem `max_score` **podanego przez sam model**, nie względem prawdziwej stałej z sekcji 8. Naprawione u źródła: `max_score` w `ScoredSection`/`MoatSection`/`ManagementSection` zmienione z `int` na `Literal[7]`/`Literal[12]`/`Literal[10]` — to wymusza stałą wartość już na poziomie JSON Schema przekazanego do Claude API (`output_format`), więc model fizycznie nie może zwrócić innej liczby, nie tylko że kod by to później odrzucił. Zweryfikowane bezpośrednio (`model_json_schema()` faktycznie generuje `"const": 7` itd.). Nowy test (`test_max_score_is_fixed_by_schema_not_chosen_by_model`). 116 testów zielonych, 1 integracyjny pominięty bez klucza w tej sesji (razem 117).

**Faza 3 formalnie ukończona (v1.15).** Kryterium „dry-run na 2-3 tickerach, ręczna ocena jakości" z sekcji 15 spełnione: pipeline działa end-to-end na realnych danych, jakość merytoryczna dobra, a znaleziony błąd (max_score) jest dokładnie tym, po co ten dry-run istniał — złapany i naprawiony przed Fazą 4, gdzie silnik scoringu faktycznie zsumowałby te punkty w finalny wynik.

### Status Fazy 4 (v1.17) — empirycznie zweryfikowana i ukończona

Przed implementacją, na wyraźną prośbę właściciela ("wejście do implementacji Fazy 4 z kompletną architekturą scoringu 100 pkt, zamiast implementowania teraz niepełnego scoringu i późniejszego łatania"), przedstawiono i zatwierdzono (2026-09-25) pełny design dwóch brakujących komponentów:

**Metodologia wyceny (zatwierdzona, z korektami właściciela):**
- Metoda: DCF na **Owner Earnings PROXY = FCF** z Fazy 1 (jawnie nazwane `owner_earnings_proxy_fcf` w kodzie/danych — uproszczenie względem pełnej klasycznej koncepcji Buffetta, do zastąpienia dokładniejszą metodologią później bez zmiany znaczenia historycznych wyników — korekta właściciela, punkt 3).
- Trzy scenariusze: BEAR/BASE/BULL, każdy z własnym discount rate i terminal growth rate — **wyłącznie z configu**, nigdy hardkodowane w kodzie jako stała (korekta właściciela, punkt 4). Wymóg matematyczny `terminal_growth < discount_rate` (model Gordona) wymuszony walidatorem configu.
- Tempo wzrostu w oknie projekcji **DERIVED z historycznej CAGR FCF spółki** (dane realne, nie zgadywane), skalowane mnożnikiem scenariusza, ograniczone sufitem/podłogą bezpieczeństwa z configu.
- Payout ratio liczony względem **FCF** (nie zysku netto); gdy FCF≤0 → jawny `NOT_MEANINGFUL`, nigdy myląca wartość ujemna (korekta właściciela, punkt 1).
- Hard gate `min_margin_of_safety_pct` sprawdzany względem scenariusza **BASE** (nie BEAR); BEAR/BULL pozostają jako dodatkowe, widoczne w raporcie wskaźniki konserwatywny/optymistyczny (korekta właściciela, punkt 2).
- Tylko `sector_profile=GENERAL` ma zaimplementowaną metodę teraz; BANK/INSURER/REIT: `NOT_YET_IMPLEMENTED` (Faza 10, Decyzja D7); BIOTECH ma odrębny pipeline rNPV (sekcja 18).

**Dividend/shareholder-return (zatwierdzony):** wymagało 3 nowych pól w Fazie 1 (`dividends_paid`, `share_buybacks`, `diluted_shares_outstanding`) z endpointów już zintegrowanych w Fazie 1 (income-statement/cash-flow-statement) — żadnego nowego wywołania FMP, tylko nowe pola z istniejących odpowiedzi. Wskaźniki: dividend per share, shareholder yield (dywidendy+buybacki / kapitalizacja), payout ratio (jak wyżej), wykrywanie cięcia dywidendy i trendu liczby akcji — oba jako `bool|None`/`Literal|None`, żeby brak danych nigdy nie fabrykował kredytu punktowego (rozróżnienie "potwierdzone dobrze" od "nie wiadomo").

**Zaimplementowane komponenty scoringu (sekcja 15, punkt 4.1):**
- `business_quality_score` (waga 45) — liniowe skalowanie sumy business_understandability+moat+management_capital_allocation (LLM, Faza 3, max zawsze 7+12+10=29 dzięki `Literal` z Fazy 3) do wagi configu.
- `financial_quality_score` (0-16, deterministyczny — sekcja 8: "LLM dostarcza tylko komentarz") → `safety_score` (waga 15) przez liniowe skalowanie 16→15. Sześć kryteriów opartych na wskaźnikach z Fazy 1 (FCF dodatni, margin zdrowy, niska dźwignia, dobra płynność, wzrost przychodów, brak persystentnych strat).
- `fear_opportunity_score` (waga 10) — macierz `classification × confidence` z Fazy 3, config-driven.
- `dividend_shareholder_return_score` (waga 10) — jak wyżej.
- `valuation_score` (waga 20) — mapowanie MoS (BASE) na punkty, piecewise liniowe do configowego sufitu `mos_pct_for_full_score`.
- **Hard gates** (punkt 4.2): `min_business_quality`/`min_financial_safety`/`min_margin_of_safety_pct`, wszystkie `UNCALIBRATED`/`null` domyślnie (nieaktywne) — sprawdzane niezależnie od `total_score`, nie wpływają na jego wartość.
- **`total_score`**: suma 5 ważonych komponentów, **`None` + `is_partial=True`**, gdy którykolwiek komponent niepoliczalny (np. wycena `NOT_YET_IMPLEMENTED`) — nigdy fałszywie kompletna liczba z brakujących danych (IMPORTANT backlog "Zachowanie PARTIAL ANALYSIS", FINAL PRE-IMPLEMENTATION STATUS).
- **Generator raportu Markdown** (punkt 4.3): `buffett_scanner/report.py` — tabela wyników, tabela wyceny BEAR/BASE/BULL, sekcja dividend/shareholder-return, sekcja jakościowa LLM.

**Nowe tabele DB (`scoring_model_versions`/`analyses`/`analysis_sources`):** IMMUTABLE, INSERT-only (sekcja 11) — `analyses.scoring_model_version` wskazuje na zamrożony snapshot wag/bramek, nie na "aktualny" config. `analysis_sources` domyka lukę zostawioną świadomie w Fazie 2 (`VerifiedSource` nie miał gdzie trafić, bo `analysis_id` jeszcze nie istniał) — teraz przechowuje WSZYSTKIE źródła z danego przebiegu (zweryfikowane i `SOURCE NOT VERIFIED`), nie tylko zweryfikowane.

Rozszerzony `cli.py` o `score TICKERS... [--markdown-out DIR]` — pełny pipeline: fundamenty+prefilter (Faza 1) → source packet (Faza 2) → Claude API (Faza 3) → scoring (Faza 4) → zapis do bazy → raport. Nowy workflow **„Phase 4 Proof Run"**.

**57 nowych testów jednostkowych, wszystkie zielone (172 razem, w tym 1 integracyjny pominięty bez klucza w tej sesji).** Kluczowy niezależny hand-check: przy zerowym wzroście i zerowym terminal growth, `enterprise_value` musi być dokładnie równe `owner_earnings/discount_rate` (wzór perpetuity) — niezależnie od `projection_years`. Test to potwierdza dla wszystkich trzech scenariuszy, co jest silniejszą weryfikacją niż samo odtworzenie formuły DCF w teście.

**Pierwsze uruchomienie „Phase 4 Proof Run" (2026-09-25) — pipeline zadziałał, ale dividend/shareholder-return wrócił pusty (`N/A` wszędzie).** Diagnoza przez surowy dump JSON (workflow „FMP Smoke Test", już istniejący z Fazy 1) zamiast kolejnego zgadywania: `share_buybacks`<-`commonStockRepurchased` i `diluted_shares_outstanding`<-`weightedAverageShsOutDil` były poprawne za pierwszym razem (potwierdzone: `share_count_trend` policzył się poprawnie jako `DECREASING`, zgodnie z rzeczywistością — AAPL agresywnie skupuje akcje). `dividends_paid`<-`dividendsPaid` było błędne: takiego pola w ogóle nie ma w odpowiedzi FMP. Prawdziwe pole to **`commonDividendsPaid`** (wybrane celowo zamiast `netDividendsPaid`, żeby DPS liczony na akcjach zwykłych wykluczał ewentualne dywidendy uprzywilejowane — AAPL akurat ma `preferredDividendsPaid: 0`, więc obie wartości były tu identyczne, ale semantycznie `common...` jest poprawnym wyborem). Naprawione w `normalize_fundamentals_rows`. Liczby po naprawie (ręczna weryfikacja z surowego JSON): dividend per share ≈ 1.03 USD, payout ratio (vs FCF) ≈ 15.6%, shareholder yield ≈ 2.1% przy cenie 339.55 — wszystkie realistyczne dla AAPL, silny sygnał poprawności poprawki.

**Silnik DCF na prawdziwych danych: działa, wyniki skrajne — zgodnie z oczekiwaniami dla `UNCALIBRATED` parametrów.** BASE margin of safety wyszedł -271,5% (cena 339,55 USD vs intrinsic value BASE 91,41 USD) — DCF uznaje AAPL za mocno przewartościowaną przy tych konserwatywnych, nigdy niekalibrowanych założeniach (discount rate 9% dla planu wzrostu wyprowadzonego z historycznej CAGR FCF). To nie błąd kodu — to dokładnie to, czego uczy sekcja 6: „nic nie jest domyślnie prawdą" dopóki backtesting (Faza 5) nie skalibruje progów. `valuation_score` poprawnie zwrócił `0.0` (podłoga dla ujemnego MoS), `hard_gates` poprawnie `PASSED` (progi wciąż `null`/nieaktywne).

**Faza 4 formalnie ukończona (v1.17).** Kryterium wyjścia z V0 (sekcja 15: „pełny pipeline działa end-to-end na próbce tickerów, generuje raport, bez dopracowanego UI") spełnione na realnych danych AAPL — pipeline liczy wszystkie 5 komponentów scoringu, stosuje hard gates, zapisuje IMMUTABLE wiersz do `analyses`/`analysis_sources`, generuje raport Markdown. Jedyny błąd znaleziony po drodze (nazwa pola dywidend) zdiagnozowany przez surowe dane, nie zgadywanie, i naprawiony w jednej rundzie.

---

### Status Fazy 5 (v1.20) — punkt 5.1 (OPEN BLOCKER 1) empirycznie potwierdzony i ukończony

Właściciel zatwierdził rozpoczęcie Fazy 5 ("Zaczynaj", 2026-09-25). Zgodnie z kolejnością z sekcji 15 (punkt 5.1) pierwszym, samodzielnym krokiem jest prototyp warstwy point-in-time (PIT) adresujący OPEN BLOCKER 1 — bez niego dalsze kroki Fazy 5 (5.2 — skład S&P 500, 5.3 — backtest) nie mają sensu, bo backtesting bez PIT ma wbudowany look-ahead bias.

**Zaimplementowane (kod + testy, jeszcze nie uruchomione na realnym koncie):**
- `SecEdgarClient.get_company_facts(cik)` — nowa metoda w `providers/sec_edgar.py`, pobiera pełny zestaw faktów XBRL spółki z SEC EDGAR (`data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json`). Każdy fakt niesie pole `filed` (data faktycznego złożenia) — to jest fundament PIT: pozwala odtworzyć „jaka była ostatnia wartość X *filed* na dzień ≤ D", zamiast dzisiejszego, już skorygowanego widoku, jaki dają komercyjni dostawcy (FMP itp.).
- Nowy moduł `buffett_scanner/point_in_time.py` (czysta logika, zero I/O):
  - `extract_fact_history(company_facts, tag, unit="USD")` — parsuje i sortuje historię faktów dla danego tagu XBRL; brakujący tag → `[]`, nigdy błąd; wpisy bez `end`/`val`/`filed` pomijane, nigdy uzupełniane zgadywaną wartością.
  - `find_first_matching_tag(company_facts, canonical_concept)` — różne spółki tagują to samo pojęcie księgowe różnymi tagami XBRL (np. `Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax`); funkcja próbuje uporządkowanej listy kandydatów (`CANDIDATE_TAGS`) per pojęcie kanoniczne (obecnie: `net_income`, `revenue`) i **zwraca, który tag faktycznie zadziałał** — nigdy nie zakłada jednego uniwersalnego tagu.
  - `value_as_of(fact_history, as_of_date)` — rdzeń PIT: zwraca najpóźniej złożony (`filed`) fakt, którego `filed` ≤ `as_of_date` (włącznie); remis na `filed` rozstrzygany na korzyść najnowszego `end` (naprawione w v1.19 — patrz niżej).
- Test `test_value_as_of_restatement_scenario_avoids_look_ahead_bias` demonstruje samo uzasadnienie PIT: spółka zgłasza 100 (filed 2020-02-01), potem koryguje do 105 w tym samym okresie sprawozdawczym (filed 2021-03-01, formularz 10-K/A). Zapytanie symulujące decyzję na 2020-06-01 musi zobaczyć oryginalne 100 (nie 105) — inaczej backtest korzystałby z wiedzy z przyszłości. Zapytanie na 2021-06-01 poprawnie widzi już 105.
- Nowa komenda CLI `pit-prototype TICKERY... [--as-of YYYY-MM-DD]` (`cmd_pit_prototype` w `cli.py`) — dla każdego tickera: pobiera company-facts z SEC EDGAR, wykonuje zapytanie PIT dla `net_income` i `revenue` na zadaną datę (domyślnie dziś), i dla porównania wypisuje odpowiadającą wartość „as reported" z FMP (Faza 1, jeżeli `ingest-fundamentals` był wcześniej uruchomiony) — czysty sanity-check rzędu wielkości, nie formalna walidacja zgodności.
- Nowy workflow **„Phase 5.1 Proof Run"** (`.github/workflows/phase5-1-proof-run.yml`) — żadnego nowego sekretu (te same `FMP_API_KEY`/`SEC_EDGAR_USER_AGENT` co Fazy 2–4).

**14 nowych testów (Faza 5.1, pierwotnie), wszystkie zielone (185 passed, 1 skipped = 186 razem):** 12 w `test_point_in_time.py` (parsowanie/sortowanie historii faktów, brakujący tag, wpisy z brakującymi polami, zły `unit`, kolejność fallback kandydatów tagów, nieznane pojęcie, inkluzywna granica `value_as_of`, brak wartości przed pierwszym `filed`, i kluczowy test restatement powyżej) + 2 w `test_sec_edgar.py` (`get_company_facts` — parsowanie JSON i błąd na status≠200).

**Pierwsze uruchomienie „Phase 5.1 Proof Run" (2026-09-25) na koncie właścicielki — pipeline zadziałał technicznie, ale ujawnił realny błąd logiki, nie tylko brakujące dane.** Dla wszystkich trzech spółek (AAPL/MSFT/KO) zwrócona wartość PIT miała `end` ewidentnie starszy niż uzasadniałby `filed` — dla MSFT nawet o 2 lata (`end=2024-06-30`, `filed=2026-07-29`), mimo że 10-K/10-Q musi trafić do SEC w ciągu maks. ~60–90 dni od `end`. Diagnoza (bez zgadywania): przyczyna to remis na `filed` w `value_as_of` — jeden 10-K/10-Q zawsze zawiera też dane porównawcze z 1–2 poprzednich okresów, złożone tego samego dnia co okres bieżący; `max()` po samym `filed` przy remisie zwracał pierwszy napotkany fakt z JSON-a SEC (stary okres porównawczy), nie okres z najnowszym `end`. **Hipoteza zweryfikowana niezależnie**, nie tylko wywnioskowana: syntetyczny test ze starą wersją funkcji, na danych ułożonych dokładnie jak scenariusz MSFT (trzy lata podatkowe, ten sam `filed`), zwrócił dokładnie tę samą wartość co w realnym uruchomieniu (88136000000 USD) — potwierdzenie przyczyny źródłowej, nie domysł.

**Naprawione (v1.19):** remis na `filed` rozstrzygany teraz na korzyść najnowszego `end`. Nowy test regresyjny `test_value_as_of_breaks_filed_tie_by_latest_end_not_json_order` odtwarza dokładnie scenariusz MSFT z realnego przebiegu — 187 testów razem (186 passed + 1 integracyjny pominięty), zielone po naprawie.

**Drugie uruchomienie „Phase 5.1 Proof Run" (2026-09-25) na naprawionym kodzie — sukces, mechanizm PIT potwierdzony na realnych danych.** Dla wszystkich trzech spółek `end` jest teraz w rozsądnej odległości od `filed` (dni–tygodnie, zgodnie z terminami SEC), nie lata jak przed naprawą:
- AAPL: net_income/revenue, `end=2026-06-27`, `filed=2026-07-31` (34 dni — normalny termin 10-Q).
- MSFT: net_income/revenue, `end=2026-06-30`, `filed=2026-07-29` (29 dni — normalny termin 10-K).
- KO: net_income/revenue, `end=2026-04-03`, `filed=2026-04-30` (27 dni — normalny termin 10-Q).

**MSFT dał dokładne (co do dolara) potwierdzenie krzyżowe między dwoma niezależnymi źródłami danych:** PIT z SEC XBRL (`net_income=133749000000`, `revenue=331839000000`, oba z 10-K FY2026) są **identyczne co do jednostki** z danymi „as reported" z FMP (Faza 1) dla tego samego okresu (`period_end_date=2026-06-30`). To silny, niezależny dowód, że zarówno naprawiona ekstrakcja PIT z SEC EDGAR, jak i wcześniej potwierdzone mapowanie pól FMP (Faza 1), poprawnie odczytują tę samą rzeczywistość finansową z dwóch osobnych źródeł.

**Dla AAPL i KO porównanie pozostaje rzędu wielkości, nie dokładnym dopasowaniem — zgodnie z zapowiedzianym ograniczeniem prototypu, ale z nową, wartą odnotowania obserwacją.** KO: PIT (kwartalny, 10-Q) to ~26–30% wartości rocznej FMP — zgodne z oczekiwaniem dla pojedynczego kwartału (~25% roku). AAPL: PIT to ~88–91% wartości rocznej FMP — dużo więcej niż jeden kwartał. Najbardziej prawdopodobne wyjaśnienie (nie zweryfikowane dodatkowym zapytaniem, bo poza zakresem prototypu): tag `NetIncomeLoss`/`Revenues` w 10-Q może reprezentować wartość **skumulowaną od początku roku fiskalnego** (np. 9 miesięcy), nie pojedynczy kwartał — `PitFact` nie przechowuje obecnie daty `start` kontekstu XBRL, więc nie odróżnia faktu kwartalnego od skumulowanego YTD dzielącego to samo `end`. To realne, praktyczne ograniczenie do adresowania w Fazie 5.3 (silnik backtestu), gdzie dokładne dopasowanie okresu będzie już wymagane — nie blokuje zamknięcia prototypu 5.1, którego jedynym celem było udowodnienie mechanizmu PIT (poprawny wybór faktu wg `filed`, bez look-ahead bias), nie dokładnej rekoncyliacji okresów.

**Faza 5.1 formalnie ukończona (v1.20).** OPEN BLOCKER 1 przechodzi ze statusu „metoda wybrana, prototyp niewykonany" na „metoda potwierdzona empirycznie na realnych danych 3 spółek, z jednym udokumentowanym ograniczeniem (rozróżnianie duration kontekstu XBRL) do adresowania przy budowie właściwego silnika backtestu w Fazie 5.3".

---

### Plan Fazy 5.2 (v1.21) — porównanie źródeł historycznego składu S&P 500 — DO ZATWIERDZENIA, KOD JESZCZE NIEPISANY

Na wyraźną prośbę właściciela: przed jakąkolwiek implementacją przedstawiony jest pełny plan porównania źródeł danych do historycznego składu S&P 500 (OPEN BLOCKER 2). Poniższe fakty pochodzą z realnego sprawdzenia (WebSearch/WebFetch dokumentacji FMP, repozytorium `fja05680/sp500` na GitHub — README, format plików, przykładowe wiersze) wykonanego w tej sesji, nie z pamięci — tam, gdzie czegoś nie udało się potwierdzić bezpośrednio (np. `site.financialmodelingprep.com` jest zablokowane przez proxy sieciowe w tym środowisku, więc dokładny kształt JSON i wymagany tier planu FMP pochodzą tylko z wtórnych źródeł/wzmianek, nie z oficjalnej strony), jest to jawnie oznaczone jako NIEPOTWIERDZONE.

**Zastrzeżenie ramowe, ważniejsze niż wybór między dwoma źródłami:** nie istnieje darmowe ani tanie źródło pierwotne dla tych danych. Przynależność do S&P 500 to redakcyjna decyzja prywatnej firmy (S&P Dow Jones Indices) — w odróżnieniu od danych finansowych (Fazy 0–5.1), gdzie SEC EDGAR jest bezpłatnym, autorytatywnym źródłem pierwotnym, tu **każde** dostępne nam źródło (FMP, fja05680, Wikipedia) jest wtórną rekonstrukcją. Realistyczny cel Fazy 5.2 to nie „znaleźć to jedno prawdziwe źródło", tylko: wybrać najlepszą dostępną rekonstrukcję, krzyżowo ją zwalidować względem drugiej, niezależnej rekonstrukcji, i jawnie oznaczać rozbieżności/niepewność tam, gdzie występują — dokładnie ten sam duch co `LIMITED_BUT_HONEST` (sekcja 13) i `SOURCE NOT VERIFIED` (BLOCKER 3).

#### 1. FMP `stable/historical-sp-500`

| Kryterium | Ustalenie |
|---|---|
| Zakres historyczny | **NIEPOTWIERDZONE** — dokumentacja FMP nie podaje wprost daty początkowej dla tego konkretnego endpointu; ogólne plany FMP deklarują „do 5 lat" (Starter) / „do 30 lat" (Premium) historii, ale niejasne, czy ten limit dotyczy też logu zmian składu indeksu, czy tylko danych cenowych/fundamentalnych. Wymaga bezpośredniego zapytania testowego. |
| Reprezentacja wejść/wyjść | **Log zdarzeń zmian**, nie snapshoty dzienne. Pola (z drugorzędnego źródła — struktury Go SDK trzeciej strony, nie z oficjalnej dokumentacji FMP): `date`, `dateAdded`, `symbol`, `addedSecurity`, `removedTicker`, `removedSecurity`, `reason`. Usunięcie i dodanie zastępujące je współdzielą tę samą datę (spółka X wypada tego samego dnia, którego spółka Y wchodzi) — typowy wzorzec redakcyjny S&P DJI. |
| Identyfikacja spółek / ticker changes | Wyłącznie **ticker**, brak CIK w odpowiedzi (typowe dla FMP, tak jak profile/fundamentals w Fazie 0/1 — nasz kod już rozwiązuje to przez własny `ticker_history`, ale to dodatkowa praca po stronie naszej, nie FMP). |
| Odtworzenie składu na dzień | Wymaga **replayu logu zdarzeń** od znanego punktu startowego (np. dzisiejszy skład + cofanie się przez zdarzenia) — nie jest to gotowy snapshot, trzeba go zbudować. |
| Survivorship / look-ahead bias | Sam log zdarzeń, przy poprawnym replayu, **eliminuje** survivorship bias (widzimy spółki, które wypadły). Ryzyko look-ahead: `date`/`dateAdded` to data redakcyjnej decyzji S&P DJI — może różnić się (zwykle nieznacznie, dni) od daty, kiedy informacja była publicznie znana/wyceniona przez rynek; wymaga tej samej dyscypliny „filed ≤ as_of" co Faza 5.1, ale na dacie ogłoszenia zmiany, nie dacie efektywnej. |
| Kompletność / ograniczenia | **NIEPOTWIERDZONE** ile zdarzeń wstecz faktycznie zwraca endpoint — to jest właśnie centralny punkt OPEN BLOCKER 2 od v1.4, wciąż niewykonany empirycznie. |
| Koszt / dostępność | Wymaga klucza FMP; **NIEPOTWIERDZONE**, czy endpoint `stable/historical-sp-500` jest dostępny na planie Starter (już zaplanowany zakup, sekcja DECYZJE) czy dopiero Premium — dokumentacja ogólna planów tego nie precyzuje per-endpoint. Do sprawdzenia bezpośrednim zapytaniem testowym (ten sam wzorzec co „FMP Smoke Test"). |
| Walidacja | Dostawca komercyjny — brak wglądu w metodologię źródłową; jedyna dostępna nam walidacja to krzyżowa z drugim źródłem (fja05680) i/lub dzisiejszym składem z Wikipedii jako punktem odniesienia „na dziś". |

#### 2. `fja05680/sp500` (GitHub, plik `S&P 500 Historical Components & Changes (Updated).csv`)

| Kryterium | Ustalenie |
|---|---|
| Zakres historyczny | **1996 do dziś** (potwierdzone bezpośrednim odczytem pliku: pierwszy wiersz `1996-01-02`, aktualizacje „co jakieś dwa miesiące" wg README). |
| Reprezentacja wejść/wyjść | **Pełny snapshot per data zmiany**, nie log zdarzeń: dwie kolumny `date`, `tickers` (lista tickerów rozdzielona przecinkami, aktywnych na tę datę). Nowy wiersz pojawia się tylko wtedy, gdy skład faktycznie się zmienił (potwierdzone: odstępy między wierszami nieregularne, dni do tygodni, nie codzienne) — odtworzenie składu na dowolny dzień to „znajdź najnowszy wiersz z datą ≤ D", **dokładnie ten sam wzorzec co `value_as_of` z Fazy 5.1**. |
| Identyfikacja spółek / ticker changes | Wyłącznie **ticker**, żadnego CIK ani stałego identyfikatora spółki. README autora wprost: przy zmianie tickera lub usunięciu ze składu traktuj to jako wyjście z indeksu — autor **nie** rozróżnia „spółka opuściła indeks" od „spółka zmieniła ticker, ale zostaje" na poziomie danych źródłowych. To bezpośrednio koliduje z naszą zasadą CIK-jako-tożsamość (v1.0) i wymaga własnej warstwy rozwiązywania ticker→CIK point-in-time (patrz „Warstwa kanoniczna" niżej) — ryzyko realne, nie teoretyczne, bo ryzyko recyklingu tickerów jest udokumentowanym powodem, dla którego ten projekt w ogóle używa CIK, nie tickera. |
| Odtworzenie składu na dzień | Bezpośrednio wspierane formatem pliku (patrz wyżej) — autor ma nawet dedykowany notebook `sp500_by_date.ipynb` do dokładnie tego zapytania. |
| Survivorship / look-ahead bias | Przy poprawnym użyciu (snapshot na dzień D, nie dzisiejszy) eliminuje survivorship bias. Ryzyko look-ahead analogiczne do FMP — data w pliku to data redakcyjna, nie data efektywnego wejścia rynku w posiadanie tej informacji (zwykle bliskie sobie, ale nieoznaczone jako odrębne pola). |
| Kompletność / ograniczenia | **Jawnie przyznane przez autora** (README/blog, potwierdzone WebFetch w tej sesji): pierwsze ~5 lat (1996–2001) może mieć brakujące symbole — autor: „nie mam sposobu, by to niezależnie zweryfikować", rekomenduje unikać tego okna, jeśli dokładna liczba 500 spółek jest krytyczna. Liczba spółek w historii waha się 487–507 (S&P 500 rzadko ma dokładnie 500 pozycji — split classes, przejęcia w toku itp. — to cecha rzeczywistości, nie błąd pliku). Dane źródłowe: 1996–2019 z książki Andreasa Clenowa *Trading Evolved* (niezależne pochodzenie), 2019+ dociągane z Wikipedii + ręczna weryfikacja autora. |
| Koszt / dostępność | **Darmowe, licencja MIT**, bez klucza API, bez limitu. |
| Walidacja | Autor weryfikuje ręcznie względem Wikipedii przy każdej aktualizacji, ale to oznacza, że **dla okresu 2019+ ten plik nie jest w pełni niezależny od Wikipedii** — ważna nietrywialna obserwacja dla poniższej sekcji o trzecim źródle. |

#### 3. Trzecie źródło — nie pełny równoległy pipeline, tylko celowana walidacja

Sprawdzone i odrzucone/odłożone jako PEŁNE trzecie źródło, z uzasadnieniem:

- **Wikipedia „List of S&P 500 companies"** — darmowa, aktualizowana na bieżąco, ale **nie jest niezależna** od `fja05680` dla okresu 2019+ (autor `fja05680` dociąga stamtąd zmiany) — użycie jej jako „trzeciego" źródła do walidacji tego samego okresu byłoby częściowo kołowe. Użyteczna wyłącznie jako **tani sanity-check „skład na dziś"**: obie rekonstrukcje (FMP, fja05680) powinny zgadzać się z dzisiejszą listą Wikipedii — jeśli nie, to sygnał błędu, nie potwierdzenie poprawności historii.
- **Norgate Data / dane holdingów ETF (np. IVV/SPY, publikowane przez emitenta)** — potencjalnie genuinie niezależne (ETF replikujący S&P 500 publikuje realny skład portfela), ale: (a) Norgate to płatny dodatek (podobny wzorzec decyzyjny co odrzucona wcześniej EODHD Historical Constituents — wymaga jawnej ceny przed zakupem, zgodnie z regułą D1), (b) głębokość publicznie dostępnego, historycznego (nie tylko bieżącego) archiwum holdingów ETF jest **NIEPOTWIERDZONA** — nie sprawdzono w tej sesji, wymagałoby osobnego researchu. Rekomendacja: **nie budować teraz** — odłożyć jako opcję, jeśli krzyżowa walidacja FMP vs fja05680 ujawni materialne rozbieżności, których nie da się rozstrzygnąć żadnym z dwóch głównych źródeł.

**Wniosek:** realna, wykonalna walidacja krzyżowa w tej fazie to **FMP vs fja05680** — dwie niezależne linie rodowodu (komercyjny dostawca vs Clenow/community + Wikipedia), plus tani sanity-check „na dziś" względem Wikipedii. Trzecie pełne źródło nie jest uzasadnione, dopóki nie pojawi się konkretna, nierozstrzygalna rozbieżność.

#### Warstwa kanoniczna — już częściowo zaprojektowana, nie od zera

Schemat DB (sekcja 5, v1.0) **już zawiera** dokładnie tę tabelę, o którą prosi cel Fazy 5.2:

```
universe_membership(id PK, cik FK, index_name, start_date, end_date)
  -- point-in-time przynależność do indeksu, potrzebna do backtestingu (BLOCKER 2)
```

To jest CIK-owa, interwałowa reprezentacja, niezależna od formatu jakiegokolwiek providera — dokładnie zgodna z wymaganiem właściciela „źródło można później wymienić bez przebudowy backtestu". Zadaniem Fazy 5.2 **nie jest** projektowanie nowego schematu, tylko: (a) zbudowanie osobnego adaptera normalizującego per źródło (FMP event-log → `universe_membership`; fja05680 snapshot-diff → `universe_membership`), (b) rozwiązanie identyfikacji ticker→CIK point-in-time, (c) walidacja krzyżowa obu wyników przed zapisem do wspólnej tabeli.

**Centralne ryzyko techniczne: ticker→CIK point-in-time.** Oba źródła identyfikują spółki wyłącznie przez ticker. Nasz istniejący `ticker_history(cik, ticker, start_date, end_date)` (sekcja 5) jest dokładnie zaprojektowany do tego problemu, ale obecnie populowany tylko reaktywnie (aktualny CIK dla tickera w momencie `ingest-prices`), nie dla pełnej historii ~503 spółek × ~30 lat zmian nazw/tickerów. Recykling tickerów (ten sam symbol przypisywany różnym spółkom w różnych okresach) to udokumentowane ryzyko, nie hipotetyczne — to właśnie powód, dla którego ten projekt od v1.0 używa CIK jako tożsamości. Proponowana zasada (zgodna z dotychczasową dyscypliną `NOT_YET_IMPLEMENTED`/`SOURCE NOT VERIFIED`): rozwiązywanie ticker→CIK wyłącznie przez potwierdzone mapowanie SEC (np. `company_tickers.json`) w połączeniu z oknem czasowym danego zdarzenia; ticker, którego nie da się jednoznacznie i pewnie rozwiązać dla danego okresu, **zostaje jawnie oznaczony `CIK_UNRESOLVED`** w tabeli roboczej — nigdy nie zgadywany ani domyślnie przypisywany do dzisiejszego posiadacza tickera.

#### Proponowane następne kroki empiryczne (jeszcze NIEWYKONANE, czekają na zatwierdzenie)

1. Analogicznie do „FMP Smoke Test"/„FMP company facts" z wcześniejszych faz: jedno zapytanie testowe do `stable/historical-sp-500` (po zakupie/potwierdzeniu planu Starter) — sprawdzić realną głębokość historyczną, dokładny kształt JSON, liczbę zwróconych zdarzeń.
2. Pobranie i sparsowanie `S&P 500 Historical Components & Changes (Updated).csv` z `fja05680/sp500` — deterministyczne, bez klucza API, można wykonać od razu (żaden koszt/decyzja właściciela nie blokuje tego kroku).
3. Zbudowanie diff/parsera przekształcającego oba źródła do wspólnego, tymczasowego formatu (jeszcze nie `universe_membership` — najpierw porównanie surowe), i policzenie zgodności/rozbieżności dla próbki dat i spółek (np. te same AAPL/MSFT/KO + kilka spółek o znanych zmianach składu, jeśli takie się znajdą w oknie 2012+ zgodnym z D14).
4. Dopiero po tym porównaniu: decyzja, czy oba źródła wystarczą do zapisania `universe_membership`, czy potrzebny jest trzeci sanity-check (Wikipedia „na dziś" — zawsze; ETF holdings/Norgate — tylko przy nierozstrzygalnej rozbieżności).

**Nie zaczynam żadnego z powyższych kroków bez Twojego zatwierdzenia**, zgodnie z instrukcją.

#### Otwarte punkty wymagające Twojej decyzji

1. Czy zacząć krok 2 (parsowanie fja05680 — darmowe, bez klucza) **teraz**, równolegle z oczekiwaniem na decyzję o planie Starter FMP (potrzebnym do kroku 1)? Czy wolisz poczekać i zrobić oba źródła w tej samej rundzie?
2. Czy akceptujesz zasadę `CIK_UNRESOLVED` (nigdy nie zgadywać ticker→CIK) jako sposób obsługi niejednoznacznych przypadków, nawet jeśli oznacza to niepełne pokrycie `universe_membership` na starcie?
3. Czy okno 2012+ (Decyzja D14, `LIMITED_BUT_HONEST`) ma też ograniczać zakres, jaki faktycznie próbujemy zrekonstruować w `universe_membership` w tej fazie (mniej pracy, mniejsze ryzyko błędu w danych z 1996–2011, które i tak nie wejdą do backtestu), czy budujemy pełną historię od 1996 od razu, skoro oba źródła ją mają?

---

### Wykonanie kroku 2 Fazy 5.2 (v1.22–v1.24) — analiza `fja05680/sp500`, empirycznie potwierdzona, jeszcze nie zapisane do `universe_membership`

Właściciel zatwierdził plan z trzema decyzjami (2026-09-25): (1) zacząć krok 2 teraz, bez czekania na FMP; (2) zaakceptować zasadę `CIK_UNRESOLVED`; (3) rekonstruować produkcyjnie tylko okno 2012+ (D14), zachowując architekturę zdolną do późniejszego rozszerzenia. Poniżej realne wyniki, nie plan.

**Realne pobranie i weryfikacja pliku (2026-09-25, bezpośrednio w tej sesji, nie z pamięci):** `S&P 500 Historical Components & Changes (Updated).csv` pobrany z `raw.githubusercontent.com` — 2720 wierszy, zakres **1996-01-02 do 2026-08-18**. **Ważna korekta własnego wcześniejszego ustalenia:** sekcja „Plan Fazy 5.2 (v1.21)" cytowała wtórne źródło (podsumowanie WebFetch) twierdzące „last noted update: May 2021" — to okazało się **nieprawdziwe**: ostatni wiersz pliku ma tickery takie jak TSLA/SMCI/TKO/SOLV/VLTO, dodane do S&P 500 długo po 2021. Złapane przez bezpośrednią weryfikację surowych danych, nie przez zaufanie podsumowaniu — dokładnie ten mechanizm, dla którego cały ten projekt trzyma się zasady „nie zgaduj, sprawdzaj surowe dane".

**Nowy kod (pokryty testami, hand-verified na syntetycznych przykładach + zweryfikowany ręcznie na realnym pliku):**
- `buffett_scanner/universe_history.py` — czysta logika: `parse_components_csv` (parser CSV `date,tickers`), `window_from_cutoff` (baseline = ostatni wiersz ≤ cutoff, potem wszystkie kolejne), `distinct_tickers`, `build_ticker_intervals` (przekształca sekwencję snapshotów w przedziały członkostwa per ticker — dokładnie zweryfikowane ręcznie na przykładzie z wejściami/wyjściami/ponownym wejściem), `resolve_tickers_to_cik` (nigdy nie zgaduje — `CIK_UNRESOLVED` jawne).
- `buffett_scanner/providers/sp500_history.py` — `fetch_components_csv` (transport, zero logiki).
- `SecEdgarClient.get_company_tickers()` (`providers/sec_edgar.py`) — nowy endpoint `company_tickers.json`, mapowanie ticker→CIK **aktualne na dziś, nie point-in-time** — jawnie udokumentowane w docstringu jako pierwszy przebieg diagnostyczny, nie finalna walidacja tożsamości.
- Nowa komenda CLI `analyze-sp500-history [--cutoff YYYY-MM-DD]` — łączy powyższe, wyłącznie raportuje, **nic nie zapisuje do bazy**.
- Nowy workflow **„Phase 5.2 Proof Run"** — żadnego nowego sekretu (`SEC_EDGAR_USER_AGENT` już istnieje).
- 25 nowych testów jednostkowych (razem 206, w tym 1 integracyjny pominięty), wszystkie zielone.

**Wyniki na realnych danych, okno 2012-01-01 → 2026-08-18 (policzone lokalnie w tej sesji, bez zapisu do bazy):**
- Baseline (ostatni wiersz źródła ≤ 2012-01-01): **2011-12-30**, 497 tickerów.
- Wierszy w oknie (baseline + kolejne zmiany): **918**.
- Dystynktywnych tickerów w całym oknie: **815**.
- Przedziałów członkostwa (po zbudowaniu diff-u): **831** — różnica względem 815 to **16 tickerów z ponownym wejściem** (opuściły indeks i wróciły później jako osobny przedział, poprawnie rozróżnione, nie scalone w jeden ciągły okres).
- Wciąż otwartych na koniec źródła (2026-08-18): **503** — zgodne co do liczby z aktualnym, znanym rozmiarem S&P 500 (multiple share classes) — silny sanity-check poprawności logiki diff.

**Obserwacja jakości danych, warta odnotowania (nie zablokowała analizy, ale wpływa na zaufanie do wczesnych lat okna):** liczba wierszy zmian na rok spada gwałtownie z ~105–130/rok (2012–2018) do ~13–19/rok (2019+). To zgadza się ze strukturą repozytorium opisaną w README (dane 1996–2019 z książki Andreasa Clenowa, 2019+ dociągane z realnych zmian Wikipedii/S&P DJI) i z własnym ostrzeżeniem autora, że ticker-based tracking konfliuje zmianę tickera spółki (bez opuszczenia indeksu) ze zdarzeniem opuszczenia indeksu. Wniosek: **część 2012–2018 prawdopodobnie zawiera sztucznie zawyżoną liczbę „zdarzeń", z których część to zmiany tickera tej samej spółki, nie faktyczny reconstitution** — nie do rozstrzygnięcia bez porównania z FMP lub dodatkowej weryfikacji nazw spółek, nie samych tickerów.

**Ticker→CIK: pierwsze uruchomienie „Phase 5.2 Proof Run" na koncie właścicielki (2026-09-25) — realne liczby.** `sec.gov` był zablokowany tylko w tej interaktywnej sesji (proxy egress, potwierdzone), nie na GitHub Actions — workflow zadziałał bez problemu:
- **RESOLVED: 617/815 (75,7%), CIK_UNRESOLVED: 198/815 (24,3%)**, mapowanie SEC `company_tickers.json` aktualne na dziś.
- Nierozwiązane tickery przejrzane ręcznie (wiedza ogólna o historii tych spółek, nie ponowna weryfikacja surowego JSON SEC w tej sesji) — zdecydowana większość to **oczekiwane, prawdziwe zdarzenia korporacyjne**, nie błąd: spółki przejęte i niefiltrujące już samodzielnie do SEC (CELG→BMS, MON→Bayer, ALXN→AstraZeneca, ATVI→Microsoft, CERN→Oracle, XLNX→AMD, DTV/TWX→AT&T, ESRX→Cigna, TIF→LVMH i wiele innych), fuzje tworzące nowy podmiot/ticker (RTN+UTX→RTX, HNZ+KRFT→KHC), bankructwa (SHLD, JCP), oraz zmiany tickera przy tym samym CIK (**FB→META** to najwyraźniejszy przykład — realna zmiana nazwy/tickera, nie luka w danych).
- **Konkretne, naprawialne znalezisko:** BRK.B (Berkshire Hathaway) i BF.B (Brown-Forman) — obie aktywne dziś w S&P 500 — nie rozwiązywały się przez różnicę formatu zapisu klasy akcji (kropka vs myślnik). Właściciel zatwierdził naprawę.

**Naprawa (v1.23), zanim przejdziemy dalej:** `resolve_tickers_to_cik` teraz próbuje wariantu formatu (kropka↔myślnik) jako DRUGI przebieg, dopiero po nieudanym dopasowaniu bezpośrednim — jawnie raportuje, który wariant zadziałał (`resolved_via_format_variant`), nigdy nie ukrywa, że to nie było dopasowanie bezpośrednie. To NIE naprawia przypadków zmiany nazwy (FB→META) — to inny, trudniejszy problem (wymaga historycznego crosswalka, nie normalizacji formatu), jawnie pozostawiony jako `CIK_UNRESOLVED`. Dodano też rozbicie `CIK_UNRESOLVED` na „wciąż aktywne dziś" (priorytet do dalszej naprawy — ich brak rozwiązania psuje też DZISIEJSZY skład, nie tylko historię) vs „tylko historyczne" (opuściły indeks w oknie, mniej pilne). 5 nowych testów jednostkowych (razem 210, w tym 1 integracyjny pominięty), hand-verified na przykładzie BRK.B/BRK-B i na kontrprzykładzie FB→META (świadomie NIE naprawione). **Czeka na drugie uruchomienie „Phase 5.2 Proof Run" z tymi poprawkami, żeby potwierdzić realną, zawężoną liczbę `CIK_UNRESOLVED` i rozbicie wciąż-aktywne/tylko-historyczne.**

**Wpływ na pokrycie backtestu (wstępna ocena, do potwierdzenia realnym przebiegiem z rozbiciem):** 815 dystynktywnych tickerów w oknie dzieli się na 503 wciąż-otwarte (aktywne dziś) i 312 tylko-historyczne (opuściły indeks przed końcem źródła). Z 198 nierozwiązanych, oczekujemy, że zdecydowana większość należy do puli 312 historycznych (spółki, które faktycznie zniknęły z niezależnego raportowania SEC) — realne rozbicie z drugiego przebiegu to potwierdzi lub obali.

**Drugie uruchomienie „Phase 5.2 Proof Run" (2026-09-25), z naprawą — potwierdza hipotezę w 100%:**
- **RESOLVED: 619/815 (617 bezpośrednio + 2 przez wariant formatu: `BF.B→BF-B`, `BRK.B→BRK-B`)** — dokładnie te dwa przypadki, które przewidziano.
- **CIK_UNRESOLVED: 196/815 (24,05%)** — spadek o dokładnie 2, zgodnie z oczekiwaniem.
- **Rozbicie: 0 nierozwiązanych wśród 503 wciąż-otwartych (aktywnych dziś), 196 nierozwiązanych wśród 312 tylko-historycznych.** To najważniejszy wynik tego kroku: **dzisiejszy skład S&P 500 (503 spółki) rozwiązuje się do CIK w 100%** przez samo dzisiejsze mapowanie SEC — cała pozostała niepewność (196/312 = 62,8% spółek, które opuściły indeks w oknie 2012+) dotyczy wyłącznie rekonstrukcji PRZESZŁEGO składu, nie bieżącego stanu. Potwierdza to hipotezę z v1.22/v1.23: nierozwiązane tickery to prawie wyłącznie spółki, które faktycznie zniknęły z niezależnego raportowania SEC (przejęcia/fuzje/bankructwa/zmiany nazwy), nie defekt kodu.

**Krok 2 Fazy 5.2 formalnie zakończony (empirycznie potwierdzony, v1.24).** Pozostaje: krok 1 (test FMP), krok 3 (porównanie krzyżowe FMP vs fja05680), i dopiero potem decyzja o finalnym zapisie do `universe_membership` — żadna z tych trzech rzeczy nie została jeszcze zrobiona.

---

### Krok 1 Fazy 5.2 (v1.25–v1.26) — minimalny FMP Smoke Test na obecnym planie, BEZ ZAKUPU

Właściciel doprecyzowała: krok 1 ma być wykonany na **obecnym `FMP_API_KEY`, bez zakupu/założenia żadnego płatnego planu**. Celem jest wyłącznie ustalić: (1) czy endpoint historycznego składu S&P 500 jest dostępny na obecnym planie, (2) jaki realny zakres historyczny zwraca, (3) czy sięga do 2012+, (4) jeśli nie — jaki dokładnie tier i zakres oferuje wyższy plan (informacja, nie zakup). Wyraźne zastrzeżenie właściciela: **nie zakładać z góry 30-letniego zakresu tylko dlatego, że wyższy plan może go oferować** — celem pozostaje 2012+ (D14), nie maksymalna dostępna głębokość. Jeśli FMP nie da 2012+ bez nieproporcjonalnie drogiego planu, następny krok to zatrzymanie się i przedstawienie alternatyw dla `universe_membership` 2012+ — nie automatyczne skracanie backtestu do 5 lat ani zmiana architektury.

**Nazwa endpointu NIEPOTWIERDZONA w oficjalnej dokumentacji FMP** (strona zablokowana przez proxy sieciowy tej sesji, sekcja „Plan Fazy 5.2 (v1.21)"). Zamiast zgadywać jedną nazwę, `FMPClient.get_historical_sp500_constituents()` (nowa metoda w `providers/fmp.py`) próbuje dwóch kandydatów po kolei — `historical-sp500-constituent`, potem `historical-sp-500` (ten drugi to jedyna nazwa, dla której w tej sesji znaleziono realny link do dokumentacji FMP przez WebSearch) — i jawnie raportuje, który zadziałał. Dokładnie ten sam wzorzec co `find_first_matching_tag` w Fazie 5.1. Rozszerzony `fmp_smoketest.py` (istniejący skrypt, już wcześniej używany do diagnozy pola `commonDividendsPaid` w Fazie 4) o nowy blok: wypisuje zadziałaną ścieżkę, liczbę wierszy, kształt pierwszego wiersza, zakres dat (min/max) i jawne `True`/`False` czy zakres sięga do 2012-01-01. Żaden nowy sekret, żaden nowy workflow — istniejący „FMP Smoke Test" (już na `main`) uruchomi się na najnowszym kodzie branchu bez dodatkowego pusha na `main`. 3 nowe testy jednostkowe (razem 213, w tym 1 integracyjny pominięty): pierwszy kandydat działa, pierwszy pada/drugi działa (fallback), oba padają → `FMPError` z treścią błędu ostatniego kandydata (np. „Restricted Endpoint" — dokładnie ten mechanizm ujawnił w Fazie 1 realny wymóg limitu planu Free).

**Kod gotowy, jeszcze nie uruchomiony na realnym koncie.** Czeka na uruchomienie „FMP Smoke Test" (branch `claude/buffett-scanner-design-review-mrud89`) przez właścicielkę.

**Pierwsze uruchomienie (2026-09-25) — wynik niejednoznaczny, ujawnił lukę w diagnostyce, nie w metodzie FMP.** `sp500-constituent` (bieżący skład, bez historii) potwierdził znany z Fazy 0 wynik: 402 „Restricted Endpoint" na obecnym planie. Nowy blok `historical-sp500-constituent` pokazał tylko: „FMP zwrócił status 404 dla `historical-sp-500`. Treść odpowiedzi: []" — **ale kod raportował wyłącznie błąd OSTATNIEGO kandydata**, więc nie było wiadomo, czy pierwszy kandydat (`historical-sp500-constituent`) dał 402 (plan) czy 404 (zła nazwa) — a to zupełnie różne wnioski. Dodatkowe sprawdzenie (WebSearch) znalazło wzmiankę sugerującą, że `historical-sp500-constituent` (bez myślnika w „sp500") to prawdopodobnie właściwa nazwa stabilnego endpointu — ale ta wzmianka sama przyznała brak potwierdzonego przykładu `curl`, więc potraktowana jako niewystarczający dowód, nie zastąpienie realnego testu.

**Naprawa (v1.26), przed wyciągnięciem wniosku:** `get_historical_sp500_constituents()` zwraca teraz `(ścieżka_lub_None, dane_lub_None, lista_prób)`, gdzie `lista_prób` to wynik KAŻDEGO kandydata z osobna (`"OK"` albo treść błędu z kodem statusu) — nigdy nie tracimy informacji, który kandydat dał 402 a który 404. `fmp_smoketest.py` wypisuje teraz obie próby jawnie. 1 nowy test regresyjny (dokładnie ten scenariusz: kandydat 1→402, kandydat 2→404, oba widoczne osobno w wyniku), razem z korektą 2 istniejących testów pod nowy kształt zwracanej krotki. 214 testów razem (213 passed + 1 integracyjny pominięty). **Czeka na drugie uruchomienie „FMP Smoke Test", żeby zobaczyć błąd KAŻDEGO kandydata osobno.**

**Drugie uruchomienie (2026-09-25) — wynik jednoznaczny, krok 1 zamknięty.**
- `historical-sp500-constituent` → **402 „Restricted Endpoint"** (identyczny wzorzec komunikatu jak `sp500-constituent`, Faza 0) — **nazwa endpointu potwierdzona jako prawdziwa**, wymaga planu płatnego wyższego niż obecny.
- `historical-sp-500` → 404, pusta tablica — **potwierdzone jako nieprawidłowa nazwa**; wcześniejszy trop z docs-page slug FMP był mylący (slug strony dokumentacji ≠ rzeczywista ścieżka API).
- **Punkty 2–3 z instrukcji właściciela (realny zakres historyczny, czy sięga do 2012+) NIE DA SIĘ ustalić na obecnym planie** — endpoint zwraca 402 bez żadnych danych podglądowych, zero wierszy do analizy.
- **Punkt 4 (dokładny wymagany tier):** sprawdzone dodatkowym WebSearch (nie zgadywane) — sam komunikat 402 nie nazywa konkretnego planu (w przeciwieństwie do komunikatu o `limit` z Fazy 1), a strona cennika FMP jest zablokowana w tej sesji. **Nie znaleziono wiarygodnego potwierdzenia, który dokładnie plan (Starter/Premium/Ultimate) odblokowuje ten konkretny endpoint** — tylko ogólne opisy planów bez przypisania do tej funkcji.

**Krok 1 Fazy 5.2 formalnie zakończony.** Wniosek: nie da się ocenić proporcjonalności kosztu FMP dla tego zadania, bo nie wiadomo ani ile dokładnie trzeba zapłacić, ani co dokładnie by to dało — zero podglądu bez zakupu. Zgodnie z instrukcją właściciela: **nie ograniczamy automatycznie backtestu i nie kupujemy planu** — przechodzimy do poszukiwania alternatywnego, niezależnego źródła walidacji (patrz sekcja niżej).

---

### Alternatywne źródła walidacji `universe_membership` 2012+ (v1.27) — RESEARCH, ZERO KODU

Na wyraźną prośbę właściciela (po tym, jak FMP okazał się w pełni zablokowany bez zakupu, bez znanego kosztu/tieru): research darmowych/tanich, niezależnych od `fja05680`/Wikipedii źródeł do walidacji historycznego składu S&P 500. Oparte na WebSearch/WebFetch w tej sesji, nie na pamięci — tam, gdzie czegoś nie dało się bezpośrednio sprawdzić (strona zablokowana przez proxy), jest to jawnie oznaczone.

**Najsilniejszy znaleziony kandydat: historyczne holdingi ETF iShares Core S&P 500 (IVV), pobierane bezpośrednio z `ishares.com` z parametrem `asOfDate=YYYYMMDD`.** Potwierdzone DWOMA niezależnymi źródłami (narzędzie GitHub `talsan/ishares` i pakiet PyPI `etf-scraper`, opisane niezależnie od siebie, nie ten sam autor/repo):

| Kryterium | Ustalenie | Pewność |
|---|---|---|
| Zakres historyczny | ~2006–2010+ do dziś (pokrywa 2012+, D14, z zapasem) | Potwierdzone dwoma niezależnymi narzędziami |
| Reprezentacja | Bezpośredni **snapshot realnego portfela funduszu na zadaną datę** (URL z `asOfDate`), NIE log zdarzeń jak fja05680/FMP | Potwierdzone |
| Granularność | Prawdopodobnie **miesięczna dla głębokiej historii, dzienna dla ostatnich lat** („long history for month-end data" + „recent daily history") | Częściowo potwierdzone — dokładna granica nieznana |
| Identyfikacja spółek | Prawdopodobnie ticker + CUSIP/ISIN + nazwa (nie CIK) — wymaga tej samej pracy resolvera co fja05680; CUSIP może być solidniejszy niż ticker (mniej podatny na recykling) | NIEPOTWIERDZONE — dokładny kształt CSV nieznany bez realnego pobrania |
| Niezależność od fja05680/Wikipedii | **Pełna** — dane administracyjne BlackRock o realnym portfelu funduszu, zupełnie inna linia rodowodu | Wysoka pewność strukturalna |
| Survivorship/look-ahead bias | Niskie ryzyko — realny, zaobserwowany stan portfela na tamten dzień, nie rekonstrukcja z dzisiejszego punktu widzenia | — |
| Kompletność/ograniczenia | IVV **nie jest identyczny** ze składem S&P 500 (bufor gotówkowy na umorzenia, opóźnienie we wdrażaniu oficjalnych zmian indeksu, drobne różnice próbkowania) — proxy, nie lustrzane odbicie | Znana, udokumentowana cecha replikujących ETF-ów |
| Koszt/dostępność | **Darmowe**, bez klucza API, publiczny CSV z `ishares.com` | Potwierdzone przez oba narzędzia |
| Walidacja | **NIEZWERYFIKOWANE w tej sesji** — `ishares.com` zablokowany przez proxy sieciowy (ten sam problem co `sec.gov`), więc ani jednego pliku nie udało się faktycznie pobrać; dokładny kształt CSV/kolumn pochodzi z opisów narzędzi trzecich, nie z bezpośredniego testu | **Wymaga empirycznej weryfikacji przed jakimkolwiek kodem produkcyjnym** |

**Odrzucone/niepomocne alternatywy w ramach tego samego researchu:**
- **SPY (State Street/SSGA)** — `etf-scraper` wprost: „latest holdings only" — brak archiwum historycznego mimo popularności funduszu.
- **Vanguard, Invesco** — tylko najnowsze/ostatni miesiąc — nieprzydatne.
- **Norgate Data / CRSP-Compustat** — płatne/instytucjonalne, nie badane dalej wobec darmowej opcji IVV.

**Rekomendacja (do zatwierdzenia, zero kodu na razie):** IVV via `asOfDate` to najsilniejszy dostępny darmowy kandydat na PRAWDZIWIE niezależne drugie źródło do walidacji `universe_membership` 2012+ — bezpośredni snapshot (nie rekonstrukcja z logu zmian, w przeciwieństwie do fja05680/FMP), inna linia rodowodu danych. Zanim jakikolwiek kod parsujący powstanie: potrzebna jest empiryczna weryfikacja dokładnego kształtu odpowiedzi (kolumny, format, rzeczywista granularność dat) — ten sam wzorzec dyscypliny co każdy poprzedni krok tego projektu (nigdy nie budujemy parsera na podstawie nieopisanej struktury). `ishares.com` jest zablokowany w tej interaktywnej sesji, ale prawdopodobnie dostępny z GitHub Actions (jak `data.sec.gov`) lub bezpośrednio w przeglądarce właścicielki — do ustalenia jako następny krok, nie wykonane teraz.

**Nie zdecydowano o finalnym zapisie do `universe_membership`** — zgodnie z instrukcją, zatrzymuję się tutaj. Następny krok wymaga (a) Twojej zgody na wypchnięcie workflow „Phase 5.2 Proof Run" na `main` i uruchomienie go, (b) przejrzenia realnych liczb `CIK_UNRESOLVED`, dopiero potem decyzji o kroku 3 (porównanie z FMP) i finalnym zapisie.

---

### Krok 3 Fazy 5.2 (v1.33) — wyniki walidacji krzyżowej FMP vs fja05680, empirycznie potwierdzone

Uruchomienie „Phase 5.2 FMP vs fja05680 Comparison" na koncie Premium (2026-09-26), pełny zbiór (1528 zdarzeń FMP, 918 wierszy fja05680 w oknie 2012+).

**Anomalie FMP (krok 2 skryptu):** 171/1528 (11,2%) wierszy ma rozjazd `date` vs `dateAdded` (lub `dateAdded` nieparsowalne) — z tego tylko **17 w oknie 2012+**. To realna, nietrywialna cecha danych FMP, potwierdza zasadę „nie zakładać poprawności tylko dlatego, że płatne" — ale skala w oknie istotnym dla nas jest mała.

**Porównanie zdarzeń zmiany składu — dokładne dopasowanie (date+ticker+action) daje pozornie słaby wynik, ale to artefakt metody, nie realna rozbieżność:**
- FMP: 613 zdarzeń w oknie, fja05680: 662. Zgodne dokładnie: tylko **108 (17,6%/16,3%)**.
- **Diagnoza (nie zgadywana — sprawdzona na konkretnych przykładach):** większość „rozbieżności" to TE SAME zdarzenia korporacyjne zapisane z przesunięciem o 1–3 dni. Przykład: FOSL/MHS — FMP: `2012-04-03 ADD FOSL` + `2012-04-03 REMOVE MHS` (jeden dzień, sparowane); fja05680: `2012-04-02 REMOVE MHS` + `2012-04-04 ADD FOSL` (rozbite na dwa różne dni). Ten sam wzorzec dla PSX/SVU (FMP: 04-30 oba; fja05680: 05-01 oba — inny dzień, ale nadal sparowane), ALXN/EP/KMI (FMP: 05-24; fja05680: 05-25). To spójne z naturą obu formatów: FMP zapisuje zdarzenie redakcyjne S&P DJI (jedna data), fja05680 zapisuje datę PIERWSZEGO snapshotu, w którym zmiana jest widoczna (zależne od częstotliwości próbkowania źródła) — różnica rzędu 1–3 dni, nie sprzeczność w treści.

**Porównanie luźniejsze (tylko zbiór tickerów dotkniętych zdarzeniem w oknie, bez wymogu zgodnej daty/akcji) — dużo bardziej informacyjne:**
- FMP: 491 tickerów, fja05680: 543, wspólne: 474.
- **96,5% tickerów z FMP też pojawia się w fja05680; 87,3% tickerów z fja05680 też pojawia się w FMP.** Wysoka zgodność co do TEGO, KTÓRE spółki uczestniczyły w zmianach — różnica leży w datach/szczegółach formatu, nie w tożsamości spółek.

**Rekonstrukcja składu na 3 datach obiema metodami — kluczowy, jednoznaczny wzorzec:**
| Data | FMP | fja05680 | Wspólne | Zgodność (wspólne / średnia) |
|---|---|---|---|---|
| 2012-01-31 | 500 | 497 | 463 | ~92,9% |
| 2018-12-31 | 505 | 505 | 473 | ~93,7% |
| 2026-09-01 | 503 | 503 | 501 | **~99,6%** |

**Zgodność rośnie monotonicznie w miarę zbliżania się do dziś — to nie przypadek, tylko bezpośrednia konsekwencja metody rekonstrukcji FMP.** `reconstruct_membership_backward` zaczyna od DZISIEJSZEGO składu i cofa się, odwracając zdarzenia — im dalej wstecz, tym więcej zdarzeń po drodze, tym więcej okazji na drobne przesunięcia dat (patrz wyżej) do „nałożenia się" na punkt zapytania. **Przy 2026-09-01 (najbliżej dziś) różnica to dokładnie 2 tickery po każdej stronie: `BF-B`/`BRK-B` (FMP) vs `BF.B`/`BRK.B` (fja05680) — ta sama, już wcześniej rozwiązana (Faza 5.2 krok 2, v1.23) różnica formatu zapisu klasy akcji, nie realna rozbieżność.** Po uwzględnieniu formatu zgodność przy dacie współczesnej jest praktycznie 100%.

**Odkryty realny problem strukturalny (nie błąd FMP, ograniczenie metody rekonstrukcji wstecznej):** przy 2012-01-31/2018-12-31 część tickerów „tylko w FMP" (np. `BBWI`, `ELV`, `CTRA`, `COR`, `GEN`, `BKR`, `CSC`) to spółki, które między 2012 a dziś przeszły **zmianę tickera bez opuszczenia indeksu** (spin-off, rebranding, fuzja tworząca nowy ticker przy zachowaniu ciągłości członkostwa) — FMP notuje takie zmiany jako log zdarzeń TYLKO gdy towarzyszy im faktyczne wejście/wyjście z indeksu; czysta zmiana nazwy/tickera bez opuszczenia S&P 500 może nie zostawiać śladu w `historical-sp500-constituent`. Efekt: `reconstruct_membership_backward`, zaczynając od DZISIEJSZEGO tickera takiej spółki, projektuje go błędnie w przeszłość, zamiast pokazać period-poprawny stary ticker. To ograniczenie naszej metody DIAGNOSTYCZNEJ (rekonstrukcja wsteczna po samym tickerze), nie dowód błędu w danych źródłowych FMP — i to dokładnie ten sam problem tożsamości spółek, dla którego cały ten projekt od v1.0 używa CIK, nie tickera, jako klucza. Przykład przeciwny w drugą stronę: `CSC`/`DXC` — FMP pokazuje period-poprawny `CSC` dla 2012 (DXC nie istniało do fuzji 2017), a fja05680 pokazuje `DXC` — sugeruje, że OBIE strony mają pewne niespójności w obsłudze ciągłości tickera, nie tylko jedna.

**Wniosek — odpowiedź na pytanie o `LIMITED_BUT_HONEST`:** obie strony niezależnie potwierdzają zbliżony, wysokiej jakości obraz składu S&P 500 dla okna 2012+ (92–99,6% zgodności w zależności od odległości czasowej), z rozbieżnościami skoncentrowanymi w rozpoznawalnych, wyjaśnialnych przypadkach (przesunięcia dat 1–3 dni, format tickera, zmiany tickera bez opuszczenia indeksu) — nie w losowym szumie sugerującym błędy jakości danych. To mocna podstawa do `LIMITED_BUT_HONEST` dla 2012+, POD WARUNKIEM że finalny `universe_membership` używa CIK (nie surowego tickera) jako klucza identyfikacji — dokładnie zgodnie z architekturą już zaprojektowaną w schemacie (sekcja 5, v1.0) i już częściowo wykonaną (Faza 5.2 krok 2: 619/815 tickerów fja05680 rozwiązanych do CIK).

**Rekomendacja źródła kanonicznego:** **fja05680/sp500 jako podstawowe źródło budowy `universe_membership`** (format snapshot, architektonicznie zgodny z docelową tabelą interval-based `universe_membership(cik, start_date, end_date)` — nie wymaga rekonstrukcji wstecznej podatnej na błąd ciągłości tickera, jaki właśnie znaleziono w metodzie FMP), **z FMP `historical-sp500-constituent` jako niezależnym źródłem walidacji krzyżowej** — dokładnie odwrotna rola niż początkowo zakładano dla FMP (v1.4: „dostawca wybrany"), ale uzasadniona konkretnymi, empirycznymi ustaleniami tej fazy, nie preferencją a priori.

**Pozostałe ryzyka do adresowania przed/podczas budowy `universe_membership` (nie rozwiązane teraz, do decyzji właściciela):**
1. **CIK musi być kluczem identyfikacji, nie ticker** — potwierdzone jako konieczne (nie tylko zalecane) przez znalezisko o zmianach tickera bez opuszczenia indeksu. Rozwiązywanie ticker→CIK dla strony FMP jeszcze niewykonane (krok 2 zrobiono tylko dla fja05680) — FMP w ogóle nie zwraca CIK w tym endponcie.
2. **Reguła rozstrzygania rozbieżności między źródłami** — gdy fja05680 i FMP się nie zgadzają (po rozwiązaniu do CIK), potrzebna jawna polityka (np. „preferuj fja05680, oznacz rozbieżność FMP w metadanych" albo odwrotnie) — decyzja architektoniczna, nie techniczna.
3. **Tolerancja dat** — biorąc pod uwagę systematyczne przesunięcia 1–3 dni między źródłami, `universe_membership.start_date`/`end_date` prawdopodobnie nie powinny być traktowane jako precyzyjne day-level bez dodatkowego zastrzeżenia w metadanych.
4. **Wewnętrzna niespójność date/dateAdded w FMP** (11,2% ogółem) — do zbadania, które pole (jeśli któreś) jest bardziej wiarygodne, zanim FMP posłuży jako aktywne źródło rozstrzygające (obecnie używane tylko jako walidator, więc mniej krytyczne).
5. **Okno 1996–2011** — świadomie poza zakresem tej walidacji (zgodnie z D14), nadal niezweryfikowane, jeśli backtest kiedyś rozszerzy się poza 2012+.

**Zatrzymuję się przed implementacją finalnego `universe_membership`**, zgodnie z instrukcją.

### Domknięcie OPEN BLOCKER 2 (v1.34) — projekt i implementacja, WALIDACJA EMPIRYCZNA JESZCZE NIEWYKONANA

Właścicielka zatwierdziła wyniki kroku 3 i rekomendację (fja05680 kanoniczne, FMP walidator, CIK jako obowiązkowy klucz) i zleciła zamknięcie 5 pozostałych ryzyk PRZED implementacją tabeli/migracji. Poniżej: zaprojektowana i zaimplementowana (kod + testy jednostkowe z ręcznie policzonymi wartościami referencyjnymi, 40 nowych testów, 274/274 zielone razem z istniejącymi) logika dla wszystkich 5 punktów. **Skrypt Proof Run (`universe_cik_revalidation_smoketest.py`) zweryfikowany OFFLINE (realne dane fja05680 z cache tej sesji + syntetyczne dane FMP/SEC, bo ta sesja nie ma dostępu sieciowego do `sec.gov` ani FMP) — działa bez błędów integracyjnych, ale liczby z tego dry-runu SĄ SYNTETYCZNE i nie stanowią empirycznej walidacji. Realne uruchomienie przez GitHub Actions jeszcze się nie odbyło.**

**1. Rozwiązanie CIK dla rekordów FMP (nigdy nie zgadywane):** `SecEdgarClient.get_company_tickers_full()` (nowość — rozszerza istniejące `get_company_tickers()` o pole `title`, zachowując wsteczną zgodność) + `fmp_sp500_events.resolve_fmp_tickers()`: dokładne dopasowanie tickera, potem warianty formatu zapisu (kropka/myślnik, reużyte z `universe_history.ticker_format_variants` — ta funkcja została upubliczniona z prywatnej `_ticker_format_variants`, bo teraz używana z dwóch modułów), nierozwiązane trafiają jawnie do `unresolved`. DODATKOWO: krzyżowa kontrola nazwy spółki (`names_plausibly_match` — reguła v1, zob. niżej) między nazwą z FMP (`addedSecurity`/`removedSecurity`) a dzisiejszym tytułem SEC — niezgodność NIE usuwa CIK z `resolved` (to jedyny potwierdzony przez ticker fakt), tylko trafia jawnie do `name_mismatch_suspicious` do ręcznej oceny (może być recykling tickera ALBO nieszkodliwy rebranding przy niezmienionym CIK — oba przypadki jawnie opisane w docstringu jako ograniczenie reguły). Osobno: `find_tickers_with_multiple_names()` sprawdza WEWNĘTRZNĄ spójność samego logu FMP (ten sam ticker, >=2 wzajemnie niezgodne nazwy w historii FMP) — niezależnie od SEC.

**2. Reguła rozstrzygania rozbieżności fja05680↔FMP po CIK:** `universe_cik_reconciliation.build_reconciliation_report()` — architektonicznie NIC w tym module nie konstruuje ani nie modyfikuje membership; funkcja zwraca WYŁĄCZNIE diagnostyczne listy `only_canonical`/`only_validator` (rozbieżności do ręcznej/audytowej oceny) + liczniki pominiętych z braku CIK po obu stronach. fja05680 pozostaje jedynym źródłem membership poza tym modułem — sprawdzone dodatkowym testem architektonicznym (`ReconciliationReport` nie ma żadnego pola reprezentującego "ostateczny" skład).

**3. Reguła tolerancji dat:** `match_cik_events_with_tolerance()` — deterministyczne, WERSJONOWANE (parametr `tolerance_days`) dopasowanie zdarzeń po (cik, action) z greedy najbliższym dopasowaniem w koszyku, motywowane empirycznym znaleziskiem z kroku 3 (przesunięcia 1–3 dni, przykłady FOSL/MHS/PSX/SVU/ALXN/EP/KMI). `tolerance_impact_curve()` mierzy wpływ tolerancji 0–5 dni na liczbę dopasowań (krzywa malejących przyrostów) zamiast zakładać wartość arbitralnie; `pick_plateau_tolerance()` wybiera najmniejszą tolerancję, od której liczba dopasowań się już nie zmienia w testowanym zakresie — deterministyczny wybór wyprowadzony z krzywej, nie liczba z góry.

**4. Problem FMP `date` vs `dateAdded`:** `fmp_change_events_by_date_added()` — wariant budowy zdarzeń używający sparsowanego `dateAdded` zamiast `date` jako klucza porównania, do bezpośredniego, empirycznego zestawienia obu krzywych tolerancji (pole `date` vs pole `dateAdded`) w skrypcie Proof Run. Wybór pola NIE jest zakodowany na sztywno — skrypt liczy dominację (`_field_dominance`: które pole ma >= liczbę dopasowań przy KAŻDEJ testowanej tolerancji) i jawnie raportuje "brak jednoznacznej dominacji" zamiast zgadywać, gdy krzywe się przecinają.

**5. Ponowna walidacja po CIK i tolerancji:** `providers/universe_cik_revalidation_smoketest.py` (nowy Proof Run, workflow `phase5-2-cik-revalidation-proof-run.yml`, wymaga `FMP_API_KEY` + `SEC_EDGAR_USER_AGENT`, oba już istnieją jako sekrety) — raportuje w jednym uruchomieniu: coverage CIK obu źródeł + listy unresolved, `name_mismatch_suspicious`, wewnętrzną niespójność nazw FMP, krzywe tolerancji dla obu pól daty, finalny raport pogodzenia na progu plateau (rzeczywiste `only_canonical`/`only_validator` po odfiltrowaniu szumu formatu/dat), oraz — DODATKOWO ponad zlecone punkty — porównanie rekonstrukcji membership na 3 reprezentatywnych datach (2012-01-31, 2018-12-31, 2026-09-01, zgodnie z D14) na poziomie TICKERA (jak w kroku 3) I na poziomie CIK, żeby bezpośrednio pokazać, ile z wcześniej obserwowanych różnic ticker-poziomu znika po przejściu na CIK.

**Offline dry-run (nie jest walidacją empiryczną, tylko testem integracyjnym skryptu):** realne dane fja05680 z cache tej sesji (2720 wierszy, 815 unikalnych tickerów w oknie 2012+) + syntetyczne zdarzenia FMP zbudowane z rzeczywistych przedziałów fja05680 (przesunięte o 1–2 dni, żeby przejść przez ścieżkę tolerancji) + syntetyczna mapa SEC (pseudo-CIK, celowo 3 tickery nierozwiązane, jeden wariant kropka/myślnik, jeden celowy `name_mismatch`, jedna wewnętrzna niespójność nazw). Skrypt przeszedł przez wszystkie 7 kroków bez wyjątków — potwierdza POPRAWNOŚĆ INTEGRACJI kodu (parsowanie, rozwiązywanie CIK, krzywa tolerancji, raport końcowy, porównanie ticker/CIK na datach próbkowanych), NIE potwierdza żadnej tezy o realnych danych S&P 500 — te liczby są w pełni syntetyczne i nie nadają się do cytowania jako wynik.

**Następny krok:** uruchomienie `phase5-2-cik-revalidation-proof-run.yml` przez właścicielkę na realnych danych, przedstawienie wyników, i DOPIERO PO ICH ZOBACZENIU — jeśli potwierdzą kontrolowane/audytowalne rozbieżności — finalny projekt schematu `universe_membership` + pól `provenance`/`validation` + zasad rekonstrukcji point-in-time. Zero implementacji tabeli/migracji do tego czasu, zgodnie z instrukcją.

### Wyniki empirycznej walidacji (v1.35) — dwa realne uruchomienia na GitHub Actions

**Pierwsze uruchomienie (2026-09-30)** ujawniło dwa błędy w SAMYM SKRYPCIE diagnostycznym (nie w danych): (1) coverage CIK dla FMP liczony był na pełnym logu 1957–2026 zamiast na oknie 2012+ (naruszenie D14 w samej diagnostyce) — naprawione przez zawężenie RAPORTOWANYCH liczb do tickerów istotnych dla okna (zdarzenie w oknie LUB obecność w dzisiejszym składzie), przy zachowaniu rozwiązywania CIK na pełnym logu (potrzebne dla tickerów stabilnych od przed 1957, np. AAPL, żeby nie zniknęły z rekonstrukcji); (2) 19 tickerów z dzisiejszego składu, które nigdy nie miały żadnego zdarzenia ADD/REMOVE w logu FMP, w ogóle nie trafiało do próby rozwiązania CIK — naprawione dopisaniem takich tickerów z pustą nazwą przed wywołaniem `resolve_fmp_tickers` (funkcja już poprawnie pomija kontrolę nazwy, gdy `fmp_name` jest puste). Dodana też tania krzyżowa kontrola (z już pobranych danych, bez dodatkowych zapytań): czy któryś `UNRESOLVED` ticker jest jednocześnie w dzisiejszym potwierdzonym składzie FMP — **wynik: 0 w obie strony, w obu uruchomieniach** — żaden aktualnie aktywny członek S&P 500 nie ginie po drodze przez rozwiązywanie CIK.

**Drugie uruchomienie (po obu poprawkach, 2026-09-30)** dało czysty, spójny obraz:
- Coverage CIK: fja05680 619/815 (76,0%), FMP 618/779 w oknie (79,3%, arytmetyka się zgadza: 618+161=779 — brak cichych ubytków).
- Pole `dateAdded` dominuje `date` przy KAŻDEJ testowanej tolerancji (0d: 97 vs 71 dopasowań) — potwierdzone w obu uruchomieniach.
- Krzywa tolerancji ma prawdziwe plateau przy 6 dniach: 366 dopasowanych, stabilnie od 6d do 10d (poszerzony zakres po tym, jak pierwsze uruchomienie pokazało, że 0-5d jeszcze rosło na końcu).
- Finalne pogodzenie na progu 6d: 366 dopasowanych / 45 tylko-kanoniczne / 34 tylko-walidator (89,1%/91,5% zgodności) — każda rozbieżność z konkretnym CIK+datą+akcją, gotowa do audytu.
- Rekonstrukcja CIK-poziom na 3 datach: 2012-01-31 — 91,3% zgodności; 2018-12-31 — 92,9%; **2026-09-01 — 100,0% (0 różnic)**. Rozbieżność rośnie w głąb historii systematycznie w jedną stronę (`tylko_FMP` ≫ `tylko_fja05680`) — spójne z już udokumentowanym (v1.33) strukturalnym ograniczeniem metody rekonstrukcji wstecznej FMP, nie nowa zagadka.

**Wniosek zatwierdzony przez właścicielkę (2026-09-30): rozbieżności są kontrolowane i audytowalne.** Recykling tickerów potwierdzony na realnych przykładach (`APC`: Anadarko → dziś niezwiązana "ARKO Petroleum Corp." pod tym samym tickerem; `EP`: El Paso Corp. → "Empire Petroleum Corp") — mechanizm wykrywania działa poprawnie na prawdziwych danych, nie tylko teoretycznie.

### Finalny projekt `universe_membership` (v1.35, zatwierdzony) — implementacja (v1.36)

Zatwierdzony projekt rozszerza istniejący schemat (sekcja 5, v1.0) — `ticker_history` (już istniejąca) pozostaje jedynym miejscem przechowującym ticker jako atrybut historyczny; `universe_membership` identyfikuje WYŁĄCZNIE przez CIK. Na wyraźne żądanie właścicielki dodano `validation_rule_version` — ODRĘBNE od parametrów (`validation_tolerance_days`, `validation_date_field`) — żeby historycznie dało się odróżnić wynik policzony starą logiką dopasowania od nowej, nawet przy tych samych parametrach; wartość pochodzi z `universe_cik_reconciliation.MATCH_ALGORITHM_VERSION` (obecnie `"cik_tolerance_match_v1"`, bumpowane przy każdej zmianie samego algorytmu, nie parametrów).

Zaimplementowane (kod + 38 nowych testów jednostkowych z ręcznie policzonymi wartościami referencyjnymi, razem z Fazą 5.2 v1.34/v1.35 łącznie 78 nowych testów, wszystkie zielone):
- **`universe_membership_build.py`** (nowy moduł, czysta logika): `build_cik_membership_intervals()` (konwersja ticker→CIK, unresolved jawnie zwrócone, nigdy nie znika), `merge_adjacent_same_cik_intervals()` (scala zero-dniowe przerwy tego samego CIK — ticker rename bez opuszczenia indeksu; realne wyjście+powrót NIE jest scalane), `attach_validation_status()` (osobno wejście i wyjście każdego przedziału, FMP nigdy nie zmienia cik/start_date/end_date), `build_conflicts()` (pełny audytowalny log, w tym `ONLY_VALIDATOR` bez odpowiadającego wiersza membership), `membership_as_of()` (rekonstrukcja point-in-time, `end_date` wyłączny).
- **`db.py`**: tabele `universe_membership` (z `validation_rule_version` i wszystkimi polami provenance/walidacji, `CHECK` na `cik_resolution_method`/`entry_validation_status`/`exit_validation_status`/`validation_date_field` — nigdy nie zgadujemy dozwolonej wartości), `universe_membership_conflicts` (append-only audit log), `universe_membership_unresolved_tickers` (jawny rejestr CIK_UNRESOLVED, UNIQUE per source+ticker+index+run — nie duplikuje się przy powtórnym uruchomieniu z tym samym `run_id`); funkcje `upsert_universe_membership()`, `insert_universe_membership_conflict()`, `insert_unresolved_ticker()`, `get_universe_membership_as_of()` (SQL point-in-time, ten sam wzorzec interwałowy co `value_as_of`/`tickers_as_of`).
- **`cli.py build-universe-membership [--cutoff YYYY-MM-DD]`**: pełny pipeline (SEC+fja05680+FMP → rozwiązanie CIK obu stron → empiryczny wybór pola daty i tolerancji PRZEZ krzywą (nie hardkodowany — algorytm identyczny jak w Proof Run) → budowa przedziałów → scalanie → walidacja → zapis) — jedyne miejsce, gdzie dane trafiają do `universe_membership`.

**Offline dry-run** (realne dane fja05680 z cache sesji + syntetyczne SEC/FMP, zapis do tymczasowego SQLite): pełny przebieg 7 kroków bez wyjątków, wszystkie ograniczenia `CHECK`/`FOREIGN KEY` przechodzą poprawnie, round-trip `membership_as_of` (w pamięci) == `get_universe_membership_as_of` (z bazy) zweryfikowany asercją w samym pipeline. Dodatkowo: dry-run wymusił sztucznie dwa realne, sąsiadujące w czasie tickery fja05680 (`AABA`→`ALGN`, dzień przetasowania indeksu 2017-06-19) na WSPÓLNY CIK, żeby przejść przez ścieżkę scalania end-to-end (hash-owany pseudo-CIK w reszcie dry-runu nigdy nie przydziela tego samego CIK dwóm różnym tickerom) — wynik: 828→827 przedziałów, 812→811 unikalnych CIK, dokładnie 1 scalona para, zgodnie z oczekiwaniem.

**Zatrzymuję się przed realnym (empirycznym) buildem** — offline dry-run potwierdza integrację kodu, nie stanowi dowodu na realnych danych 2012+. Wymaga uruchomienia `build-universe-membership` przez GitHub Actions (workflow do przygotowania/pushnięcia po akceptacji tej sekcji).

---

## DECYZJE WCIĄŻ WYMAGAJĄCE TWOJEGO WYBORU

**Zero decyzji architektonicznych.** Wszystkie 15 pierwotnych decyzji (D1–D15) są zamknięte, architektura MULTI-USER (v1.5/v1.6) zaakceptowana, **wszystkie Fazy 0–4 w pełni empirycznie zweryfikowane na realnych danych (v1.17), Faza 5.1 (OPEN BLOCKER 1) empirycznie potwierdzona i ukończona (v1.20)** — pierwsze uruchomienie na realnym koncie ujawniło błąd tie-breakingu w `value_as_of`, naprawiony i potwierdzony drugim uruchomieniem (MSFT: dokładna zgodność z FMP z dwóch niezależnych źródeł).

Otwarte kwestie operacyjne:
- **Kiedy kupić plan Starter FMP** — potrzebny dopiero do `ingest-universe` (pełne 503 spółki), nie do dokończenia dowodu koncepcji na próbce tickerów. Można to zrobić teraz albo poczekać do Fazy 1/6. Billing Claude API już aktywowany (Faza 3/4).
- **Faza 5.2 (OPEN BLOCKER 2 — historyczny skład S&P 500), stan v1.36.** Empirycznie zwalidowana na realnych danych (2 uruchomienia GitHub Actions, 2026-09-30): coverage CIK 76-79%, zgodność po CIK+tolerancji 89-92% historycznie i 100% przy dacie współczesnej, recykling tickerów potwierdzony na realnych przykładach (APC/Anadarko, EP/El Paso). **Finalny projekt `universe_membership` zatwierdzony przez właścicielkę (z dodatkiem `validation_rule_version` na jej wyraźne żądanie) i ZAIMPLEMENTOWANY**: `universe_membership_build.py` (scalanie zmian tickera bez opuszczenia indeksu, walidacja wejścia/wyjścia niezależnie, audytowalne konflikty), 3 nowe tabele w `db.py`, `cli.py build-universe-membership` (pełny pipeline SEC+fja05680+FMP → CIK → walidacja → zapis, empiryczny wybór pola daty/tolerancji, nie hardkodowany). 78 nowych testów w całej Fazie 5.2 (v1.34-v1.36), wszystkie zielone. Zweryfikowane offline (w tym ścieżka scalania, wymuszona na realnych tickerach z cache). **Czeka na:** jeden realny build przez GitHub Actions na danych 2012+ — dopiero po nim formalne domknięcie Fazy 5.2.

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
