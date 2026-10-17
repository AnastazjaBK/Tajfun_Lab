# Buffett Opportunity Scanner — audyt rozszerzenia (2026-10-17)

Tryb: wyłącznie audyt. Nie zmieniłam kodu ani bazy, niczego nie wdrażałam, nie wywołałam FMP ani Claude API.

Oznaczenia źródeł:
- **[R]** zweryfikowane w repo albo w danych (kod na branchu `claude/buffett-scanner-design-review-mrud89`, commit `5c6efc8`; snapshot scannera pobrany z GitHub Release, SHA256 zgodny ze wskaźnikiem)
- **[Z]** dokumentacja zewnętrzna (wyszukiwarka; strony FMP i NBP są niedostępne bezpośrednio z mojego środowiska)
- **[H]** założenie
- **[T]** wymaga testu empirycznego
- **[Rek]** rekomendacja

---

## 0. Trzy sprawy do zgłoszenia przed resztą audytu

### 0.1 Prawdopodobny błąd danych w działającym scannerze: Corteva (CTVA) [R] + [H]

W snapshocie live-scanu `live-scan-2026-10-06T083825543395Z`:

| Data | Close | Wolumen |
|---|---|---|
| 2026-09-30 | 77,65 | 4,0 mln |
| 2026-10-01 | 12,57 | 88,4 mln |
| 2026-10-05 | 12,39 | 183,2 mln |

- Spadek o 84% w jeden dzień przy 20-krotnym wolumenie.
- CTVA jest na **15. miejscu TOP20**: Margin of Safety (BASE) = **86,8%**, `deterministic_score_pct` = 93,75.
- Analiza Claude (COMPLETE) tłumaczy spadek cyklem cen surowców rolnych.

Hipoteza [H]: to nie spadek, tylko zdarzenie korporacyjne, najpewniej wydzielenie części biznesu (spin-off). Cena po podziale jest porównywana ze wskaźnikami fundamentalnymi całej firmy sprzed podziału. Taki wzorzec daje fałszywy sygnał spadku i fałszywy margines bezpieczeństwa.

Tego nie zweryfikowałam: nie mam dostępu do danych o zdarzeniach korporacyjnych. **To podpada pod regułę „STOP i zgłoś” (błędna interpretacja danych, systematyczny błąd).**

- Ceny w `price_daily` uwzględniają splity [R]: BKNG ma w całej historii ~150–220 USD, więc split został przeliczony wstecz.
- Wydzielenia spółek nie są korygowane [R], a scanner nie ma żadnej detekcji zdarzeń korporacyjnych [R].
- Ten sam mechanizm zaburzy planowane zmiany cen 1D–MAX (sekcja D).
- Inne skoki w danych: MRNA +177% (2026-08-19, wolumen 46×) i FISV −44% (2025-10-29). Wyglądają na prawdziwe reakcje rynku [H], ale też wymagają oznaczenia [T].

### 0.2 Moja wcześniejsza informacja o FMP była błędna [R]

Napisałam wcześniej, że test cen europejskich z Fazy 7 był na planie Free, „więc Starter powinien wystarczyć”. Dokumentacja projektu pokazuje jednak, że plan Premium był aktywny od v1.31 (2026-09-26, linia 35), a test Fazy 7 to ~6–7.10. **Test był więc na planie Premium.** Wpis „na planie Free” w dokumentacji Fazy 7 jest nieprawdziwy.

Według cennika FMP [Z]:
- Starter: tylko rynek USA (plus kryptowaluty i forex);
- Premium: dodaje Wielką Brytanię i Kanadę;
- Ultimate: „global”.

Wniosek [H]: **od 27.10 (przejście na Starter) ceny `SU.PA` i `GSK.L` prawdopodobnie przestaną być dostępne.** Na Premium Euronext Paris też może nie być objęty planem. Profil `SU.PA` zadziałał na Premium, ale nie wiadomo, czy w ramach planu, czy przez tolerancję endpointu [T].

### 0.3 Faza 9 (wdrożona wczoraj) częściowo łamie Twoje wymaganie E4 [R]

- Kwoty USD (Revolut) są przeliczane na PLN **dzisiejszym** kursem NBP, także koszt historyczny. Wymaganie E4 tego zakazuje. Pozycji z Trade Republic to nie dotyczy: ich koszt jest zapisany w PLN.
- Nie wiem, czy Faza 9 działa na produkcji. Odpowiedzi NBP nie sprawdziłam na żywym API [T].
- Formularz ma `format="%.4f"` dla liczby akcji [R]. Ułamkowe akcje z Trade Republic (zwykle 6 miejsc po przecinku) i kryptowaluty (do 8 miejsc) mogą być zaokrąglane przy wpisie [T].

