# Audyt metodologii oceny — 2026-10-23

Status: **do decyzji właścicielki. Kod scoringu, DCF, CAGR, MoS, wagi i zasady kwalifikacji NIE zostały zmienione.**

Dane: shortlista skanu z 22.10.2026 (`live-scan-2026-10-22T202049554465Z`, 162 spółki w rankingu, 24 na shortliście, limit 20 + remisy). Warianty alternatywne policzono jednorazowym skryptem analitycznym (poza repozytorium), każdy osobno, przy pozostałych regułach bez zmian. Są ilustracją wrażliwości, nie rekomendacją parametrów.

## Kontekst z dokumentacji projektu

- Cała konfiguracja scoringu, wyceny i dywidend ma status `UNCALIBRATED`.
- Trzy rundy kalibracji (Faza 5.4, okno 2012–2021) nie zmieniły żadnego parametru. Round 3 badała `mos_pct_for_full_score` (35/50/65) i sufity wzrostu (15/20/25) jako analizę stabilności, nie optymalizację.
- Jednorazowy holdout 2022–2026 (Faza 5.6): model nie wykazał przewagi nad rynkiem, a **komponent wyceny nie wnosi informacji rankingowej**: Spearman BEZ wyceny > Z wyceną na wszystkich 4 horyzontach.
- Holdout został już wykorzystany. Każda zmiana metodologii nie może być „czysto” zwalidowana na tych samych danych 2022–2026 (ryzyko dopasowania do danych).

## Jak model wybiera dziś shortlistę

1. Spadek ceny (progi `decline_scanner`) → prefilter, który tylko flaguje (reguły wykluczające są celowo puste, BLOCKER 5).
2. Wynik deterministyczny bez Claude: bezpieczeństwo finansowe (15 pkt) + wycena DCF (20 pkt) + dywidendy i zwrot dla akcjonariuszy (10 pkt).
3. `deterministic_score_pct` = punkty / maksimum DOSTĘPNYCH komponentów × 100.
4. Shortlista = TOP 20 po tym procencie, z zachowaniem remisów. Na 22.10: po 5 spółek remisowało na 100% i na 87,5%, stąd 24 spółki.
5. Dopiero shortlista trafia do Claude (jakość biznesu 45 pkt, strach/okazja 10 pkt).

## Mnożnik wyceny w scenariuszu BASE (dyskonto 9%, wzrost rezydualny 2,5%, 10 lat)

| Wzrost w oknie projekcji | EV / najnowszy FCF | MoS ≥ 50% (pełne 20 pkt), gdy FCF/EV ≥ | MoS > 0, gdy FCF/EV ≥ |
|---|---|---|---|
| 0% | 13,1× | 15,3% | 7,6% |
| 5% | 19,0× | 10,5% | 5,3% |
| 10% | 27,8× | 7,2% | 3,6% |
| 15% | 40,5× | 4,9% | 2,5% |
| 20% (sufit) | 58,9× | 3,4% | 1,7% |

## Wpływ wariantów na shortlistę 22.10 (każdy osobno)

| Wariant | Wypadają | Wchodzą |
|---|---|---|
| A. Brak wyceny = 0 z 45 pkt (bez renormalizacji) | PODD, CEG, NFLX, UBER | — |
| B. Bez komponentu wyceny (jak test „BEZ wyceny” w holdoucie) | 16 spółek | 19 spółek |
| C. MoS z średniego FCF zamiast najnowszego | APP, DXCM, MU, SNDK, XYL, PNR, EME | CHRW, IR, PYPL |
| D. Sufit wzrostu 10% zamiast 20% | APP, DXCM, XYL, EME, HII, JBL | PYPL, CMCSA |
| E. Spółka bez dywidendy bez punktów za „brak cięcia” i „bezpieczny payout” | PODD, ADBE, NFLX, UBER, APTV, FISV | IR, CHRW |

Spółki z DCF na shortliście: 20. MoS BASE ≥ 50%: 16. Przy średnim FCF: 8. Przy suficie 10%: 8.

---

## 1. Maksymalne punkty za wycenę (16/24)

**Reguła i źródło.**
- `scoring.valuation_score` (`buffett_scanner/scoring.py`), to samo mapowanie w `backtest_harness.compute_deterministic_score`:
  - MoS BASE ≤ 0 → 0 pkt;
  - MoS ≥ `mos_pct_for_full_score` (50, `config/config.yaml`) → 20 pkt;
  - pomiędzy → liniowo.
