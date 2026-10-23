# Propozycje do decyzji — runda 3 (2026-10-23)

Status: **wyłącznie analizy i propozycje. Nic nie zostało wdrożone; produkcyjna metodologia bez zmian. Bez płatnych API, bez skanu, bez publikacji.**

Symulacje:
- skrypt `docs/analysis/round3_2026_10_23.py`, pełny wynik w `docs/analysis/round3_2026_10_23_results.txt`;
- dane skanu 22.10, kod scoringu z gałęzi roboczej (poprawki 1–4);
- założenia jak w rundzie 2: GL = INSURER, ARE i WY = REIT (źródła wtórne), CAPEX = 0 bez potwierdzenia u APO i COIN → brak danych.

Grupy na 22.10 po decyzjach z rundy 3:

| Grupa | Liczba | Spółki / uwagi |
|---|---|---|
| Z DCF | 117 | |
| Bez DCF (reguła wyceny) | 39 | |
| Brak odpowiedniej metody oceny | 3 | GL, ARE, WY |
| Niekompletne lub niewiarygodne dane | 3 | APO, COIN, HONA |

---

## 1. Kwalifikacja do Claude według kryteriów (bez kwot miejsc)

### 1.1 Zasada: dwie niezależne warstwy

**Warstwa 1 — kwalifikacja inwestycyjna.**
- Spółka spełnia kryteria swojej grupy albo nie. Liczba zakwalifikowanych (Q) wynika wyłącznie z tego.
- Brak listy rankingowej z granicą. Nie ma więc kwot ani podziału miejsc między grupami.
- Remisy nie mają znaczenia: nie istnieje pozycja graniczna, o którą spółki konkurują.
- Równość z progiem kwalifikuje (≥). Porównujemy wartości surowe, nie zaokrąglone do wyświetlenia.

**Warstwa 2 — limit kosztowy.**
- Najgorszy przypadek: W = |Q| × 3 wywołania (analiza + do 2 napraw, `MAX_REPAIR_ATTEMPTS = 2`).
- Jeśli W ≤ limit, analizowane jest całe Q.
- Jeśli W > limit, **skan zatrzymuje się przed pierwszym wywołaniem Claude**. Raport podaje Q i limit potrzebny do analizy. Decyzja należy do właścicielki:
  - (a) podnieść limit dla tego skanu;
  - (b) przeanalizować Q w kilku partiach (wznowienia), aż całe Q będzie przeanalizowane.
- **Nigdy nie ma obcinania Q** według wyniku, alfabetu ani losowania.
- Licznik wywołań w trakcie działania zostaje (już istnieje) jako drugie zabezpieczenie. Jeśli mimo kontroli wstępnej zostanie osiągnięty:
  - pozostałe spółki dostają status „nieprzeanalizowane z powodu limitu”;
  - skan ma status INCOMPLETE i nie może być opublikowany.
- **Progi kwalifikacji nie są dopasowywane do budżetu w żadnym skanie.** Zmiana progu to decyzja metodologiczna, nie operacyjna.

### 1.2 Kryteria w grupach (propozycja)

| Grupa | Kryterium bezpieczeństwa | Kryterium wyceny | Do Claude |
|---|---|---|---|
| Z DCF | K-B (to samo dla obu grup operacyjnych) | K-W: MoS BASE ≥ próg | gdy K-B i K-W |
| Bez DCF | K-B | brak miary wyceny → oznaczenie „bez weryfikacji wyceny” | gdy K-B (wariant Q-B1, patrz 1.4) |
| Brak metody oceny | nie stosujemy kryteriów spółek operacyjnych | brak | nie (sekcja 2) |
| Niekompletne dane | brak wiarygodnych danych | brak | nie |

Oba kryteria to **istniejące, dziś wyłączone bramki** z `config.yaml` (`hard_gates.min_financial_safety`, `hard_gates.min_margin_of_safety_pct`). Kwalifikacja nie wymaga więc nowej koncepcji, tylko ich włączenia i zdefiniowania progów. K-B można określić na dwa sposoby:
- **K-B1 — próg punktowy:** `financial_quality_score` (0–16 pkt, 6 obecnych kryteriów) ≥ próg.
- **K-B2 — rdzeń wypłacalności:** trzy obecne kryteria łącznie:
  - FCF > 0;
  - dług netto / EBITDA ≤ 2;
  - brak trwałych strat.
  K-B2 jest łatwiejszy do zinterpretowania (każdy warunek ma jedno znaczenie ekonomiczne) i nie zależy od wag kryteriów.

