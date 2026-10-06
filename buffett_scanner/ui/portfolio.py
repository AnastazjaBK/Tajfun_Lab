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

from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerCurrencySubposition:
    """Jedna subpozycja (broker, currency) jednej `position_id`."""

    broker: str
    currency: str
    shares_held: float
    total_invested: float  # 0.0 dla subpozycji złożonej wyłącznie z BONUS
    avg_price: float | None  # None gdy shares_held <= 0 (w pełni sprzedana/nigdy nie była kupiona)


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
    events: list[tuple[str, str, str, str, float, float | None]] = []
    for p in purchases:
        events.append((p["purchase_date"], "BUY", p["broker"], p["currency"], p["shares"], p["total_invested"]))
    for s in sales:
        events.append((s["sale_date"], "SELL", s["broker"], s["currency"], s["shares"], None))
    events.sort(key=lambda e: e[0])

    state: dict[tuple[str, str], dict[str, float]] = {}
    for _date, kind, broker, currency, shares, invested in events:
        group = state.setdefault((broker, currency), {"shares": 0.0, "invested": 0.0})
        if kind == "BUY":
            group["shares"] += shares
            group["invested"] += invested if invested is not None else 0.0
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
    specyfikacji) i nie trafia do `current_value_by_currency`."""
    subpositions = compute_broker_currency_subpositions(purchases, sales)
    shares_held = sum(s.shares_held for s in subpositions)

    invested_by_currency: dict[str, float] = {}
    for s in subpositions:
        invested_by_currency[s.currency] = invested_by_currency.get(s.currency, 0.0) + s.total_invested

    current_value_by_currency: dict[str, float] | None = None
    unrealized_pl_by_currency: dict[str, float] | None = None
    if current_price is not None and current_price_currency is not None:
        current_value_by_currency = {}
        for s in subpositions:
            if s.currency != current_price_currency:
                continue  # inna waluta -- bieżąca wartość nieznana bez FX, nie zgadujemy
            current_value_by_currency[s.currency] = (
                current_value_by_currency.get(s.currency, 0.0) + s.shares_held * current_price
            )
        if current_value_by_currency:
            unrealized_pl_by_currency = {
                currency: value - invested_by_currency.get(currency, 0.0)
                for currency, value in current_value_by_currency.items()
            }

    return PositionSummary(
        position_id=position_id, shares_held=shares_held,
        by_broker_currency=tuple(subpositions),
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
