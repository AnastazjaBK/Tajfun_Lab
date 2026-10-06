"""Testy czystych funkcji liczenia pozycji portfela (Faza 7, UI +
PORTFOLIO V0). Zero bazy danych -- fejkowe wiersze transakcji jako
dict (pola odczytywane przez `[...]`, zgodnie z `sqlite3.Row`)."""

from __future__ import annotations

import pytest

from buffett_scanner.ui.portfolio import (
    compute_broker_currency_subpositions,
    compute_portfolio_bar_summary,
    compute_position_summary,
    merge_currency_dicts,
)


def _purchase(*, broker, currency, date, shares, total_invested, acquisition_type="BUY"):
    return {
        "broker": broker, "currency": currency, "purchase_date": date, "shares": shares,
        "total_invested": total_invested, "acquisition_type": acquisition_type,
    }


def _sale(*, broker, currency, date, shares):
    return {"broker": broker, "currency": currency, "sale_date": date, "shares": shares}


def test_bonus_only_subposition_has_zero_invested_and_valid_avg_price():
    """Test (specyfikacja właścicielki, sekcja 10): BONUS -- shares
    zwiększają pozycję normalnie, invested=0, avg_price=0 (koszt/akcję=0,
    nie None -- akcje SĄ posiadane, po prostu za darmo)."""
    purchases = [_purchase(
        broker="TRADE_REPUBLIC", currency="USD", date="2026-05-01", shares=3.0,
        total_invested=0.0, acquisition_type="BONUS",
    )]
    result = compute_broker_currency_subpositions(purchases, [])
    assert len(result) == 1
    sub = result[0]
    assert sub.shares_held == 3.0
    assert sub.total_invested == 0.0
    assert sub.avg_price == 0.0
    assert sub.acquisition_types == ("BONUS",)


def test_two_brokers_same_position_tracked_separately():
    """Test (sekcja 7): AAPL BONUS na Trade Republic + BUY na Revolut
    pod JEDNĄ position -- dwie odrębne subpozycje."""
    purchases = [
        _purchase(
            broker="TRADE_REPUBLIC", currency="USD", date="2026-05-01", shares=3.0,
            total_invested=0.0, acquisition_type="BONUS",
        ),
        _purchase(broker="REVOLUT", currency="USD", date="2026-06-01", shares=2.0, total_invested=380.0),
    ]
    result = {s.broker: s for s in compute_broker_currency_subpositions(purchases, [])}
    assert result["TRADE_REPUBLIC"].shares_held == 3.0
    assert result["TRADE_REPUBLIC"].total_invested == 0.0
    assert result["TRADE_REPUBLIC"].acquisition_types == ("BONUS",)
    assert result["REVOLUT"].shares_held == 2.0
    assert result["REVOLUT"].total_invested == 380.0
    assert result["REVOLUT"].avg_price == 190.0
    assert result["REVOLUT"].acquisition_types == ("BUY",)


def test_subposition_mixing_buy_and_bonus_reports_both_acquisition_types():
    purchases = [
        _purchase(
            broker="REVOLUT", currency="USD", date="2026-05-01", shares=2.0,
            total_invested=0.0, acquisition_type="BONUS",
        ),
        _purchase(broker="REVOLUT", currency="USD", date="2026-06-01", shares=1.0, total_invested=190.0),
    ]
    result = compute_broker_currency_subpositions(purchases, [])
    assert result[0].acquisition_types == ("BONUS", "BUY")


def test_sell_on_one_broker_never_reduces_other_brokers_subposition():
    """Test KLUCZOWY (Decyzja właścicielki, sekcja 7, "WAŻNA REGUŁA"):
    SELL z Revolut zmniejsza WYŁĄCZNIE subpozycję Revolut, Trade
    Republic (3 BONUS shares) zostaje nietknięte."""
    purchases = [
        _purchase(broker="TRADE_REPUBLIC", currency="USD", date="2026-05-01", shares=3.0, total_invested=0.0),
        _purchase(broker="REVOLUT", currency="USD", date="2026-06-01", shares=2.0, total_invested=380.0),
    ]
    sales = [_sale(broker="REVOLUT", currency="USD", date="2026-07-01", shares=1.0)]
    result = {s.broker: s for s in compute_broker_currency_subpositions(purchases, sales)}
    assert result["TRADE_REPUBLIC"].shares_held == 3.0
    assert result["TRADE_REPUBLIC"].total_invested == 0.0
    assert result["REVOLUT"].shares_held == 1.0
    assert result["REVOLUT"].total_invested == 190.0  # average cost: 50% sprzedane -> 50% invested zostaje