---

## H1. Stan obecny

| Funkcjonalność | Co istnieje | Czego brakuje / co nie działa | Pliki / tabele | Gotowość |
|---|---|---|---|---|
| Scanner, scoring, DCF | Deterministyczny ranking 156 kandydatów, TOP20 (`in_shortlist=1`), analiza Claude dla TOP20 [R] | Brak detekcji zdarzeń korporacyjnych (CTVA) [R] | `live_scan*.py`, `scoring.py`, `valuation.py`; `live_scan_candidates`, `analyses` | Działa; jakość danych do weryfikacji |
| TOP20 w UI | Tabela syntezy pokazuje wszystkich 20 z shortlisty [R] | Finalna piątka nie jest oznaczona w UI (liczona tylko w raporcie markdown) [R] | `ui/queries.get_synthesis_rows`, `live_scan.rank_candidates` | Działa |
| Historia cen scannera | `price_daily` w snapshocie: 2025-09-02 → 2026-10-05, 275 sesji, 501 spółek, tylko USA [R] | Brak historii 5Y i MAX; `adj_close` = `close` we wszystkich wierszach (brak korekty o dywidendy) [R] | `price_daily`, `cli.py --price-days 400` | 1D–1Y: tak; 5Y/MAX: nie |
| Dywidendy (dane) | Roczne `dividends_paid` z cash flow (FY2021–FY2026) i DPS = dividends_paid ÷ akcje rozwodnione [R] | Brak wypłat na akcję, dat ex-dividend/wypłaty, częstotliwości, dywidend specjalnych [R] | `fundamentals_raw`, `shareholder_returns.py` | Tylko dla scoringu, nie do prezentacji |
| Dywidendy w portfelu | Nic [R] | Brak rejestru otrzymanych dywidend [R] | — | Brak |
| Portfel: model | `positions` (1 na użytkownika i instrument) + transakcje kupna/sprzedaży per broker, BONUS, anulowanie (Faza 9) [R] | Brak klasy aktywa, ISIN, waluty notowania (`instrument_currency` faktycznie przechowuje walutę transakcji) [R] | `positions`, `purchase_transactions`, `sale_transactions` (SQLite + Supabase) | Rozszerzalny |
| P/L niezrealizowany | Metoda średniego kosztu per (broker, waluta) [R] | Opłaty nie wchodzą do obliczeń [R] | `ui/portfolio.py` | Działa |
| P/L zrealizowany | Sprzedaże zapisywane z ceną [R] | Wynik sprzedaży nie jest liczony ani pokazywany [R] | `ui/portfolio.py` | Brak |
| Ceny bieżące | Faza 9: profil FMP po potwierdzonym tickerze, cache 1 h; zapasowo `price_daily` [R] | Europa prawdopodobnie zniknie po 27.10 (0.2); brak daty ceny [R] | `ui/pricing.py`, `ui/queries.py` | Do pilnej weryfikacji |
| FX / PLN | Faza 9: NBP tabela A, kurs bieżący, cache 1 h [R] | Brak kursów historycznych (E4), brak zapisu kursów w bazie, brak tabeli B [R] | `ui/pricing.py` | Częściowo |
| Hosting | Streamlit Community Cloud z tego brancha; Supabase (Session pooler); snapshot z GitHub Release [R] | Brak harmonogramu w samej aplikacji: odświeżanie tylko przy otwarciu strony albo przez GitHub Actions [R] | `app.py`, `pg_store.py`, `scanner_snapshot.py` | Działa |

---

## H2. Instrumenty europejskie

**Przyczyna braku wyceny przed Fazą 9 [R]:** cena bieżąca pochodziła wyłącznie z `price_daily` po CIK (tylko spółki SEC z uniwersum S&P 500). Spółki europejskie nie mają CIK, więc nie dostawały ceny.

**Po Fazie 9 [R]:**
- Cena pochodzi z profilu FMP, z normalizacją `GBp → GBP ÷ 100`.
- Działa tylko dla pozycji, które po wdrożeniu potwierdzisz w karcie pozycji.
- To naprawia przyczynę, ale tylko dopóki plan FMP obejmuje daną giełdę (0.2).

