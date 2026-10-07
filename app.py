"""Buffett Opportunity Scanner — UI + PORTFOLIO V0 (Faza 7).

Punkt wejścia Streamlit. WYŁĄCZNIE prezentacja/odczyt + proste
formularze zapisu (decyzje, transakcje) — zero logiki
scoringu/wyceny/DCF/decline-screeningu/Claude API; cała ta logika
mieszka w `buffett_scanner.*` i jest tu TYLKO odczytywana/tłumaczona.

Uruchomienie lokalne:
    streamlit run app.py

Baza: zmienna środowiskowa `BUFFETT_SCANNER_DB` (domyślnie
`buffett_scanner.db` — ten sam plik, który zapisuje `cli.py`).

Połączenie z SQLite jest otwierane NA NOWO przy każdym rerunie skryptu
(zero `st.cache_resource` na samym obiekcie połączenia) — Streamlit
może wykonywać rerun różnych sesji (np. Anastazja i mąż z dwóch
przeglądarek naraz) w różnych wątkach, a `sqlite3.Connection` nie wolno
współdzielić między wątkami. Koszt otwarcia pliku SQLite jest
pomijalny przy tej skali danych.
"""

from __future__ import annotations

import json
import os

import streamlit as st

from buffett_scanner.db import (
    create_user,
    get_latest_holding_user_action,
    get_latest_user_decision,
    get_purchase_thesis,
    get_purchase_transactions,
    get_sale_transactions,
    get_users,
    init_db,
    insert_holding_user_action,
    insert_position,
    insert_purchase_transaction,
    insert_sale_transaction,
    insert_user_decision,
)
from buffett_scanner.ui.instrument_lookup import InstrumentLookupResult, lookup_instrument
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
from buffett_scanner.ui.queries import (
    get_brokers_in_use_for_user,
    get_candidate_detail,
    get_latest_live_scan_run,
    get_review_needed_count,
    get_synthesis_rows,
    get_user_positions_with_summaries,
)

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


def _format_currency_dict(values: dict[str, float]) -> str:
    """Nigdy nie sumuje różnych walut (sekcja 12 specyfikacji) --
    pokazuje każdą walutę osobno."""
    if not values:
        return "—"
    return " | ".join(f"{amount:,.0f} {currency}" for currency, amount in sorted(values.items()))


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


def _render_user_picker(conn) -> dict | None:
    """Selector czyta realnych użytkowników z bazy -- ZERO hardcode'owanych
    "Anastazja"/"Mąż" (Decyzja właścicielki, Faza 7 pkt 7: "nie zakładaj,
    że display_name drugiego użytkownika na zawsze brzmi 'Mąż'"). Gdy
    baza jest pusta, UI prosi o jawne, ręczne utworzenie pierwszego
    użytkownika -- zero automatycznego seedu przy starcie aplikacji."""
    with st.expander("+ Dodaj nowego użytkownika"):
        with st.form("add_user_form", clear_on_submit=True):
            new_name = st.text_input("Imię nowego użytkownika")
            if st.form_submit_button("Dodaj") and new_name.strip():
                create_user(conn, new_name.strip())
                conn.commit()
                st.rerun()

    users = get_users(conn)
    if not users:
        st.warning("Brak użytkowników. Dodaj pierwszego powyżej, aby zacząć.")
        return None

    names = [u["display_name"] for u in users]
    selected = st.selectbox("Użytkownik", names, key="selected_user_name")
    return next(u for u in users if u["display_name"] == selected)


