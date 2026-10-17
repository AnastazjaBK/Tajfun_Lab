# P0a (pokrycie FMP) i analiza CTVA — wyniki, 2026-10-17

Wykonano wyłącznie zatwierdzony zakres:
- 19 zapytań FMP (bez ponawiania) i 1 zapytanie SEC EDGAR;
- jednorazowy workflow na osobnym branchu `claude/diag-p0a-fmp`, run [39066715293](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/39066715293).

Nie było live scanu, wywołań Claude API, zmian w `main`, w branchu aplikacji ani w bazie. Plan FMP w momencie testu: **Premium** (aktywny do 27.10).

Oznaczenia: **[R]** zweryfikowane w repo/danych/teście, **[Z]** źródło zewnętrzne, **[H]** założenie, **[T]** do testu.

---

## 1. Repozytorium [R]

| Element | Stan |
|---|---|
| Repo | `AnastazjaBK/Tajfun_Lab` |
| Branch | `claude/buffett-scanner-design-review-mrud89` (zsynchronizowany z GitHub) |
| Status | czysty |
| Ostatnie commity | `5c6efc8` (Faza 9), `3fde515`, `85a4d6e` |
| Commity z Twojej listy | `05b1b33`, `bdfcc92`, `536c924`, `c670644` — obecne w historii |
| `buffett_scanner/` | obecny (scanner, scoring, `pg_store.py`, `db.py`, `ui/`) |
| UI | `app.py` (Streamlit), wdrażany z tego brancha |

---

## 2. P0a — pokrycie FMP na planie Premium [R]

| Instrument / dane | Profil (cena, waluta, ISIN) | Notowania historyczne | Dywidendy | Quote |
|---|---|---|---|---|
| Schneider `SU.PA` (Euronext Paris) | ✅ 253,30 EUR, ISIN FR0000121972 | ❌ 402 | ❌ 402 | ❌ 402 |
| GSK `GSK.L` (LSE) | ✅ 1862,5 **GBp**, ISIN GB00BN7SWP63 | ✅ od 2007-01-02 | ✅ 119 wypłat od 1993 | nie testowano |
| iShares MSCI World `EUNL.DE` (Xetra, ETF) | ✅ 130,54 EUR, `isEtf` | nie testowano | — | — |
| Xetra-Gold `4GLD.DE` (Xetra, ETC) | ✅ 119,43 EUR | ❌ 402 | — | — |
| AAPL (USA) | — | ✅ od 2006-11-30 | ✅ 92 wypłaty od 1987 | — |
| BTCUSD | — | — | — | ✅ 81 543 USD, ze znacznikiem czasu |
| Złoto `GCUSD` / srebro `SIUSD` | — | — | — | ✅ ceny **kontraktów terminowych** (4181,1 / 57,305 USD za uncję), nie spot |

Błąd 402 = „This value set for 'symbol' is not available under your current subscription” — symbol spoza planu.

**Wnioski:**
- **Wycena bieżąca (Faza 9) działa na Premium dla Paryża, Londynu i Xetry**, bo korzysta z profilu, który przechodzi także tam, gdzie notowania i dywidendy są zablokowane.
- **Na Premium nie ma** historii ani dywidend dla Paryża i Xetry. Zmiany 1D–MAX i dywidendy Schneidera oraz europejskich ETF/ETC są niemożliwe na obecnym planie.
- **Londyn jest w Premium** (historia i dywidendy GSK działają). To zgodne z cennikiem: Premium = USA + Wielka Brytania + Kanada [Z].
- **Limit 5000 wierszy na zapytanie:** zarówno AAPL, jak i GSK.L zwróciły dokładnie 5000 wierszy, czyli ok. 20 lat. „MAX” wymaga zapytań stronicowanych po datach.
- **Brak `adjClose`** w `historical-price-eod/full`. Ceny są przeliczone o splity (AAPL 3,27 USD w 2006), ale nie o dywidendy. Potwierdza to wcześniejsze ustalenie (`adj_close = close`).
- **Dywidendy FMP mają wszystko, czego wymaga A2:** `date` (ex-dividend), `recordDate`, `paymentDate`, `declarationDate`, `dividend`, `adjDividend`, `yield`, `frequency` („Quarterly”, „Semi-Annual”). Brak jawnego oznaczenia dywidendy specjalnej [R]: trzeba wnioskować z `frequency` i odstępstw od wzorca [H].
- **Złoto i srebro:** FMP daje kontrakty terminowe, nie spot. Różnica jest zwykle niewielka, ale to nie jest cena spot i musi być tak oznaczona. Darmowa alternatywa dla złota: NBP [Z, T].

