"""Liczenie pozycji portfela "on-read" (Faza 7, UI + PORTFOLIO V0).

Zero I/O -- czyste funkcje nad listami wierszy transakcji (sqlite3.Row
albo dict), ten sam wzorzec co `report.py`/`live_scan.py` (czysta
funkcja formatująca/licząca, wołający -- `ui/queries.py` -- decyduje,
skąd biorą się dane). Pozycje NIE są cache'owane jako mutowalne kolumny
na `positions` (Decyzja właścicielki, Faza 7 / sekcja 5 design review:
"liczone deterministycznie z transakcji przy każdym odczycie, żeby
wykluczyć rozjazd cache'u z transakcjami").

COST BASIS — V0 używa WYŁĄCZNIE metody average-cost: przy sprzedaży
`invested` tej subpozycji (broker, currency) jest redukowane
PROPORCJONALNIE do sprzedanych akcji względem akcji posiadanych w
momencie sprzedaży (chronologicznie, nie "wszystkie zakupy potem
wszystkie sprzedaże"). `sale_transactions.cost_basis_method_used`
istnieje w schemacie (zgodność z sekcją 16 design review) jako
zarezerwowane na przyszłość FIFO/LIFO/specific-lot -- NIE jest tu
czytane.

BROKER/CURRENCY — Decyzja właścicielki, Faza 7 pkt 4: SELL na jednym
brokerze zmniejsza WYŁĄCZNIE subpozycję tego brokera (nigdy arbitralnie
globalną pulę instrumentu) -- dlatego agregacja grupuje transakcje po
(broker, currency) PRZED zsumowaniem do poziomu pozycji/portfela.
Różne waluty NIGDY nie są sumowane (sekcja 12 specyfikacji) -- wszystkie
pieniężne wyniki są słownikami `{currency: value}`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class BrokerCurrencySubposition:
    """Jedna subpozycja (broker, currency) jednej `position_id`."""

    broker: str
    currency: str
    shares_held: float
    total_invested: float  # 0.0 dla subpozycji złożonej wyłącznie z BONUS
    avg_price: float | None  # None gdy shares_held <= 0 (w pełni sprzedana/nigdy nie była kupiona)
    # Sposoby nabycia, które KIEDYKOLWIEK zasiliły tę subpozycję (nie
    # "nadal posiadane" -- uproszczenie dla czytelnej etykiety UI, np.
    # "Zakup + bonus"). Posortowane dla deterministycznego porównania w testach.
    acquisition_types: tuple[str, ...]
    # Wypełniane DOPIERO w `compute_position_summary` (wymaga current_price
    # z zewnątrz) -- `None`, dopóki cena nie jest znana LUB subpozycja jest
    # w innej walucie niż cena. NIGDY nie czytać `PositionSummary.
    # current_value_by_currency` per subpozycja -- to jest suma WSZYSTKICH
    # subpozycji tej waluty, nie wartość TEJ JEDNEJ (realny bug znaleziony
    # przy weryfikacji wizualnej UI, Faza 7 KROK 6).
    current_value: float | None = None
    unrealized_pl: float | None = None


@dataclass(frozen=True)
class PositionSummary:
    position_id: int
    shares_held: float
    by_broker_currency: tuple[BrokerCurrencySubposition, ...]
    invested_by_currency: dict[str, float]
    # None (nie {}) == current_price nieznana -- UI musi pokazać
    # "cena bieżąca niedostępna", nigdy fałszywą wartość 0.
    current_value_by_currency: dict[str, float] | None
    unrealized_pl_by_currency: dict[str, float] | None


def compute_broker_currency_subpositions(
    purchases: list, sales: list,
) -> list[BrokerCurrencySubposition]:
    """`purchases`/`sales` to wiersze `purchase_transactions`/
    `sale_transactions` (sqlite3.Row albo dict) dla JEDNEJ `position_id`.
    Zdarzenia scalane i sortowane CHRONOLOGICZNIE (nie "najpierw
    wszystkie zakupy") -- inaczej proporcjonalna redukcja invested przy
    sprzedaży użyłaby złej bazy akcji, gdy sprzedaż nastąpiła między
    dwoma zakupami."""
    events: list[tuple[str, str, str, str, float, float | None, str | None]] = []
    for p in purchases:
        events.append((
            p["purchase_date"], "PURCHASE", p["broker"], p["currency"], p["shares"],
            p["total_invested"], p["acquisition_type"],
        ))
    for s in sales:
        events.append((s["sale_date"], "SALE", s["broker"], s["currency"], s["shares"], None, None))
    events.sort(key=lambda e: e[0])

    state: dict[tuple[str, str], dict] = {}
    for _date, kind, broker, currency, shares, invested, acquisition_type in events:
        group = state.setdefault(
            (broker, currency), {"shares": 0.0, "invested": 0.0, "acquisition_types": set()},
        )
        if kind == "PURCHASE":
            group["shares"] += shares
            group["invested"] += invested if invested is not None else 0.0
            group["acquisition_types"].add(acquisition_type)
        else:
            if group["shares"] > 0:
                # Average cost: redukcja invested proporcjonalnie do
                # sprzedanych akcji względem akcji posiadanych TERAZ
                # (nie względem całej historii zakupów).
                fraction_sold = min(shares / group["shares"], 1.0)
                group["invested"] -= group["invested"] * fraction_sold
            group["shares"] -= shares

    result = []
    for (broker, currency), group in state.items():
        shares_held = group["shares"]
        total_invested = group["invested"]
        avg_price = (total_invested / shares_held) if shares_held > 0 else None
        result.append(BrokerCurrencySubposition(
            broker=broker, currency=currency, shares_held=shares_held,
            total_invested=total_invested, avg_price=avg_price,
            acquisition_types=tuple(sorted(group["acquisition_types"])),
        ))
    return result


def compute_position_summary(
    position_id: int,
    purchases: list,
    sales: list,
    *,
    current_price: float | None = None,
    current_price_currency: str | None = None,
) -> PositionSummary:
    """`current_price`/`current_price_currency` to JEDNA cena (z
    `price_daily`/profilu FMP) w JEDNEJ walucie -- jeśli subpozycja jest
    w innej walucie niż `current_price_currency`, jej bieżąca wartość
    jest NIEZNANA (nigdy przeliczana bez FX engine, sekcja 12
    specyfikacji) i nie trafia do `current_value_by_currency`.

    Każda subpozycja (`BrokerCurrencySubposition.current_value`) dostaje
    WŁASNĄ, osobno policzoną wartość (`shares_held * current_price`) --
    agregaty `current_value_by_currency`/`unrealized_pl_by_currency` są
    PÓŹNIEJ liczone jako suma tych już-policzonych wartości, nigdy
    odwrotnie (żeby UI nigdy nie pomyliło sumy całej pozycji z wartością
    jednej subpozycji -- realny bug znaleziony przy weryfikacji
    wizualnej, Faza 7 KROK 6)."""
    raw_subpositions = compute_broker_currency_subpositions(purchases, sales)

    enriched_subpositions = []
    for s in raw_subpositions:
        current_value = None
        unrealized_pl = None
        if current_price is not None and current_price_currency is not None and s.currency == current_price_currency:
            current_value = s.shares_held * current_price
            unrealized_pl = current_value - s.total_invested
        enriched_subpositions.append(replace(s, current_value=current_value, unrealized_pl=unrealized_pl))

    shares_held = sum(s.shares_held for s in enriched_subpositions)

    invested_by_currency: dict[str, float] = {}
    for s in enriched_subpositions:
        invested_by_currency[s.currency] = invested_by_currency.get(s.currency, 0.0) + s.total_invested

    current_value_by_currency: dict[str, float] | None = None
    unrealized_pl_by_currency: dict[str, float] | None = None
    priced_subpositions = [s for s in enriched_subpositions if s.current_value is not None]
    if priced_subpositions:
        current_value_by_currency = {}
        for s in priced_subpositions:
            current_value_by_currency[s.currency] = current_value_by_currency.get(s.currency, 0.0) + s.current_value
        unrealized_pl_by_currency = {
            currency: value - invested_by_currency.get(currency, 0.0)
            for currency, value in current_value_by_currency.items()
        }

    return PositionSummary(
        position_id=position_id, shares_held=shares_held,
        by_broker_currency=tuple(enriched_subpositions),
        invested_by_currency=invested_by_currency,
        current_value_by_currency=current_value_by_currency,
        unrealized_pl_by_currency=unrealized_pl_by_currency,
    )


def merge_currency_dicts(dicts: list[dict[str, float] | None]) -> dict[str, float]:
    """Sumuje listę `{currency: value}` (albo `None`, pomijany) po
    walucie -- NIGDY po sumie różnych walut (sekcja 12 specyfikacji).
    Używane do zbudowania agregatu portfela z agregatów pozycji."""
    merged: dict[str, float] = {}
    for d in dicts:
        if d is None:
            continue
        for currency, value in d.items():
            merged[currency] = merged.get(currency, 0.0) + value
    return merged


def compute_portfolio_bar_summary(
    summaries: list[PositionSummary], *, review_needed_count: int,
) -> dict:
    """Agregat do jednoliniowego paska portfela (sekcja 5
    specyfikacji) -- liczba pozycji, wartość bieżąca/zainwestowany
    kapitał/P&L PER CURRENCY (nigdy jedna fałszywa suma), liczba pozycji
    wymagających review."""
    return {
        "position_count": len(summaries),
        "invested_by_currency": merge_currency_dicts([s.invested_by_currency for s in summaries]),
        "current_value_by_currency": merge_currency_dicts(
            [s.current_value_by_currency for s in summaries]
        ),
        "unrealized_pl_by_currency": merge_currency_dicts(
            [s.unrealized_pl_by_currency for s in summaries]
        ),
        "review_needed_count": review_needed_count,
    }
