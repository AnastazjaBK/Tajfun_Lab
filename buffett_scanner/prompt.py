"""Budowa promptu — Faza 3 (sekcja 15, punkt 3.2).

Łączy deterministyczne wskaźniki (Faza 1: `fundamentals.compute_metrics`
+ `evaluate_prefilter`) i source packet (Faza 2: `sources.
build_sec_source_packet`) w kontekst dla Claude API.

Tylko ZWERYFIKOWANE źródła (`VerifiedSource.verified=True`) trafiają do
promptu — niezweryfikowane nie istnieją z perspektywy modelu (BLOCKER 3,
sekcja 9: "Claude cytuje wyłącznie po source_id z dostarczonej listy").
`source_id` przydzielany tu jest lokalny dla jednego wywołania promptu
(sekwencyjny `src-1`, `src-2`, ...) — nie jest to jeszcze DB PK
`analysis_sources.source_id`, którego jeszcze nie ma (patrz sources.py).
"""

from __future__ import annotations

from buffett_scanner.sources import VerifiedSource

SCHEMA_VERSION = "1.0"


def build_analysis_prompt(
    *,
    ticker: str,
    metrics: dict[str, float | None],
    prefilter_flags: list[str],
    sources: list[VerifiedSource],
) -> tuple[str, dict[str, VerifiedSource]]:
    """Zwraca (prompt, source_id_map). `source_id_map` mapuje
    lokalny source_id -> VerifiedSource, do przekazania jako
    `allowed_source_ids` przy walidacji odpowiedzi."""
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
        "DETERMINISTYCZNE WSKAŹNIKI FINANSOWE (policzone przez kod, nie przez Ciebie):",
    ]
    for key, value in metrics.items():
        lines.append(f"  {key}: {value}")

    lines.append(
        f"  FLAGI PRE-FILTRA: {prefilter_flags}" if prefilter_flags
        else "  FLAGI PRE-FILTRA: brak (żaden próg nie przekroczony)"
    )

    lines.append("")
    lines.append("ŹRÓDŁA DOSTĘPNE DO CYTOWANIA:")
    if source_id_map:
        for source_id, s in source_id_map.items():
            lines.append(f"  [{source_id}] {s.title} — {s.issuer} — {s.url}")
    else:
        lines.append("  (brak — nie cytuj żadnego dokumentu, verification_items musi być puste)")

    return "\n".join(lines), source_id_map