### 1.3 Siatka progów na 22.10 (do decyzji, nie wybór)

K-B1, próg w punktach surowych na 16 (w nawiasie odpowiednik na skali wagi 15). Ostatnia kolumna: ile z 24 spółek obecnej shortlisty znalazłoby się w Q.

| Bezpieczeństwo ≥ | MoS ≥ | Q z DCF | Q bez DCF | Razem | Maks. wywołań | Wspólne z obecną shortlistą |
|---|---|---|---|---|---|---|
| 8 (7,5) | 0% | 50 | 21 | 71 | 213 | 23/24 |
| 8 (7,5) | 50% | 22 | 21 | 43 | 129 | 19/24 |
| 10 (9,4) | 25% | 40 | 18 | 58 | 174 | 23/24 |
| 12 (11,25) | 0% | 35 | 8 | 43 | 129 | 18/24 |
| 12 (11,25) | 25% | 29 | 8 | 37 | 111 | 18/24 |
| 12 (11,25) | 50% | 13 | 8 | 21 | 63 | 14/24 |
| 14 (13,1) | 25% | 14 | 3 | 17 | 51 | 11/24 |
| 14 (13,1) | 50% | 6 | 3 | 9 | 27 | 7/24 |

Pełna siatka (12 kombinacji) jest w pliku wyników.

K-B2 (rdzeń wypłacalności):

| MoS ≥ | Q z DCF | Q bez DCF | Razem | Wspólne z obecną shortlistą |
|---|---|---|---|---|
| 0% | 41 | 9 | 50 | 21/24 |
| 25% | 34 | 9 | 43 | 21/24 |
| 50% | 17 | 9 | 26 | 17/24 |

Przykład składu (K-B2, MoS ≥ 50%):
- **z DCF:** ADBE, APP, BKNG, CHRW, DECK, EME, EXE, F, HII, INTU, JBHT, JBL, LDOS, MU, SNDK, TPR, TYL;
- **bez DCF:** CEG, CVNA, FSLR, GEV, LEN, NFLX, PODD, RDDT, UBER.

Obserwacje:
- **Q zmienia się kilkukrotnie w zależności od progów (9–71 spółek).** Przy obecnym limicie roboczym 75 wywołań mieści się do 25 spółek. Część kombinacji będzie więc regularnie wymagać decyzji o limicie albo o partiach. To skutek oddzielenia jakości od kosztu, a nie błąd. Koszt staje się jawny zamiast ukryty w N.
- **APO** jest na obecnej shortliście, a w żadnym wariancie nie trafia do Q (grupa niekompletnych danych).
- **MoS ≥ 0%** to jedyny próg wyceny wynikający z definicji („cena poniżej wartości BASE”). 25% i 50% to wybór inwestycyjny. 50% to dziś granica pełnych punktów za wycenę, więc nie byłaby nową liczbą.

### 1.4 Asymetria grupy bez DCF

Spółka bez DCF ma do spełnienia jedno kryterium zamiast dwóch. Przy K-B1 ≥ 12 i MoS ≥ 50%:
- kwalifikuje się 8 z 39 spółek bez DCF (21%);
- kwalifikuje się 13 z 117 spółek z DCF (11%).

| Wariant | Reguła | Ocena |
|---|---|---|
| **Q-B1** | Bez DCF: tylko K-B, z oznaczeniem „bez weryfikacji wyceny” | Bez kwot nie ma rywalizacji o miejsca, więc kwalifikacja spółki bez DCF **nikogo nie wypiera**. Asymetria podnosi tylko koszt. Wynik końcowy pozostaje na osobnej liście, bez porównania z wynikami z DCF. |
| Q-B2 | Bez DCF nie trafia do Claude | Faktycznie wyklucza; to ukryta kara, którą wcześniej odrzuciłaś. |
| Q-B3 | Bez DCF: ostrzejszy próg K-B | Ostrzejszy próg nie ma uzasadnienia merytorycznego (arbitralny). |
| Q-B4 | Bez DCF: zastępcze kryterium wyceny (np. rentowność FCF) | Nowe kryterium wyceny: wymaga osobnego projektu i testu. Nie teraz. |

**Rekomendacja techniczna: Q-B1.**