**Na Starterze (od 27.10) nie da się tego teraz sprawdzić**, bo konto jest na Premium. Według cennika [Z] Starter = tylko USA. Hipoteza [H]: odpadną notowania i dywidendy GSK.L. Nie wiadomo, czy profil (cena bieżąca) dla Europy zostanie dostępny [T]. Ten sam skrypt można uruchomić ponownie po 28.10 (ok. 19 zapytań) — tylko za Twoją zgodą.

---

## 3. Koszty i rekomendacja (decyzja kosztowa)

**Wymagania z zakresu P0–P4 a dostawca:**
- ceny bieżące: USA, Paryż, Londyn, Xetra (ETF/ETC), krypto, złoto/srebro;
- historia 5Y/MAX dla tych samych rynków;
- dywidendy USA i Europa.

| Wariant | Koszt miesięcznie [Z] | Paryż / Xetra: historia i dywidendy | Londyn | Ryzyko |
|---|---|---|---|---|
| A. FMP Starter | 29 USD (19 USD rocznie) | ❌ | ❌ [H] | Europa prawdopodobnie bez cen |
| B. FMP Premium | 69 USD (49 USD rocznie) | ❌ **(sprawdzone)** | ✅ | Nie spełnia wymagań dla Paryża i Xetry |
| C. FMP Ultimate | 139 USD (99 USD rocznie) | ? „global”, **niesprawdzone** | ✅ | Najdroższy, pokrycie Paryża i Xetry niepotwierdzone |
| D. FMP Starter + EODHD „EOD All World” | 29 + ~20 = ~49 USD | ✅ wg opisu planu (60+ giełd, splity, dywidendy) [Z], **niesprawdzone** | ✅ [Z] | Drugi klient API do napisania; waluta cennika (USD/EUR) niepewna |

FMP Starter zostaje w każdym wariancie, bo scanner potrzebuje danych z USA (fundamenty, notowania, skład S&P 500).

**Rekomendacja: wariant D jest najtańszy spośród tych, które mogą spełnić wymagania.** Warunek: krótki test EODHD na `SU.PA`, `GSK.L`, `4GLD.DE`, `EUNL.DE` przed zakupem. EODHD ma darmowy klucz testowy z małym limitem [Z, T]. Tego testu nie wykonywałam: wymaga Twojej zgody i założenia konta przez Ciebie.

Ważne dla Startera: **scanner zależy od endpointu składu historycznego S&P 500**, który według dokumentacji projektu wymagał Premium (v1.31). Trzeba sprawdzić, czy przejście na Starter nie zablokuje kolejnego live-scanu [T]. To ryzyko istnieje niezależnie od tego audytu.

---

## 4. CTVA — weryfikacja i wpływ

### Zdarzenie: zweryfikowane trzema niezależnymi źródłami

- **FMP `splits` [R]:** `{"date": "2026-10-01", "numerator": 1333, "denominator": 200, "splitType": "spin-off"}`.
- **SEC EDGAR [R]:** 4 formularze 8-K złożone 2026-10-01 oraz 8-K z 2026-10-05 i 2026-10-07.
- **Źródła zewnętrzne [Z]:** wydzielenie biznesu nasion jako **Vylor (VYLR)**, 1 akcja VYLR za 1 akcję CTVA, dzień wydzielenia 2026-10-01.
- **Snapshot [R]:** CTVA 12,57 + VYLR 68,26 = **80,83 USD** wobec 77,65 USD dzień wcześniej. Akcjonariusz zyskał ok. 4%, nie stracił 84%.

**FMP poprawia historię wstecz, ale z opóźnieniem [R].** Dzisiejsze dane FMP pokazują CTVA 2026-09-22 = 12,05 USD, czyli ceny sprzed wydzielenia przemnożone przez ~0,15. Snapshot pobrany 6.10 miał jeszcze ceny nieskorygowane. Skan trafił w okno niespójności danych dostawcy.

