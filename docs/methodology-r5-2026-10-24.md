# Runda 5 (2026-10-24): wdrożone poprawki, symulacja kwalifikacji na 22.10, propozycja K2

Status:
- **Poprawki 6, 7, 8, 9 i 13 wdrożone w kodzie gałęzi roboczej, z testami regresyjnymi.** Pełny zestaw testów: 970 zaliczonych, 24 pominięte (przed modułem kwalifikacji). Commit `6cef41d`.
- **Moduł kwalifikacji** (`buffett_scanner/qualification.py`, decyzje 1, 3, 4, 5) gotowy i przetestowany, ale **niepodłączony do skanu na żywo**. Próg MoS czeka na decyzję.
- **K2 — tylko propozycja.** Produkcyjna punktacja dywidend bez zmian.
- Bez płatnych wywołań Claude, bez skanu, bez publikacji.

Symulacja:
- skrypt `docs/analysis/round5_2026_10_24.py`, wyniki w `round5_2026_10_24_results.txt`;
- dane zapisane ze skanu 22.10, kod produkcyjny po poprawkach;
- kody SIC z diagnostyki SEC (run 40098265387);
- założenie jak w rundach 3–4: CAPEX = 0 bez potwierdzenia u APO i COIN traktowany jako brak danych.

---

## 1. Wdrożone poprawki

| Nr | Poprawka | Skan na żywo | Backtest | Skutek na 22.10 |
|---|---|---|---|---|
| 6 | Dług netto przy EBITDA ≤ 0 nie jest niską dźwignią; gotówka netto jest. Iloraz przy EBITDA ≤ 0 = „niemiarodajny” (brak liczby zamiast ujemnej wartości). | tak | tak (wspólny scoring) | Bezpieczeństwo −2,81 pkt (z 15) dla CVNA, ECHO, F, IP, SKYD |
| 7 | Dywidendy „na akcje zwykłe” weryfikowane w SEC XBRL, gdy spółka ma ślady akcji uprzywilejowanych. Brak potwierdzenia → NIEZNANE (z przyczyną w raporcie); nie zatrzymuje skanu. | tak (nowy krok + pola FMP `preferredDividendsPaid`, `netPreferredStockIssuance`) | tak (zapasowy tag `PaymentsOfDividends`) | Na snapshocie niesprawdzalne (brak faktów SEC). Z diagnostyki: BA FY2025 → NIEZNANE; AVGO FY2021–22 → wartość SEC dla akcji zwykłych. |
| 8 | SIC 6500 nie jest REIT; kody nieruchomości 6500–6553 → GENERAL z oznaczeniem do weryfikacji | tak | tak | CBRE: GENERAL + „profil do weryfikacji” |
| 9 | Brak SIC albo błąd SEC → NIEZNANY, wykluczenie z ocenianego rankingu z przyczyną (nigdy GENERAL). Tabela `companies` zmigrowana, by przyjąć tę wartość. | tak | tak | 0 przypadków (diagnostyka: brak SIC u 0 spółek) |
| 13 | Profil sektorowy w backteście wg SIC z dnia decyzji (nagłówki 10-K); brak nagłówka sprzed daty → NIEZNANY | — | tak, domyślnie; `--sector-profiles current` odtwarza dawne wyniki | Diagnostyka: 2 z 5 834 obserwacji |

Uwagi:
- **Backtest wymaga nowego kroku** `build-sector-profile-history` (tylko SEC, ok. 30 min). Dodałam go do workflow backtestu i kalibracji na gałęzi roboczej. Bez historii backtest w trybie domyślnym odmawia startu, zamiast cicho użyć bieżącego SIC.
- **Wcześniejsze wyniki kalibracji i holdoutu policzono starą regułą.** Nowe uruchomienie da nieco inne liczby (poprawki 6, 7, 13). Żadnego backtestu nie uruchamiałam.
- **Ograniczenie, które pozostaje:** flaga prefiltra „wysoka dźwignia” (> 4) nie zadziała przy EBITDA ≤ 0. Iloraz jest teraz niemiarodajny (wcześniej był ujemny i też nie działał). Flaga nie wpływa na punktację, ale F czy CVNA nie dostaną flagi w raporcie. Do decyzji: osobna flaga „dług netto przy EBITDA ≤ 0”.

