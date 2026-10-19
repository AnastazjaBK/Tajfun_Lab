"""Sprzedaż i zmiana typu transakcji (2026-10-19): BUY -> SELL, sprzedaż
całości i części (z prowizją), BONUS, ponowny zakup po całkowitej
sprzedaży, blokada ujemnego stanu na całej osi czasu. Zapis przez
istniejący mechanizm: nowy wpis + anulowanie starego (nic nie znika)."""

from __future__ import annotations

import pytest

from buffett_scanner import db
from buffett_scanner.ui.portfolio import (
    compute_portfolio_pln_summary,
    compute_position_summary,
    find_negative_holding,
    replace_transaction,
    retype_defaults,
)
from buffett_scanner.ui.pricing import FxRates
from buffett_scanner.ui.queries import TransactionChangeError, apply_transaction_change

FX = FxRates(mid_pln={"PLN": 1.0}, effective_date="2026-10-16")


def buy(tid, date, shares, total, fees=None, broker="TRADE_REPUBLIC", acq="BUY"):
    return {"transaction_id": tid, "broker": broker, "currency": "PLN", "purchase_date": date, "shares": shares,
            "total_invested": total, "fees": fees, "acquisition_type": acq}


def sell(tid, date, shares, price, fees=None, broker="TRADE_REPUBLIC"):
    return {"transaction_id": tid, "broker": broker, "currency": "PLN", "sale_date": date, "shares": shares,
            "sale_price": price, "fees": fees}


def summary(purchases, sales, price=130.0):
    return compute_position_summary(1, purchases, sales, current_price=price, current_price_currency="PLN", fx=FX)


def test_sale_of_whole_position_zero_shares_zero_value_realized_result_kept():
    s = summary([buy(1, "2026-01-10", 10, 1000.0)], [sell(1, "2026-03-01", 10, 120.2, fees=2.0)])
    [sub] = s.by_broker_currency
    assert sub.shares_held == 0 and sub.total_invested == 0 and sub.avg_price is None
    assert sub.current_value == 0
    assert sub.realized_pl == pytest.approx(10 * 120.2 - 2.0 - 1000.0)  # 200 PLN
    pln = compute_portfolio_pln_summary([({"ticker": "X"}, s)])
    assert pln["value_pln"] == 0 and pln["realized_pl_pln"] == pytest.approx(200.0) and pln["missing"] == []


def test_partial_sale_with_fee_uses_average_cost_at_the_time_of_sale():
    purchases = [buy(1, "2026-01-10", 10, 1000.0, fees=1.0), buy(2, "2026-02-10", 10, 1400.0)]
    s = summary(purchases, [sell(1, "2026-03-01", 5, 150.0, fees=5.0)])
    [sub] = s.by_broker_currency
    assert sub.shares_held == 15
    assert sub.total_invested == pytest.approx(2400.0 * 15 / 20)  # średni koszt 120
    assert sub.realized_pl == pytest.approx(5 * 150.0 - 5.0 - 600.0)
    assert sub.current_value == pytest.approx(15 * 130.0)


def test_chronological_order_sale_between_purchases():
    purchases = [buy(1, "2026-01-10", 10, 1000.0), buy(2, "2026-05-10", 10, 2000.0)]
    s = summary(purchases, [sell(1, "2026-03-01", 5, 150.0)])
    [sub] = s.by_broker_currency
    assert sub.realized_pl == pytest.approx(750.0 - 500.0)  # koszt z dnia sprzedaży, nie po drugim zakupie
    assert sub.total_invested == pytest.approx(500.0 + 2000.0)


def test_bonus_adds_units_at_zero_cost():
    s = summary([buy(1, "2026-01-10", 10, 1000.0), buy(2, "2026-02-01", 2, 0.0, acq="BONUS")],
                [sell(1, "2026-03-01", 12, 100.0)])
    [sub] = s.by_broker_currency
    assert sub.shares_held == 0
    assert sub.realized_pl == pytest.approx(1200.0 - 1000.0)
    assert sub.acquisition_types == ("BONUS", "BUY")


def test_rebuy_after_full_sale_starts_fresh_cost_and_keeps_realized():
    purchases = [buy(1, "2026-01-10", 10, 1000.0), buy(2, "2026-06-01", 5, 600.0)]
    s = summary(purchases, [sell(1, "2026-03-01", 10, 120.0)])
    [sub] = s.by_broker_currency
    assert sub.shares_held == 5 and sub.total_invested == pytest.approx(600.0) and sub.avg_price == pytest.approx(120.0)
    assert sub.realized_pl == pytest.approx(200.0)


