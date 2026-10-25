# Skan 23.10 — korekta kontroli dywidend uprzywilejowanych (2026-10-25)

Skan: `live-scan-2026-10-24T220005090685Z` (run 40136571596). Diagnostyka: run 40180283457 (SEC + FMP, bez Claude). Przeliczenie: run 40181315863 (bez Claude), baza w artefakcie `phase6-live-scan-result` tego runu. Oryginalny artefakt skanu jest nietknięty.

## Przyczyny (potwierdzone danymi SEC i FMP)

1. **Fałszywy ślad akcji uprzywilejowanych z FMP.**
   - Pole `netPreferredStockIssuance` jest niezerowe u spółek, które według SEC nie mają akcji uprzywilejowanych (`PreferredStockValue = 0`):
     - QCOM FY2023: −955 mln;
     - JBL: −44 / +51 mln;
     - CHRW: −27 / −28 mln;
     - DPZ: +20 mln.
   - Ślad przechodził na wszystkie późniejsze lata. SEC nie podaje tagu dla wypłat na akcje zwykłe, więc wynik brzmiał NIEZNANE.
   - QCOM: 2 zamiast 10 punktów za dywidendy, pozycja 36 zamiast 9.
   - Poprawka: emisja z FMP nie jest śladem. Śladem pozostają: wypłaty dywidend uprzywilejowanych (FMP lub SEC) oraz saldo akcji uprzywilejowanych w SEC > 0. BA FY2025 nadal NIEZNANE (SEC: dywidendy uprzywilejowane 345 mln).
2. **Przesunięcie CRH: dywidendy zadeklarowane zamiast wypłaconych.**
   - Korekta używała też tagów SEC dla dywidend zadeklarowanych (`DividendsCommonStock`, `DividendsCommonStockCash`).
   - CRH 2023/2024: zadeklarowane 1688/956 mln, wypłacone według FMP 851/1706 mln.
   - Poprawka: tylko `PaymentsOfDividendsCommonStock` (wypłaty), tak jak backtest.
   - Skutek: spółki z rzeczywistymi akcjami uprzywilejowanymi i bez tego tagu mają teraz dywidendy NIEZNANE zamiast zastępczej kwoty: CRH, HWM, GLW (2021), PCG (2025).

## Wpływ na ranking (te same funkcje co skan; punktacja i reguły bez zmian)

| Spółka | Przed | Po |
|---|---|---|
| QCOM | 78,29% (36) | 96,07% (9) — **wchodzi do TOP 20** |
| JBL | 69,72% | 87,50% (22=, poza TOP 20) |
| CHRW | 67,36% | 85,14% (28) |
| SBAC | 45,50% | 77,50% (41=) |
| DPZ | 31,53% | 49,31% |
| HWM / CRH / PCG | 62,55 / 49,31 / 39,00% | 44,78 / 31,53 / 15,00% (dywidendy NIEZNANE) |

- Shortlista: 21 spółek. Dochodzi QCOM, nikt nie wypada, remis 19= (CEG, NFLX, UBER) zostaje na granicy.
- 20 gotowych analiz Claude: wyniki bez zmian (polecenie zatrzymałoby się, gdyby wynik spółki z gotową analizą się zmienił).
- TOP 5: nieznane do czasu analizy QCOM. QCOM wejdzie do TOP 5 tylko wtedy, gdy jego pełny wynik przekroczy 77,2 (BKNG).

## Jak uzyskać poprawny wynik

Wznowienie `phase6b` z bazy runu 40181315863: Claude analizuje wyłącznie QCOM (status PENDING).
- Koszt: około 0,10 USD (zakres pojedynczej analizy w skanie: 0,074–0,134 USD).
- Twardy limit: 3 wywołania (najgorszy przypadek: 1 analiza + 2 naprawy, około 0,5 USD).
- Wymaga zgody właścicielki. Publikacja tylko po osobnej zgodzie.
