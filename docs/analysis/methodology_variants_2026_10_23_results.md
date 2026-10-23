# Analiza wrażliwości rankingu — dane skanu 22.10.2026

Weryfikacja odtworzenia produkcji: MoS niezgodnych: 0/162; ranking i shortlista identyczne z bazą: TAK. Shortlista produkcyjna (24): APP, DECK, INTU, PODD, TPR, DXCM, QCOM, MU, SNDK, XYL, ADBE, BKNG, LDOS, PNR, APO, EXE, CEG, NFLX, UBER, APTV, EME, FISV, HII, JBL.

Każdy wariant zmienia JEDNĄ regułę; pozostałe = produkcja. Spearman 1,0 = identyczna kolejność. Warianty nie są oceniane jako lepsze/gorsze -- na danych jednego dnia nie da się tego stwierdzić.

## G1. Sufit wzrostu 15%

Zmienia tylko ścieżkę wzrostu w DCF (baza FCF = najnowszy rok, CAGR jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.947**
- TOP20: wypadają DXCM, XYL; wchodzą FISV, HII
- Shortlista: 24 -> 20 spółek; wypadają DXCM, XYL, EME, JBL; wchodzą brak
- DCF policzony: 120 -> 120 spółek; MoS>=50%: 24 -> 17; mediana MoS: -14.4 -> -25.0

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 8 | 100.0 -> 93.8 | 61 -> 43 | = |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 73 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 72 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 100.0 | 77 -> 66 | = |
| DXCM | 6 -> 31 | 99.6 -> 79.1 | 50 -> 26 | wypada |
| QCOM | 7 -> 5 | 96.9 -> 96.9 | 47 -> 47 | = |
| MU | 8 -> 6 | 95.6 -> 95.6 | 72 -> 60 | = |
| SNDK | 9 -> 7 | 95.6 -> 95.6 | 71 -> 58 | = |
| XYL | 10 -> 40 | 95.3 -> 74.7 | 50 -> 27 | wypada |
| ADBE | 11 -> 9 | 93.8 -> 93.8 | 55 -> 55 | = |
| BKNG | 12 -> 10 | 93.8 -> 93.8 | 75 -> 64 | = |
| LDOS | 13 -> 11 | 93.8 -> 93.8 | 71 -> 71 | = |
| PNR | 14 -> 12 | 93.0 -> 93.0 | 42 -> 42 | = |
| APO | 15 -> 13 | 89.3 -> 89.3 | 84 -> 77 | = |
| EXE | 16 -> 14 | 89.3 -> 89.3 | 68 -> 68 | = |
| CEG | 17 -> 15 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 16 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 17 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 18 | 87.5 -> 87.5 | 88 -> 83 | = |
| EME | 21 -> 32 | 87.5 -> 77.8 | 58 -> 39 | wypada |
| FISV | 22 -> 19 | 87.5 -> 87.5 | 71 -> 71 | = |
| HII | 23 -> 20 | 87.5 -> 87.5 | 68 -> 63 | = |
| JBL | 24 -> 22 | 87.5 -> 84.4 | 64 -> 46 | wypada |

**Ograniczenia i ryzyko:** Nadal 10 lat stałego wzrostu; 15% to wartość z siatki Round 3, nie wynik walidacji.

## G2. Sufit wzrostu 10%

Zmienia tylko ścieżkę wzrostu w DCF (baza FCF = najnowszy rok, CAGR jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.827**
- TOP20: wypadają APP, DXCM, XYL; wchodzą CMCSA, FISV, PYPL
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, XYL, EME, HII, JBL; wchodzą PYPL, CMCSA
- DCF policzony: 120 -> 118 spółek; MoS>=50%: 24 -> 10; mediana MoS: -14.4 -> -55.7

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 34 | 100.0 -> 70.4 | 61 -> 17 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 61 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 58 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 99.5 | 77 -> 49 | = |
| DXCM | 6 -> 58 | 99.6 -> 55.6 | 50 -> -8 | wypada |
| QCOM | 7 -> 5 | 96.9 -> 95.6 | 47 -> 45 | = |
| MU | 8 -> 15 | 95.6 -> 88.0 | 72 -> 41 | = |
| SNDK | 9 -> 18 | 95.6 -> 86.4 | 71 -> 40 | = |
| XYL | 10 -> 81 | 95.3 -> 51.1 | 50 -> -8 | wypada |
| ADBE | 11 -> 6 | 93.8 -> 93.8 | 55 -> 55 | = |
| BKNG | 12 -> 9 | 93.8 -> 91.5 | 75 -> 48 | = |
| LDOS | 13 -> 7 | 93.8 -> 93.8 | 71 -> 56 | = |
| PNR | 14 -> 8 | 93.0 -> 93.0 | 42 -> 42 | = |
| APO | 15 -> 10 | 89.3 -> 89.3 | 84 -> 67 | = |
| EXE | 16 -> 11 | 89.3 -> 89.3 | 68 -> 52 | = |
| CEG | 17 -> 12 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 13 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 14 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 16 | 87.5 -> 87.5 | 88 -> 73 | = |
| EME | 21 -> 70 | 87.5 -> 53.5 | 58 -> 12 | wypada |
| FISV | 22 -> 17 | 87.5 -> 87.5 | 71 -> 69 | = |
| HII | 23 -> 21 | 87.5 -> 82.5 | 68 -> 44 | wypada |
| JBL | 24 -> 46 | 87.5 -> 61.2 | 64 -> 20 | wypada |
| PYPL | 27 -> 19 | 83.9 -> 83.9 | 39 -> 39 | wchodzi |
| CMCSA | 28 -> 20 | 83.3 -> 83.3 | 61 -> 61 | wchodzi |

**Ograniczenia i ryzyko:** Zaniża spółki o trwałym wysokim wzroście; liczba arbitralna.

## G3. Wygaszanie: start od obecnego wzrostu (max 20%), liniowo do 2,5% w roku 10

Zmienia tylko ścieżkę wzrostu w DCF (baza FCF = najnowszy rok, CAGR jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.866**
- TOP20: wypadają APP, DXCM, PNR, XYL; wchodzą CMCSA, FISV, HII, PYPL
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, XYL, PNR, EME, JBL; wchodzą CMCSA, PYPL
- DCF policzony: 120 -> 118 spółek; MoS>=50%: 24 -> 9; mediana MoS: -14.4 -> -53.8

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 23 | 100.0 -> 80.2 | 61 -> 28 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 66 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 64 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 100.0 | 77 -> 56 | = |
| DXCM | 6 -> 46 | 99.6 -> 61.3 | 50 -> 7 | wypada |
| QCOM | 7 -> 20 | 96.9 -> 81.7 | 47 -> 29 | = |
| MU | 8 -> 5 | 95.6 -> 94.6 | 72 -> 49 | = |
| SNDK | 9 -> 8 | 95.6 -> 93.3 | 71 -> 47 | = |
| XYL | 10 -> 53 | 95.3 -> 56.9 | 50 -> 6 | wypada |
| ADBE | 11 -> 14 | 93.8 -> 88.0 | 55 -> 44 | = |
| BKNG | 12 -> 6 | 93.8 -> 93.8 | 75 -> 54 | = |
| LDOS | 13 -> 7 | 93.8 -> 93.8 | 71 -> 53 | = |
| PNR | 14 -> 21 | 93.0 -> 81.5 | 42 -> 29 | wypada |
| APO | 15 -> 9 | 89.3 -> 89.3 | 84 -> 71 | = |
| EXE | 16 -> 13 | 89.3 -> 88.4 | 68 -> 49 | = |
| CEG | 17 -> 10 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 11 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 12 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 15 | 87.5 -> 87.5 | 88 -> 77 | = |
| EME | 21 -> 43 | 87.5 -> 63.6 | 58 -> 23 | wypada |
| FISV | 22 -> 16 | 87.5 -> 87.5 | 71 -> 58 | = |
| HII | 23 -> 18 | 87.5 -> 82.9 | 68 -> 45 | = |
| JBL | 24 -> 34 | 87.5 -> 70.9 | 64 -> 31 | wypada |
| PYPL | 27 -> 19 | 83.9 -> 82.4 | 39 -> 37 | wchodzi |
| CMCSA | 28 -> 17 | 83.3 -> 83.3 | 61 -> 60 | wchodzi |

**Ograniczenia i ryzyko:** Profil liniowy to założenie; nadal startuje od CAGR z dwóch punktów i od najnowszego FCF.

## G4. Wygaszanie od max 10%

Zmienia tylko ścieżkę wzrostu w DCF (baza FCF = najnowszy rok, CAGR jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.742**
- TOP20: wypadają APP, BKNG, DXCM, EXE, MU, SNDK, XYL; wchodzą ARES, CMCSA, F, FISV, FSLR, PYPL, RDDT
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, MU, SNDK, XYL, BKNG, EXE, EME, HII, JBL; wchodzą CMCSA, PYPL, ARES, FSLR, RDDT, F
- DCF policzony: 120 -> 118 spółek; MoS>=50%: 24 -> 5; mediana MoS: -14.4 -> -81.8

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 50 | 100.0 -> 55.6 | 61 -> -8 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 50 | = |
| INTU | 3 -> 3 | 100.0 -> 96.3 | 80 -> 46 | = |
| PODD | 4 -> 2 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 12 | 100.0 -> 85.2 | 77 -> 33 | = |
| DXCM | 6 -> 53 | 99.6 -> 55.6 | 50 -> -40 | wypada |
| QCOM | 7 -> 16 | 96.9 -> 80.8 | 47 -> 28 | = |
| MU | 8 -> 29 | 95.6 -> 73.0 | 72 -> 25 | wypada |
| SNDK | 9 -> 30 | 95.6 -> 70.8 | 71 -> 22 | wypada |
| XYL | 10 -> 77 | 95.3 -> 51.1 | 50 -> -41 | wypada |
| ADBE | 11 -> 8 | 93.8 -> 88.0 | 55 -> 44 | = |
| BKNG | 12 -> 21 | 93.8 -> 77.7 | 75 -> 32 | wypada |
| LDOS | 13 -> 11 | 93.8 -> 85.6 | 71 -> 41 | = |
| PNR | 14 -> 15 | 93.0 -> 81.5 | 42 -> 29 | = |
| APO | 15 -> 4 | 89.3 -> 89.3 | 84 -> 58 | = |
| EXE | 16 -> 26 | 89.3 -> 77.2 | 68 -> 36 | wypada |
| CEG | 17 -> 5 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 6 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 7 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 9 | 87.5 -> 87.5 | 88 -> 64 | = |
| EME | 21 -> 111 | 87.5 -> 43.1 | 58 -> -14 | wypada |
| FISV | 22 -> 10 | 87.5 -> 87.5 | 71 -> 56 | = |
| HII | 23 -> 37 | 87.5 -> 65.6 | 68 -> 25 | wypada |
| JBL | 24 -> 118 | 87.5 -> 43.1 | 64 -> -5 | wypada |
| PYPL | 27 -> 14 | 83.9 -> 82.4 | 39 -> 37 | wchodzi |
| CMCSA | 28 -> 13 | 83.3 -> 83.3 | 61 -> 60 | wchodzi |
| F | 36 -> 20 | 80.8 -> 79.0 | 63 -> 48 | wchodzi |
| ARES | 37 -> 17 | 80.8 -> 80.8 | — -> — | wchodzi |
| FSLR | 38 -> 18 | 80.0 -> 80.0 | — -> — | wchodzi |
| RDDT | 39 -> 19 | 80.0 -> 80.0 | — -> — | wchodzi |

**Ograniczenia i ryzyko:** Najbardziej konserwatywny wzrost; łączy dwie zmiany (sufit + profil).

## F1. Baza FCF = średnia z okna

Zmienia tylko bazę FCF w DCF; wzrost i CAGR jak w produkcji (DCF tylko tam, gdzie produkcja go liczy).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.855**
- TOP20: wypadają APP, DXCM, MU, PNR, SNDK, XYL; wchodzą CHRW, FISV, HII, IR, JBL, PYPL
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, MU, SNDK, XYL, PNR, EME; wchodzą CHRW, IR, PYPL
- DCF policzony: 120 -> 120 spółek; MoS>=50%: 24 -> 9; mediana MoS: -14.4 -> -54.1

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 51 | 100.0 -> 56.7 | 61 -> 1 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 72 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 70 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 100.0 | 77 -> 62 | = |
| DXCM | 6 -> 60 | 99.6 -> 55.6 | 50 -> -6 | wypada |
| QCOM | 7 -> 18 | 96.9 -> 82.2 | 47 -> 30 | = |
| MU | 8 -> 81 | 95.6 -> 51.1 | 72 -> -37 | wypada |
| SNDK | 9 -> 83 | 95.6 -> 51.1 | 71 -> -50 | wypada |
| XYL | 10 -> 30 | 95.3 -> 74.8 | 50 -> 27 | wypada |
| ADBE | 11 -> 11 | 93.8 -> 88.1 | 55 -> 44 | = |
| BKNG | 12 -> 5 | 93.8 -> 93.8 | 75 -> 66 | = |
| LDOS | 13 -> 6 | 93.8 -> 93.8 | 71 -> 56 | = |
| PNR | 14 -> 31 | 93.0 -> 73.8 | 42 -> 21 | wypada |
| APO | 15 -> 7 | 89.3 -> 89.3 | 84 -> 73 | = |
| EXE | 16 -> 14 | 89.3 -> 86.6 | 68 -> 47 | = |
| CEG | 17 -> 8 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 9 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 10 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 12 | 87.5 -> 87.5 | 88 -> 82 | = |
| EME | 21 -> 25 | 87.5 -> 77.5 | 58 -> 39 | wypada |
| FISV | 22 -> 13 | 87.5 -> 87.5 | 71 -> 66 | = |
| HII | 23 -> 17 | 87.5 -> 82.5 | 68 -> 44 | = |
| JBL | 24 -> 20 | 87.5 -> 81.2 | 64 -> 43 | = |
| IR | 25 -> 16 | 87.1 -> 84.3 | 56 -> 47 | wchodzi |
| CHRW | 26 -> 15 | 85.1 -> 85.1 | 66 -> 57 | wchodzi |
| PYPL | 27 -> 19 | 83.9 -> 81.2 | 39 -> 36 | wchodzi |

**Ograniczenia i ryzyko:** Zaniża spółki z trwałą poprawą (np. wzrost skali); okno 5 lat może nie obejmować pełnego cyklu.

## F2. Baza FCF = mediana z okna

Zmienia tylko bazę FCF w DCF; wzrost i CAGR jak w produkcji (DCF tylko tam, gdzie produkcja go liczy).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.838**
- TOP20: wypadają APP, DXCM, MU, PNR, XYL; wchodzą CHRW, FISV, HII, IR, JBL
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, MU, XYL, PNR, EME; wchodzą IR, CHRW
- DCF policzony: 120 -> 119 spółek; MoS>=50%: 24 -> 9; mediana MoS: -14.4 -> -58.2

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 57 | 100.0 -> 55.6 | 61 -> -48 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 78 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 65 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 100.0 | 77 -> 61 | = |
| DXCM | 6 -> 60 | 99.6 -> 55.6 | 50 -> -7 | wypada |
| QCOM | 7 -> 19 | 96.9 -> 82.1 | 47 -> 30 | = |
| MU | 8 -> 81 | 95.6 -> 51.1 | 72 -> -645 | wypada |
| SNDK | 9 -> 6 | 95.6 -> 92.0 | 71 -> — | = |
| XYL | 10 -> 39 | 95.3 -> 67.6 | 50 -> 19 | wypada |
| ADBE | 11 -> 15 | 93.8 -> 85.4 | 55 -> 41 | = |
| BKNG | 12 -> 5 | 93.8 -> 93.8 | 75 -> 68 | = |
| LDOS | 13 -> 7 | 93.8 -> 92.0 | 71 -> 48 | = |
| PNR | 14 -> 33 | 93.0 -> 72.4 | 42 -> 19 | wypada |
| APO | 15 -> 8 | 89.3 -> 89.3 | 84 -> 68 | = |
| EXE | 16 -> 20 | 89.3 -> 81.7 | 68 -> 41 | = |
| CEG | 17 -> 9 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 10 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 11 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 12 | 87.5 -> 87.5 | 88 -> 81 | = |
| EME | 21 -> 26 | 87.5 -> 78.0 | 58 -> 39 | wypada |
| FISV | 22 -> 13 | 87.5 -> 87.5 | 71 -> 66 | = |
| HII | 23 -> 18 | 87.5 -> 82.5 | 68 -> 44 | = |
| JBL | 24 -> 17 | 87.5 -> 83.6 | 64 -> 46 | = |
| IR | 25 -> 14 | 87.1 -> 87.1 | 56 -> 56 | wchodzi |
| CHRW | 26 -> 16 | 85.1 -> 85.1 | 66 -> 53 | wchodzi |

**Ograniczenia i ryzyko:** Jak F1; przy 5 punktach mediana bywa skokowa.

## F3. Baza FCF = mniejsza z: najnowszy, średnia

Zmienia tylko bazę FCF w DCF; wzrost i CAGR jak w produkcji (DCF tylko tam, gdzie produkcja go liczy).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.855**
- TOP20: wypadają APP, DXCM, MU, PNR, SNDK, XYL; wchodzą CHRW, FISV, HII, IR, JBL, PYPL
- Shortlista: 24 -> 20 spółek; wypadają APP, DXCM, MU, SNDK, XYL, PNR, EME; wchodzą CHRW, IR, PYPL
- DCF policzony: 120 -> 120 spółek; MoS>=50%: 24 -> 9; mediana MoS: -14.4 -> -55.4

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 51 | 100.0 -> 56.7 | 61 -> 1 | wypada |
| DECK | 2 -> 1 | 100.0 -> 100.0 | 81 -> 72 | = |
| INTU | 3 -> 2 | 100.0 -> 100.0 | 80 -> 70 | = |
| PODD | 4 -> 3 | 100.0 -> 100.0 | — -> — | = |
| TPR | 5 -> 4 | 100.0 -> 100.0 | 77 -> 62 | = |
| DXCM | 6 -> 60 | 99.6 -> 55.6 | 50 -> -6 | wypada |
| QCOM | 7 -> 18 | 96.9 -> 82.2 | 47 -> 30 | = |
| MU | 8 -> 81 | 95.6 -> 51.1 | 72 -> -37 | wypada |
| SNDK | 9 -> 83 | 95.6 -> 51.1 | 71 -> -50 | wypada |
| XYL | 10 -> 30 | 95.3 -> 74.8 | 50 -> 27 | wypada |
| ADBE | 11 -> 11 | 93.8 -> 88.1 | 55 -> 44 | = |
| BKNG | 12 -> 5 | 93.8 -> 93.8 | 75 -> 66 | = |
| LDOS | 13 -> 6 | 93.8 -> 93.8 | 71 -> 56 | = |
| PNR | 14 -> 31 | 93.0 -> 73.8 | 42 -> 21 | wypada |
| APO | 15 -> 7 | 89.3 -> 89.3 | 84 -> 73 | = |
| EXE | 16 -> 14 | 89.3 -> 86.6 | 68 -> 47 | = |
| CEG | 17 -> 8 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 9 | 88.8 -> 88.8 | — -> — | = |
| UBER | 19 -> 10 | 88.8 -> 88.8 | — -> — | = |
| APTV | 20 -> 12 | 87.5 -> 87.5 | 88 -> 82 | = |
| EME | 21 -> 25 | 87.5 -> 77.5 | 58 -> 39 | wypada |
| FISV | 22 -> 13 | 87.5 -> 87.5 | 71 -> 66 | = |
| HII | 23 -> 17 | 87.5 -> 82.5 | 68 -> 44 | = |
| JBL | 24 -> 20 | 87.5 -> 81.2 | 64 -> 43 | = |
| IR | 25 -> 16 | 87.1 -> 84.3 | 56 -> 47 | wchodzi |
| CHRW | 26 -> 15 | 85.1 -> 85.1 | 66 -> 57 | wchodzi |
| PYPL | 27 -> 19 | 83.9 -> 81.2 | 39 -> 36 | wchodzi |

**Ograniczenia i ryzyko:** Systematycznie konserwatywne; asymetrycznie karze spółki rosnące.

## D1. Bez punktów za 'brak cięcia' i 'bezpieczny payout' przy zerowej dywidendzie

Spółka z DPS = 0 traci 3 + 2 pkt, jeśli je dostawała.

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.944**
- TOP20: wypadają ADBE, APTV, NFLX, PODD, UBER; wchodzą CHRW, EME, HII, IR, JBL
- Shortlista: 24 -> 20 spółek; wypadają PODD, ADBE, NFLX, UBER, APTV, FISV; wchodzą IR, CHRW

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 11 | 100.0 -> 88.9 | = |
| DECK | 2 -> 12 | 100.0 -> 88.9 | = |
| INTU | 3 -> 1 | 100.0 -> 100.0 | = |
| PODD | 4 -> 29 | 100.0 -> 80.0 | wypada |
| TPR | 5 -> 2 | 100.0 -> 100.0 | = |
| DXCM | 6 -> 14 | 99.6 -> 88.5 | = |
| QCOM | 7 -> 3 | 96.9 -> 96.9 | = |
| MU | 8 -> 4 | 95.6 -> 95.6 | = |
| SNDK | 9 -> 20 | 95.6 -> 84.4 | = |
| XYL | 10 -> 5 | 95.3 -> 95.3 | = |
| ADBE | 11 -> 25 | 93.8 -> 82.6 | wypada |
| BKNG | 12 -> 6 | 93.8 -> 93.8 | = |
| LDOS | 13 -> 7 | 93.8 -> 93.8 | = |
| PNR | 14 -> 8 | 93.0 -> 93.0 | = |
| APO | 15 -> 9 | 89.3 -> 89.3 | = |
| EXE | 16 -> 10 | 89.3 -> 89.3 | = |
| CEG | 17 -> 13 | 88.8 -> 88.8 | = |
| NFLX | 18 -> 54 | 88.8 -> 68.8 | wypada |
| UBER | 19 -> 55 | 88.8 -> 68.8 | wypada |
| APTV | 20 -> 36 | 87.5 -> 76.4 | wypada |
| EME | 21 -> 15 | 87.5 -> 87.5 | = |
| FISV | 22 -> 37 | 87.5 -> 76.4 | wypada |
| HII | 23 -> 16 | 87.5 -> 87.5 | = |
| JBL | 24 -> 17 | 87.5 -> 87.5 | = |
| IR | 25 -> 18 | 87.1 -> 87.1 | wchodzi |
| CHRW | 26 -> 19 | 85.1 -> 85.1 | wchodzi |

**Ograniczenia i ryzyko:** Karze spółki wzrostowe zwracające gotówkę wyłącznie buybackiem; DPS = 0 z FMP może też być brakiem danych.

## D2. Kryteria dywidendowe 'nie dotyczy' przy zerowej dywidendzie (komponent liczony z 5 pkt i skalowany do 10)

Yield (3) + liczba akcji (2) przeskalowane do 10.

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.986**
- TOP20: wypadają brak; wchodzą brak
- Shortlista: 24 -> 24 spółek; wypadają brak; wchodzą brak

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | = |
| PODD | 4 -> 4 | 100.0 -> 100.0 | = |
| TPR | 5 -> 5 | 100.0 -> 100.0 | = |
| DXCM | 6 -> 6 | 99.6 -> 99.6 | = |
| QCOM | 7 -> 7 | 96.9 -> 96.9 | = |
| MU | 8 -> 8 | 95.6 -> 95.6 | = |
| SNDK | 9 -> 14 | 95.6 -> 91.1 | = |
| XYL | 10 -> 9 | 95.3 -> 95.3 | = |
| ADBE | 11 -> 10 | 93.8 -> 93.8 | = |
| BKNG | 12 -> 11 | 93.8 -> 93.8 | = |
| LDOS | 13 -> 12 | 93.8 -> 93.8 | = |
| PNR | 14 -> 13 | 93.0 -> 93.0 | = |
| APO | 15 -> 15 | 89.3 -> 89.3 | = |
| EXE | 16 -> 16 | 89.3 -> 89.3 | = |
| CEG | 17 -> 17 | 88.8 -> 88.8 | = |
| NFLX | 18 -> 18 | 88.8 -> 88.8 | = |
| UBER | 19 -> 19 | 88.8 -> 88.8 | = |
| APTV | 20 -> 20 | 87.5 -> 87.5 | = |
| EME | 21 -> 21 | 87.5 -> 87.5 | = |
| FISV | 22 -> 22 | 87.5 -> 87.5 | = |
| HII | 23 -> 23 | 87.5 -> 87.5 | = |
| JBL | 24 -> 24 | 87.5 -> 87.5 | = |

**Ograniczenia i ryzyko:** Ten sam problem mieszania baz co w punkcie 4, tylko wewnątrz komponentu; spółka z buybackiem i malejącą liczbą akcji nadal 10/10.

## B1. Brak wyceny = 0 z 20 pkt (wynik z 45)

Brak DCF traktowany jak najgorsza wycena.

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.783**
- TOP20: wypadają CEG, NFLX, PODD, UBER; wchodzą EME, FISV, HII, JBL
- Shortlista: 24 -> 20 spółek; wypadają PODD, CEG, NFLX, UBER; wchodzą brak

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | = |
| PODD | 4 -> 64 | 100.0 -> 55.6 | wypada |
| TPR | 5 -> 4 | 100.0 -> 100.0 | = |
| DXCM | 6 -> 5 | 99.6 -> 99.6 | = |
| QCOM | 7 -> 6 | 96.9 -> 96.9 | = |
| MU | 8 -> 7 | 95.6 -> 95.6 | = |
| SNDK | 9 -> 8 | 95.6 -> 95.6 | = |
| XYL | 10 -> 9 | 95.3 -> 95.3 | = |
| ADBE | 11 -> 10 | 93.8 -> 93.8 | = |
| BKNG | 12 -> 11 | 93.8 -> 93.8 | = |
| LDOS | 13 -> 12 | 93.8 -> 93.8 | = |
| PNR | 14 -> 13 | 93.0 -> 93.0 | = |
| APO | 15 -> 14 | 89.3 -> 89.3 | = |
| EXE | 16 -> 15 | 89.3 -> 89.3 | = |
| CEG | 17 -> 76 | 88.8 -> 49.3 | wypada |
| NFLX | 18 -> 82 | 88.8 -> 49.3 | wypada |
| UBER | 19 -> 84 | 88.8 -> 49.3 | wypada |
| APTV | 20 -> 16 | 87.5 -> 87.5 | = |
| EME | 21 -> 17 | 87.5 -> 87.5 | = |
| FISV | 22 -> 18 | 87.5 -> 87.5 | = |
| HII | 23 -> 19 | 87.5 -> 87.5 | = |
| JBL | 24 -> 20 | 87.5 -> 87.5 | = |

**Ograniczenia i ryzyko:** Karze uzasadniony brak DCF (np. spółki odbudowujące FCF) tak samo jak przewartościowanie.

## B2. Brak wyceny = połowa punktów (10 z 20)

Neutralne uzupełnienie.

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.985**
- TOP20: wypadają CEG, NFLX, PODD, UBER; wchodzą EME, FISV, HII, JBL
- Shortlista: 24 -> 20 spółek; wypadają PODD, CEG, NFLX, UBER; wchodzą brak

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | = |
| PODD | 4 -> 34 | 100.0 -> 77.8 | wypada |
| TPR | 5 -> 4 | 100.0 -> 100.0 | = |
| DXCM | 6 -> 5 | 99.6 -> 99.6 | = |
| QCOM | 7 -> 6 | 96.9 -> 96.9 | = |
| MU | 8 -> 7 | 95.6 -> 95.6 | = |
| SNDK | 9 -> 8 | 95.6 -> 95.6 | = |
| XYL | 10 -> 9 | 95.3 -> 95.3 | = |
| ADBE | 11 -> 10 | 93.8 -> 93.8 | = |
| BKNG | 12 -> 11 | 93.8 -> 93.8 | = |
| LDOS | 13 -> 12 | 93.8 -> 93.8 | = |
| PNR | 14 -> 13 | 93.0 -> 93.0 | = |
| APO | 15 -> 14 | 89.3 -> 89.3 | = |
| EXE | 16 -> 15 | 89.3 -> 89.3 | = |
| CEG | 17 -> 46 | 88.8 -> 71.5 | wypada |
| NFLX | 18 -> 47 | 88.8 -> 71.5 | wypada |
| UBER | 19 -> 48 | 88.8 -> 71.5 | wypada |
| APTV | 20 -> 16 | 87.5 -> 87.5 | = |
| EME | 21 -> 17 | 87.5 -> 87.5 | = |
| FISV | 22 -> 18 | 87.5 -> 87.5 | = |
| HII | 23 -> 19 | 87.5 -> 87.5 | = |
| JBL | 24 -> 20 | 87.5 -> 87.5 | = |

**Ograniczenia i ryzyko:** Wartość 10/20 jest arbitralna.

## B3. Najpierw spółki z pełną bazą (z DCF), potem bez DCF

Ta sama zasada co w finalnym rankingu (complete przed partial).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.628**
- TOP20: wypadają CEG, NFLX, PODD, UBER; wchodzą EME, FISV, HII, JBL
- Shortlista: 24 -> 20 spółek; wypadają PODD, CEG, NFLX, UBER; wchodzą brak

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 1100.0 | = |
| DECK | 2 -> 2 | 100.0 -> 1100.0 | = |
| INTU | 3 -> 3 | 100.0 -> 1100.0 | = |
| PODD | 4 -> 121 | 100.0 -> 100.0 | wypada |
| TPR | 5 -> 4 | 100.0 -> 1100.0 | = |
| DXCM | 6 -> 5 | 99.6 -> 1099.6 | = |
| QCOM | 7 -> 6 | 96.9 -> 1096.9 | = |
| MU | 8 -> 7 | 95.6 -> 1095.6 | = |
| SNDK | 9 -> 8 | 95.6 -> 1095.6 | = |
| XYL | 10 -> 9 | 95.3 -> 1095.3 | = |
| ADBE | 11 -> 10 | 93.8 -> 1093.8 | = |
| BKNG | 12 -> 11 | 93.8 -> 1093.8 | = |
| LDOS | 13 -> 12 | 93.8 -> 1093.8 | = |
| PNR | 14 -> 13 | 93.0 -> 1093.0 | = |
| APO | 15 -> 14 | 89.3 -> 1089.3 | = |
| EXE | 16 -> 15 | 89.3 -> 1089.3 | = |
| CEG | 17 -> 122 | 88.8 -> 88.8 | wypada |
| NFLX | 18 -> 123 | 88.8 -> 88.8 | wypada |
| UBER | 19 -> 124 | 88.8 -> 88.8 | wypada |
| APTV | 20 -> 16 | 87.5 -> 1087.5 | = |
| EME | 21 -> 17 | 87.5 -> 1087.5 | = |
| FISV | 22 -> 18 | 87.5 -> 1087.5 | = |
| HII | 23 -> 19 | 87.5 -> 1087.5 | = |
| JBL | 24 -> 20 | 87.5 -> 1087.5 | = |

**Ograniczenia i ryzyko:** Spółki bez DCF praktycznie nie trafiają na shortlistę, dopóki jest >=20 spółek z DCF.

## B4. Bez komponentu wyceny (bezpieczeństwo + dywidendy, z 25 pkt)

Odpowiednik modelu 'BEZ wyceny' z testu historycznego.

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.483**
- TOP20: wypadają ADBE, APO, APTV, BKNG, CEG, EXE, LDOS, MU, NFLX, PNR, PODD, QCOM, SNDK, TPR, UBER, XYL; wchodzą ADI, ALLE, AMAT, AMD, ANET, CDNS, CIEN, CPRT, GL, HWM, KEYS, KLAC, LRCX, META, MPWR, MRK
- Shortlista: 24 -> 27 spółek; wypadają MU, SNDK, XYL, ADBE, BKNG, LDOS, APO, EXE, CEG, NFLX, UBER, APTV, EME, FISV, HII, JBL; wchodzą ADI, ALLE, AMAT, AMD, ANET, CDNS, CIEN, CPRT, GL, HWM, KEYS, KLAC, LRCX, META, MPWR, MRK, SNA, TER, ZTS

| Spółka | Pozycja | Wynik % | Shortlista |
|---|---|---|---|
| APP | 1 -> 6 | 100.0 -> 100.0 | = |
| DECK | 2 -> 10 | 100.0 -> 100.0 | = |
| INTU | 3 -> 14 | 100.0 -> 100.0 | = |
| PODD | 4 -> 22 | 100.0 -> 100.0 | = |
| TPR | 5 -> 26 | 100.0 -> 100.0 | = |
| DXCM | 6 -> 11 | 99.6 -> 100.0 | = |
| QCOM | 7 -> 23 | 96.9 -> 100.0 | = |
| MU | 8 -> 35 | 95.6 -> 92.0 | wypada |
| SNDK | 9 -> 37 | 95.6 -> 92.0 | wypada |
| XYL | 10 -> 41 | 95.3 -> 92.0 | wypada |
| ADBE | 11 -> 42 | 93.8 -> 88.8 | wypada |
| BKNG | 12 -> 44 | 93.8 -> 88.8 | wypada |
| LDOS | 13 -> 52 | 93.8 -> 88.8 | wypada |
| PNR | 14 -> 21 | 93.0 -> 100.0 | = |
| APO | 15 -> 64 | 89.3 -> 80.8 | wypada |
| EXE | 16 -> 67 | 89.3 -> 80.8 | wypada |
| CEG | 17 -> 45 | 88.8 -> 88.8 | wypada |
| NFLX | 18 -> 55 | 88.8 -> 88.8 | wypada |
| UBER | 19 -> 60 | 88.8 -> 88.8 | wypada |
| APTV | 20 -> 76 | 87.5 -> 77.5 | wypada |
| EME | 21 -> 79 | 87.5 -> 77.5 | wypada |
| FISV | 22 -> 82 | 87.5 -> 77.5 | wypada |
| HII | 23 -> 86 | 87.5 -> 77.5 | wypada |
| JBL | 24 -> 89 | 87.5 -> 77.5 | wypada |
| CPRT | 33 -> 9 | 81.6 -> 100.0 | wchodzi |
| ALLE | 49 -> 2 | 74.7 -> 100.0 | wchodzi |
| ZTS | 59 -> 27 | 70.5 -> 100.0 | wchodzi |
| ANET | 65 -> 5 | 67.6 -> 100.0 | wchodzi |
| HWM | 69 -> 13 | 59.3 -> 100.0 | wchodzi |
| ADI | 76 -> 1 | 55.6 -> 100.0 | wchodzi |
| AMAT | 77 -> 3 | 55.6 -> 100.0 | wchodzi |
| AMD | 78 -> 4 | 55.6 -> 100.0 | wchodzi |
| CDNS | 79 -> 7 | 55.6 -> 100.0 | wchodzi |
| CIEN | 80 -> 8 | 55.6 -> 100.0 | wchodzi |
| GL | 81 -> 12 | 55.6 -> 100.0 | wchodzi |
| KEYS | 82 -> 15 | 55.6 -> 100.0 | wchodzi |
| KLAC | 83 -> 16 | 55.6 -> 100.0 | wchodzi |
| LRCX | 84 -> 17 | 55.6 -> 100.0 | wchodzi |
| META | 85 -> 18 | 55.6 -> 100.0 | wchodzi |
| MPWR | 86 -> 19 | 55.6 -> 100.0 | wchodzi |
| MRK | 87 -> 20 | 55.6 -> 100.0 | wchodzi |
| SNA | 88 -> 24 | 55.6 -> 100.0 | wchodzi |
| TER | 89 -> 25 | 55.6 -> 100.0 | wchodzi |

**Ograniczenia i ryzyko:** Porzuca wycenę -- sprzeczne z filozofią Buffetta; sam test historyczny ma ograniczenia (sekcja walidacji).

## C1. CAGR od pierwszego dodatniego roku (min. 2 lata)

Zmienia tylko sposób liczenia wzrostu historycznego (sufit 20% i baza FCF jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.949**
- TOP20: wypadają brak; wchodzą brak
- Shortlista: 24 -> 25 spółek; wypadają brak; wchodzą TMUS
- DCF policzony: 120 -> 131 spółek; MoS>=50%: 24 -> 28; mediana MoS: -14.4 -> -8.9

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | 61 -> 61 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | 81 -> 81 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | 80 -> 80 | = |
| PODD | 4 -> 4 | 100.0 -> 100.0 | — -> 51 | = |
| TPR | 5 -> 5 | 100.0 -> 100.0 | 77 -> 77 | = |
| DXCM | 6 -> 6 | 99.6 -> 99.6 | 50 -> 50 | = |
| QCOM | 7 -> 7 | 96.9 -> 96.9 | 47 -> 47 | = |
| MU | 8 -> 8 | 95.6 -> 95.6 | 72 -> 72 | = |
| SNDK | 9 -> 9 | 95.6 -> 95.6 | 71 -> 71 | = |
| XYL | 10 -> 10 | 95.3 -> 95.3 | 50 -> 50 | = |
| ADBE | 11 -> 11 | 93.8 -> 93.8 | 55 -> 55 | = |
| BKNG | 12 -> 12 | 93.8 -> 93.8 | 75 -> 75 | = |
| LDOS | 13 -> 13 | 93.8 -> 93.8 | 71 -> 71 | = |
| PNR | 14 -> 15 | 93.0 -> 93.0 | 42 -> 42 | = |
| APO | 15 -> 17 | 89.3 -> 89.3 | 84 -> 84 | = |
| EXE | 16 -> 18 | 89.3 -> 89.3 | 68 -> 68 | = |
| CEG | 17 -> 19 | 88.8 -> 88.8 | — -> — | = |
| NFLX | 18 -> 16 | 88.8 -> 91.5 | — -> 48 | = |
| UBER | 19 -> 14 | 88.8 -> 93.8 | — -> 74 | = |
| APTV | 20 -> 20 | 87.5 -> 87.5 | 88 -> 88 | = |
| EME | 21 -> 21 | 87.5 -> 87.5 | 58 -> 58 | = |
| FISV | 22 -> 22 | 87.5 -> 87.5 | 71 -> 71 | = |
| HII | 23 -> 23 | 87.5 -> 87.5 | 68 -> 68 | = |
| JBL | 24 -> 24 | 87.5 -> 87.5 | 64 -> 64 | = |
| TMUS | 43 -> 25 | 77.5 -> 87.5 | — -> 77 | wchodzi |

**Ograniczenia i ryzyko:** Nadal dwa punkty końcowe; start z niskiej bazy daje bardzo wysoki CAGR (sufit 20% to tłumi).

## C2. Trend log-liniowy z lat dodatnich (min. 3 lata)

Zmienia tylko sposób liczenia wzrostu historycznego (sufit 20% i baza FCF jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.873**
- TOP20: wypadają APO, APTV, CEG, EXE; wchodzą LII, LULU, PYPL, ZTS
- Shortlista: 24 -> 20 spółek; wypadają APO, EXE, CEG, APTV, EME, FISV, HII, JBL; wchodzą LII, ZTS, LULU, PYPL
- DCF policzony: 120 -> 128 spółek; MoS>=50%: 24 -> 30; mediana MoS: -14.4 -> -4.4

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | 61 -> 61 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | 81 -> 81 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | 80 -> 80 | = |
| PODD | 4 -> 5 | 100.0 -> 100.0 | — -> 51 | = |
| TPR | 5 -> 7 | 100.0 -> 100.0 | 77 -> 77 | = |
| DXCM | 6 -> 8 | 99.6 -> 99.6 | 50 -> 50 | = |
| QCOM | 7 -> 6 | 96.9 -> 100.0 | 47 -> 59 | = |
| MU | 8 -> 10 | 95.6 -> 95.6 | 72 -> 72 | = |
| SNDK | 9 -> 19 | 95.6 -> 92.0 | 71 -> — | = |
| XYL | 10 -> 11 | 95.3 -> 95.3 | 50 -> 50 | = |
| ADBE | 11 -> 13 | 93.8 -> 93.8 | 55 -> 51 | = |
| BKNG | 12 -> 14 | 93.8 -> 93.8 | 75 -> 75 | = |
| LDOS | 13 -> 15 | 93.8 -> 93.8 | 71 -> 73 | = |
| PNR | 14 -> 4 | 93.0 -> 100.0 | 42 -> 71 | = |
| APO | 15 -> 23 | 89.3 -> 89.3 | 84 -> 84 | wypada |
| EXE | 16 -> 116 | 89.3 -> 44.9 | 68 -> -82 | wypada |
| CEG | 17 -> 24 | 88.8 -> 88.8 | — -> — | wypada |
| NFLX | 18 -> 20 | 88.8 -> 91.5 | — -> 48 | = |
| UBER | 19 -> 17 | 88.8 -> 93.8 | — -> 74 | = |
| APTV | 20 -> 25 | 87.5 -> 87.5 | 88 -> 88 | wypada |
| EME | 21 -> 26 | 87.5 -> 87.5 | 58 -> 58 | wypada |
| FISV | 22 -> 27 | 87.5 -> 87.5 | 71 -> 78 | wypada |
| HII | 23 -> 126 | 87.5 -> 43.1 | 68 -> -127 | wypada |
| JBL | 24 -> 29 | 87.5 -> 87.5 | 64 -> 64 | wypada |
| PYPL | 27 -> 18 | 83.9 -> 92.6 | 39 -> 49 | wchodzi |
| LII | 47 -> 9 | 75.8 -> 95.8 | 27 -> 63 | wchodzi |
| ZTS | 59 -> 12 | 70.5 -> 94.3 | 17 -> 44 | wchodzi |
| LULU | 108 -> 16 | 49.3 -> 93.8 | -18 -> 68 | wchodzi |

**Ograniczenia i ryzyko:** Pomija lata ujemne (optymistyczne); 3-5 punktów to mała próbka.

## C3. Mediana wzrostu r/r z par dodatnich lat (min. 2 pary)

Zmienia tylko sposób liczenia wzrostu historycznego (sufit 20% i baza FCF jak w produkcji).

- Spearman (cały ranking 162 spółek, produkcja vs wariant): **0.789**
- TOP20: wypadają APO, APTV, CEG, EXE, NFLX; wchodzą ALLE, COIN, DPZ, LII, ON
- Shortlista: 24 -> 20 spółek; wypadają APO, EXE, CEG, NFLX, APTV, EME, FISV, HII, JBL; wchodzą LII, ON, COIN, DPZ, ALLE
- DCF policzony: 120 -> 124 spółek; MoS>=50%: 24 -> 34; mediana MoS: -14.4 -> 1.9

| Spółka | Pozycja | Wynik % | MoS BASE % | Shortlista |
|---|---|---|---|---|
| APP | 1 -> 1 | 100.0 -> 100.0 | 61 -> 61 | = |
| DECK | 2 -> 2 | 100.0 -> 100.0 | 81 -> 81 | = |
| INTU | 3 -> 3 | 100.0 -> 100.0 | 80 -> 80 | = |
| PODD | 4 -> 5 | 100.0 -> 100.0 | — -> 51 | = |
| TPR | 5 -> 7 | 100.0 -> 100.0 | 77 -> 77 | = |
| DXCM | 6 -> 8 | 99.6 -> 99.6 | 50 -> 50 | = |
| QCOM | 7 -> 6 | 96.9 -> 100.0 | 47 -> 60 | = |
| MU | 8 -> 12 | 95.6 -> 95.6 | 72 -> 72 | = |
| SNDK | 9 -> 20 | 95.6 -> 92.0 | 71 -> — | = |
| XYL | 10 -> 13 | 95.3 -> 95.3 | 50 -> 50 | = |
| ADBE | 11 -> 14 | 93.8 -> 93.8 | 55 -> 59 | = |
| BKNG | 12 -> 15 | 93.8 -> 93.8 | 75 -> 62 | = |
| LDOS | 13 -> 17 | 93.8 -> 93.8 | 71 -> 80 | = |
| PNR | 14 -> 4 | 93.0 -> 100.0 | 42 -> 74 | = |
| APO | 15 -> 23 | 89.3 -> 89.3 | 84 -> 84 | wypada |
| EXE | 16 -> 24 | 89.3 -> 89.3 | 68 -> 78 | wypada |
| CEG | 17 -> 25 | 88.8 -> 88.8 | — -> — | wypada |
| NFLX | 18 -> 21 | 88.8 -> 91.5 | — -> 48 | wypada |
| UBER | 19 -> 18 | 88.8 -> 93.8 | — -> 74 | = |
| APTV | 20 -> 26 | 87.5 -> 87.5 | 88 -> 88 | wypada |
| EME | 21 -> 27 | 87.5 -> 87.5 | 58 -> 58 | wypada |
| FISV | 22 -> 30 | 87.5 -> 87.5 | 71 -> 80 | wypada |
| HII | 23 -> 31 | 87.5 -> 87.5 | 68 -> 75 | wypada |
| JBL | 24 -> 32 | 87.5 -> 87.5 | 64 -> 64 | wypada |
| LII | 47 -> 9 | 75.8 -> 95.8 | 27 -> 63 | wchodzi |
| ALLE | 49 -> 19 | 74.7 -> 93.1 | 22 -> 42 | wchodzi |
| ON | 92 -> 10 | 51.4 -> 95.8 | -44 -> 63 | wchodzi |
| COIN | 94 -> 11 | 51.1 -> 95.6 | -91 -> 67 | wchodzi |
| DPZ | 106 -> 16 | 49.3 -> 93.8 | -42 -> 53 | wchodzi |

**Ograniczenia i ryzyko:** Niestabilna przy małej liczbie par; ignoruje lata ujemne.

## MU i SNDK — MoS BASE w każdym wariancie DCF

| Wariant | MU | SNDK |
|---|---|---|
| Produkcja | 72 | 71 |
| G1. Sufit wzrostu 15% | 60 | 58 |
| G2. Sufit wzrostu 10% | 41 | 40 |
| G3. Wygaszanie: start od obecnego wzrostu (max 20%), liniowo do 2,5% w roku 10 | 49 | 47 |
| G4. Wygaszanie od max 10% | 25 | 22 |
| F1. Baza FCF = średnia z okna | -37 | -50 |
| F2. Baza FCF = mediana z okna | -645 | — |
| F3. Baza FCF = mniejsza z: najnowszy, średnia | -37 | -50 |
