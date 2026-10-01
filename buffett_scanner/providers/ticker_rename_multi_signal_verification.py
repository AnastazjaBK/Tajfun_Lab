"""Próba rozszerzenia kuratorowanej allowlisty rename tickerów przez
wielosygnałową weryfikację (Faza 5.3, zatwierdzone przez właściciela
2026-09-30, podejście LIMITED_BUT_HONEST — patrz
`universe_ticker_rename_allowlist`). NIE jest to ogólna automatyczna
reguła — każdy kandydat oceniany jest przez >=2 niezależne sygnały
(FMP `get_company_profile`, FMP nazwa spółki z logu zdarzeń vs SEC/FMP
nazwa sąsiada, SEC `formerNames`), a jawna sprzeczność w
`get_company_profile` dyskwalifikuje kandydata natychmiast. Przypadek
bez wystarczającego potwierdzenia ZOSTAJE `CIK_UNRESOLVED`.

Ocena PER KANDYDAT (nie per ticker): ticker z wieloma kandydatami
(AMBIGUOUS_CONFLICTING_CIK w Części A Proof Run) może mieć jeden
kandydat potwierdzony sygnałami, a resztę odrzuconą — to naprawia
wadę architektoniczną znalezioną w poprzednim Proof Run (agregacja
per-ticker myliła jednoznaczną granicę wyjścia z niezwiązaną
niejednoznaczną granicą wejścia, np. dla FB/META).

WYŁĄCZNIE DIAGNOSTYCZNE — nie zapisuje nic do bazy, nie zmienia
`universe_membership` ani `resolve_tickers_to_cik`. To pomiar, nie
wdrożenie produkcyjne (decyzja o wpięciu wyniku do pipeline'u należy
do właściciela, po przejrzeniu tego raportu).

    python -m buffett_scanner.providers.ticker_rename_multi_signal_verification

Wymaga FMP_API_KEY i SEC_EDGAR_USER_AGENT."""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.fmp_sp500_events import collect_fmp_ticker_names, names_plausibly_match, parse_fmp_events
from buffett_scanner.providers.fmp import FMPClient, FMPError
from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError
from buffett_scanner.providers.sp500_history import Sp500HistoryError, fetch_components_csv
from buffett_scanner.universe_history import (
    build_ticker_intervals,
    distinct_tickers,
    parse_components_csv,
    resolve_tickers_to_cik,
    window_from_cutoff,
)
from buffett_scanner.universe_ticker_adjacency import (
    analyze_ticker_adjacency,
    chronological_order,
    former_name_corroborates_boundary,
)
from buffett_scanner.universe_ticker_rename_allowlist import (
    CURATED_ALLOWLIST_SEED,
    RenameSignals,
    TickerRenameRecord,
    evaluate_rename_signals,
)

FORMER_NAME_WIDE_TOLERANCE_DAYS = 400  # obejmuje z marginesem oba znane przypadki (4 i 225 dni)


