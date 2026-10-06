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

from buffett_scanner.db import connect, create_user, get_users
from buffett_scanner.ui.labels import (
    METHODOLOGY_DISCLAIMER,
    analysis_status_label,
    decline_flags_label,
)
from buffett_scanner.ui.portfolio import compute_portfolio_bar_summary
from buffett_scanner.ui.queries import (
    get_latest_live_scan_run,
    get_review_needed_count,
    get_synthesis_rows,
    get_user_positions_with_summaries,
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


def _render_synthesis_table(conn) -> list[dict]:
    """Sekcja 4 specyfikacji: tabela SYNTEZY ostatniego WŁAŚCIWEGO
    live-scanu (nigdy walidacji technicznej -- patrz `ui/queries.
    get_latest_live_scan_run`). FAILED to status RAPORTU jakościowego,
    nie ocena spółki -- deterministyczne dane/cena/wycena pozostają
    widoczne niezależnie od statusu analizy LLM."""
    run = get_latest_live_scan_run(conn)
    if run is None:
        st.info("Brak jeszcze ukończonego live-scan rynku.")
        return []

    st.subheader(f"Co scanner znalazł — skan z {run['run_date']}")
    rows = get_synthesis_rows(conn, run["run_id"])
    if not rows:
        st.info("Ten skan nie wytypował żadnych kandydatów (to prawidłowy wynik).")
        return rows

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
    return rows


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


def main() -> None:
    st.set_page_config(page_title="Buffett Opportunity Scanner", layout="wide")
    conn = connect(DB_PATH)

    st.title("Buffett Opportunity Scanner")
    user = _render_user_picker(conn)

    synthesis_rows = _render_synthesis_table(conn)

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
            st.write(f"Karta kandydata {row['ticker']} — KROK 4 (w budowie).")


if __name__ == "__main__":
    main()