### 1.5 Czego nie wiemy (uczciwie)
- **Historia nie potwierdza skuteczności takich progów.**
  - Runda 1 (5.4a) testowała `min_financial_safety = 7,5/15` jako bramkę selekcji. Wynik: remis z baseline (mediana nadwyżki identyczna, 0,7608%). Bez poprawy, ale też bez szkody.
  - Bramka MoS nie była testowana.
  - Holdout 2022–2026: wynik z wyceną korelował ze zwrotem słabiej niż bez wyceny (Spearman 0,031 wobec 0,135).
- **Progi są dziś decyzją inwestycyjną, nie wnioskiem z danych.** Każdy test historyczny tych progów byłby kolejnym spojrzeniem na lata 2012–2021 (patrz 4.3).
- W tej architekturze **dywidendy nie wpływają na skierowanie do Claude.** Wpływają tylko na wynik końcowy. To skutek konstrukcji, a nie przeoczenie.

### 1.6 Decyzje do podjęcia
1. Forma K-B: K-B1 (próg punktowy) czy K-B2 (rdzeń wypłacalności).
2. Próg K-B i próg K-W.
3. Grupa bez DCF: Q-B1 czy inny wariant.
4. Przekroczenie limitu: zatrzymanie przed Claude (rekomendacja) czy automatyczne partie.

---

## 2. Spółki finansowe i REIT — zakres przyszłej metodologii (bez projektowania modeli)

### 2.1 Traktowanie teraz (zgodnie z decyzją)
- Osobna grupa „brak odpowiedniej metody oceny”, widoczna w raporcie z przyczyną.
- Bez wyniku bezpieczeństwa i bez wyceny. Nie trafia do rankingu ani do Claude.
- **Oznaczenie neutralne: „nieoceniona”, nie „odrzucona”.** GL (dziś 15/15 z kryteriów nieadekwatnych dla ubezpieczyciela) przestaje być oceniana tymi kryteriami.

### 2.2 Skala problemu
- **Backtest:** 88 z 615 CIK (14%): BANK 20, INSURER 35, REIT 33 (log klasyfikacji z 5.10.2026, run 37313299445).
- **Skan 22.10:** 3 z 162 rankowanych spółek.
- **Pytanie do zakresu:** zarządzający aktywami i brokerzy (SIC 6282 i 6211: APO, ARES, BX, KKR, COIN, HOOD) mają dziś profil GENERAL. Ich bilanse (konsolidowane fundusze, środki klientów) mogą zniekształcać miary operacyjne, ale tego nie zweryfikowałam. Czy przyszła metodologia ma ich obejmować — do decyzji.

### 2.3 Zakres przyszłych prac (lista pytań, nie rozwiązania)

| Profil | Wymiary oceny do zdefiniowania | Ryzyko danych (do sprawdzenia) |
|---|---|---|
| Bank | rentowność kapitału; adekwatność kapitałowa; jakość kredytów; finansowanie i płynność; wycena względem wartości księgowej | Miary regulacyjne (np. współczynniki kapitałowe) często nie są standardowymi tagami us-gaap w XBRL. Dostępność w FMP nieznana. |
| Ubezpieczyciel | rentowność ubezpieczeniowa; adekwatność rezerw; portfel inwestycyjny; wzrost wartości księgowej | Ubezpieczyciele majątkowi i na życie wymagają innych miar (GL to życie/zdrowie). Możliwy podział profilu. |
| REIT | przepływy z działalności nieruchomościowej (FFO/AFFO); dźwignia; wartość aktywów netto | FFO/AFFO to miary spoza GAAP, raportowane przez spółki, nie standardowe w XBRL. WY (las) jest nietypowym REIT. |

**Każdy profil wymagałby osobno:**
- źródeł danych zweryfikowanych w FMP i SEC (także historycznie, dla backtestu);
- kryteriów bezpieczeństwa i metody wyceny;
- protokołu testu;
- osobnej listy w rankingu.

Pierwsza decyzja: **czy przy 3 spółkach na skan i 14% historycznego uniwersum warto to budować teraz, czy później.**

---

## 3. Zwrot kapitału — doprecyzowany P-D3 (10 pkt)

### 3.1 Jak mierzyć poprawnie: odpowiedzi na pięć pytań