def test_negative_holding_is_detected_on_the_whole_timeline():
    purchases = [buy(1, "2026-05-01", 10, 1000.0)]
    assert find_negative_holding(purchases, [sell(1, "2026-03-01", 10, 100.0)])["date"] == "2026-03-01"  # przed zakupem
    assert find_negative_holding(purchases, [sell(1, "2026-06-01", 10, 100.0)]) is None
    assert find_negative_holding(purchases, [sell(1, "2026-06-01", 11, 100.0)])["held"] == 10
    other_broker = find_negative_holding(purchases, [sell(1, "2026-06-01", 1, 100.0, broker="REVOLUT")])
    assert other_broker["broker"] == "REVOLUT"  # akcje na innym brokerze się nie liczą
    assert find_negative_holding([buy(1, "2026-01-01", 0.15, 10.0)], [sell(1, "2026-01-02", 0.1 + 0.05, 1.0)]) is None


def test_retype_defaults_keep_applicable_data():
    wrong_buy = buy(7, "2026-03-01", 10, 1200.0, fees=2.0)
    d = retype_defaults("PURCHASE", wrong_buy, "SELL")
    assert (d["date"], d["broker"], d["shares"], d["currency"], d["fees"]) == ("2026-03-01", "TRADE_REPUBLIC", 10, "PLN", 2.0)
    assert d["sale_price"] == pytest.approx(120.2)  # przychód netto = 10 x 120,2 - 2 = 1200
    back = retype_defaults("SALE", sell(3, "2026-03-01", 10, 120.2, fees=2.0), "BUY")
    assert back["total_invested"] == pytest.approx(1204.0)
    assert retype_defaults("PURCHASE", wrong_buy, "BONUS")["total_invested"] == 0.0


def test_buy_to_sell_that_would_oversell_is_rejected_by_replace_check():
    purchases = [buy(1, "2026-01-10", 5, 500.0), buy(2, "2026-03-01", 10, 1200.0)]
    hypothetical = replace_transaction(purchases, [], kind="PURCHASE", transaction_id=2, new_type="SELL",
                                       new_row=sell(None, "2026-03-01", 10, 120.0))
    assert find_negative_holding(*hypothetical)["held"] == 5


# --- zapis w bazie (SQLite; ta sama funkcja działa na Postgresie, patrz test_pg_store) ---


@pytest.fixture
def conn(tmp_path):
    return db.init_db(tmp_path / "t.db")


def _position_with_wrong_buy(conn):
    uid = db.create_user(conn, "Anastazja")
    other = db.create_user(conn, "Mąż")
    pid = db.insert_position(conn, user_id=uid, ticker="KO", company_name="Coca-Cola", instrument_confirmed=True)
    db.insert_purchase_transaction(conn, position_id=pid, broker="REVOLUT", acquisition_type="BUY",
                                   purchase_date="2026-01-10", shares=10, total_invested=1000.0, currency="PLN")
    wrong = db.insert_purchase_transaction(conn, position_id=pid, broker="REVOLUT", acquisition_type="BUY",
                                           purchase_date="2026-03-01", shares=10, total_invested=1200.0,
                                           currency="PLN", fees=2.0, note="sprzedaż")
    other_pid = db.insert_position(conn, user_id=other, ticker="KO", company_name="Coca-Cola")
    db.insert_purchase_transaction(conn, position_id=other_pid, broker="REVOLUT", acquisition_type="BUY",
                                   purchase_date="2026-01-10", shares=3, total_invested=300.0, currency="PLN")
    conn.commit()
    return pid, wrong, other_pid


