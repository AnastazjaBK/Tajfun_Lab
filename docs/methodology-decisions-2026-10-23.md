# Poprawki błędów logicznych i propozycje do decyzji — 2026-10-23

Status:
- **Poprawki 1–4 wdrożone w kodzie gałęzi roboczej, z testami regresyjnymi. Nieużyte w żadnym skanie.**
- **Propozycje A–C: niewdrożone, do akceptacji.**
- Wagi i parametry inwestycyjne bez zmian.

## 1. Poprawki błędów logicznych

| Nr | Błąd | Poprawka | Testy (`tests/test_logic_fixes_2026_10_23.py`) |
|---|---|---|---|
| 1 | Skan na żywo dawał wszystkim profil GENERAL | Profil z kodu SIC, ta sama funkcja co w backteście (`classify_sic_to_sector_profile`), dla spółek wchodzących do rankingu. **Błąd SEC → spółka poza rankingiem z przyczyną w raporcie (nie GENERAL)**; powyżej 5% takich spółek skan stop przed Claude. Brak kodu SIC w SEC → GENERAL jak w backteście, z ostrzeżeniem. | ubezpieczyciel bez DCF; błąd SEC nigdy nie daje GENERAL; brak SIC raportowany |
| 2 | CAPEX = 0 z FMP traktowany jako prawdziwe zero | Weryfikacja w SEC XBRL (roczny fakt dla tego samego okresu, złożony najpóźniej w dniu sesji). Stany: **POTWIERDZONE_ZERO** (SEC = 0) → zostaje 0; **PODEJRZANE** (SEC > 0 albo spółka operacyjna bez potwierdzenia) → brak danych, oryginał w raporcie; **NIEZWERYFIKOWANE_PRZYJĘTE** (bank/ubezpieczyciel/REIT bez faktu w SEC) → 0 z oznaczeniem. „Brak danych” z FMP bez zmian. | stany; dopasowanie okresu ±7 dni i dnia sesji; trzy scenariusze w pełnym skanie |
| 3 | Komunikat „potrzeba ≥2 okresów z dodatnim FCF” | Komunikat opisuje rzeczywistą regułę: CAGR tylko między pierwszym a ostatnim okresem, oba dodatnie; podaje FCF pierwszego okresu; lata pośrednie nie są brane pod uwagę. | treść komunikatu |
| 4 | Remis rozstrzygany alfabetem i pokazywany jako pozycja | Pozycje ex aequo (1, 1, 1, 4, …) w bazie i raporcie, znacznik „=”; kolejność w obrębie remisu (ticker) tylko do wyświetlania. Shortlista jak dotąd obejmuje cały remis na granicy. | wspólna pozycja w bazie i tabeli |

Pełny zestaw testów: zielony (wynik w podsumowaniu commita).

### Wpływ na dane z 22.10 (kod produkcyjny po poprawkach)

**Założenia:**
- Kody SIC: GL 6311 → INSURER, ARE 6798 → REIT, WY 6798 → REIT, APO 6282 → GENERAL. Źródła wtórne (wyszukiwarka), bo SEC jest niedostępny z tego środowiska.
- Pozostałe 7 spółek finansowych i nieruchomościowych przyjęte jako GENERAL bez weryfikacji. Pełny skan pobierze kody z SEC.
- Faktów CAPEX z SEC nie da się stąd pobrać, więc dla APO policzone dwa scenariusze.

| | Scenariusz A: SEC potwierdza CAPEX APO = 0 | Scenariusz B: CAPEX APO podejrzany |
|---|---|---|
| Shortlista | 24 → 20 | 24 → 24 |
| Wypadają | APTV, EME, FISV, HII, JBL | APO (pozycja 15 → 99, wynik 89,3% → 50,2%) |
| Wchodzą | **GL** | **GL** |
| Remisy | 6 spółek na pozycji 1= (APP, DECK, GL, INTU, PODD, TPR) | jak A |

**Najważniejsze: poprawka 1 uruchamia problem z punktu 3.**
- GL (ubezpieczyciel) zgodnie z konfiguracją traci DCF. Przy obecnej renormalizacji jego wynik rośnie z 55,6% (pozycja 81) do 100% (pozycja 1=).
- To jest dokładnie „sztuczna przewaga przez normalizację”.
- **Rekomendacja: nie uruchamiać skanu z poprawką 1, dopóki nie zapadnie decyzja w sprawie rankingu spółek bez DCF (punkt B).**

**Konsekwencja poprawki 2 do decyzji.** Spółka, której podejrzany CAPEX staje się brakiem danych, a która trafi na shortlistę, zatrzyma skan przed Claude (reguła kompletności danych z 23.10). W scenariuszu B APO wypada z shortlisty, więc na 22.10 do tego nie dochodzi. Alternatywa do decyzji: zamiast zatrzymywać skan, przenieść taką spółkę do grupy „bez kompletnych danych”.

## 2. Propozycje do akceptacji (niewdrożone)

