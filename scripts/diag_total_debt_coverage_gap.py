"""DIAGNOSTYKA JEDNORAZOWA (Faza 5.3e, Decyzja właścicielki 2026-10-05,
po zmierzonym coverage=38.71% w v1.46): czy można stworzyć bezpieczny
Tier 2 dla `total_debt`, bez imputacji/zgadywania/double-countingu, który
odzyska część z 61.3% obserwacji oznaczonych `INSUFFICIENT_DATA`.

ZERO zmian w `buffett_scanner/total_debt.py` -- Tier 1
(CURRENT_PLUS_NONCURRENT, NOTES_PAYABLE_ONLY) pozostaje nietknięty,
żadna nowa logika nie jest tu wpisywana do produkcyjnego kodu. Wszystkie
warianty Tier 2 poniżej są PROTOTYPAMI tylko do pomiaru coverage --
decyzja o wdrożeniu należy do właścicielki po przeczytaniu wyników.

Czyta WYŁĄCZNIE z lokalnej kopii bazy (artefakt baseline-walk-forward,
już naprawiony universe_membership + realny backtest_coverage z 178
decision dates) -- zero sieci, zero zmiany danych źródłowych.

Do usunięcia po wykorzystaniu (razem z odpowiadającym workflow)."""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date as date_cls

sys.path.insert(0, ".")

from buffett_scanner.point_in_time import PitFact, extract_fact_history, value_as_of
from buffett_scanner.total_debt import compute_total_debt_as_of

DB_PATH = "baseline_walk_forward_result.db"

LTD_CURRENT = "LongTermDebtCurrent"
LTD_NONCURRENT = "LongTermDebtNoncurrent"
NOTES_PAYABLE = "NotesPayable"

REQUESTED_CURRENT_DEBT_TAGS = [
    "ShortTermBorrowings",
    "ShortTermDebt",
    "DebtCurrent",
    "CommercialPaper",
    "NotesPayableCurrent",
]

# Tagi już rozstrzygnięte w total_debt.py (Decyzja właścicielki 2026-10-04)
# -- nigdy nie wchodzą do puli "kandydatów" tej diagnostyki, żeby nie
# relitygować już podjętych decyzji.
EXCLUDE_FROM_POOL = {
    "LongTermDebt",
    LTD_CURRENT,
    LTD_NONCURRENT,
    NOTES_PAYABLE,
    "DebtInstrumentCarryingAmount",
    "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtAndCapitalLeaseObligationsCurrent",
    "LongTermDebtAndCapitalLeaseObligationsNoncurrent",
    "LongTermDebtAndFinanceLeaseObligations",
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "FinanceLeaseLiability",
    "FinanceLeaseLiabilityCurrent",
    "FinanceLeaseLiabilityNoncurrent",
}

KEYWORD_RE = re.compile(r"(Debt|Borrowing|Commercial|NotesPayable|LineOfCredit)", re.IGNORECASE)


def parse_date(s: str) -> date_cls:
    y, m, d = s.split("-")
    return date_cls(int(y), int(m), int(d))