- MoS = (wartość wewnętrzna − cena) / wartość wewnętrzna, ze scenariusza BASE.

**Konsekwencja.** Komponent się nasyca. 16 z 20 spółek z DCF ma komplet 20 pkt, więc wycena przestaje je różnicować, a o kolejności decydują bezpieczeństwo i dywidendy. Przy wzroście na suficie wystarczy FCF/EV ≥ 3,4%, żeby dostać komplet.

**Świadoma zasada czy uproszczenie?** Świadomy parametr projektu z 2026-09-25. Round 3 potwierdziła stabilność rankingu przy 35/50/65 (Spearman 0,97–0,99), ale nie jego wartość prognostyczną. Holdout: wycena pogarsza ranking. Status: **niezweryfikowane**.

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) Bez zmian | Zgodność z zamrożoną metodologią | Nasycenie; wycena nie różnicuje |
| b) Wyższy próg pełnych punktów lub mapowanie bez sufitu | Lepsze różnicowanie | Nadal oparte na niewiarygodnym MoS (pkt 2, 6) |
| c) Punkty liczone z MoS w scenariuszu BEAR | Ostrożniej, mniej nasycenia | Inna semantyka; BEAR też zależy od najnowszego FCF |
| d) Mniejsza waga lub wycena tylko jako informacja, nie w rankingu | Zgodne z wynikiem holdoutu | Duża zmiana filozofii (podejście Buffetta wymaga wyceny) |

**Kalibracja/walidacja:** tak, każda z opcji b–d zmienia selekcję.

## 2. Sufit wzrostu BASE 20% (13/24)

**Reguła i źródło.**
- `valuation._compute_dcf_owner_earnings`: wzrost w oknie projekcji = CAGR FCF × mnożnik scenariusza (BASE 1,0), obcięty do [−5%, 20%] (`max_projected_growth_rate_pct`, `min_projected_growth_rate_pct`).
- Stały wzrost przez 10 lat, potem od razu 2,5%.
- CAGR liczony tylko z pierwszego i ostatniego okresu, w oknie do 5 lat.

**Konsekwencja.**
- Przy 20% EV wynosi 58,9× FCF, czyli 4,5 razy więcej niż przy 0%.
- 13 spółek ma historyczny CAGR 24–112% i trafia na sufit.
- Wariant D (sufit 10%) usuwa 6 spółek z shortlisty, a liczba spółek z MoS ≥ 50% spada z 16 do 8.

**Świadoma zasada czy uproszczenie?** Sufit jest świadomym „pasem bezpieczeństwa”. Założenie 10 lat stałego wzrostu bez wygaszania nie ma w dokumentacji uzasadnienia empirycznego. Round 3 testowała 15/25 na danych, w których większość obserwacji nie miała wyceny (n = 1 111 z 5 834). Status: **uproszczenie, niezweryfikowane dla obecnego składu shortlisty**.

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) Niższy sufit (10–12%) | Prosto, mniej zawyżonych wycen | Arbitralna liczba |
| b) Wygaszanie wzrostu (np. liniowo do 2,5% w 10 lat) | Standard w praktyce DCF, mniej wrażliwe na sufit | Więcej założeń |
| c) Krótsza faza wysokiego wzrostu (5 lat) + wygaszanie | Ostrożniej | Wymaga nowej siatki parametrów |
| d) Wzrost = mniejszy z CAGR FCF i CAGR przychodów | Ogranicza skoki z niskiej bazy FCF | Spółki z poprawą marży niedoszacowane |

**Kalibracja/walidacja:** tak.

## 3. Pełne punkty dywidendowe bez dywidendy (9/24; 30 z 54 spółek bez dywidendy w rankingu)

**Reguła i źródło.** `shareholder_returns.evaluate_dividend_shareholder_return`, wagi w `config.yaml`:
- dodatni shareholder yield (dywidendy + buyback) / kapitalizacja → 3 pkt;
- brak cięcia DPS: `_no_dividend_cut`, DPS bieżący ≥ poprzedni, czyli dla 0 ≥ 0 → prawda → 3 pkt;
- bezpieczny payout: dywidendy / FCF ≤ 75%, czyli dla 0% → prawda → 2 pkt;
- malejąca lub stała liczba akcji → 2 pkt.