def _normalize_cik(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit():
        return None
    return str(int(text))


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
        user_agent = config.sources.sec_edgar.resolve_user_agent()
    except RuntimeError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1
    cutoff = config.backtest.window_start
    run_id = "ticker-rename-multi-signal-2026-09-30"

    already_seeded_old_tickers = {r.old_ticker for r in CURATED_ALLOWLIST_SEED}

    print("== Krok 1: SEC company_tickers_full ==")
    with SecEdgarClient(user_agent) as sec_client:
        try:
            sec_full = sec_client.get_company_tickers_full()
        except SecEdgarError as exc:
            print(f"BŁĄD pobierania SEC company_tickers.json: {exc}", file=sys.stderr)
            return 1
        sec_ticker_map = {t: info["cik"] for t, info in sec_full.items()}
        sec_titles = {t: info["title"] for t, info in sec_full.items()}
        print(f"SEC: {len(sec_full)} tickerów.")

        print(f"\n== Krok 2: fja05680/sp500, okno {cutoff}+, rozwiązanie CIK ==")
        try:
            fja_csv = fetch_components_csv()
        except Sp500HistoryError as exc:
            print(f"BŁĄD pobierania fja05680/sp500: {exc}", file=sys.stderr)
            return 1
        fja_rows = parse_components_csv(fja_csv)
        fja_window = window_from_cutoff(fja_rows, cutoff)
        if not fja_window:
            print(f"BŁĄD: fja05680 nie ma żadnego wiersza <= {cutoff}.", file=sys.stderr)
            return 1
        fja_intervals = build_ticker_intervals(fja_window, cutoff_date=cutoff)
        fja_all_tickers = distinct_tickers(fja_window)
        resolution = resolve_tickers_to_cik(fja_all_tickers, sec_ticker_map)
        total_tickers = len(fja_all_tickers)
        print(
            f"fja05680: {total_tickers} tickerów w oknie, "
            f"rozwiązanych (baseline)={len(resolution.resolved)}, "
            f"CIK_UNRESOLVED (baseline)={len(resolution.unresolved)}"
        )

        print("\n== Krok 3: analiza strukturalna zero-gap adjacency (Część A) ==")
        analyses = analyze_ticker_adjacency(fja_intervals, resolution.resolved, resolution.unresolved)
        candidates_to_check = [
            a for a in analyses
            if a.status in ("UNIQUE_CANDIDATE", "AMBIGUOUS_CONFLICTING_CIK")
            and a.unresolved_ticker not in already_seeded_old_tickers
        ]
        total_candidate_pairs = sum(len(a.candidates) for a in candidates_to_check)
        print(
            f"Tickerów z >=1 kandydatem (poza już zaseedowanymi {sorted(already_seeded_old_tickers)}): "
            f"{len(candidates_to_check)}, łącznie par (ticker, kandydat) do oceny: {total_candidate_pairs}"
        )

        print("\n== Krok 4: FMP historical-sp500-constituent (pełny log, nazwy spółek) ==")
        with FMPClient(api_key) as fmp_client:
            path, raw_rows, attempts = fmp_client.get_historical_sp500_constituents()
            if path is None or not raw_rows:
                print("BŁĄD: historical-sp500-constituent niedostępny lub pusty.", file=sys.stderr)
                return 1
            fmp_events_all = parse_fmp_events(raw_rows)
            fmp_names_by_ticker = collect_fmp_ticker_names(fmp_events_all)
            print(f"FMP: {len(fmp_names_by_ticker)} tickerów z nazwą w pełnym logu.")

            print(
                f"\n== Krok 5: ocena sygnałów PER KANDYDAT "
                f"(tolerancja formerNames: {FORMER_NAME_WIDE_TOLERANCE_DAYS} dni, tylko do raportowania odległości) =="
            )
            former_names_cache: dict[str, list[dict]] = {}
            profile_cik_cache: dict[str, str | None] = {}

            per_ticker_confirmed: dict[str, list[tuple]] = {}
            per_ticker_all_verdicts: dict[str, list[tuple]] = {}

            for a in candidates_to_check:
                old_ticker = a.unresolved_ticker
                fmp_old_name = fmp_names_by_ticker.get(old_ticker, "")

                if old_ticker not in profile_cik_cache:
                    try:
                        profile = fmp_client.get_company_profile(old_ticker)
                        profile_cik_cache[old_ticker] = _normalize_cik(profile.get("cik"))
                    except FMPError:
                        profile_cik_cache[old_ticker] = None
                profile_cik = profile_cik_cache[old_ticker]

                for cand in a.candidates:
                    target_name = sec_titles.get(cand.adjacent_ticker) or fmp_names_by_ticker.get(cand.adjacent_ticker, "")
                    fmp_name_match = (
                        names_plausibly_match(fmp_old_name, target_name)
                        if fmp_old_name and target_name else None
                    )

                    if profile_cik is None:
                        fmp_profile_cik_match = None
                    else:
                        fmp_profile_cik_match = profile_cik == cand.adjacent_cik

                    if cand.adjacent_cik not in former_names_cache:
                        try:
                            former_names_cache[cand.adjacent_cik] = sec_client.get_former_names(cand.adjacent_cik)
                        except SecEdgarError:
                            former_names_cache[cand.adjacent_cik] = []
                    fnames = former_names_cache[cand.adjacent_cik]
                    if not fnames:
                        former_name_match = None
                    else:
                        match = former_name_corroborates_boundary(
                            fnames, cand.boundary_date, tolerance_days=FORMER_NAME_WIDE_TOLERANCE_DAYS
                        )
                        former_name_match = match is not None

                    signals = RenameSignals(
                        fmp_profile_cik_match=fmp_profile_cik_match,
                        fmp_name_match=fmp_name_match,
                        former_name_match=former_name_match,
                    )
                    verdict = evaluate_rename_signals(signals)
                    per_ticker_all_verdicts.setdefault(old_ticker, []).append((cand, signals, verdict))
                    if verdict.status == "CONFIRMED_MULTI_SIGNAL":
                        per_ticker_confirmed.setdefault(old_ticker, []).append((cand, signals, verdict))

        # Klasyfikacja PER TICKER w jednym przebiegu — jawnie rozłączne koszyki
        # (poprzednia wersja liczyła to przez odejmowanie zbiorów i gubiła
        # tickery z MIESZANYM wynikiem, np. część kandydatów DISCONFIRMED a
        # jeden INSUFFICIENT_EVIDENCE — wykryte w offline dry-run przed tym
        # uruchomieniem, patrz komentarz w teście/diagnozie).
        new_records: list[TickerRenameRecord] = []
        still_ambiguous_after_signals: list[str] = []
        all_disconfirmed_tickers: list[str] = []
        insufficient_tickers: list[str] = []

        for old_ticker in sorted(per_ticker_all_verdicts):
            entries = per_ticker_all_verdicts[old_ticker]
            confirmed = [(c, s, v) for c, s, v in entries if v.status == "CONFIRMED_MULTI_SIGNAL"]
            distinct_confirmed_ciks = {c.adjacent_cik for c, _, _ in confirmed}
            if len(distinct_confirmed_ciks) == 1:
                cand, signals, verdict = confirmed[0]
                # UWAGA (błąd znaleziony i zgłoszony przez właścicielkę dla
                # FI/FISV, 2026-10-01): old_ticker/new_ticker MUSZĄ pochodzić
                # z chronological_order (kierunek strukturalny w fja05680),
                # NIGDY z tego, który ticker jest `unresolved` wg dzisiejszej
                # mapy SEC — to dwie niezależne rzeczy. "unresolved" bywa
                # chronologicznie NOWSZYM tickerem (jak FI), jeśli SEC z
                # jakiegoś powodu rozwiązuje starszy symbol (FISV).
                true_old, true_new = chronological_order(old_ticker, cand)
                new_records.append(
                    TickerRenameRecord(
                        old_ticker=true_old,
                        new_ticker=true_new,
                        cik=cand.adjacent_cik,
                        zero_gap_date=cand.boundary_date,
                        evidence=verdict.reasons + (f"direction (fja05680, strukturalne)={cand.direction}",),
                        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
                        validation_run_id=run_id,
                    )
                )
            elif len(distinct_confirmed_ciks) > 1:
                still_ambiguous_after_signals.append(old_ticker)
            elif all(v.status == "DISCONFIRMED" for _, _, v in entries):
                all_disconfirmed_tickers.append(old_ticker)
            else:
                insufficient_tickers.append(old_ticker)

        print(
            "\n== Tabela: NOWO ODZYSKANE (dokładnie jeden potwierdzony kandydat na ticker; "
            "old_ticker/new_ticker wg STRUKTURALNEGO kierunku fja05680, NIE wg statusu "
            "resolved/unresolved w dzisiejszej mapie SEC) =="
        )
        for record in sorted(new_records, key=lambda r: r.old_ticker):
            print(
                f"  {record.old_ticker} -> {record.new_ticker} [{record.zero_gap_date}] "
                f"CIK={record.cik} | sygnały: {', '.join(record.evidence)}"
            )
        if not new_records:
            print("  (brak)")

        print("\n== Tabela: NADAL AMBIGUOUS mimo sygnałów (audit-safety guard) ==")
        for old_ticker in still_ambiguous_after_signals:
            confirmed_ciks = sorted({c.adjacent_cik for c, _, v in per_ticker_all_verdicts[old_ticker] if v.status == "CONFIRMED_MULTI_SIGNAL"})
            print(f"  {old_ticker}: wielosygnałowa weryfikacja potwierdziła >1 odrębny CIK ({confirmed_ciks}) — pozostaje CIK_UNRESOLVED.")
        if not still_ambiguous_after_signals:
            print("  (brak)")

        print("\n== Tabela: DISCONFIRMED (KAŻDY kandydat jawnie sprzeczny w FMP profile) ==")
        for old_ticker in all_disconfirmed_tickers:
            print(f"  {old_ticker}: profil FMP({old_ticker}).cik={profile_cik_cache.get(old_ticker)} nie pasuje do ŻADNEGO strukturalnego kandydata.")
        if not all_disconfirmed_tickers:
            print("  (brak)")

        print("\n== Tabela: NIEWYSTARCZAJĄCE DOWODY (pozostają CIK_UNRESOLVED) ==")
        for old_ticker in insufficient_tickers:
            best = max(per_ticker_all_verdicts[old_ticker], key=lambda e: e[2].positive_signal_count)
            cand, signals, verdict = best
            would_be_old, would_be_new = chronological_order(old_ticker, cand)
            print(
                f"  {old_ticker}: najlepszy kandydat {cand.adjacent_ticker} [{cand.boundary_date}] "
                f"CIK={cand.adjacent_cik}, {verdict.positive_signal_count}/3 sygnałów ({', '.join(verdict.reasons)}), "
                f"gdyby potwierdzony: {would_be_old} -> {would_be_new} (dir={cand.direction})"
            )
        if not insufficient_tickers:
            print("  (brak)")

        print("\n== Podsumowanie ==")
        seed_count = len(CURATED_ALLOWLIST_SEED)
        recovered_count = len(new_records)
        disconfirmed_count = len(all_disconfirmed_tickers)
        previously_resolved = len(resolution.resolved)
        new_total_resolved = previously_resolved + seed_count + recovered_count
        remaining_unresolved = len(resolution.unresolved) - seed_count - recovered_count
        print(f"Tickerów w oknie {cutoff}+: {total_tickers}")
        print(f"Rozwiązanych przed tą sesją (baseline, SEC-only): {previously_resolved}")
        print(f"Kuratorowana allowlista (seed, 2 przypadki): +{seed_count}")
        print(f"Nowo odzyskane przez wielosygnałową weryfikację: +{recovered_count}")
        print(f"NADAL AMBIGUOUS mimo sygnałów (audit-safety guard): {len(still_ambiguous_after_signals)}")
        print(f"DISCONFIRMED (jawna sprzeczność FMP profile): {disconfirmed_count}")
        print(f"NIEWYSTARCZAJĄCE DOWODY (pozostają CIK_UNRESOLVED): {len(insufficient_tickers)}")
        print(f"Łącznie pozostaje CIK_UNRESOLVED: {remaining_unresolved} z {total_tickers}")
        print(
            f"Finalny coverage (rozwiązanych/wszystkich w oknie): "
            f"{new_total_resolved}/{total_tickers} = {100 * new_total_resolved / total_tickers:.2f}%"
        )
        print(
            "\nUWAGA: to JEDNO przejście wielosygnałowej weryfikacji (mechanizmy: FMP get_company_profile, "
            "FMP nazwa z logu zdarzeń vs SEC/FMP nazwa sąsiada, SEC formerNames). Zgodnie z decyzją "
            "właściciela (2026-09-30) NIE próbujemy dalej ręcznie rozwiązywać pozostałych przypadków "
            "'za wszelką cenę' — jeśli pozostają one w większości historycznymi wyjściami z indeksu "
            "(przejęcia/bankructwa/delisting) lub przypadkami bez wystarczających niezależnych sygnałów, "
            "zostają jawnie CIK_UNRESOLVED (LIMITED_BUT_HONEST). Żaden zapis tutaj NIE został wpięty "
            "do produkcyjnego resolve_tickers_to_cik/universe_membership_build — to wymaga osobnej decyzji."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
