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

from buffett_scanner.ui.pricing import FxRates, convert


# Faza 11 (P1): sposób przeliczenia kwoty historycznej na PLN.
PLN_RATE_PLN = "PLN"        # transakcja w PLN -- bez przeliczenia
PLN_RATE_ACTUAL = "ACTUAL"  # kurs rzeczywisty brokera zapisany przy transakcji
PLN_RATE_NBP = "NBP"        # kurs średni NBP z dnia roboczego przed transakcją (orientacyjny)


def _field(row, key: str):
    """`sqlite3.Row`/dict bez kolumny (starsze testy, dane sprzed Fazy 11) -> None."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


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
    # Faza 11 (P1). Koszt historyczny w PLN aktualnie posiadanych akcji:
    # każdy zakup przeliczony WŁASNYM kursem z dnia transakcji (nigdy
    # dzisiejszym), zmniejszany proporcjonalnie przy sprzedaży (średni
    # koszt). None == brak kursu dla któregoś zakupu.
    invested_pln: float | None = 0.0
    pln_cost_estimated: bool = False  # True == choć jeden kurs to NBP (orientacyjny), nie kurs brokera
    # Wynik zrealizowany: przychód ze sprzedaży (akcje x cena - opłaty
    # sprzedaży) minus koszt sprzedanej części (średni koszt). Opłaty
    # zakupu są już w `total_invested` ("cała kwota, która zeszła z konta").
    realized_pl: float | None = 0.0
    realized_pl_pln: float | None = 0.0
    current_value_pln: float | None = None
    unrealized_pl_pln: float | None = None


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
    # Faza 11 (P0b): skąd i z kiedy jest cena bieżąca (wypełniane w
    # `ui/queries.get_position_summary`, nie liczone tutaj).
    quote_source: str | None = None
    quote_as_of: str | None = None
    quote_stale: bool = False


def compute_broker_currency_subpositions(
    purchases: list, sales: list, *, pln_rate_fn=None,
) -> list[BrokerCurrencySubposition]:
    """`purchases`/`sales` to wiersze `purchase_transactions`/
    `sale_transactions` (sqlite3.Row albo dict) dla JEDNEJ `position_id`.
    Zdarzenia scalane i sortowane CHRONOLOGICZNIE (nie "najpierw
    wszystkie zakupy") -- inaczej proporcjonalna redukcja invested przy
    sprzedaży użyłaby złej bazy akcji, gdy sprzedaż nastąpiła między
    dwoma zakupami.

    `pln_rate_fn(currency, date, fx_rate_actual) -> (kurs, rodzaj) | None`
    (Faza 11, P1) -- PLN za 1 jednostkę waluty transakcji. Brak funkcji
    -> wartości PLN tylko dla transakcji w PLN."""
    def rate(currency: str, date: str, actual):
        if currency.upper() == "PLN":
            return 1.0, PLN_RATE_PLN
        if pln_rate_fn is None:
            return None
        return pln_rate_fn(currency, date, actual)

    events = []
    for p in purchases:
        events.append((p["purchase_date"], 0, "PURCHASE", p))
    for s in sales:
        events.append((s["sale_date"], 1, "SALE", s))
    events.sort(key=lambda e: (e[0], e[1]))

    state: dict[tuple[str, str], dict] = {}
    for date, _order, kind, row in events:
        broker, currency, shares = row["broker"], row["currency"], row["shares"]
        group = state.setdefault((broker, currency), {
            "shares": 0.0, "invested": 0.0, "invested_pln": 0.0, "estimated": False,
            "realized": 0.0, "realized_pln": 0.0, "acquisition_types": set(),
        })
        fx = rate(currency, date, _field(row, "fx_rate_actual"))
        if fx is not None and fx[1] == PLN_RATE_NBP:
            group["estimated"] = True
        if kind == "PURCHASE":
            invested = row["total_invested"] if row["total_invested"] is not None else 0.0
            group["shares"] += shares
            group["invested"] += invested
            if group["invested_pln"] is not None:
                group["invested_pln"] = None if fx is None else group["invested_pln"] + invested * fx[0]
            group["acquisition_types"].add(row["acquisition_type"])
            continue
        fraction_sold = min(shares / group["shares"], 1.0) if group["shares"] > 0 else 0.0
        # Average cost: redukcja invested proporcjonalnie do sprzedanych
        # akcji względem akcji posiadanych TERAZ (nie całej historii).
        cost_removed = group["invested"] * fraction_sold
        cost_removed_pln = None if group["invested_pln"] is None else group["invested_pln"] * fraction_sold
        group["invested"] -= cost_removed
        if group["invested_pln"] is not None:
            group["invested_pln"] -= cost_removed_pln
        group["shares"] -= shares
        sale_price = _field(row, "sale_price")
        proceeds = None if sale_price is None else shares * sale_price - (_field(row, "fees") or 0.0)
        if proceeds is None or group["realized"] is None:
            group["realized"] = None
        else:
            group["realized"] += proceeds - cost_removed
        if proceeds is None or fx is None or cost_removed_pln is None or group["realized_pln"] is None:
            group["realized_pln"] = None
        else:
            group["realized_pln"] += proceeds * fx[0] - cost_removed_pln

    result = []
    for (broker, currency), group in state.items():
        shares_held = group["shares"]
        total_invested = group["invested"]
        avg_price = (total_invested / shares_held) if shares_held > 0 else None
        result.append(BrokerCurrencySubposition(
            broker=broker, currency=currency, shares_held=shares_held,
            total_invested=total_invested, avg_price=avg_price,
            acquisition_types=tuple(sorted(group["acquisition_types"])),
            invested_pln=group["invested_pln"], pln_cost_estimated=group["estimated"],
            realized_pl=group["realized"], realized_pl_pln=group["realized_pln"],
        ))
    return result


def compute_position_summary(
    position_id: int,
    purchases: list,
    sales: list,
    *,
    current_price: float | None = None,
    current_price_currency: str | None = None,
    fx: FxRates | None = None,
    pln_rate_fn=None,
) -> PositionSummary:
    """`current_price`/`current_price_currency` to JEDNA cena (z
    `price_daily`/profilu FMP) w JEDNEJ walucie (głównej -- pensy GBp są
    już przeliczone na GBP w `ui/pricing.normalize_quote`). Subpozycja w
    innej walucie (np. akcje z Paryża kupione w PLN) dostaje wartość
    przeliczoną kursem NBP (`fx`, Faza 9) -- czyli wartość w walucie, w
    której użytkownik faktycznie zapłacił, z efektem kursowym od zakupu.
    Brak kursu -> wartość NIEZNANA (nigdy 0, nigdy zgadnięta) i nie
    trafia do `current_value_by_currency`.

    Faza 11 (P1): `current_value_pln` = wartość dziś (dzisiejszy kurs
    NBP), `unrealized_pl_pln` = ta wartość minus koszt historyczny PLN
    (kursy z dni transakcji, patrz `compute_broker_currency_subpositions`).

    Każda subpozycja (`BrokerCurrencySubposition.current_value`) dostaje
    WŁASNĄ, osobno policzoną wartość (`shares_held * current_price`) --
    agregaty `current_value_by_currency`/`unrealized_pl_by_currency` są
    PÓŹNIEJ liczone jako suma tych już-policzonych wartości, nigdy
    odwrotnie (żeby UI nigdy nie pomyliło sumy całej pozycji z wartością
    jednej subpozycji -- realny bug znaleziony przy weryfikacji
    wizualnej, Faza 7 KROK 6)."""
    raw_subpositions = compute_broker_currency_subpositions(purchases, sales, pln_rate_fn=pln_rate_fn)

    enriched_subpositions = []
    for s in raw_subpositions:
        current_value = None
        unrealized_pl = None
        current_value_pln = None
        unrealized_pl_pln = None
        if current_price is not None and current_price_currency is not None:
            current_value = convert(s.shares_held * current_price, current_price_currency, s.currency, fx)
            if current_value is not None:
                unrealized_pl = current_value - s.total_invested
                current_value_pln = convert(current_value, s.currency, "PLN", fx)
                if current_value_pln is not None and s.invested_pln is not None:
                    unrealized_pl_pln = current_value_pln - s.invested_pln
        enriched_subpositions.append(replace(
            s, current_value=current_value, unrealized_pl=unrealized_pl,
            current_value_pln=current_value_pln, unrealized_pl_pln=unrealized_pl_pln,
        ))

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


def compute_portfolio_pln_summary(positions_with_summaries: list) -> dict:
    """Faza 11 (P1): podsumowanie portfela w PLN.

    - `value_pln`: wartość dziś pozycji z ceną (dzisiejszy kurs NBP);
    - `cost_pln`: koszt historyczny PLN (kursy z dni transakcji) TYCH
      SAMYCH, wycenionych pozycji -- żeby zysk = wartość - koszt;
    - `cost_pln_all`: koszt historyczny wszystkich posiadanych pozycji;
    - `realized_pl_pln`: wynik zrealizowany na sprzedażach;
    - `missing`: instrumenty bez ceny / bez kursu (suma jest wtedy CZĘŚCIOWA);
    - `estimated`: choć jeden koszt liczony kursem NBP (orientacyjnym);
    - `by_broker`: {broker: {"value_pln", "cost_pln"}} dla wycenionych.
    Nigdy nie zastępuje braków zerem."""
    value = cost = cost_all = realized = 0.0
    missing: list[str] = []
    estimated = False
    by_broker: dict[str, dict[str, float]] = {}
    for position, summary in positions_with_summaries:
        label = position["ticker"]
        for sub in summary.by_broker_currency:
            estimated = estimated or sub.pln_cost_estimated
            if sub.realized_pl_pln is None:
                if f"{label} (wynik sprzedaży)" not in missing:
                    missing.append(f"{label} (wynik sprzedaży)")
            else:
                realized += sub.realized_pl_pln
            if sub.shares_held <= 1e-12:
                continue
            if sub.invested_pln is None:
                if label not in missing:
                    missing.append(label)
                continue
            cost_all += sub.invested_pln
            if sub.current_value_pln is None:
                if label not in missing:
                    missing.append(label)
                continue
            value += sub.current_value_pln
            cost += sub.invested_pln
            bucket = by_broker.setdefault(sub.broker, {"value_pln": 0.0, "cost_pln": 0.0})
            bucket["value_pln"] += sub.current_value_pln
            bucket["cost_pln"] += sub.invested_pln
    unrealized = value - cost
    return {
        "value_pln": value, "cost_pln": cost, "cost_pln_all": cost_all,
        "unrealized_pl_pln": unrealized, "realized_pl_pln": realized,
        "total_result_pln": unrealized + realized,
        "unrealized_pl_pct": (unrealized / cost * 100.0) if cost > 0 else None,
        "missing": missing, "estimated": estimated, "by_broker": by_broker,
    }