**Konsekwencja.**
- Spółka bez dywidendy, ale z buybackiem, dostaje 10/10, tak jak wieloletni dywidendowy „arystokrata”.
- 5 z tych 10 punktów pochodzi z kryteriów dywidendowych, które dla 0 są spełnione automatycznie.
- Wariant E zmienia 6 spółek shortlisty.

**Świadoma zasada czy uproszczenie?** W dokumentacji jest zasada „brak danych nie daje punktów”. Zero dywidendy nie jest jednak brakiem danych, więc ta zasada go nie obejmuje. Nie znalazłam decyzji, że „brak cięcia” i „bezpieczny payout” mają nagradzać spółki niewypłacające dywidendy. Status: **prawdopodobnie efekt uboczny, niezweryfikowany**.

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) Bez zmian (buyback = równoważny zwrot dla akcjonariuszy) | Spójne z „shareholder return” | Kryteria dywidendowe tracą sens |
| b) Kryteria dywidendowe „nie dotyczy” dla spółek bez dywidendy + renormalizacja w komponencie | Neutralnie dla obu grup | Ten sam problem baz punktowych co w pkt 4 |
| c) 0 pkt za kryteria dywidendowe bez dywidendy | Prosto, dosłownie | Karze spółki wzrostowe; preferuje dywidendowe |
| d) Komponent oparty wyłącznie na shareholder yield i liczbie akcji | Jedna miara całkowitego zwrotu | Zmiana definicji komponentu |

**Kalibracja/walidacja:** tak. Dane dywidendowe istnieją w backteście 2012–2021.

## 4. Porównywanie wyników przy różnych bazach punktowych

**Reguła i źródło.** `backtest_harness.compute_deterministic_score`: procent = punkty / maksimum dostępnych komponentów. Brak wyceny zmniejsza bazę z 45 do 25 pkt. Shortlista: `live_scan_pipeline.select_shortlist` (TOP N po procencie, remisy zachowane).

**Konsekwencja.**
- PODD (25/25 = 100%) jest na 4. miejscu, przed DXCM (44,8/45 = 99,6%).
- CEG, NFLX i UBER (22,2/25 = 88,8%) wyprzedzają spółki z 39,4/45 (87,5%).
- Brak wyceny bywa korzystny: spółka unika oceny w najbardziej wymagającym komponencie.
- Wariant A usuwa wszystkie 4 spółki bez DCF.
- Renormalizacja tworzy też liczne remisy (5 spółek po 100%).

**Świadoma zasada czy uproszczenie?** **Świadoma zasada** (projekt backtestu v1.41, 2026-10-01): brak komponentu nie może liczyć się jako 0. Jej skutek dla mieszania baz 25 i 45 pkt w jednym rankingu nie był oceniany. W backteście bazowym 100% obserwacji miało bazę 25.

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) Bez zmian | Brak kary za brak danych | Zawyża spółki bez DCF |
| b) Brak = 0 | Prosto | Karze uzasadniony brak wyceny jak złą wycenę |
| c) Neutralne uzupełnienie (np. połowa punktów lub mediana grupy) | Kompromis | Arbitralne |
| d) Osobna kolejność: najpierw pełne bazy, potem częściowe (jak `total_score`: complete przed partial) | Spójne z istniejącą regułą finalnego rankingu | Spółki bez DCF rzadko na shortliście |
| e) Osobna, mała pula dla spółek bez DCF | Widoczne, ale nieporównywane | Więcej złożoności |

**Kalibracja/walidacja:** tak, zmienia selekcję.

## 5. Brak DCF przez ujemny pierwszy rok FCF

**Reguła i źródło.** `valuation.historical_owner_earnings_cagr_pct`: CAGR wyłącznie między pierwszym a ostatnim okresem, oba muszą być dodatnie. Komunikat w `_compute_dcf_owner_earnings` mówi „potrzeba ≥2 okresów z dodatnim FCF”, co nie odpowiada regule.

**Konsekwencja.**
- UBER (4/5 lat dodatnich), NFLX (4/5) i PODD (3/5) nie mają DCF, mimo kilku lat dodatniego FCF.
- Ta sama reguła daje skrajne CAGR, gdy pierwszy rok jest niski: MU 109%, DXCM 112%, APP 82%.
- Na shortliście takie spółki trafiają na sufit 20%.

