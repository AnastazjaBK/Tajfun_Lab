# Runda 4 (2026-10-24): diagnostyka SIC, liczebności, kwalifikacja do Claude, alokacja kapitału

Status: **analizy i propozycje. Produkcyjna metodologia i punktacja bez zmian. Bez wywołań Claude, bez skanu, bez publikacji.**

Źródła:
- Diagnostyka: workflow `diag-sic-sample-sizes.yml`, run [40098265387](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/40098265387), commit `668d3e7` gałęzi roboczej (potwierdzony w logu).
  - SEC: 7 856 zapytań, tempo poniżej limitu.
  - FMP w ramach abonamentu: aktualny skład indeksu i 162 zapytania o cash flow.
  - Odczyt artefaktu kalibracji Round 1 i snapshotu 22.10 (SHA256 zgodny).
  - Log: `docs/analysis/diag_2026_10_24/run_40098265387_log.txt`. Kody SIC spółek z 22.10: `sic_ranked_22_10.csv`.
- Analiza 22.10: `docs/analysis/round4_2026_10_24.py`, wynik w `round4_2026_10_24_results.txt` (profile z SEC).

Trzy zbiory spółek są raportowane osobno i nie zastępują się nawzajem:
- **uniwersum backtestu:** 615 CIK, historyczny skład 2012+;
- **uniwersum skanu 22.10:** 500 spółek ze snapshotu;
- **aktualny skład indeksu z FMP** (24.10): 503 notowania = 500 CIK.

---

## 1. SIC i wpływ na pokrycie danych

### 1.1 Brakujące SIC i profil NIEZNANY

| Zbiór | n | GENERAL | BANK | INSURER | REIT | Brak SIC | Błąd SEC |
|---|---|---|---|---|---|---|---|
| Uniwersum backtestu | 615 | 527 | 20 | 35 | 33 | **0** | 0 |
| Uniwersum skanu 22.10 | 500 | 425 | 17 | 29 | 28 | **0** | 1 |
| Aktualny skład (FMP) | 500 | 425 | 17 | 29 | 28 | **0** | 1 |
| Rankowane 22.10 | 162 | 158 | 0 | 1 (GL) | 3 (ARE, CBRE, WY) | 0 | 0 |

- **Profil NIEZNANY nie zmienia pokrycia historycznego: 0 spółek bez SIC, 0 obserwacji dotkniętych.** Reguła ma znaczenie wyłącznie jako zabezpieczenie na przyszłość.
- **Błąd SEC: jeden przypadek, Vylor Inc. (VYLR, CIK 2012866).** SEC zwraca 404 dla tego CIK. Spółka jest w obu zbiorach bieżących, nie było jej na liście rankowanej 22.10. Przyczyny nie ustaliłam (możliwy nowy CIK albo błędny CIK u dostawcy). Według reguły z poprawki 1 spółka trafiłaby do wykluczonych z przyczyną, nigdy do GENERAL.
- **Aktualny skład FMP jest identyczny** (te same 500 CIK) z uniwersum skanu 22.10. Na dziś oba zbiory się pokrywają, ale nadal raportuję je osobno.
- **CBRE ma SIC 6500 („Real Estate”), więc reguła klasyfikuje ją jako REIT.** CBRE to firma usług nieruchomościowych, nie REIT. Kod 6500 w regule jest za szeroki (do decyzji, punkt 6). Na 22.10 bez skutku: CBRE nie przechodzi kryteriów (dług netto/EBITDA 3,19).

### 1.2 Historyczne zmiany SIC i wiarygodność point-in-time
- **6 476 nagłówków 10-K (2011–2021 + najnowszy), wszystkie odczytane.**
- **Wiarygodność.** Najnowszy nagłówek jest zgodny z bieżącym SIC u 610/610 spółek. Jednocześnie 33 spółki mają w starszych nagłówkach inny kod. Wniosek: nagłówki zachowują stan z dnia złożenia i nie są aktualizowane wstecz.
- **Zmiany profilu: 5 spółek, wszystkie przejścia do REIT:**
  - AMT (nagłówek 2012);
  - CCI (2015);
  - EQIX (2016);
  - IRM (2016);
  - SBAC (2017).