| Zagadnienie | Propozycja | Uzasadnienie |
|---|---|---|
| **Buyback netto i rozwodnienie** | Mierzyć **zmianą liczby akcji rozwodnionych w 3 latach**, a nie kwotą buybacku minus emisje | Kwota emisji (I_t) nie jest dziś pobierana. Liczba akcji łapie łącznie skup, emisje, opcje i SBC. Jest w obu źródłach (FMP i SEC), więc skan i backtest liczą to samo. |
| **Finansowanie długiem** | Porównanie wypłat z 3-letnim FCF; nadwyżka przy rosnącym **długu brutto** = 0 pkt | **Dług netto się nie nadaje:** wypłata z gotówki też go podnosi. Pieniądz jest wymienny: jeśli spółka wypłaca więcej niż wypracowała i jednocześnie zaciąga dług, wypłaty są de facto finansowane długiem. |
| **Wieloletni FCF** | Sumy 3-letnie (t−2..t) wypłat i FCF | Wygładza pojedynczy rok (cykl, jednorazowe wydatki). |
| **Brakujące dane** | Brak wejścia kryterium → 0 pkt + oznaczenie NIEZNANE. Brak D, B lub S w najnowszym okresie → grupa niekompletnych danych (M4 z rundy 2). | Brak danych nie może dawać punktów ani wyglądać jak „zły wynik”. |
| **Spółki reinwestujące** | 0 pkt we wszystkich kryteriach. Brak punktów za nieistniejące dywidendy. | Komponent mierzy zwrot kapitału. Jakość reinwestycji ocenia Claude w sekcji „management_capital_allocation” (10 z 45 pkt). Opcje w 3.4. |

### 3.2 Punktacja (propozycja, progi do decyzji)

Okno: 3 ostatnie lata obrachunkowe (t−2..t). Liczba akcji: S_t wobec S_{t−3}.

**A. Zwrot netto (0–4 pkt)**
- NSY3 = średnia roczna dywidenda / kapitalizacja + roczne tempo spadku liczby akcji.
  - Tempo spadku jest ujemne przy rozwodnieniu.
  - Kapitalizacja = cena × S_t.
- Punkty liniowo: 0 pkt przy NSY3 ≤ 0, 4 pkt przy NSY3 ≥ T.
- **T to nowy próg do decyzji.** Na 22.10 policzone dwa warianty: 4% i 6%. Mediana NSY3 w spółkach operacyjnych: 2,21%.

**B. Źródło finansowania (0–4 pkt)** — tylko gdy spółka zwracała kapitał (D3 + B3 > 0)

| Warunek | Punkty |
|---|---|
| (D3 + B3) ≤ FCF3 przy FCF3 > 0 | 4 |
| Nadwyżka ponad FCF3, ale dług brutto nie wzrósł | 2 |
| Nadwyżka przy rosnącym długu brutto albo FCF3 ≤ 0 | 0 + flaga |

**C. Ciągłość (0–2 pkt)**
- 2 pkt: zwrot kapitału w każdym z 3 lat (D > 0 lub B > 0), a u płacących brak cięcia DPS r/r (reguła jak dziś).
- Spółka bez zwrotu: 0 pkt.
- Cięcie buybacku nie jest karane: buyback jest z założenia uznaniowy.

**Bez kredytu za brak.** Ani A, ani B, ani C nie przyznaje punktów spółce, która nic nie wypłaca.

### 3.3 Przykłady (22.10, T = 4%)