Wszystkie liczby: dane 22.10 z poprawkami 1–4, scenariusz A. **Wagi i progi poniżej są przykładowe: do decyzji, nie do wdrożenia bez akceptacji.** Całkowita waga komponentu (10 pkt) zostaje bez zmian.

### A. Dywidendy i buyback

Dziś: łączny yield (dywidendy + buyback) > 0 → 3; „brak cięcia DPS” → 3; „payout ≤ 75% FCF” → 2; liczba akcji nie rośnie → 2. Spółka bez dywidendy dostaje „brak cięcia” (0 ≥ 0) i „payout” (0%) automatycznie: 30 z 54 takich spółek ma 10/10.

| Propozycja | Reguła | 10/10 bez dywidendy | 10/10 z dywidendą | Shortlista 22.10 |
|---|---|---|---|---|
| **P-D1** Równoległe kryteria | Płacący: bez zmian. Niepłacący: zamiast „brak cięcia” (3) → „buyback w obu ostatnich latach” (3); zamiast „payout” (2) → „buyback ≤ FCF” (2). | 30 → 18 | 63 → 63 | bez zmian |
| **P-D2** Dwa podkomponenty po 5 pkt | Dywidenda: DPS > 0 i brak cięcia (3) + payout ≤ 75% FCF (2). Buyback: buyback > 0 (3) + liczba akcji nie rośnie (2). Niepłacący max 5. | 30 → 0 | 63 → 61 | −PODD, SNDK, ADBE, NFLX, UBER; +EME, HII, JBL, IR, CHRW |
| **P-D3** Całkowity zwrot | Łączny yield > 0 (4) + (dywidendy + buyback) ≤ FCF (4) + liczba akcji nie rośnie (2); bez kryteriów czysto dywidendowych. | 30 → 20 | 63 → 51 | −ADBE; +IR |

**Zalety i wady.**
- **P-D1:** buyback oceniany osobno, a obie grupy mają to samo maksimum. Wada: dwa nowe kryteria do zatwierdzenia (próg „ciągłości” i „≤ FCF”).
- **P-D2:** najprostsza i dosłowna. Wada: strukturalnie faworyzuje płacących dywidendę (preferencja inwestycyjna, nie neutralna technicznie).
- **P-D3:** jedna miara zwrotu dla wszystkich. Wada: traci wykrywanie cięcia dywidendy.

**Kalibracja/walidacja:** każda zmiana wpływa na ranking. Dane dywidend i buybacków są w backteście 2012–2021, więc można je porównać według tego samego protokołu (sekcja 3).

### B. Spółki bez DCF (bez usuwania i bez arbitralnej kary)

Na 22.10: 119 spółek z DCF, 43 bez DCF.

| Propozycja | Reguła | Shortlista 22.10 | Zalety | Wady |
|---|---|---|---|---|
| **P-N1** Dwie listy | Ranking i shortlista osobno: z DCF (wynik z 45 pkt) i bez DCF (z 25 pkt); kwota dla listy bez DCF do decyzji (przykład: 20 + 5) | 25: TOP20 z DCF (+APTV, EME, FISV, HII, JBL) i lista bez DCF: GL, PODD, CEG, NFLX, UBER | Brak porównywania różnych baz; brak kary; spółki bez DCF zostają w analizie | Wielkość kwoty to decyzja; dwie listy w aplikacji |
| **P-N2** Najpierw z DCF | Spółki bez DCF po wszystkich z DCF (reguła finalnego rankingu) | −GL, PODD, CEG, NFLX, UBER | Spójne z istniejącą regułą | Praktycznie wyklucza spółki bez DCF z shortlisty (ukryta kara) |
| **P-N3** Uzupełnienie medianą | Brak wyceny = mediana punktów wyceny spółek z DCF w skanie | Mediana = **0 z 20**, więc to samo co P-N2 | Reguła oparta na danych | Na tym rynku działa jak kara; zależy od rynku |
| **P-N4** Wspólna baza | Ranking wszystkich wg bezpieczeństwa + dywidend (25 pkt); wycena jako osobna kolumna i flaga | 27 (remisy); −11, +18 | Porównywalne bazy; zgodne z wynikiem holdoutu | Wycena przestaje wpływać na kolejność; masowe remisy |

**Rekomendacja techniczna (do decyzji): P-N1.** To jedyny wariant, który spełnia oba warunki naraz: spółka bez DCF nie zyskuje przewagi przez renormalizację i nie dostaje kary. Wielkość kwoty jest decyzją inwestycyjną.

### C. Metodologia wyceny
Z góry zdefiniowany protokół: `docs/protocol-valuation-variants-2012-2021.md`. Bez wykonania.

## 3. Kolejność dalszych prac (propozycja)
1. **Decyzja B (ranking bez DCF).** Dopiero po niej poprawka 1 może trafić do skanu.
2. **Decyzja A (dywidendy).** Wdrożenie z testami i pokazanie wpływu.
3. **Zatwierdzenie protokołu C**, implementacja wariantów w backteście (tylko analiza), jedno uruchomienie, raport wszystkich wariantów.
4. Dopiero potem pełny skan.
