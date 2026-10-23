# Propozycje do decyzji — runda 2 (2026-10-23)

Status: **wyłącznie analizy, formuły i symulacje. Nic nie zostało wdrożone; produkcyjna metodologia bez zmian.** Docelowo jeden kontrolowany pakiet zmian po akceptacji.

Symulacje:
- `docs/analysis/selection_rules_2026_10_23.py` (dane skanu 22.10, kod scoringu po poprawkach z `d36e7a6`).
- Przyjęte założenia:
  - profile SIC: GL = INSURER, ARE i WY = REIT (źródła wtórne), reszta GENERAL;
  - CAPEX = 0 bez potwierdzenia w SEC u APO i COIN → brak danych (scenariusz ostrożny).

> **Ostrzeżenie o stanie kodu.** Gałąź robocza zawiera poprawki 1–4. Bez pozostałych elementów pakietu (dwie listy, grupa niekompletnych danych) skan na tym kodzie dałby efekt GL z pozycji 81 na 1 i zatrzymywałby się na spółce z podejrzanym CAPEX na shortliście. **Tego kodu nie należy używać do pełnego skanu przed wdrożeniem całego pakietu.**

---

## 1. Wybór kandydatów do Claude z dwóch list (P-N1) — bez kwot

### 1.1 Skład grup na 22.10

| Grupa | Liczba | Kto |
|---|---|---|
| Z DCF | 117 | spółki z policzalną wyceną |
| Bez DCF (reguła wyceny) | 42 | dane kompletne, DCF wyłącza reguła (np. ujemny FCF na początku lub końcu okna) lub profil BANK/INSURER/REIT (GL, ARE, WY) |
| Niekompletne lub niewiarygodne dane | 3 | APO, COIN (CAPEX = 0 bez potwierdzenia), HONA (brak dywidend za poprzedni rok i OCF za pierwszy) |

### 1.2 Problem w liście „bez DCF”

**Spółki finansowe są tam oceniane kryteriami bezpieczeństwa dla spółek operacyjnych.**
- GL (ubezpieczyciel) ma 15/15, w tym „płynność bieżąca ≥ 1,5” i „dług netto/EBITDA ≤ 2”. Dla ubezpieczyciela te miary nie mają sensu ekonomicznego.
- ARE: 7,5/15. WY: 4,7/15.

Lista „bez DCF” nie jest więc wewnętrznie porównywalna, dopóki zawiera profile, dla których model nie ma ani metody wyceny, ani właściwych kryteriów bezpieczeństwa.

**Propozycja do decyzji: trzecia lista „profil bez metody oceny” (BANK/INSURER/REIT).**
- Spółki widoczne w raporcie, bez porównywania z innymi listami.
- Do Claude dopiero po zaprojektowaniu metody dla tych profili, albo według zasady z 1.3 z jawnym oznaczeniem.

Na 22.10 dotyczy to GL, ARE i WY.

### 1.3 Zasady wyboru (bez kwot ustalanych ręcznie)

Wspólny element wszystkich zasad: budżet analiz Claude N (dziś 20). To parametr kosztowy, nie inwestycyjny; o podziale między listy decyduje reguła, nie N.

