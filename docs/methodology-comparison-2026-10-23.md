# Porównanie metodologii Buffett Scannera — 2026-10-23

Status: **analiza do decyzji. Produkcyjny scoring, DCF, CAGR, MoS i wagi bez zmian. Żaden wariant nie jest wdrożony.**

Materiały:
- pełne tabele wariantów (pozycja, wynik, MoS dla każdej spółki): `docs/analysis/methodology_variants_2026_10_23_results.md`;
- skrypt do odtworzenia: `docs/analysis/methodology_variants_2026_10_23.py` (czyta snapshot skanu 22.10, niczego nie zapisuje);
- wcześniejszy audyt reguł: `docs/methodology-audit-2026-10-23.md`.

## 1. Analiza wrażliwości na danych 22.10

**Metoda.**
- Skrypt odtwarza produkcyjny DCF i ranking: 0/162 rozbieżności MoS, identyczny ranking i shortlista.
- Każdy wariant zmienia JEDNĄ regułę, pozostałe zostają jak w produkcji.
- Shortlista = TOP 20 + remisy (jak w produkcji).
- Spearman to korelacja kolejności całego rankingu 162 spółek: 1,0 = kolejność identyczna.
- „MoS ≥ 50%” liczone w całym rankingu (produkcja: 24 spółki, z czego 16 na shortliście).

**To porównanie, nie ocena.** Na danych jednego dnia nie da się stwierdzić, który wariant wybiera lepsze spółki. Mierzymy wyłącznie, jak bardzo ranking zależy od reguły.

| Wariant | Spearman | Shortlista (24 → n) | Wypadają | Wchodzą | MoS ≥ 50% w rankingu |
|---|---|---|---|---|---|
| G1 Sufit wzrostu 15% | 0,947 | 20 | DXCM, XYL, EME, JBL | — | 24 → 17 |
| G2 Sufit wzrostu 10% | 0,827 | 20 | APP, DXCM, XYL, EME, HII, JBL | PYPL, CMCSA | 24 → 10 |
| G3 Wygaszanie wzrostu do 2,5% w 10 lat | 0,866 | 20 | APP, DXCM, XYL, PNR, EME, JBL | CMCSA, PYPL | 24 → 9 |
| G4 Wygaszanie od max 10% | 0,742 | 20 | APP, DXCM, MU, SNDK, XYL, BKNG, EXE, EME, HII, JBL | CMCSA, PYPL, ARES, FSLR, RDDT, F | 24 → 5 |
| F1 Baza FCF = średnia z okna | 0,855 | 20 | APP, DXCM, MU, SNDK, XYL, PNR, EME | CHRW, IR, PYPL | 24 → 9 |
| F2 Baza FCF = mediana | 0,838 | 20 | APP, DXCM, MU, XYL, PNR, EME | IR, CHRW | 24 → 9 |
| F3 Mniejsza z: najnowszy, średni FCF | 0,855 | 20 | jak F1 | jak F1 | 24 → 9 |
| D1 Bez punktów „brak cięcia”/„payout” przy DPS = 0 | 0,944 | 20 | PODD, ADBE, NFLX, UBER, APTV, FISV | IR, CHRW | bez zmian |
| D2 Kryteria dywidendowe „nie dotyczy” przy DPS = 0 | 0,986 | 24 | — | — | bez zmian |
| B1 Brak wyceny = 0 z 20 pkt | 0,783 | 20 | PODD, CEG, NFLX, UBER | — | bez zmian |
| B2 Brak wyceny = 10 z 20 pkt | 0,985 | 20 | PODD, CEG, NFLX, UBER | — | bez zmian |
| B3 Najpierw spółki z DCF | 0,628 | 20 | PODD, CEG, NFLX, UBER | — | bez zmian |
| B4 Bez komponentu wyceny | 0,483 | 27 | 16 spółek | 19 spółek | — |
| C1 CAGR od 1. dodatniego roku | 0,949 | 25 | — | TMUS | 24 → 28 |
| C2 Trend log-liniowy lat dodatnich | 0,873 | 20 | APO, EXE, CEG, APTV, EME, FISV, HII, JBL | LII, ZTS, LULU, PYPL | 24 → 30 |
| C3 Mediana wzrostu r/r | 0,789 | 20 | APO, EXE, CEG, NFLX, APTV, EME, FISV, HII, JBL | LII, ON, COIN, DPZ, ALLE | 24 → 34 |

