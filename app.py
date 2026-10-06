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

import os

import streamlit as st

from buffett_scanner.db import connect, create_user, get_latest_user_decision, get_users, insert_user_decision
from buffett_scanner.ui.labels import (
    METHODOLOGY_DISCLAIMER,
    analysis_status_label,
    decision_status_label,
    decline_flags_label,
)

# Sekcja 16 specyfikacji: mapowanie przycisków UI na istniejący enum
# `user_decisions.status` (sekcja 1.1/16 design review) -- NIE
# wymyślamy nowego modelu statusów.
_DECISION_BUTTONS = (
    ("REJECT", "Odrzucam"),
    ("WATCH", "Obserwuję"),
    ("SNOOZE", "Sprawdzam"),
    ("BOUGHT", "Kupiłam/Kupiłem"),
)
from buffett_scanner.ui.portfolio import compute_portfolio_bar_summary
from buffett_scanner.ui.queries import (
    get_candidate_detail,
    get_latest_live_scan_run,
    get_review_needed_count,
    get_synthesis_rows,
    get_user_positions_with_summaries,
)

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
    pozycji tutaj."""
    positions_with_summaries = get_user_positions_with_summaries(conn, user["user_id"])
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


def main() -> None:
    st.set_page_config(page_title="Buffett Opportunity Scanner", layout="wide")
    conn = connect(DB_PATH)

    st.title("Buffett Opportunity Scanner")
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
        st.write("Szczegóły portfela — KROK 6 (w budowie).")

    for tab, row in zip(tabs[1:], synthesis_rows):
        with tab:
            _render_candidate_card(conn, run_id=latest_run_id, cik=row["cik"], user_id=user["user_id"])


if __name__ == "__main__":
    main()
