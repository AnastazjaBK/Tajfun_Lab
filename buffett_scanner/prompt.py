"""Budowa promptu — Faza 3 (sekcja 15, punkt 3.2) + Faza 6 (anti-
confirmation-bias layer, instrukcje jawne).

Łączy deterministyczne wskaźniki (Faza 1: `fundamentals.compute_metrics`
+ `evaluate_prefilter`) i source packet (Faza 2: `sources.
build_sec_source_packet`) w kontekst dla Claude API.

Tylko ZWERYFIKOWANE źródła (`VerifiedSource.verified=True`) trafiają do
promptu — niezweryfikowane nie istnieją z perspektywy modelu (BLOCKER 3,
sekcja 9: "Claude cytuje wyłącznie po source_id z dostarczonej listy").
`source_id` przydzielany tu jest lokalny dla jednego wywołania promptu
(sekwencyjny `src-1`, `src-2`, ...) — nie jest to jeszcze DB PK
`analysis_sources.source_id`, którego jeszcze nie ma (patrz sources.py).

ANTI-CONFIRMATION-BIAS LAYER (Faza 6, domknięcie MVP V0): `AnalysisOutput`
(analysis_schema.py) wymusza KSZTAŁT pól bull_case/bear_case/
why_market_may_be_right/why_this_may_not_be_a_bargain/biggest_unknown/
thesis_invalidation/verification_items od początku Fazy 3 — ale sam
`output_format` Claude API gwarantuje tylko poprawny JSON, nie TREŚĆ.
Do Fazy 6 prompt nie instruował modelu, czym te pola są i czego od nich
wymagamy — gap zgłoszony i naprawiony w ramach GAP ANALYSIS V0 (nie
zmiana schematu, tylko instrukcji tekstowych). Wymóg: bear_case/
why_market_may_be_right/why_this_may_not_be_a_bargain muszą być tak
samo rygorystyczne jak bull_case — model ma AKTYWNIE argumentować
PRZECIW własnej tezie inwestycyjnej, nie tylko wymienić formalności.

BUGFIX V0 OUTPUT CONTRACT (Faza 6f, 2026-10-06): realny live run
(live-scan-2026-10-06T083825543395Z) ujawnił, że Claude wielokrotnie
pisał "nie dysponuję danymi o aktualnej cenie/Margin of Safety" —
PRAWDZIWE stwierdzenie, bo prompt do tej fazy NIGDY nie przekazywał
current_price/DCF/MoS/decline context modelowi, choć pipeline je już
policzył deterministycznie (Stage 1 ranking / `valuation.
compute_valuation`, zero LLM) PRZED wywołaniem Claude. Nowa sekcja
"KONTEKST CENY I WYCENY" niżej przekazuje te JUŻ POLICZONE wartości
jako dane — Claude ma z nich korzystać do oceny tezy/MoS, NIE
przeliczać DCF samodzielnie i NIE zgadywać innych wskaźników rynkowych
(P/E, EV/EBITDA itd.), których tu nie podano (dla nich prawidłowa
odpowiedź to jawne "niedostępne/unknown", nie zgadywanie).

ROOT CAUSE AUDIT — thesis_invalidation (Faza 6g, 2026-10-06): LIVE
VALIDATION TEST Fazy 6f (`validation-6f-2026-10-06T110249722378Z`, 5
historycznych finalistów) wykazał 4/5 FAILED z identycznym powodem —
`thesis_invalidation` semantycznie pusty na OBU próbach. Audyt
wykazał: (1) instrukcja tego pola opisywała tylko JAKOŚĆ treści
("konkretne, obserwowalne warunki..."), nigdy nie mówiła wprost "musisz
podać co najmniej jeden" — w przeciwieństwie do `why_market_may_be_
right`/`why_this_may_not_be_a_bargain`, które mają explicite "jeśli nie
widzisz dobrego argumentu, napisz to wprost" (fallback dla niskiej
pewności); (2) ogólna zasada anty-halucynacyjna ("jeśli czegoś nie
wiesz, napisz to wprost, zamiast zgadywać") prawdopodobnie była
nadinterpretowana dla tego pola jako "zwróć pustą listę". Naprawione
TYLKO instrukcją tekstową niżej (jawny wymóg >=1 + jawny fallback bez
wymyślonych progów liczbowych) — zero zmiany schematu JSON/typu pola.
"""

from __future__ import annotations

from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.sources import VerifiedSource
from buffett_scanner.valuation import ValuationResult

SCHEMA_VERSION = "1.0"