| Spółka | Dziś | Dyw. yield 3 l. | Liczba akcji %/rok | NSY3 | A | Wypłaty / FCF3 | B | C | **P-D3** | P-D3 przy T = 6% | Uwagi |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MRK | 10 | 2,12% | −0,46 | 2,58% | 2,6 | 79% | 4 | 2 | **8,6** | 7,7 | dług brutto wzrósł (32,0 → 50,5 mld USD), ale wypłaty pokryte z FCF — bez kary |
| SNA | 10 | 2,16% | −0,74 | 2,90% | 2,9 | 67% | 4 | 2 | **8,9** | 7,9 | |
| QCOM | 10 | 1,91% | −0,95 | 2,86% | 2,9 | 79% | 4 | 2 | **8,9** | 7,9 | |
| CHTR | 10 | 0 | −5,73 | 5,73% | 4,0 | 86% | 4 | 2 | **10,0** | 9,8 | sam buyback, pokryty z FCF |
| DECK | 10 | 0 | −3,07 | 3,07% | 3,1 | 69% | 4 | 2 | **9,1** | 8,0 | |
| APP | 10 | 0 | −2,73 | 2,73% | 2,7 | 61% | 4 | 2 | **8,7** | 7,8 | |
| NFLX | 10 | 0 | −1,47 | 1,47% | 1,5 | 92% | 4 | 2 | **7,5** | 7,0 | |
| ADBE | 10 | 0 | −3,22 | 3,22% | 3,2 | 102% | 0 | 2 | **5,2** | 4,1 | wypłaty > FCF3, dług brutto 4,6 → 6,6 mld USD |
| TPR | 10 | 1,32% | −4,50 | 5,81% | 4,0 | 112% | 0 | 2 | **6,0** | 5,9 | wypłaty > FCF3, dług brutto wzrósł |
| AVGO | 8 | 0,61% | +4,69 | −4,08% | 0 | 86% | 4 | 2 | **6,0** | 6,0 | liczba akcji +15% (emisja przy przejęciu VMware) |
| UBER | 10 | 0 | +2,39 | −2,39% | 0 | 39% | 4 | 0 | **4,0** | 4,0 | buyback dopiero od 2 lat, liczba akcji rośnie |
| BA | 6 | 0,08% | +8,60 | −8,52% | 0 | — | 0 | 0 | **0** | 0 | FCF3 ≤ 0; „dywidenda” 331 mln USD w FY2025 — patrz 3.5 |
| AXON, BSX, CVNA | 5 | 0 | rozwodnienie | < 0 | 0 | — | 0 | 0 | **0** | 0 | czysta reinwestycja |

W kolumnie „Liczba akcji %/rok” znak minus oznacza spadek liczby akcji, plus — wzrost.

Inne ścieżki:
- **B = 2** (nadwyżka bez wzrostu długu brutto): BX, LITE, NKE, PG, PYPL.
- **10/10:** CAT, CHTR, CMCSA, FIS, LEN, LOW, ULTA, VST, WYNN.

### 3.4 Skutki zbiorcze (spółki operacyjne, 22.10)
- Mediana punktów 6,0. Przy T = 4%: 9 spółek z 10/10 i 15 z 0. Przy T = 6%: 5 z 10/10.
- **Bez dywidendy w oknie: 52 spółki. Dziś 29 z nich ma 10/10, po zmianie 2.**
- Czysta reinwestycja: 8 spółek (AXON, BSX, CVNA, DDOG, FDXF, HONA, RDDT, TYL): dziś 3–5 pkt, po zmianie 0.
- Wypłaty nie pokryte 3-letnim FCF: 56 spółek; w tym przy rosnącym długu brutto: 36 (np. ADBE, ADI, APTV, BKNG, CARR, CLX, CSX, FICO, GIS).
- Buyback w oknie, a liczba akcji wzrosła w 3 latach: 42 spółki (np. AMD, ANET, APH, AVGO, BX, DASH).
- **TOP 20 + remisy** (obecna reguła rankingu na grupach z DCF i bez DCF, bez spółek bez metody oceny i niekompletnych; tylko informacyjnie):
  - wypadają: APTV, CEG, FISV, JBL, NFLX, PODD, UBER;
  - wchodzą: CHRW, CMCSA, F, IR.

  Przy kwalifikacji z sekcji 1 dywidendy nie decydują o skierowaniu do Claude.

**Spółki reinwestujące — opcje:**

| Opcja | Reguła | Ocena |
|---|---|---|
| **R1** | 0 pkt (komponent mierzy zwrot kapitału) | Spójne z Twoją zasadą. Względem spółek zwracających kapitał różnica do 10 pkt (ok. 22 pp wyniku przy bazie 45 pkt). |
| R2 | „Nie dotyczy” + renormalizacja | Sztuczna przewaga przez normalizację — ten sam problem co przy braku DCF. Odradzam. |
| R3 | Kryterium jakości reinwestycji (test jednego dolara albo ROIC) | Wymaga nowych danych. W bazie są ceny z ok. 13 miesięcy (test potrzebuje 5 lat). Kapitał własny nie jest pobierany (ROIC). Nie teraz. |

**Rekomendacja techniczna: R1.** Jakość reinwestycji ocenia Claude.