---

## 2. Rzeczywista liczba spółek kwalifikowanych do Claude (22.10)

Grupy: z DCF 117, bez DCF 39, bez metody oceny 3 (GL, ARE, WY), niekompletne dane 3 (APO, COIN, HONA).

| Status | MoS ≥ 0 (preferencja) | MoS ≥ 50 (porównanie) |
|---|---|---|
| Kwalifikacja (z DCF) | **39** | 15 |
| Kwalifikacja „jakość bez potwierdzonej ceny” (bez DCF, N1) | **6** | 6 |
| **Razem do Claude** | **45** | **21** |
| Ręczny przegląd | 16 | 16 |
| Brak kwalifikacji | 95 | 119 |
| Brak metody oceny | 3 | 3 |
| Niekompletne dane | 3 | 3 |

**MoS ≥ 0 — z DCF (39):** ADBE, ALLE, ANET, APH, APP, BKNG, CHRW, CMG, CMI, CPRT, DASH, DECK, DXCM, EME, ETN, EXE, FIX, FLEX, HII, HWM, INTU, JBHT, JBL, LDOS, LII, MU, PH, PNR, PYPL, QCOM, ROL, STX, TPL, TPR, TYL, VRT, WDC, XYL, ZTS.

**MoS ≥ 50 — z DCF (15):** ADBE, APP, BKNG, CHRW, DECK, EME, EXE, HII, INTU, JBHT, JBL, LDOS, MU, TPR, TYL.

**Bez DCF, „jakość bez potwierdzonej ceny” (6):** FSLR, GEV, LEN, NFLX, PODD, UBER.
- 5 z 6 nie ma DCF tylko dlatego, że pierwszy rok okna miał ujemny FCF (NFLX −0,13 → 9,46 mld; UBER −0,74 → 9,76 mld; GEV −2,24 → 3,71 mld; FSLR, PODD).
- LEN ma FCF ≈ 0 w ostatnim roku.
- Nie mogą być pokazywane jako potwierdzone okazje cenowe.

**Względem obecnej shortlisty (24), przy MoS ≥ 0:**
- odpadają: APO (niekompletne dane), APTV (dźwignia 2,17), CEG (ręczny przegląd), FISV (dźwignia 3,16), SNDK (zysk w 1 z 3 lat);
- dochodzi 26 spółek.

**Powody braku kwalifikacji (MoS ≥ 0, 95 spółek; jedna spółka może mieć kilka):**
- dźwignia powyżej progu: 60;
- MoS < 0: 29;
- zysk netto w mniej niż 2 z 3 lat: 10;
- ujemny FCF z 3 lat: 6;
- dług netto przy EBITDA ≤ 0 bez dodatniego OCF (ECHO): 1.

---

## 3. Spółki wymagające ręcznego przeglądu (16)

Reguła jest mechaniczna i dotyczy wyłącznie spółek, które **nie przeszły** rdzenia. Spółka nie jest kwalifikowana automatycznie ani odrzucana bez wyjaśnienia. Analizę można zlecić ręcznie.

| Typ przyczyny | Spółki | Co sprawdzić |
|---|---|---|
| EBITDA ≤ 0 przy dodatnim przepływie operacyjnym (możliwe odpisy, dźwignia niemiarodajna) | **F** (MoS 63,2%), CVNA, IP, SKYD (MoS −15,4%) | Czy EBITDA zawiera odpisy jednorazowe. Przy F: czy dług obejmuje Ford Credit. Przy CVNA: EBITDA −0,11 mld przy zysku netto +1,41 mld — dane do weryfikacji. |
| Ujemny przepływ operacyjny z 3 lat przy zyskach netto | CEG, SMCI | Klasyfikacja przepływów, kapitał obrotowy |
| FCF ujemny przez inwestycje (CAPEX > przepływ operacyjny) przy zyskach | COHR, EIX, NCLH, ORCL, PCG | Inwestycje regulowane (energetyka: EIX, PCG) czy realne ryzyko (ORCL, NCLH) |
| Usługi finansowe — dług netto/EBITDA może być nieadekwatny | ARES, HOOD, KKR, **NDAQ** (MoS 44,8%) | Konsolidowane fundusze, środki klientów |
| SIC nieruchomości (nie REIT) | CBRE | Czy profil i wskaźniki pasują |