def _render_synthesis_table(conn) -> tuple[str | None, list[dict]]:
    """Sekcja 4 specyfikacji: tabela SYNTEZY ostatniego WŁAŚCIWEGO
    live-scanu (nigdy walidacji technicznej -- patrz `ui/queries.
    get_latest_live_scan_run`). FAILED to status RAPORTU jakościowego,
    nie ocena spółki -- deterministyczne dane/cena/wycena pozostają
    widoczne niezależnie od statusu analizy LLM. Zwraca `(run_id, rows)`
    -- `run_id` reużywany przez karty kandydatów, żeby nie odpytywać
    "najnowszego skanu" drugi raz per zakładkę."""
    run = get_latest_live_scan_run(conn)
    if run is None:
        st.info("Brak jeszcze ukończonego live-scan rynku.")
        return None, []

    st.subheader(f"Co scanner znalazł — skan z {run['run_date']}")
    rows = get_synthesis_rows(conn, run["run_id"])
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


def _render_portfolio_bar(conn, user: dict) -> None:
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
    positions_with_summaries = get_user_positions_with_summaries(conn, user["user_id"], broker=broker)
    summaries = [s for _, s in positions_with_summaries]
    review_needed = get_review_needed_count(conn, user["user_id"])
    bar = compute_portfolio_bar_summary(summaries, review_needed_count=review_needed)

    st.subheader("Portfel")
    cols = st.columns(5)
    cols[0].metric("Pozycje", bar["position_count"])
    cols[1].metric("Wartość bieżąca", _format_currency_dict(bar["current_value_by_currency"]))
    cols[2].metric("Zainwestowany kapitał", _format_currency_dict(bar["invested_by_currency"]))
    cols[3].metric("Zysk/strata", _format_currency_dict(bar["unrealized_pl_by_currency"]))
    cols[4].metric("Do przeglądu", bar["review_needed_count"])
    if bar["position_count"] > 0 and not bar["current_value_by_currency"]:
        st.caption("Konwersja walut niedostępna w V0 — wartości pokazane per waluta, gdy znane.")


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


def _render_decision_buttons(conn, *, user_id: int, cik: str) -> None:
    """Sekcja 16 specyfikacji: decyzja jest USER-SPECIFIC (`user_decisions`,
    append-only) -- Anastazja i mąż mogą mieć RÓŻNY status dla tej samej
    spółki, kliknięcie jednego usera nigdy nie zmienia SHARED analizy."""
    current = get_latest_user_decision(conn, user_id=user_id, cik=cik)
    if current is not None:
        st.caption(f"Twoja ostatnia decyzja: **{decision_status_label(current['status'])}**")

    cols = st.columns(4)
    for col, (status, label) in zip(cols, _DECISION_BUTTONS):
        if col.button(label, key=f"decision_{cik}_{status}"):
            insert_user_decision(conn, user_id=user_id, cik=cik, status=status)
            conn.commit()
            st.rerun()


def _render_candidate_card(conn, run_id: str, cik: str, *, user_id: int) -> None:
    """Sekcja 15 specyfikacji UI -- pełna karta kandydata PO POLSKU.
    Deterministyczne sekcje (decline/wycena) zawsze renderowane; sekcje
    zależne od analizy LLM (`analysis`) pokazują jawnie "Analiza
    jakościowa niekompletna", gdy `llm_status != COMPLETE` -- nigdy nie
    ukrywają reszty karty ani przycisków decyzji (sekcja 16: decyzja
    musi być możliwa NIEZALEŻNIE od kompletności analizy jakościowej)."""
    detail = get_candidate_detail(conn, run_id, cik)
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
    _render_decision_buttons(conn, user_id=user_id, cik=cik)


def _format_optional(value: float | None, fmt: str = "{:.2f}") -> str:
    return fmt.format(value) if value is not None else "—"