def load_data(conn: sqlite3.Connection):
    decision_dates = [
        r["decision_date"]
        for r in conn.execute(
            "SELECT DISTINCT decision_date FROM backtest_coverage ORDER BY decision_date"
        ).fetchall()
    ]
    all_ciks = [
        r["cik"]
        for r in conn.execute(
            "SELECT DISTINCT cik FROM universe_membership WHERE index_name = 'SP500'"
        ).fetchall()
    ]
    company_facts_by_cik: dict[str, dict] = {}
    for cik in all_ciks:
        row = conn.execute(
            "SELECT raw_json FROM sec_company_facts_cache WHERE CAST(cik AS INTEGER) = CAST(? AS INTEGER)",
            (cik,),
        ).fetchone()
        if row is not None:
            company_facts_by_cik[cik] = json.loads(row["raw_json"])
    membership_rows = conn.execute(
        "SELECT cik, start_date, end_date FROM universe_membership WHERE index_name = 'SP500'"
    ).fetchall()
    return decision_dates, all_ciks, company_facts_by_cik, membership_rows


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    decision_dates, all_ciks, company_facts_by_cik, membership_rows = load_data(conn)

    print(f"Decision dates: {len(decision_dates)}")
    print(f"CIK w universe_membership: {len(all_ciks)}")
    print(f"CIK z SEC cache: {len(company_facts_by_cik)}/{len(all_ciks)}")

    def pit_universe_at(d: str) -> list[str]:
        return [
            r["cik"]
            for r in membership_rows
            if r["start_date"] <= d and (r["end_date"] is None or r["end_date"] > d)
        ]

    # ------------------------------------------------------------------
    # Discovery: tagi debt-podobne faktycznie występujące w danych
    # (Część C -- "inne rzeczywiście występujące standardowe tagi").
    # ------------------------------------------------------------------
    tag_cik_counts: Counter[str] = Counter()
    for cik, facts in company_facts_by_cik.items():
        try:
            usgaap_keys = list(facts["facts"]["us-gaap"].keys())
        except (KeyError, TypeError):
            continue
        for tag in usgaap_keys:
            if KEYWORD_RE.search(tag) and tag not in EXCLUDE_FROM_POOL:
                if extract_fact_history(facts, tag):
                    tag_cik_counts[tag] += 1

    print("\n" + "=" * 70)
    print("CZĘŚĆ C (discovery) -- tagi debt-podobne faktycznie występujące")
    print("w danych (>=5 CIK), z wyłączeniem już rozstrzygniętych w Tier 1")
    print("=" * 70)
    for tag, cnt in tag_cik_counts.most_common(40):
        if cnt >= 5:
            marker = " [REQUESTED przez właścicielkę]" if tag in REQUESTED_CURRENT_DEBT_TAGS else ""
            print(f"  {tag}: {cnt} CIK{marker}")

    candidate_pool = sorted(
        set(REQUESTED_CURRENT_DEBT_TAGS)
        | {t for t, c in tag_cik_counts.most_common(30) if c >= 5}
    )
    candidate_pool = [t for t in candidate_pool if t not in EXCLUDE_FROM_POOL]
    print(f"\nPula kandydatów do dalszej analizy (Część B/C): {candidate_pool}")

    # ------------------------------------------------------------------
    # Precompute: historie faktów per CIK dla tagów potrzebnych w analizie.
    # ------------------------------------------------------------------
    histories_by_cik: dict[str, dict[str, list[PitFact]]] = {}
    for cik, facts in company_facts_by_cik.items():
        h = {
            LTD_CURRENT: extract_fact_history(facts, LTD_CURRENT),
            LTD_NONCURRENT: extract_fact_history(facts, LTD_NONCURRENT),
            NOTES_PAYABLE: extract_fact_history(facts, NOTES_PAYABLE),
        }
        for tag in candidate_pool:
            h[tag] = extract_fact_history(facts, tag)
        histories_by_cik[cik] = h

    def ever_reported(cik: str, tag: str) -> bool:
        return bool(histories_by_cik[cik].get(tag))

    # ------------------------------------------------------------------
    # Główny przebieg: 76 292 obserwacje (PIT universe x decision_date).
    # Tier 1 (produkcyjna funkcja, nietknięta) rozstrzyga coverage/None;
    # dla obserwacji None klasyfikujemy przyczynę do: END_DATE_MISMATCH,
    # MISSING_ONE_COMPONENT (split current/noncurrent), albo
    # NO_FAMILY_NO_NOTES_PAYABLE (reszta -- poza zakresem A/B/C).
    # ------------------------------------------------------------------
    total_observations = 0
    tier1_covered: set[tuple[str, str]] = set()  # (cik, date) z total_debt != None

    end_mismatch_cases: list[dict] = []
    missing_current_cases: list[dict] = []  # NONCURRENT present / CURRENT missing
    missing_noncurrent_cases: list[dict] = []  # CURRENT present / NONCURRENT missing
    no_family_cases: list[tuple[str, str]] = []
    no_sec_cache = 0

    for d in decision_dates:
        pit_ciks = pit_universe_at(d)
        for cik in pit_ciks:
            facts = company_facts_by_cik.get(cik)
            if facts is None:
                no_sec_cache += 1
                continue
            total_observations += 1
            result = compute_total_debt_as_of(facts, d)
            if result.value is not None:
                tier1_covered.add((cik, d))
                continue

            h = histories_by_cik[cik]
            current = value_as_of(h[LTD_CURRENT], d)
            noncurrent = value_as_of(h[LTD_NONCURRENT], d)

            if current is not None and noncurrent is not None and current.end != noncurrent.end:
                end_mismatch_cases.append({"cik": cik, "date": d, "current": current, "noncurrent": noncurrent})
            elif current is not None and noncurrent is None:
                missing_noncurrent_cases.append({"cik": cik, "date": d, "present": current, "missing": "noncurrent"})
            elif noncurrent is not None and current is None:
                missing_current_cases.append({"cik": cik, "date": d, "present": noncurrent, "missing": "current"})
            else:
                no_family_cases.append((cik, d))

    total_none = len(end_mismatch_cases) + len(missing_current_cases) + len(missing_noncurrent_cases) + len(no_family_cases)
    print("\n" + "=" * 70)
    print("KONTROLA ZGODNOŚCI Z v1.46 (powinno być identyczne)")
    print("=" * 70)
    print(f"Suma obserwacji: {total_observations}")
    print(f"Tier 1 covered: {len(tier1_covered)} ({len(tier1_covered)/total_observations*100:.2f}%)")
    print(f"None (INSUFFICIENT_DATA): {total_none} ({total_none/total_observations*100:.2f}%)")
    print(f"  END_DATE_MISMATCH: {len(end_mismatch_cases)}")
    print(f"  MISSING current (noncurrent present): {len(missing_current_cases)}")
    print(f"  MISSING noncurrent (current present): {len(missing_noncurrent_cases)}")
    print(f"  NO_FAMILY_NO_NOTES_PAYABLE: {len(no_family_cases)}")

    # ==================================================================
    # CZĘŚĆ A -- END_DATE_MISMATCH
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ A -- END_DATE_MISMATCH (struktura problemu)")
    print("=" * 70)

    diffs = []
    buckets = Counter()
    recoverable_count = 0
    true_mismatch_count = 0
    recoverable_examples = []

    for case in end_mismatch_cases:
        c, n = case["current"], case["noncurrent"]
        diff = abs((parse_date(c.end) - parse_date(n.end)).days)
        diffs.append(diff)
        if diff == 0:
            buckets["0 dni"] += 1
        elif diff <= 7:
            buckets["1-7 dni"] += 1
        elif diff <= 31:
            buckets["8-31 dni"] += 1
        elif diff <= 100:
            buckets["32-100 dni"] += 1
        else:
            buckets[">100 dni"] += 1

        cik, d = case["cik"], case["date"]
        h = histories_by_cik[cik]
        eligible_current = [f for f in h[LTD_CURRENT] if f.filed <= d]
        eligible_noncurrent = [f for f in h[LTD_NONCURRENT] if f.filed <= d]
        ends_current = {f.end for f in eligible_current}
        ends_noncurrent = {f.end for f in eligible_noncurrent}
        common_ends = ends_current & ends_noncurrent
        if common_ends:
            recoverable_count += 1
            best_common_end = max(common_ends)
            staleness_days = (parse_date(d) - parse_date(best_common_end)).days
            case["recoverable"] = True
            case["best_common_end"] = best_common_end
            case["staleness_days"] = staleness_days
            if len(recoverable_examples) < 8:
                recoverable_examples.append((cik, d, c.end, n.end, best_common_end, staleness_days))
        else:
            true_mismatch_count += 1
            case["recoverable"] = False

    print(f"\nRozkład abs(end_date_current - end_date_noncurrent), {len(diffs)} przypadków:")
    for label in ("0 dni", "1-7 dni", "8-31 dni", "32-100 dni", ">100 dni"):
        cnt = buckets.get(label, 0)
        pct = cnt / len(diffs) * 100 if diffs else 0
        print(f"  {label}: {cnt} ({pct:.1f}%)")

    if diffs:
        qs = statistics.quantiles(diffs, n=100, method="inclusive")
        print("\nPercentyle różnicy (dni):")
        for p in (10, 25, 50, 75, 90, 95, 99):
            print(f"  p{p}: {qs[p-1]:.0f}")
        print(f"  max: {max(diffs)}")

    print(f"\n-- Test: czy wśród PIT-dostępnych faktów istnieje ALTERNATYWNA, zgodna")
    print("   para (current, noncurrent) o TYM SAMYM end, którą resolver nie wybrał,")
    print("   bo value_as_of() maksymalizuje (filed, end) NIEZALEŻNIE per tag? --")
    print(f"RECOVERABLE_VIA_JOINT_SELECTION (istnieje wspólny end w eligible): {recoverable_count} ({recoverable_count/len(diffs)*100:.1f}%)" if diffs else "n/a")
    print(f"TRUE_MISMATCH (żaden wspólny end nie istnieje nawet w pełnej eligible historii): {true_mismatch_count} ({true_mismatch_count/len(diffs)*100:.1f}%)" if diffs else "n/a")

    print("\nPrzykłady RECOVERABLE (cik, date, current.end wybrany, noncurrent.end wybrany, wspólny_end_istniejący, staleness_dni):")
    for ex in recoverable_examples:
        print(f"  {ex}")

    print("\nPełna provenance próbki z każdego bucketa (do 4 per bucket):")
    by_bucket_samples: dict[str, list] = defaultdict(list)
    for case in end_mismatch_cases:
        diff = abs((parse_date(case["current"].end) - parse_date(case["noncurrent"].end)).days)
        if diff == 0:
            label = "0 dni"
        elif diff <= 7:
            label = "1-7 dni"
        elif diff <= 31:
            label = "8-31 dni"
        elif diff <= 100:
            label = "32-100 dni"
        else:
            label = ">100 dni"
        if len(by_bucket_samples[label]) < 4:
            by_bucket_samples[label].append(case)

    for label, cases in by_bucket_samples.items():
        print(f"\n  -- Bucket {label} --")
        for case in cases:
            c, n = case["current"], case["noncurrent"]
            print(f"    CIK={case['cik']} date={case['date']} recoverable={case.get('recoverable')}")
            print(f"      LongTermDebtCurrent:    end={c.end} start={c.start} val={c.val} filed={c.filed} form={c.form} accn={c.accession_number} fy={c.fiscal_year} fp={c.fiscal_period}")
            print(f"      LongTermDebtNoncurrent: end={n.end} start={n.start} val={n.val} filed={n.filed} form={n.form} accn={n.accession_number} fy={n.fiscal_year} fp={n.fiscal_period}")

    # ==================================================================
    # CZĘŚĆ B -- MISSING ONE COMPONENT
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ B -- MISSING ONE COMPONENT")
    print("=" * 70)
    print(f"CURRENT present / NONCURRENT missing: {len(missing_noncurrent_cases)}")
    print(f"NONCURRENT present / CURRENT missing: {len(missing_current_cases)}")

    def scan_fillers(cases: list[dict], missing_label: str) -> Counter:
        filler_counts: Counter[str] = Counter()
        examples: dict[str, list] = defaultdict(list)
        for case in cases:
            cik, d = case["cik"], case["date"]
            instant = case["present"].end
            h = histories_by_cik[cik]
            for tag in candidate_pool:
                f = value_as_of(h[tag], d)
                if f is not None and f.end == instant:
                    filler_counts[tag] += 1
                    if len(examples[tag]) < 3:
                        examples[tag].append((cik, d, instant, case["present"].val, f.val))
        print(f"\n  Tagi znalezione dla TEGO SAMEGO balance-sheet instant ({missing_label}):")
        for tag, cnt in filler_counts.most_common():
            pct = cnt / len(cases) * 100 if cases else 0
            print(f"    {tag}: {cnt} przypadków ({pct:.1f}% z {missing_label})")
            for ex in examples[tag]:
                print(f"      przykład: CIK={ex[0]} date={ex[1]} instant={ex[2]} present_component={ex[3]} candidate_val={ex[4]}")
        return filler_counts

    fillers_for_missing_current = scan_fillers(missing_current_cases, "missing CURRENT")
    fillers_for_missing_noncurrent = scan_fillers(missing_noncurrent_cases, "missing NONCURRENT")

    # ==================================================================
    # CZĘŚĆ C -- relacja kandydatów do LongTermDebtCurrent/Noncurrent/Tier1
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ C -- relacja kandydatów short-term debt do Tier 1")
    print("=" * 70)

    tags_to_check = sorted(set(REQUESTED_CURRENT_DEBT_TAGS) | set(candidate_pool))
    exclusivity_report: dict[str, dict] = {}

    for tag in tags_to_check:
        ciks_reporting_tag = [cik for cik in company_facts_by_cik if ever_reported(cik, tag)]
        if not ciks_reporting_tag:
            continue

        co_occur_near_equal = 0
        co_occur_different = 0
        co_occur_ratios = []
        stands_alone_instants = 0
        exclusive_ciks = 0  # CIK, które NIGDY w całej historii nie raportowały LongTermDebtCurrent

        for cik in ciks_reporting_tag:
            h = histories_by_cik[cik]
            if not h[LTD_CURRENT]:
                exclusive_ciks += 1

            tag_facts_by_end: dict[str, PitFact] = {}
            for f in h[tag]:
                tag_facts_by_end[f.end] = f  # najpóźniejszy filed wygrywa (historia posortowana po filed)
            current_facts_by_end: dict[str, PitFact] = {}
            for f in h[LTD_CURRENT]:
                current_facts_by_end[f.end] = f

            for end, tf in tag_facts_by_end.items():
                cf = current_facts_by_end.get(end)
                if cf is None:
                    stands_alone_instants += 1
                    continue
                if cf.val == 0:
                    continue
                ratio = tf.val / cf.val
                co_occur_ratios.append(ratio)
                if 0.9 <= ratio <= 1.1:
                    co_occur_near_equal += 1
                else:
                    co_occur_different += 1

        exclusivity_report[tag] = {
            "cik_count": len(ciks_reporting_tag),
            "exclusive_ciks_never_report_ltd_current": exclusive_ciks,
            "stands_alone_instants": stands_alone_instants,
            "co_occur_near_equal_alias_suspicion": co_occur_near_equal,
            "co_occur_different_independent_candidate": co_occur_different,
            "ratio_median": statistics.median(co_occur_ratios) if co_occur_ratios else None,
            "ratio_max": max(co_occur_ratios) if co_occur_ratios else None,
        }

    for tag, rep in sorted(exclusivity_report.items(), key=lambda kv: -kv[1]["cik_count"]):
        print(f"\n  {tag}:")
        print(f"    CIK raportujące kiedykolwiek: {rep['cik_count']}")
        print(f"    z nich: NIGDY nie raportują LongTermDebtCurrent (exclusive use): {rep['exclusive_ciks_never_report_ltd_current']}")
        print(f"    Instants gdzie LongTermDebtCurrent NIEOBECNY dla tego end (stoi samo): {rep['stands_alone_instants']}")
        print(f"    Instants gdzie OBA obecne, near-equal (ratio 0.9-1.1, podejrzenie alias): {rep['co_occur_near_equal_alias_suspicion']}")
        print(f"    Instants gdzie OBA obecne, różne wartości (kandydat niezależny): {rep['co_occur_different_independent_candidate']}")
        if rep["ratio_median"] is not None:
            print(f"    ratio (tag/LongTermDebtCurrent) median={rep['ratio_median']:.3f} max={rep['ratio_max']:.3f}")

    # ==================================================================
    # CZĘŚĆ D -- proponowane warianty Tier 2 (wyłącznie z dowodem na danych)
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ D -- proponowane warianty Tier 2")
    print("=" * 70)

    # Tier 2a: JOINT_INSTANT_SELECTION -- tylko dla END_DATE_MISMATCH,
    # gdzie w PEŁNEJ eligible historii obu tagów istnieje WSPÓLNY end
    # (ta sama, realna data bilansowa), który resolver nie wybrał, bo
    # value_as_of() maksymalizuje (filed, end) NIEZALEŻNIE per tag.
    # To NIE jest tolerancja dat -- end musi być IDENTYCZNY, tylko wybór
    # pary jest łączny, nie per-tag. ZGŁASZAM to jako potencjalną zmianę
    # w resolverze (value_as_of/kompozyt), NIE wdrażam jej tutaj.
    print("\n  Tier 2a: CURRENT_PLUS_NONCURRENT_JOINT_INSTANT")
    print(f"    Źródło: END_DATE_MISMATCH, podzbiór RECOVERABLE_VIA_JOINT_SELECTION ({recoverable_count} obs.)")
    print("    Status: WYMAGA DECYZJI -- to jest zmiana w SPOSOBIE WYBORU faktu przez")
    print("    resolver (joint, nie per-tag), nie w definicji total_debt. Zgłaszam przed")
    print("    zmianą kodu, zgodnie z instrukcją.")

    # Tier 2c: NONCURRENT_PLUS_<TAG>_SYNONYM -- tylko dla CIK, które w
    # CAŁEJ historii NIGDY nie raportowały LongTermDebtCurrent (brak
    # ryzyka aliasu, bo nie ma z czym konkurować -- analogiczne do już
    # zaakceptowanego wzorca NOTES_PAYABLE_ONLY).
    tier2c_variants = {}
    for tag, cnt in fillers_for_missing_current.most_common():
        rep = exclusivity_report.get(tag, {})
        recoverable_via_exclusive = 0
        for case in missing_current_cases:
            cik = case["cik"]
            if not histories_by_cik[cik][LTD_CURRENT]:  # nigdy nie raportuje LTD current
                f = value_as_of(histories_by_cik[cik][tag], case["date"])
                if f is not None and f.end == case["present"].end:
                    recoverable_via_exclusive += 1
        if recoverable_via_exclusive > 0:
            tier2c_variants[tag] = recoverable_via_exclusive

    print("\n  Tier 2c: NONCURRENT_PLUS_<TAG>_SYNONYM (tylko CIK, które NIGDY w całej")
    print("  historii nie raportowały LongTermDebtCurrent -- brak ryzyka aliasu/double counting)")
    for tag, cnt in sorted(tier2c_variants.items(), key=lambda kv: -kv[1]):
        print(f"    NONCURRENT_PLUS_{tag}_SYNONYM: odzyskuje {cnt} obs. z missing-CURRENT ({cnt/len(missing_current_cases)*100:.1f}%)")

    if not tier2c_variants:
        print("    Brak tagu spełniającego kryterium exclusive-use z niezerowym odzyskiem.")

    print("\n  Tier 2b (mirror dla missing NONCURRENT): sprawdzone te same tagi --")
    recovered_b_mirror = 0
    for case in missing_noncurrent_cases:
        cik = case["cik"]
        if not histories_by_cik[cik][LTD_NONCURRENT]:
            for tag in candidate_pool:
                f = value_as_of(histories_by_cik[cik][tag], case["date"])
                if f is not None and f.end == case["present"].end:
                    recovered_b_mirror += 1
                    break
    print(f"    Żaden z {len(candidate_pool)} kandydatów nie jest typowym 'noncurrent' tagiem." if recovered_b_mirror == 0 else f"    Odzyskano {recovered_b_mirror} obs. (zobacz log szczegółowy wyżej).")

    # ==================================================================
    # CZĘŚĆ E -- symulacja coverage
    # ==================================================================
    print("\n" + "=" * 70)
    print("CZĘŚĆ E -- symulacja coverage (Tier 1 vs Tier 1 + Tier 2)")
    print("=" * 70)

    def apply_tier2a(covered: set[tuple[str, str]]) -> set[tuple[str, str]]:
        newly = set()
        for case in end_mismatch_cases:
            if case.get("recoverable"):
                newly.add((case["cik"], case["date"]))
        return covered | newly

    def apply_tier2c(covered: set[tuple[str, str]], tag: str) -> set[tuple[str, str]]:
        newly = set()
        for case in missing_current_cases:
            cik, d = case["cik"], case["date"]
            if not histories_by_cik[cik][LTD_CURRENT]:
                f = value_as_of(histories_by_cik[cik][tag], d)
                if f is not None and f.end == case["present"].end:
                    newly.add((cik, d))
        return covered | newly

    best_tier2c_tag = max(tier2c_variants, key=tier2c_variants.get) if tier2c_variants else None

    scenarios: dict[str, set[tuple[str, str]]] = {"Tier 1 only": set(tier1_covered)}
    scenarios["Tier 1 + Tier 2a (joint instant)"] = apply_tier2a(set(tier1_covered))
    if best_tier2c_tag:
        scenarios[f"Tier 1 + Tier 2c ({best_tier2c_tag})"] = apply_tier2c(set(tier1_covered), best_tier2c_tag)
        scenarios["Tier 1 + Tier 2a + Tier 2c"] = apply_tier2c(apply_tier2a(set(tier1_covered)), best_tier2c_tag)

    all_dates_ciks = []
    for d in decision_dates:
        for cik in pit_universe_at(d):
            if cik in company_facts_by_cik:
                all_dates_ciks.append((cik, d))

    for name, covered_set in scenarios.items():
        print(f"\n  -- {name} --")
        print(f"    Overall: {len(covered_set)}/{total_observations} ({len(covered_set)/total_observations*100:.2f}%)")
        by_year: dict[str, list[int]] = {}
        for cik, d in all_dates_ciks:
            year = d[:4]
            by_year.setdefault(year, [0, 0])
            by_year[year][0] += 1
            if (cik, d) in covered_set:
                by_year[year][1] += 1
        for year in sorted(by_year):
            obs, withval = by_year[year]
            pct = withval / obs * 100 if obs else 0
            print(f"      {year}: {withval}/{obs} ({pct:.1f}%)")
        cik_ever_covered = {cik for cik, d in covered_set}
        cik_ever_observed = {cik for cik, d in all_dates_ciks}
        print(f"    Per-CIK: {len(cik_ever_covered)}/{len(cik_ever_observed)} ({len(cik_ever_covered)/len(cik_ever_observed)*100:.1f}%) CIK z total_debt != None choć raz")

    tier2a_only = scenarios["Tier 1 + Tier 2a (joint instant)"] - set(tier1_covered)
    if best_tier2c_tag:
        tier2c_only = scenarios[f"Tier 1 + Tier 2c ({best_tier2c_tag})"] - set(tier1_covered)
        overlap = tier2a_only & tier2c_only
        print(f"\n  Overlap między Tier 2a i Tier 2c (powinno być 0 -- różne buckety źródłowe): {len(overlap)}")

    remaining_after_all = total_observations - len(scenarios[max(scenarios, key=lambda k: len(scenarios[k]))])
    print(f"\n  Obserwacje pozostające None po wszystkich proponowanych Tier 2: {remaining_after_all} ({remaining_after_all/total_observations*100:.2f}%)")


if __name__ == "__main__":
    main()