Tylko **F i NDAQ** mają jednocześnie DCF i dodatni MoS. To one byłyby najbliżej kwalifikacji, gdyby przegląd uznał standardowy wskaźnik za nieadekwatny.

**Uwaga do zakresu reguły:** grupa „CAPEX > przepływ operacyjny” obejmuje spółki, u których ujemny FCF może być prawdziwym ryzykiem (ORCL), nie tylko błędem miary. Możesz ją zawęzić (np. tylko energetyka, SIC 4900–4999) albo zostawić do przeglądu.

---

## 4. Przewidywana liczba płatnych wywołań i koszt

Podstawa:
- **Zużycie:** 24 rzeczywiste analizy z 22.10 — wejście średnio 5 394 tokeny, wyjście średnio 8 219 (6 266–10 874), z myśleniem.
- **Cennik:** `claude-sonnet-5` (model z konfiguracji) wg dokumentacji Claude API, stan na 06.10.2026: 2 USD za mln tokenów wejścia, 10 USD za mln tokenów wyjścia.
- **Koszt jednego wywołania:** średnio 0,093 USD, maksymalnie 0,120 USD.

| Wariant | Spółki | Wywołania bez napraw | Koszt bez napraw | Najgorszy przypadek (×3) | Koszt najgorszego przypadku | Limit 75 |
|---|---|---|---|---|---|---|
| MoS ≥ 0 | 45 | 45 | ≈ 4,18 USD (do 5,38 USD przy maks. zużyciu) | 135 | ≈ 16,14 USD | **przekroczony → zatrzymanie przed Claude** |
| MoS ≥ 50 | 21 | 21 | ≈ 1,95 USD (do 2,51 USD) | 63 | ≈ 7,53 USD | mieści się |
| Ręczny przegląd (jeśli zlecisz) | 16 | 16 | ≈ 1,49 USD | 48 | ≈ 5,74 USD | osobna decyzja |

**Zastrzeżenia (to nie jest gwarantowany limit):**
- Częstość napraw po poprawce schematu nie jest zmierzona. 22.10 analizowano starszą wersją, w której 22 z 24 analiz odrzucono.
- Najgorszy przypadek liczy każdą naprawę jak pełne wywołanie. Rzeczywista naprawa jest krótsza, więc to górne oszacowanie.
- Koszt zależy od długości odpowiedzi.
- Cennik pochodzi z dokumentacji ze stanem na 06.10.2026.
- Limit 75 to dotychczasowy limit roboczy. Jego zmiana wymaga Twojej zgody (decyzja 5).

---

## 5. MoS ≥ 0 — skutki i ograniczenia obecnego DCF

**Skutki:**
- MoS ≥ 0 przyjmuje 39 spółek z DCF, MoS ≥ 50 — 15. Różnica to 24 spółki z MoS 0–50%, czyli +72 wywołania w najgorszym przypadku.
- Przy MoS ≥ 0 Q = 45 przekracza limit 75 wywołań, więc skan zatrzymałby się przed Claude. Potrzebna byłaby decyzja o limicie albo analiza w partiach.

**Ograniczenia DCF widoczne w zakwalifikowanych spółkach (39):**