**Problem symboli i walut [R]:**
- `SU` w FMP to Suncor. Faza 9 blokuje zapis bez potwierdzenia.
- Brak kolumny ISIN, więc akcji GSK (`GB…`) nie odróżnimy od ADR GSK (`US…`) inaczej niż po tickerze i giełdzie.
- `instrument_currency` w `positions` miesza walutę notowania z walutą zapłaty.

**Dostępność cen europejskich w FMP:**
- Profil i cena `SU.PA` (EUR) i `GSK.L` (GBp) działały na Premium [R, dokumentacja Fazy 7].
- Na Starterze najpewniej nie [Z + H].
- Historia EOD dla Europy: nieznana [T].
- Xetra (`.DE`) i ETC: nieprzetestowane [T].

**Minimalna poprawka:**
1. Test diagnostyczny przed 27.10, póki Premium jest aktywny: `profile` i `historical-price-eod/full` dla `SU.PA`, `GSK.L`, jednego ETF/ETC z Xetra; potem to samo na Starterze. Kilkanaście zapytań, jednorazowy workflow według dotychczasowego wzorca DIAG. **Wymaga Twojej zgody.**
2. Dodać do `positions` pola `isin` i `quote_currency` (migracja niedestrukcyjna).
3. Jeśli Starter nie obejmuje Europy: decyzja o planie albo o drugim dostawcy (H8).

**Alternatywy dla FMP** (wszystko [Z/H], do weryfikacji przed wyborem):

| Dostawca | Pokrycie | Koszt | Uwagi |
|---|---|---|---|
| FMP Premium | USA + UK + Kanada | ~69 USD/mies. | Paryż/Xetra niepewne |
| FMP Ultimate | „global” | ~139 USD/mies. | Najprostsza ciągłość kodu |
| EODHD (EOD All World) | 60+ giełd, EOD + dywidendy + splity | rzędu 20–30 USD/mies. | Oceniany w D1 projektu; nowy klient API |
| Stooq / Yahoo | szerokie | 0 | Nieoficjalne, niejasne warunki użycia, niestabilne |

---

## H3. Dywidendy

**Dostępne źródła:**
- **Repo/baza [R]:** tylko roczne `dividends_paid` (łączna kwota ze sprawozdania przepływów pieniężnych) i DPS wyliczony dzieleniem przez liczbę akcji rozwodnionych. To kwota spółki, nie wypłata na akcję. Nie nadaje się do yieldu TTM, częstotliwości ani dat.
- **SEC EDGAR [R]:** klient `get_company_facts` istnieje. Może zawierać `CommonStockDividendsPerShareDeclared` [H], ale cache w snapshocie jest pusty [R], tylko dla spółek z USA i bez dat ex-dividend.
- **FMP [Z]:** endpoint `stable/dividends?symbol=` (historia wypłat na akcję, daty) i kalendarz dywidend. Dostępność na Starterze i dla Europy, nazwy pól, pole częstotliwości i oznaczenie dywidend specjalnych: [T].

**Proponowane obliczenia** (wszystko poza scoringiem; zero zmian wag):
- **Yield TTM** = suma wypłat na akcję z ex-date w ostatnich 365 dniach ÷ cena. Dla historycznego raportu: cena z dnia skanu i wypłaty do dnia skanu (PIT).
- **Częstotliwość:** liczba regularnych wypłat w ostatnich 12–24 mies. (12 = miesięczna, 4 = kwartalna, 2 = półroczna, 1 = roczna, inaczej nieregularna). Dywidendy specjalne wykluczone, jeśli dostawca je oznacza; w przeciwnym razie flaga „niepewne”.
- **Brutto na 100 PLN** = 100 × yield TTM, z dopiskiem „orientacyjnie, przy dzisiejszym kursie i cenie”.
- **Trend:** porównanie sum rocznych wypłat na akcję (3–5 lat): rośnie / stabilna (±2%) / spada / obcięta (spadek >25% albo zawieszenie) / brak danych. Bez oceny „bezpieczeństwa” na podstawie samego yieldu. Wskaźnik wypłaty (payout ratio) już istnieje w kodzie (dividends_paid ÷ FCF) i można go pokazać jako kontekst.
- **Najbliższa ex-date** tylko gdy ogłoszona (kalendarz dostawcy). Nigdy prognozowana jako potwierdzona.

**Rejestr wypłat: tak, jest potrzebny [Rek].** Nowa tabela `dividend_receipts`:
- `user_id`, `position_id`, `broker`, `pay_date`, `ex_date`
- `gross_amount`, `withholding_tax`, `net_amount`, `currency`
- `fx_rate_pln` i jego źródło, `reinvested` (bool), `note`, `voided_at`

