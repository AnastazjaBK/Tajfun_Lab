"""Faza 5.3c — dualny benchmark BASELINE walk-forward (Decyzja
właścicielki 2026-10-04, specyfikacja podana dokładnie, bez zmian):

PRIMARY — `equal_weighted_pit_universe`: dla każdej `decision_date` i
każdego horyzontu (1m/3m/6m/12m) średni forward price return WSZYSTKICH
spółek z PIT universe (nie tylko kandydatów-CANDIDATE) z wystarczającymi
danymi cenowymi na tę datę. Jawnie NIE nazywany "S&P 500 return" — to nie
jest indeks cap-weighted, tylko equal-weighted przeciętna dostępnego
wtedy universe. Odpowiada na: "Czy scanner wybiera lepsze spółki niż
przeciętna dostępna wtedy spółka z PIT universe?"

SECONDARY — zwrot cenowy SPY, DOKŁADNIE tą samą konwencją forward price
return (close-to-close, bez dywidend/reinwestycji — `forward_return_pct`
z `backtest_harness.py`, ta sama funkcja co dla kandydatów i dla
PRIMARY). Odpowiada na: "Czy scanner wybiera spółki, które później
zachowują się lepiej niż praktyczny benchmark rynku?"

Zero zmiany scoringu/wag/thresholds/hard gates/valuation — to WYŁĄCZNIE
dodatkowa miara porównawcza, licząca się z już wczytanych cen (ta sama
pamięć w pamięci co funnel w `cli.cmd_run_baseline_walk_forward`), zero
nowej logiki PIT, zero nowego providera cen (SPY pobierany tym samym
FMP price-history pathem jak każdy inny ticker)."""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.backtest_harness import FORWARD_RETURN_HORIZONS_MONTHS, forward_return_pct
from buffett_scanner.scanner import PriceBar


def _decision_price_as_of(bars: list[PriceBar], decision_date: str) -> float | None:
    """Ostatni bar z datą <= decision_date — identyczna konwencja ceny
    bazowej jak `evaluate_candidate_at_date`/`BacktestCandidate.decision_
    price` (sekcja 13), żeby benchmark i kandydaci nie różnili się
    definicją punktu startowego zwrotu. `None`, jeśli brak baru <=
    decision_date (nigdy nie ekstrapolujemy do przeszłości)."""
    bars_as_of = [b for b in bars if b.date <= decision_date]
    if not bars_as_of:
        return None
    return max(bars_as_of, key=lambda b: b.date).close


@dataclass(frozen=True)
class BenchmarkSnapshot:
    decision_date: str
    ew_pit_universe_return_1m_pct: float | None
    ew_pit_universe_return_3m_pct: float | None
    ew_pit_universe_return_6m_pct: float | None
    ew_pit_universe_return_12m_pct: float | None
    ew_pit_universe_n_1m: int
    ew_pit_universe_n_3m: int
    ew_pit_universe_n_6m: int
    ew_pit_universe_n_12m: int
    spy_return_1m_pct: float | None
    spy_return_3m_pct: float | None
    spy_return_6m_pct: float | None
    spy_return_12m_pct: float | None


_HORIZON_FIELD_SUFFIX = {1: "1m", 3: "3m", 6: "6m", 12: "12m"}


def compute_benchmark_snapshot(
    *,
    decision_date: str,
    pit_universe_ciks_with_sufficient_price: list[str],
    price_bars_by_cik: dict[str, list[PriceBar]],
    spy_bars: list[PriceBar] | None,
) -> BenchmarkSnapshot:
    """Jedna migawka per decision_date, obejmująca OBA benchmarki —
    odzwierciedla wzorzec `CoverageSnapshot` (jeden obiekt -> jeden
    wiersz w bazie). `pit_universe_ciks_with_sufficient_price` to
    WYŁĄCZNIE spółki z PIT universe tej daty, dla których `classify_data_
    sufficiency` już stwierdził `has_price=True` (ten sam zbiór, nie
    nowa, osobna definicja "wystarczających danych cenowych") —
    kandydaci-CANDIDATE są tu podzbiorem, nie jedynym źródłem."""
    ew_returns: dict[int, float | None] = {}
    ew_n: dict[int, int] = {}
    for h in FORWARD_RETURN_HORIZONS_MONTHS:
        values: list[float] = []
        for cik in pit_universe_ciks_with_sufficient_price:
            full_bars = price_bars_by_cik.get(cik, [])
            decision_price = _decision_price_as_of(full_bars, decision_date)
            if decision_price is None:
                continue
            r = forward_return_pct(full_bars, decision_date, decision_price, h)
            if r is not None:
                values.append(r)
        ew_returns[h] = (sum(values) / len(values)) if values else None
        ew_n[h] = len(values)

    spy_returns: dict[int, float | None] = {h: None for h in FORWARD_RETURN_HORIZONS_MONTHS}
    if spy_bars:
        spy_decision_price = _decision_price_as_of(spy_bars, decision_date)
        if spy_decision_price is not None:
            spy_returns = {
                h: forward_return_pct(spy_bars, decision_date, spy_decision_price, h)
                for h in FORWARD_RETURN_HORIZONS_MONTHS
            }

    return BenchmarkSnapshot(
        decision_date=decision_date,
        ew_pit_universe_return_1m_pct=ew_returns[1],
        ew_pit_universe_return_3m_pct=ew_returns[3],
        ew_pit_universe_return_6m_pct=ew_returns[6],
        ew_pit_universe_return_12m_pct=ew_returns[12],
        ew_pit_universe_n_1m=ew_n[1],
        ew_pit_universe_n_3m=ew_n[3],
        ew_pit_universe_n_6m=ew_n[6],
        ew_pit_universe_n_12m=ew_n[12],
        spy_return_1m_pct=spy_returns[1],
        spy_return_3m_pct=spy_returns[3],
        spy_return_6m_pct=spy_returns[6],
        spy_return_12m_pct=spy_returns[12],
    )