| Zasada | Definicja | Wynik 22.10 | Ocena |
|---|---|---|---|
| **S1 — ta sama selektywność** | Każda lista oddaje ten sam odsetek swoich spółek: N / (liczba spółek w obu listach). Przydział metodą największych reszt; remis na granicy w obrębie listy zachowany. | 12,6% każdej listy → 15 z DCF (+4 remis = 19) i 5 bez DCF: GL, PODD, CEG, NFLX, UBER. Względem produkcji: −APO, +GL | Neutralna: prawdopodobieństwo wyboru nie zależy od tego, czy spółka ma DCF. Podział wynika z liczebności list, nie z decyzji. Remisy zwiększają liczbę analiz. |
| **S2 — percentyl we własnej liście** | Pozycja spółki = odsetek spółek jej listy z wynikiem nie wyższym; wspólny próg percentylowy dla obu list; remisy zachowane. | 20: 14 z DCF + 6 bez DCF (GL, PODD, CEG, NFLX, UBER, ARES). Względem produkcji: −APO, APTV, EME, FISV, HII, JBL; +ARES, GL | Także neutralna. Lepiej obsługuje różne rozkłady wyników w listach, ale przy małej liście bez DCF percentyle są „grube” (skoki co 1/42). |
| **S3 — wspólna bramka na porównywalnych komponentach** | Kolejność wszystkich według bezpieczeństwa + dywidend (25 pkt, ta sama baza); wycena tylko porządkuje w liście z DCF | 27 (masowe remisy); bez DCF tylko GL i PODD; wypada 16 spółek | Porównywalna baza, ale wycena traci wpływ na wybór, a remisy decydują o liczbie analiz. Nie rekomenduję. |

**Rekomendacja techniczna: S1.**
- Najprostsza zasada, która nie premiuje i nie karze spółek bez DCF.
- Nie wymaga żadnej proporcji ustalanej ręcznie.
- Wewnątrz każdej listy porównywane są wyniki z tej samej bazy (45 albo 25 pkt).

**Do decyzji:**
- czy remisy na granicy mają zwiększać liczbę analiz (dziś tak), czy budżet N jest twardy (wtedy potrzebna reguła rozstrzygania remisu, np. losowanie z zapisanym ziarnem — nie alfabet);
- czy lista „profil bez metody” (1.2) uczestniczy w S1.

### 1.4 Grupa „niekompletne lub niewiarygodne dane” (decyzja nr 3)

**Kryteria przynależności:**
- spółka GENERAL z brakiem danych wejściowych, w tym CAPEX podejrzany → brak;
- brak DCF z powodu braku danych (`BRAK_DANYCH`);
- brak klasyfikacji sektorowej (błąd SEC albo brak kodu SIC, patrz punkt 5).

**Traktowanie:**
- bez wyceny pokazywanej jako wiarygodna;
- bez analizy Claude;
- pełna lista z przyczynami w raporcie;
- **nie zatrzymuje skanu** (zastąpi obecną regułę „spółka z luką na shortliście = stop”).

**Brak CAPEX nie przenosi do tej grupy spółek, dla których standardowy DCF nie ma zastosowania** (BANK/INSURER/REIT). Ich wymagane dane wejściowe nie obejmują CAPEX.

**Bramki globalne (bez zmian w zasadzie):**
- pokrycie cen ≥ 98%;
- braki danych finansowych ≤ 5%;
- brak klasyfikacji ≤ 5%.

Proponowana nowa bramka: grupa niekompletnych danych ≤ 5% rankingu, inaczej skan stop. Na 22.10: 3/162 = 1,9%.

---

## 2. Dywidendy i buyback — dokładne formuły (bez wyboru wariantu)

### 2.1 Źródła i definicje wspólne

| Symbol | Znaczenie | FMP (skan na żywo) | SEC XBRL (backtest) |
|---|---|---|---|
| D_t | dywidendy wypłacone na akcje zwykłe w roku t (wartość dodatnia) | `commonDividendsPaid` (abs) | `PaymentsOfDividendsCommonStock` / `PaymentsOfDividends` |
| B_t | skup akcji brutto (dodatni) | `commonStockRepurchased` (abs) | `PaymentsForRepurchaseOfCommonStock` |
| I_t | emisja akcji (dodatnia) | **dziś niepobierana**; kandydat `commonStockIssued`, do potwierdzenia na surowym JSON jak przy `dividends_paid` w Fazie 4 | `ProceedsFromIssuanceOfCommonStock` (niepobierany) |
| S_t | średnia ważona liczba akcji rozwodnionych | `weightedAverageShsOutDil` | `WeightedAverageNumberOfDilutedSharesOutstanding` |
| FCF_t | OCF − CAPEX | `operatingCashFlow` − abs(`capitalExpenditure`) | jak w backteście |
| ND_t | dług netto = dług − gotówka | `totalDebt` − `cashAndCashEquivalents` | kompozyt `total_debt` (Faza 5.3f) |
| M | kapitalizacja = cena × S_t | — | — |