Dlaczego osobno:
- Prognoza (shares × DPS) nigdy nie jest „otrzymana”.
- Otrzymane dywidendy to fakt z wyciągu brokera.
- Reinwestycja to osobna transakcja zakupu.

**Yield on Cost** = prognozowana roczna dywidenda dla posiadanych akcji ÷ koszt aktualnie posiadanych akcji (istniejący `total_invested` per subpozycja po sprzedażach, metoda średniego kosztu) [R]. Przy koszcie 0 (BONUS): N/A, kwota dywidendy normalnie.

**Prezentacja:**
- **TOP20:** domyślnie 4 kompaktowe kolumny (Yield TTM, Częst., /100 PLN, Trend). Selektor „Widok: Scoring / Dywidendy / Zmiany cen” zamiast 20+ kolumn naraz. `st.dataframe` przewija się poziomo.
- **Karta spółki:** pełne szczegóły z A2.
- **Portfel:** sekcja „Dywidendy”.

---

## H4. Nowe klasy aktywów

**Model (jeden portfel) [Rek]:**
- `positions` + kolumna `asset_class`. Wartości: STOCK, ETF, ETC, ETN, PHYSICAL_GOLD, PHYSICAL_SILVER, CRYPTO; domyślnie STOCK dla istniejących wierszy.
- `positions` + kolumny `isin`, `quote_currency`, `price_source`.
- Tabela 1:1 `instrument_details` dla pól specyficznych dla klasy:
  - ETF/ETC: typ produktu, metal bazowy, sposób ekspozycji, opłata roczna;
  - metal fizyczny: forma (moneta/sztabka), masa sztuki, jednostka, próba, przechowywanie, flaga „kolekcjonerska”;
  - krypto: identyfikator dostawcy (np. `BTCUSD` w FMP) i opcjonalny identyfikator CoinGecko.
- Transakcje bez zmian: `shares` = sztuki / jednostki / ilość monet. Dzięki temu cała historia i logika średniego kosztu działa dalej.

**Metale fizyczne:**
- Wartość spot = sztuki × masa × próba × cena spot za gram.
- Złoto: NBP publikuje cenę złota w PLN za gram [Z], endpoint `api/cenyzlota`. Czy dotyczy próby 1000 i czy jest nadal publikowana: [T].
- Srebro: NBP nie publikuje [H]. Potrzebne źródło (FMP commodities, plan: [T]).
- Wartość odkupu: ręcznie wpisywany spread/wycena dealera z datą. Nigdy spot jako odkup.
- Moneta kolekcjonerska: bez wyceny spot, tylko wycena ręczna.

**Metale giełdowe (ETC/ETN/ETF):**
- Wyceniane jak papiery (ticker + ISIN + giełda). Nigdy jako gramy fizyczne.
- Ekspozycja na złoto = fizyczne (gramy × spot) + giełdowe (wartość rynkowa), pokazane osobno i łącznie.
- Bez przeliczania jednostek ETC na gramy, więc bez podwójnego liczenia.

**Kryptowaluty:**
- Identyfikacja po parze dostawcy, nie po samym symbolu.
- Ceny: FMP crypto (Starter obejmuje crypto według cennika [Z], [T]).
- Brak integracji z giełdami (zgodnie z Twoim zakazem).

**Precyzja [R + Rek]:**
- `shares` to `REAL`/`DOUBLE PRECISION` (ok. 15–16 cyfr znaczących).
- Dla wartości i P/L to wystarcza: błąd rzędu 1e-16 względnie.
- Dokładnych 8 miejsc nie gwarantuje przy sumowaniu wielu wpisów.
- [Rek] W Postgresie zmienić `shares` na `NUMERIC(28,10)` (ALTER bez utraty danych, z backupem przed). Formularz: `format` z 8–10 miejscami zamiast `%.4f`.

**Migracje:**
- Wyłącznie `ADD COLUMN` z wartościami domyślnymi, nowe tabele i ewentualny `ALTER TYPE` na NUMERIC.
- Wzorzec idempotentnych migracji z Fazy 9 już istnieje i jest przetestowany na Postgresie [R].
- Rollback: nowe kolumny są ignorowane przez stary kod (`SELECT *` + dostęp po nazwie), więc powrót do poprzedniego commita działa bez cofania schematu [R].

---

## H5. Historyczne zmiany cen

