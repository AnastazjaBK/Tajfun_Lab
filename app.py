"""Buffett Opportunity Scanner — UI + PORTFOLIO V0 (Faza 7) + Hostowany
V0 (Faza 8).

Punkt wejścia Streamlit. WYŁĄCZNIE prezentacja/odczyt + proste
formularze zapisu (decyzje, transakcje) — zero logiki
scoringu/wyceny/DCF/decline-screeningu/Claude API; cała ta logika
mieszka w `buffett_scanner.*` i jest tu TYLKO odczytywana/tłumaczona.

Uruchomienie lokalne (tryb DEV, domyślny -- `SUPABASE_DB_URL` nieustawione):
    streamlit run app.py
Jedno połączenie SQLite (`BUFFETT_SCANNER_DB`, domyślnie
`buffett_scanner.db` — ten sam plik, który zapisuje `cli.py`) obsługuje
ZARÓWNO dane scannera, JAK I portfel — dokładnie jak w Fazie 7, zero
zmian w tym trybie.

Tryb HOSTOWANY (Faza 8, `SUPABASE_DB_URL` ustawione -- Streamlit
Community Cloud): DWA OSOBNE połączenia, bo dane SHARED scannera i
USER-SCOPED portfel żyją w dwóch różnych, niezależnych miejscach
(Decyzja właścicielki, "Hostowany V0"):
- `portfolio_conn` -- Postgres/Supabase (`pg_store.py`), WYŁĄCZNIE 7
  tabel user-generated.
- `scanner_conn` -- SQLite, snapshot pobrany i zweryfikowany (SHA256)
  z GitHub Release (`ui/scanner_snapshot.py`), otwarty w trybie
  read-only (`file:...?mode=ro`) -- hostowana appka NIGDY nie zapisuje
  do danych scannera.
Oba tryby dzielą DOKŁADNIE ten sam kod renderujący (funkcje `_render_*`
przyjmują `portfolio_conn`/`scanner_conn` jawnie) — w trybie DEV oba
parametry to ten sam obiekt połączenia.

Połączenia są otwierane NA NOWO przy każdym rerunie skryptu (zero
`st.cache_resource` na samym obiekcie połączenia) — Streamlit może
wykonywać rerun różnych sesji (np. Anastazja i mąż z dwóch przeglądarek
naraz) w różnych wątkach, a połączenia bazodanowe nie wolno współdzielić
między wątkami. Koszt otwarcia połączenia jest pomijalny przy tej skali
danych (`ensure_local_snapshot` dodatkowo cache'uje pobrany plik lokalnie
między rerunami, patrz `ui/scanner_snapshot.py`).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from buffett_scanner import portfolio_backend
from buffett_scanner.config import load_config
from buffett_scanner.db import get_fundamentals_periods, init_db
from buffett_scanner.shareholder_returns import payout_ratio
from buffett_scanner.ui.dividends import (
    FREQUENCY_LABELS,
    TREND_LABELS,
    compute_dividend_metrics,
    cut_risk_note,
    receipt_net,
    summarize_receipts,
)
from buffett_scanner.pg_store import BackupVerificationError, PgStoreUnavailableError
from buffett_scanner.portfolio_backend import (
    create_user,
    get_latest_holding_user_action,
    get_latest_user_decisions_for_user,
    get_positions_for_user,
    get_purchase_thesis,
    get_purchase_transactions,
    get_sale_transactions,
    get_users,
    insert_holding_user_action,
    insert_position,
    insert_purchase_transaction,
    insert_sale_transaction,
    insert_user_decision,
    backup_payload,
    get_latest_backup_info,
    get_dividend_receipts,
    insert_dividend_receipt,
    insert_manual_valuation,
    set_transaction_fx_rate,
    update_position_fields,
    void_dividend_receipt,
    update_position_instrument,
    void_position,
    void_purchase_transaction,
    void_sale_transaction,
)
from buffett_scanner.ui.assets import (
    ASSET_CLASS_LABELS,
    CATEGORY_LABELS,
    COMMODITY,
    COMMODITY_SYMBOLS,
    CRYPTO,
    ETC,
    ETF,
    ETN,
    EXCHANGE_TRADED,
    EXPOSURE_LABELS,
    METAL_LABELS,
    PHYSICAL,
    PHYSICAL_GOLD,
    PHYSICAL_SILVER,
    PRODUCT_FORM_LABELS,
    STOCK,
    asset_class_of,
    category_summaries,
    exposure_summary,
    is_active,
    pure_grams_per_piece,
    commodity_cost_error,
    realizable_value_pln,
)
from buffett_scanner.ui.data_quality import data_quality_warning
from buffett_scanner.ui.instrument_lookup import (
    InstrumentLookupResult,
    instrument_save_errors,
    lookup_instrument_routed,
)
from buffett_scanner.ui.labels import (
    GLOSSARY,
    METHODOLOGY_DISCLAIMER,
    acquisition_types_label,
    analysis_status_label,
    broker_label,
    decision_status_label,
    decline_flags_label,
    deterministic_points_label,
    holding_action_label,
    missing_components_label,
    run_status_banner,
)
from buffett_scanner.ui.price_changes import (
    PERIODS,
    compute_period_changes,
    detect_price_anomalies,
    periods_affected,
)
from buffett_scanner.ui.portfolio import (
    FEES_KNOWN,
    FEES_UNSPLIT,
    AmountError,
    describe_sale_amounts,
    fees_unknown_default,
    compute_portfolio_bar_summary,
    compute_portfolio_pln_summary,
    find_negative_holding,
    replace_transaction,
    resolve_purchase_amounts,
    resolve_sale_amounts,
    retype_defaults,
    sale_amounts,
    transaction_type,
)
from buffett_scanner.ui.market_data import EODHD_DAILY_BUDGET, MarketData
from buffett_scanner.ui.pricing import FxRates, convert
from buffett_scanner.ui.queries import (
    TransactionChangeError,
    apply_transaction_change,
    get_brokers_in_use_for_user,
    get_candidate_detail,
    get_latest_live_scan_run,
    get_review_needed_count,
    get_scan_price_rows,
    get_synthesis_rows,
    get_user_positions_with_summaries,
    is_instrument_confirmed,
    top5_label,
)
from buffett_scanner.ui.scanner_snapshot import SnapshotUnavailableError, ensure_local_snapshot

# Filtr platformy w PORTFELU (Decyzja właścicielki) -- "ALL" oznacza
# "Wszystkie" (agregacja wszystkich platform), pozostałe to dokładnie
# kody brokerów z istniejącego enumu. Trade Republic/Revolut są ZAWSZE
# dostępne w filtrze; "Inny" (OTHER) pokazuje się TYLKO gdy użytkownik
# ma choć jedną realną transakcję na tym brokerze (patrz
# `get_brokers_in_use_for_user`) -- nigdy jako pusta, myląca opcja.
_PLATFORM_FILTER_ALWAYS_AVAILABLE = ("ALL", "TRADE_REPUBLIC", "REVOLUT")

# Sekcja 16 specyfikacji: mapowanie przycisków UI na istniejący enum
# `user_decisions.status` (sekcja 1.1/16 design review) -- NIE
# wymyślamy nowego modelu statusów.
_DECISION_BUTTONS = (
    ("REJECT", "Odrzucam"),
    ("WATCH", "Obserwuję"),
    ("SNOOZE", "Sprawdzam"),
    ("BOUGHT", "Kupiłam/Kupiłem"),
)

# Sekcja 14 specyfikacji: status pozycji -- istniejący enum
# `holding_user_actions.action` (sekcja 16 design review).
_HOLDING_ACTION_BUTTONS = (
    ("HOLD", "Trzymam"),
    ("REDUCE", "Redukuję"),
    ("REVIEW_LATER", "Do przeglądu"),
    ("SOLD", "Sprzedane"),
)

# Sekcja 9/3 specyfikacji -- istniejący enum `purchase_transactions.
# broker`/`sale_transactions.broker` (sekcja 1.1/16 design review).
_BROKER_OPTIONS = ("TRADE_REPUBLIC", "REVOLUT", "CASHIFY", "GOLD_SAVER", "MENNICA_SKARBOWA", "OTHER")

# Sekcja 10 specyfikacji -- istniejący enum `purchase_transactions.
# acquisition_type`.
_ACQUISITION_TYPE_OPTIONS = ("BUY", "BONUS")
_TRANSACTION_TYPES = ("BUY", "SELL", "BONUS")
_TRANSACTION_TYPE_LABELS = {"BUY": "Zakup", "SELL": "Sprzedaż", "BONUS": "Bonus (bezpłatne jednostki)"}

_VALUATION_SCENARIO_LABELS = (
    ("bear", "Pesymistyczny (BEAR)"),
    ("base", "Bazowy (BASE)"),
    ("bull", "Optymistyczny (BULL)"),
)

DB_PATH = os.environ.get("BUFFETT_SCANNER_DB", "buffett_scanner.db")
_MISSING = object()

# Faza 8 "Hostowany V0" -- tylko w trybie `portfolio_backend.is_hosted()`.
SNAPSHOT_REPO_OWNER = os.environ.get("SNAPSHOT_REPO_OWNER", "AnastazjaBK")
SNAPSHOT_REPO_NAME = os.environ.get("SNAPSHOT_REPO_NAME", "Tajfun_Lab")
SNAPSHOT_CACHE_DIR = os.environ.get("SNAPSHOT_CACHE_DIR", tempfile.gettempdir())


# Faza 9: kolory zysku/straty w tabeli (Styler) -- czytelne w jasnym
# i ciemnym motywie Streamlit.
_PL_GAIN_CSS = "color: #21a366; font-weight: 600"
_PL_LOSS_CSS = "color: #e5534b; font-weight: 600"

# Faza 11 (P0b): klasy aktywów wybierane przy potwierdzaniu instrumentu.
# Typ podany przez dostawcę jest tylko podpowiedzią (EODHD oznacza ETC
# Xetra-Gold jako "ETF") -- decyduje użytkownik.
_ASSET_CLASS_LABELS = {c: ASSET_CLASS_LABELS[c] for c in EXCHANGE_TRADED}


@st.cache_resource
def _market_memory() -> dict:
    """Jedna pamięć cen na serwer (wszystkie sesje) -- patrz
    `MarketData.__init__`. Bez niej każde kliknięcie czytało ~80 wpisów
    cache z Supabase (pomiar 2026-10-19)."""
    return {}


def _market(portfolio_conn) -> MarketData:
    """Ceny, historia, dywidendy i kursy NBP przez wspólny cache w bazie
    portfela (Faza 11) -- jeden obiekt na przebieg skryptu."""
    return MarketData(portfolio_conn, memory=_market_memory())


def _format_currency_dict(values: dict[str, float]) -> str:
    """Nigdy nie sumuje różnych walut (sekcja 12 specyfikacji) --
    pokazuje każdą walutę osobno."""
    if not values:
        return "—"
    return " | ".join(f"{amount:,.0f} {currency}" for currency, amount in sorted(values.items()))


def _color_pl_text(amount: float, text: str) -> str:
    """Markdown Streamlit: zielony zysk, czerwona strata, zero bez koloru."""
    if amount > 0:
        return f":green[{text}]"
    if amount < 0:
        return f":red[{text}]"
    return text


def _format_pl_dict_colored(values: dict[str, float] | None) -> str:
    if not values:
        return "—"
    return " | ".join(
        _color_pl_text(amount, f"{amount:+,.0f} {currency}") for currency, amount in sorted(values.items())
    )


def _render_pl_metric(container, label: str, values: dict[str, float] | None) -> None:
    """Odpowiednik `st.metric` dla zysku/straty -- `st.metric` nie
    koloruje samej wartości, a P/L może mieć kilka walut o różnych
    znakach (każda kolorowana osobno)."""
    container.caption(label)
    container.markdown(f"#### {_format_pl_dict_colored(values)}")


def _format_pln(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+,.0f} PLN" if signed else f"{value:,.0f} PLN"


def _format_shares(value: float) -> str:
    """Do 8 miejsc po przecinku (ułamki akcji, kryptowaluty), bez zbędnych zer."""
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _render_pln_summary(
    container, positions_with_summaries: list, fx: FxRates | None, *,
    dividends_net_pln: float | None = 0.0,
) -> None:
    """Faza 11 (P1): portfel w PLN. Koszt = kursy z dni transakcji (kurs
    brokera, jeśli zapisany, inaczej NBP sprzed transakcji), wartość =
    dzisiejszy kurs NBP. Suma bez ceny/kursu którejś pozycji jest jawnie
    oznaczona jako częściowa, z listą brakujących instrumentów."""
    pln = compute_portfolio_pln_summary(positions_with_summaries)
    partial = bool(pln["missing"])
    star = " *" if partial else ""
    cols = container.columns(4)
    cols[0].metric(f"Wartość portfela{star}", _format_pln(pln["value_pln"]))
    cols[1].metric(f"Koszt nabycia{star}", _format_pln(pln["cost_pln"]))
    pct = f" ({pln['unrealized_pl_pct']:+.1f}%)" if pln["unrealized_pl_pct"] is not None else ""
    _render_pl_metric(cols[2], "Zysk/strata niezrealizowany", {"PLN": pln["unrealized_pl_pln"]})
    if pct:
        cols[2].caption(pct.strip())
    _render_pl_metric(cols[3], "Zrealizowany (sprzedaże)", {"PLN": pln["realized_pl_pln"]})
    total = pln["total_result_pln"] + (dividends_net_pln or 0.0)
    dividends_text = (
        f" (w tym otrzymane dywidendy netto {_format_pln(dividends_net_pln)})" if dividends_net_pln else ""
    )
    if dividends_net_pln is None:
        dividends_text = " (bez dywidend — brak kursu dla części wypłat)"
    container.markdown(
        f"Łączny wynik: {_color_pl_text(total, _format_pln(total, signed=True))}{dividends_text} — "
        "zmiana wartości + sprzedaże + dywidendy, po opłatach."
    )
    if partial:
        container.warning(
            "* Suma częściowa — brak ceny bieżącej lub kursu dla: " + ", ".join(pln["missing"])
            + f". Koszt wszystkich posiadanych pozycji: {_format_pln(pln['cost_pln_all'])}."
        )
    notes = []
    if fx is not None:
        notes.append(f"Wartość po kursie średnim NBP z {fx.effective_date}")
    else:
        notes.append("Kurs NBP chwilowo niedostępny — wartości w walutach obcych nieznane")
    if pln["estimated"]:
        notes.append(
            "koszt części transakcji w walucie obcej przeliczony kursem NBP z dnia roboczego przed transakcją "
            "(orientacyjnie — to nie kurs brokera ani kurs podatkowy; kurs brokera możesz dopisać w karcie pozycji)"
        )
    container.caption("; ".join(notes) + ".")


def _dividends_received_pln(portfolio_conn, market: MarketData, positions_with_summaries: list, broker: str | None):
    receipts = []
    for position, _summary in positions_with_summaries:
        receipts += [
            r for r in get_dividend_receipts(portfolio_conn, position["position_id"])
            if broker is None or r["broker"] == broker
        ]
    if not receipts:
        return 0.0
    return summarize_receipts(receipts, pln_rate_fn=market.pln_rate, year=dt.date.today().year).net_pln


def _format_quote_source(summary) -> str:
    if summary.quote_source is None:
        return "—"
    text = f"{summary.quote_source} · {summary.quote_as_of or '?'}"
    return text + " (ostatnia znana)" if summary.quote_stale else text


def _render_pricing_caption(container, summaries: list, fx: FxRates | None, eodhd_calls: int | None = None) -> None:
    priced = sum(1 for s in summaries if s.current_value_by_currency)
    fx_text = f"kursy NBP z {fx.effective_date}" if fx is not None else "kursy NBP chwilowo niedostępne"
    partial = (
        " Zysk/strata liczony tylko dla pozycji z ceną, a zainwestowany kapitał obejmuje wszystkie — "
        "dlatego wartość minus kapitał nie równa się zyskowi/stracie."
        if priced < len(summaries) else ""
    )
    eodhd_text = f" (dziś {eodhd_calls}/{EODHD_DAILY_BUDGET} zapytań darmowego planu)" if eodhd_calls is not None else ""
    container.caption(
        f"Cena bieżąca dostępna dla {priced} z {len(summaries)} pozycji.{partial} Ceny odświeżane automatycznie: "
        f"FMP (USA, co godzinę), EODHD (Europa, ceny zamknięcia, co 12 h{eodhd_text}); {fx_text}."
    )


def _render_glossary() -> None:
    """Sekcja 17/18 specyfikacji UI: "Jak to czytać?" -- wyjaśnienie
    pojęć (DCF/MoS/Bear-Base-Bull/FCF/dług netto-EBITDA/hard gate/Bull
    Case/Bear Case/Thesis Invalidation/Biggest Unknown) prostym
    językiem, BEZ usuwania profesjonalnych terminów. Zwinięte domyślnie
    (`st.expander`) -- materiał referencyjny, nie nawigacja (sekcja 2
    specyfikacji dotyczy wyłącznie zakładek nawigacyjnych, nie tego)."""
    with st.expander("Jak to czytać? (słowniczek pojęć)"):
        for term, explanation in GLOSSARY:
            st.markdown(f"**{term}** — {explanation}")


def _render_user_picker(portfolio_conn) -> dict | None:
    """Selector czyta realnych użytkowników z bazy -- ZERO hardcode'owanych
    "Anastazja"/"Mąż" (Decyzja właścicielki, Faza 7 pkt 7: "nie zakładaj,
    że display_name drugiego użytkownika na zawsze brzmi 'Mąż'"). Gdy
    baza jest pusta, UI prosi o jawne, ręczne utworzenie pierwszego
    użytkownika -- zero automatycznego seedu przy starcie aplikacji."""
    with st.expander("+ Dodaj nowego użytkownika"):
        with st.form("add_user_form", clear_on_submit=True):
            new_name = st.text_input("Imię nowego użytkownika")
            if st.form_submit_button("Dodaj") and new_name.strip():
                create_user(portfolio_conn, new_name.strip())
                portfolio_conn.commit()
                st.rerun()

    users = get_users(portfolio_conn)
    if not users:
        st.warning("Brak użytkowników. Dodaj pierwszego powyżej, aby zacząć.")
        return None

    names = [u["display_name"] for u in users]
    selected = st.selectbox("Użytkownik", names, key="selected_user_name")
    return next(u for u in users if u["display_name"] == selected)


def _render_synthesis_table(scanner_conn, portfolio_conn) -> tuple[str | None, list[dict], bool]:
    """Sekcja 4 specyfikacji: tabela SYNTEZY ostatniego WŁAŚCIWEGO
    live-scanu (nigdy walidacji technicznej -- patrz `ui/queries.
    get_latest_live_scan_run`). FAILED to status RAPORTU jakościowego,
    nie ocena spółki -- deterministyczne dane/cena/wycena pozostają
    widoczne niezależnie od statusu analizy LLM. Zwraca `(run_id, rows, is_complete)`
    -- `run_id` reużywany przez karty kandydatów, żeby nie odpytywać
    "najnowszego skanu" drugi raz per zakładkę."""
    run = get_latest_live_scan_run(scanner_conn)
    if run is None:
        st.info("Brak jeszcze ukończonego live-scan rynku.")
        return None, [], False

    st.subheader(f"Co scanner znalazł — skan z {run['run_date']}")
    rows = get_synthesis_rows(scanner_conn, run["run_id"])
    completed = sum(1 for r in rows if r["llm_status"] == "COMPLETE")
    is_complete, banner = run_status_banner(run["status"], run["run_date"], completed, len(rows))
    (st.success if is_complete else st.error)(banner)
    if not rows:
        st.info("Ten skan nie wytypował żadnych kandydatów (to prawidłowy wynik).")
        return run["run_id"], rows, is_complete

    for r in rows:
        warning = data_quality_warning(run["run_id"], r["cik"])
        if warning:
            st.warning(f"⚠ {r['ticker']}: {warning}")

    view = st.radio(
        "Widok tabeli", _TOP20_VIEWS, horizontal=True, key="top20_view",
        help="Na telefonie wybierz jeden widok — tabelę można też przewijać w bok.",
    )
    if view == "Zmiany cen":
        _render_top20_price_changes(scanner_conn, portfolio_conn, run, rows)
        st.caption(METHODOLOGY_DISCLAIMER)
        return run["run_id"], rows, is_complete
    if view == "Dywidendy":
        _render_top20_dividends(portfolio_conn, run, rows)
        st.caption(METHODOLOGY_DISCLAIMER)
        return run["run_id"], rows, is_complete

    weights = load_config().scoring.weights.model_dump()
    table_data = [
        {
            "Ticker": r["ticker"],
            "TOP 5": top5_label(r),
            "Spółka": r["company_name"],
            "Cena": r["current_price"],
            "Dlaczego spadła": decline_flags_label(r["triggered_decline_flags"]),
            "Wynik": f"{r['full_score']:.1f} / 100" if r["full_score"] is not None else "—",
            "Punkty deterministyczne": deterministic_points_label(
                r["deterministic_partial_score"], r["available_components"], weights,
            ),
            "Brakujące komponenty": missing_components_label(r["missing_components"], weights),
            "Margines bezpieczeństwa (BASE)": (
                f"{r['margin_of_safety_pct']:.1f}%" if r["margin_of_safety_pct"] is not None else "—"
            ),
            "Dlaczego ciekawa?": r["bull_case_first"] or "—",
            "Największe ryzyko": r["biggest_risk"] or "—",
            "Status analizy": analysis_status_label(r["llm_status"]),
        }
        for r in rows
    ]
    _show_table(_name_first(table_data))
    st.caption("★ TOP 5 = pierwsza piątka w ramach TOP 20 wg pełnego wyniku po analizie jakościowej "
               "(„=” — równy wynik).")
    if rows[0]["top5_boundary_tie"]:
        st.warning("Remis na granicy TOP 5: " + ", ".join(rows[0]["top5_boundary_tie"])
                   + " ma ten sam pełny wynik co piąta spółka, ale nie jest oznaczona ★.")
    st.caption(
        "Punkty deterministyczne = punkty zdobyte / maksimum komponentów, które dało się policzyć bez "
        "analizy jakościowej; pełna skala wyniku to 100 pkt. 45/45 nie oznacza 100/100 — brakujące "
        "komponenty (w nawiasie ich waga) nie zostały ocenione."
    )
    st.caption(METHODOLOGY_DISCLAIMER)
    return run["run_id"], rows, is_complete


_TOP20_VIEWS = ("Scoring", "Zmiany cen", "Dywidendy")


def _dividend_cells(metrics) -> dict:
    yield_text = f"{metrics.yield_ttm_pct:.2f}%" if metrics.yield_ttm_pct is not None else "N/A"
    per_100 = f"{metrics.gross_per_100_pln:.2f} PLN" if metrics.gross_per_100_pln is not None else "N/A"
    last = metrics.last_event
    return {
        "Yield TTM": yield_text,
        "Częstotliwość": FREQUENCY_LABELS[metrics.frequency],
        "Brutto/100 PLN rocznie": per_100,
        "Trend": TREND_LABELS[metrics.trend],
        "Ostatnia ex-date": last.ex_date if last else "—",
    }


def _render_top20_dividends(portfolio_conn, run, rows: list[dict]) -> None:
    """Faza 11 (P3): dywidendy TOP20 -- wypłaty na akcję z FMP. Widok "na
    dzień skanu" liczy yield z ceny skanu i wypłat z ex-date <= data skanu
    (bez look-ahead), "bieżący" -- z ceny i wypłat na dziś. Scoring
    dywidendowy scannera bez zmian."""
    source = st.radio("Dane", _CHANGE_SOURCES, horizontal=True, key="top20_dividend_source")
    market = _market(portfolio_conn)
    table_rows = []
    for r in rows:
        with st.spinner(f"Pobieram dywidendy {r['ticker']}…"):
            events = market.dividend_events_for_symbol("FMP", r["ticker"], "USD")
        if source == _CHANGE_SOURCES[0]:
            price, as_of = r["current_price"], run["run_date"]
        else:
            quote = market.quote_for_symbol("FMP", r["ticker"])
            price, as_of = (quote.price if quote else None), dt.date.today().isoformat()
        notes = []
        warning = data_quality_warning(run["run_id"], r["cik"])
        if warning:
            notes.append(warning)
        if events is None:
            cells = {k: "N/A" for k in ("Yield TTM", "Częstotliwość", "Brutto/100 PLN rocznie", "Trend")}
            cells["Ostatnia ex-date"] = "—"
            notes.append("brak danych o dywidendach")
        else:
            metrics = compute_dividend_metrics(events, price=price, price_currency="USD", as_of=as_of)
            cells = _dividend_cells(metrics)
            if metrics.ttm_special:
                notes.append(f"wypłaty specjalne w 12 mies.: {metrics.ttm_special:.2f} USD (poza yieldem)")
        table_rows.append({
            "Ticker": r["ticker"],
            "TOP 5": top5_label(r),
            "Spółka": r["company_name"], **cells, "Uwagi": "; ".join(notes),
        })
    _show_table(_name_first(table_rows))
    st.caption(
        "Yield TTM = regularne wypłaty na akcję z ostatnich 12 miesięcy / cena (bez wypłat specjalnych). "
        "„Brutto/100 PLN” = orientacyjna roczna dywidenda brutto na każde 100 PLN zainwestowane po tej cenie "
        "(przed podatkiem, bez zmian kursu). Wysoki yield nie oznacza bezpiecznej dywidendy. Źródło: FMP."
    )


def _render_company_dividends(scanner_conn, portfolio_conn, *, cik: str, ticker: str) -> None:
    """Faza 11 (P3): szczegóły dywidend na karcie spółki (dane bieżące)."""
    st.markdown("#### Dywidendy")
    market = _market(portfolio_conn)
    events = market.dividend_events_for_symbol("FMP", ticker, "USD")
    if events is None:
        st.info("Dane o dywidendach chwilowo niedostępne.")
        return
    if not events:
        st.write("Spółka nie wypłaca dywidend (brak wypłat w danych FMP).")
        return
    quote = market.quote_for_symbol("FMP", ticker)
    today = dt.date.today().isoformat()
    m = compute_dividend_metrics(events, price=quote.price if quote else None, price_currency="USD", as_of=today)
    last = m.last_event
    cols = st.columns(3)
    cols[0].metric("Ostatnia dywidenda/akcję", f"{last.amount:.4f} {last.currency or ''}" if last else "—")
    cols[1].metric("DPS TTM (regularne)", f"{m.ttm_dps:.4f}")
    cols[2].metric("DPS od początku roku", f"{m.ytd_dps:.4f}")
    st.write(
        f"Yield TTM: **{f'{m.yield_ttm_pct:.2f}%' if m.yield_ttm_pct is not None else 'N/A'}** · "
        f"częstotliwość: **{FREQUENCY_LABELS[m.frequency]}** · trend: **{TREND_LABELS[m.trend]}**"
    )
    if last:
        st.write(f"Ostatnia ex-date: {last.ex_date} · data wypłaty: {last.pay_date or 'brak danych'}")
    if m.next_confirmed:
        n = m.next_confirmed
        st.write(
            f"Najbliższa potwierdzona ex-date: **{n.ex_date}** (ogłoszona {n.declaration_date}), "
            f"wypłata: {n.pay_date or 'brak danych'}, kwota {n.amount:.4f}"
        )
    else:
        st.caption("Brak ogłoszonej przyszłej wypłaty — kolejne daty nie są prognozowane.")
    if m.ttm_special:
        st.write(f"Wypłaty specjalne w ostatnich 12 mies.: {m.ttm_special:.4f} (nie wliczane do yieldu).")
    if m.by_year:
        st.dataframe(
            [{"Rok": y, "Suma wypłat/akcję": round(v, 4)} for y, v in m.by_year.items()],
            hide_index=True,
        )
    periods = get_fundamentals_periods(scanner_conn, cik)
    payout = payout_ratio(periods[-1]).value_pct if periods else None
    risk = cut_risk_note(m, payout)
    if payout is not None:
        st.caption(f"Wypłata dywidend / wolne przepływy pieniężne (ostatni rok obrotowy): {payout:.0f}%.")
    if risk:
        st.warning(f"Ryzyko obniżki: {risk}.")


def _render_portfolio_dividends(portfolio_conn, positions_with_summaries: list, fx, broker: str | None) -> None:
    """Faza 11 (P3): dywidendy posiadanych pozycji -- prognoza (z
    regularnych wypłat TTM) oddzielona od faktycznie otrzymanych (rejestr)."""
    market = _market(portfolio_conn)
    today = dt.date.today()
    table_rows = []
    forecast_total_pln = 0.0
    forecast_missing = []
    all_receipts = []
    for position, summary in positions_with_summaries:
        position = dict(position)
        receipts = [
            r for r in get_dividend_receipts(portfolio_conn, position["position_id"])
            if broker is None or r["broker"] == broker
        ]
        all_receipts += receipts
        received = summarize_receipts(receipts, pln_rate_fn=market.pln_rate, year=today.year)
        metrics = None
        if asset_class_of(position) in (*PHYSICAL, CRYPTO, COMMODITY):
            continue
        if is_instrument_confirmed(position):
            provider = position.get("price_provider")
            symbol = position.get("price_symbol") or position["ticker"]
            events = market.dividend_events_for_symbol(provider, symbol, position.get("quote_currency"))
            quote = market.quote_for_position(position)
            if events is not None:
                metrics = compute_dividend_metrics(
                    events, price=quote.price if quote else None,
                    price_currency=quote.currency if quote else None, as_of=today.isoformat(),
                )
        forecast_pln = None
        if metrics is not None and metrics.currency:
            forecast = metrics.ttm_dps * summary.shares_held
            forecast_pln = convert(forecast, metrics.currency, "PLN", fx)
        if forecast_pln is None:
            forecast_missing.append(position["ticker"])
        else:
            forecast_total_pln += forecast_pln
        # Yield on Cost tylko dla akcji z kosztem > 0: akcje z bonusu (koszt 0)
        # nie mogą zawyżać wskaźnika; same bonusy -> N/A.
        paid = [s for s in summary.by_broker_currency if s.invested_pln and s.invested_pln > 0 and s.shares_held > 0]
        cost_pln = sum(s.invested_pln for s in paid)
        paid_shares = sum(s.shares_held for s in paid)
        yoc = None
        if metrics is not None and metrics.currency and cost_pln > 0:
            paid_forecast_pln = convert(metrics.ttm_dps * paid_shares, metrics.currency, "PLN", fx)
            yoc = paid_forecast_pln / cost_pln * 100.0 if paid_forecast_pln is not None else None
        table_rows.append({
            "Ticker": position["ticker"], "Spółka": position["company_name"],
            "Yield (bieżąca cena)": (
                f"{metrics.yield_ttm_pct:.2f}%" if metrics and metrics.yield_ttm_pct is not None else "N/A"
            ),
            "Yield on Cost": f"{yoc:.2f}%" if yoc is not None else "N/A",
            "Prognoza roczna brutto": f"{forecast_pln:,.2f} PLN" if forecast_pln is not None else "N/A",
            "Otrzymane netto (łącznie)": f"{received.net_pln:,.2f} PLN" if receipts and received.net_pln is not None else "—",
            "Otrzymane netto (od 1.01)": f"{received.ytd_net_pln:,.2f} PLN" if receipts and received.ytd_net_pln is not None else "—",
            "Częstotliwość": FREQUENCY_LABELS[metrics.frequency] if metrics else "N/A",
            "Trend": TREND_LABELS[metrics.trend] if metrics else "N/A",
            "Najbliższa potwierdzona ex-date": (
                metrics.next_confirmed.ex_date if metrics and metrics.next_confirmed else "—"
            ),
        })
    totals = summarize_receipts(all_receipts, pln_rate_fn=market.pln_rate, year=today.year)
    cols = st.columns(3)
    cols[0].metric("Prognoza roczna brutto" + (" *" if forecast_missing else ""), _format_pln(forecast_total_pln))
    cols[1].metric(
        "Otrzymane netto (łącznie)",
        f"{totals.net_pln:,.2f} PLN" if all_receipts and totals.net_pln is not None else "—",
    )
    cols[2].metric(
        "Otrzymane netto (od 1 stycznia)",
        f"{totals.ytd_net_pln:,.2f} PLN" if all_receipts and totals.ytd_net_pln is not None else "—",
    )
    if forecast_missing:
        st.caption("* Bez prognozy (brak danych o dywidendach lub kursie): " + ", ".join(forecast_missing) + ".")
    if all_receipts:
        def money(values):
            return " | ".join(f"{v:,.2f} {c}" for c, v in sorted(values.items())) or "—"

        st.caption(
            f"Otrzymane brutto: {money(totals.gross_by_currency)} · podatek u źródła: "
            f"{money(totals.tax_by_currency)} · netto: {money(totals.net_by_currency)}"
            + (" · część kwot PLN po kursie NBP (orientacyjnie)" if totals.estimated else "")
        )
    _show_table(_name_first(table_rows))
    st.caption(
        "Prognoza = regularne wypłaty na akcję z ostatnich 12 mies. × posiadane akcje (brutto, dzisiejszy kurs NBP) — "
        "to NIE są otrzymane pieniądze. Yield on Cost = prognoza / koszt posiadanych akcji w PLN (przy koszcie 0, "
        "np. bonus: N/A). Otrzymane = Twój rejestr wypłat (karta pozycji → „Dywidendy otrzymane”)."
    )
_CHANGE_SOURCES = ("Na dzień skanu", "Bieżące")


def _format_pct(change) -> str:
    return "N/A" if change is None else f"{change.pct:+.1f}%"


def _price_changes_cells(rows: list[dict], *, complete: bool, ref_date: str | None = None) -> tuple[dict, dict, str]:
    """Komórki 1D..MAX (+ znaki do kolorowania) i opis anomalii (Faza 11, P2)."""
    series = [(r["date"], r["close"]) for r in rows]
    changes = compute_period_changes(series, ref_date=ref_date, history_complete=complete)
    scoped = [r for r in rows if ref_date is None or r["date"][:10] <= ref_date]
    anomalies = detect_price_anomalies(scoped)
    affected = periods_affected(changes, anomalies)
    cells, signs = {}, {}
    for period in PERIODS:
        change = changes[period]
        cells[period] = _format_pct(change) + (" ⚠" if period in affected else "")
        signs[period] = 0 if change is None else (1 if change.pct > 0 else -1 if change.pct < 0 else 0)
    cells["MAX od"] = changes["MAX"].start_date if changes["MAX"] else "—"
    note = "; ".join(
        f"skok {a.pct:+.0f}% {a.date} — możliwe zdarzenie korporacyjne" for a in anomalies if a.strong
    )
    return cells, signs, note


_NAME_COLUMN = "Spółka"


def _name_first(rows: list[dict]) -> list[dict]:
    """Nazwa spółki jako pierwsza kolumna -- przypięta przy przewijaniu w prawo."""
    return [{_NAME_COLUMN: r.get(_NAME_COLUMN), **{k: v for k, v in r.items() if k != _NAME_COLUMN}} for r in rows]


def _show_table(data) -> None:
    """Tabela z przypiętą kolumną „Spółka” (Decyzja właścicielki 2026-10-18:
    przy przewijaniu w prawo nazwa spółki zostaje widoczna)."""
    st.dataframe(
        data, use_container_width=True, hide_index=True,
        column_config={_NAME_COLUMN: st.column_config.TextColumn(_NAME_COLUMN, pinned=True)},
    )


def _style_change_table(table_rows: list[dict], signs: list[dict]):
    def css(column):
        return [
            _PL_GAIN_CSS if sign.get(column.name, 0) > 0 else _PL_LOSS_CSS if sign.get(column.name, 0) < 0 else ""
            for sign in signs
        ]
    return pd.DataFrame(_name_first(table_rows)).style.apply(css, subset=list(PERIODS))


def _render_top20_price_changes(scanner_conn, portfolio_conn, run, rows: list[dict]) -> None:
    """Faza 11 (P2): zmiany cen TOP20 + finaliści. Dwa jawnie rozdzielone
    źródła: snapshot skanu (stan na dzień skanu, niezmienny) i bieżące
    notowania FMP -- ceny skanu nigdy nie są podmieniane na dzisiejsze."""
    source = st.radio("Dane", _CHANGE_SOURCES, horizontal=True, key="top20_change_source")
    market = _market(portfolio_conn)
    table_rows, signs = [], []
    scan_dates = []
    since = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    for r in rows:
        notes = []
        warning = data_quality_warning(run["run_id"], r["cik"])
        if warning:
            notes.append(warning)
        if source == _CHANGE_SOURCES[0]:
            price_rows = get_scan_price_rows(scanner_conn, r["cik"])
            ref_date = run["run_date"]
            cells, sign, note = _price_changes_cells(price_rows, complete=False, ref_date=ref_date)
            if price_rows:
                scan_dates.append(max(p["date"] for p in price_rows if p["date"] <= ref_date))
        else:
            with st.spinner(f"Pobieram notowania {r['ticker']}…"):
                history = market.history_for_symbol("FMP", r["ticker"])
            if history is None:
                cells, sign, note = {p: "N/A" for p in PERIODS} | {"MAX od": "—"}, {}, "brak notowań"
            else:
                cells, sign, note = _price_changes_cells(history[0], complete=history[1])
            spin_off = market.has_recent_spin_off(r["ticker"], since)
            if spin_off:
                notes.append(f"wydzielenie spółki (spin-off) {spin_off} wg FMP")
        if note:
            notes.append(note)
        table_rows.append({
            "Ticker": r["ticker"],
            "TOP 5": top5_label(r),
            "Spółka": r["company_name"], **cells, "Uwagi": "; ".join(notes),
        })
        signs.append(sign)
    _show_table(_style_change_table(table_rows, signs))
    if source == _CHANGE_SOURCES[0]:
        st.caption(
            f"Notowania zapisane w skanie (ostatnia sesja {max(scan_dates) if scan_dates else '—'}); skan pobiera "
            "ok. 13 miesięcy historii, więc 5Y i MAX = N/A. Te liczby się nie zmieniają."
        )
    else:
        st.caption(
            "Bieżące notowania dzienne FMP (odświeżane co 12 h). MAX = najstarsza cena dostępna u dostawcy (data w "
            "kolumnie „MAX od”), nie zawsze debiut giełdowy. N/A = brak pełnej historii dla okresu."
        )
    st.caption(
        "Zmiana ceny, nie zwrot z dywidendami. ⚠ = okres obejmuje jednodniowy skok ≥50% albo ≥25% przy "
        "wielokrotnym wolumenie — możliwe zdarzenie korporacyjne (np. wydzielenie spółki), liczba może być "
        "niewiarygodna. Ranking i scoring bez zmian."
    )


def _render_portfolio_bar(portfolio_conn, scanner_conn, user: dict) -> None:
    """Sekcja 5 specyfikacji: jednoliniowy pasek, nigdy pełna tabela
    pozycji tutaj. Respektuje filtr platformy wybrany w zakładce
    PORTFEL (`st.session_state["platform_filter"]`) -- ten pasek
    renderuje się PRZED wejściem w zakładki, ale widget filtra jest
    zdefiniowany PÓŹNIEJ w tym samym przebiegu skryptu; czytanie jego
    `session_state` tutaj jest bezpieczne, bo Streamlit zachowuje
    wartość widgetu między przebiegami -- przy pierwszym uruchomieniu
    klucza jeszcze nie ma, stąd jawny fallback na "ALL" (Wszystkie)."""
    platform_filter = st.session_state.get("platform_filter", "ALL")
    broker = None if platform_filter == "ALL" else platform_filter
    market = _market(portfolio_conn)
    fx = market.nbp_table_a()
    positions_with_summaries = get_user_positions_with_summaries(
        portfolio_conn, scanner_conn, user["user_id"], broker=broker, quote_fn=market.quote_for_position, fx=fx,
        pln_rate_fn=market.pln_rate,
    )
    summaries = [s for _, s in positions_with_summaries]
    review_needed = get_review_needed_count(portfolio_conn, user["user_id"])

    st.subheader("Portfel")
    cols = st.columns(2)
    cols[0].metric("Pozycje", len(summaries))
    cols[1].metric("Do przeglądu", review_needed)
    if summaries:
        _render_pln_summary(
            st, positions_with_summaries, fx,
            dividends_net_pln=_dividends_received_pln(portfolio_conn, market, positions_with_summaries, broker),
        )
        _render_pricing_caption(st, summaries, fx, market.eodhd_calls_today())


def _format_decline_narrative(snapshot, triggered_flags: list[str]) -> str:
    """Sekcja 15 specyfikacji: "DLACZEGO SCANNER JĄ ZNALAZŁ?" -- jedno
    zdanie z realnymi % zmiany ceny, nigdy wymyślone liczby."""
    if snapshot is None:
        return "Brak wystarczającej historii cen, by pokazać szczegóły spadku."
    parts = []
    if snapshot.month_pct is not None:
        parts.append(f"zmiana ceny w ostatnim miesiącu: {snapshot.month_pct:.1f}%")
    if snapshot.drawdown_from_52w_high_pct is not None:
        parts.append(f"spadek od szczytu 52-tygodniowego: {snapshot.drawdown_from_52w_high_pct:.1f}%")
    detail = ", ".join(parts) if parts else "brak szczegółowych danych procentowych dla tego okna"
    return f"Wykryte sygnały: {decline_flags_label(triggered_flags)}. {detail.capitalize()}."


def _render_valuation_section(valuation_result, current_price: float) -> None:
    """Sekcja 15 specyfikacji: BEAR/BASE/BULL + jawne zastrzeżenie, że
    DCF to szacunek modelu, nie pewna wartość spółki (nigdy
    przedstawiana jako prawda)."""
    st.markdown("#### Wycena")
    st.write(f"Obecna cena: **{current_price}**")
    if not valuation_result.implemented:
        st.info(f"Wycena DCF niedostępna dla tej spółki. Powód: {valuation_result.reason}")
        return

    for scenario_key, label in _VALUATION_SCENARIO_LABELS:
        scenario = valuation_result.scenarios.get(scenario_key)
        if scenario is None:
            continue
        mos_text = (
            f"{scenario.margin_of_safety_pct:.1f}%" if scenario.margin_of_safety_pct is not None else "n/d"
        )
        st.write(
            f"**{label}**: szacowana wartość wewnętrzna/akcję ≈ {scenario.intrinsic_value_per_share:.2f}, "
            f"margines bezpieczeństwa: {mos_text}"
        )

    base_scenario = valuation_result.scenarios.get("base")
    if base_scenario is not None and base_scenario.margin_of_safety_pct is not None:
        direction = "wyższa" if base_scenario.margin_of_safety_pct >= 0 else "niższa"
        st.caption(
            "Według bazowego (BASE) scenariusza modelu szacowana wartość wewnętrzna jest o "
            f"{abs(base_scenario.margin_of_safety_pct):.1f}% {direction} od obecnej ceny. "
            "To szacunek oparty na modelu DCF przy założonych parametrach wzrostu/dyskonta, "
            "nie pewna, zweryfikowana wartość spółki."
        )


def _render_decision_buttons(portfolio_conn, *, user_id: int, cik: str) -> None:
    """Sekcja 16 specyfikacji: decyzja jest USER-SPECIFIC (`user_decisions`,
    append-only) -- Anastazja i mąż mogą mieć RÓŻNY status dla tej samej
    spółki, kliknięcie jednego usera nigdy nie zmienia SHARED analizy."""
    # Jedno zapytanie dla wszystkich kart (pamięć połączenia), nie 20.
    current = get_latest_user_decisions_for_user(portfolio_conn, user_id).get(cik)
    if current is not None:
        st.caption(f"Twoja ostatnia decyzja: **{decision_status_label(current['status'])}**")

    cols = st.columns(4)
    for col, (status, label) in zip(cols, _DECISION_BUTTONS):
        if col.button(label, key=f"decision_{cik}_{status}"):
            insert_user_decision(portfolio_conn, user_id=user_id, cik=cik, status=status)
            portfolio_conn.commit()
            st.rerun()


def _render_candidate_card(
    scanner_conn, portfolio_conn, run_id: str, cik: str, *, user_id: int, run_complete: bool = True,
) -> None:
    """Sekcja 15 specyfikacji UI -- pełna karta kandydata PO POLSKU.
    Deterministyczne sekcje (decline/wycena) zawsze renderowane; sekcje
    zależne od analizy LLM (`analysis`) pokazują jawnie "Analiza
    jakościowa niekompletna", gdy `llm_status != COMPLETE` -- nigdy nie
    ukrywają reszty karty ani przycisków decyzji (sekcja 16: decyzja
    musi być możliwa NIEZALEŻNIE od kompletności analizy jakościowej)."""
    detail = get_candidate_detail(scanner_conn, run_id, cik)
    analysis = detail["analysis"]

    st.header(f"{detail['ticker']} — {detail['company_name']}")
    if not run_complete:
        st.error("Skan niekompletny (INCOMPLETE) — to nie jest gotowy ranking inwestycyjny, wynik diagnostyczny.")
    warning = data_quality_warning(run_id, cik)
    if warning:
        st.warning(f"⚠ {warning}")

    st.markdown("#### Co to za firma?")
    reasoning = analysis.business_understandability.reasoning.strip() if analysis else ""
    if reasoning:
        st.write(reasoning)
    else:
        st.info("Opis spółki niedostępny w tej analizie.")

    st.markdown("#### Dlaczego scanner ją znalazł?")
    st.write(_format_decline_narrative(detail["decline_snapshot"], detail["triggered_decline_flags"]))

    if analysis is None:
        # Celowo BEZ surowego `llm_error` (sekcja 1 specyfikacji: "Nie
        # chcę czytać ... technicznych outputów") -- pełny techniczny
        # powód pozostaje dostępny w `live_scan_candidates.llm_error`
        # dla kogoś, kto faktycznie potrzebuje debugować raport.
        st.warning(analysis_status_label(detail["llm_status"]))
    else:
        st.markdown("#### Co przemawia za?")
        for item in analysis.bull_case:
            st.write(f"- {item}")
        st.markdown("#### Co przemawia przeciw?")
        for item in analysis.bear_case:
            st.write(f"- {item}")

    _render_valuation_section(detail["valuation_result"], detail["current_price"])
    _render_company_dividends(scanner_conn, portfolio_conn, cik=cik, ticker=detail["ticker"])

    st.markdown("#### Co muszę sprawdzić przed zakupem?")
    if analysis is None:
        st.warning(
            "Analiza jakościowa niekompletna — pełna lista rzeczy do sprawdzenia nie jest dziś "
            "dostępna dla tej spółki. Cena i wycena powyżej są dostępne niezależnie."
        )
    else:
        st.write(f"**Największa niewiadoma:** {analysis.biggest_unknown}")
        st.write("**Co obaliłoby tezę inwestycyjną:**")
        for item in analysis.thesis_invalidation:
            st.write(f"- {item}")
        if analysis.verification_items:
            st.write("**Do zweryfikowania przed decyzją:**")
            for vi in analysis.verification_items:
                st.write(f"- {vi.question or vi.reason}")

        st.markdown("#### Dlaczego rynek może mieć rację?")
        for item in analysis.why_market_may_be_right:
            st.write(f"- {item}")

        st.markdown("#### Dlaczego ta przecena może NIE być okazją?")
        for item in analysis.why_this_may_not_be_a_bargain:
            st.write(f"- {item}")

        st.markdown("#### Źródła")
        if detail["analysis_sources"]:
            for source in detail["analysis_sources"]:
                st.markdown(f"- [{source.title}]({source.url}) — {source.issuer}")
        else:
            st.caption("Brak zweryfikowanych źródeł dla tej analizy.")

    st.markdown("---")
    st.markdown("#### Twoja decyzja")
    _render_decision_buttons(portfolio_conn, user_id=user_id, cik=cik)


def _format_optional(value: float | None, fmt: str = "{:.2f}") -> str:
    return fmt.format(value) if value is not None else "—"


def _render_portfolio_summary_tab(
    portfolio_conn, positions_with_summaries: list, *, platform_filter: str = "ALL", fx: FxRates | None = None,
) -> None:
    """Sekcja 6 specyfikacji -- PODSUMOWANIE + tabela pozycji. Tabela
    jest na poziomie (pozycja, broker) -- sekcja 7: "szczegóły muszą
    zachować rozbicie na brokerów", nigdy tylko zagregowana linia.
    `positions_with_summaries` przychodzi JUŻ przefiltrowane po
    platformie (patrz `_render_portfolio_tab`) -- `platform_filter` jest
    tu tylko do poprawnego komunikatu o pustym stanie."""
    summaries = [s for _, s in positions_with_summaries]
    if not positions_with_summaries:
        if platform_filter == "ALL":
            st.info("Brak pozycji. Dodaj pierwszą transakcję w zakładce '+ Dodaj transakcję'.")
        else:
            st.info(f"Brak pozycji na platformie {broker_label(platform_filter)}.")
        return

    market = _market(portfolio_conn)
    broker = None if platform_filter == "ALL" else platform_filter
    with st.expander("Kwoty w oryginalnych walutach"):
        bar = compute_portfolio_bar_summary(summaries, review_needed_count=0)
        cols = st.columns(3)
        cols[0].metric("Wartość bieżąca", _format_currency_dict(bar["current_value_by_currency"]))
        cols[1].metric("Zainwestowany kapitał", _format_currency_dict(bar["invested_by_currency"]))
        _render_pl_metric(cols[2], "Zysk/strata", bar["unrealized_pl_by_currency"])
        st.caption("Każda waluta osobno — bez przeliczania i bez sumowania różnych walut.")

    portfolio_view = st.radio("Widok pozycji", _PORTFOLIO_VIEWS, horizontal=True, key="portfolio_view")
    if portfolio_view == "Zmiany cen":
        _render_portfolio_price_changes(portfolio_conn, positions_with_summaries)
        return
    if portfolio_view == "Dywidendy":
        _render_portfolio_dividends(portfolio_conn, positions_with_summaries, fx, broker)
        return

    st.markdown("##### Pozycje (rozbicie per broker)")
    table_rows = []
    pl_signs = []
    pln_signs = []
    for position, summary in positions_with_summaries:
        latest_action = get_latest_holding_user_action(portfolio_conn, position["position_id"])
        status_label = holding_action_label(latest_action["action"]) if latest_action else "Trzymam"
        for sub in summary.by_broker_currency:
            # WŁASNA wartość tej subpozycji (broker), NIE suma całej
            # pozycji -- patrz komentarz w `BrokerCurrencySubposition`
            # (realny bug znaleziony przy weryfikacji wizualnej).
            current_value = sub.current_value
            pl = sub.unrealized_pl
            pl_pct = pl / sub.total_invested * 100 if pl is not None and sub.total_invested > 0 else None
            current_price_per_share = (
                current_value / sub.shares_held if current_value is not None and sub.shares_held > 0 else None
            )
            if not is_instrument_confirmed(position):
                price_note = "Instrument niepotwierdzony — popraw w karcie pozycji"
            elif current_value is None and sub.shares_held > 0:
                price_note = "Brak ceny lub kursu waluty"
            else:
                price_note = ""
            table_rows.append({
                "Ticker": position["ticker"],
                "Spółka": position["company_name"],
                "Platforma": broker_label(sub.broker),
                "Ilość": _format_shares(sub.shares_held),
                "Śr. cena zakupu": _format_optional(sub.avg_price),
                "Własny koszt": f"{sub.total_invested:.2f} {sub.currency}",
                "Bieżąca cena": (
                    f"{current_price_per_share:.2f} {sub.currency}" if current_price_per_share is not None else "—"
                ),
                "Bieżąca wartość": (
                    f"{current_value:.2f} {sub.currency}" if current_value is not None else "—"
                ),
                "Źródło ceny": _format_quote_source(summary),
                "Wartość (PLN)": _format_pln(sub.current_value_pln),
                "Koszt (PLN)": (_format_pln(sub.invested_pln) + (" ≈" if sub.pln_cost_estimated else ""))
                if sub.invested_pln is not None else "—",
                "Zysk/strata (PLN)": _format_pln(sub.unrealized_pl_pln, signed=True),
                "Zysk/strata": f"{pl:+.2f} {sub.currency}" if pl is not None else "—",
                "Zysk/strata %": f"{pl_pct:+.1f}%" if pl_pct is not None else "n/d",
                "Sposób nabycia": acquisition_types_label(sub.acquisition_types),
                "Status": status_label,
                "Uwagi": price_note,
            })
            realizable, _basis = _realizable_for_sub(market, position, sub, fx)
            if realizable is not None:
                table_rows[-1]["Przy sprzedaży (PLN)"] = _format_pln(realizable)
            pl_signs.append(0 if pl is None else (1 if pl > 0 else -1 if pl < 0 else 0))
            pln_pl = sub.unrealized_pl_pln
            pln_signs.append(0 if pln_pl is None else (1 if pln_pl > 0 else -1 if pln_pl < 0 else 0))

    if not table_rows:
        # Np. pozycja, której wszystkie transakcje anulowano (Faza 9).
        st.info("Brak aktywnych transakcji w pozycjach.")
        return

    def _pl_column_css(_column):
        return [_PL_GAIN_CSS if sign > 0 else _PL_LOSS_CSS if sign < 0 else "" for sign in pl_signs]

    def _pln_column_css(_column):
        return [_PL_GAIN_CSS if sign > 0 else _PL_LOSS_CSS if sign < 0 else "" for sign in pln_signs]

    if any("Przy sprzedaży (PLN)" in row for row in table_rows):
        for row in table_rows:
            row.setdefault("Przy sprzedaży (PLN)", "—")
    styled = (
        pd.DataFrame(_name_first(table_rows)).style
        .apply(_pl_column_css, subset=["Zysk/strata", "Zysk/strata %"])
        .apply(_pln_column_css, subset=["Zysk/strata (PLN)"])
    )
    _show_table(styled)
    st.caption(
        "Bieżąca cena i wartość w walucie, w której zapłaciłaś/eś (np. PLN) — przeliczone kursem NBP. "
        "Zysk/strata = bieżąca wartość − własny koszt, razem z efektem zmiany kursu waluty."
    )


_PORTFOLIO_VIEWS = ("Wycena", "Zmiany cen", "Dywidendy")
_PORTFOLIO_SECTIONS = ("Kategorie", "Wszystkie pozycje", "Wg platform", "+ Dodaj transakcję")


def _pl_styled(rows: list[dict], signs: list[int], columns: list[str]):
    """Zielony zysk / czerwona strata w podanych kolumnach (Styler)."""
    return pd.DataFrame(rows).style.apply(
        lambda _col: [_PL_GAIN_CSS if x > 0 else _PL_LOSS_CSS if x < 0 else "" for x in signs], subset=columns,
    )


def _sign(value: float | None) -> int:
    return 0 if not value else (1 if value > 0 else -1)


def _render_category_comparison(positions_with_summaries: list, categories: dict) -> None:
    """Porównanie kategorii (które grupy zyskują, które tracą) i
    ekspozycja na metale szlachetne -- każda pozycja liczona raz."""
    with st.expander("Porównanie kategorii i ekspozycja na metale"):
        rows, signs = [], []
        for key, data in categories.items():
            pl = data["unrealized_pl_pln"]
            rows.append({
                "Kategoria": CATEGORY_LABELS[key], "Wartość (PLN)": _format_pln(data["value_pln"]),
                "Wynik (PLN)": _format_pln(pl, signed=True),
                "Wynik %": f"{data['unrealized_pl_pct']:+.1f}%" if data["unrealized_pl_pct"] is not None else "—",
                "Udział": f"{data['share_pct']:.1f}%" if data["share_pct"] is not None else "—",
            })
            signs.append(_sign(pl))
        st.dataframe(_pl_styled(rows, signs, ["Wynik (PLN)", "Wynik %"]), hide_index=True, use_container_width=True)
        exposure = exposure_summary(positions_with_summaries)
        total = sum(exposure["by_class"].values())
        metal_rows = []
        for metal, parts in exposure["metals"].items():
            if parts["physical"] or parts["platform"] or parts["exchange"]:
                metal_rows.append({
                    "Metal": METAL_LABELS[metal], "Fizyczny (PLN)": round(parts["physical"], 2),
                    "Na platformie (PLN)": round(parts["platform"], 2),
                    "Giełdowy ETF/ETC/ETN (PLN)": round(parts["exchange"], 2),
                    "Razem (PLN)": round(parts["physical"] + parts["platform"] + parts["exchange"], 2),
                })
        if metal_rows and total > 0:
            st.markdown("Ekspozycja na metale szlachetne")
            st.dataframe(metal_rows, hide_index=True, use_container_width=True)
            precious = sum(r["Razem (PLN)"] for r in metal_rows)
            st.write(f"Łącznie metale szlachetne: **{precious:,.0f} PLN** ({precious / total * 100:.1f}% wycenionej części portfela).")
        st.caption(
            "Metal fizyczny i metal na platformie (np. XAG/XAU w Revolut) wyceniane po cenie spot czystego metalu "
            "(złoto: NBP; srebro: kontrakt FMP jako przybliżenie) — to nie cena odkupu u dealera ani cena "
            "sprzedaży na platformie. Giełdowe ETF/ETC/ETN po cenie rynkowej, nie jako gramy "
            "metalu na własność; każda pozycja liczona raz. Udział = część wycenionej wartości portfela."
            + (f" Bez wyceny (pominięte): {', '.join(exposure['unpriced'])}." if exposure["unpriced"] else "")
        )


def _position_pln(summary) -> tuple[float | None, float | None, float | None]:
    """(wartość, koszt, wynik) pozycji w PLN -- suma jej subpozycji
    (platform); None, gdy którejś posiadanej subpozycji brakuje ceny/kursu."""
    held = [sub for sub in summary.by_broker_currency if sub.shares_held > 1e-12]
    values = [sub.current_value_pln for sub in held]
    costs = [sub.invested_pln for sub in held]
    value = sum(values) if all(v is not None for v in values) else None
    cost = sum(costs) if all(c is not None for c in costs) else None
    return value, cost, (value - cost) if value is not None and cost is not None else None


def _instrument_label(position) -> str:
    position = dict(position)
    if asset_class_of(position) in PHYSICAL:
        return (position.get("company_name") or position["ticker"])[:30]
    return position["ticker"]


def _render_categories(portfolio_conn, positions_with_summaries: list) -> None:
    """Widok domyślny PORTFELA: kategoria aktywów (poziom 1) -> dashboard
    kategorii -> tabela jej instrumentów -> instrument (poziom 2) i jego
    karta z historią i edycją transakcji. Liczby z tej samej logiki co
    pasek portfela u góry; sprzedane w całości pozycje nie są aktywne."""
    categories = category_summaries(positions_with_summaries)
    if not categories:
        return
    keys = list(categories)
    chosen = st.segmented_control(
        "Kategoria", keys, default=keys[0], key="portfolio_category",
        format_func=lambda k: f"{CATEGORY_LABELS[k]} ({categories[k]['active_count']})",
    )
    key = chosen if chosen in categories else keys[0]
    data = categories[key]

    star = " *" if data["missing"] else ""
    pl, pct = data["unrealized_pl_pln"], data["unrealized_pl_pct"]
    cols = st.columns(2)
    cols[0].metric(
        f"{CATEGORY_LABELS[key]} — wartość{star}", _format_pln(data["value_pln"]),
        delta=(_format_pln(pl, signed=True) + (f" ({pct:+.1f}%)" if pct is not None else "")) if pl else None,
        help="Zmiana = wynik niezrealizowany: wartość dziś minus historyczny koszt nabycia (PLN).",
    )
    cols[1].metric("Udział w portfelu", f"{data['share_pct']:.1f}%" if data["share_pct"] is not None else "—")
    realized = data["realized_pl_pln"]
    st.markdown(
        f"Koszt nabycia{star}: **{_format_pln(data['cost_pln'])}** · aktywne pozycje: **{data['active_count']}**"
        + (f" · zamknięte: {data['closed_count']}" if data["closed_count"] else "")
        + f" · zrealizowany: {_color_pl_text(realized, _format_pln(realized, signed=True)) if realized is not None else '—'}"
    )
    if data["missing"]:
        st.warning("* Wycena częściowa — brak ceny lub kursu dla: " + ", ".join(data["missing"]) + ".")

    active = [(p, s) for p, s in data["positions"] if is_active(s)]
    closed = [(p, s) for p, s in data["positions"] if not is_active(s)]
    if active:
        rows, signs = [], []
        for position, summary in active:
            value, cost, pl = _position_pln(summary)
            rows.append({
                "Instrument": _instrument_label(position),
                "Ilość": _format_shares(summary.shares_held),
                "Wartość (PLN)": _format_pln(value),
                "Wynik (PLN)": _format_pln(pl, signed=True),
                "Wynik %": f"{pl / cost * 100:+.1f}%" if pl is not None and cost else "—",
                "Koszt (PLN)": _format_pln(cost),
            })
            signs.append(_sign(pl))
        st.dataframe(
            _pl_styled(rows, signs, ["Wynik (PLN)", "Wynik %"]), use_container_width=True, hide_index=True,
            column_config={"Instrument": st.column_config.TextColumn("Instrument", pinned=True)},
        )
    if closed:
        st.caption("Zamknięte (sprzedane w całości): " + ", ".join(
            f"{_instrument_label(p)} — wynik zrealizowany "
            + _format_pln(sum(sub.realized_pl_pln or 0.0 for sub in s.by_broker_currency), signed=True)
            for p, s in closed
        ))

    by_id = {p["position_id"]: (p, s) for p, s in active + closed}

    def label(position_id) -> str:
        position, summary = by_id[position_id]
        return _instrument_label(position) + ("" if is_active(summary) else " (zamknięta)")

    if len(by_id) <= 20:
        selected = st.pills("Instrument — szczegóły i transakcje", list(by_id), format_func=label,
                            key=f"portfolio_instrument_{key}")
    else:
        selected = st.selectbox("Instrument — szczegóły i transakcje", list(by_id), index=None, format_func=label,
                                placeholder="Wybierz instrument", key=f"portfolio_instrument_{key}")
    if selected in by_id:
        position, summary = by_id[selected]
        with st.container(border=True):
            _render_position_card(portfolio_conn, dict(position), summary)
    else:
        st.caption("Wybierz instrument, aby zobaczyć jego szczegóły, historię i edycję transakcji.")

    _render_category_comparison(positions_with_summaries, categories)


def _render_platform_breakdown(positions_with_summaries: list) -> None:
    """Dodatkowy widok: wartość, koszt i wynik według platform (brokerów).
    Pełna tabela pozycji z rozbiciem na platformy -> „Wszystkie pozycje”."""
    pln = compute_portfolio_pln_summary(positions_with_summaries)
    if not pln["by_broker"]:
        st.info("Brak wycenionych pozycji.")
        return
    rows, signs = [], []
    for broker, values in sorted(pln["by_broker"].items()):
        pl = values["value_pln"] - values["cost_pln"]
        rows.append({
            "Platforma": broker_label(broker), "Wartość (PLN)": _format_pln(values["value_pln"]),
            "Koszt (PLN)": _format_pln(values["cost_pln"]), "Wynik (PLN)": _format_pln(pl, signed=True),
            "Wynik %": f"{pl / values['cost_pln'] * 100:+.1f}%" if values["cost_pln"] else "—",
        })
        signs.append(_sign(pl))
    st.dataframe(_pl_styled(rows, signs, ["Wynik (PLN)", "Wynik %"]), hide_index=True, use_container_width=True)
    st.caption(
        "Tylko wycenione pozycje. Filtr „Platforma” powyżej zawęża cały portfel do jednej platformy; "
        "pełna tabela z rozbiciem na platformy jest w „Wszystkie pozycje”."
        + (" Bez wyceny: " + ", ".join(pln["missing"]) + "." if pln["missing"] else "")
    )


def _position_history(market: MarketData, position) -> tuple[list[dict], bool, str] | None:
    """Notowania pozycji od jej dostawcy ceny (tylko potwierdzony instrument)."""
    position = dict(position)
    if not is_instrument_confirmed(position) or asset_class_of(position) in (*PHYSICAL, COMMODITY):
        return None
    provider = position.get("price_provider")
    symbol = position.get("price_symbol") or position["ticker"]
    return market.history_for_symbol(provider, symbol)


def _render_portfolio_price_changes(portfolio_conn, positions_with_summaries: list) -> None:
    """Faza 11 (P2): zmiany cen posiadanych instrumentów (po pozycji, nie
    po brokerze -- cena jest ta sama na każdej platformie)."""
    market = _market(portfolio_conn)
    table_rows, signs = [], []
    for position, _summary in positions_with_summaries:
        history = _position_history(market, position)
        if history is None:
            cells, sign, note = {p: "N/A" for p in PERIODS} | {"MAX od": "—"}, {}, ""
            source = "brak (instrument niepotwierdzony albo brak danych)"
        else:
            cells, sign, note = _price_changes_cells(history[0], complete=history[1])
            source = history[2]
        table_rows.append({
            "Ticker": position["ticker"], "Spółka": position["company_name"], **cells,
            "Źródło": source, "Uwagi": note,
        })
        signs.append(sign)
    _show_table(_style_change_table(table_rows, signs))
    st.caption(
        "Zmiana ceny instrumentu w walucie notowania (nie Twój wynik inwestycji — ten jest w widoku „Wycena”). "
        "EODHD w darmowym planie daje tylko ostatni rok: 5Y i MAX = N/A. ⚠ = możliwe zdarzenie korporacyjne."
    )


def _render_position_card(portfolio_conn, position: dict, summary) -> None:
    """Sekcja 14 specyfikacji -- karta JEDNEJ posiadanej pozycji."""
    st.header(f"{position['ticker']} — {position['company_name']}")

    thesis = get_purchase_thesis(portfolio_conn, position["position_id"])
    snapshot: dict = {}
    if thesis is not None and thesis["snapshot_json"]:
        try:
            snapshot = json.loads(thesis["snapshot_json"])
        except (TypeError, ValueError):
            snapshot = {}

    # Opis firmy i teza zakupowa pochodzą z analizy spółek scannera -- dla
    # metali, krypto i funduszy tylko zaśmiecałyby kartę na telefonie.
    is_stock = asset_class_of(position) == STOCK
    if is_stock:
        st.markdown("#### Co to za firma?")
        description = snapshot.get("business_description") if snapshot else None
        if description:
            st.write(description)
        else:
            st.info("Opis spółki niedostępny — ta pozycja nie ma jeszcze zapisanej analizy scannera.")

    st.markdown("#### Moja pozycja")
    st.write(f"Liczba akcji/jednostek: **{_format_shares(summary.shares_held)}**")
    brokers = sorted({sub.broker for sub in summary.by_broker_currency})
    st.write(f"Broker(rzy): {', '.join(broker_label(b) for b in brokers) or '—'}")
    for currency, invested in summary.invested_by_currency.items():
        value = (summary.current_value_by_currency or {}).get(currency)
        pl = (summary.unrealized_pl_by_currency or {}).get(currency)
        pl_text = _color_pl_text(pl, f"{pl:+.2f} {currency}") if pl is not None else "—"
        st.markdown(
            f"Własny koszt: {invested:.2f} {currency} | "
            f"Bieżąca wartość: {(f'{value:.2f} {currency}' if value is not None else '—')} | "
            f"Zysk/strata: {pl_text}"
        )
    for sub in summary.by_broker_currency:
        realized = sub.realized_pl_pln
        st.markdown(
            f"- {broker_label(sub.broker)}: {_format_shares(sub.shares_held)} szt., "
            f"śr. cena {_format_optional(sub.avg_price)} {sub.currency} · koszt "
            f"{_format_pln(sub.invested_pln)}{' (kurs NBP, orientacyjnie)' if sub.pln_cost_estimated else ''} · "
            f"wartość {_format_pln(sub.current_value_pln)} · wynik "
            f"{_color_pl_text(sub.unrealized_pl_pln, _format_pln(sub.unrealized_pl_pln, signed=True)) if sub.unrealized_pl_pln is not None else '—'}"
            + (f" · zrealizowany {_color_pl_text(realized, _format_pln(realized, signed=True))}" if realized else "")
        )

    if is_stock:
        st.markdown("#### Dlaczego ją mam?")
        bull_case = snapshot.get("bull_case") if snapshot else None
        if bull_case:
            for item in bull_case:
                st.write(f"- {item}")
        else:
            st.info("Zakup przed analizą scannera — teza do uzupełnienia.")

        st.markdown("#### Co się zmieniło od zakupu?")
        st.info("Brak danych — monitoring zmian od zakupu nie jest jeszcze częścią V0.")

        st.markdown("#### Co obserwować?")
        thesis_invalidation = snapshot.get("thesis_invalidation") if snapshot else None
        biggest_unknown = snapshot.get("biggest_unknown") if snapshot else None
        if thesis_invalidation or biggest_unknown:
            if thesis_invalidation:
                st.write("**Co obaliłoby tezę:**")
                for item in thesis_invalidation:
                    st.write(f"- {item}")
            if biggest_unknown:
                st.write(f"**Największa niewiadoma:** {biggest_unknown}")
        else:
            st.info("Niedostępne — brak zapisanej tezy zakupowej dla tej pozycji.")

    st.markdown("---")
    st.markdown("#### Status")
    latest_action = get_latest_holding_user_action(portfolio_conn, position["position_id"])
    if latest_action is not None:
        st.caption(f"Obecny status: **{holding_action_label(latest_action['action'])}**")
    cols = st.columns(4)
    for col, (action, label) in zip(cols, _HOLDING_ACTION_BUTTONS):
        if col.button(label, key=f"holding_{position['position_id']}_{action}"):
            insert_holding_user_action(portfolio_conn, position_id=position["position_id"], action=action)
            portfolio_conn.commit()
            st.rerun()

    st.markdown("---")
    _position_forms_fragment(portfolio_conn, position, summary)


@st.fragment
def _position_forms_fragment(full_run_conn, position: dict, summary) -> None:
    """Formularze karty pozycji: wybory w nich odświeżają tylko ten
    fragment; zapis woła `st.rerun()` = pełne odświeżenie."""
    with _fragment_portfolio_conn(full_run_conn) as portfolio_conn:
        if asset_class_of(position) in PHYSICAL:
            with st.expander("Wycena ręczna i cena odkupu", expanded=True):
                _render_manual_valuations(portfolio_conn, position, summary)
        elif asset_class_of(position) == COMMODITY:
            with st.expander("Wartość rynkowa i kwota przy sprzedaży", expanded=True):
                _render_commodity_sale_value(portfolio_conn, position, summary)
        else:
            with st.expander("Dywidendy otrzymane"):
                _render_dividend_register(portfolio_conn, position)
        with st.expander("Historia i edycja transakcji (zmiana typu: zakup / sprzedaż / bonus)"):
            _render_transaction_editor(portfolio_conn, position)
        with st.expander("Popraw dane / anuluj błędny wpis"):
            _render_instrument_correction(portfolio_conn, position)
            st.markdown("---")
            _render_transaction_voiding(portfolio_conn, position)


def _realizable_for_sub(market: MarketData, position, sub, fx) -> tuple[float | None, str | None]:
    """Kwota przy sprzedaży (PLN) dla subpozycji metalu na platformie lub
    metalu fizycznego: cena sprzedaży/odkupu wpisana ręcznie albo (tylko
    platforma) wartość rynkowa minus opłata. Inne klasy -- None."""
    position = dict(position)
    asset_class = asset_class_of(position)
    if asset_class not in (*PHYSICAL, COMMODITY) or sub.shares_held <= 1e-12:
        return None, None
    sale_price = market.manual_valuation(position, "BUYBACK")
    sale_value_pln = (
        convert(sale_price.price * sub.shares_held, sale_price.currency, "PLN", fx) if sale_price is not None else None
    )
    fee_pct = position.get("sale_fee_pct") if asset_class == COMMODITY else None
    return realizable_value_pln(sub.current_value_pln, sale_fee_pct=fee_pct, sale_price_value_pln=sale_value_pln)


def _render_commodity_sale_value(portfolio_conn, position: dict, summary) -> None:
    """Metal na platformie: wartość rynkowa (spot) OBOK kwoty możliwej do
    uzyskania przy sprzedaży -- ta jest niższa o opłatę platformy. Opłatę
    albo cenę sprzedaży podaje właścicielka (nie zgadujemy cennika)."""
    market = _market(portfolio_conn)
    fx = market.nbp_table_a()
    held = [sub for sub in summary.by_broker_currency if sub.shares_held > 1e-12]
    values = [sub.current_value_pln for sub in held]
    market_pln = sum(values) if values and all(v is not None for v in values) else None
    realizable = [_realizable_for_sub(market, position, sub, fx) for sub in held]
    st.write(f"Ilość: **{_format_shares(summary.shares_held)} oz** (uncje trojańskie czystego metalu)")
    st.write(
        "Wartość rynkowa (cena spot): **"
        + (f"{market_pln:,.2f} PLN" if market_pln is not None else "brak ceny") + "**"
    )
    if realizable and all(r[0] is not None for r in realizable):
        st.write(
            f"Do uzyskania przy sprzedaży: **{sum(r[0] for r in realizable):,.2f} PLN** ({realizable[0][1]})"
        )
    else:
        st.info("Kwota przy sprzedaży: brak danych — podaj opłatę platformy przy sprzedaży albo cenę sprzedaży poniżej.")

    purchases = get_purchase_transactions(portfolio_conn, position["position_id"])
    paid_fees = [
        (tx["fees"], tx["total_invested"], tx["currency"]) for tx in purchases
        if tx["fees"] and tx["total_invested"] > tx["fees"]
    ]
    if paid_fees:
        fee, total, currency = paid_fees[-1]
        st.caption(
            f"Dla porównania: przy ostatnim zakupie z opłatą zapłaciłaś/eś {fee:.2f} {currency} opłaty "
            f"= {fee / (total - fee) * 100:.2f}% wartości metalu. Opłata przy sprzedaży może być inna — sprawdź w aplikacji platformy."
        )

    with st.form(f"commodity_fee_{position['position_id']}"):
        current_fee = position.get("sale_fee_pct")
        fee_pct = st.number_input(
            "Opłata platformy przy sprzedaży (%)", min_value=0.0, max_value=99.0, step=0.01, format="%.2f",
            value=float(current_fee) if current_fee is not None else 0.0,
        )
        clear = st.checkbox("Nie znam opłaty (usuń zapisaną)")
        if st.form_submit_button("Zapisz opłatę"):
            update_position_fields(portfolio_conn, position["position_id"], sale_fee_pct=None if clear else fee_pct)
            portfolio_conn.commit()
            st.rerun()

    sale_price = market.manual_valuation(position, "BUYBACK")
    if sale_price is not None:
        st.caption(f"Zapisana cena sprzedaży z platformy: {sale_price.price:,.2f} {sale_price.currency}/oz (z {sale_price.as_of}).")
    with st.form(f"commodity_sale_price_{position['position_id']}", clear_on_submit=True):
        st.markdown("Cena sprzedaży widoczna w aplikacji platformy (ma pierwszeństwo przed opłatą %)")
        cols = st.columns(2)
        price = cols[0].number_input("Cena za 1 oz", min_value=0.0, step=0.01, format="%.2f")
        currency = cols[1].text_input("Waluta", value="PLN")
        valuation_date = st.date_input("Data")
        if st.form_submit_button("Zapisz cenę sprzedaży"):
            if price <= 0 or not currency.strip():
                st.error("Podaj cenę i walutę.")
            else:
                insert_manual_valuation(
                    portfolio_conn, position_id=position["position_id"], kind="BUYBACK", price_per_unit=price,
                    currency=currency.strip().upper(), valuation_date=str(valuation_date),
                    note="cena sprzedaży z platformy",
                )
                portfolio_conn.commit()
                st.rerun()


def _render_manual_valuations(portfolio_conn, position: dict, summary) -> None:
    """Faza 11 (P4): metal fizyczny -- wycena ręczna (gdy brak ceny
    automatycznej albo moneta kolekcjonerska) i szacunkowa cena odkupu u
    dealera, zawsze z datą. Odkup pokazywany OBOK spot, nigdy zamiast."""
    market = _market(portfolio_conn)
    grams = pure_grams_per_piece(position.get("unit_weight"), position.get("weight_unit"), position.get("fineness"))
    st.write(
        f"{PRODUCT_FORM_LABELS.get(position.get('product_form'), 'produkt')} · czysty metal w sztuce: "
        f"{f'{grams:.4f} g' if grams else '—'} · przechowywanie: {position.get('storage_location') or '—'}"
        + (" · moneta kolekcjonerska (bez wyceny spot)" if position.get("is_collectible") else "")
    )
    buyback = market.manual_valuation(position, "BUYBACK")
    if buyback is not None:
        st.write(
            f"Szacunkowa wartość odkupu: **{buyback.price * summary.shares_held:,.2f} {buyback.currency}** "
            f"({buyback.price:,.2f} {buyback.currency}/szt., wpis z {buyback.as_of})."
        )
    with st.form(f"manual_valuation_{position['position_id']}", clear_on_submit=True):
        kind = st.radio(
            "Rodzaj wyceny", ("BUYBACK", "MARKET"), horizontal=True,
            format_func=lambda k: "cena odkupu u dealera" if k == "BUYBACK" else "wartość rynkowa (zamiast spot)",
        )
        price = st.number_input("Cena za 1 sztukę", min_value=0.0, step=0.01, format="%.2f")
        currency = st.text_input("Waluta", value="PLN")
        valuation_date = st.date_input("Data wyceny")
        note = st.text_input("Źródło / notatka (np. nazwa dealera)")
        if st.form_submit_button("Zapisz wycenę"):
            if price <= 0 or not currency.strip():
                st.error("Podaj cenę i walutę.")
            else:
                insert_manual_valuation(
                    portfolio_conn, position_id=position["position_id"], kind=kind, price_per_unit=price,
                    currency=currency.strip().upper(), valuation_date=str(valuation_date), note=note.strip() or None,
                )
                portfolio_conn.commit()
                st.rerun()


def _render_dividend_register(portfolio_conn, position: dict) -> None:
    """Faza 11 (P3): rejestr FAKTYCZNIE otrzymanych dywidend (z wyciągu
    brokera) -- brutto, podatek u źródła, netto, waluta, kurs brokera.
    Reinwestycję wpisuje się osobno jako zakup."""
    position_id = position["position_id"]
    receipts = get_dividend_receipts(portfolio_conn, position_id)
    if receipts:
        st.dataframe(
            [
                {"Wypłata": r["pay_date"], "Ex-date": r["ex_date"] or "—", "Platforma": broker_label(r["broker"]),
                 "Brutto": r["gross_amount"], "Podatek u źródła": r["withholding_tax"] or 0.0,
                 "Netto": round(receipt_net(r), 4), "Waluta": r["currency"],
                 "Kurs brokera": r["fx_rate_actual"] or "—"}
                for r in receipts
            ],
            hide_index=True, use_container_width=True,
        )
    else:
        st.caption("Brak zapisanych wypłat.")
    with st.form(f"dividend_form_{position_id}", clear_on_submit=True):
        broker = st.selectbox("Platforma", _BROKER_OPTIONS, format_func=broker_label, key=f"div_broker_{position_id}")
        pay_date = st.date_input("Data wypłaty", key=f"div_pay_{position_id}")
        gross = st.number_input("Kwota brutto", min_value=0.0, step=0.01, format="%.4f", key=f"div_gross_{position_id}")
        tax = st.number_input("Podatek u źródła", min_value=0.0, step=0.01, format="%.4f", key=f"div_tax_{position_id}")
        net = st.number_input(
            "Kwota netto (opcjonalnie — domyślnie brutto minus podatek)", min_value=0.0, step=0.01, format="%.4f",
            key=f"div_net_{position_id}",
        )
        currency = st.text_input("Waluta wypłaty (np. USD, EUR, PLN)", key=f"div_ccy_{position_id}")
        fx_rate = st.number_input(
            "Kurs brokera (opcjonalnie): ile PLN za 1 jednostkę waluty", min_value=0.0, step=0.0001, format="%.4f",
            key=f"div_fx_{position_id}",
        )
        note = st.text_input("Notatka (opcjonalnie)", key=f"div_note_{position_id}")
        if st.form_submit_button("Zapisz otrzymaną dywidendę"):
            errors = []
            if gross <= 0:
                errors.append("Kwota brutto musi być większa od zera.")
            if not currency.strip():
                errors.append("Waluta jest wymagana.")
            if tax > gross:
                errors.append("Podatek nie może być wyższy niż kwota brutto.")
            for error in errors:
                st.error(error)
            if not errors:
                insert_dividend_receipt(
                    portfolio_conn, position_id=position_id, broker=broker, pay_date=str(pay_date),
                    gross_amount=gross, currency=currency.strip().upper(), withholding_tax=tax or None,
                    net_amount=net or None, fx_rate_actual=(fx_rate or None) if currency.strip().upper() != "PLN" else None,
                    note=note.strip() or None,
                )
                portfolio_conn.commit()
                st.toast("Zapisano dywidendę.")
                st.rerun()
    if receipts:
        with st.form(f"dividend_void_form_{position_id}"):
            index = st.selectbox(
                "Błędny wpis do anulowania", range(len(receipts)),
                format_func=lambda i: f"{receipts[i]['pay_date']} · {receipts[i]['gross_amount']} {receipts[i]['currency']}",
            )
            sure = st.checkbox("Tak, anuluj ten wpis (zostaje w historii bazy)")
            if st.form_submit_button("Anuluj wpis dywidendy"):
                if not sure:
                    st.error("Zaznacz potwierdzenie.")
                else:
                    void_dividend_receipt(portfolio_conn, receipts[index]["receipt_id"])
                    portfolio_conn.commit()
                    st.rerun()


def _render_instrument_correction(portfolio_conn, position: dict) -> None:
    """Faza 9 -- poprawa tożsamości instrumentu (np. `SU` -> `SU.PA`).
    Te same reguły co przy nowej pozycji: rozpoznany symbol wymaga
    jawnego potwierdzenia. Transakcje (koszt) zostają nietknięte."""
    position_id = position["position_id"]
    st.markdown("##### Instrument")
    status = "potwierdzony" if is_instrument_confirmed(position) else "NIEPOTWIERDZONY — cena bieżąca nie jest pobierana"
    provider = position.get("price_provider") or ("FMP" if is_instrument_confirmed(position) else "—")
    st.write(
        f"Obecnie: **{position['ticker']}** — {position['company_name']} "
        f"({position['exchange'] or 'giełda nieznana'}, ISIN {position.get('isin') or '—'}). "
        f"Status: {status}. Źródło ceny: {provider}."
    )
    choice = _render_instrument_lookup_widget(f"fix_{position_id}", _market(portfolio_conn))
    confirmed_result = choice.confirmed_result
    current_class = position.get("asset_class") or (
        _default_asset_class(choice.result) if choice.result else "STOCK"
    )
    asset_class = _render_asset_class_picker(f"fix_{position_id}_asset_class", current_class)
    with st.form(f"fix_instrument_form_{position_id}"):
        company_name = st.text_input(
            "Nazwa spółki",
            value=(confirmed_result.company_name if confirmed_result else None) or position["company_name"],
        )
        exchange = st.text_input(
            "Giełda (opcjonalnie)",
            value=(confirmed_result.exchange if confirmed_result else None) or position["exchange"] or "",
        )
        if st.form_submit_button("Zapisz poprawiony instrument"):
            errors = choice.save_errors()
            if not company_name.strip():
                errors.append("Nazwa spółki jest wymagana.")
            for error in errors:
                st.error(error)
            if not errors:
                ticker = (confirmed_result.symbol if confirmed_result else choice.symbol).strip()
                update_position_instrument(
                    portfolio_conn, position_id=position_id, ticker=ticker, company_name=company_name.strip(),
                    cik=(confirmed_result.cik if confirmed_result else None),
                    exchange=(exchange.strip() or None), instrument_confirmed=confirmed_result is not None,
                )
                update_position_fields(
                    portfolio_conn, position_id, **_instrument_identity_fields(confirmed_result, asset_class),
                )
                portfolio_conn.commit()
                for key in (f"fix_{position_id}_lookup_symbol", f"fix_{position_id}_lookup_result"):
                    st.session_state.pop(key, None)
                st.toast(f"Zapisano instrument: {ticker}.")
                st.rerun()


def _describe_transaction(kind: str, row) -> str:
    if kind == "PURCHASE":
        label = acquisition_types_label((row["acquisition_type"],))
        return (
            f"{label} {row['purchase_date']} · {broker_label(row['broker'])} · "
            f"{_format_shares(row['shares'])} szt. · {row['total_invested']:.2f} {row['currency']}"
        )
    return (
        f"Sprzedaż {row['sale_date']} · {broker_label(row['broker'])} · "
        f"{_format_shares(row['shares'])} jedn. · {describe_sale_amounts(row)}"
    )


def _negative_holding_message(negative: dict, what: str) -> str:
    return (
        f"{what}: {negative['date']} na {broker_label(negative['broker'])} ({negative['currency']}) "
        f"sprzedaż {_format_shares(negative['sold'])} jedn., a w tym dniu posiadane były tylko "
        f"{_format_shares(negative['held'])}. Zapis zablokowany — dane nie zostały zmienione. "
        "Sprawdź datę, liczbę jednostek, platformę i walutę."
    )


_AMOUNT_MODES = {
    "BUY": {True: "Kwota zawiera opłaty", False: "Kwota bez opłat (+ opłaty)"},
    "SELL": {True: "Kwota otrzymana (netto)", False: "Kwota sprzedaży przed opłatami (brutto)"},
}


def _render_amount_fields(key: str, *, side: str, amount: float = 0.0, fees: float = 0.0,
                          fees_unknown: bool = False, includes: bool = True) -> tuple[bool, float, float, bool]:
    """Kwota i opłaty transakcji (wewnątrz st.form) -- dwa sposoby
    wpisania: kwota łączna z opłatami albo kwota bez opłat + opłaty.
    Opłat nigdy nie doliczamy drugi raz (patrz `resolve_purchase_amounts`).
    Sprzedaż: łączna kwota za wszystkie jednostki, bez ceny jednostkowej --
    cenę wylicza `resolve_sale_amounts`."""
    sell = side == "SELL"
    includes = st.radio(
        "Sposób wpisania kwoty", (True, False), index=0 if includes else 1, format_func=_AMOUNT_MODES[side].get,
        horizontal=True, key=f"{key}_amode",
        help=("Netto: tyle wpłynęło na konto, opłaty już potrącone. "
              "Brutto: kwota sprzedaży przed opłatami — opłaty wpisz osobno, aplikacja je odejmie.") if sell else None,
    )
    amount = st.number_input(
        "Kwota łączna za wszystkie sprzedane jednostki" if sell else "Kwota zakupu (łącznie)",
        min_value=0.0, value=float(amount or 0.0), step=0.01, format="%.2f", key=f"{key}_amount",
    )
    fees = st.number_input(
        "Opłaty / prowizja (opcjonalnie)" if sell else "Opłaty / prowizja", min_value=0.0, value=float(fees or 0.0),
        step=0.01, format="%.2f", key=f"{key}_afees",
        help=("Przy kwocie netto — tylko informacyjnie, nie odejmowane drugi raz. "
              "Przy kwocie brutto — odejmowane od kwoty.") if sell else None,
    )
    fees_unknown = st.checkbox(
        "Nie znam wysokości opłat — kwota otrzymana już je uwzględnia" if sell
        else "Nie znam wysokości opłat — są zawarte w kwocie (nierozdzielone)",
        value=bool(fees_unknown), key=f"{key}_aunknown",
    )
    if sell:
        st.caption("Cena za jednostkę nie jest potrzebna — aplikacja wyliczy ją z kwoty i liczby jednostek.")
    return includes, amount, fees, fees_unknown


def _render_bonus_fields(key: str, *, received_value: float = 0.0) -> float | None:
    """BONUS (wewnątrz st.form): jednostki bez wydatku -- koszt nabycia 0.
    Wartość z dnia otrzymania jest zapisywana OSOBNO, tylko informacyjnie:
    nie jest kosztem i aplikacja nie zakłada, że to wartość podatkowa."""
    st.caption("Bonus: jednostki otrzymane bez wydatku (np. prezent, akcje za darmo) — koszt nabycia 0.")
    value = st.number_input(
        "Wartość w dniu otrzymania (opcjonalnie, informacyjnie — nie jest kosztem)", min_value=0.0,
        value=float(received_value or 0.0), step=0.01, format="%.2f", key=f"{key}_received",
        help="W walucie transakcji. Zapisywana osobno od kosztu; nie wpływa na koszt, wynik ani wycenę.",
    )
    return value or None


def _resolve_buy(fields: tuple[bool, float, float, bool]) -> tuple[float, float | None, str]:
    includes, amount, fees, unknown = fields
    total, fees, status = resolve_purchase_amounts(amount, fees, amount_includes_fees=includes, fees_unknown=unknown)
    if total <= 0:
        raise AmountError("Kwota zakupu musi być większa od zera (bezpłatne jednostki to „Bonus”).")
    return total, fees, status


def _resolve_sell(shares: float, fields: tuple[bool, float, float, bool]) -> tuple[float, float | None, str]:
    includes, amount, fees, unknown = fields
    if amount <= 0:
        raise AmountError("Kwota sprzedaży musi być większa od zera.")
    return resolve_sale_amounts(shares, amount, fees, amount_is_net=includes, fees_unknown=unknown)


def _fees_text(kind: str, row) -> str:
    status = row.get("fee_status") if hasattr(row, "get") else None
    if status == FEES_UNSPLIT:
        return "w kwocie (nieznane)"
    if row["fees"]:
        return f"{row['fees']:.2f}"
    return "0.00" if status == FEES_KNOWN else "—"


def _render_transaction_editor(portfolio_conn, position: dict) -> None:
    """Historia transakcji pozycji i edycja jednego wpisu, w tym zmiana
    typu (zakup <-> sprzedaż, -> bonus). Zapis = nowy wpis właściwego typu
    + anulowanie starego z powodem (istniejący mechanizm, sekcja 11 design
    review: nic nie jest kasowane ani nadpisywane). Przed zapisem cała oś
    czasu jest sprawdzana -- stan jednostek nigdy nie może spaść poniżej zera."""
    position_id = position["position_id"]
    purchases = [dict(r) for r in get_purchase_transactions(portfolio_conn, position_id)]
    sales = [dict(r) for r in get_sale_transactions(portfolio_conn, position_id)]
    entries = sorted(
        [("PURCHASE", r) for r in purchases] + [("SALE", r) for r in sales],
        key=lambda e: (e[1]["sale_date"] if e[0] == "SALE" else e[1]["purchase_date"], e[0] == "SALE"),
    )
    if not entries:
        st.info("Brak aktywnych transakcji.")
        return
    history = []
    for kind, row in entries:
        tx_type = transaction_type(kind, row)
        history.append({
            "Data": row["sale_date"] if kind == "SALE" else row["purchase_date"],
            "Typ": _TRANSACTION_TYPE_LABELS[tx_type].split(" (")[0],
            "Platforma": broker_label(row["broker"]),
            "Ilość": _format_shares(row["shares"]),
            "Kwota": (
                f"{sale_amounts(row)[1]:.2f} {row['currency']}" if kind == "SALE"
                else f"0.00 {row['currency']} (koszt)"
                + (f" · wartość w dniu otrzymania {row['received_value']:.2f}" if row.get("received_value") else "")
                if tx_type == "BONUS" else f"{row['total_invested']:.2f} {row['currency']}"
            ),
            "Opłaty": _fees_text(kind, row),
        })
    st.dataframe(history, hide_index=True, use_container_width=True)
    st.caption(
        "Kwota: zakup — łączny koszt z opłatami; sprzedaż — wpływ po opłatach; bonus — koszt 0 "
        "(wartość w dniu otrzymania tylko informacyjnie, nie jest kosztem). "
        "„w kwocie (nieznane)” = opłaty zawarte w kwocie, wysokość nierozdzielona. "
        "Sposób rozliczenia opłat zmienisz poniżej: wybierz transakcję, ten sam typ, popraw kwotę/opłaty i zapisz."
    )

    st.markdown("###### Edytuj transakcję")
    index = st.selectbox(
        "Transakcja", range(len(entries)), format_func=lambda i: _describe_transaction(*entries[i]),
        key=f"edit_tx_{position_id}",
    )
    kind, row = entries[index]
    current_type = transaction_type(kind, row)
    new_type = st.radio(
        "Typ po zmianie", _TRANSACTION_TYPES, index=_TRANSACTION_TYPES.index(current_type),
        format_func=_TRANSACTION_TYPE_LABELS.get, horizontal=True, key=f"edit_type_{position_id}_{kind}_{row['transaction_id']}",
    )
    defaults = retype_defaults(kind, row, new_type)
    if new_type != current_type:
        st.caption(
            f"Zmiana: {_TRANSACTION_TYPE_LABELS[current_type]} → {_TRANSACTION_TYPE_LABELS[new_type]}. "
            "Pola wypełniono danymi z obecnego wpisu — sprawdź je z potwierdzeniem transakcji."
            + (" Wpisz łączną kwotę otrzymaną ze sprzedaży — w polu kwoty wstawiono kwotę dotychczasowego "
               "zakupu, popraw ją. Cenę za jednostkę aplikacja wyliczy sama."
               if new_type == "SELL" and kind == "PURCHASE" else "")
        )
    key = f"edit_{kind}_{row['transaction_id']}_{new_type}"
    with st.form(f"{key}_form"):
        broker = st.selectbox(
            "Platforma", _BROKER_OPTIONS, format_func=broker_label, key=f"{key}_broker",
            index=_BROKER_OPTIONS.index(defaults["broker"]) if defaults["broker"] in _BROKER_OPTIONS else 0,
        )
        tx_date = st.date_input("Data transakcji", value=dt.date.fromisoformat(str(defaults["date"])[:10]),
                                key=f"{key}_date")
        shares = st.number_input("Liczba jednostek", min_value=0.0, value=defaults["shares"], step=0.00000001,
                                 format="%.8f", key=f"{key}_shares")
        currency = st.text_input("Waluta", value=defaults["currency"], key=f"{key}_ccy")
        amount_fields, received_value = None, None
        if new_type in ("BUY", "SELL"):
            amount_fields = _render_amount_fields(
                key, side=new_type, amount=defaults["amount"], fees=defaults["fees"],
                fees_unknown=defaults["fees_unknown"],
            )
        else:
            received_value = _render_bonus_fields(key, received_value=defaults["received_value"])
            if current_type == "BUY":
                st.caption(f"Dotychczasowa kwota zakupu: {defaults['total_invested']:.2f} {defaults['currency']} — "
                           "nie jest przenoszona automatycznie; jeśli to wartość prezentu, wpisz ją powyżej.")
        fx_rate = st.number_input(
            "Kurs brokera (opcjonalnie, waluta inna niż PLN): ile PLN za 1 jednostkę waluty", min_value=0.0,
            value=float(defaults["fx_rate_actual"]), step=0.0001, format="%.4f", key=f"{key}_fx",
        )
        note = st.text_input("Notatka", value=defaults["note"], key=f"{key}_note")
        if st.form_submit_button("Zapisz zmianę"):
            currency = currency.strip()
            errors = []
            if shares <= 0:
                errors.append("Liczba jednostek musi być większa od zera.")
            if not currency:
                errors.append("Waluta jest wymagana.")
            total_invested = sale_price = 0.0
            fees, fee_status = None, None
            if amount_fields is not None and not errors:
                try:
                    if new_type == "BUY":
                        total_invested, fees, fee_status = _resolve_buy(amount_fields)
                    else:
                        sale_price, fees, fee_status = _resolve_sell(shares, amount_fields)
                except AmountError as exc:
                    errors.append(str(exc))
            new_row = {
                "transaction_id": None, "broker": broker, "currency": currency, "shares": shares,
                "purchase_date": str(tx_date), "sale_date": str(tx_date),
                "acquisition_type": new_type if new_type != "SELL" else None,
                "total_invested": total_invested, "sale_price": sale_price, "fees": fees, "fee_status": fee_status,
                "received_value": received_value,
            }
            if not errors:
                negative = find_negative_holding(*replace_transaction(
                    purchases, sales, kind=kind, transaction_id=row["transaction_id"], new_type=new_type,
                    new_row=new_row,
                ))
                if negative:
                    errors.append(_negative_holding_message(negative, "Po tej zmianie"))
            for error in errors:
                st.error(error)
            if not errors:
                try:
                    apply_transaction_change(
                        portfolio_conn, position_id, kind=kind, old_id=row["transaction_id"],
                        current_type=current_type, new_type=new_type, new_row=new_row, fx_rate=fx_rate,
                        note=note.strip(),
                    )
                except TransactionChangeError as exc:
                    st.error(f"Zapis zablokowany — dane nie zostały zmienione. {exc}")
                else:
                    saved = _TRANSACTION_TYPE_LABELS[new_type]
                    if new_type == "SELL":
                        saved += " — " + describe_sale_amounts(
                            {"shares": shares, "sale_price": sale_price, "fees": fees, "currency": currency})
                    st.toast(f"Zapisano: {saved}.")
                    st.rerun()


def _render_transaction_voiding(portfolio_conn, position: dict) -> None:
    """Faza 9 -- anulowanie błędnego wpisu bez kasowania: wiersz zostaje
    w bazie z `voided_at` (audit trail, sekcja 11 design review) i
    przestaje wchodzić do obliczeń. Poprawny wpis dodaje się potem
    zwykłym formularzem "+ Dodaj transakcję"."""
    position_id = position["position_id"]
    st.markdown("##### Transakcje")
    purchases = list(get_purchase_transactions(portfolio_conn, position_id))
    sales = list(get_sale_transactions(portfolio_conn, position_id))
    entries = [("PURCHASE", r) for r in purchases] + [("SALE", r) for r in sales]

    if not entries:
        st.info("Ta pozycja nie ma żadnych aktywnych transakcji.")
        with st.form(f"void_position_form_{position_id}"):
            sure = st.checkbox("Tak, usuń tę pozycję z portfela (wpis zostanie w historii bazy)")
            if st.form_submit_button("Usuń pozycję"):
                if not sure:
                    st.error("Zaznacz potwierdzenie, aby usunąć pozycję.")
                else:
                    void_position(portfolio_conn, position_id)
                    portfolio_conn.commit()
                    st.toast(f"Usunięto pozycję {position['ticker']}.")
                    st.rerun()
        return

    foreign = [(k, r) for k, r in entries if str(r["currency"]).strip().upper() != "PLN"]
    if foreign:
        with st.form(f"fx_rate_form_{position_id}"):
            st.markdown("##### Kurs brokera dla transakcji w walucie obcej")
            st.caption(
                "Bez wpisanego kursu koszt w PLN liczony jest kursem średnim NBP z dnia roboczego przed transakcją "
                "(orientacyjnie). Kwota, data i waluta transakcji pozostają bez zmian."
            )
            fx_index = st.selectbox(
                "Transakcja", range(len(foreign)),
                format_func=lambda i: _describe_transaction(*foreign[i]) + (
                    f" · kurs brokera {foreign[i][1]['fx_rate_actual']}" if foreign[i][1]["fx_rate_actual"] else ""
                ),
            )
            new_rate = st.number_input("Ile PLN za 1 jednostkę waluty", min_value=0.0, step=0.0001, format="%.4f")
            if st.form_submit_button("Zapisz kurs brokera"):
                if new_rate <= 0:
                    st.error("Kurs musi być większy od zera.")
                else:
                    kind, row = foreign[fx_index]
                    set_transaction_fx_rate(
                        portfolio_conn, kind=kind, transaction_id=row["transaction_id"], fx_rate_actual=new_rate,
                    )
                    portfolio_conn.commit()
                    st.toast("Zapisano kurs brokera.")
                    st.rerun()

    st.caption(
        "Błędny wpis anuluj tutaj, a poprawny dodaj w zakładce „+ Dodaj transakcję”. "
        "Anulowany wpis nie jest kasowany — zostaje w bazie jako historia, ale nie wchodzi do obliczeń."
    )
    with st.form(f"void_tx_form_{position_id}"):
        index = st.selectbox(
            "Transakcja do anulowania", range(len(entries)),
            format_func=lambda i: _describe_transaction(*entries[i]),
        )
        reason = st.text_input("Powód (opcjonalnie)", placeholder="np. zły ticker, zła kwota")
        sure = st.checkbox("Tak, anuluj tę transakcję")
        if st.form_submit_button("Anuluj transakcję"):
            kind, row = entries[index]
            remaining_purchases = [r for r in purchases if not (kind == "PURCHASE" and r is row)]
            remaining_sales = [r for r in sales if not (kind == "SALE" and r is row)]
            negative = find_negative_holding(remaining_purchases, remaining_sales)
            if not sure:
                st.error("Zaznacz potwierdzenie, aby anulować transakcję.")
            elif negative:
                st.error(_negative_holding_message(negative, "Po anulowaniu tego zakupu"))
            else:
                void_fn = void_purchase_transaction if kind == "PURCHASE" else void_sale_transaction
                void_fn(portfolio_conn, row["transaction_id"], reason.strip() or None)
                portfolio_conn.commit()
                st.toast("Transakcja anulowana.")
                st.rerun()


@dataclass(frozen=True)
class _InstrumentChoice:
    """Stan weryfikacji instrumentu w chwili zapisu formularza (Faza 9)."""

    symbol: str
    looked_up: bool  # sprawdzenie w FMP wykonane dla DOKŁADNIE tego symbolu
    result: InstrumentLookupResult | None  # None == FMP nie rozpoznał
    confirmed: bool

    @property
    def confirmed_result(self) -> InstrumentLookupResult | None:
        return self.result if self.confirmed else None

    def save_errors(self) -> list[str]:
        return instrument_save_errors(
            self.symbol, looked_up=self.looked_up, result=self.result, confirmed=self.confirmed,
        )


def _render_instrument_lookup_widget(key_prefix: str, market: MarketData) -> _InstrumentChoice:
    """Sekcja 9/19 specyfikacji: "Nie zgaduj symbolu ani giełdy. Formularz
    ma pozwolić użytkownikowi potwierdzić instrument." Lookup jest POZA
    `st.form` -- musi pokazać wynik PRZED zapisem, więc potrzebuje
    własnego przycisku. Faza 9: wołający blokuje zapis przez
    `_InstrumentChoice.save_errors()` (rozpoznany, ale niepotwierdzony
    symbol albo brak sprawdzenia); zapis ręczny bez weryfikacji tylko,
    gdy FMP symbolu nie rozpoznał (Decyzja właścicielki, Faza 7 pkt 6)."""
    symbol = st.text_input(
        "Symbol/ticker (np. AAPL, SU.PA, GSK.L)", key=f"{key_prefix}_symbol"
    ).strip()
    st.caption(
        "Giełdy europejskie podawaj z sufiksem: SU.PA (Paryż), GSK.L (Londyn), EUNL.DE (Xetra) — "
        "sprawdzane w EODHD; pozostałe (USA) w FMP."
    )
    if st.button("Sprawdź instrument", key=f"{key_prefix}_lookup_btn") and symbol:
        st.session_state[f"{key_prefix}_lookup_symbol"] = symbol
        st.session_state[f"{key_prefix}_lookup_result"] = lookup_instrument_routed(symbol, market)
        st.session_state[f"{key_prefix}_confirm"] = False

    looked_up_symbol = st.session_state.get(f"{key_prefix}_lookup_symbol")
    result = st.session_state.get(f"{key_prefix}_lookup_result")

    if looked_up_symbol != symbol:
        if looked_up_symbol is not None:
            st.caption("Symbol zmienił się od ostatniego sprawdzenia — sprawdź ponownie przed zapisem.")
        return _InstrumentChoice(symbol=symbol, looked_up=False, result=None, confirmed=False)

    if result is None:
        st.warning(
            "Dostawca danych nie rozpoznał tego symbolu (albo brak klucza API / wyczerpany dzienny limit). "
            "Możesz zapisać pozycję ręcznie, bez automatycznej ceny bieżącej — nigdy nie "
            "zgadujemy symbolu ani giełdy za Ciebie."
        )
        return _InstrumentChoice(symbol=symbol, looked_up=True, result=None, confirmed=False)

    st.success(
        f"{result.provider} rozpoznał: **{result.company_name or '—'}** "
        f"({result.exchange or '—'}, {result.currency or '—'}, ISIN {result.isin or '—'})."
    )
    confirmed = st.checkbox("Tak, to właściwy instrument", key=f"{key_prefix}_confirm")
    if not confirmed:
        st.caption(
            "Jeśli to nie ta spółka, zmień symbol — np. dodaj sufiks giełdy (SU.PA = Paryż, GSK.L = Londyn)."
        )
    return _InstrumentChoice(symbol=symbol, looked_up=True, result=result, confirmed=confirmed)


def _render_quote_currency_hint(choice: _InstrumentChoice) -> None:
    """Faza 9: waluta transakcji NIE jest już podpowiadana z FMP -- FMP
    zwraca walutę NOTOWANIA (np. GBp dla Londynu), a właścicielka wpisuje
    walutę, w której faktycznie zapłaciła (PLN w Trade Republic)."""
    result = choice.confirmed_result
    if result is None or not result.currency:
        return
    currency = result.currency.strip()
    pence = " (pensy brytyjskie — aplikacja sama przeliczy na funty)" if currency in {"GBp", "GBX"} else ""
    st.caption(
        f"Waluta notowania na giełdzie: {currency}{pence}. W polu „Waluta transakcji” wpisz walutę, "
        "w której faktycznie zapłaciłaś/eś (np. PLN)."
    )


def _render_acquisition_type_picker(key: str) -> str:
    """Faza 9: wybór Zakup/Bonus jako widoczne przyciski POZA `st.form`
    -- wewnątrz formularza Streamlit nie odświeża pól przed zapisem, więc
    pole kapitału nie wyszarzało się po wyborze "Bonus" (realny problem
    właścicielki przy dodawaniu Apple BONUS)."""
    return st.radio(
        "Sposób nabycia", _ACQUISITION_TYPE_OPTIONS,
        format_func=lambda t: acquisition_types_label((t,)), key=key, horizontal=True,
    )


def _default_asset_class(result: InstrumentLookupResult | None) -> str:
    if result is not None and (result.asset_type or "").upper() in {"ETF", "FUND"}:
        return "ETF"
    return "STOCK"


def _render_asset_class_picker(key: str, default: str) -> str:
    options = list(_ASSET_CLASS_LABELS)
    return st.radio(
        "Klasa aktywa", options, index=options.index(default) if default in options else 0,
        format_func=lambda c: _ASSET_CLASS_LABELS[c], key=key, horizontal=True,
    )


def _instrument_identity_fields(result: InstrumentLookupResult | None, asset_class: str) -> dict:
    """Pola tożsamości zapisywane przy pozycji (Faza 11, P0b). Bez
    potwierdzenia -- brak źródła ceny (pozycja ręczna)."""
    if result is None:
        return {"isin": None, "quote_currency": None, "price_provider": None, "price_symbol": None,
                "asset_class": asset_class}
    return {"isin": result.isin, "quote_currency": result.currency, "price_provider": result.provider,
            "price_symbol": result.provider_symbol, "asset_class": asset_class}


def _render_new_position_form(portfolio_conn, user: dict) -> None:
    st.markdown("##### Nowa pozycja")
    choice = _render_instrument_lookup_widget("new_pos", _market(portfolio_conn))
    confirmed_result = choice.confirmed_result
    _render_quote_currency_hint(choice)
    asset_class = _render_asset_class_picker("new_pos_asset_class", _default_asset_class(choice.result))
    fund_fields = _render_fund_fields("new_pos") if asset_class in (ETF, ETC, ETN) else {}
    acquisition_type = _render_acquisition_type_picker("new_pos_acq_type")

    with st.form("new_position_form", clear_on_submit=True):
        company_name = st.text_input(
            "Nazwa spółki", value=(confirmed_result.company_name if confirmed_result else "") or "",
        )
        exchange = st.text_input(
            "Giełda (opcjonalnie)", value=(confirmed_result.exchange if confirmed_result else "") or "",
        )
        broker = st.selectbox("Platforma", _BROKER_OPTIONS, format_func=broker_label, key="new_pos_broker")
        purchase_date = st.date_input("Data transakcji", key="new_pos_date")
        shares = st.number_input("Liczba (akcji / sztuk / jednostek)", min_value=0.0, step=0.00000001, format="%.8f", key="new_pos_shares")
        currency = st.text_input("Waluta transakcji (np. PLN, USD, EUR)", key="new_pos_currency")
        amount_fields, received_value = None, None
        if acquisition_type == "BUY":
            amount_fields = _render_amount_fields("new_pos", side="BUY")
        else:
            received_value = _render_bonus_fields("new_pos")
        fx_rate = st.number_input(
            "Kurs brokera (opcjonalnie, tylko waluta inna niż PLN): ile PLN za 1 jednostkę waluty",
            min_value=0.0, step=0.0001, format="%.4f", key="new_pos_fx",
        )
        note = st.text_input("Notatka (opcjonalnie)", key="new_pos_note")

        submitted = st.form_submit_button("Zapisz nową pozycję")
        if submitted:
            errors = choice.save_errors()
            if not company_name.strip():
                errors.append("Nazwa spółki jest wymagana.")
            if shares <= 0:
                errors.append("Liczba akcji musi być większa od zera.")
            if not currency.strip():
                errors.append("Waluta transakcji jest wymagana.")
            final_invested, fees, fee_status = 0.0, None, None
            if amount_fields is not None:
                try:
                    final_invested, fees, fee_status = _resolve_buy(amount_fields)
                except AmountError as exc:
                    errors.append(str(exc))
            for error in errors:
                st.error(error)
            if not errors:
                price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                ticker = (confirmed_result.symbol if confirmed_result else choice.symbol).strip()
                position_id = insert_position(
                    portfolio_conn, user_id=user["user_id"], ticker=ticker, company_name=company_name.strip(),
                    cik=(confirmed_result.cik if confirmed_result else None),
                    exchange=(exchange.strip() or None), instrument_currency=currency.strip(),
                    instrument_confirmed=confirmed_result is not None,
                )
                update_position_fields(
                    portfolio_conn, position_id, **_instrument_identity_fields(confirmed_result, asset_class),
                    **fund_fields,
                )
                transaction_id = insert_purchase_transaction(
                    portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                    purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                    currency=currency.strip(), price_per_share=price_per_share,
                    fees=fees, note=(note.strip() or None), fee_status=fee_status, received_value=received_value,
                )
                if fx_rate and currency.strip().upper() != "PLN":
                    set_transaction_fx_rate(
                        portfolio_conn, kind="PURCHASE", transaction_id=transaction_id, fx_rate_actual=fx_rate,
                    )
                portfolio_conn.commit()
                for key in ("new_pos_lookup_symbol", "new_pos_lookup_result", "new_pos_confirm"):
                    st.session_state.pop(key, None)
                st.toast(f"Zapisano nową pozycję: {ticker}.")
                st.rerun()


def _render_existing_position_transaction_form(portfolio_conn, position: dict) -> None:
    position_id = position["position_id"]
    st.markdown(f"##### {position['ticker']} — {position['company_name']}")
    new_type = st.radio(
        "Typ transakcji", _TRANSACTION_TYPES, format_func=_TRANSACTION_TYPE_LABELS.get,
        key=f"tx_type_{position_id}", horizontal=True,
    )

    if new_type in ("BUY", "BONUS"):
        acquisition_type = new_type
        with st.form(f"purchase_form_{position_id}", clear_on_submit=True):
            broker = st.selectbox("Platforma", _BROKER_OPTIONS, format_func=broker_label, key=f"ep_broker_{position_id}")
            purchase_date = st.date_input("Data transakcji", key=f"ep_date_{position_id}")
            shares = st.number_input(
                "Liczba (akcji / sztuk / jednostek)", min_value=0.0, step=0.00000001, format="%.8f", key=f"ep_shares_{position_id}",
            )
            currency = st.text_input(
                "Waluta transakcji", value=position["instrument_currency"] or "", key=f"ep_currency_{position_id}",
            )
            amount_fields, received_value = None, None
            if acquisition_type == "BUY":
                amount_fields = _render_amount_fields(f"ep_{position_id}", side="BUY")
            else:
                received_value = _render_bonus_fields(f"ep_{position_id}")
            fx_rate = st.number_input(
                "Kurs brokera (opcjonalnie, tylko waluta inna niż PLN): ile PLN za 1 jednostkę waluty",
                min_value=0.0, step=0.0001, format="%.4f", key=f"ep_fx_{position_id}",
            )
            note = st.text_input("Notatka (opcjonalnie)", key=f"ep_note_{position_id}")

            submitted = st.form_submit_button("Zapisz zakup/bonus")
            if submitted:
                errors = []
                if shares <= 0:
                    errors.append("Liczba akcji musi być większa od zera.")
                if not currency.strip():
                    errors.append("Waluta transakcji jest wymagana.")
                final_invested, fees, fee_status = 0.0, None, None
                if amount_fields is not None:
                    try:
                        final_invested, fees, fee_status = _resolve_buy(amount_fields)
                    except AmountError as exc:
                        errors.append(str(exc))
                for error in errors:
                    st.error(error)
                if not errors:
                    price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                    transaction_id = insert_purchase_transaction(
                        portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                        purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                        currency=currency.strip(), price_per_share=price_per_share,
                        fees=fees, note=(note.strip() or None), fee_status=fee_status, received_value=received_value,
                    )
                    if fx_rate and currency.strip().upper() != "PLN":
                        set_transaction_fx_rate(
                            portfolio_conn, kind="PURCHASE", transaction_id=transaction_id, fx_rate_actual=fx_rate,
                        )
                    portfolio_conn.commit()
                    st.toast("Zapisano zakup/bonus.")
                    st.rerun()
    else:
        with st.form(f"sale_form_{position_id}", clear_on_submit=True):
            broker = st.selectbox("Platforma", _BROKER_OPTIONS, format_func=broker_label, key=f"es_broker_{position_id}")
            sale_date = st.date_input("Data sprzedaży", key=f"es_date_{position_id}")
            shares = st.number_input(
                "Liczba sprzedanych jednostek", min_value=0.0, step=0.00000001, format="%.8f", key=f"es_shares_{position_id}",
            )
            currency = st.text_input(
                "Waluta transakcji", value=position["instrument_currency"] or "", key=f"es_currency_{position_id}",
            )
            amount_fields = _render_amount_fields(f"es_{position_id}", side="SELL")
            fx_rate = st.number_input(
                "Kurs brokera (opcjonalnie, tylko waluta inna niż PLN): ile PLN za 1 jednostkę waluty",
                min_value=0.0, step=0.0001, format="%.4f", key=f"es_fx_{position_id}",
            )
            note = st.text_input("Notatka (opcjonalnie)", key=f"es_note_{position_id}")

            submitted = st.form_submit_button("Zapisz sprzedaż")
            if submitted:
                errors = []
                if shares <= 0:
                    errors.append("Liczba sprzedanych jednostek musi być większa od zera.")
                if not currency.strip():
                    errors.append("Waluta transakcji jest wymagana.")
                sale_price, fees, fee_status = 0.0, None, None
                if not errors:
                    try:
                        sale_price, fees, fee_status = _resolve_sell(shares, amount_fields)
                    except AmountError as exc:
                        errors.append(str(exc))
                if not errors:
                    # Sekcja 7 specyfikacji: "Nie pozwalaj, aby sprzedaż na
                    # jednym brokerze tworzyła ujemną subpozycję tylko
                    # dlatego, że akcje istnieją na drugim brokerze." --
                    # realny bug znaleziony przy weryfikacji wizualnej (Faza
                    # 7 KROK 7): sprzedaż z brokera bez wystarczających akcji
                    # cicho tworzyła "-4 akcje" w tabeli. Sprawdzane TUTAJ
                    # (nie w ui/portfolio.py, które poprawnie liczy to, co
                    # dostanie) -- to warstwa walidacji formularza.
                    negative = find_negative_holding(
                        get_purchase_transactions(portfolio_conn, position_id),
                        [*get_sale_transactions(portfolio_conn, position_id),
                         {"sale_date": str(sale_date), "broker": broker, "currency": currency.strip(),
                          "shares": shares}],
                    )
                    if negative:
                        errors.append(_negative_holding_message(negative, "Ta sprzedaż"))
                for error in errors:
                    st.error(error)
                if not errors:
                    transaction_id = insert_sale_transaction(
                        portfolio_conn, position_id=position_id, broker=broker, sale_date=str(sale_date),
                        shares=shares, sale_price=sale_price, currency=currency.strip(),
                        fees=fees, note=(note.strip() or None), fee_status=fee_status,
                    )
                    if fx_rate and currency.strip().upper() != "PLN":
                        set_transaction_fx_rate(
                            portfolio_conn, kind="SALE", transaction_id=transaction_id, fx_rate_actual=fx_rate,
                        )
                    portfolio_conn.commit()
                    st.toast("Zapisano sprzedaż — " + describe_sale_amounts(
                        {"shares": shares, "sale_price": sale_price, "fees": fees, "currency": currency.strip()}) + ".")
                    st.rerun()


_ADD_MODES = ("Nowa transakcja", "Skopiuj istniejącą transakcję")
_COPY_TARGETS = ("Kolejny zakup tej samej pozycji", "Nowa pozycja z tymi samymi danymi produktu")


def _render_copy_transaction(portfolio_conn, user: dict, positions: list[dict]) -> None:
    """Kopia istniejącego zakupu (Decyzja właścicielki 2026-10-18):
    formularz wypełniony danymi źródłowej transakcji -- zmienia się tylko
    to, co inne (np. nazwa monety, cena). Oryginał pozostaje bez zmian.
    Dla metali fizycznych kopia może być nową pozycją (inna moneta/
    sztabka); dla akcji, ETF i kryptowalut -- kolejnym zakupem tej samej
    pozycji (nowy instrument wymaga sprawdzenia symbolu)."""
    sources = [
        (position, tx) for position in positions
        for tx in get_purchase_transactions(portfolio_conn, position["position_id"])
    ]
    if not sources:
        st.info("Nie ma jeszcze zakupów do skopiowania.")
        return
    index = st.selectbox(
        "Transakcja do skopiowania", range(len(sources)),
        format_func=lambda i: f"{sources[i][0]['company_name']} · " + _describe_transaction("PURCHASE", sources[i][1]),
        key="copy_source",
    )
    position, tx = sources[index]
    physical = asset_class_of(position) in PHYSICAL
    target = (
        st.radio("Zapisz kopię jako", _COPY_TARGETS, horizontal=True, key=f"copy_target_{tx['transaction_id']}")
        if physical else _COPY_TARGETS[0]
    )
    if not physical:
        st.caption("Kopia zostanie dopisana jako kolejny zakup tej samej pozycji. Inną spółkę dodaj jako nową transakcję.")
    key = f"copy_{tx['transaction_id']}_{_COPY_TARGETS.index(target)}"
    acquisition_type = st.radio(
        "Sposób nabycia", _ACQUISITION_TYPE_OPTIONS, index=_ACQUISITION_TYPE_OPTIONS.index(tx["acquisition_type"]),
        format_func=lambda t: acquisition_types_label((t,)), key=f"{key}_acq", horizontal=True,
    )
    with st.form(f"{key}_form"):
        product = {}
        if target == _COPY_TARGETS[1]:
            product["name"] = st.text_input("Nazwa produktu", value=position["company_name"], key=f"{key}_name")
            forms = list(PRODUCT_FORM_LABELS)
            product["product_form"] = st.selectbox(
                "Rodzaj", forms, index=forms.index(position.get("product_form") or "OTHER"),
                format_func=PRODUCT_FORM_LABELS.get, key=f"{key}_form",
            )
            cols = st.columns(2)
            product["unit_weight"] = cols[0].number_input(
                "Masa jednej sztuki", min_value=0.0, value=float(position.get("unit_weight") or 0.0), step=0.01,
                format="%.4f", key=f"{key}_w",
            )
            units = ("OZT", "G")
            product["weight_unit"] = cols[1].selectbox(
                "Jednostka", units, index=units.index(position.get("weight_unit") or "OZT"),
                format_func=lambda u: "uncja trojańska" if u == "OZT" else "gram", key=f"{key}_wu",
            )
            product["fineness"] = st.number_input(
                "Próba", min_value=0.0, value=float(position.get("fineness") or 0.0), step=0.0001, format="%.4f",
                key=f"{key}_fine",
            )
            product["is_collectible"] = 1 if st.checkbox(
                "Moneta kolekcjonerska", value=bool(position.get("is_collectible")), key=f"{key}_coll",
            ) else 0
            product["storage_location"] = st.text_input(
                "Miejsce przechowywania", value=position.get("storage_location") or "", key=f"{key}_storage",
            ).strip() or None
        broker = st.selectbox(
            "Platforma", _BROKER_OPTIONS, index=_BROKER_OPTIONS.index(tx["broker"]), format_func=broker_label,
            key=f"{key}_broker",
        )
        purchase_date = st.date_input("Data zakupu", value=dt.date.fromisoformat(str(tx["purchase_date"])[:10]),
                                      key=f"{key}_date")
        quantity = st.number_input(
            "Liczba (akcji / sztuk / jednostek)", min_value=0.0, value=float(tx["shares"]), step=0.00000001,
            format="%.8f", key=f"{key}_qty",
        )
        currency = st.text_input("Waluta", value=tx["currency"], key=f"{key}_ccy")
        amount_fields, received_value = None, None
        if acquisition_type == "BUY":
            amount_fields = _render_amount_fields(
                key, side="BUY", amount=tx["total_invested"] or 0.0, fees=tx["fees"] or 0.0,
                fees_unknown=fees_unknown_default(tx),
            )
        else:
            received_value = _render_bonus_fields(key, received_value=dict(tx).get("received_value") or 0.0)
        fx_rate = st.number_input(
            "Kurs brokera (opcjonalnie, waluta inna niż PLN)", min_value=0.0,
            value=float(tx["fx_rate_actual"] or 0.0), step=0.0001, format="%.4f", key=f"{key}_fx",
        )
        note = st.text_input("Notatka", value=tx["note"] or "", key=f"{key}_note")
        if st.form_submit_button("Zapisz kopię"):
            final_total, fees, fee_status = 0.0, None, None
            errors = []
            if quantity <= 0:
                errors.append("Ilość musi być większa od zera.")
            if not currency.strip():
                errors.append("Waluta jest wymagana.")
            if amount_fields is not None:
                try:
                    final_total, fees, fee_status = _resolve_buy(amount_fields)
                except AmountError as exc:
                    errors.append(str(exc))
            if product and not product["name"].strip():
                errors.append("Nazwa produktu jest wymagana.")
            if product and pure_grams_per_piece(product["unit_weight"], product["weight_unit"], product["fineness"]) is None:
                errors.append("Podaj masę sztuki i próbę (ułamek 0–1 albo promile 100–1000).")
            for error in errors:
                st.error(error)
            if errors:
                return
            if product:
                metal = "GOLD" if asset_class_of(position) == PHYSICAL_GOLD else "SILVER"
                name = product.pop("name").strip()
                _save_new_asset_position(
                    portfolio_conn, user, ticker=f"{'Złoto' if metal == 'GOLD' else 'Srebro'}: {name}"[:40], name=name,
                    fields={"asset_class": asset_class_of(position), "metal": metal,
                            "price_provider": position.get("price_provider"), **product},
                    broker=broker, purchase_date=purchase_date, quantity=quantity, currency=currency,
                    total=final_total, fees=fees, fx_rate=fx_rate, note=note, acquisition_type=acquisition_type,
                    fee_status=fee_status, received_value=received_value,
                )
            else:
                transaction_id = insert_purchase_transaction(
                    portfolio_conn, position_id=position["position_id"], broker=broker,
                    acquisition_type=acquisition_type, purchase_date=str(purchase_date), shares=quantity,
                    total_invested=final_total, currency=currency.strip(),
                    price_per_share=(final_total / quantity) if acquisition_type == "BUY" else None,
                    fees=fees, note=(note.strip() or None), fee_status=fee_status, received_value=received_value,
                )
                if fx_rate and currency.strip().upper() != "PLN":
                    set_transaction_fx_rate(
                        portfolio_conn, kind="PURCHASE", transaction_id=transaction_id, fx_rate_actual=fx_rate,
                    )
                portfolio_conn.commit()
            st.toast("Zapisano kopię transakcji.")
            st.rerun()


_NEW_ASSET_KINDS = (
    "Instrument giełdowy (akcja/ETF/ETC/ETN)", "Złoto fizyczne", "Srebro fizyczne", "Kryptowaluta",
    "Złoto/srebro na platformie (np. Revolut)",
)
_COMMODITY_LABELS = {"XAG": "XAG — srebro", "XAU": "XAU — złoto"}


def _render_fund_fields(key_prefix: str) -> dict:
    """ETF/ETC/ETN (P4): ekspozycja na metal, sposób zabezpieczenia,
    opłata roczna -- dane opisowe, nie zmieniają wyceny rynkowej."""
    cols = st.columns(3)
    metal = cols[0].selectbox(
        "Metal bazowy", ("", "GOLD", "SILVER"), format_func=lambda m: METAL_LABELS.get(m, "— brak —"),
        key=f"{key_prefix}_metal",
    )
    exposure = cols[1].selectbox(
        "Sposób ekspozycji", ("", *EXPOSURE_LABELS), format_func=lambda e: EXPOSURE_LABELS.get(e, "— nieznany —"),
        key=f"{key_prefix}_exposure",
    )
    fee = cols[2].number_input("Opłata roczna % (opcjonalnie)", min_value=0.0, step=0.01, format="%.2f",
                               key=f"{key_prefix}_fee")
    return {"metal": metal or None, "exposure_type": exposure or None, "annual_fee_pct": fee or None}


def _render_purchase_fields(key_prefix: str, *, default_broker_index: int = 0, quantity_label: str = "Liczba sztuk",
                            acquisition_type: str = "BUY"):
    """Wspólne pola zakupu/bonusu dla metali i kryptowalut (wewnątrz st.form)."""
    broker = st.selectbox(
        "Platforma / miejsce zakupu", _BROKER_OPTIONS, index=default_broker_index, format_func=broker_label,
        key=f"{key_prefix}_broker",
    )
    bonus = acquisition_type == "BONUS"
    purchase_date = st.date_input("Data otrzymania" if bonus else "Data zakupu", key=f"{key_prefix}_date")
    quantity = st.number_input(quantity_label, min_value=0.0, step=0.00000001, format="%.8f", key=f"{key_prefix}_qty")
    currency = st.text_input("Waluta (np. PLN, USD, EUR)", value="PLN", key=f"{key_prefix}_ccy")
    amount_fields, received_value = None, None
    if bonus:
        received_value = _render_bonus_fields(key_prefix)
    else:
        amount_fields = _render_amount_fields(key_prefix, side="BUY")
    fx_rate = st.number_input(
        "Kurs (opcjonalnie, waluta inna niż PLN): ile PLN za 1 jednostkę waluty", min_value=0.0, step=0.0001,
        format="%.4f", key=f"{key_prefix}_fx",
    )
    note = st.text_input("Notatka (opcjonalnie)", key=f"{key_prefix}_note")
    return broker, purchase_date, quantity, currency, amount_fields, received_value, fx_rate, note


def _new_asset_amounts(amount_fields) -> tuple[float, float | None, str | None, list[str]]:
    """(koszt, opłaty, fee_status, błędy) dla nowej pozycji metalu/krypto;
    BONUS (brak pól kwoty) -> koszt 0."""
    if amount_fields is None:
        return 0.0, None, None, []
    try:
        total, fees, fee_status = _resolve_buy(amount_fields)
    except AmountError as exc:
        return 0.0, None, None, [str(exc)]
    return total, fees, fee_status, []


def _save_new_asset_position(
    portfolio_conn, user: dict, *, ticker: str, name: str, fields: dict, broker: str, purchase_date, quantity: float,
    currency: str, total: float, fees: float | None, fx_rate: float, note: str, acquisition_type: str = "BUY",
    fee_status: str | None = None, received_value: float | None = None,
) -> None:
    position_id = insert_position(
        portfolio_conn, user_id=user["user_id"], ticker=ticker, company_name=name,
        instrument_currency=currency.strip(), instrument_confirmed=True,
    )
    update_position_fields(portfolio_conn, position_id, **fields)
    transaction_id = insert_purchase_transaction(
        portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
        purchase_date=str(purchase_date), shares=quantity, total_invested=total, currency=currency.strip(),
        price_per_share=(total / quantity) if acquisition_type == "BUY" else None,
        fees=fees, note=(note.strip() or None), fee_status=fee_status,
        received_value=received_value if acquisition_type == "BONUS" else None,
    )
    if fx_rate and currency.strip().upper() != "PLN":
        set_transaction_fx_rate(portfolio_conn, kind="PURCHASE", transaction_id=transaction_id, fx_rate_actual=fx_rate)
    portfolio_conn.commit()


def _purchase_errors(quantity: float, currency: str, total: float) -> list[str]:
    errors = []
    if quantity <= 0:
        errors.append("Ilość musi być większa od zera.")
    if not currency.strip():
        errors.append("Waluta jest wymagana.")
    if total <= 0:
        errors.append("Łączny koszt musi być większy od zera.")
    return errors


def _render_new_physical_metal_form(portfolio_conn, user: dict, asset_class: str) -> None:
    """Faza 11 (P4): moneta/sztabka. Wycena: czysty metal x cena spot
    (złoto NBP, srebro FMP -- kontrakt jako przybliżenie spot); moneta
    kolekcjonerska tylko wyceną ręczną. Cenę odkupu wpisuje się w karcie."""
    metal = "GOLD" if asset_class == PHYSICAL_GOLD else "SILVER"
    st.markdown(f"##### Nowa pozycja: {ASSET_CLASS_LABELS[asset_class].lower()}")
    acquisition_type = _render_acquisition_type_picker(f"{asset_class}_acq")
    with st.form(f"new_{asset_class}_{acquisition_type}_form", clear_on_submit=True):
        name = st.text_input("Nazwa produktu (np. Krugerrand 1 oz, sztabka 10 g)", key=f"{asset_class}_name")
        form = st.selectbox("Rodzaj", list(PRODUCT_FORM_LABELS), format_func=PRODUCT_FORM_LABELS.get,
                            key=f"{asset_class}_form")
        cols = st.columns(2)
        unit_weight = cols[0].number_input("Masa jednej sztuki", min_value=0.0, step=0.01, format="%.4f",
                                           key=f"{asset_class}_w")
        weight_unit = cols[1].selectbox(
            "Jednostka", ("OZT", "G"), format_func=lambda u: "uncja trojańska" if u == "OZT" else "gram",
            key=f"{asset_class}_wu",
        )
        fineness = st.number_input(
            "Próba (np. 0.9999 albo 999.9)", min_value=0.0, value=0.9999 if metal == "GOLD" else 0.999,
            step=0.0001, format="%.4f", key=f"{asset_class}_fine",
        )
        collectible = st.checkbox(
            "Moneta kolekcjonerska (wycena tylko ręczna, nie po cenie metalu)", key=f"{asset_class}_coll",
        )
        storage = st.text_input("Miejsce przechowywania (opcjonalnie)", key=f"{asset_class}_storage")
        broker, purchase_date, quantity, currency, amount_fields, received_value, fx_rate, note = _render_purchase_fields(
            asset_class, default_broker_index=_BROKER_OPTIONS.index("OTHER"), acquisition_type=acquisition_type,
        )
        if st.form_submit_button("Zapisz"):
            total, fees, fee_status, errors = _new_asset_amounts(amount_fields)
            errors += _purchase_errors(quantity, currency, total or 1.0)
            if not name.strip():
                errors.append("Nazwa produktu jest wymagana.")
            if pure_grams_per_piece(unit_weight, weight_unit, fineness) is None:
                errors.append("Podaj masę sztuki i próbę (ułamek 0–1 albo promile 100–1000).")
            for error in errors:
                st.error(error)
            if not errors:
                _save_new_asset_position(
                    portfolio_conn, user, ticker=f"{'Złoto' if metal == 'GOLD' else 'Srebro'}: {name.strip()}"[:40],
                    name=name.strip(),
                    fields={"asset_class": asset_class, "metal": metal, "product_form": form,
                            "unit_weight": unit_weight, "weight_unit": weight_unit, "fineness": fineness,
                            "is_collectible": 1 if collectible else 0, "storage_location": storage.strip() or None,
                            "price_provider": "NBP" if metal == "GOLD" else "FMP"},
                    broker=broker, purchase_date=purchase_date, quantity=quantity, currency=currency,
                    total=total, fees=fees, fx_rate=fx_rate, note=note, fee_status=fee_status,
                    acquisition_type=acquisition_type, received_value=received_value,
                )
                st.toast("Zapisano pozycję.")
                st.rerun()


def _render_new_commodity_form(portfolio_conn, user: dict) -> None:
    """Metal na platformie (np. Revolut), nieprzechowywany samodzielnie.
    Ilość w uncjach trojańskich (XAU/XAG), do 8 miejsc. Koszt nabycia =
    łączna kwota, która zeszła z konta (z opłatą); cena z platformy
    zapisywana w `price_per_share` (informacyjnie, jak na potwierdzeniu).
    Kolejny zakup tego samego metalu dopisuje się do istniejącej pozycji."""
    st.markdown("##### Złoto/srebro na platformie (np. Revolut)")
    st.caption("Metal kupiony w aplikacji platformy, nieprzechowywany przez Ciebie. Ilość w uncjach trojańskich (oz).")
    acquisition_type = _render_acquisition_type_picker("commodity_acq")
    bonus = acquisition_type == "BONUS"
    with st.form(f"new_commodity_{acquisition_type}_form", clear_on_submit=True):
        symbol = st.selectbox("Instrument", list(_COMMODITY_LABELS), format_func=_COMMODITY_LABELS.get,
                              key="commodity_symbol")
        broker = st.selectbox("Platforma", _BROKER_OPTIONS, index=_BROKER_OPTIONS.index("REVOLUT"),
                              format_func=broker_label, key="commodity_broker")
        purchase_date = st.date_input("Data otrzymania" if bonus else "Data transakcji", key="commodity_date")
        quantity = st.number_input("Ilość (oz, do 8 miejsc po przecinku)", min_value=0.0, step=0.00000001,
                                   format="%.8f", key="commodity_qty")
        price = fee = total = 0.0
        received_value = None
        if bonus:
            currency = st.text_input("Waluta", value="PLN", key="commodity_ccy")
            received_value = _render_bonus_fields("commodity")
        else:
            cols = st.columns(2)
            price = cols[0].number_input("Cena za 1 oz (z platformy)", min_value=0.0, step=0.01, format="%.4f",
                                         key="commodity_price")
            currency = cols[1].text_input("Waluta", value="PLN", key="commodity_ccy")
            fee = st.number_input("Opłata", min_value=0.0, step=0.01, format="%.2f", key="commodity_fee")
            total = st.number_input(
                "Łączny koszt (cała kwota, która zeszła z konta; puste = ilość × cena + opłata)",
                min_value=0.0, step=0.01, format="%.2f", key="commodity_total",
            )
        fx_rate = st.number_input(
            "Kurs (opcjonalnie, waluta inna niż PLN): ile PLN za 1 jednostkę waluty", min_value=0.0, step=0.0001,
            format="%.4f", key="commodity_fx",
        )
        sale_fee = st.number_input(
            "Opłata platformy przy sprzedaży % (opcjonalnie — do kwoty możliwej do uzyskania)",
            min_value=0.0, max_value=99.0, step=0.01, format="%.2f", key="commodity_sale_fee",
        )
        note = st.text_input("Notatka (opcjonalnie, np. „prezent”)", key="commodity_note")
        if st.form_submit_button("Zapisz"):
            final_total = 0.0 if bonus else (total if total > 0 else quantity * price + fee)
            errors = _purchase_errors(quantity, currency, 1.0 if bonus else final_total)
            if not bonus and price <= 0:
                errors.append("Cena za 1 oz musi być większa od zera.")
            if not bonus and not errors and total > 0:
                mismatch = commodity_cost_error(quantity, price, fee, total)
                if mismatch:
                    errors.append(mismatch)
            for error in errors:
                st.error(error)
            if not errors:
                _save_commodity_purchase(
                    portfolio_conn, user, symbol=symbol, broker=broker, purchase_date=purchase_date,
                    quantity=quantity, price=price, currency=currency.strip().upper(), fee=fee,
                    total=round(final_total, 2), fx_rate=fx_rate, sale_fee_pct=sale_fee or None, note=note,
                    acquisition_type=acquisition_type, received_value=received_value,
                )
                st.toast(f"Zapisano {'bonus' if bonus else 'zakup'} {symbol}.")
                st.rerun()


def _save_commodity_purchase(
    portfolio_conn, user: dict, *, symbol: str, broker: str, purchase_date, quantity: float, price: float,
    currency: str, fee: float, total: float, fx_rate: float, sale_fee_pct: float | None, note: str,
    acquisition_type: str = "BUY", received_value: float | None = None,
) -> None:
    metal = COMMODITY_SYMBOLS[symbol]
    bonus = acquisition_type == "BONUS"
    existing = [
        p for p in get_positions_for_user(portfolio_conn, user["user_id"])
        if asset_class_of(p) == COMMODITY and (dict(p).get("price_symbol") or p["ticker"]) == symbol
    ]
    if existing:
        position_id = existing[0]["position_id"]
    else:
        position_id = insert_position(
            portfolio_conn, user_id=user["user_id"], ticker=symbol,
            company_name=f"{'Złoto' if metal == 'GOLD' else 'Srebro'} ({symbol})",
            instrument_currency=currency, instrument_confirmed=True,
        )
        update_position_fields(
            portfolio_conn, position_id, asset_class=COMMODITY, metal=metal, price_symbol=symbol,
            price_provider="NBP" if metal == "GOLD" else "FMP", unit_weight=1.0, weight_unit="OZT",
        )
    if sale_fee_pct is not None:
        update_position_fields(portfolio_conn, position_id, sale_fee_pct=sale_fee_pct)
    transaction_id = insert_purchase_transaction(
        portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
        purchase_date=str(purchase_date), shares=quantity, total_invested=0.0 if bonus else total, currency=currency,
        price_per_share=None if bonus else price, fees=None if bonus else fee, note=(note.strip() or None),
        fee_status=None if bonus else FEES_KNOWN, received_value=received_value if bonus else None,
    )
    if fx_rate and currency != "PLN":
        set_transaction_fx_rate(portfolio_conn, kind="PURCHASE", transaction_id=transaction_id, fx_rate_actual=fx_rate)
    portfolio_conn.commit()


def _render_new_crypto_form(portfolio_conn, user: dict) -> None:
    """Faza 11 (P4): kryptowaluta identyfikowana parą notowania FMP (np.
    BTCUSD), nie samym symbolem -- wynik trzeba potwierdzić."""
    st.markdown("##### Nowa pozycja: kryptowaluta")
    market = _market(portfolio_conn)
    symbol = st.text_input("Para notowania (np. BTCUSD, ETHUSD)", key="crypto_symbol").strip().upper()
    if st.button("Sprawdź", key="crypto_lookup_btn") and symbol:
        cached = market.fmp_quote(symbol)
        st.session_state["crypto_lookup"] = (symbol, cached.value if cached is not None else None)
    looked_up = st.session_state.get("crypto_lookup")
    confirmed = False
    name = None
    if looked_up and looked_up[0] == symbol:
        quote = looked_up[1]
        if not quote or not quote.get("price"):
            st.warning("FMP nie zna tej pary — sprawdź zapis (np. BTCUSD).")
        else:
            name = quote.get("name") or symbol
            st.success(f"FMP: **{name}** — cena {quote['price']:,.2f} {symbol[-3:]}.")
            confirmed = st.checkbox("Tak, to właściwe aktywo", key="crypto_confirm")
    acquisition_type = _render_acquisition_type_picker("crypto_acq")
    with st.form(f"new_crypto_{acquisition_type}_form", clear_on_submit=True):
        storage = st.text_input("Gdzie przechowywane (giełda/portfel, opcjonalnie)", key="crypto_storage")
        broker, purchase_date, quantity, currency, amount_fields, received_value, fx_rate, note = _render_purchase_fields(
            "crypto", quantity_label="Ilość (do 8 miejsc po przecinku)", acquisition_type=acquisition_type,
        )
        if st.form_submit_button("Zapisz"):
            total, fees, fee_status, errors = _new_asset_amounts(amount_fields)
            errors += _purchase_errors(quantity, currency, total or 1.0)
            if not confirmed:
                errors.append("Najpierw sprawdź parę notowania i potwierdź aktywo.")
            for error in errors:
                st.error(error)
            if not errors:
                _save_new_asset_position(
                    portfolio_conn, user, ticker=symbol, name=name,
                    fields={"asset_class": CRYPTO, "price_provider": "FMP", "price_symbol": symbol,
                            "quote_currency": symbol[-3:], "storage_location": storage.strip() or None},
                    broker=broker, purchase_date=purchase_date, quantity=quantity, currency=currency,
                    total=total, fees=fees, fx_rate=fx_rate, note=note, fee_status=fee_status,
                    acquisition_type=acquisition_type, received_value=received_value,
                )
                st.session_state.pop("crypto_lookup", None)
                st.toast("Zapisano pozycję.")
                st.rerun()


@contextlib.contextmanager
def _fragment_portfolio_conn(full_run_conn):
    """Połączenie dla fragmentu. W pełnym przebiegu -- to samo co reszta
    strony (bez dodatkowego łączenia). Gdy odświeża się SAM fragment --
    nowe połączenie: to z pełnego przebiegu mogło już wygasnąć
    (Supabase) albo należy do innego wątku (SQLite). Gdyby Streamlit
    zmienił wewnętrzne API, wybierana jest bezpieczna opcja (nowe)."""
    ctx = get_script_run_ctx()
    fragment_ids = getattr(ctx, "fragment_ids_this_run", _MISSING) if ctx is not None else _MISSING
    if fragment_ids is not _MISSING and not fragment_ids:
        yield full_run_conn
        return
    conn = _open_portfolio_conn()
    try:
        yield conn
    finally:
        conn.close()


@st.fragment
def _add_transaction_fragment(full_run_conn, user: dict) -> None:
    """Wybory w "+ Dodaj transakcję" (tryb, pozycja, rodzaj aktywa, wzór
    do skopiowania) odświeżają TYLKO ten fragment, nie całą aplikację
    (portfel + 20 kart spółek). Zapis woła `st.rerun()` = pełne
    odświeżenie, więc portfel od razu pokazuje nową transakcję."""
    with _fragment_portfolio_conn(full_run_conn) as conn:
        _render_add_transaction_tab(conn, user)


def _render_add_transaction_tab(portfolio_conn, user: dict) -> None:
    """Sekcja 11 specyfikacji -- formularz "Dodaj transakcję". Jedna
    `position_id` może mieć transakcje na wielu brokerach (sekcja 7) --
    wybór "istniejąca pozycja" NIGDY nie tworzy drugiej, równoległej
    pozycji dla tego samego instrumentu."""
    positions = [dict(p) for p in get_positions_for_user(portfolio_conn, user["user_id"])]

    mode = st.radio("Co chcesz zrobić?", _ADD_MODES, horizontal=True, key="add_tx_mode")
    if mode == _ADD_MODES[1]:
        _render_copy_transaction(portfolio_conn, user, positions)
        return

    options = ["+ Nowa pozycja"] + [f"{p['ticker']} — {p['company_name']}" for p in positions]
    choice = st.selectbox("Pozycja", options, key="add_tx_position_choice")

    if choice == "+ Nowa pozycja":
        st.caption("Sprzedaż albo bonus do posiadanej pozycji: wybierz tę pozycję w polu „Pozycja” powyżej.")
        kind = st.radio("Rodzaj aktywa", _NEW_ASSET_KINDS, horizontal=True, key="new_asset_kind")
        if kind == _NEW_ASSET_KINDS[0]:
            _render_new_position_form(portfolio_conn, user)
        elif kind == _NEW_ASSET_KINDS[3]:
            _render_new_crypto_form(portfolio_conn, user)
        elif kind == _NEW_ASSET_KINDS[4]:
            _render_new_commodity_form(portfolio_conn, user)
        else:
            _render_new_physical_metal_form(
                portfolio_conn, user, PHYSICAL_GOLD if kind == _NEW_ASSET_KINDS[1] else PHYSICAL_SILVER,
            )
    else:
        _render_existing_position_transaction_form(portfolio_conn, positions[options.index(choice) - 1])


def _render_platform_filter(portfolio_conn, user: dict) -> str:
    """Filtr platformy w PORTFELU (Decyzja właścicielki). Działa na
    poziomie TRANSAKCJI (filtruje purchase/sale rows PRZED przekazaniem
    do `compute_position_summary` -- `ui/queries.get_user_positions_
    with_summaries(..., broker=...)`), nigdy nie miesza brokerów,
    użytkowników ani walut, nie wymaga FX. Trade Republic/Revolut
    zawsze widoczne; pozostałe platformy (Cashify, Gold Saver, Mennica
    Skarbowa, Inny) tylko gdy użytkownik ma na nich choć jedną realną
    transakcję (`get_brokers_in_use_for_user`)."""
    brokers_in_use = get_brokers_in_use_for_user(portfolio_conn, user["user_id"])
    codes = list(_PLATFORM_FILTER_ALWAYS_AVAILABLE)
    codes += [c for c in _BROKER_OPTIONS if c in brokers_in_use and c not in codes]
    labels = {"ALL": "Wszystkie", **{c: broker_label(c) for c in codes if c != "ALL"}}
    selected = st.selectbox(
        "Platforma", codes, format_func=lambda c: labels[c], key="platform_filter",
    )
    return selected


def _render_portfolio_tab(portfolio_conn, scanner_conn, user: dict) -> None:
    """PORTFEL (przebudowa 2026-10-19, wygoda na iPhonie): filtr platformy
    i krótki przełącznik widoku zamiast rzędu zakładek ze wszystkimi
    instrumentami. Domyślnie „Kategorie” (kategoria -> dashboard ->
    instrument -> karta); „Wszystkie pozycje” = pełna tabela na żądanie;
    „Wg platform” = podział na brokerów. Podsumowanie całego portfela jest
    TYLKO w pasku nad zakładkami (bez powielania). Renderowany jest wyłącznie
    wybrany widok i wybrany instrument. Filtr platformy zawęża widoki;
    "+ Dodaj transakcję" celowo NIE jest filtrowana (można dodać transakcję
    na innej platformie niż aktualnie przeglądana)."""
    platform_filter = _render_platform_filter(portfolio_conn, user)
    broker = None if platform_filter == "ALL" else platform_filter
    market = _market(portfolio_conn)
    fx = market.nbp_table_a()
    positions_with_summaries = get_user_positions_with_summaries(
        portfolio_conn, scanner_conn, user["user_id"], broker=broker, quote_fn=market.quote_for_position, fx=fx,
        pln_rate_fn=market.pln_rate,
    )

    section = st.segmented_control(
        "Widok portfela", _PORTFOLIO_SECTIONS, default=_PORTFOLIO_SECTIONS[0], key="portfolio_section",
    ) or _PORTFOLIO_SECTIONS[0]
    if section == "+ Dodaj transakcję":
        _add_transaction_fragment(portfolio_conn, user)
    elif not positions_with_summaries:
        st.info(
            "Brak pozycji. Dodaj pierwszą transakcję w „+ Dodaj transakcję”." if platform_filter == "ALL"
            else f"Brak pozycji na platformie {broker_label(platform_filter)}."
        )
    elif section == "Wszystkie pozycje":
        _render_portfolio_summary_tab(
            portfolio_conn, positions_with_summaries, platform_filter=platform_filter, fx=fx,
        )
    elif section == "Wg platform":
        _render_platform_breakdown(positions_with_summaries)
    else:
        _render_categories(portfolio_conn, positions_with_summaries)

    _render_backup_section(portfolio_conn)


def _render_backup_section(portfolio_conn) -> None:
    """Faza 11: kopia zapasowa. Automatyczna, zweryfikowana kopia powstaje
    w bazie przed każdą migracją (`pg_store.init_schema`); tutaj można
    dodatkowo pobrać pełną kopię danych portfela na telefon/komputer."""
    with st.expander("Kopia zapasowa danych portfela"):
        info = get_latest_backup_info(portfolio_conn)
        if info is not None:
            counts = json.loads(info["row_counts"])
            st.write(
                f"Ostatnia automatyczna kopia w bazie: {info['created_at']} UTC — {info['reason']}. "
                f"Wiersze: " + ", ".join(f"{table} {count}" for table, count in counts.items())
            )
        else:
            st.caption("Brak automatycznej kopii w bazie (tryb lokalny albo nie było jeszcze migracji).")
        if st.button("Przygotuj plik kopii", key="prepare_backup"):
            payload, counts = backup_payload(portfolio_conn)
            st.session_state["backup_file"] = json.dumps(
                {"row_counts": counts, "tables": payload}, ensure_ascii=False, default=str, indent=1,
            )
        if "backup_file" in st.session_state:
            st.download_button(
                "Pobierz kopię (JSON)", st.session_state["backup_file"],
                file_name=f"portfel-kopia-{dt.date.today().isoformat()}.json", mime="application/json",
            )


def _open_portfolio_conn():
    """Połączenie z bazą portfela; przy błędzie czytelny komunikat i
    `st.stop()` (Decyzja właścicielki pkt 3), nigdy traceback."""
    if not portfolio_backend.is_hosted():
        # `init_db` (nie `connect`) -- `CREATE TABLE IF NOT EXISTS` +
        # migracje kolumn idempotentne, ten sam wzorzec co KAŻDE
        # wywołanie w cli.py. Realny błąd znaleziony przy weryfikacji
        # "czy aplikacja startuje bez błędów" (Faza 7): plain `connect()`
        # na zupełnie świeżym pliku DB wywalał `OperationalError: no
        # such table: users` -- `init_db` naprawia to bez ryzyka dla
        # istniejących danych.
        return init_db(DB_PATH)

    try:
        portfolio_conn = portfolio_backend.connect_portfolio()
    except BackupVerificationError as exc:
        st.error(
            f"Aktualizacja bazy wstrzymana: kopia zapasowa nie przeszła weryfikacji ({exc}). "
            "Dane nie zostały zmienione."
        )
        st.stop()
    except PgStoreUnavailableError as exc:
        st.error(
            f"Baza portfela (Supabase) jest chwilowo niedostępna: {exc}\n\n"
            "Jeśli to darmowy, nieużywany od tygodnia projekt Supabase — wznów go ręcznie "
            "w dashboardzie Supabase i odśwież tę stronę."
        )
        st.stop()
    return portfolio_conn


@st.cache_resource(ttl=600, show_spinner=False)
def _snapshot_path():
    """Wskaźnik snapshotu z GitHuba + SHA256 pliku (21 MB) raz na 10 min,
    nie przy każdym kliknięciu. Nowy skan pojawi się najwyżej 10 min
    po publikacji. Błąd (`SnapshotUnavailableError`) nie jest pamiętany."""
    snapshot_path, _pointer = ensure_local_snapshot(
        SNAPSHOT_REPO_OWNER, SNAPSHOT_REPO_NAME, cache_dir=SNAPSHOT_CACHE_DIR,
    )
    return snapshot_path


def _connect_backends() -> tuple[object, object] | None:
    """Faza 8 Etap D -- zwraca `(portfolio_conn, scanner_conn)` albo
    `None`, gdy któryś backend jest niedostępny (w tym wypadku ta
    funkcja sama pokazuje czytelny `st.error` i woła `st.stop()` --
    Decyzja właścicielki pkt 3: "Jeżeli baza jest paused/unavailable:
    UI ma pokazać czytelny komunikat zamiast tracebacka", NIGDY próba
    automatycznego utworzenia/naprawienia bazy).

    Tryb LOKALNY (`portfolio_backend.is_hosted()` == False, domyślny):
    JEDNO połączenie SQLite dla obu -- dokładnie jak w Fazie 7, zero
    zmian.

    Tryb HOSTOWANY: `portfolio_conn` = Postgres/Supabase (7 tabel
    user-generated), `scanner_conn` = SQLite snapshot pobrany i
    zweryfikowany (SHA256) z GitHub Release, otwarty READ-ONLY
    (`file:...?mode=ro`) -- hostowana appka nigdy nie zapisuje do
    danych scannera."""
    portfolio_conn = _open_portfolio_conn()
    if not portfolio_backend.is_hosted():
        return portfolio_conn, portfolio_conn

    try:
        snapshot_path = _snapshot_path()
    except SnapshotUnavailableError as exc:
        st.error(f"Dane scannera są chwilowo niedostępne: {exc}")
        st.stop()
        return None

    scanner_conn = sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True)
    scanner_conn.row_factory = sqlite3.Row
    return portfolio_conn, scanner_conn


def main() -> None:
    st.set_page_config(page_title="Buffett Opportunity Scanner", layout="wide")
    st.title("Buffett Opportunity Scanner")

    backends = _connect_backends()
    if backends is None:
        return  # _connect_backends już pokazał błąd i wywołał st.stop()
    portfolio_conn, scanner_conn = backends

    _render_glossary()
    user = _render_user_picker(portfolio_conn)

    latest_run_id, synthesis_rows, run_complete = _render_synthesis_table(scanner_conn, portfolio_conn)

    if user is None:
        return

    st.markdown("---")
    _render_portfolio_bar(portfolio_conn, scanner_conn, user)
    st.markdown("---")

    # Sekcja 2 specyfikacji: PORTFEL jest stałą pierwszą zakładką,
    # zakładki kandydatów są DYNAMICZNE (z ostatniego właściwego skanu,
    # nigdy hard-coded CBOE/PAYX/...). Zagnieżdżone st.tabs() empirycznie
    # potwierdzone stabilne -- patrz KROK 0.
    tab_labels = ["PORTFEL"] + [r["ticker"] for r in synthesis_rows]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_portfolio_tab(portfolio_conn, scanner_conn, user)

    for tab, row in zip(tabs[1:], synthesis_rows):
        with tab:
            _render_candidate_card(
                scanner_conn, portfolio_conn, run_id=latest_run_id, cik=row["cik"], user_id=user["user_id"],
                run_complete=run_complete,
            )


if __name__ == "__main__":
    main()