### 3.5 Ograniczenia danych (znalezione w tej analizie)
- **Liczba akcji z emisją przy przejęciu (AVGO).** Udział akcjonariusza naprawdę się rozwodnił, ale w zamian za aktywa. Propozycja liczy to jako ujemny zwrot. Do decyzji, czy to akceptujesz; ocenę samej transakcji zostawiam Claude.
- **BA: FMP podaje 331 mln USD dywidend w FY2025.** O ile wiem, BA nie płaci dywidendy od akcji zwykłych od 2020 r. Możliwe, że to dywidenda od akcji uprzywilejowanych, ale tego nie zweryfikowałam. **Do sprawdzenia w 10-K** przed oparciem się na polu `dividends_paid`.
- **DPS liczony z wypłat gotówkowych** może pokazać „cięcie”, które jest tylko przesunięciem terminu płatności. Przykład: TPR, FY2025 vs FY2024, przy oknie wieloletnim. Dlatego w C zostawiłam regułę r/r jak dziś. Rozwiązanie docelowe: zadeklarowany DPS (nowe pole, dostępność do sprawdzenia).
- **Próg 100% pokrycia ma efekt progu.** ADBE przy 102% traci 4 pkt (dług brutto wzrósł).
- **FMP może raportować brak danych jako 0.** Na 22.10 zero braków D, B, S, ale tego nie da się odróżnić od prawdziwego zera bez SEC.
- **Kalibracja T i wag 4/4/2** wymaga danych historycznych. D, B i S są w backteście (SEC). Komponent dywidend był już oglądany na 2012–2021 (runda 2A: wagi 15/10, 20/5, 10/15, 12,5/12,5), więc to nie byłyby świeże dane.

### 3.6 Decyzje do podjęcia
1. Struktura A/B/C i wagi 4/4/2.
2. Próg T.
3. Opcja dla spółek reinwestujących (R1 rekomendowana).
4. Traktowanie emisji przy przejęciach.

---

## 4. Protokół historyczny — fakty przed wersją v2 (bez zamrażania)

### 4.1 Historyczna klasyfikacja SIC

**Stan obecny (sprawdzony w kodzie i logach):**
- Backtest i kalibracja klasyfikują każdą spółkę **dzisiejszym** kodem SIC: SEC Submissions API, pole `sic`, pobierane w chwili uruchomienia. Ten sam profil obowiązuje dla wszystkich dat 2012–2021.
- Log z 5.10.2026 (run 37313299445): 615 CIK → BANK 20, GENERAL 527, INSURER 35, REIT 33, zero błędów SEC.
- **Liczba CIK bez kodu SIC nie jest logowana.** Takie spółki są liczone jako GENERAL. Nie da się jej odczytać z istniejących logów.
- **Ten sam błąd co w skanie na żywo przed poprawką 1:** w backteście błąd SEC zostawia profil bez zmian, czyli domyślnie GENERAL. W sprawdzonym runie błędów nie było, ale reguła wymaga wyrównania w pakiecie.

**Możliwość odtworzenia point-in-time:**
- Nagłówek każdego zgłoszenia EDGAR zawiera „STANDARD INDUSTRIAL CLASSIFICATION” z dnia złożenia. Wcześniej widziane na przykładzie WY: 2400 w zgłoszeniach 1995–2000, 6798 w 2016.
- Reguła: profil w dacie decyzji = SIC z ostatniego 10-K lub 10-Q złożonego najpóźniej w tej dacie.
- Koszt: ok. 615 CIK × ok. 15 raportów rocznych ≈ 9 tys. zapytań do SEC. Bezpłatnie; przy limicie SEC (10 zapytań/s) ok. 15–30 minut w GitHub Actions.
- **Niezweryfikowane założenie:** że nagłówek zawsze pokazuje SIC z dnia złożenia, a nie stan zaktualizowany wstecz. Opiera się na jednym przykładzie. Przed użyciem trzeba sprawdzić na próbie.
- **Zastrzeżenie merytoryczne:** SIC zmienia się z opóźnieniem względem biznesu (WY jest REIT od 2010 r.). Point-in-time usuwa wiedzę z przyszłości, ale nie usuwa błędnej klasyfikacji.

**Znaczenie dla protokołu wyceny:** warianty są porównywane z V0 na tych samych obserwacjach. Błąd klasyfikacji dotyczy więc wszystkich wariantów jednakowo i nie faworyzuje żadnego. Klasyfikacja point-in-time jest pożądana, ale dla porównania względnego nie blokuje. Jest konieczna dla twierdzeń bezwzględnych („model daje X% ponad rynek”).