**Świadoma zasada czy uproszczenie?** Zasada „nie zgadujemy wzrostu” jest świadoma. CAGR z dwóch punktów to **uproszczenie**. Komunikat jest **błędem opisu** (do poprawy niezależnie od decyzji, bo poprawa nie zmienia wyników).

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) CAGR od pierwszego dodatniego roku (min. 3 lata) | Mała zmiana | Nadal wrażliwe na punkty końcowe |
| b) Trend log-liniowy z lat dodatnich | Mniej wrażliwe na jeden rok | Pomija lata ujemne |
| c) Mediana wzrostu r/r | Odporna na skoki | Niestabilna przy małej bazie |
| d) Wzrost = 0, gdy CAGR nieokreślony | Ostrożnie; DCF dostępny | Zaniża spółki wzrostowe |
| e) Bez zmian, tylko poprawiony komunikat | Brak zmian wyników | Problem merytoryczny zostaje |

**Kalibracja/walidacja:** a–d tak; e nie.

## 6. Ryzyko zawyżonego MoS u spółek cyklicznych

**Reguła i źródło.** Podstawą DCF jest **najnowszy** FCF (`latest_oe = FCF(periods[-1])`). Rośnie on w tempie CAGR liczonym od punktu startowego, który bywa dołkiem cyklu. Nie ma normalizacji przez cykl ani flagi cykliczności (w dokumentacji 0 wzmianek).

**Konsekwencja.** Najnowszy FCF względem średniej z okna:

| Spółka | Najnowszy / średni FCF | MoS BASE | MoS przy średnim FCF | MoS przy suficie 10% |
|---|---|---|---|---|
| SNDK | 5,4× | 71% | −50% | 40% |
| MU | 5,1× | 72% | −37% | 41% |
| APP | 2,5× | 61% | 1% | 17% |
| DXCM | 2,1× | 50% | −6% | −8% |

Wariant C (średni FCF) usuwa 7 spółek z shortlisty.

**Świadoma zasada czy uproszczenie?** **Udokumentowane uproszczenie:** „Owner Earnings PROXY = FCF … do zastąpienia dokładniejszą metodologią”. Cykliczność nie jest nigdzie adresowana.

**Możliwe rozwiązania.**

| Rozwiązanie | Zalety | Wady |
|---|---|---|
| a) FCF znormalizowany (średnia lub mediana z okna) | Prosto, mniej szczytów | Zaniża spółki z trwałą poprawą |
| b) Mniejszy z: najnowszy, średni | Ostrożnie | Systematycznie zaniża wzrostowe |
| c) Marża w średnim cyklu × bieżące przychody | Standard dla cyklicznych | Wymaga dłuższej historii |
| d) Flaga cykliczności (np. najnowszy/średni > 2×) i punkty z BEAR albo brak punktów za wycenę | Celowane | Arbitralny próg |
| e) Klasyfikacja sektorowa (półprzewodniki, surowce) | Ekonomicznie uzasadnione | Wymaga danych sektorowych |

**Kalibracja/walidacja:** tak.

---

## Inne obserwacje (bez zmian)

- **APO (Apollo Global Management)** ma profil GENERAL i wycenę DCF z FCF, mimo że to zarządzający aktywami z działalnością ubezpieczeniową. Do weryfikacji: klasyfikacja sektorowa (MoS 84%).
- **„FCF TTM” to w rzeczywistości ostatni FCF roczny**, bo model używa wyłącznie okresów rocznych.
- **FMP zwraca 0 zamiast braku wartości dla części pozycji.** Prawdziwego zera nie da się odróżnić od braku danych.
- **`config.yaml` ma `data_provider.plan: free`**, a skan wykonuje ok. 1 100 zapytań do FMP. Etykieta planu prawdopodobnie jest nieaktualna (nie weryfikowałam planu).

## Ograniczenie walidacji dowolnej zmiany

Holdout 2022–2026 został zużyty jednorazowo. Uczciwe możliwości walidacji zmian:
1. Ponowne testy na oknie kalibracyjnym 2012–2021 z wewnętrznymi foldami poza próbką. Uwaga: mało obserwacji z pełną wyceną (n = 1 111).
2. Śledzenie wyników nowych skanów od teraz (forward tracking), bez wpływu na decyzje.

Decyzja o zmianie bez walidacji to decyzja ekspercka i powinna być tak oznaczona.