### Wpływ na wynik skanu [R]

| Element | Wartość w skanie | Dlaczego niewiarygodna |
|---|---|---|
| Sygnał spadku | 4 z 6 flag (tydzień, miesiąc, kwartał, od szczytu 52 tyg.) + nietypowy wolumen | Sztuczny „spadek” −84% wynikający z wydzielenia, nie z rynku |
| Wycena DCF / Margin of Safety | MoS **86,8%** | FCF całej firmy 2025 (2,82 mld USD, z nasionami) porównany z kapitalizacją po wydzieleniu (12,39 × 681 mln akcji = 8,44 mld USD) → FCF yield 33% |
| Dywidenda w scoringu | 10/10 pkt | DPS 0,70 USD ÷ 12,39 = yield **5,6%** zamiast ok. 0,9% przed wydzieleniem |
| Ranking | `deterministic_score_pct` 93,75 → **miejsce 15 w TOP20** | Wynik napędzany powyższymi trzema błędami |
| Analiza Claude | Ocena 75,7; „fear: UNCERTAIN”; przyczyna spadku przypisana cyklowi cen surowców rolnych | Claude nie dostał informacji o wydzieleniu; brak słowa „spin-off/Vylor” w analizie |

Wyniku nie da się „poprawić” bez danych fundamentalnych samego biznesu środków ochrony roślin. Pierwszy raport po wydzieleniu (10-Q) jeszcze nie istnieje [H]. **Wynik CTVA z tego skanu jest niewiarygodny i nie powinien być traktowany jako okazja.**

### Ryzyko podobnych przypadków w tym samym skanie [R]

Przeszukano całe uniwersum (501 spółek) pod kątem jednodniowej zmiany ceny o ponad 25% przy wolumenie powyżej 5× mediany z 20 sesji. Wynik: 14 zdarzeń.
- **Ponad 50%:** tylko CTVA (−84%) i MRNA (+177%, poza listą kandydatów).
- **W TOP20:** tylko CTVA.
- Kandydaci spoza TOP20 z dużym ruchem jednodniowym: FISV (miejsce 32, −44%), PTC (23, +34%), FICO (41, −27%), IBM, CHTR, SMCI, FLEX. Wyglądają na reakcje na wyniki kwartalne [H]; nie mają flagi spin-off/split w danych, ale tego nie sprawdzałam w FMP (to kolejne zapytania).

### Proponowany mechanizm kontroli jakości (bez zmian scoringu, wag, DCF i snapshotów)

Warstwa „flag jakości danych”, liczona obok skanu i zapisywana osobno. Nie zmienia rankingu ani wyników.

1. **Zdarzenie korporacyjne z dostawcy:** FMP `splits` dla kandydatów po screeningu spadków (np. 156 zapytań na skan, w limicie planu). `splitType = spin-off` (lub inne niż zwykły split) w ostatnich 400 dniach → flaga **BLOKUJĄCA: dane cenowe/fundamentalne nieporównywalne**.
2. **Zdarzenie po dacie fundamentów:** zdarzenie z pkt 1 ma datę późniejszą niż `period_end_date` ostatnich użytych fundamentów → wycena, MoS i dywidenda oznaczone jako nieporównywalne.
3. **Anomalia ceny:** jednodniowa zmiana ≥50% → flaga blokująca do wyjaśnienia; 25–50% przy wolumenie ≥5× → flaga informacyjna („sprawdź przyczynę”).
4. **Nowa spółka w uniwersum w dniu anomalii** (VYLR pojawił się 2026-10-01, w dniu skoku CTVA) → wzmocnienie hipotezy wydzielenia.
5. **Prezentacja:** w tabeli TOP20 i na karcie spółki widoczna etykieta „⚠ Wynik niewiarygodny — [powód]”. Ranking i liczby zostają bez zmian, ale nie są przedstawiane jako okazja.
6. Wykluczenie takich spółek z shortlisty (i z płatnej analizy Claude) **to zmiana metodologii** — wyłącznie za Twoją odrębną zgodą.