Wskaźniki pochodne:
- DPS_t = D_t / S_t;
- spółka płacąca: D_t > 0;
- buyback netto NB_t = B_t − I_t (wymaga I_t);
- zmiana liczby akcji ΔS = S_t − S_{t−1} (łapie łącznie emisje, opcje i SBC, ale z opóźnieniem średniej ważonej);
- łączny yield SY = (D_t + B_t) / M (dziś brutto); netto NSY = (D_t + NB_t) / M.

### 2.2 Obecna reguła (dla porównania)
SY > 0 → 3 pkt; DPS_t ≥ DPS_{t−1} → 3; D_t / FCF_t ≤ 75% przy FCF > 0 → 2; ΔS ≤ 0 → 2. Maksimum 10.

Spółka bez dywidendy: DPS 0 ≥ 0 → 3 i payout 0% → 2 przyznawane automatycznie.

### 2.3 Warianty (progi = obecne z configu, chyba że zaznaczono)

**P-D1 — równoległe kryteria.**
- Płacący (D_t > 0): bez zmian: SY > 0 (3), DPS_t ≥ DPS_{t−1} (3), D_t/FCF_t ≤ 75% (2), ΔS ≤ 0 (2).
- Niepłacący (D_t = 0):
  - SY > 0, czyli B_t > 0 (3);
  - **ciągłość:** B_t > 0 i B_{t−1} > 0 (3, nowy próg: 2 lata);
  - **pokrycie:** B_t ≤ FCF_t przy FCF > 0 (2, nowy próg: 100% FCF);
  - ΔS ≤ 0 (2).
- Max 10 dla obu grup.

**P-D2 — dwa podkomponenty po 5.**
- Dywidenda: [D_t > 0 i DPS_t ≥ DPS_{t−1}] (3) + [D_t > 0 i D_t/FCF_t ≤ 75%] (2).
- Buyback: B_t > 0 (3) + ΔS ≤ 0 (2).
- Niepłacący max 5; płacący bez buybacku max 7.

**P-D3 — całkowity zwrot.**
- SY > 0 (4);
- (D_t + B_t) ≤ FCF_t przy FCF > 0 (4);
- ΔS ≤ 0 (2).
- Bez kryterium cięcia dywidendy. Wagi 4/4/2 są nowe, do decyzji.

### 2.4 Kwestie przekrojowe

Te modyfikatory można dołączyć do każdego wariantu.

| Kwestia | Dziś | Propozycja | Dane 22.10 |
|---|---|---|---|
| **Spółki bez dywidendy** | 5 pkt automatycznie | P-D1: równoważne kryteria buybacku; P-D2: max 5; P-D3: wspólne kryteria | 54 z 162 bez dywidendy; dziś 30 z nich ma 10/10 |
| **Buyback netto i emisje** | B_t brutto; emisje łapie tylko ΔS | M1: SY i pokrycie liczone z NB_t = B_t − I_t; wymaga pobrania I_t (nowe pole) | 28 spółek ma B_t > 0 i rosnącą liczbę akcji (np. APO, ARES, AVGO, BX, COIN) |
| **Buyback finansowany długiem** | Niewykrywany (tylko payout dywidendy vs FCF) | M2: kryterium pokrycia = 0, jeśli D_t + NB_t > FCF_t **i** ND_t > ND_{t−1}; M3: pokrycie z sum 3-letnich (wygładza pojedynczy rok) | 55 ze 148 zwracających kapitał zwraca więcej niż FCF; u 47 z nich dług netto wzrósł (np. ADBE, AMAT, BA, CAT, CHTR) |
| **Brakujące dane** | Brak → kryterium niespełnione (0), bez śladu | M4: brak wejścia → kryterium „nieznane” (0 pkt) + oznaczenie; brak D_t, B_t lub S_t → spółka do grupy niekompletnych danych | Na 22.10: 0 braków D_t, B_t, S_t w najnowszym okresie (zastrzeżenie: FMP może raportować brak jako 0) |
| **Reinwestujący bez zwrotu kapitału** | Dostają 5–7 pkt (automatyczne punkty dywidendowe) | We wszystkich trzech wariantach: 0–2 pkt (tylko ΔS ≤ 0). Komponent z definicji mierzy **zwrot** kapitału, nie jakość reinwestycji. Opcje: (a) akceptacja, bo reinwestycję ma oceniać jakość biznesu (Claude); (b) nowe kryterium jakości reinwestycji, np. „test jednego dolara” Buffetta (przyrost kapitalizacji ≥ zatrzymane zyski w 5 latach) albo ROIC; wymaga nowych danych (5-letnie ceny, kapitał zainwestowany) | 14 z 54 spółek bez dywidendy nie robi też buybacku |