| Ograniczenie | Liczba | Przykłady | Skutek dla MoS |
|---|---|---|---|
| Wzrost przycięty do sufitu 20% i stały przez 10 lat | 21 z 39 | DECK (CAGR 73%), CHRW (147%), MU (109%), APP (82%), DXCM (112%) | MoS zależy bardziej od sufitu niż od historii. Przy 20% wartość = 58,9 × FCF. |
| Baza FCF ≥ 2× średniej z wcześniejszych lat (szczyt cyklu albo jednorazowy skok) | 10 z 39 | STX 4,42×, JBHT 3,86×, VRT 3,46×, APP 3,32× | Wysoki MoS z jednego roku |
| CAGR z dwóch punktów (pierwszy i ostatni rok) | wszystkie | CHRW 147% przy bazie 1,01× | Wrażliwość na rok startowy |
| Nasycenie: MoS ≥ 50% = pełne 20 pkt | 15 z 39 | DECK 81%, INTU 81%, TPR 77% | Brak rozróżnienia między 50% a 80% |
| Skrajne wartości przy niskiej bazie | — | AKAM −3 672%, CBRE −1 373% | Liczba nie ma interpretacji ekonomicznej |

**Ocena:**
- Przy obecnym DCF **MoS ≥ 0 oznacza „model nie wskazuje przewartościowania”, a nie potwierdzoną okazję.** Systematyczne obciążenia (stały wysoki wzrost, baza w szczycie) zawyżają MoS u spółek wzrostowych i cyklicznych.
- W holdoucie 2022–2026 wycena nie poprawiła korelacji z późniejszym zwrotem (Spearman z wyceną 0,031, bez wyceny 0,135).
- MoS ≥ 0 jest spójny z rolą wstępnego filtru (Claude ocenia jakość), ale wymaga oznaczenia tych ograniczeń w raporcie.
- **Alternatywa niewymagająca nowych progów:** MoS ≥ 0 oraz osobne oznaczenie spółek z wzrostem przy suficie albo bazą ≥ 2× średniej, żeby Claude i Ty widzieli, że MoS jest niepewny. Próg 2× jest tu opisowy, nie decyzyjny.

---

## 6. Propozycja szczegółowej punktacji K2 (do Twojej akceptacji, niewdrożona)

**Cel (decyzja 10):** jakość alokacji kapitału — czy decyzje zarządu tworzą wartość na akcję — niezależnie od tego, czy spółka wypłaca, czy reinwestuje. 10 pkt, w miejsce obecnych kryteriów dywidend.

| Element | Punkty | Miara | Skąd próg |
|---|---|---|---|
| **A. Realny zwrot dla właściciela** | 0–7 | Roczne tempo zmiany (FCF − SBC) na akcję: średnia 2 ostatnich lat wobec średniej 2 lat sprzed 3 lat. Plus średnia stopa dywidendy na akcje zwykłe (potwierdzona, poprawka 7) z 3 lat. Liniowo: ≤ 0% → 0, ≥ 9% → 7. | 9% = stopa dyskontowa BASE z configu, czyli wymagana stopa zwrotu tego samego modelu. Nie jest dopasowana do danych. |
| **B. Dyscyplina liczby akcji** | 0–2 | Liczba akcji rozwodnionych w oknie 3 lat (bez lat z oznaczoną emisją przy przejęciu): nie wzrosła → 2, wzrosła → 0 | Definicyjny (brak rozwodnienia) |
| **C. Alokacja bez pogorszenia bilansu** | 0–1 | Dźwignia na końcu okna ≤ próg bezpieczeństwa (2,0) albo gotówka netto, albo dźwignia nie wzrosła w oknie → 1; inaczej 0 | Ten sam próg co w rdzeniu wypłacalności |