**Stała część shortlisty** (liczba wariantów z 16, w których spółka wypada):
- **0/16:** DECK, INTU, TPR, QCOM;
- **1–2/16:** LDOS (B4), ADBE (D1, B4), BKNG (G4, B4);
- **najbardziej wrażliwe:** EME 10/16, XYL 8/16, DXCM 7/16, JBL 7/16, APP 6/16, CEG 6/16, NFLX 6/16.

O mniej więcej połowie listy decydują reguły, nie same dane.

**MU i SNDK** (MoS BASE, %):

| Produkcja | Sufit 15% | Sufit 10% | Wygaszanie | Wygaszanie od 10% | Średni FCF | Mediana FCF |
|---|---|---|---|---|---|---|
| MU 72 / SNDK 71 | 60 / 58 | 41 / 40 | 49 / 47 | 25 / 22 | −37 / −50 | −645 / brak DCF |

**Obserwacje przekrojowe.**
1. **Reguły działają na siebie nawzajem i nie zawsze w intuicyjnym kierunku.** Gdy wariant odbiera spółce DCF (SNDK w F2, C2, C3), renormalizacja podnosi jej wynik procentowy. Gorsze dane mogą więc dać wyższą pozycję.
2. **Remisy.** W produkcji 5 spółek ma 100%, a ich kolejność jest alfabetyczna. W B4 ponad 25 spółek ma 100%, więc TOP 20 wybiera alfabet. Skala punktowa safety i dywidend jest zbyt gruba, by sama tworzyła ranking.
3. **Warianty CAGR (C2, C3) są niestabilne przy latach z FCF bliskim zeru.** HII i EXE mają rok z FCF ≈ 0, co daje ujemny trend i MoS −127% oraz −82%. Jednocześnie warianty te dodają spółki z odbudowującym się FCF (ON, COIN, LULU).
4. **Warianty konserwatywne (G2–G4, F1–F3)** zgodnie wyrzucają te same spółki: APP, DXCM, XYL, EME, a w F oraz G4 także MU i SNDK. To spółki, których MoS opiera się na wysokim wzroście albo szczytowym FCF.

Ograniczenia każdego wariantu: sekcja „Ograniczenia i ryzyko” w pliku wyników.

## 2. Test historyczny 2022–2026 (Faza 5.6, `docs/buffett-scanner-design-review.md`, l. 1901–1998)

**Status: wykorzystany jednorazowo. Nie wolno go używać do strojenia ani ponownie przedstawiać jako niezależnej walidacji jakiejkolwiek zmiany.**

**Metodologia.**
- Walk-forward: 58 miesięcznych dat decyzji, 2022-01-01 → 2026-10-01.
- Konfiguracja zamrożona przed otwarciem holdoutu (hash `config.yaml:9553e5c9f27ac673`, commit `c6d7e357`), jedno uruchomienie GitHub Actions (37346815021).
- Konfiguracja identyczna z tą sprzed kalibracji: kalibracja niczego nie zmieniła.
- Okno kalibracyjne 2012–2021 zakodowane na sztywno; dane 2022–2026 były dla kalibracji niedostępne.
- **Oceniany był tylko wynik deterministyczny** (bezpieczeństwo + wycena + dywidendy). Komponenty Claude (jakość biznesu 45 pkt, strach/okazja 10 pkt) nigdy nie były testowane historycznie.
- **Źródło danych: SEC XBRL** (fakty roczne, point-in-time), nie FMP jak w skanie na żywo. W backteście stosowano klasyfikację sektorową z SIC; w skanie na żywo nie (pkt 3.4).

**Benchmark.**
- Główny: średnia stopa zwrotu wszystkich spółek uniwersum point-in-time danego dnia (equal-weighted).
- Pomocniczy: SPY.
- Oba jako zwrot cenowy, bez dywidend.

**Metryki i horyzonty.**
- Mediana nadwyżki zwrotu nad benchmarkiem, hit rate (% kandydatów lepszych od benchmarku), Spearman (wynik vs nadwyżka).
- Horyzonty 1, 3, 6 i 12 miesięcy; główny: 6 miesięcy.