**Uwaga metodologiczna.** Wariant nie powinien być wybierany według tego, jak mało zmienia shortlistę. Kryteria wyboru do zatwierdzenia:
- spójność z intencją komponentu („zwrot dla akcjonariuszy” vs „dyscyplina alokacji kapitału”);
- jednakowe maksimum dla porównywalnych spółek;
- odporność na buyback długiem i emisje;
- dostępność danych w obu źródłach (FMP i SEC), żeby backtest i skan liczyły to samo.

---

## 3. Podejrzany CAPEX (decyzja: osobna grupa) — założenia do pakietu

Szczegóły w 1.4:
- grupa „niekompletne lub niewiarygodne dane”;
- bez Claude i bez wiarygodnej wyceny;
- skan nie zatrzymuje się z powodu pojedynczej spółki;
- bramki globalne zostają;
- profile BANK/INSURER/REIT nie wymagają CAPEX.

---

## 4. Protokół 2012–2021 — wyjaśnienia przed zamrożeniem

**Dlaczego „4 z 6 lat”.**
- Okno 2012–2021 działa w schemacie rozszerzającym się (jak kalibracja Fazy 5.4, `docs/buffett-scanner-design-review.md` l. 1454–1456). Lata 2012–2015 służą wyłącznie jako historia i rozgrzewka (CAGR, okno spadków); lata testowe to 2016–2021, czyli 6 foldów.
- Słabość kryterium: jeśli wariant nie różni się od V0, a lata są niezależne, P(≥ 4 z 6) = 22/64 ≈ 34%. Kryterium samo w sobie jest słabe.
- **Proponuję:** licznik lat tylko opisowo (albo ≥ 5 z 6, P ≈ 11%), a o rekomendacji decyduje test z bootstrapu (niżej).

**Które lata mają odpowiednie dane.**
- Pokrycie uniwersum: 82–86% w 2012–2013 i 96–99% od 2019.
- Wycena DCF dostępna tylko dla ok. 18,5% kandydatów; obecnie zdeterminowane pokryciem `total_debt` (38%).
- Pełna populacja OOS w latach 2016–2021: 879 / 481 / 741 / 1 042 / 2 113 / 578; razem 5 834.
- Podzbioru z wyceną per rok dokumentacja nie podaje (łącznie 1 111, więc szacunkowo ok. 90–400 na rok).
- **Propozycja:** przed jakimkolwiek spojrzeniem na stopy zwrotu policzyć tylko liczebności per rok (wspólna populacja wszystkich wariantów). Lata z n < 100 wyłączyć z licznika lat. Liczebności nie zdradzają wyników, więc to nie jest dopasowanie do danych.