**Zasady dla niepełnych danych (decyzja 11):**
- A niepoliczalne (ujemny lub zerowy start, brak danych) → 3,5 pkt (połowa, neutralnie) + oznaczenie „do oceny jakościowej”.
- Rok z oznaczoną emisją przy przejęciu bez danych do rozdzielenia → B = 1 (neutralnie) + oznaczenie.
- Oznaczenie przejęcia (propozycja do decyzji): w danym roku liczba akcji wzrosła o więcej niż 5% i w tym samym roku są przejęcia (FMP `acquisitionsNet` ≠ 0 albo SEC `StockIssuedDuringPeriodValueAcquisitions` > 0). **5% to wartość robocza, bez uzasadnienia z danych.** Mogę policzyć rozkład rocznych zmian liczby akcji i pokazać, ile przypadków oznacza każdy próg.

**Ciągłość dywidendy (decyzja 12):**
- Liczona na zadeklarowanym DPS dla akcji zwykłych (SEC `CommonStockDividendsPerShareDeclared`, w skanie endpoint dywidend FMP).
- Proponuję **oznaczenie i przekazanie do analizy Claude, bez punktów.**
- Powód: kara za cięcie dla płacących jest matematycznie tym samym co punkt dla niepłacących „za brak cięcia” — czyli tym, czego nie chcesz. Jeśli wolisz punkty, alternatywa to −1 w C dla płacących, którzy obcięli DPS, ze świadomością tej asymetrii.

**Ilustracja na 22.10** (przybliżona: snapshot nie ma SBC ani danych o przejęciach, więc A liczone z FCF bez SBC, a B bez wyłączenia przejęć):

| Spółka | Dziś | Wzrost FCF/akcję %/r | Dyw. % | A | Liczba akcji 3 l. | B | C | **K2** |
|---|---|---|---|---|---|---|---|---|
| MRK | 10 | 7,9 | 2,10 | 7,0 | −1,4% | 2 | 1 | **10** |
| QCOM | 10 | 16,6 | 1,89 | 7,0 | −2,8% | 2 | 1 | **10** |
| ADBE | 10 | 10,5 | 0 | 7,0 | −9,3% | 2 | 1 | **10** |
| CHTR | 10 | **−13,1** | 0 | 0 | −16,2% | 2 | 1 | **3** |
| AVGO | 8 | 11,3 | 0,63 | 7,0 | +14,7% (VMware) | 0* | 1 | **8** (*z oznaczeniem przejęcia: 9) |
| BSX | 5 | 39,6 | 0 | 7,0 | +3,8% | 0 | 1 | **8** |
| TYL | 5 | 23,0 | 0 | 7,0 | +3,3% | 0 | 1 | **8** |
| DDOG | 5 | 38,1 | 0 | 7,0 | +15,2% | 0 | 1 | **8** |
| AXON | 5 | 11,2 | 0 | 7,0 | +37,9% | 0 | 0 | **7** |
| UBER, MU, FSLR, RDDT | 4–10 | — (ujemny start) | — | 3,5 | — | 0 | 1 | **4,5** |

Skutki zbiorcze (156 spółek operacyjnych):
- Spółki bez wypłat w 3 latach (n = 7): mediana punktów 5 → 7.
- Płacące dywidendę co roku (n = 93): 10 → 8.
- K2 nie karze reinwestycji, a karze spadek wartości na akcję mimo wypłat (CHTR).

**Ryzyka K2 (do decyzji przed wdrożeniem):**
1. **Nasycenie:** 49 ze 156 spółek ma 10/10. Próg 9% jest uzasadniony, ale słabo różnicuje przy szybkim wzroście FCF w latach 2021–2025.
2. **33 spółki (21%) z A niepoliczalnym** (neutralne 3,5) — głównie zwroty od strat.
3. **Krótkie okno** (5 lat danych FMP) i zależność od lat startowych.
4. **Częściowe podwójne liczenie z DCF** (oba korzystają ze wzrostu FCF). DCF liczy całkowity FCF, K2 — FCF na akcję po SBC.
5. **Kalibracja na 2012–2021** byłaby kolejnym spojrzeniem na wielokrotnie używane dane. Proponuję liczyć K2 „w cieniu” w przyszłych skanach.

---

