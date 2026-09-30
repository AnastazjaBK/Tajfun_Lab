"""Proof Run (Faza 5.3, zatwierdzony przez właściciela 2026-09-30,
PRZED jakąkolwiek implementacją produkcyjną): czy zero-gap adjacency
jest wystarczająco silnym i jednoznacznym sygnałem do odzyskiwania
historycznego CIK dla obecnych `CIK_UNRESOLVED` tickerów (np.
ANTM->ELV, FB->META — spółki, które zmieniły ticker w oknie 2012+, a
`resolve_tickers_to_cik` rozwiązuje wyłącznie względem DZISIEJSZEGO
mapowania SEC, więc stary ticker zostaje nierozwiązany).

Celowo TANI i WYŁĄCZNIE LOKALNY względem danych: SEC company_tickers.json
+ fja05680/sp500 (dokładnie Krok 1-2 `cli.py build-universe-membership`,
reużyte wprost) + SEC `formerNames` per kandydat. BEZ FMP.

Dwie niezależne części, świadomie rozdzielone (patrz zastrzeżenie w
`universe_ticker_adjacency` — sama adjacency NIE jest dowodem tożsamości
spółki, może to być TICKER RENAME SAME COMPANY albo INDEX REPLACEMENT
DIFFERENT COMPANY):
  A) `analyze_ticker_adjacency` — czysto strukturalna klasyfikacja
     wszystkich 196 obecnych CIK_UNRESOLVED tickerów.
  B) `former_name_corroborates_boundary` — dla KAŻDEGO strukturalnie
     jednoznacznego kandydata, niezależna weryfikacja przez SEC
     `formerNames` (zmiana nazwy prawnej spółki w pobliżu daty
     zero-gap). BRAK korroboracji NIE oznacza automatycznie "to
     coincidental index replacement" — może to znaczyć, że spółka
     zmieniła TYLKO ticker (nie nazwę prawną), albo że `formerNames`
     nie obejmuje tej zmiany. Oba przypadki (skorroborowane i
     nieskorroborowane) są jawnie raportowane osobno, NIGDY nie są
     traktowane jako równoważne "potwierdzone".

WYŁĄCZNIE DIAGNOSTYCZNE — nie zapisuje nic do bazy, nie zmienia
`universe_membership`, nie implementuje żadnej metody rozwiązywania
CIK produkcyjnie. To jest pomiar, nie decyzja.

    python -m buffett_scanner.providers.ticker_adjacency_proof_run

Wymaga SEC_EDGAR_USER_AGENT (NIE wymaga FMP_API_KEY)."""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    window_from_cutoff,
)
from buffett_scanner.universe_ticker_adjacency import (
    analyze_ticker_adjacency,
    former_name_corroborates_boundary,
)

FORMER_NAME_TOLERANCE_DAYS = 3

# Kontrolne CIK-i do surowej diagnostyki formerNames (dodane po tym, jak
# realny Proof Run 2026-09-30 dał 0/107 korroboracji — łącznie ze znanym,
# potwierdzonym wcześniej w tej sesji rename ANTM/ELV). Cel: ustalić, czy
# pole `formerNames` w ogóle zawiera dane dla tych spółek, i jeśli tak, w
# jakiej odległości od daty zero-gap leżą — zanim cokolwiek wywnioskujemy
# o przydatności tego sygnału jako niezależnej weryfikacji.
CONTROL_CIKS = [
    ("ANTM -> ELV (znany prawdziwy rename, zero-gap 2022-06-28)", "1156039"),
    ("FB -> META (znany prawdziwy rename, zero-gap 2022-06-09)", "1326801"),
    ("EA -> FERG (podejrzany fałszywy pozytyw, zero-gap 2026-08-05)", "2011641"),
    ("BK -> BNY (podejrzany fałszywy pozytyw, zero-gap 2026-05-21)", "1390777"),
]