**Zależność obserwacji i 12 porównań.**
- Metryka liczona jako Spearman **w każdej dacie osobno** (jedna liczba na datę, co usuwa problem wielu spółek z tego samego dnia w jednej korelacji), potem średnia.
- Zależność w czasie (6-miesięczne zwroty z miesięcznych dat nakładają się na 5 kolejnych dat): bootstrap blokowy dat z blokiem ≥ 6 miesięcy; dodatkowo raport wrażliwości dla bloków 9 i 12 miesięcy.
- 12 porównań z V0: korekta Holma–Bonferroniego, rodzinny poziom błędu 5%.
- Moc testu będzie niska. „Brak istotnej różnicy” nie dowodzi, że warianty są równoważne.

**Wybór najlepszego wariantu ≠ walidacja.**
- Wybór najlepszego z 12 na tych samych danych daje optymistycznie zawyżony wynik („klątwa zwycięzcy”).
- Rozdzielenie, ustalone przed testem:
  1. **Wybór** na latach 2016–2018 (3 foldy).
  2. **Potwierdzenie** jednorazowe na 2019–2021, wyłącznie dla zwycięzcy i V0. Kryterium potwierdzenia ustalone z góry: różnica dodatnia i przedział ufności nie obejmujący zera.
  3. **Walidacja niezależna** tylko prospektywnie: śledzenie skanów z zamrożoną konfiguracją przez z góry określony czas (np. 12 miesięcy), przed ostateczną decyzją.
- **Uczciwe zastrzeżenia:**
  - Round 3 (Faza 5.4d) już oglądała na 2012–2021 wyniki diagnostyczne dla sufitu 15% i 25% (Spearman 0,126 vs 0,113), więc wariant G1 nie jest „ślepy”.
  - Definicje wariantów powstały po obejrzeniu wrażliwości na 22.10 i wyników holdoutu.
  - Lata 2019–2021 to ta sama epoka rynkowa co 2016–2018.
  - Backtest klasyfikuje sektory **dzisiejszym** kodem SIC dla wszystkich dat (np. WY: dawniej SIC 2400, dziś 6798), czyli klasyfikacja nie jest point-in-time.

---

## 5. Klasyfikacja sektorowa — brak kodu SIC i normalizacja

**Brak SIC ≠ GENERAL.**
- Backtest przyjmuje GENERAL dla braku kodu (`sector_classification.py`: „brak kodu → GENERAL”). Zgadzam się z Twoim zastrzeżeniem: brak klasyfikacji nie jest dowodem profilu GENERAL, tylko domyślnym założeniem.
- **Propozycja:** profil `NIEZNANY` → grupa niekompletnych lub niewiarygodnych danych (bez wyceny i bez Claude, w raporcie). Sektor z FMP pokazywany pomocniczo, bez wpływu na klasyfikację.
- Dla spójności ta sama reguła w backteście. Liczbę takich CIK trzeba zmierzyć w SEC. Z tego środowiska SEC jest niedostępne; dla S&P 500 spodziewam się pojedynczych przypadków, ale tego nie zweryfikowałam.

**Normalizacja.**
- Poprawka sektorowa wejdzie dopiero razem z P-N1 + S1 (listy porównywalne wewnętrznie) i listą „profil bez metody oceny” (1.2).
- Wtedy GL nie przechodzi z pozycji 81 na 1: nie konkuruje z wynikami liczonymi z 45 pkt ani ze spółkami operacyjnymi.

---

## 6. Proponowany pakiet do wdrożenia (po akceptacji, jako całość)
1. Poprawki 1–4 (już w kodzie) + brak SIC → `NIEZNANY`.
2. Trzy listy i grupa danych:
   - z DCF;
   - bez DCF (reguła wyceny);
   - profil bez metody oceny;
   - niekompletne lub niewiarygodne dane.
3. Wybór do Claude według wybranej zasady (rekomendacja S1) + decyzja o remisach.
4. Komponent dywidend według wybranego wariantu i modyfikatorów M1–M4.
5. Testy regresyjne + symulacja na 22.10 przed użyciem w skanie.
6. Protokół 2012–2021 w wersji z punktu 4, zamrożony osobno (test wyceny niezależny od pakietu 1–5).