def test_average_cost_uses_chronological_order_not_purchases_then_sales():
    """Test KRYTYCZNY: zdarzenia muszą być przetwarzane chronologicznie.
    Kupno 1 @ 100 (2026-01-01) -> sprzedaż 1 (2026-02-01, 100% udziału w
    MOMENCIE sprzedaży) -> kupno 1 @ 200 (2026-03-01). Jeśli kod
    błędnie liczyłby "najpierw wszystkie zakupy, potem wszystkie
    sprzedaże", sprzedaż zredukowałaby invested względem SUMY 2 akcji
    (100+200=300), nie względem 1 akcji posiadanej w chwili sprzedaży."""
    purchases = [
        _purchase(broker="REVOLUT", currency="USD", date="2026-01-01", shares=1.0, total_invested=100.0),
        _purchase(broker="REVOLUT", currency="USD", date="2026-03-01", shares=1.0, total_invested=200.0),
    ]
    sales = [_sale(broker="REVOLUT", currency="USD", date="2026-02-01", shares=1.0)]
    result = compute_broker_currency_subpositions(purchases, sales)
    sub = result[0]
    # Po chronologii: kupno 1@100 (shares=1, invested=100) -> sprzedaż
    # 1 (100% udziału -> invested spada do 0, shares=0) -> kupno 1@200
    # (shares=1, invested=200).
    assert sub.shares_held == 1.0
    assert sub.total_invested == 200.0


def test_fully_sold_subposition_has_no_avg_price():
    purchases = [_purchase(broker="REVOLUT", currency="USD", date="2026-01-01", shares=2.0, total_invested=200.0)]
    sales = [_sale(broker="REVOLUT", currency="USD", date="2026-02-01", shares=2.0)]
    result = compute_broker_currency_subpositions(purchases, sales)
    sub = result[0]
    assert sub.shares_held == 0.0
    assert sub.avg_price is None


def test_position_summary_computes_current_value_only_for_matching_currency():
    """Test (sekcja 12 specyfikacji): subpozycja w innej walucie niż
    current_price_currency -> bieżąca wartość NIEZNANA dla tej waluty,
    nigdy przeliczana bez FX engine."""
    purchases = [
        _purchase(broker="TRADE_REPUBLIC", currency="USD", date="2026-05-01", shares=10.0, total_invested=1000.0),
        _purchase(broker="REVOLUT", currency="EUR", date="2026-06-01", shares=5.0, total_invested=400.0),
    ]
    summary = compute_position_summary(
        1, purchases, [], current_price=120.0, current_price_currency="USD",
    )
    assert summary.shares_held == 15.0
    assert summary.invested_by_currency == {"USD": 1000.0, "EUR": 400.0}
    assert summary.current_value_by_currency == {"USD": 1200.0}  # 10 * 120
    assert summary.unrealized_pl_by_currency == {"USD": 200.0}  # 1200 - 1000
    # EUR subpozycja: brak wpisu w current_value/pl (nieznana, nie 0).
    assert "EUR" not in (summary.current_value_by_currency or {})


