# Protokół porównania wariantów wyceny na danych 2012–2021 (zdefiniowany przed testem)

> **Wersja robocza v1 — NIE do zamrożenia.** Fakty do v2 (liczebności, wcześniejsze analizy, SIC, ograniczenie przeuczenia): `docs/methodology-proposals-2026-10-23-r3.md`, sekcja 4. Kryterium lat, dobór lat z odpowiednimi danymi, obsługa zależności obserwacji i 12 porównań oraz rozdzielenie wyboru od potwierdzenia wymagają zmian opisanych w `docs/methodology-proposals-2026-10-23-r2.md`, sekcja 4. Wersja v2 powstanie po akceptacji tych zmian.

Status: **PROJEKT DO AKCEPTACJI. Test nie został wykonany.** Po akceptacji protokół jest zamrażany (commit + hash) przed jakimkolwiek uruchomieniem. Zmiany po obejrzeniu wyników są niedozwolone. Nowy pomysł = nowa wersja protokołu oznaczona jako eksploracyjna.

## 1. Cel
Sprawdzić, czy wybrane warianty wzrostu w DCF, liczenia CAGR i bazy FCF dają **stabilniejszą i bardziej informacyjną** wycenę niż obecna reguła.

Celem NIE jest znalezienie parametrów maksymalizujących historyczny wynik ani uzasadnienie konkretnej listy spółek.

## 2. Dane i okno
- Silnik walk-forward point-in-time z backtestu (Faza 5.3c), dane SEC XBRL, historyczny skład S&P 500 (615 CIK), miesięczne daty decyzji.
- **Okno: 2012-01-01 → 2021-12-01.** Wewnętrzne foldy poza próbką: lata 2016–2021 (jak w kalibracji).
- **Okres 2022–2026 jest WYŁĄCZONY.** Raz użyty jako holdout, nie może służyć do wyboru ani do „niezależnej walidacji” żadnego wariantu.
- Lejek (sygnały spadku, prefilter) zamrożony jak w produkcji: ci sami kandydaci we wszystkich wariantach.
- Wymóg wstępny: artefakt z zabackfillowaną bazą (Faza 5.3b) musi być dostępny. Do sprawdzenia przed uruchomieniem (retencja artefaktów).

## 3. Warianty (lista zamknięta)
Każdy wariant zmienia wyłącznie wycenę. Wagi, mapowanie MoS → punkty (pełne punkty od 50%), dyskonto (BEAR/BASE/BULL 11/9/7%), wzrost rezydualny (1/2,5/3,5%), 10 lat projekcji, bezpieczeństwo i dywidendy pozostają produkcyjne.

| Kod | Wariant |
|---|---|
| V0 | Produkcja: CAGR z pierwszego i ostatniego okresu, sufit 20%, stały wzrost 10 lat, najnowszy FCF |
| G1 | Sufit 15% |
| G2 | Sufit 10% |
| G3 | Wygaszanie liniowe od obecnego wzrostu (max 20%) do wzrostu rezydualnego w roku 10 |
| G4 | Wygaszanie od min(wzrost, 10%) |
| F1 | Baza FCF = średnia z okna (do 5 lat rocznych) |
| F2 | Baza FCF = mediana z okna |
| F3 | Baza FCF = mniejsza z: najnowszy, średnia |
| C1 | CAGR od pierwszego dodatniego roku (min. 2 lata) |
| C2 | Trend log-liniowy z lat dodatnich (min. 3 lata) |
| C3 | Mediana wzrostu r/r z par dodatnich lat (min. 2 pary) |
| K1 | Pakiet: G3 + F1 |
| K2 | Pakiet: G4 + F1 + C1 |

Razem 12 wariantów porównywanych z V0. Definicje są identyczne z `docs/analysis/methodology_variants_2026_10_23.py`.

## 4. Metryki
Wariant C zmienia, które obserwacje w ogóle mają DCF, dlatego:
- **Populacja główna: obserwacje, które mają DCF we WSZYSTKICH wariantach** (porównanie parami na tych samych obserwacjach).
- Populacja pomocnicza: wszystkie obserwacje z DCF w danym wariancie (pokazuje też zmianę pokrycia).

