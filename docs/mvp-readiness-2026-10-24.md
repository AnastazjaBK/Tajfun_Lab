# Gotowość MVP — porównanie skanów 6.10 i 22.10 (2026-10-24)

Bez nowych wywołań Claude, bez skanu, bez publikacji. Źródła danych:
- snapshot 6.10 (`live-scan-2026-10-06T083825543395Z`, kod `c670644`, run 37437405189);
- snapshot i log 22.10 (`live-scan-2026-10-22T202049554465Z`, kod `f931c38`, run 39847892014);
- płatna walidacja z 23.10 (run 39950291317, kod `6972def`).

## 1. Co nie działało 22.10

**Potwierdzone:**
- **Schemat JSON.** Sześć pól treści (`bull_case`, `bear_case`, `why_market_may_be_right`, `biggest_unknown`, `thesis_invalidation`, `why_this_may_not_be_a_bargain`) miało wartości domyślne. W schemacie wysyłanym do API przez SDK nie były więc wymagane. Sprawdzone przez `transform_schema` z SDK: w `f931c38` wymaganych 0 z 6, obecnie 6 z 6.
- **Odpowiedzi modelu.** Model zostawiał puste `thesis_invalidation` i `biggest_unknown`. W 6.10 tak było w 19 z 20 zapisanych odpowiedzi (wszystkie oprócz PAYX).
- **6.10 a walidacja.** W 6.10 walidacja nie sprawdzała, czy pola mają treść, więc te 19 analiz dostało COMPLETE mimo pustych pól. „Kompletność” 6.10 była dla tych dwóch pól pozorna.
- **22.10 a naprawa.** 22.10 walidacja treści już działała (wprowadzona 6.10 po skanie). Naprawa obejmowała tylko przypadek „puste wyłącznie `thesis_invalidation`”. Log 22.10 dla wszystkich 22 spółek: „brak targeted repair — naruszenie nie jest izolowanym, pustym thesis_invalidation”. Wynik: FAILED bez próby naprawy.
- **To nie kod portfela.** Prompt w 22.10 był identyczny z obecnym (porównanie bajt po bajcie). Ścieżka Claude nie zmieniła się między pracami nad portfelem (19.10) a skanem 22.10.

**Hipoteza, niepotwierdzalna z zapisanych danych:** w 22 odrzuconych odpowiedziach z 22.10 drugim pustym polem było `biggest_unknown`. Odrzucone odpowiedzi nie były wtedy zapisywane. Za hipotezą przemawia wzorzec 19/20 z 6.10 i to, że po poprawce schematu 5/5 tych spółek przeszło.

**Inne różnice (bez wpływu na awarię):**
- dłuższy prompt (+~780 tokenów input: blok ceny i wyceny oraz wymogi pól, dodane 6.10 po skanie);
- 6.10 odpowiedzi po angielsku, 22.10 po polsku. Prompt nie określa języka, to zachowanie modelu.

## 2. Co naprawiono i jak potwierdzono

| Poprawka | Potwierdzenie |
|---|---|
| Sześć pól wymaganych w schemacie (23.10) | Płatna walidacja 23.10: DECK, TPR, PODD, NFLX, CEG (22.10: FAILED) → 5/5 COMPLETE w 1 wywołaniu, 0 napraw, 0,48 USD. Od tamtej pory ścieżka Claude bez zmian (schemat, prompt, klient, SDK 1.17.0). |
| Naprawa wszystkich pustych pól (max 2 próby, tylko te pola) | Nowe testy na **prawdziwych** odpowiedziach z 6.10 i 22.10 (`tests/test_regression_scans_2026_10.py`): odpowiedź z wzorcem 22.10 → 1 naprawa obu pól → COMPLETE, reszta analizy bez zmian. Nieudana naprawa → FAILED po 2 próbach z przyczyną, każda odpowiedź zapisana. Błąd strukturalny → FAILED bez naprawy. |
| Status i przyczyna dla każdej spółki; niekompletny skan nie jest publikowany | Istniejące testy (`publish-snapshot` odrzuca skan inny niż COMPLETE). |

Pełny zestaw testów: 991 passed, 24 skipped.

## 3. Metodologia i zakres z 6.10

**Bez zmian:**
- punktacja i wagi;
- wycena;
- reguła TOP 20 z całym remisem na granicy;
- reguła TOP 5;
- struktura analizy (te same pola);
- jedna pełna analiza na spółkę z TOP 20.

**Kod kwalifikacji z rundy 5 nie jest podłączony do skanu.**

Wpływ zachowanych poprawek na ranking, na danych 22.10 (`docs/analysis/mvp_rerank_22_10.py`):