def test_change_buy_to_sell_in_database_keeps_history_and_fixes_portfolio(conn):
    pid, wrong, other_pid = _position_with_wrong_buy(conn)
    row = dict(conn.execute("SELECT * FROM purchase_transactions WHERE transaction_id = ?", (wrong,)).fetchone())
    d = retype_defaults("PURCHASE", row, "SELL")
    new_id = apply_transaction_change(
        conn, pid, kind="PURCHASE", old_id=wrong, current_type="BUY", new_type="SELL",
        new_row={"broker": d["broker"], "currency": d["currency"], "shares": d["shares"], "sale_date": d["date"],
                 "sale_price": d["sale_price"], "fees": d["fees"]},
        note=d["note"],
    )
    purchases, sales = db.get_purchase_transactions(conn, pid), db.get_sale_transactions(conn, pid)
    assert len(purchases) == 1 and [s["transaction_id"] for s in sales] == [new_id]
    old = conn.execute("SELECT voided_at, void_reason FROM purchase_transactions WHERE transaction_id = ?",
                       (wrong,)).fetchone()
    assert old["voided_at"] is not None and f"sprzedaż #{new_id}" in old["void_reason"]  # stary wpis zostaje
    [sub] = summary(purchases, sales).by_broker_currency
    assert sub.shares_held == 0 and sub.realized_pl == pytest.approx(200.0)
    assert len(db.get_purchase_transactions(conn, other_pid)) == 1  # dane drugiego użytkownika nietknięte

    db.insert_purchase_transaction(conn, position_id=pid, broker="REVOLUT", acquisition_type="BUY",
                                   purchase_date="2026-06-01", shares=4, total_invested=520.0, currency="PLN")
    conn.commit()
    [sub] = summary(db.get_purchase_transactions(conn, pid), db.get_sale_transactions(conn, pid)).by_broker_currency
    assert sub.shares_held == 4 and sub.avg_price == pytest.approx(130.0)  # ponowny zakup po sprzedaży całości


def test_change_that_would_oversell_is_blocked_and_nothing_changes(conn):
    pid, wrong, _ = _position_with_wrong_buy(conn)
    before = [tuple(r) for r in conn.execute("SELECT * FROM purchase_transactions ORDER BY transaction_id")]
    with pytest.raises(TransactionChangeError):
        apply_transaction_change(
            conn, pid, kind="PURCHASE", old_id=wrong, current_type="BUY", new_type="SELL",
            new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 25, "sale_date": "2026-03-01",
                     "sale_price": 120.0, "fees": None},
        )
    assert [tuple(r) for r in conn.execute("SELECT * FROM purchase_transactions ORDER BY transaction_id")] == before
    assert db.get_sale_transactions(conn, pid) == []


def test_sell_to_buy_and_buy_to_bonus(conn):
    pid, wrong, _ = _position_with_wrong_buy(conn)
    sale_id = apply_transaction_change(
        conn, pid, kind="PURCHASE", old_id=wrong, current_type="BUY", new_type="SELL",
        new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 10, "sale_date": "2026-03-01",
                 "sale_price": 120.2, "fees": 2.0},
    )
    buy_id = apply_transaction_change(
        conn, pid, kind="SALE", old_id=sale_id, current_type="SELL", new_type="BUY",
        new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 10, "purchase_date": "2026-03-01",
                 "total_invested": 1204.0, "fees": 2.0},
    )
    bonus_id = apply_transaction_change(
        conn, pid, kind="PURCHASE", old_id=buy_id, current_type="BUY", new_type="BONUS",
        new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 10, "purchase_date": "2026-03-01"},
    )
    rows = {r["transaction_id"]: r for r in db.get_purchase_transactions(conn, pid)}
    assert rows[bonus_id]["acquisition_type"] == "BONUS" and rows[bonus_id]["total_invested"] == 0
    assert db.get_sale_transactions(conn, pid) == []
    with pytest.raises(TransactionChangeError):  # stary, już zastąpiony wpis nie może być zmieniony drugi raz
        apply_transaction_change(
            conn, pid, kind="PURCHASE", old_id=buy_id, current_type="BUY", new_type="SELL",
            new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 1, "sale_date": "2026-03-01",
                     "sale_price": 1.0},
        )


# --- Kwota z opłatami albo bez + opłaty (2026-10-19) ---

from buffett_scanner.ui.portfolio import (  # noqa: E402
    FEES_KNOWN,
    FEES_UNSPLIT,
    AmountError,
    fees_unknown_default,
    resolve_purchase_amounts,
    resolve_sale_amounts,
)


def test_both_purchase_entry_modes_give_exactly_the_same_total_cost():
    assert resolve_purchase_amounts(300.0, 4.50, amount_includes_fees=True, fees_unknown=False) == (300.0, 4.5, FEES_KNOWN)
    assert resolve_purchase_amounts(295.50, 4.50, amount_includes_fees=False, fees_unknown=False) == (300.0, 4.5, FEES_KNOWN)
    assert resolve_purchase_amounts(300.0, 0.0, amount_includes_fees=True, fees_unknown=True) == (300.0, None, FEES_UNSPLIT)
    with pytest.raises(AmountError):  # bez opłat, a opłat nie znam -> nie da się policzyć kosztu
        resolve_purchase_amounts(295.5, 0.0, amount_includes_fees=False, fees_unknown=True)
    with pytest.raises(AmountError):
        resolve_purchase_amounts(3.0, 4.5, amount_includes_fees=True, fees_unknown=False)