# Faza 6g ROOT CAUSE AUDIT -- wydzielone do stałej modułowej, żeby prompt
# głównej analizy (`build_analysis_prompt`) i prompt targeted repair
# (`build_thesis_invalidation_repair_prompt`, Faza 6h) zawsze używały
# IDENTYCZNEGO wymogu kardynalności dla `thesis_invalidation` -- nigdy
# dwóch niezależnie dryfujących kopii tej instrukcji.
_THESIS_INVALIDATION_REQUIREMENT = (
    "MUSISZ podać co najmniej JEDEN konkretny, obserwowalny warunek/zdarzenie, "
    "które obaliłoby tezę inwestycyjną (nie ogólne 'jeśli sytuacja się pogorszy') "
    "— np. trwała utrata moat, materialne pogorszenie FCF/marży, materializacja "
    "konkretnego ryzyka regulacyjnego, niepowodzenie kluczowej integracji/akwizycji, "
    "utrata istotnego klienta/udziału rynkowego, trwałe pogorszenie konkretnego "
    "wskaźnika operacyjnego. TO POLE NIE MOŻE BYĆ PUSTE — jeśli dostarczone dane nie "
    "uzasadniają konkretnego progu liczbowego, sformułuj warunek jakościowo (bez "
    "wymyślonego progu), ale podaj przynajmniej jeden."
)


def _price_valuation_context_lines(
    current_price: float | None,
    decline_snapshot: PriceChangeSnapshot | None,
    valuation_result: ValuationResult | None,
) -> list[str]:
    """Wspólny blok "KONTEKST CENY I WYCENY" (Faza 6f) -- współdzielony
    przez `build_analysis_prompt` i `build_thesis_invalidation_repair_prompt`
    (Faza 6h), żeby repair prompt dostawał TĘ SAMĄ reprezentację już
    policzonych wartości, bez duplikowania formatowania."""
    lines = [
        "KONTEKST CENY I WYCENY (policzone przez pipeline — kod, NIE Ty; użyj jako "
        "DANYCH do oceny tezy inwestycyjnej i Margin of Safety, NIE przeliczaj DCF "
        "samodzielnie):"
    ]
    if current_price is not None:
        lines.append(f"  Aktualna cena: {current_price}")
    else:
        lines.append("  Aktualna cena: NIEDOSTĘPNA w tym wywołaniu")

    if valuation_result is None:
        lines.append("  Wycena DCF: NIEDOSTĘPNA w tym wywołaniu")
    elif not valuation_result.implemented:
        lines.append(f"  Wycena DCF: NIEDOSTĘPNA w tym przebiegu — powód: {valuation_result.reason}")
    else:
        lines.append("  Wycena DCF (Owner Earnings proxy FCF), policzona przez kod:")
        for scenario in ("bear", "base", "bull"):
            sv = valuation_result.scenarios.get(scenario)
            if sv is None:
                continue
            mos = f"{sv.margin_of_safety_pct:.1f}%" if sv.margin_of_safety_pct is not None else "N/A"
            lines.append(
                f"    {scenario.upper()}: intrinsic value/akcję={sv.intrinsic_value_per_share:.2f}, "
                f"Margin of Safety={mos}"
            )

    if decline_snapshot is not None:
        # Każde pole `PriceChangeSnapshot` jest `None` (nie 0!), gdy historia
        # nie wystarcza na dane okno (zasada DATA UNAVAILABLE, scanner.py) —
        # formatowanie musi to respektować pole po polu, nigdy zgadywać 0.0.
        def _fmt_pct(value: float | None) -> str:
            return f"{value:.2f}%" if value is not None else "N/A"

        lines.append(
            "  Decline context (zmiana ceny, policzona przez kod): "
            f"1D={_fmt_pct(decline_snapshot.daily_pct)}, 1T={_fmt_pct(decline_snapshot.week_pct)}, "
            f"1M={_fmt_pct(decline_snapshot.month_pct)}, 1Q={_fmt_pct(decline_snapshot.quarter_pct)}, "
            f"YTD={_fmt_pct(decline_snapshot.ytd_pct)}, 1R={_fmt_pct(decline_snapshot.year_pct)}, "
            f"Drawdown od 52w high={_fmt_pct(decline_snapshot.drawdown_from_52w_high_pct)}, "
            "Wolumen względny="
            + (f"{decline_snapshot.relative_volume:.2f}"
               if decline_snapshot.relative_volume is not None else "N/A")
        )
    else:
        lines.append("  Decline context: NIEDOSTĘPNY w tym wywołaniu")

    lines.append(
        "  Powyższe dane są JUŻ POLICZONE przez pipeline, nie przez Ciebie — użyj ich "
        "jako faktów w analizie. NIE twierdź, że nie znasz ceny/Margin of Safety, jeśli "
        "są podane powyżej. Inne wskaźniki rynkowe (P/E, EV/EBITDA, konsensus analityków "
        "itd.), których tu NIE podano, rzeczywiście nie są dostępne — jeśli ich "
        "potrzebujesz, napisz to wprost jako ograniczenie/unknown, nie zgaduj ich wartości."
    )
    return lines