| Poprawka | Wpływ na TOP 20 |
|---|---|
| Znak dźwigni przy EBITDA ≤ 0 | Brak. Zmienia wynik 5 spółek spoza TOP 20 (F, CVNA, IP, ECHO, SKYD). |
| Profil z SIC zamiast „wszystkie GENERAL” | GL (ubezpieczyciel) wchodzi na 1= (100%), bo nie ma metody wyceny i wynik jest renormalizowany. Wypada pięciospółkowy remis z pozycji 20= (APTV, EME, FISV, HII, JBL). Shortlista 24 → 20. |
| CAPEX = 0 weryfikowany w SEC | APO ma CAPEX = 0 w FMP. Jeśli SEC go nie potwierdzi, APO wypada (89,3% → ~50%), a remis 20= wraca: shortlista 24. Wynik zależy od SEC, nie da się go ustalić offline. |
| Dywidendy uprzywilejowane | Snapshot 22.10 nie ma faktów SEC ani nowych pól FMP. Wpływ widoczny dopiero w skanie, w raporcie danych. |
| SEC 404 / brak SIC → poza rankingiem | Uniwersum 22.10: 1 spółka z błędem SEC (CIK 2012866), 0 bez SIC. Nie była w rankingu. |

Renormalizacja spółki bez DCF działa tak samo jak 6.10: wtedy PODD miał 100% bez wyceny. Zmienia się tylko przyczyna braku DCF: dla BANK, INSURER i REIT konfiguracja nie przewiduje wyceny. W TOP 5 takie spółki są za spółkami z pełnym wynikiem, jak PODD w 6.10. Znany problem „sztucznej przewagi przez renormalizację” (decyzja B z 23.10) pozostaje taki sam jak 6.10 i nie jest ruszany.

## 4. 500 spółek, TOP 20, TOP 5

- **Mechanizm z 6.10:**
  - spadki cen i bramka pokrycia notowań dla całego uniwersum (500);
  - pełny wynik deterministyczny dla wszystkich wytypowanych (6.10: 156, 22.10: 162), cały ranking zapisany;
  - Claude dla TOP 20 z remisem na granicy.

  Bez zmian.
- **Braki są oznaczane jawnie:** spółka bez SIC lub z błędem SEC jest poza rankingiem z przyczyną; CAPEX i dywidendy mają stan weryfikacji; brakujące komponenty są pokazane w aplikacji.
- **Bramki przed Claude** (koszt 0, gdy zatrzymają skan):
  - świeżość i pokrycie danych;
  - ponad 5% spółek bez klasyfikacji;
  - braki danych na shortliście (na 22.10: brak);
  - limit wywołań poniżej 3 × liczba spółek na shortliście.
- **TOP 5 (zmiana w tej rundzie, tylko oznaczenie):**
  - kolumna „TOP 5” zamiast „Finalista”;
  - przy równym wyniku ta sama pozycja ze znakiem „=” (6.10: DECK i INTU, oba 79,59, były pokazane jako 3 i 4);
  - ostrzeżenie, gdy spółka spoza piątki ma wynik równy piątej.

  Reguła wyboru bez zmian.

## 5. Koszt pełnego skanu

Na podstawie zmierzonych tokenów, cena 2 / 10 USD za mln tokenów input / output:

| | Wywołania | Koszt | Średnio na analizę |
|---|---|---|---|
| 6.10 | 20 | 1,75 USD | 0,088 |
| 22.10 | 24 | 2,23 USD | 0,093 |
| Walidacja 23.10 (obecny kod) | 5 | 0,48 USD | 0,097 |

- **Przewidywany koszt:**
  - 20 spółek: **~1,9 USD** (zakres pojedynczej analizy 0,07–0,12 USD, czyli 1,5–2,4 USD);
  - 24 spółki (remis): **~2,3 USD**;
  - na danych 22.10 shortlista miałaby 20 albo 24 spółki, zależnie od weryfikacji CAPEX APO.
- **Naprawy:** po zmianie schematu 0 na 5. Koszt pojedynczej naprawy nie był zmierzony na obecnym kodzie.
- **Granica teoretyczna** (każda spółka 2 nieudane naprawy i każda odpowiedź do limitu 16 000 tokenów): ~0,17 USD za wywołanie × 3 × liczba spółek, czyli ~10 USD dla 20 spółek. Twardy limit wywołań to 75 (25 spółek × 3).

**Dodatkowy płatny test nie jest potrzebny.** Ścieżka Claude jest identyczna z tą z walidacji 23.10. Elementów SEC i FMP (SIC, CAPEX, dywidendy na pełnym uniwersum) nie da się sprawdzić offline. Sprawdzi je etap 1 skanu kontrolnego przed pierwszym wywołaniem Claude. Opcjonalnie da się to zrobić osobno, przebiegiem tylko z rankingiem (koszt Claude 0).

## 6. MVP gotowe: TAK — do jednego skanu kontrolnego

Brak znanych blokad technicznych. Do zdecydowania przed skanem, bez zmian w kodzie:
1. Czy akceptujesz skutek profili z SIC: GL na 1= w TOP 20 przez renormalizację, czyli ten sam mechanizm co PODD w 6.10.
2. Limit wywołań dla skanu: domyślne 75 pokrywa shortlistę do 25 spółek. Większy remis zatrzyma skan przed Claude, bez kosztu.