**Metryka główna:** Spearman(MoS BASE, nadwyżka 6-miesięcznego zwrotu nad benchmarkiem EW), liczony w każdej dacie decyzji i uśredniany, raportowany:
- łącznie;
- dla każdego roku 2016–2021.

**Metryki pomocnicze:**
- Spearman dla horyzontów 3 i 12 miesięcy;
- różnica median nadwyżki: górny vs dolny kwintyl MoS;
- hit rate górnego kwintyla;
- odsetek obserwacji z pełnymi punktami za wycenę (nasycenie);
- odsetek obserwacji z MoS > 0;
- stabilność rankingu względem V0 (Spearman wyników);
- zmiana pokrycia DCF.

**Benchmarki:**
- główny: średnia (EW) uniwersum point-in-time;
- pomocniczy: SPY.

Zwroty cenowe bez dywidend, jak w dotychczasowych testach.

## 5. Kryteria oceny (ustalone z góry)
Wariant może zostać **zarekomendowany** tylko, jeśli spełnia WSZYSTKIE warunki:
1. **Metryka główna wyższa niż w V0 w co najmniej 4 z 6 lat (2016–2021).**
2. **Istotność różnicy:** 95% przedział ufności różnicy łącznej metryki głównej (wariant − V0) nie obejmuje zera.
   - Bootstrap blokowy po miesiącach decyzji, bloki 6-miesięczne (z powodu nakładających się 6-miesięcznych zwrotów), 2 000 losowań.
   - Poziom skorygowany Bonferronim na 12 porównań.
3. **Brak pogorszenia o więcej niż 0,02 Spearmana na żadnym z horyzontów pomocniczych (3, 12 m).**
4. **Przegląd ekonomiczny:** brak oczywistych artefaktów (np. MoS skrajnie wrażliwy na rok z FCF ≈ 0), udokumentowany przed decyzją.

Jeśli żaden wariant nie spełnia warunków: **produkcja bez zmian**, wynik zapisany jako ważny wynik negatywny. Wariant spełniający warunki nie jest wdrażany automatycznie. Rekomendacja trafia do właścicielki z pełnym raportem wszystkich wariantów.

## 6. Ograniczenia (znane przed testem)
- **Zależne obserwacje.** Nakładające się okna zwrotów i korelacje między spółkami w tym samym dniu sprawiają, że efektywna liczebność jest wielokrotnie mniejsza od liczby obserwacji. Bootstrap blokowy łagodzi ten problem, ale go nie usuwa.
- **Mała próba z wyceną.** Obserwacji z DCF było w kalibracji ok. 1 100. Moc testu jest niska, więc wynik „brak różnicy” jest prawdopodobny i nie dowodzi równoważności.
- **Inne źródło danych.** Backtest używa SEC XBRL, skan na żywo FMP (inne definicje, np. CAPEX brutto/netto).
- **Tylko część modelu.** Test nie obejmuje komponentów Claude (55% wagi) ani interakcji z renormalizacją wyniku.
- **Specyfika okna.** 2012–2021 to w większości hossa; zachowanie w długich bessach słabo reprezentowane. Cykl pamięci 2025–2026 (MU, SNDK) leży poza oknem.
- **Brak niezależnego potwierdzenia.** Jedynym kolejnym sprawdzianem będzie śledzenie przyszłych skanów (forward tracking) z zamrożoną wersją konfiguracji.

## 7. Wykonanie (po akceptacji)
1. Implementacja wariantów jako opcji analitycznych w silniku backtestu (bez zmiany produkcji) + testy jednostkowe zgodności V0 z produkcją.
2. Zamrożenie: commit, hash konfiguracji, ten dokument.
3. Jedno uruchomienie GitHub Actions. Bez płatnych API: dane SEC i ceny są już w bazie z backfillu.
4. Raport wszystkich 13 wariantów według sekcji 4–5, bez pomijania niekorzystnych.
5. Decyzja właścicielki.