- **Opóźnienie SIC wobec zmiany biznesu.** Według mojej wiedzy (niezweryfikowanej w diagnostyce) część z tych spółek przeszła na status REIT rok–dwa wcześniej, niż pokazuje SIC. Point-in-time usuwa wiedzę z przyszłości, ale nie usuwa opóźnienia klasyfikacji.
- **38 CIK backtestu nie ma żadnego 10-K w latach 2011–2021** (późniejsze debiuty, zgłoszenia pod innymi formularzami).

### 1.3 Wpływ na populację kalibracji (OOS 2016–2021)

| | Pełna próba (5 834 obs.) | Podzbiór z wyceną (1 111 obs.) |
|---|---|---|
| Profil NIEZNANY | 0 | 0 |
| Profil point-in-time inny niż bieżący | 2 obs. / 1 spółka (2016, REIT → GENERAL) | 0 |
| Brak nagłówka sprzed daty decyzji | 2 obs. (2019, 2020) | 0 |

**Wniosek:**
- Klasyfikacja bieżącym SIC zmieniła profil 2 z 5 834 obserwacji, a podzbioru z wyceną nie dotknęła wcale.
- Dla protokołu wyceny (porównanie wariantów na podzbiorze z wyceną) klasyfikacja point-in-time **nie zmienia populacji**.
- Wdrożenie jej w backteście jest tanie, ale na dotychczasowe wyniki praktycznie nie wpływa (decyzja: punkt 6).

---

## 2. Rzeczywiste liczebności 2016–2021

Liczebności obserwacji odtworzone z artefaktu kalibracji są **dokładnie zgodne z dokumentacją** w każdym roku i w obu próbach.

| Rok | Pełna próba: obserwacje | Pełna próba: unikalne spółki | Z wyceną: obserwacje | Z wyceną: unikalne spółki |
|---|---|---|---|---|
| 2016 | 879 | 231 | 177 | 56 |
| 2017 | 481 | 184 | 108 | 39 |
| 2018 | 741 | 255 | 138 | 53 |
| 2019 | 1 042 | 281 | 229 | 64 |
| 2020 | 2 113 | 423 | 365 | 95 |
| 2021 | 578 | 262 | 94 | 49 |
| **Razem** | **5 834** | **474** | **1 111** | **127** |

Wnioski dla protokołu:
- **Podzbiór z wyceną to 127 spółek w 6 lat, 39–95 spółek rocznie.** Średnio każda spółka występuje ok. 8,7 razy (1 111 / 127). Efektywna liczba niezależnych obserwacji jest bliżej setki niż tysiąca.
- **Przy minimalnej mocy testu** porównanie 3 wariantów wyceny z V0 da najpewniej wynik „brak istotnej różnicy”. Taki wynik nie dowodzi równoważności wariantów.
- Bootstrap powinien losować bloki w czasie **i** uwzględniać powtarzanie tych samych spółek (np. bootstrap po spółkach albo dwuwymiarowy). To element do protokołu v2.

---

## 3. Kwalifikacja do Claude — propozycja kryteriów

### 3.1 Ograniczenia trzech warunków (dane 22.10)

| Warunek | Problem | Przykłady |
|---|---|---|
| FCF > 0 | Tylko ostatni rok (pole `fcf_ttm` to w praktyce ostatni rok obrotowy). Jeden rok kapitału obrotowego lub inwestycji decyduje o wyniku. | Odpadają mimo dodatniego FCF z 3 lat: DOW, FDXF, IP, MOS. Przechodzą mimo ujemnego FCF z 3 lat: ALB, BE, CEG. |
| Dług netto / EBITDA ≤ 2 | **Błąd logiczny:** przy EBITDA ≤ 0 iloraz jest ujemny i warunek jest zaliczany. Błąd jest też w produkcyjnym wyniku bezpieczeństwa (+3 pkt). | 7 spółek, m.in. F (dług netto 144 mld USD, EBITDA −4,6 mld), CVNA, ECHO, IP, SKYD |
| | Twardy próg 2,0 | 28 spółek w przedziale (2; 3], m.in. LMT 2,01, BSX 2,03, APTV 2,17, CAT 2,25, UNP 2,36 |
| | Miara nie pasuje do spółek z ramieniem finansowym (dług finansujący klientów) | F (Ford Credit), CAT (Cat Financial) |
| Brak trwałych strat | Zaliczony, gdy choć 1 z 3 lat jest zyskowny | 21 spółek ze stratą w 1–2 z 3 lat, m.in. INTC (+1,7 / −18,8 / −0,3 mld), BA |
| Wszystkie (dane FMP) | EBITDA z FMP zawiera odpisy. CVNA: EBITDA −0,11 mld przy zysku netto +1,41 mld — dane do weryfikacji. | F, CVNA, ECHO |