def build_analysis_prompt(
    *,
    ticker: str,
    metrics: dict[str, float | None],
    prefilter_flags: list[str],
    sources: list[VerifiedSource],
    current_price: float | None = None,
    decline_snapshot: PriceChangeSnapshot | None = None,
    valuation_result: ValuationResult | None = None,
) -> tuple[str, dict[str, VerifiedSource]]:
    """Zwraca (prompt, source_id_map). `source_id_map` mapuje
    lokalny source_id -> VerifiedSource, do przekazania jako
    `allowed_source_ids` przy walidacji odpowiedzi.

    `current_price`/`decline_snapshot`/`valuation_result` (Faza 6f,
    BUGFIX V0 OUTPUT CONTRACT) to wartości JUŻ POLICZONE deterministycznie
    przez pipeline (zero LLM) — przekazywane jako kontekst, NIE do
    przeliczenia przez model. `None` oznacza "rzeczywiście niedostępne w
    tym wywołaniu" (np. `score`/`cmd_analyze` bez pobranej ceny) — prompt
    to mówi wprost, nigdy nie udaje dostępności, której nie ma."""
    verified = [s for s in sources if s.verified]
    source_id_map = {f"src-{i + 1}": s for i, s in enumerate(verified)}

    lines = [
        f"Analizujesz spółkę {ticker} pod kątem podejścia value investing "
        "(Warren Buffett — jakość biznesu, moat, dyscyplina kapitałowa, "
        "margines bezpieczeństwa).",
        f'Pole "ticker" w wyjściu musi być dokładnie "{ticker}".',
        f'Pole "schema_version" w wyjściu musi być dokładnie "{SCHEMA_VERSION}".',
        "",
        "ZASADY (nieprzekraczalne):",
        "- Cytuj WYŁĄCZNIE źródła z listy 'ŹRÓDŁA DOSTĘPNE DO CYTOWANIA' poniżej, "
        "po ich source_id. Nie twórz własnych URL-i, nie powołuj się na dokumenty "
        "spoza tej listy, nawet jeśli je znasz skądinąd.",
        "- Pole `page` w verification_items wypełniaj TYLKO gdy źródło jest PDF "
        "z potwierdzoną paginacją. Żadne źródło poniżej nie jest — zostaw "
        "`page: null` dla wszystkich verification_items w tej analizie.",
        "- Jeśli czegoś nie wiesz z dostarczonych danych, napisz to wprost "
        "(niska pewność / biggest_unknown) zamiast zgadywać albo dopowiadać.",
        "",
        "ANTI-CONFIRMATION-BIAS (nieprzekraczalne — nie formalność, realny wymóg treści):",
        "- `bull_case`: konkretne, uzasadnione dowodami argumenty ZA tezą inwestycyjną.",
        "- `bear_case`: TAK SAMO rygorystyczne argumenty PRZECIW tezie — nie wolno "
        "ograniczyć się do ogólników ('ryzyko rynkowe'); szukaj najsilniejszego "
        "kontrargumentu, jaki uczciwy sceptyk by przedstawił.",
        "- `why_market_may_be_right`: napisz, dlaczego spadek ceny/wycena rynkowa MOŻE "
        "być racjonalna i uzasadniona, a nie błędem rynku do wykorzystania. Jeśli nie "
        "widzisz dobrego argumentu, napisz to wprost — nie wymyślaj słabego na siłę.",
        "- `why_this_may_not_be_a_bargain`: napisz, dlaczego obecna cena może NIE być "
        "okazją (np. wycena już uwzględnia realne ryzyko, margin of safety jest iluzoryczny "
        "z powodu niepewnych założeń).",
        f"- `thesis_invalidation`: {_THESIS_INVALIDATION_REQUIREMENT}",
        "- `biggest_unknown`: najważniejsza rzecz, której NIE wiesz z dostarczonych danych "
        "i źródeł, a która mogłaby zmienić ocenę.",
        "- Te pola mają równą wagę z bull_case — ocena, która nie potrafi uczciwie "
        "argumentować przeciw samej sobie, jest bezużyteczna.",
        "",
        "DETERMINISTYCZNE WSKAŹNIKI FINANSOWE (policzone przez kod, nie przez Ciebie):",
    ]
    for key, value in metrics.items():
        lines.append(f"  {key}: {value}")

    lines.append(
        f"  FLAGI PRE-FILTRA: {prefilter_flags}" if prefilter_flags
        else "  FLAGI PRE-FILTRA: brak (żaden próg nie przekroczony)"
    )

    lines.append("")
    lines.extend(_price_valuation_context_lines(current_price, decline_snapshot, valuation_result))

    lines.append("")
    lines.append("ŹRÓDŁA DOSTĘPNE DO CYTOWANIA:")
    if source_id_map:
        for source_id, s in source_id_map.items():
            lines.append(f"  [{source_id}] {s.title} — {s.issuer} — {s.url}")
    else:
        lines.append("  (brak — nie cytuj żadnego dokumentu, verification_items musi być puste)")

    return "\n".join(lines), source_id_map


