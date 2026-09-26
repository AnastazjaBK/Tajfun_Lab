"""Defensywny parser CSV holdingów IVV (Faza 5.2, research v1.27) —
zero I/O, czysta transformacja już pobranego tekstu.

Dokładny kształt pliku (liczba wierszy preambuły przed właściwym
nagłówkiem, dokładne nazwy kolumn) jest NIEPOTWIERDZONY bezpośrednim
testem (`ishares.com` zablokowany w sesji interaktywnej) — znany z
opisów narzędzi trzecich: kilka wierszy metadanych (nazwa funduszu,
data "as of"), potem wiersz nagłówka zawierający m.in. `Ticker`,
`Name`, `Sector`, `Asset Class`, `CUSIP`, `ISIN`, potem wiersze danych,
często zakończone stopką/disclaimerem. Parser NIGDY nie zakłada stałej
liczby wierszy preambuły — lokalizuje wiersz nagłówka po obecności
kolumny `Ticker`, a wiersze bez wypełnionego tickera (np. stopka) są
pomijane, nigdy nie fabrykowane."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class IvvHoldingsParseResult:
    header_row_index: int | None  # None = nagłówek nieznaleziony (surowy tekst do ręcznej inspekcji)
    columns: tuple[str, ...]
    rows: tuple[dict, ...]

    @property
    def tickers(self) -> set[str]:
        return {r["Ticker"].strip() for r in self.rows if r.get("Ticker", "").strip()}


def locate_header_row(lines: list[str], *, required_column: str = "Ticker") -> int | None:
    """Znajduje indeks wiersza nagłówka — pierwszy wiersz CSV, którego
    pola zawierają `required_column` dokładnie (nie podciąg — unika
    fałszywego trafienia w wierszu opisowym/disclaimerze). `None`, jeśli
    żaden wiersz nie pasuje."""
    for i, line in enumerate(lines):
        fields = next(csv.reader([line]))
        if required_column in [f.strip() for f in fields]:
            return i
    return None


def parse_ivv_holdings_csv(csv_text: str) -> IvvHoldingsParseResult:
    """Parsuje surowy CSV holdingów IVV. Lokalizuje nagłówek dynamicznie
    (patrz `locate_header_row`), potem parsuje wiersze danych jako
    słowniki wg tego nagłówka. Wiersz bez wypełnionego `Ticker` (np.
    stopka/disclaimer po tabeli) jest pomijany. Brak rozpoznanego
    nagłówka -> `header_row_index=None`, `rows=()` — nigdy nie zgaduje
    struktury, jaką nie udało się potwierdzić."""
    lines = csv_text.splitlines()
    header_idx = locate_header_row(lines)
    if header_idx is None:
        return IvvHoldingsParseResult(header_row_index=None, columns=(), rows=())

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    columns = tuple(reader.fieldnames or ())
    # `None not in r.values()`: csv.DictReader wypełnia BRAKUJĄCE (nie
    # puste) pola wartością None, gdy wiersz ma mniej faktycznych pól
    # niż nagłówek — dokładnie to dzieje się dla wierszy stopki/
    # disclaimeru bez przecinków (cały tekst wpada w pierwszą kolumnę
    # "Ticker", reszta staje się None). Pole obecne, ale puste (np.
    # brak CUSIP dla pozycji cash) to '', nie None — rozróżnienie
    # świadome, nie przypadkowe.
    rows = tuple(r for r in reader if r.get("Ticker", "").strip() and None not in r.values())
    return IvvHoldingsParseResult(header_row_index=header_idx, columns=columns, rows=rows)