### 3.2 Proponowany rdzeń wypłacalności (K-B)

Progi nie są kalibrowane. Każdy ma uzasadnienie spójnością z istniejącą konfiguracją.

| Warunek | Reguła | Uzasadnienie |
|---|---|---|
| Przepływy | Suma FCF z 3 lat > 0 | To samo okno 3 lat co `persistent_losses_lookback_years: 3` w configu |
| Dźwignia | Gotówka netto → spełnia. Dług netto > 0 wymaga EBITDA > 0 i dług netto/EBITDA ≤ 2,0 | Usuwa błąd znaku. Próg 2,0 bez zmian z configu (efekt progu opisany wyżej). |
| Zyskowność | Zysk netto > 0 w co najmniej 2 z 3 lat | Większość lat zamiast „nie wszystkie stratne” |

Wycena (K-W, tylko grupa z DCF): **MoS BASE ≥ 0.** To próg wynikający z definicji („cena poniżej wartości BASE”). Stopień atrakcyjności porządkuje wynik, nie bramka. Alternatywa: MoS ≥ 50%, czyli dzisiejsza granica pełnych punktów za wycenę.

### 3.3 Porównanie reguł na 22.10 (profile z SEC)

Grupy: z DCF 116, bez DCF 39, bez metody oceny 4 (GL, ARE, WY, CBRE), niekompletne 3 (APO, COIN, HONA).

| Bezpieczeństwo | Wycena | Z DCF | Bez DCF | Razem | Maks. wywołań Claude (×3) |
|---|---|---|---|---|---|
| Punkty ≥ 12/16 | MoS ≥ 0 | 35 | 8 | 43 | 129 |
| Punkty ≥ 12/16 | MoS ≥ 50 | 13 | 8 | 21 | 63 |
| Rdzeń obecny | MoS ≥ 0 | 41 | 9 | 50 | 150 |
| Rdzeń obecny | MoS ≥ 50 | 17 | 9 | 26 | 78 |
| **Rdzeń poprawiony** | **MoS ≥ 0** | **39** | **6** | **45** | **135** |
| Rdzeń poprawiony | MoS ≥ 50 | 15 | 6 | 21 | 63 |

„×3” to najgorszy przypadek (analiza + 2 naprawy). Faktyczna liczba napraw po poprawkach schematu nie jest jeszcze zmierzona.

**Rdzeń poprawiony + MoS ≥ 0:**
- **z DCF (39):** ADBE, ALLE, ANET, APH, APP, BKNG, CHRW, CMG, CMI, CPRT, DASH, DECK, DXCM, EME, ETN, EXE, FIX, FLEX, HII, HWM, INTU, JBHT, JBL, LDOS, LII, MU, PH, PNR, PYPL, QCOM, ROL, STX, TPL, TPR, TYL, VRT, WDC, XYL, ZTS;
- **bez DCF (6):** FSLR, GEV, LEN, NFLX, PODD, UBER.

### 3.4 Kto odpada i czy to ekonomicznie uzasadnione

**Odpadają przy przejściu z obecnego rdzenia na poprawiony:**

| Spółka | Przyczyna | Ocena ekonomiczna |
|---|---|---|
| F | dług netto przy EBITDA ≤ 0 | **Wątpliwe w obie strony.** Dług obejmuje prawdopodobnie Ford Credit, a EBITDA za 2025 jest ujemna przez odpisy (OCF 21,3 mld). Miara nie pasuje. |
| CVNA | jw. | **Dane do weryfikacji:** EBITDA ujemna przy zysku netto +1,4 mld |
| CEG | FCF z 3 lat −11,5 mld | **Wątpliwe.** OCF ujemny w latach 2021–2024 przy zyskach netto. Wygląda na efekt klasyfikacji przepływów (np. należności), ale tego nie zweryfikowałam. |
| SNDK | zysk w 1 z 3 lat | Uzasadnione regułą: straty FY2024–25, zysk 11,4 mld w FY2026 (szczyt cyklu pamięci) |
| MRVL, LITE, RDDT | zysk w 1 z 3 lat | Uzasadnione: krótka historia zyskowności |