**Źródło:**
- `price_daily` w snapshocie: 275 sesji, ok. 13 mies. [R].
- Skan pobiera tylko 400 dni (`--price-days 400`) [R].
- 1D/1W/1M/3M/1Y można policzyć dziś dla całego TOP20 **na datę skanu**, bez nowych zapytań i bez Claude.
- 5Y i MAX wymagają pobrania dłuższej historii: 20 spółek × 1 zapytanie `historical-price-eod/full`. Zasięg historii na Starterze [T]; dokumentacja projektu mówi o „5+ lat” dla Startera.

**Obliczenia [Rek]:**
- Zmiana = close(ostatnia sesja ≤ data_ref) ÷ close(ostatnia sesja ≤ data_ref − okres) − 1.
- Okresy kalendarzowe: 1W = 7 dni, 1M/3M/1Y/5Y przez przesunięcie daty.
- 1D = poprzednia sesja.
- Brak sesji w dniu odniesienia → ostatnia wcześniejsza sesja; święta i strefy czasowe obsłużone automatycznie, bo liczymy po datach sesji danej giełdy.
- MAX = pierwsza dostępna cena u dostawcy, z jej datą (np. „od 2021-10-18”), nie IPO.
- Brak pełnego okresu (najstarsza cena późniejsza niż data_ref − okres) → N/A.
- Splity: dane są już przeliczone wstecz [R].
- Spin-offy i inne zdarzenia: bez korekty [R]. Skok >40% w jeden dzień przy wielokrotnym wolumenie dostaje flagę „możliwe zdarzenie korporacyjne”, nie automatyczną korektę (patrz 0.1).
- To jest zmiana ceny, nie total return.

**PIT [Rek]:**
- Dwa jawnie podpisane widoki: „Na dzień skanu (2026-10-05)” ze snapshotu, niezmienny, oraz „Dziś” ze świeżych danych z cache.
- Nigdy nie podmieniać ceny skanu bez etykiety.
- Backtest i kalibracja nietknięte: nowe wartości liczone tylko w UI.

**Telefon [Rek]:** selektor okresu (domyślnie 1M) i jedna kolumna zmiany na telefonie. Pełne 7 kolumn w widoku „Zmiany cen”. Streamlit nie rozpoznaje urządzenia, więc o układzie decyduje wybór widoku, a nie automat.

---

## H6. NBP i PLN

**Architektura [Rek]:** tabela `fx_rates` w Supabase z kolumnami:
- `currency`, `rate_date` (data obowiązywania), `mid`, `table` (A/B), `table_no`, `source`, `fetched_at`.

Działanie:
- Pobranie dzienne: najpierw sprawdzenie, czy w bazie jest już tabela z dzisiejszą datą; jeśli nie, jedno zapytanie. NBP publikuje tabelę A raz dziennie w dni robocze [Z].
- Kursy historyczne: dla każdej waluty jedno zapytanie zakresowe (maks. 93 dni na zapytanie [Z]) od najstarszej transakcji, zapisane na stałe. Dane NBP się nie zmieniają.

**Koszt historyczny:**
- Transakcja w PLN: koszt to kwota zapisana [R]. Nic nie przeliczamy.
- Transakcja w USD/EUR: koszt PLN = kwota × kurs **rzeczywisty brokera, jeśli został zapisany** (nowe opcjonalne pole `fx_rate_actual` w transakcji). W przeciwnym razie kurs NBP z ostatniej tabeli przed datą transakcji, oznaczony jako „orientacyjny NBP”, nie podatkowy.
- Bieżąca wartość = jednostki × ostatnia cena × dzisiejszy kurs NBP, z datami ceny i kursu.
- Niezrealizowany P/L w PLN = bieżąca wartość PLN − historyczny koszt PLN. Pokazuje efekt kursowy.
- Zrealizowany P/L: przychód ze sprzedaży (PLN) − koszt sprzedanej części (PLN) − opłaty. Wymaga dodania obliczeń do `ui/portfolio.py`.

**Waluty spoza tabeli A:** tabela B (publikowana raz w tygodniu [Z]) z datą i oznaczeniem. Brak kursu → N/A, nigdy 0.

**Brakujące dane:** suma oznaczona „częściowa: N z M pozycji”, z listą brakujących instrumentów. Faza 9 robi to częściowo (licznik, bez listy nazw) [R].

**Testy:** czyste funkcje (kurs D-1, weekendy, święta, brak tabeli, GBp, BONUS, częściowa sprzedaż) plus integracyjne na lokalnym Postgresie (wzorzec z Fazy 9).

---

## H7. Plan wdrożenia