## 7. Protokół v2 — bootstrap (decyzja 14, bez zamrażania)
- **Metryka:** Spearman liczony w każdej dacie decyzji, średnia po datach.
- **Bootstrap dwuwymiarowy:**
  1. losowanie bloków kolejnych miesięcy decyzji (blok ≥ 6 miesięcy, bo 6-miesięczne zwroty się nakładają);
  2. w każdym losowaniu losowanie spółek ze zwracaniem — spółka wchodzi ze wszystkimi swoimi obserwacjami z wylosowanych miesięcy.

  Uwzględnia to powtarzanie tych samych spółek (127 spółek w 1 111 obserwacjach) i zależność w czasie.
- **Wrażliwość:** bloki 9 i 12 miesięcy; 2 000 losowań; korekta Holma na 3 porównania.
- **Okresy:**
  - 2016–2021 opisywane wyłącznie jako dane wcześniej używane (rundy 1–3);
  - podział 2016–2018 / 2019–2021 nie jest walidacją niezależną;
  - jedyna niezależna walidacja: przyszłe skany „w cieniu”.
- **Przed testem:** nowy backtest z SIC point-in-time i poprawkami 6–7, inaczej porównanie wariantów odbyłoby się na starej klasyfikacji.

---

## 8. Ryzyka metodologiczne, które nadal pozostają
1. **DCF:** stały wzrost do 20% przez 10 lat, CAGR z dwóch punktów i baza z jednego roku zawyżają MoS u spółek wzrostowych i cyklicznych (sekcja 5). Protokół wyceny nie został jeszcze wykonany.
2. **Historia nie potwierdza** skuteczności rdzenia wypłacalności ani bramki MoS jako filtrów. Runda 1: bramka bezpieczeństwa 7,5 dała remis. Holdout: wycena nie poprawiła korelacji.
3. **Próg dźwigni 2,0** odcina spółki tuż powyżej (APTV 2,17, CAT 2,25, UNP 2,36). Miara nie pasuje do spółek z ramieniem finansowym i do części usług finansowych (ręczny przegląd częściowo to łagodzi).
4. **Dane FMP:** EBITDA z odpisami (F), niespójności (CVNA), dywidendy uprzywilejowane jako zwykłe. Poprawka 7 działa tylko tam, gdzie są ślady akcji uprzywilejowanych.
5. **Koszt jest niepewny:** częstość napraw nieznana po poprawce schematu; MoS ≥ 0 przekracza limit 75.
6. **Profile finansowe** (BANK, INSURER, REIT, usługi finansowe) nadal bez metody oceny.
7. **Moduł kwalifikacji nie jest podłączony do skanu.** Do pełnego skanu potrzebna jest jeszcze jedna implementacja: grupy, kwalifikacja, limit, raport. Obecny skan nadal wybiera TOP 20 + remisy.
8. **Backtest i kalibracja** po poprawkach dadzą inne liczby niż dotychczasowe. Wcześniejszych wniosków nie należy traktować jako potwierdzonych na nowym kodzie.
9. **Uniwersum backtestu** obejmuje ok. 77% historycznego składu S&P 500 (ograniczenie znane z Fazy 5.3).

---

## 9. Decyzje potrzebne
1. Próg MoS w kwalifikacji: ≥ 0 (45 spółek, przekracza limit 75) czy ≥ 50 (21 spółek). Przy ≥ 0: podniesienie limitu albo partie, plus oznaczenie niepewnego MoS (sekcja 5).
2. Zakres ręcznego przeglądu: zostawić grupę „CAPEX > przepływ operacyjny” w całości czy zawęzić.
3. K2: akceptacja struktury A/B/C (7/2/1), progu 9%, neutralnych 3,5 i 1, oraz ciągłości dywidendy jako oznaczenia bez punktów.
4. Próg oznaczenia przejęć (robocze 5%) — mogę najpierw policzyć rozkład.
5. Flaga prefiltra „dług netto przy EBITDA ≤ 0” (sekcja 1).
6. Zgoda na podłączenie kwalifikacji do skanu (jedna implementacja z testami). Potem osobna zgoda na skan i płatne analizy.
