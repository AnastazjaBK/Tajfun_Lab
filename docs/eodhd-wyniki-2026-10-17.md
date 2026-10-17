# Diagnostyka EODHD (darmowy klucz) i rekomendacja P0b — 2026-10-17

Run: [39070026144](https://github.com/AnastazjaBK/Tajfun_Lab/actions/runs/39070026144), branch `claude/diag-eodhd`, sekret `EODHD_API_KEY` (nigdy niedrukowany).

Zużycie według licznika EODHD: **14/20** zapytań dziennego limitu. Zapytania `user` nie są liczone.

Bez zmian produkcyjnych, bez Claude API, bez scanu.

## Wyniki [zweryfikowane w teście]

| Instrument | Wyszukiwarka (waluta, ISIN, typ) | Notowania dzienne | Dywidendy | Cena „real-time” |
|---|---|---|---|---|
| Schneider `SU.PA` | ✅ EUR, FR0000121972, Common Stock | ✅ 255 sesji (1 rok), z `adjusted_close` | ✅ 7 wypłat od 2020, waluta EUR | ✅ 253,30, znacznik czasu 2026-10-16 15:36 UTC |
| GSK `GSK.LSE` | ✅ **GBX (pensy)**, GB00BN7SWP63 | ✅ 253 sesje | ✅ 27 wypłat od 2020, w **GBP** (0,17 = 17 p) | ✅ 1862,5 GBX |
| iShares MSCI World `EUNL.XETRA` | ✅ EUR, IE00B4L5Y983, ETF | ✅ 253 sesje | nie testowano (fundusz akumulujący) | nie testowano |
| Xetra-Gold `4GLD.XETRA` | ✅ EUR, DE000A0S9GB0, **typ „ETF”** (w rzeczywistości ETC) | ✅ 253 sesje | — | nie testowano |
| Vanguard FTSE All-World Dist `VGWL.XETRA` | — | — | ✅ 27 wypłat, EUR | — |

## Ograniczenia i uwagi

- **Free: historia notowań tylko 1 rok.** Zapytanie od 2015 r. zwróciło te same 255 sesji z ostrzeżeniem „Data is limited by one year as you have free subscription”. Według cennika płatny plan ma 30+ lat [Z]. Tego nie da się sprawdzić darmowym kluczem i to nie jest dowód braku.
- **Dywidendy na Free nie były ograniczone do roku:** zwrócone od 2020 r.
- Dywidendy mają `date` (ex-dividend), `paymentDate`, `declarationDate`, `period` (Final/Interim/Quarterly), `currency`. `recordDate` zawsze null. Brak pola częstotliwości, trzeba ją wyliczać. Dla ETF brak dat wypłaty.
- Jakość danych do pilnowania:
  - SU.PA 2025 oznaczona „Interim”, choć Schneider płaci raz w roku [H];
  - część dat ogłoszenia GSK sprzed roku lub więcej przed wypłatą (np. 2024-11-11 dla wypłaty 2026-04).
- **Jednostki:** notowania LSE w GBX (pensy), dywidendy LSE w GBP. Przy FMP dywidenda GSK.L była w pensach (17). Każde źródło trzeba normalizować osobno.
- Typ instrumentu od dostawcy jest zawodny (4GLD = „ETF”, a to ETC). Klasa aktywa musi pochodzić z potwierdzenia użytkownika.
- Wyszukiwarka zwraca kilka notowań (4GLD: XETRA i Frankfurt `F` bez ISIN). Wybór giełdy musi być jawny.
- Konwencja symboli różni się od FMP: `GSK.L` → `GSK.LSE`, `4GLD.DE` → `4GLD.XETRA`; `SU.PA` bez zmian.
- Plany EODHD dla osób prywatnych nie obejmują użytku komercyjnego [Z]. Prywatna aplikacja dla dwóch osób z gospodarstwa domowego najpewniej się mieści [H].

## Porównanie z FMP Premium (P0a)

| | FMP Premium (69 USD/mies.) | EODHD Free (0 USD) | EODHD EOD All World (19,99 USD/mies. lub 199 USD/rok) [Z] |
|---|---|---|---|
| Cena bieżąca Paryż / Londyn / Xetra | ✅ / ✅ / ✅ (z profilu) | ✅ / ✅ / ✅ | ✅ |
| Historia Paryż / Xetra | ❌ 402 | ✅ 1 rok | ✅ 30+ lat [Z] |
| Historia Londyn | ✅ od 2007 | ✅ 1 rok | ✅ [Z] |
| Dywidendy Paryż / Londyn / ETF | ❌ / ✅ / — | ✅ / ✅ / ✅ | ✅ [Z] |
| Waluta notowania i ISIN | ✅ | ✅ | ✅ |
| Limit | 750/min | **20/dzień** | 100 000/dzień [Z] |
| USA (scanner, fundamenty, skład S&P 500) | ✅ | nie dotyczy | nie dotyczy |

## Rekomendacja

- **Podział:** FMP dla USA (scanner i dotychczasowe pozycje z USA, bez zmian) + EODHD dla notowań europejskich (akcje, ETF, ETC).
- **Koszt:**
  - P0b: **FMP Starter 29 USD/mies. + EODHD Free 0 USD**. Kilka europejskich pozycji przy dziennym cache to kilka zapytań dziennie, w limicie 20.
  - Od P2/P3 (historia 5Y/MAX, dywidendy dla wielu instrumentów): + EODHD EOD All World 19,99 USD/mies. (lub 199 USD/rok).
  - Docelowo ok. 49 USD/mies. (rozliczenie miesięczne) albo ok. 36 USD/mies. (oba plany rocznie: 19 + 16,58).
- Warunek: test FMP Starter po 28.10 potwierdzi, że scanner (skład historyczny S&P 500) działa na Starterze.