**Obecna shortlista (24) poza kwalifikacją (rdzeń poprawiony + MoS ≥ 0):**
- APO (niekompletne dane);
- APTV (2,17: efekt progu);
- CEG (patrz wyżej);
- FISV (3,16: realna dźwignia);
- SNDK.

**Propozycja:** spółki, które odpadają przez warunek z wątpliwymi danymi albo miarą nieadekwatną do modelu biznesu (F, CVNA, CEG), trafiają do raportu jako **„do ręcznego przeglądu”**. Nie są automatycznie kwalifikowane ani cicho odrzucane. Analizę Claude dla wybranej spółki można zlecić ręcznie (istniejący tryb `--tickers`).

### 3.5 Spółki bez DCF, dla których nie potwierdzono atrakcyjnej ceny

Faktyczna przyczyna braku DCF u 5 z 6 zakwalifikowanych: **pierwszy rok okna ma ujemny FCF** (reguła CAGR z dwóch punktów), mimo silnie dodatniego FCF w ostatnich latach:
- NFLX: −0,13 → 9,46 mld;
- UBER: −0,74 → 9,76 mld;
- GEV: −2,24 → 3,71 mld;
- PODD i FSLR podobnie.

LEN: FCF w ostatnim roku ≈ 0 → wycena niepoliczalna.

Brak potwierdzenia ceny wynika więc z reguły wyceny, nie z ekonomii spółki.

| Wariant | Traktowanie | Wywołania na 22.10 (maks.) |
|---|---|---|
| **N1** | Analiza Claude dozwolona. Wynik na osobnej liście „jakość bez potwierdzonej ceny”; spółka nie może mieć statusu okazji cenowej. | 18 |
| N2 | Bez Claude do czasu metody wyceny (ukryte wykluczenie) | 0 |
| N3 | Bez automatycznej analizy, tylko na Twoje ręczne zlecenie | 0 + ręczne |

**Rekomendacja techniczna: N1** (jawne oznaczenie, niski koszt). Zmiana reguły CAGR należy do protokołu wyceny i nie jest tu proponowana.

---

## 4. Alokacja kapitału — poprawiona koncepcja (bez progów i bez zmian punktacji)

### 4.1 Co ma mierzyć komponent

| Definicja | Mierzy | Konsekwencja |
|---|---|---|
| **K1 — wypłaty dla akcjonariuszy** (obecna nazwa komponentu) | Gotówkę oddaną akcjonariuszom | Spółka skutecznie reinwestująca dostaje 0, nawet gdy reinwestycja tworzy więcej wartości |
| **K2 — jakość alokacji kapitału** | Czy decyzje zarządu (reinwestycja, przejęcia, buyback, dywidenda) podniosły wartość na akcję i nie osłabiły bilansu | Forma alokacji jest neutralna. Wypłata to jedna z możliwych dobrych decyzji. |

Ilustracja na 22.10 (FCF na akcję: średnia z 3 ostatnich lat wobec średniej z 3 lat wcześniejszych, roczne tempo):
- reinwestujące: BSX +41%, DDOG +39%, TYL +25%; AXON +2,6% (liczba akcji +32% w 2 lata);
- wypłacające: CHTR **−18%** mimo buybacku, MRK +9,6%, SNA +13%, QCOM +17%.

Mediana wzrostu:
- spółki wypłacające < 10% FCF (n = 8): 38,7%;
- spółki wypłacające ≥ 75% FCF (n = 76): 7,1%.

To ilustracja, nie dowód. Próba jest mała, a spółki reinwestujące to tu głównie spółki wzrostowe.

**Rekomendacja: K2.** K1 strukturalnie karze reinwestycję, a Ty zaznaczasz, że może ona być korzystniejsza od wypłaty. Zmiana definicji jest decyzją metodologiczną.

### 4.2 Elementy K2 i dostępność danych (zweryfikowane)