def _render_portfolio_summary_tab(
    conn, positions_with_summaries: list, *, platform_filter: str = "ALL",
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
    cols[2].metric("Zysk/strata", _format_currency_dict(bar["unrealized_pl_by_currency"]))
    st.caption(
        "Dywidendy: dane niedostępne w V0. "
        + ("" if bar["current_value_by_currency"] else "Konwersja walut niedostępna w V0 — wartości per waluta.")
    )

    st.markdown("##### Pozycje (rozbicie per broker)")
    table_rows = []
    for position, summary in positions_with_summaries:
        latest_action = get_latest_holding_user_action(conn, position["position_id"])
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
            table_rows.append({
                "Ticker": position["ticker"],
                "Spółka": position["company_name"],
                "Platforma": broker_label(sub.broker),
                "Akcje": sub.shares_held,
                "Śr. cena zakupu": _format_optional(sub.avg_price),
                "Własny koszt": f"{sub.total_invested:.2f} {sub.currency}",
                "Bieżąca cena": _format_optional(current_price_per_share),
                "Bieżąca wartość": (
                    f"{current_value:.2f} {sub.currency}" if current_value is not None else "—"
                ),
                "P/L": f"{pl:.2f} {sub.currency}" if pl is not None else "—",
                "P/L %": f"{pl_pct:.1f}%" if pl_pct is not None else "n/d",
                "Sposób nabycia": acquisition_types_label(sub.acquisition_types),
                "Status": status_label,
            })
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


def _render_position_card(conn, position: dict, summary) -> None:
    """Sekcja 14 specyfikacji -- karta JEDNEJ posiadanej pozycji."""
    st.header(f"{position['ticker']} — {position['company_name']}")

    thesis = get_purchase_thesis(conn, position["position_id"])
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
        st.write(
            f"Własny koszt: {invested:.2f} {currency} | "
            f"Bieżąca wartość: {(f'{value:.2f} {currency}' if value is not None else '—')} | "
            f"P/L: {(f'{pl:.2f} {currency}' if pl is not None else '—')}"
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
    latest_action = get_latest_holding_user_action(conn, position["position_id"])
    if latest_action is not None:
        st.caption(f"Obecny status: **{holding_action_label(latest_action['action'])}**")
    cols = st.columns(4)
    for col, (action, label) in zip(cols, _HOLDING_ACTION_BUTTONS):
        if col.button(label, key=f"holding_{position['position_id']}_{action}"):
            insert_holding_user_action(conn, position_id=position["position_id"], action=action)
            conn.commit()
            st.rerun()


def _render_instrument_lookup_widget(key_prefix: str) -> tuple[str, InstrumentLookupResult | None]:
    """Sekcja 9/19 specyfikacji: "Nie zgaduj symbolu ani giełdy. Formularz
    ma pozwolić użytkownikowi potwierdzić instrument." Lookup jest POZA
    `st.form` -- musi pokazać wynik PRZED zapisem, więc potrzebuje
    własnego przycisku. Zwraca `(symbol, wynik_lookupu)` -- wynik jest
    `None`, dopóki użytkownik nie zaznaczy jawnego potwierdzenia, LUB
    gdy FMP nie rozpoznał symbolu (wtedy UI pozwala zapisać ręcznie,
    bez automatycznej ceny -- Decyzja właścicielki, Faza 7 pkt 6)."""
    symbol = st.text_input(
        "Symbol/ticker (np. AAPL, SU.PA, GSK.L)", key=f"{key_prefix}_symbol"
    ).strip()
    if st.button("Sprawdź instrument w FMP", key=f"{key_prefix}_lookup_btn") and symbol:
        st.session_state[f"{key_prefix}_lookup_symbol"] = symbol
        st.session_state[f"{key_prefix}_lookup_result"] = lookup_instrument(symbol)

    looked_up_symbol = st.session_state.get(f"{key_prefix}_lookup_symbol")
    result = st.session_state.get(f"{key_prefix}_lookup_result")

    if looked_up_symbol != symbol:
        if looked_up_symbol is not None:
            st.caption("Symbol zmienił się od ostatniego sprawdzenia — sprawdź ponownie przed zapisem.")
        return symbol, None

    if result is None:
        if looked_up_symbol is not None:
            st.warning(
                "FMP nie rozpoznał tego symbolu (albo brak skonfigurowanego klucza API). "
                "Możesz zapisać pozycję ręcznie, bez automatycznej ceny bieżącej — nigdy nie "
                "zgadujemy symbolu ani giełdy za Ciebie."
            )
        return symbol, None

    st.success(
        f"FMP rozpoznał: **{result.company_name or '—'}** "
        f"({result.exchange or '—'}, {result.currency or '—'})."
    )
    if result.currency and result.currency.strip() in {"GBp", "GBX"}:
        st.caption(
            "Uwaga: to notowanie jest w pensach (GBp), NIE w funtach (GBP) — sprawdź, w "
            "jakiej walucie Twój broker raportuje wartość tej transakcji."
        )
    confirmed = st.checkbox("Tak, to właściwy instrument", key=f"{key_prefix}_confirm")
    return symbol, (result if confirmed else None)


def _render_new_position_form(conn, user: dict) -> None:
    st.markdown("##### Nowa pozycja")
    symbol, confirmed_result = _render_instrument_lookup_widget("new_pos")

    with st.form("new_position_form", clear_on_submit=True):
        company_name = st.text_input(
            "Nazwa spółki", value=(confirmed_result.company_name if confirmed_result else "") or "",
        )
        exchange = st.text_input(
            "Giełda (opcjonalnie)", value=(confirmed_result.exchange if confirmed_result else "") or "",
        )
        broker = st.selectbox("Broker", _BROKER_OPTIONS, format_func=broker_label, key="new_pos_broker")
        acquisition_type = st.selectbox(
            "Sposób nabycia", _ACQUISITION_TYPE_OPTIONS,
            format_func=lambda t: acquisition_types_label((t,)), key="new_pos_acq_type",
        )
        purchase_date = st.date_input("Data transakcji", key="new_pos_date")
        shares = st.number_input("Liczba akcji", min_value=0.0, step=0.0001, format="%.4f", key="new_pos_shares")
        currency = st.text_input(
            "Waluta transakcji (np. USD, EUR, GBP)",
            value=(confirmed_result.currency if confirmed_result else "") or "",
            key="new_pos_currency",
        )
        total_invested = st.number_input(
            "Zainwestowany kapitał (0 dla bonusu)", min_value=0.0, step=0.01, format="%.2f",
            disabled=(acquisition_type == "BONUS"), key="new_pos_invested",
        )
        fees = st.number_input("Opłaty (opcjonalnie)", min_value=0.0, step=0.01, format="%.2f", key="new_pos_fees")
        note = st.text_input("Notatka (opcjonalnie)", key="new_pos_note")

        submitted = st.form_submit_button("Zapisz nową pozycję")
        if submitted:
            errors = []
            if not symbol:
                errors.append("Symbol/ticker jest wymagany.")
            if not company_name.strip():
                errors.append("Nazwa spółki jest wymagana.")
            if shares <= 0:
                errors.append("Liczba akcji musi być większa od zera.")
            if not currency.strip():
                errors.append("Waluta transakcji jest wymagana.")
            if acquisition_type == "BUY" and total_invested <= 0:
                errors.append("Zainwestowany kapitał musi być większy od zera dla zakupu (nie bonusu).")
            for error in errors:
                st.error(error)
            if not errors:
                final_invested = 0.0 if acquisition_type == "BONUS" else total_invested
                price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                position_id = insert_position(
                    conn, user_id=user["user_id"], ticker=symbol, company_name=company_name.strip(),
                    cik=(confirmed_result.cik if confirmed_result else None),
                    exchange=(exchange.strip() or None), instrument_currency=currency.strip(),
                )
                insert_purchase_transaction(
                    conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                    purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                    currency=currency.strip(), price_per_share=price_per_share,
                    fees=(fees or None), note=(note.strip() or None),
                )
                conn.commit()
                st.session_state.pop("new_pos_lookup_symbol", None)
                st.session_state.pop("new_pos_lookup_result", None)
                st.toast(f"Zapisano nową pozycję: {symbol}.")
                st.rerun()


def _render_existing_position_transaction_form(conn, position: dict) -> None:
    position_id = position["position_id"]
    st.markdown(f"##### {position['ticker']} — {position['company_name']}")
    kind = st.radio(
        "Typ transakcji", ["Zakup/Bonus", "Sprzedaż"], key=f"tx_kind_{position_id}", horizontal=True,
    )

    if kind == "Zakup/Bonus":
        with st.form(f"purchase_form_{position_id}", clear_on_submit=True):
            broker = st.selectbox("Broker", _BROKER_OPTIONS, format_func=broker_label, key=f"ep_broker_{position_id}")
            acquisition_type = st.selectbox(
                "Sposób nabycia", _ACQUISITION_TYPE_OPTIONS,
                format_func=lambda t: acquisition_types_label((t,)), key=f"ep_acq_type_{position_id}",
            )
            purchase_date = st.date_input("Data transakcji", key=f"ep_date_{position_id}")
            shares = st.number_input(
                "Liczba akcji", min_value=0.0, step=0.0001, format="%.4f", key=f"ep_shares_{position_id}",
            )
            currency = st.text_input(
                "Waluta transakcji", value=position["instrument_currency"] or "", key=f"ep_currency_{position_id}",
            )
            total_invested = st.number_input(
                "Zainwestowany kapitał (0 dla bonusu)", min_value=0.0, step=0.01, format="%.2f",
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
                    errors.append("Zainwestowany kapitał musi być większy od zera dla zakupu (nie bonusu).")
                for error in errors:
                    st.error(error)
                if not errors:
                    final_invested = 0.0 if acquisition_type == "BONUS" else total_invested
                    price_per_share = (final_invested / shares) if acquisition_type == "BUY" and shares > 0 else None
                    insert_purchase_transaction(
                        conn, position_id=position_id, broker=broker, acquisition_type=acquisition_type,
                        purchase_date=str(purchase_date), shares=shares, total_invested=final_invested,
                        currency=currency.strip(), price_per_share=price_per_share,
                        fees=(fees or None), note=(note.strip() or None),
                    )
                    conn.commit()
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
                            get_purchase_transactions(conn, position_id),
                            get_sale_transactions(conn, position_id),
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
                        conn, position_id=position_id, broker=broker, sale_date=str(sale_date),
                        shares=shares, sale_price=sale_price, currency=currency.strip(),
                        fees=(fees or None), note=(note.strip() or None),
                    )
                    conn.commit()
                    st.toast("Zapisano sprzedaż.")
                    st.rerun()


def _render_add_transaction_tab(conn, user: dict) -> None:
    """Sekcja 11 specyfikacji -- formularz "Dodaj transakcję". Jedna
    `position_id` może mieć transakcje na wielu brokerach (sekcja 7) --
    wybór "istniejąca pozycja" NIGDY nie tworzy drugiej, równoległej
    pozycji dla tego samego instrumentu."""
    positions_with_summaries = get_user_positions_with_summaries(conn, user["user_id"])
    positions = [dict(p) for p, _ in positions_with_summaries]

    options = ["+ Nowa pozycja"] + [f"{p['ticker']} — {p['company_name']}" for p in positions]
    choice = st.selectbox("Pozycja", options, key="add_tx_position_choice")

    if choice == "+ Nowa pozycja":
        _render_new_position_form(conn, user)
    else:
        _render_existing_position_transaction_form(conn, positions[options.index(choice) - 1])


def _render_platform_filter(conn, user: dict) -> str:
    """Filtr platformy w PORTFELU (Decyzja właścicielki). Działa na
    poziomie TRANSAKCJI (filtruje purchase/sale rows PRZED przekazaniem
    do `compute_position_summary` -- `ui/queries.get_user_positions_
    with_summaries(..., broker=...)`), nigdy nie miesza brokerów,
    użytkowników ani walut, nie wymaga FX. Trade Republic/Revolut
    zawsze widoczne; "Inny" tylko gdy użytkownik ma choć jedną realną
    transakcję OTHER (`get_brokers_in_use_for_user`)."""
    brokers_in_use = get_brokers_in_use_for_user(conn, user["user_id"])
    codes = list(_PLATFORM_FILTER_ALWAYS_AVAILABLE)
    if "OTHER" in brokers_in_use:
        codes.append("OTHER")
    labels = {"ALL": "Wszystkie", **{c: broker_label(c) for c in codes if c != "ALL"}}
    selected = st.selectbox(
        "Platforma", codes, format_func=lambda c: labels[c], key="platform_filter",
    )
    return selected


def _render_portfolio_tab(conn, user: dict) -> None:
    """Sekcja 6 specyfikacji: wewnątrz PORTFEL, filtr platformy, drugi
    poziom zakładek [PODSUMOWANIE][+ Dodaj transakcję] + DYNAMICZNE
    tickery posiadanych pozycji. Filtr platformy zawęża PODSUMOWANIE i
    zakładki pozycji; "+ Dodaj transakcję" celowo NIE jest filtrowana
    (`_render_add_transaction_tab` sama czyta pełną, nieprzefiltrowaną
    listę pozycji -- można dodać transakcję na innej platformie niż
    aktualnie przeglądana)."""
    platform_filter = _render_platform_filter(conn, user)
    broker = None if platform_filter == "ALL" else platform_filter
    positions_with_summaries = get_user_positions_with_summaries(conn, user["user_id"], broker=broker)

    inner_labels = ["PODSUMOWANIE", "+ Dodaj transakcję"] + [p["ticker"] for p, _ in positions_with_summaries]
    inner_tabs = st.tabs(inner_labels)

    with inner_tabs[0]:
        _render_portfolio_summary_tab(conn, positions_with_summaries, platform_filter=platform_filter)

    with inner_tabs[1]:
        _render_add_transaction_tab(conn, user)

    for tab, (position, summary) in zip(inner_tabs[2:], positions_with_summaries):
        with tab:
            _render_position_card(conn, dict(position), summary)


def main() -> None:
    st.set_page_config(page_title="Buffett Opportunity Scanner", layout="wide")
    # `init_db` (nie `connect`) -- `CREATE TABLE IF NOT EXISTS` + migracje
    # kolumn idempotentne, ten sam wzorzec co KAŻDE wywołanie w cli.py
    # (zero wyjątku dla UI). Realny błąd znaleziony przy weryfikacji
    # "czy aplikacja startuje bez błędów": plain `connect()` na zupełnie
    # świeżym pliku DB (bez tabel) wywalał `OperationalError: no such
    # table: users` -- `init_db` naprawia to bez ryzyka dla istniejących
    # danych (nigdy nie kasuje/nadpisuje, tylko dodaje brakujący schemat).
    conn = init_db(DB_PATH)

    st.title("Buffett Opportunity Scanner")
    _render_glossary()
    user = _render_user_picker(conn)

    latest_run_id, synthesis_rows = _render_synthesis_table(conn)

    if user is None:
        return

    st.markdown("---")
    _render_portfolio_bar(conn, user)
    st.markdown("---")

    # Sekcja 2 specyfikacji: PORTFEL jest stałą pierwszą zakładką,
    # zakładki kandydatów są DYNAMICZNE (z ostatniego właściwego skanu,
    # nigdy hard-coded CBOE/PAYX/...). Zagnieżdżone st.tabs() empirycznie
    # potwierdzone stabilne -- patrz KROK 0.
    tab_labels = ["PORTFEL"] + [r["ticker"] for r in synthesis_rows]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_portfolio_tab(conn, user)

    for tab, row in zip(tabs[1:], synthesis_rows):
        with tab:
            _render_candidate_card(conn, run_id=latest_run_id, cik=row["cik"], user_id=user["user_id"])


if __name__ == "__main__":
    main()