def test_position_summary_subpositions_get_own_current_value_not_position_total():
    """Test KLUCZOWY -- regresja na realny bug znaleziony przy
    weryfikacji wizualnej UI (Faza 7 KROK 6): tabela "Pozycje (rozbicie
    per broker)" pokazywała WARTOŚĆ CAŁEJ POZYCJI na KAŻDYM wierszu
    brokera, zamiast własnej wartości tej subpozycji. 3 akcje BONUS na
    Trade Republic + 1 akcja (po sprzedaży) na Revolut, cena=230 ->
    TR musi mieć WŁASNĄ current_value=690 (nie 920 -- suma całej
    pozycji), Revolut WŁASNĄ current_value=230 (nie 920)."""
    purchases = [
        _purchase(
            broker="TRADE_REPUBLIC", currency="USD", date="2026-05-01", shares=3.0,
            total_invested=0.0, acquisition_type="BONUS",
        ),
        _purchase(broker="REVOLUT", currency="USD", date="2026-06-01", shares=2.0, total_invested=380.0),
    ]
    sales = [_sale(broker="REVOLUT", currency="USD", date="2026-07-01", shares=1.0)]
    summary = compute_position_summary(
        1, purchases, sales, current_price=230.0, current_price_currency="USD",
    )
    by_broker = {s.broker: s for s in summary.by_broker_currency}

    assert by_broker["TRADE_REPUBLIC"].shares_held == 3.0
    assert by_broker["TRADE_REPUBLIC"].current_value == pytest.approx(690.0)  # 3 * 230, NIE 920
    assert by_broker["TRADE_REPUBLIC"].unrealized_pl == pytest.approx(690.0)  # 690 - 0 invested

    assert by_broker["REVOLUT"].shares_held == 1.0
    assert by_broker["REVOLUT"].current_value == pytest.approx(230.0)  # 1 * 230, NIE 920
    assert by_broker["REVOLUT"].unrealized_pl == pytest.approx(40.0)  # 230 - 190 invested

    # Agregat pozycji nadal poprawnie sumuje obie subpozycje.
    assert summary.current_value_by_currency == {"USD": pytest.approx(920.0)}
    assert summary.unrealized_pl_by_currency == {"USD": pytest.approx(730.0)}


def test_position_summary_subposition_in_other_currency_has_no_current_value():
    purchases = [_purchase(broker="OTHER", currency="EUR", date="2026-05-01", shares=5.0, total_invested=400.0)]
    summary = compute_position_summary(1, purchases, [], current_price=120.0, current_price_currency="USD")
    sub = summary.by_broker_currency[0]
    assert sub.current_value is None
    assert sub.unrealized_pl is None


def test_position_summary_without_current_price_leaves_value_and_pl_none():
    """Test (sekcja 19 specyfikacji): brak current_price (np. pozycja
    bez CIK, jeszcze niezweryfikowana przez FMP) -> "cena bieżąca
    niedostępna", NIGDY current_value=0 jako substytut."""
    purchases = [_purchase(broker="OTHER", currency="EUR", date="2026-05-01", shares=5.0, total_invested=400.0)]
    summary = compute_position_summary(1, purchases, [])
    assert summary.current_value_by_currency is None
    assert summary.unrealized_pl_by_currency is None
    assert summary.invested_by_currency == {"EUR": 400.0}


def test_merge_currency_dicts_sums_per_currency_never_across():
    merged = merge_currency_dicts([
        {"USD": 100.0, "EUR": 50.0},
        {"USD": 200.0},
        None,
        {"PLN": 10.0},
    ])
    assert merged == {"USD": 300.0, "EUR": 50.0, "PLN": 10.0}


def test_portfolio_bar_summary_aggregates_across_positions_per_currency():
    purchases_a = [_purchase(broker="TRADE_REPUBLIC", currency="USD", date="2026-01-01", shares=10.0, total_invested=1000.0)]
    purchases_b = [_purchase(broker="REVOLUT", currency="EUR", date="2026-01-01", shares=5.0, total_invested=400.0)]
    summary_a = compute_position_summary(1, purchases_a, [], current_price=120.0, current_price_currency="USD")
    summary_b = compute_position_summary(2, purchases_b, [], current_price=90.0, current_price_currency="EUR")

    bar = compute_portfolio_bar_summary([summary_a, summary_b], review_needed_count=1)
    assert bar["position_count"] == 2
    assert bar["invested_by_currency"] == {"USD": 1000.0, "EUR": 400.0}
    assert bar["current_value_by_currency"] == {"USD": 1200.0, "EUR": 450.0}
    assert bar["unrealized_pl_by_currency"] == {"USD": 200.0, "EUR": 50.0}
    assert bar["review_needed_count"] == 1