def build_thesis_invalidation_repair_prompt(
    *,
    ticker: str,
    bull_case: list[str],
    bear_case: list[str],
    biggest_unknown: str,
    why_market_may_be_right: list[str],
    why_this_may_not_be_a_bargain: list[str],
    metrics: dict[str, float | None],
    current_price: float | None = None,
    decline_snapshot: PriceChangeSnapshot | None = None,
    valuation_result: ValuationResult | None = None,
) -> str:
    """Faza 6h (TARGETED FIELD REPAIR) -- minimalny prompt dla dokładnie
    JEDNEGO empirycznie potwierdzonego przypadku naprawy: cała reszta
    analizy jest poprawna, zawodzi WYŁĄCZNIE `thesis_invalidation`.
    Zwraca TYLKO tekst promptu (nie source_id_map) -- celowo NIE
    zawiera listy źródeł/cytowań (`sources`), ponieważ
    `thesis_invalidation` nie ma wymogu cytowania (patrz
    `ThesisInvalidationRepair` -- jedno pole, bez `verification_items`).
    Dostaje dokładnie ten kontekst, którego potrzebuje do sformułowania
    warunku falsyfikacji tezy -- istniejącą treść analizy (bull_case/
    bear_case/biggest_unknown/why_market_may_be_right/
    why_this_may_not_be_a_bargain) plus te same deterministyczne
    metrics/current_price/decline/valuation co prompt głównej analizy
    -- nigdy cały pierwotny prompt/source payload."""
    lines = [
        f"To jest TARGETED REPAIR dla spółki {ticker} -- naprawiasz WYŁĄCZNIE "
        "jedno pole istniejącej analizy value investing (Warren Buffett), "
        "`thesis_invalidation`, które w poprzedniej odpowiedzi było semantycznie "
        "puste. Reszta analizy (poniżej, jako kontekst) jest już gotowa i "
        "ZAAKCEPTOWANA -- nie zmieniasz jej, nie komentujesz jej, nie poprawiasz "
        "niczego innego. Zwróć WYŁĄCZNIE pole `thesis_invalidation`.",
        "",
        "ISTNIEJĄCA ANALIZA (kontekst, nie do zmiany):",
        f"  bull_case: {bull_case}",
        f"  bear_case: {bear_case}",
        f"  why_market_may_be_right: {why_market_may_be_right}",
        f"  why_this_may_not_be_a_bargain: {why_this_may_not_be_a_bargain}",
        f"  biggest_unknown: {biggest_unknown}",
        "",
        "DETERMINISTYCZNE WSKAŹNIKI FINANSOWE (policzone przez kod, nie przez Ciebie):",
    ]
    for key, value in metrics.items():
        lines.append(f"  {key}: {value}")

    lines.append("")
    lines.extend(_price_valuation_context_lines(current_price, decline_snapshot, valuation_result))

    lines.append("")
    lines.append("ZADANIE:")
    lines.append(f"- `thesis_invalidation`: {_THESIS_INVALIDATION_REQUIREMENT}")
    lines.append(
        "- Warunek MUSI wynikać z powyższej istniejącej analizy i danych -- nie "
        "wymyślaj nowych faktów, które nie są obecne w kontekście powyżej, i nie "
        "wymyślaj arbitralnych progów liczbowych, których dane nie uzasadniają."
    )
    lines.append(
        '- Pole "ticker" nie istnieje w tym schemacie -- zwróć wyłącznie '
        '"thesis_invalidation" jako listę co najmniej jednego konkretnego ciągu tekstowego.'
    )

    return "\n".join(lines)