### 4.2 Rzeczywiste liczebności prób

Kalibracja, okno 2012–2021, foldy poza próbką 2016–2021. Źródła: design review 5.4a i 5.4c oraz log runu 37313299445.

| Rok | Wszyscy kandydaci | Z wyceną (podzbiór rundy 2B) |
|---|---|---|
| 2012 | 431 | brak danych* |
| 2013 | 319 | brak danych* |
| 2014 | 316 | brak danych* |
| 2015 | 705 | brak danych* |
| 2016 | 879 | 177 |
| 2017 | 481 | 108 |
| 2018 | 741 | 138 |
| 2019 | 1 042 | 229 |
| 2020 | 2 113 | 365 |
| 2021 | 578 | 94 |
| **Razem 2016–2021** | **5 834** | **1 111** |

\* 2012–2015 to lata rozgrzewki; podzbioru z wyceną dla nich nie raportowano. Uwaga na różne definicje: 2012–2015 = wszyscy kandydaci (raport 5.3c; suma 2012–2021 w tym raporcie = 7 847, tyle samo co w kalibracji), 2016–2021 = kandydaci z dostępnym zwrotem 6 m (np. 2016: 900 kandydatów, 879 ze zwrotem).

Wnioski:
- **Liczebności to obserwacje spółka-miesiąc, a nie niezależne spółki.** Ta sama spółka występuje w wielu kolejnych miesiącach, a 6-miesięczne zwroty z miesięcznych dat się nakładają. Efektywna liczba niezależnych obserwacji jest wielokrotnie mniejsza; dokładnie jej nie znam.
- Liczbę unikalnych spółek na rok można policzyć z artefaktu kalibracji (`calibration-round1-baseline-db`, retencja 30 dni od 5.10, czyli do ok. 4.11.2026). **Z tego środowiska pobranie jest zablokowane przez proxy.** Wymagałoby to krótkiego, bezpłatnego workflow.
- Populacja wspólna dla wszystkich wariantów będzie **nie większa niż kolumna „z wyceną”**. Przy regule „n ≥ 100” rok 2021 (94) odpada już dla V0. Kryterium „4 z 6 lat” jest w praktyce niewykonalne.
- **Propozycja:** decyzja na podstawie wyniku łącznego z bootstrapem; lata pokazywane tylko opisowo.

### 4.3 Co było już analizowane na tych danych

| Kiedy | Co | Okres i populacja | Czy patrzono na zwroty |
|---|---|---|---|
| 5.3c / 5.3g | Baseline walk-forward | 2012–2026, pełna | tak (zbiorcze rozkłady zwrotów i nadwyżek za cały okres, bez podziału na lata) |
| Runda 1 (5.4a) | 4 warianty selekcji: ostrzejsze spadki, bramka bezpieczeństwa 7,5, wykluczenia prefiltra, kombinacja | 2012–2021, foldy 2016–2021 | tak (metryka główna) |
| Runda 2A | Wagi bezpieczeństwo/dywidendy: 15/10, 20/5, 10/15, 12,5/12,5 | jw., pełna populacja | tak |
| Runda 2B | Waga wyceny 0/10/20/30 (z wyceną i bez niej) | jw., podzbiór z wyceną (1 111) | tak |
| Runda 3 (5.4d) | MoS pełnych punktów 35/50/65; sufity wzrostu 15/−3 i 25/−7 | stabilność 2012–2021; zwroty 2016–2021 | tak (diagnostycznie: Spearman 0,113–0,126) |
| Holdout (5.6) | Model zamrożony, z wyceną i bez | 2022–2026, jednorazowo | tak |
| 22.10 | 16 wariantów wrażliwości wyceny i dywidend | jeden przekrój, bez zwrotów | nie |

Uwaga do pierwszego wiersza: raport 5.3c (punkty 6 i 8) pokazał zbiorcze zwroty i nadwyżki kandydatów za cały okres 2012–2026, bez wyceny i bez podziału na lata. Lata 2022–2026 były więc widziane zbiorczo, zanim otwarto holdout; per rok pokazano tylko liczebności kandydatów.

**Wniosek:**
- **Żaden okres 2012–2021 nie jest świeży.** Lata 2016–2018 i 2019–2021 były foldami OOS we wszystkich trzech rundach.
- Wariant G1 (sufit 15%) jest bliski oglądanemu w rundzie 3 wariantowi 15/−3.
- **Podziału 2016–2018 / 2019–2021 nie wolno nazywać niezależną walidacją.** To podział wewnętrzny na danych już używanych.