**Liczebność.**
- 7 809 kandydatów (6 m: n = 6 689).
- Podzbiór z kompletną wyceną: 1 429 obserwacji (6 m: n = 1 188).
- Pokrycie uniwersum 98,1% (615 CIK).

**Zabezpieczenia.**
- **Survivorship bias:** historyczny skład S&P 500 (fja05680 jako źródło kanoniczne, FMP jako walidator), okno od 2012 z powodu jakości danych, naprawione podwójne klasy akcji.
- **Look-ahead:** fakty XBRL z datą złożenia nie późniejszą niż data decyzji (asercje programowe); stopy zwrotu liczone osobną funkcją po zamrożeniu kandydata.

**Wyniki (6 m, główny horyzont).**

| Model | Mediana nadwyżki vs EW | vs SPY | Hit rate vs EW | Spearman |
|---|---|---|---|---|
| Pełny model deterministyczny (cała populacja, n = 6 689) | −2,30% | −4,19% | 45,2% | 0,058 |
| Z wyceną (podzbiór z wyceną, n = 1 188) | −0,29% | −2,12% | 49,5% | 0,031 |
| Bez wyceny (te same 1 188 obserwacji) | — | — | — | 0,135 |

- Spearman bez wyceny był wyższy na wszystkich 4 horyzontach (1 m: 0,053 vs 0,016; 3 m: 0,106 vs 0,030; 12 m: 0,115 vs 0,020).
- Per rok: wyższy w 4 z 5 lat; w 2024 bez wyceny −0,071.
- Wszystkie 5 lat holdoutu miały ujemną medianę nadwyżki.
- Klasyfikacja w raporcie: **B — słabe / niejednoznaczne uogólnienie.**

**Ograniczenia statystyczne.**
- **Protokół nie przewidywał testu istotności.** Raport wprost odmawia post-hoc progu.
- **Szacunek pomocniczy (mój, nie z protokołu):** przy założeniu niezależnych obserwacji błąd standardowy Spearmana przy n = 1 188 to ok. 0,03. 0,031 jest wtedy nieodróżnialne od zera, a 0,135 to ok. 4,5 błędu.
- **Obserwacje NIE są niezależne:** miesięczne daty przy horyzoncie 6 m nakładają się, te same spółki się powtarzają, a w danym dniu spółki są skorelowane. Efektywna liczebność jest wielokrotnie mniejsza (dokładnie nieznana), więc przewaga modelu bez wyceny jest **wskazówką, nie dowodem**.
- **Podzbiór z wyceną jest wybrany nielosowo** (spółki z dodatnim FCF i kompletnym długiem), a w kalibracji był mały (n = 1 111).
- **Test mówi o modelu deterministycznym na danych SEC**, nie o skanie na żywo z FMP i komponentami Claude.

## 3. Dane finansowe

### 3.1 MU i SNDK — zweryfikowane z wynikami spółek

**MU, FY2026 (rok do 3.09.2026).**
- Dane FMP: przychody 133,19 mld, zysk netto 84,97 mld, przepływy operacyjne 89,68 mld, nakłady inwestycyjne 30,71 mld, czyli FCF 58,96 mld USD.
- Micron: przychody 133,2 mld, zysk netto 84,97 mld, nakłady inwestycyjne **netto** 27,37 mld, adjusted FCF 62,31 mld USD. Wynika z tego przepływ operacyjny 89,68 mld, zgodny z FMP.
- Różnica wynika z definicji: FMP ujmuje nakłady brutto, Micron netto.
- FY2022–FY2025 w FMP są zgodne z publicznymi danymi (np. FY2025: przychody 37,38 mld, zysk netto 8,54 mld).

**SNDK, FY2026 (rok do 3.07.2026).**
- Dane FMP: przychody 20,25 mld, zysk netto 11,43 mld, przepływy operacyjne 11,67 mld USD — zgodne z raportem spółki.
- Nakładów inwestycyjnych (0,18 mld) nie zweryfikowałam.
- FY2022–FY2024 pochodzą sprzed wydzielenia ze struktur Western Digital. FMP podaje dla nich niewiarygodne daty złożenia, równe końcowi okresu.