def test_sale_gross_and_net_entry_give_the_same_proceeds():
    price_net, fees, _ = resolve_sale_amounts(2.0, 196.0, 4.0, amount_is_net=True, fees_unknown=False)
    price_gross, fees2, _ = resolve_sale_amounts(2.0, 200.0, 4.0, amount_is_net=False, fees_unknown=False)
    assert price_net == price_gross == 100.0 and fees == fees2 == 4.0
    price, fees, status = resolve_sale_amounts(2.0, 196.0, 0.0, amount_is_net=True, fees_unknown=True)
    assert (price * 2, fees, status) == (196.0, None, FEES_UNSPLIT)  # wpływ = kwota, opłaty nierozdzielone
    with pytest.raises(AmountError):
        resolve_sale_amounts(2.0, 200.0, 0.0, amount_is_net=False, fees_unknown=True)


def test_fees_are_not_counted_twice_in_cost_and_counted_once_in_sale_result():
    total, fees, _ = resolve_purchase_amounts(295.50, 4.50, amount_includes_fees=False, fees_unknown=False)
    price, sale_fees, _ = resolve_sale_amounts(1.0, 400.0, 5.0, amount_is_net=False, fees_unknown=False)
    s = summary([buy(1, "2026-01-10", 1.0, total, fees=fees)], [sell(1, "2026-03-01", 1.0, price, fees=sale_fees)])
    [sub] = s.by_broker_currency
    assert sub.realized_pl == pytest.approx(395.0 - 300.0)  # wpływ netto - koszt z opłatami


def test_legacy_row_without_fees_is_treated_as_unknown_not_zero():
    assert fees_unknown_default({"fees": None, "fee_status": None}) is True
    assert fees_unknown_default({"fees": 4.5, "fee_status": None}) is False
    assert fees_unknown_default({"fees": None, "fee_status": FEES_KNOWN}) is False
    assert fees_unknown_default({"fees": None, "fee_status": FEES_UNSPLIT}) is True


def test_historic_bitcoin_purchase_can_be_marked_unsplit_then_split_without_changing_cost(conn):
    uid = db.create_user(conn, "Anastazja")
    pid = db.insert_position(conn, user_id=uid, ticker="BTCUSD", company_name="Bitcoin", instrument_confirmed=True)
    legacy = db.insert_purchase_transaction(conn, position_id=pid, broker="REVOLUT", acquisition_type="BUY",
                                            purchase_date="2021-05-01", shares=0.00123456, total_invested=300.0,
                                            currency="PLN")
    conn.commit()
    row = dict(db.get_purchase_transactions(conn, pid)[0])
    d = retype_defaults("PURCHASE", row, "BUY")
    assert d["amount"] == 300.0 and d["fees_unknown"] is True  # domyślnie: opłaty nieznane, nie zero

    total, fees, status = resolve_purchase_amounts(300.0, 0.0, amount_includes_fees=True, fees_unknown=True)
    marked = apply_transaction_change(conn, pid, kind="PURCHASE", old_id=legacy, current_type="BUY", new_type="BUY",
                                      new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 0.00123456,
                                               "purchase_date": "2021-05-01", "total_invested": total,
                                               "fees": fees, "fee_status": status})
    total, fees, status = resolve_purchase_amounts(295.50, 4.50, amount_includes_fees=False, fees_unknown=False)
    split = apply_transaction_change(conn, pid, kind="PURCHASE", old_id=marked, current_type="BUY", new_type="BUY",
                                     new_row={"broker": "REVOLUT", "currency": "PLN", "shares": 0.00123456,
                                              "purchase_date": "2021-05-01", "total_invested": total,
                                              "fees": fees, "fee_status": status})
    [active] = db.get_purchase_transactions(conn, pid)
    assert active["transaction_id"] == split
    assert (active["total_invested"], active["fees"], active["fee_status"], active["shares"]) == (300.0, 4.5, FEES_KNOWN, 0.00123456)
    history = conn.execute("SELECT transaction_id, fee_status, voided_at FROM purchase_transactions ORDER BY transaction_id").fetchall()
    assert [(r["transaction_id"], r["fee_status"], r["voided_at"] is not None) for r in history] == [
        (legacy, None, True), (marked, FEES_UNSPLIT, True), (split, FEES_KNOWN, False)]  # nic nie zniknęło