| Element | Miara | FMP (162 spółki, 802 lata) | SEC (615 CIK, 2016–2021) |
|---|---|---|---|
| Wartość na akcję | (FCF − SBC) na akcję, średnie 3-letnie, zmiana | `stockBasedCompensation`: 718 lat niezerowych | `ShareBasedCompensation`: 495 CIK |
| Buyback netto | skup − emisja za gotówkę | `commonStockRepurchased` 644, `commonStockIssuance` 398, `netCommonStockIssuance` 756 | skup: 521 CIK; emisja: 223 CIK (+ opcje 296) |
| Rozwodnienie bez przejęć | zmiana liczby akcji z wyłączeniem emisji przy przejęciach | **brak pola** (emisja przy przejęciu jest bezgotówkowa, poza cash flow) | `StockIssuedDuringPeriodSharesAcquisitions`: **24 CIK**; wartość: 127 CIK |
| Przejęcia gotówkowe | do oceny źródła wypłat | `acquisitionsNet` 591 | `PaymentsToAcquireBusinessesNetOfCashAcquired` 448 CIK |
| Finansowanie | przepływy długu | `netDebtIssuance` 710, `longTermNetDebtIssuance` 688 | emisja i spłata długu: ok. 347 CIK |
| Ciągłość dywidendy | **zadeklarowany** DPS (nie wypłaty gotówkowe) | dostępny endpoint `dividends` (nie badany tu) | `CommonStockDividendsPerShareDeclared`: 348 CIK |

### 4.3 Odpowiedzi na Twoje punkty

**1. Buyback netto vs rozwodnienie vs przejęcia.**
- Buyback netto i SBC da się mierzyć w obu źródłach.
- **Emisji przy przejęciach nie da się rzetelnie zmierzyć** ani w FMP (brak pola), ani w backteście (tag w SEC u 24 z 615 spółek).
- Propozycja:
  - rozwodnienie mierzyć **SBC** (powtarzalny koszt dla akcjonariusza);
  - skokowy wzrost liczby akcji w roku przejęcia oznaczać jako „możliwa emisja przy przejęciu — do weryfikacji” i nie liczyć go automatycznie jako rozwodnienia (przykład: AVGO +13,7% w roku przejęcia VMware);
  - próg „skoku” wymagałby decyzji, dlatego proponuję oznaczenie, a nie punkty.

**2. Wzrost długu brutto ≠ finansowanie wypłat.** Potwierdzone danymi:
- 54 spółki wypłaciły więcej niż 3-letni FCF; u 20 z nich dźwignia na końcu okna nadal ≤ 2,0.
  - ADBE: 102% FCF, dług brutto +2,0 mld, dźwignia 0,06 → 0,12;
  - PYPL: dźwignia 0,53 → 0,25;
  - TPR: 1,84 → 1,40.
- Propozycja: **test wynikowy zamiast przypisywania źródeł.** Wypłaty ponad FCF obniżają ocenę tylko wtedy, gdy dźwignia na końcu okna przekracza próg bezpieczeństwa (ten sam 2,0 co w K-B, dla spójności) albo EBITDA ≤ 0. Przykłady:
  - DOW: 584% FCF, dźwignia 1,35 → 13,3;
  - CARR: 1,31 → 3,15;
  - NRG: 2,84 → 3,66.
- Przypisanie wydatków do źródeł (FCF, dług, gotówka) wymaga arbitralnej kolejności, więc pokazuję je tylko jako diagnostykę.

**3. Dywidendy na akcje zwykłe, BA.**
- SEC dla BA FY2025:
  - brak tagu dywidend na akcje zwykłe i brak zadeklarowanego DPS;
  - jest tylko „dywidendy razem” 331 mln USD.
- FMP podaje te same 331 mln jako `commonDividendsPaid`, z `preferredDividendsPaid` = 0.
- W 2024 BA wyemitowała akcje uprzywilejowane za 5,66 mld (FMP `netPreferredStockIssuance`).
- **Wniosek: 331 mln to z dużym prawdopodobieństwem dywidenda od akcji uprzywilejowanych, błędnie zaliczona przez FMP do zwykłych.** SEC nie potwierdza wypłaty na akcje zwykłe. Treści 10-K nie czytałam.
- **Problem jest szerszy:**
  - 57 z 792 lat różni się między FMP a SEC.
  - AVGO 2021–2022: FMP „common” = suma z dywidendą uprzywilejowaną (SEC common 5,91 mld wobec FMP 6,21 mld; uprzywilejowane 0,30 mld).
  - Przy BSX jest odwrotnie (FMP 0, SEC 55 mln, prawdopodobnie uprzywilejowane).
  - Większość pozostałych to „brak w SEC” pod badanymi tagami (spółka używa innego tagu), a nie błąd.
  - **Backtest ma ten sam problem:** gdy brak tagu dla akcji zwykłych, bierze `PaymentsOfDividends` (suma z uprzywilejowanymi).