def main() -> int:
    config = load_config()
    try:
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1
    cutoff = config.backtest.window_start

    print("== Krok 1: SEC company_tickers_full (identycznie jak build-universe-membership) ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_full = sec_client.get_company_tickers_full()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania SEC company_tickers.json: {exc}", file=sys.stderr)
            return 1
        sec_ticker_map = {t: info["cik"] for t, info in sec_full.items()}
        print(f"SEC: {len(sec_full)} tickerów.")

        print(f"\n== Krok 2: fja05680/sp500, okno {cutoff}+, rozwiązanie CIK ==")
        try:
            fja_csv = fetch_components_csv()
        except Sp500HistoryError as exc:
            print(f"BŁĄD pobierania fja05680/sp500: {exc}", file=sys.stderr)
            return 1
        fja_rows = parse_components_csv(fja_csv)
        fja_window = window_from_cutoff(fja_rows, cutoff)
        if not fja_window:
            print(f"BŁĄD: fja05680 nie ma żadnego wiersza <= {cutoff}.", file=sys.stderr)
            return 1
        fja_intervals = build_ticker_intervals(fja_window, cutoff_date=cutoff)
        fja_all_tickers = distinct_tickers(fja_window)
        resolution = resolve_tickers_to_cik(fja_all_tickers, sec_ticker_map)
        print(
            f"fja05680: {len(fja_all_tickers)} tickerów w oknie, "
            f"rozwiązanych={len(resolution.resolved)}, "
            f"CIK_UNRESOLVED={len(resolution.unresolved)}"
        )

        print("\n== Krok 3 (część A): analiza strukturalna zero-gap adjacency ==")
        analyses = analyze_ticker_adjacency(
            fja_intervals, resolution.resolved, resolution.unresolved
        )
        by_status: dict[str, list] = {}
        for a in analyses:
            by_status.setdefault(a.status, []).append(a)
        print(f"Razem CIK_UNRESOLVED przeanalizowanych: {len(analyses)}")
        for status in ("NO_CANDIDATE", "UNIQUE_CANDIDATE", "AMBIGUOUS_CONFLICTING_CIK"):
            print(f"  {status}: {len(by_status.get(status, []))}")

        unique_analyses = by_status.get("UNIQUE_CANDIDATE", [])
        print(
            f"\n== Krok 4 (część B): niezależna weryfikacja przez SEC `formerNames` "
            f"dla {len(unique_analyses)} strukturalnie jednoznacznych kandydatów "
            f"(tolerancja {FORMER_NAME_TOLERANCE_DAYS} dni) =="
        )
        former_names_cache: dict[str, list[dict]] = {}
        corroborated = []
        not_corroborated = []
        for a in unique_analyses:
            cik = a.distinct_ciks[0]
            if cik not in former_names_cache:
                try:
                    former_names_cache[cik] = sec_client.get_former_names(cik)
                except SecEdgarError as exc:
                    print(f"  OSTRZEŻENIE: get_former_names({cik}) nieudane: {exc}", file=sys.stderr)
                    former_names_cache[cik] = []
            fnames = former_names_cache[cik]
            best_match = None
            for cand in a.candidates:
                m = former_name_corroborates_boundary(
                    fnames, cand.boundary_date, tolerance_days=FORMER_NAME_TOLERANCE_DAYS
                )
                if m is not None and (best_match is None or abs(m.day_diff) < abs(best_match.day_diff)):
                    best_match = m
            if best_match is not None:
                corroborated.append((a, best_match))
            else:
                not_corroborated.append(a)

        print(f"Skorroborowane przez zmianę nazwy prawnej (SEC formerNames): {len(corroborated)}")
        print(f"NIESKORROBOROWANE (strukturalnie jednoznaczne, ale brak wsparcia w formerNames): {len(not_corroborated)}")

        print("\n== Tabela: skorroborowane (old_ticker -> new_ticker -> zero-gap date -> CIK -> evidence) ==")
        for a, m in sorted(corroborated, key=lambda pair: pair[0].unresolved_ticker):
            cand = a.candidates[0]
            print(
                f"  {a.unresolved_ticker} -> {cand.adjacent_ticker} "
                f"[{cand.boundary_date}] -> CIK={a.distinct_ciks[0]} "
                f"| formerName={m.name!r} to_date={m.to_date} day_diff={m.day_diff}"
            )

        print("\n== Tabela: NIESKORROBOROWANE (strukturalnie jednoznaczne, bez potwierdzenia formerNames) ==")
        for a in sorted(not_corroborated, key=lambda x: x.unresolved_ticker):
            for cand in a.candidates:
                print(
                    f"  {a.unresolved_ticker} -> {cand.adjacent_ticker} "
                    f"[{cand.boundary_date}] -> CIK={a.distinct_ciks[0]} | brak formerNames w tolerancji"
                )

        print("\n== Tabela: AMBIGUOUS_CONFLICTING_CIK (wiele różnych CIK-ów jako kandydaci) ==")
        for a in sorted(by_status.get("AMBIGUOUS_CONFLICTING_CIK", []), key=lambda x: x.unresolved_ticker):
            print(f"  {a.unresolved_ticker}: {len(a.distinct_ciks)} odrębnych CIK-ów, {len(a.candidates)} kandydatów")
            for cand in a.candidates:
                print(f"    -> {cand.adjacent_ticker} [{cand.boundary_date}] CIK={cand.adjacent_cik} dir={cand.direction}")

        print("\n== Podsumowanie ==")
        print(f"Obecnych CIK_UNRESOLVED: {len(analyses)}")
        print(f"  NO_CANDIDATE (realne wyjścia z indeksu / brak sygnału adjacency): {len(by_status.get('NO_CANDIDATE', []))}")
        print(f"  AMBIGUOUS_CONFLICTING_CIK (wiele kandydatów, sygnał odrzucony): {len(by_status.get('AMBIGUOUS_CONFLICTING_CIK', []))}")
        print(f"  UNIQUE_CANDIDATE strukturalnie: {len(unique_analyses)}")
        print(f"    z czego skorroborowane formerNames: {len(corroborated)}")
        print(f"    z czego NIESKORROBOROWANE: {len(not_corroborated)}")
        print(
            "\nUWAGA: 'skorroborowane' oznacza, że zmiana nazwy prawnej spółki w SEC "
            "wystąpiła blisko daty zero-gap — silny, ale wciąż NIE definitywny dowód "
            "(nie każdy rename tickera wiąże się ze zmianą nazwy prawnej, i odwrotnie). "
            "'Nieskorroborowane' NIE oznacza fałszywy pozytyw — może to być realny rename "
            "bez zmiany nazwy prawnej, albo `formerNames` nieobecne/niepełne dla tej spółki. "
            "Żadna z tych klasyfikacji nie jest samodzielną podstawą do wdrożenia "
            "INFERRED_VIA_ADJACENT_TICKER produkcyjnie — to wymaga decyzji właściciela "
            "po przejrzeniu tych wyników."
        )

        print(
            "\n== Krok 5: surowa diagnostyka formerNames dla kontrolnych CIK "
            "(po znalezisku 0/107 korroboracji w poprzednim Proof Run) =="
        )
        for label, cik in CONTROL_CIKS:
            print(f"  -- {label}, CIK={cik} --")
            try:
                raw = sec_client.get_former_names(cik)
            except SecEdgarError as exc:
                print(f"    BŁĄD get_former_names({cik}): {exc}")
                continue
            if not raw:
                print("    formerNames: PUSTA LISTA (pole nieobecne albo bez wpisów dla tego CIK).")
                continue
            for entry in raw:
                print(f"    name={entry['name']!r} from={entry['from_date']} to={entry['to_date']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
