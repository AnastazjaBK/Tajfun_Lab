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

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from buffett_scanner import portfolio_backend
from buffett_scanner.db import init_db
from buffett_scanner.pg_store import PgStoreUnavailableError
from buffett_scanner.portfolio_backend import (
    create_user,
    get_latest_holding_user_action,
    get_latest_user_decision,
    get_purchase_thesis,
    get_purchase_transactions,
    get_sale_transactions,
    get_users,
    insert_holding_user_action,
    insert_position,
    insert_purchase_transaction,
    insert_sale_transaction,
    insert_user_decision,
    update_position_instrument,
    void_position,
    void_purchase_transaction,
    void_sale_transaction,
)
from buffett_scanner.ui.instrument_lookup import (
    InstrumentLookupResult,
    instrument_save_errors,
    lookup_instrument,
)
from buffett_scanner.ui.labels import (
    GLOSSARY,
    METHODOLOGY_DISCLAIMER,
    acquisition_types_label,
    analysis_status_label,
    broker_label,
    decision_status_label,
    decline_flags_label,
    holding_action_label,
)
from buffett_scanner.ui.portfolio import compute_broker_currency_subpositions, compute_portfolio_bar_summary
from buffett_scanner.ui.pricing import (
    BASE_CURRENCY,
    FxRates,
    Quote,
    fetch_nbp_rates,
    fetch_quote,
    total_in_currency,
)
from buffett_scanner.ui.queries import (
    get_brokers_in_use_for_user,
    get_candidate_detail,
    get_latest_live_scan_run,
    get_review_needed_count,
    get_synthesis_rows,
    get_user_positions_with_summaries,
    is_instrument_confirmed,
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
_BROKER_OPTIONS = ("TRADE_REPUBLIC", "REVOLUT", "OTHER")

# Sekcja 10 specyfikacji -- istniejący enum `purchase_transactions.
# acquisition_type`.
_ACQUISITION_TYPE_OPTIONS = ("BUY", "BONUS")

_VALUATION_SCENARIO_LABELS = (
    ("bear", "Pesymistyczny (BEAR)"),
    ("base", "Bazowy (BASE)"),
    ("bull", "Optymistyczny (BULL)"),
)

DB_PATH = os.environ.get("BUFFETT_SCANNER_DB", "buffett_scanner.db")

# Faza 8 "Hostowany V0" -- tylko w trybie `portfolio_backend.is_hosted()`.
SNAPSHOT_REPO_OWNER = os.environ.get("SNAPSHOT_REPO_OWNER", "AnastazjaBK")
SNAPSHOT_REPO_NAME = os.environ.get("SNAPSHOT_REPO_NAME", "Tajfun_Lab")
SNAPSHOT_CACHE_DIR = os.environ.get("SNAPSHOT_CACHE_DIR", tempfile.gettempdir())


# Faza 9: kolory zysku/straty w tabeli (Styler) -- czytelne w jasnym
# i ciemnym motywie Streamlit.
_PL_GAIN_CSS = "color: #21a366; font-weight: 600"
_PL_LOSS_CSS = "color: #e5534b; font-weight: 600"

# Faza 9: ceny FMP i kursy NBP odświeżane co godzinę (Decyzja
# właścicielki 2026-10-17) -- chroni dzienny limit zapytań planu FMP.
_PRICE_CACHE_TTL_S = 3600


@st.cache_data(ttl=_PRICE_CACHE_TTL_S, show_spinner=False)
def _cached_quote(symbol: str) -> Quote | None:
    return fetch_quote(symbol)


@st.cache_data(ttl=_PRICE_CACHE_TTL_S, show_spinner=False)
def _cached_nbp_rates() -> FxRates | None:
    return fetch_nbp_rates()


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


def _render_pln_totals(container, bar: dict, fx: FxRates | None) -> None:
    """Faza 9: łączne kwoty przeliczone na PLN kursem NBP -- tylko gdy
    portfel ma waluty inne niż PLN (inaczej to dubel wiersza powyżej).
    Brak kursu którejkolwiek waluty -> komunikat, nigdy suma częściowa."""
    currencies = set(bar["invested_by_currency"]) | set(bar["current_value_by_currency"])
    if not currencies or currencies == {BASE_CURRENCY}:
        return
    # Pusty słownik (żadna pozycja nie ma ceny) -> "—", nigdy "0 PLN".
    value = total_in_currency(bar["current_value_by_currency"], BASE_CURRENCY, fx) if bar["current_value_by_currency"] else None
    invested = total_in_currency(bar["invested_by_currency"], BASE_CURRENCY, fx)
    pl = total_in_currency(bar["unrealized_pl_by_currency"], BASE_CURRENCY, fx) if bar["unrealized_pl_by_currency"] else None
    if fx is None or invested is None:
        container.caption("Łącznie w PLN: kurs NBP chwilowo niedostępny.")
        return
    cols = container.columns(3)
    cols[0].metric("Wartość bieżąca łącznie (PLN)", f"{value:,.0f} PLN" if value is not None else "—")
    cols[1].metric("Zainwestowany kapitał łącznie (PLN)", f"{invested:,.0f} PLN")
    _render_pl_metric(cols[2], "Zysk/strata łącznie (PLN)", {BASE_CURRENCY: pl} if pl is not None else None)
    container.caption(
        f"Przeliczenie po kursie średnim NBP z {fx.effective_date}. Kwoty w USD przeliczone po "
        "dzisiejszym kursie (nie po kursie z dnia zakupu)."
    )


def _render_pricing_caption(container, summaries: list, fx: FxRates | None) -> None:
    priced = sum(1 for s in summaries if s.current_value_by_currency)
    fx_text = f"kursy NBP z {fx.effective_date}" if fx is not None else "kursy NBP chwilowo niedostępne"
    partial = (
        " Zysk/strata liczony tylko dla pozycji z ceną, a zainwestowany kapitał obejmuje wszystkie — "
        "dlatego wartość minus kapitał nie równa się zyskowi/stracie."
        if priced < len(summaries) else ""
    )
    container.caption(
        f"Cena bieżąca dostępna dla {priced} z {len(summaries)} pozycji.{partial} Ceny: FMP (z opóźnieniem, "
        f"odświeżane co godzinę), {fx_text}. Dywidendy: dane niedostępne."
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


def _render_synthesis_table(scanner_conn) -> tuple[str | None, list[dict]]:
    """Sekcja 4 specyfikacji: tabela SYNTEZY ostatniego WŁAŚCIWEGO
    live-scanu (nigdy walidacji technicznej -- patrz `ui/queries.
    get_latest_live_scan_run`). FAILED to status RAPORTU jakościowego,
    nie ocena spółki -- deterministyczne dane/cena/wycena pozostają
    widoczne niezależnie od statusu analizy LLM. Zwraca `(run_id, rows)`
    -- `run_id` reużywany przez karty kandydatów, żeby nie odpytywać
    "najnowszego skanu" drugi raz per zakładkę."""
    run = get_latest_live_scan_run(scanner_conn)
    if run is None:
        st.info("Brak jeszcze ukończonego live-scan rynku.")
        return None, []

    st.subheader(f"Co scanner znalazł — skan z {run['run_date']}")
    rows = get_synthesis_rows(scanner_conn, run["run_id"])
    if not rows:
        st.info("Ten skan nie wytypował żadnych kandydatów (to prawidłowy wynik).")
        return run["run_id"], rows

    table_data = [
        {
            "Ticker": r["ticker"],
            "Spółka": r["company_name"],
            "Cena": r["current_price"],
            "Dlaczego spadła": decline_flags_label(r["triggered_decline_flags"]),
            "Wynik": r["full_score"] if r["full_score"] is not None else "—",
            "Wynik deterministyczny (%)": r["deterministic_score_pct"],
            "Margines bezpieczeństwa (BASE)": (
                f"{r['margin_of_safety_pct']:.1f}%" if r["margin_of_safety_pct"] is not None else "—"
            ),
            "Dlaczego ciekawa?": r["bull_case_first"] or "—",
            "Największe ryzyko": r["biggest_risk"] or "—",
            "Status analizy": analysis_status_label(r["llm_status"]),
        }
        for r in rows
    ]
    st.dataframe(table_data, use_container_width=True, hide_index=True)
    st.caption(METHODOLOGY_DISCLAIMER)
    return run["run_id"], rows


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
    fx = _cached_nbp_rates()
    positions_with_summaries = get_user_positions_with_summaries(
        portfolio_conn, scanner_conn, user["user_id"], broker=broker, quote_fn=_cached_quote, fx=fx,
    )
    summaries = [s for _, s in positions_with_summaries]
    review_needed = get_review_needed_count(portfolio_conn, user["user_id"])
    bar = compute_portfolio_bar_summary(summaries, review_needed_count=review_needed)

    header_cols = st.columns([4, 1])
    header_cols[0].subheader("Portfel")
    if header_cols[1].button("Odśwież ceny", key="refresh_prices"):
        _cached_quote.clear()
        _cached_nbp_rates.clear()
        st.rerun()
    cols = st.columns(5)
    cols[0].metric("Pozycje", bar["position_count"])
    cols[1].metric("Wartość bieżąca", _format_currency_dict(bar["current_value_by_currency"]))
    cols[2].metric("Zainwestowany kapitał", _format_currency_dict(bar["invested_by_currency"]))
    _render_pl_metric(cols[3], "Zysk/strata", bar["unrealized_pl_by_currency"])
    cols[4].metric("Do przeglądu", bar["review_needed_count"])
    if bar["position_count"] > 0:
        _render_pln_totals(st, bar, fx)
        _render_pricing_caption(st, summaries, fx)


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
    current = get_latest_user_decision(portfolio_conn, user_id=user_id, cik=cik)
    if current is not None:
        st.caption(f"Twoja ostatnia decyzja: **{decision_status_label(current['status'])}**")

    cols = st.columns(4)
    for col, (status, label) in zip(cols, _DECISION_BUTTONS):
        if col.button(label, key=f"decision_{cik}_{status}"):
            insert_user_decision(portfolio_conn, user_id=user_id, cik=cik, status=status)
            portfolio_conn.commit()
            st.rerun()


def _render_candidate_card(scanner_conn, portfolio_conn, run_id: str, cik: str, *, user_id: int) -> None:
    """Sekcja 15 specyfikacji UI -- pełna karta kandydata PO POLSKU.
    Deterministyczne sekcje (decline/wycena) zawsze renderowane; sekcje
    zależne od analizy LLM (`analysis`) pokazują jawnie "Analiza
    jakościowa niekompletna", gdy `llm_status != COMPLETE` -- nigdy nie
    ukrywają reszty karty ani przycisków decyzji (sekcja 16: decyzja
    musi być możliwa NIEZALEŻNIE od kompletności analizy jakościowej)."""
    detail = get_candidate_detail(scanner_conn, run_id, cik)
    analysis = detail["analysis"]

    st.header(f"{detail['ticker']} — {detail['company_name']}")

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

    st.markdown("##### Łączne wartości")
    bar = compute_portfolio_bar_summary(summaries, review_needed_count=0)
    cols = st.columns(3)
    cols[0].metric("Wartość bieżąca", _format_currency_dict(bar["current_value_by_currency"]))
    cols[1].metric("Zainwestowany kapitał", _format_currency_dict(bar["invested_by_currency"]))
    _render_pl_metric(cols[2], "Zysk/strata", bar["unrealized_pl_by_currency"])
    _render_pln_totals(st, bar, fx)
    _render_pricing_caption(st, summaries, fx)

    st.markdown("##### Pozycje (rozbicie per broker)")
    table_rows = []
    pl_signs = []
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
                "Akcje": sub.shares_held,
                "Śr. cena zakupu": _format_optional(sub.avg_price),
                "Własny koszt": f"{sub.total_invested:.2f} {sub.currency}",
                "Bieżąca cena": (
                    f"{current_price_per_share:.2f} {sub.currency}" if current_price_per_share is not None else "—"
                ),
                "Bieżąca wartość": (
                    f"{current_value:.2f} {sub.currency}" if current_value is not None else "—"
                ),
                "Zysk/strata": f"{pl:+.2f} {sub.currency}" if pl is not None else "—",
                "Zysk/strata %": f"{pl_pct:+.1f}%" if pl_pct is not None else "n/d",
                "Sposób nabycia": acquisition_types_label(sub.acquisition_types),
                "Status": status_label,
                "Uwagi": price_note,
            })
            pl_signs.append(0 if pl is None else (1 if pl > 0 else -1 if pl < 0 else 0))

    if not table_rows:
        # Np. pozycja, której wszystkie transakcje anulowano (Faza 9).
        st.info("Brak aktywnych transakcji w pozycjach.")
        return

    def _pl_column_css(_column):
        return [_PL_GAIN_CSS if sign > 0 else _PL_LOSS_CSS if sign < 0 else "" for sign in pl_signs]

    styled = pd.DataFrame(table_rows).style.apply(_pl_column_css, subset=["Zysk/strata", "Zysk/strata %"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(
        "Bieżąca cena i wartość w walucie, w której zapłaciłaś/eś (np. PLN) — przeliczone kursem NBP. "
        "Zysk/strata = bieżąca wartość − własny koszt, razem z efektem zmiany kursu waluty."
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

    st.markdown("#### Co to za firma?")
    description = snapshot.get("business_description") if snapshot else None
    if description:
        st.write(description)
    else:
        st.info("Opis spółki niedostępny — ta pozycja nie ma jeszcze zapisanej analizy scannera.")

    st.markdown("#### Moja pozycja")
    st.write(f"Liczba akcji: **{summary.shares_held:g}**")
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
    if len(summary.by_broker_currency) > 1:
        st.write("**Rozbicie per broker:**")
        for sub in summary.by_broker_currency:
            st.write(
                f"- {broker_label(sub.broker)}: {sub.shares_held:g} akcji, "
                f"śr. cena {_format_optional(sub.avg_price)} {sub.currency}"
            )

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
    with st.expander("Popraw dane / anuluj błędny wpis"):
        _render_instrument_correction(portfolio_conn, position)
        st.markdown("---")
        _render_transaction_voiding(portfolio_conn, position)


def _render_instrument_correction(portfolio_conn, position: dict) -> None:
    """Faza 9 -- poprawa tożsamości instrumentu (np. `SU` -> `SU.PA`).
    Te same reguły co przy nowej pozycji: rozpoznany symbol wymaga
    jawnego potwierdzenia. Transakcje (koszt) zostają nietknięte."""
    position_id = position["position_id"]
    st.markdown("##### Instrument")
    status = "potwierdzony" if is_instrument_confirmed(position) else "NIEPOTWIERDZONY — cena bieżąca nie jest pobierana"
    st.write(
        f"Obecnie: **{position['ticker']}** — {position['company_name']} "
        f"({position['exchange'] or 'giełda nieznana'}). Status: {status}."
    )
    choice = _render_instrument_lookup_widget(f"fix_{position_id}")
    confirmed_result = choice.confirmed_result
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
            f"{row['shares']:g} akcji · {row['total_invested']:.2f} {row['currency']}"
        )
    return (
        f"Sprzedaż {row['sale_date']} · {broker_label(row['broker'])} · "
        f"{row['shares']:g} akcji po {row['sale_price']:.2f} {row['currency']}"
    )


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
            negative = [
                sub for sub in compute_broker_currency_subpositions(remaining_purchases, remaining_sales)
                if sub.shares_held < -1e-9
            ]
            if not sure:
                st.error("Zaznacz potwierdzenie, aby anulować transakcję.")
            elif negative:
                st.error(
                    "Po anulowaniu tego zakupu sprzedaże przekroczyłyby posiadane akcje "
                    f"({broker_label(negative[0].broker)}, {negative[0].currency}). Najpierw anuluj sprzedaż."
                )
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


def _render_instrument_lookup_widget(key_prefix: str) -> _InstrumentChoice:
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
    if st.button("Sprawdź instrument w FMP", key=f"{key_prefix}_lookup_btn") and symbol:
        st.session_state[f"{key_prefix}_lookup_symbol"] = symbol
        st.session_state[f"{key_prefix}_lookup_result"] = lookup_instrument(symbol)
        st.session_state[f"{key_prefix}_confirm"] = False

    looked_up_symbol = st.session_state.get(f"{key_prefix}_lookup_symbol")
    result = st.session_state.get(f"{key_prefix}_lookup_result")

    if looked_up_symbol != symbol:
        if looked_up_symbol is not None:
            st.caption("Symbol zmienił się od ostatniego sprawdzenia — sprawdź ponownie przed zapisem.")
        return _InstrumentChoice(symbol=symbol, looked_up=False, result=None, confirmed=False)

    if result is None:
        st.warning(
            "FMP nie rozpoznał tego symbolu (albo brak skonfigurowanego klucza API). "
            "Możesz zapisać pozycję ręcznie, bez automatycznej ceny bieżącej — nigdy nie "
            "zgadujemy symbolu ani giełdy za Ciebie."
        )
        return _InstrumentChoice(symbol=symbol, looked_up=True, result=None, confirmed=False)

    st.success(
        f"FMP rozpoznał: **{result.company_name or '—'}** "
        f"({result.exchange or '—'}, {result.currency or '—'})."
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


def _render_new_position_form(portfolio_conn, user: dict) -> None:
    st.markdown("##### Nowa pozycja")
    choice = _render_instrument_lookup_widget("new_pos")
    confirmed_result = choice.confirmed_result
    _render_quote_currency_hint(choice)
    acquisition_type = _render_acquisition_type_picker("new_pos_acq_type")

    with st.form("new_position_form", clear_on_submit=True):
        company_name = st.text_input(
            "Nazwa spółki", value=(confirmed_result.company_name if confirmed_result else "") or "",
        )
        exchange = st.text_input(
            "Giełda (opcjonalnie)", value=(confirmed_result.exchange if confirmed_result else "") or "",
        )
        broker = st.selectbox("Broker", _BROKER_OPTIONS, format_func=broker_label, key="new_pos_broker")
        purchase_date = st.date_input("Data transakcji", key="new_pos_date")
        shares = st.number_input("Liczba akcji", min_value=0.0, step=0.0001, format="%.4f", key="new_pos_shares")
        currency = st.text_input("Waluta transakcji (np. PLN, USD, EUR)", key="new_pos_currency")
        total_invested = st.number_input(
            "Zainwestowany kapitał (cała kwota, która zeszła z konta)" if acquisition_type == "BUY"
            else "Zainwestowany kapitał (bonus = 0)",
            min_value=0.0, step=0.01, format="%.2f",
            disabled=(acquisition_type == "BONUS"), key="new_pos_invested",
        )
        fees = st.number_input("Opłaty (opcjonalnie)", min_value=0.0, step=0.01, format="%.2f", key="new_pos_fees")
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
            if acquisition_type == "BUY" and total_invested <= 0:
                errors.append(
                    "Zainwestowany kapitał musi być większy od zera dla zakupu. "
                    "Jeśli to akcje za darmo, wybierz powyżej „Bonus”."
                )
            for error in errors:
                st.error(error)
            if not errors:
                final_invested = 0.0 if acquisition_type == "BONUS" else total_invested
                price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                ticker = (confirmed_result.symbol if confirmed_result else choice.symbol).strip()
                position_id = insert_position(
                    portfolio_conn, user_id=user["user_id"], ticker=ticker, company_name=company_name.strip(),
                    cik=(confirmed_result.cik if confirmed_result else None),
                    exchange=(exchange.strip() or None), instrument_currency=currency.strip(),
                    instrument_confirmed=confirmed_result is not None,
                )
                insert_purchase_transaction(
                    portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                    purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                    currency=currency.strip(), price_per_share=price_per_share,
                    fees=(fees or None), note=(note.strip() or None),
                )
                portfolio_conn.commit()
                for key in ("new_pos_lookup_symbol", "new_pos_lookup_result", "new_pos_confirm"):
                    st.session_state.pop(key, None)
                st.toast(f"Zapisano nową pozycję: {ticker}.")
                st.rerun()


def _render_existing_position_transaction_form(portfolio_conn, position: dict) -> None:
    position_id = position["position_id"]
    st.markdown(f"##### {position['ticker']} — {position['company_name']}")
    kind = st.radio(
        "Typ transakcji", ["Zakup/Bonus", "Sprzedaż"], key=f"tx_kind_{position_id}", horizontal=True,
    )

    if kind == "Zakup/Bonus":
        acquisition_type = _render_acquisition_type_picker(f"ep_acq_type_{position_id}")
        with st.form(f"purchase_form_{position_id}", clear_on_submit=True):
            broker = st.selectbox("Broker", _BROKER_OPTIONS, format_func=broker_label, key=f"ep_broker_{position_id}")
            purchase_date = st.date_input("Data transakcji", key=f"ep_date_{position_id}")
            shares = st.number_input(
                "Liczba akcji", min_value=0.0, step=0.0001, format="%.4f", key=f"ep_shares_{position_id}",
            )
            currency = st.text_input(
                "Waluta transakcji", value=position["instrument_currency"] or "", key=f"ep_currency_{position_id}",
            )
            total_invested = st.number_input(
                "Zainwestowany kapitał (cała kwota, która zeszła z konta)" if acquisition_type == "BUY"
                else "Zainwestowany kapitał (bonus = 0)",
                min_value=0.0, step=0.01, format="%.2f",
                disabled=(acquisition_type == "BONUS"), key=f"ep_invested_{position_id}",
            )
            fees = st.number_input(
                "Opłaty (opcjonalnie)", min_value=0.0, step=0.01, format="%.2f", key=f"ep_fees_{position_id}",
            )
            note = st.text_input("Notatka (opcjonalnie)", key=f"ep_note_{position_id}")

            submitted = st.form_submit_button("Zapisz zakup/bonus")
            if submitted:
                errors = []
                if shares <= 0:
                    errors.append("Liczba akcji musi być większa od zera.")
                if not currency.strip():
                    errors.append("Waluta transakcji jest wymagana.")
                if acquisition_type == "BUY" and total_invested <= 0:
                    errors.append(
                        "Zainwestowany kapitał musi być większy od zera dla zakupu. "
                        "Jeśli to akcje za darmo, wybierz powyżej „Bonus”."
                    )
                for error in errors:
                    st.error(error)
                if not errors:
                    final_invested = 0.0 if acquisition_type == "BONUS" else total_invested
                    price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                    insert_purchase_transaction(
                        portfolio_conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                        purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                        currency=currency.strip(), price_per_share=price_per_share,
                        fees=(fees or None), note=(note.strip() or None),
                    )
                    portfolio_conn.commit()
                    st.toast("Zapisano zakup/bonus.")
                    st.rerun()
    else:
        with st.form(f"sale_form_{position_id}", clear_on_submit=True):
            broker = st.selectbox("Broker", _BROKER_OPTIONS, format_func=broker_label, key=f"es_broker_{position_id}")
            sale_date = st.date_input("Data sprzedaży", key=f"es_date_{position_id}")
            shares = st.number_input(
                "Liczba sprzedanych akcji", min_value=0.0, step=0.0001, format="%.4f", key=f"es_shares_{position_id}",
            )
            sale_price = st.number_input(
                "Cena sprzedaży za akcję", min_value=0.0, step=0.01, format="%.2f", key=f"es_price_{position_id}",
            )
            currency = st.text_input(
                "Waluta transakcji", value=position["instrument_currency"] or "", key=f"es_currency_{position_id}",
            )
            fees = st.number_input(
                "Opłaty (opcjonalnie)", min_value=0.0, step=0.01, format="%.2f", key=f"es_fees_{position_id}",
            )
            note = st.text_input("Notatka (opcjonalnie)", key=f"es_note_{position_id}")

            submitted = st.form_submit_button("Zapisz sprzedaż")
            if submitted:
                errors = []
                if shares <= 0:
                    errors.append("Liczba sprzedanych akcji musi być większa od zera.")
                if sale_price <= 0:
                    errors.append("Cena sprzedaży musi być większa od zera.")
                if not currency.strip():
                    errors.append("Waluta transakcji jest wymagana.")
                if not errors:
                    # Sekcja 7 specyfikacji: "Nie pozwalaj, aby sprzedaż na
                    # jednym brokerze tworzyła ujemną subpozycję tylko
                    # dlatego, że akcje istnieją na drugim brokerze." --
                    # realny bug znaleziony przy weryfikacji wizualnej (Faza
                    # 7 KROK 7): sprzedaż z brokera bez wystarczających akcji
                    # cicho tworzyła "-4 akcje" w tabeli. Sprawdzane TUTAJ
                    # (nie w ui/portfolio.py, które poprawnie liczy to, co
                    # dostanie) -- to warstwa walidacji formularza.
                    existing_subpositions = {
                        (s.broker, s.currency): s.shares_held
                        for s in compute_broker_currency_subpositions(
                            get_purchase_transactions(portfolio_conn, position_id),
                            get_sale_transactions(portfolio_conn, position_id),
                        )
                    }
                    held = existing_subpositions.get((broker, currency.strip()), 0.0)
                    if shares > held:
                        errors.append(
                            f"Na {broker_label(broker)} w walucie {currency.strip()} posiadasz "
                            f"{held:g} akcji — nie można sprzedać {shares:g}. Sprawdź, czy wybrałaś/eś "
                            "właściwego brokera i walutę."
                        )
                for error in errors:
                    st.error(error)
                if not errors:
                    insert_sale_transaction(
                        portfolio_conn, position_id=position_id, broker=broker, sale_date=str(sale_date),
                        shares=shares, sale_price=sale_price, currency=currency.strip(),
                        fees=(fees or None), note=(note.strip() or None),
                    )
                    portfolio_conn.commit()
                    st.toast("Zapisano sprzedaż.")
                    st.rerun()


def _render_add_transaction_tab(portfolio_conn, scanner_conn, user: dict) -> None:
    """Sekcja 11 specyfikacji -- formularz "Dodaj transakcję". Jedna
    `position_id` może mieć transakcje na wielu brokerach (sekcja 7) --
    wybór "istniejąca pozycja" NIGDY nie tworzy drugiej, równoległej
    pozycji dla tego samego instrumentu."""
    positions_with_summaries = get_user_positions_with_summaries(portfolio_conn, scanner_conn, user["user_id"])
    positions = [dict(p) for p, _ in positions_with_summaries]

    options = ["+ Nowa pozycja"] + [f"{p['ticker']} — {p['company_name']}" for p in positions]
    choice = st.selectbox("Pozycja", options, key="add_tx_position_choice")

    if choice == "+ Nowa pozycja":
        _render_new_position_form(portfolio_conn, user)
    else:
        _render_existing_position_transaction_form(portfolio_conn, positions[options.index(choice) - 1])


def _render_platform_filter(portfolio_conn, user: dict) -> str:
    """Filtr platformy w PORTFELU (Decyzja właścicielki). Działa na
    poziomie TRANSAKCJI (filtruje purchase/sale rows PRZED przekazaniem
    do `compute_position_summary` -- `ui/queries.get_user_positions_
    with_summaries(..., broker=...)`), nigdy nie miesza brokerów,
    użytkowników ani walut, nie wymaga FX. Trade Republic/Revolut
    zawsze widoczne; "Inny" tylko gdy użytkownik ma choć jedną realną
    transakcję OTHER (`get_brokers_in_use_for_user`)."""
    brokers_in_use = get_brokers_in_use_for_user(portfolio_conn, user["user_id"])
    codes = list(_PLATFORM_FILTER_ALWAYS_AVAILABLE)
    if "OTHER" in brokers_in_use:
        codes.append("OTHER")
    labels = {"ALL": "Wszystkie", **{c: broker_label(c) for c in codes if c != "ALL"}}
    selected = st.selectbox(
        "Platforma", codes, format_func=lambda c: labels[c], key="platform_filter",
    )
    return selected


def _render_portfolio_tab(portfolio_conn, scanner_conn, user: dict) -> None:
    """Sekcja 6 specyfikacji: wewnątrz PORTFEL, filtr platformy, drugi
    poziom zakładek [PODSUMOWANIE][+ Dodaj transakcję] + DYNAMICZNE
    tickery posiadanych pozycji. Filtr platformy zawęża PODSUMOWANIE i
    zakładki pozycji; "+ Dodaj transakcję" celowo NIE jest filtrowana
    (`_render_add_transaction_tab` sama czyta pełną, nieprzefiltrowaną
    listę pozycji -- można dodać transakcję na innej platformie niż
    aktualnie przeglądana)."""
    platform_filter = _render_platform_filter(portfolio_conn, user)
    broker = None if platform_filter == "ALL" else platform_filter
    fx = _cached_nbp_rates()
    positions_with_summaries = get_user_positions_with_summaries(
        portfolio_conn, scanner_conn, user["user_id"], broker=broker, quote_fn=_cached_quote, fx=fx,
    )

    inner_labels = ["PODSUMOWANIE", "+ Dodaj transakcję"] + [p["ticker"] for p, _ in positions_with_summaries]
    inner_tabs = st.tabs(inner_labels)

    with inner_tabs[0]:
        _render_portfolio_summary_tab(
            portfolio_conn, positions_with_summaries, platform_filter=platform_filter, fx=fx,
        )

    with inner_tabs[1]:
        _render_add_transaction_tab(portfolio_conn, scanner_conn, user)

    for tab, (position, summary) in zip(inner_tabs[2:], positions_with_summaries):
        with tab:
            _render_position_card(portfolio_conn, dict(position), summary)


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
    if not portfolio_backend.is_hosted():
        # `init_db` (nie `connect`) -- `CREATE TABLE IF NOT EXISTS` +
        # migracje kolumn idempotentne, ten sam wzorzec co KAŻDE
        # wywołanie w cli.py. Realny błąd znaleziony przy weryfikacji
        # "czy aplikacja startuje bez błędów" (Faza 7): plain `connect()`
        # na zupełnie świeżym pliku DB wywalał `OperationalError: no
        # such table: users` -- `init_db` naprawia to bez ryzyka dla
        # istniejących danych.
        conn = init_db(DB_PATH)
        return conn, conn

    try:
        portfolio_conn = portfolio_backend.connect_portfolio()
    except PgStoreUnavailableError as exc:
        st.error(
            f"Baza portfela (Supabase) jest chwilowo niedostępna: {exc}\n\n"
            "Jeśli to darmowy, nieużywany od tygodnia projekt Supabase — wznów go ręcznie "
            "w dashboardzie Supabase i odśwież tę stronę."
        )
        st.stop()
        return None

    try:
        snapshot_path, _pointer = ensure_local_snapshot(
            SNAPSHOT_REPO_OWNER, SNAPSHOT_REPO_NAME, cache_dir=SNAPSHOT_CACHE_DIR,
        )
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

    latest_run_id, synthesis_rows = _render_synthesis_table(scanner_conn)

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
            )


if __name__ == "__main__":
    main()