- Propozycja:
  - DPS i cięcie dywidendy liczyć z **zadeklarowanego DPS** (SEC `CommonStockDividendsPerShareDeclared`, w skanie endpoint dywidend FMP);
  - wypłaty gotówkowe na akcje zwykłe = FMP `commonDividendsPaid` − `preferredDividendsPaid`, gdy oba są dostępne;
  - przy rozbieżności z SEC powyżej 5% — flaga.

**4. Wypłaty czy jakość alokacji:** patrz 4.1, rekomendacja K2.

**5. Reinwestycja może być lepsza od wypłaty:** K2 to uwzględnia przez wartość na akcję. K1 tego nie umie z konstrukcji.

### 4.4 Ryzyka K2 (jawnie)
- **Podwójne liczenie z wyceną.** DCF też korzysta ze wzrostu FCF. K2 mierzy wzrost na akcję po SBC, a DCF — wzrost całkowitego FCF. Nakładanie się jest częściowe, ale realne.
- **Cykliczność.** Szczyty cyklu (MU, SNDK) dają wysoki wzrost. Średnie 3-letnie łagodzą efekt, ale go nie usuwają.
- **Ujemny start.** U 23 z 153 spółek wzrost jest niepoliczalny. Potrzebna reguła: brak punktów za wzrost i oznaczenie, a nie kara.
- **Kalibracja progów.** Każdy próg ustalony na danych 2012–2021 to kolejne spojrzenie na wielokrotnie używane dane. Alternatywa: progi z definicji (np. wzrost ≤ 0 → 0 pkt) i śledzenie prospektywne „w cieniu”.

---

## 5. Znalezione błędy i problemy danych (do decyzji, niepoprawione)
1. **Znak dźwigni przy EBITDA ≤ 0.** Produkcyjny `low_leverage` zalicza warunek. 7 spółek na 22.10 dostaje nienależne 3 pkt bezpieczeństwa.
2. **Dywidendy uprzywilejowane jako zwykłe.** FMP: BA, AVGO 2021–22. Backtest: zapasowy tag `PaymentsOfDividends`.
3. **SIC 6500 → REIT** obejmuje firmy usługowe (CBRE).
4. **Backtest: błąd SEC przy klasyfikacji zostawia profil GENERAL.** W runie z 5.10 i w tej diagnostyce błędów nie było, ale reguła wymaga wyrównania ze skanem.

---

## 6. Decyzje potrzebne przed nowym pełnym skanem

**Kwalifikacja do Claude**
1. Rdzeń wypłacalności: poprawiony (3.2) czy inny wariant.
2. Wycena w kwalifikacji: MoS ≥ 0 czy ≥ 50%.
3. Spółki bez DCF: N1, N2 czy N3.
4. Lista „do ręcznego przeglądu” (F, CVNA, CEG-podobne): tak / nie.
5. Limit wywołań dla pełnego skanu przy znanym Q (na 22.10: 63–135 w najgorszym przypadku) i zachowanie po przekroczeniu (zatrzymanie przed Claude — zaakceptowane).

**Poprawki błędów (osobno od metodologii)**

6. Błąd znaku dźwigni (5.1): poprawić w produkcyjnym scoringu?
7. Dywidendy uprzywilejowane (5.2): korekta w FMP i w backteście?
8. Zakres REIT: zawęzić do 6798 (bez 6500)?
9. Backtest: błąd SEC → wykluczenie zamiast GENERAL.

**Alokacja kapitału**

10. K1 czy K2. Przy K2: struktura elementów, bez progów na tym etapie.
11. Emisja przy przejęciu: oznaczenie zamiast punktów.
12. Ciągłość dywidendy z zadeklarowanego DPS.

**Protokół i backtest**

13. SIC point-in-time w backteście: wdrożyć dla poprawności (wpływ: 2 obserwacje) czy pominąć z adnotacją.
14. Protokół v2: bootstrap uwzględniający powtarzanie spółek (127 spółek w podzbiorze z wyceną).

**Kolejność:**
1. Decyzje 1–9.
2. Jedna implementacja z testami regresyjnymi i symulacją na 22.10.
3. Decyzja 10–12 (alokacja kapitału może wejść osobno, po niej).
4. Zgoda na pełny skan.