| Etap | Zakres | Pliki | Migracje | Źródła | Ryzyka | Zależności | Złożoność |
|---|---|---|---|---|---|---|---|
| **P0a: DIAG FMP** | Test Premium vs Starter dla `SU.PA`, `GSK.L`, Xetra ETF/ETC, `dividends`, crypto, historia 5Y | jednorazowy workflow (usuwany po teście) | brak | FMP | wynik może wymusić decyzję o dostawcy | **przed 27.10** | S |
| **P0b: tożsamość + wycena Europy** | `isin`, `quote_currency`, `asset_class` (od razu, żeby nie migrować dwa razy), data ceny, ewentualnie drugi dostawca | `pg_store.py`, `db.py`, `ui/pricing.py`, `app.py` | ADD COLUMN | FMP lub EODHD | plan FMP | P0a | M |
| **P1: PLN poprawnie** | `fx_rates`, kursy historyczne, `fx_rate_actual`, zrealizowany P/L, opłaty w koszcie, suma częściowa z listą, poprawka 0.3 i `%.4f` | `ui/pricing.py`, `ui/portfolio.py`, `app.py`, `pg_store.py`, `db.py` | nowa tabela + ADD COLUMN | NBP | konwencja kursu (D-1) | P0b (waluta notowania) | M |
| **P2: zmiany cen 1D–MAX** | Widok „na dzień skanu” ze snapshotu (od razu) + „dziś” (cache, historia 5Y), flaga zdarzeń korporacyjnych | nowy `ui/price_changes.py`, `ui/queries.py`, `app.py` | brak (cache w pamięci albo w nowej tabeli) | snapshot + dostawca | 5Y/MAX zależne od planu | P0a | M |
| **P3: dywidendy** | Dane wypłat (TOP20 + portfel), tabela `dividend_receipts`, Yield on Cost, prognoza, karta spółki | nowy `ui/dividends.py`, `providers/fmp.py`, `app.py` | nowa tabela | FMP `dividends` / EODHD | pola i plan [T] | P0a, P1 (PLN) | L |
| **P4: metale, ETC, krypto** | `instrument_details`, wycena spot/odkup, ekspozycja na metale, krypto, NUMERIC | `pg_store.py`, `db.py`, `ui/portfolio.py`, `app.py` | nowa tabela + ALTER TYPE | NBP złoto, FMP commodities/crypto | źródło srebra, spread | P0b, P1 | L |

Odstępstwa od Twojej kolejności:
- P0a musi być pierwszy i przed 27.10.
- `asset_class` warto dodać już w P0b, żeby nie migrować dwa razy.
- **Backup przed każdą migracją:** eksport tabel z Supabase (darmowy plan nie ma automatycznych kopii do pobrania [H], [T]).

---

## H8. Decyzje do akceptacji

1. **Zgoda na test diagnostyczny FMP (P0a)**: kilkanaście zapytań, przed 27.10, na planie Premium.
2. **Plan danych po 27.10**, po wyniku P0a: Starter + drugi dostawca dla Europy (np. EODHD) / zostać na Premium / Ultimate. To decyzja kosztowa.
3. **Corteva i zdarzenia korporacyjne (0.1)**: (a) tylko oznaczyć w UI jako „możliwe zdarzenie korporacyjne, wynik niewiarygodny” albo (b) dodatkowo zbadać i zaprojektować detekcję w scannerze. Wariant (b) zmienia działanie scannera, więc wymaga Twojej decyzji metodologicznej.
4. **Kurs dla historycznych transakcji w walucie, gdy nie wpiszesz kursu brokera**: NBP z ostatniego dnia roboczego przed transakcją (moja rekomendacja) albo z dnia transakcji.
5. **Źródło ceny srebra** (NBP go nie publikuje) i czy cenę odkupu metali wpisujesz ręcznie.

---

Źródła zewnętrzne:
- Cennik FMP: https://site.financialmodelingprep.com/pricing-plans
- Recenzja FMP z porównaniem planów: https://www.findmymoat.com/tools/financial-modeling-prep-fmp
- FMP, endpoint dywidend: https://site.financialmodelingprep.com/de/developer/docs/stable/dividends-company
- API NBP: https://api.nbp.pl/en.html
- Pakiet rnbp (opis API NBP): https://ftp.fau.de/cran/web/packages/rnbp/refman/rnbp.html
- Kalendarz dywidend OpenBB (pola FMP, pośrednio): https://docs.openbb.co/odp/python/reference/equity/calendar/dividend