**Wniosek.** Dane są prawdziwe. MoS +72% i +71% wynika z metody, a nie z błędu danych: FCF z roku szczytu cyklu pamięci (MU: z 1,67 do 58,96 mld; SNDK: z −0,12 do 11,49 mld) jest projektowany jako baza rosnąca o 20% rocznie przez 10 lat.

Źródła:
- [Micron FY2026 press release](https://www.globenewswire.com/news-release/2026/09/30/3372366/14450/en/micron-technology-inc-reports-record-fiscal-fourth-quarter-and-full-year-2026-results.html)
- [Micron 8-K (SEC)](https://www.sec.gov/Archives/edgar/data/0000723125/000072312526000018/a2026q4ex991-pressrelease.htm)
- [Sandisk Q4 FY2026 release](https://investor.sandisk.com/news-releases/news-release-details/sandisk-reports-fiscal-fourth-quarter-2026-financial-results)
- [Sandisk 8-K (SEC)](https://www.sec.gov/Archives/edgar/data/0002023554/000162828026053346/sndkq4-26ex991xpressrelease.htm)

### 3.2 Zera z FMP

- Normalizacja pomija wartości brakujące (`None`), ale zapisuje `0` jako zero. Brak pozycji w odpowiedzi FMP daje brak danych; zero z FMP traktujemy jako prawdziwe zero.
- W 804 okresach 162 spółek z 22.10:

| Pozycja | Zera | Ocena |
|---|---|---|
| dividends_paid | 294 | Zwykle prawdziwe (spółki bez dywidendy) |
| share_buybacks | 158 | Zwykle prawdziwe |
| capital_expenditure | 10 (Apollo ×3, Alexandria ×4, Coinbase ×3) | **Podejrzane**: firma finansowa / REIT; FCF = całe przepływy operacyjne |
| total_debt | 7 (Arista, Intuitive Surgical, MPWR, GE Vernova) | Wiarygodne: spółki bez długu |
| pozostałe pola | 0 | — |

**Wpływ na scoring.**
- Nakłady = 0 zawyżają FCF, a przez to MoS, punkty za wycenę i kryteria FCF w bezpieczeństwie. Apollo jest na shortliście (MoS 84%) z nakładami 0 we wszystkich ostatnich latach.
- Zerowa dywidenda daje automatyczne punkty za „brak cięcia” i „payout” (patrz D1).
- Dla dywidend nie da się odróżnić „nie płaci” od „FMP nie podało”.

### 3.3 (wcześniej) Niewiarygodne daty złożenia
22 z 804 okresów ma datę „złożenia” równą końcowi okresu. Obsłużone regułą dostępności z 23.10 (commit `b5a1bab`).

### 3.4 Brak klasyfikacji sektorowej w skanie na żywo — **błąd logiczny**

- `run-live-scan` zapisuje spółki przez `upsert_company` bez `sector_profile`, więc wszystkie 500 mają GENERAL.
- Klasyfikacja z SIC (`classify-sector-profiles`) była używana wyłącznie w backteście.
- Konfiguracja przewiduje dla BANK/INSURER/REIT brak metody DCF, a skan wycenia je zwykłym DCF z FCF.
- W rankingu 22.10 jest 9 spółek finansowych i 4 nieruchomościowe, m.in.:
  - GL (Insurance-Life) z DCF;
  - ARE i WY (REIT);
  - APO na shortliście. Apollo jako zarządzający aktywami według zasad SIC prawdopodobnie i tak pozostałby GENERAL, ale tego nie sprawdziłam.
- Dokładny podział wymaga kodów SIC z SEC.

## 4. Rekomendowana architektura metodologii

### A. Ewidentne błędy logiczne (niezależnie od decyzji inwestycyjnych)
1. **Brak klasyfikacji sektorowej w skanie na żywo.** Banki, ubezpieczyciele i REIT-y są wyceniane metodą, której konfiguracja dla nich nie przewiduje. Skan na żywo różni się też tu od backtestu.
2. **Nakłady inwestycyjne = 0 z FMP traktowane jako prawdziwe zero** u spółek finansowych i REIT. FCF = przepływy operacyjne.
3. **Mylący komunikat o braku DCF.** Mówi o „≥2 dodatnich latach”, a reguła wymaga dodatniego pierwszego i ostatniego roku.
4. **Kolejność w remisie jest alfabetyczna, a pokazywana jako ranking** (np. „miejsce 1”). Shortlista obejmuje remisy, ale pozycje sugerują nieistniejące pierwszeństwo.

### B. Świadome decyzje inwestycyjne (udokumentowane, do potwierdzenia)
- Spadek ceny jako sygnał wejścia; prefilter tylko flaguje.
- Wagi: jakość biznesu 45, bezpieczeństwo 15, wycena 20, strach/okazja 10, dywidendy 10.
- DCF na proxy owner earnings (FCF), 3 scenariusze, MoS z BASE.
- „Brak danych to nie 0”, czyli renormalizacja.
- „Nie zgadujemy wzrostu.”
- Twarde bramki wyłączone.
- Payout liczony od FCF.

### C. Uproszczenia wymagające walidacji
- Sufit 20% i stały wzrost przez 10 lat bez wygaszania (G1–G4).
- Najnowszy FCF jako baza, bez normalizacji przez cykl (F1–F3; MU, SNDK).
- CAGR z dwóch punktów końcowych (C1–C3).
- Nasycenie punktów wyceny przy MoS ≥ 50%.
- Kryteria dywidendowe dla spółek bez dywidendy (D1/D2), jeśli punkty przy DPS = 0 były zamierzone. Jeśli nie, przenieść do kategorii A.
- Łączenie baz 25 i 45 pkt w jednym rankingu (B1–B3). Zasada jest świadoma, ale efekt „gorsze dane → wyższa pozycja” nie był oceniany.
- Gruba skala punktowa safety i dywidend, stąd masowe remisy.

### D. Obszary bez wystarczających dowodów
- Czy model w ogóle ma przewagę: holdout klasy B, wszystkie lata ujemne.
- Czy wycena wnosi informację: holdout sugeruje, że nie, ale obserwacje są zależne, a test był na danych SEC, bez Claude.
- Komponenty Claude (55% wagi): zero walidacji historycznej.
- Progi spadku cen (`UNCALIBRATED`).
- Traktowanie spółek cyklicznych i finansowych.

### Proponowana struktura (do decyzji, bez wdrożenia)
1. **Dane i kwalifikacja** (warstwa techniczna, bez wpływu na filozofię):
   - kontrola danych z 23.10;
   - klasyfikacja sektorowa w skanie na żywo (banki, ubezpieczyciele i REIT poza DCF albo na osobnej liście);
   - nakłady = 0 u spółek operacyjnych traktowane jako brak danych.
2. **Ranking deterministyczny tylko na porównywalnych bazach.** Spółki bez DCF w osobnej puli albo z jawną regułą (decyzja B1/B2/B3). Remisy pokazywane jako remisy.
3. **Wycena jako przedział i flaga wrażliwości, nie tylko punkty.**
   - Pokazywać MoS w scenariuszu bazowym i konserwatywnym (np. wygaszanie + znormalizowany FCF).
   - Oznaczać spółki, u których znak MoS zależy od założeń (MU, SNDK, APP, DXCM).
   - Czy wycena zostaje w punktach, wchodzi jako bramka czy jako informacja — decyzja inwestycyjna.
4. **Analiza Claude** wyraźnie oznaczona jako niewalidowana.
5. **Protokół walidacji:**
   - każda zmiana z kategorii C jako z góry zapisany pakiet;
   - test na oknie 2012–2021 (wewnętrzne foldy; uwaga na małe n z wyceną);
   - śledzenie kolejnych skanów od teraz, z zamrożoną wersją konfiguracji;
   - holdout 2022–2026 już zużyty — tylko jako opis, nie do wyboru.

**Proponowana kolejność decyzji:**
1. Błędy z kategorii A. Zmieniają wyniki, więc po poprawce trzeba ponownie policzyć baseline 2012–2021, ale tylko w celu dokumentacji, bez strojenia.
2. Zasady z kategorii B/C dotyczące baz punktowych i dywidend.
3. Pakiet wyceny (wzrost, baza FCF, CAGR) testowany jako całość na 2012–2021.