### 4.4 Ograniczenie przeuczenia i wielokrotnego testowania (propozycja do v2)
1. **Mniej wariantów, każdy z uzasadnieniem z audytu, nie z wyników.** Jeden wariant na zidentyfikowany problem:
   - stały wzrost przez 10 lat → G3 (wygaszanie);
   - baza z jednego roku → F1 (średnia);
   - CAGR z dwóch punktów → C2 (trend log-liniowy).

   Razem 3 zamiast 12. G1 i G2 wypadają, bo sufity były już oglądane w rundzie 3.
2. **Jedna metryka główna i jeden horyzont** (Spearman, 6 m, liczony w każdej dacie). Pozostałe metryki tylko opisowo.
3. **Korekta Holma** na 3 porównania; bootstrap blokowy (≥ 6 miesięcy, wrażliwość 9 i 12).
4. **Asymetryczna reguła decyzji:** domyślnie V0. Zmiana tylko przy istotnej poprawie **i** uzasadnieniu ekonomicznym. Brak różnicy = V0 zostaje.
5. **Zamrożenie przed uruchomieniem:** commit z hashem protokołu i kodu; raport wszystkich wariantów, także niekorzystnych.
6. **Jedyna niezależna walidacja: prospektywna.** Warianty liczone w każdym przyszłym skanie „w cieniu”:
   - tylko zapis, bez wpływu na ranking i shortlistę;
   - ocena po z góry ustalonym czasie (np. 12 miesięcy).

   To jedyne dane, których jeszcze nikt nie widział. Koszt: brak, bo bez wywołań Claude.
7. Wynik historyczny przedstawiany jako **„eksploracyjny na danych wielokrotnie używanych”**, nie jako potwierdzenie.

---

## 5. Profil NIEZNANY — wpływ na pokrycie (nie da się zmierzyć z tego środowiska)

- **Reguła (zatwierdzona):** brak kodu SIC → NIEZNANY → grupa niekompletnych lub niewiarygodnych danych. Tak samo w skanie na żywo i w backteście.
- **Czego brakuje:** liczby CIK bez SIC w 615 CIK backtestu i w 500 obecnych spółkach.
  - Logi jej nie zawierają (brak SIC jest liczony jako GENERAL).
  - Artefakty kalibracji mają tylko profil, bez surowego SIC.
  - SEC jest z tego środowiska zablokowane.
- **Skutek dla backtestu, gdy liczba będzie znana:** spółki NIEZNANY wypadają z kandydatów we wszystkich datach. Jeśli to pojedyncze przypadki, wpływ na liczebności z 4.2 będzie marginalny; jeśli więcej, trzeba to pokazać per rok przed protokołem.
- **Proponowany pomiar (bezpłatny, wymaga Twojej zgody):** diagnostyczny workflow tylko z zapytaniami do SEC. Bez FMP, bez Claude, bez liczenia zwrotów. Zapisuje:
  1. liczbę CIK bez SIC i z błędem SEC: 615 CIK backtestu i obecny skład;
  2. opcjonalnie próbkę SIC point-in-time z nagłówków (np. 20 CIK z różnych profili), żeby sprawdzić założenie z 4.1.

  **Ograniczenie GitHub:** uruchamianie ręczne działa tylko dla workflow, którego plik istnieje na `main`. Wymaga to więc dodania jednego pliku na `main` (bez sekretów poza `SEC_EDGAR_USER_AGENT`) albo innej ścieżki, którą wskażesz.

---

## 6. Kolejność (propozycja)
1. Twoje decyzje: sekcja 1.6 (kwalifikacja) i 3.6 (zwrot kapitału).
2. Zgoda (lub nie) na diagnostykę SIC z sekcji 5. Po pomiarze: decyzja, czy SIC point-in-time wchodzi do protokołu.
3. Protokół v2 według 4.4, do akceptacji (bez zamrażania przed Twoją decyzją).
4. Jedna spójna implementacja pakietu z testami regresyjnymi:
   - grupy;
   - kwalifikacja i limit;
   - NIEZNANY;
   - zwrot kapitału;
   - wyrównanie obsługi błędów SEC w backteście.

   Potem symulacja na 22.10.
5. Dopiero potem pełny skan.