---

## 5. Audyt UI + portfela wobec wymagań multi-user / Trade Republic / Revolut [R]

Wymagania z drugiej części wiadomości są w większości **już zrealizowane** (Faza 7–9):

| Wymaganie | Stan |
|---|---|
| Osobne dane dwóch użytkowników (transakcje, pozycje, decyzje, teza zakupu) | ✅ `user_id` na `positions` i `user_decisions`; teza i statusy per pozycja |
| Watchlista | ✅ jako decyzja „Obserwuję” (`user_decisions.status = WATCH`) |
| Notatki | ⚠ tylko pole `note` w transakcjach i decyzjach; brak osobnych notatek do spółki |
| Exit Review | ❌ poza zakresem (zgodnie z planem „później”) |
| Broker jako właściwość transakcji | ✅ `TRADE_REPUBLIC` / `REVOLUT` / `OTHER` w zakupach i sprzedażach |
| Pola transakcji | ✅ data, typ (BUY/BONUS w zakupach, SELL w osobnej tabeli sprzedaży), liczba akcji, cena, waluta, opłata, notatka; użytkownik i spółka przez pozycję |
| BONUS: liczba akcji, broker, koszt 0, wartość w portfelu | ✅ |
| Ta sama spółka na dwóch brokerach w jednej pozycji | ✅ rozbicie per (broker, waluta), sprzedaż zmniejsza tylko swój broker |
| Kolumna „Platforma” i filtr Wszystkie / Trade Republic / Revolut | ✅ |
| Jeden portfel, nie dwa | ✅ |
| Waluta per transakcja, bez mechanicznego sumowania | ✅ sumy per waluta |
| Brak FX w V0 | ⚠ **sprzeczność z późniejszą decyzją:** 2026-10-17 zleciłaś „Wprowadź wszystko. Kursy NBP” i Faza 9 to dodała. Twoje nowsze decyzje (pkt 4) to potwierdzają, więc traktuję tę część wiadomości jako wcześniejszą wersję wymagań. |
| Nie zapisywać pozycji automatycznie | ✅ żadnej pozycji nie zapisałam; wpisywałaś je sama przez formularz |

Znane braki już w zatwierdzonym zakresie: precyzja ułamków (`%.4f`), koszt historyczny w PLN dla transakcji w walucie, opłaty i wynik zrealizowany — etap P1.

---

## 6. Sprzątanie

- Branch `claude/diag-p0a-fmp` **nadal istnieje na GitHubie**: moje środowisko nie może usuwać zdalnych branchy.
- Jest nieszkodliwy: nie dotyka aplikacji, a workflow uruchamia się tylko przy pushu na ten branch.
- Możesz go usunąć w GitHub → Branches.
- Wyników nie dopisałam do `docs/buffett-scanner-design-review.md`, bo push na branch aplikacji uruchomiłby wdrożenie. Dopiszę je razem z następnym zatwierdzonym etapem.

Źródła zewnętrzne:
- [Cennik FMP](https://site.financialmodelingprep.com/pricing-plans)
- [Recenzja FMP z porównaniem planów](https://www.findmymoat.com/tools/financial-modeling-prep-fmp)
- [Cennik EODHD](https://eodhd.com/pricing?via=aiva)
- [EODHD w zestawieniu planów](https://apis.io/plans/eodhd/eodhd-plans-pricing/)
- [EODHD na G2](https://www.g2.com/products/eodhd-financial-data-apis/pricing)
- [Corteva/Vylor – Benzinga](https://www.benzinga.com/Opinion/26/10/62224289/corteva-completes-vylor-spin-off-ctva-vs-vylr-which-stock-is-the-better-play-now)
- [Corteva/Vylor – StreetInsider](https://www.streetinsider.com/Corporate+News/Corteva+completes+seed+business+spin-off,+becomes+crop+protection+firm/27131866.html)
- [Corteva/Vylor – Yahoo Finance](https://finance.yahoo.com/markets/stocks/articles/corteva-just-split-two-shareholders-181004474.html)
- [Corteva/Vylor – Spinoff Analysis](https://spinoffanalysis.substack.com/p/corteva-vylor-spin-complete-parent)
