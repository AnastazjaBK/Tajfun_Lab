"""Live scan — dwustopniowy pipeline (Faza 6c, domknięcie MVP V0,
Decyzja właścicielki 2026-10-06, OPCJA 3).

Real-world znalezisko (2026-10-05/06, 3 kolejne full runy na aktualnym
rynku): 150-156/501 tickerów przechodzi decline/opportunity screening —
dużo więcej niż pierwszy mały test sugerował. Pełna analiza Claude dla
KAŻDEGO z nich jest operacyjnie/kosztowo niewykonalna w jednym
przebiegu (2 kolejne runy wyczerpały limit Anthropic w połowie, mimo
uzupełnienia kredytu; trzeci przekroczył nawet podniesiony 180->350 min
timeout, choć w końcu się domknął).

Rozwiązanie — NIE zmiana metodologii scoringu/wyceny/hard gates/decline
thresholds/prefiltra/PIT (wszystko to pozostaje zamrożone od Fazy 5.5) —
tylko dodanie WARSTWY OPERACYJNEJ między decline screening a Claude:

1. Deterministic ranking WSZYSTKICH kandydatów, którzy przeszli decline
   screening + prefilter — zero LLM, przez już istniejący, zamrożony
   `backtest_harness.compute_deterministic_score`/
   `evaluate_deterministic_hard_gates` (ten sam kod, który liczył
   `deterministic_score_pct` przez całą Fazę 5.3-5.6 kalibracji/
   holdoutu — żaden nowy "proxy score" nie jest tu tworzony).
2. Shortlist = TOP N po `deterministic_score_pct` (domyślnie N=20,
   wszyscy remisujący na granicy zachowani) — jawnie opisany jako
   OPERACYJNY/KOSZTOWY budget warstwy research, NIE nowy próg
   inwestycyjny i NIE element zwalidowanej metodologii alpha.
3. Pełna analiza Claude (jakościowa + anti-confirmation-bias + source
   assembly) WYŁĄCZNIE dla shortlisty, z resumable per-kandydat stanem
   (`PENDING`/`COMPLETE`/`FAILED` w `db.live_scan_candidates`) i cache
   po (cik, data_timestamp, config_version, prompt_schema_version,
   source_fingerprint) — identyczne wejście nigdy nie płaci za Claude
   dwa razy.
4. Finalny raport (0-N kandydatów) generowany TYLKO, gdy CAŁA shortlist
   ma status `COMPLETE` — w przeciwnym razie status
   `INCOMPLETE_LLM_ANALYSIS`, nigdy partial top-N.

Dobór TOP 20 nie jest nigdy strojony na podstawie tego, jakie spółki
się w nim znalazły w danym dniu (to by było post-hoc tuningiem) — jest
stałym, zadeklarowanym PRZED analizą parametrem operacyjnym."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from buffett_scanner.backtest_harness import DeterministicScoreResult
from buffett_scanner.scanner import PriceChangeSnapshot
from buffett_scanner.scoring import HardGateResult
from buffett_scanner.sources import VerifiedSource

DEFAULT_SHORTLIST_LIMIT = 20


@dataclass(frozen=True)
class RankedCandidate:
    """Jeden kandydat po decline screening + prefilter, z pełnym
    deterministycznym (zero-LLM) wynikiem — etap 1 pipeline'u."""

    ticker: str
    cik: str
    current_price: float
    decline_snapshot: PriceChangeSnapshot
    triggered_decline_flags: dict[str, bool]
    score: DeterministicScoreResult
    hard_gate_result: HardGateResult  # deterministyczny wariant (bez business_quality)


def _rank_key(candidate: RankedCandidate) -> tuple[int, float]:
    """`deterministic_score_pct=None` (brak JAKIEGOKOLWIEK dostępnego
    komponentu — w praktyce nie powinno się zdarzyć, bo safety/dividend
    są liczone dla każdego kandydata z fundamentals, ale nigdy nie
    zgadujemy) ląduje na końcu, nigdy w shortliście."""
    if candidate.score.deterministic_score_pct is not None:
        return (0, -candidate.score.deterministic_score_pct)
    return (1, 0.0)


def rank_all_candidates(candidates: list[RankedCandidate]) -> list[RankedCandidate]:
    """Pełny ranking — sortowanie, BEZ obcinania. Zapisywany/raportowany
    w całości (Decyzja właścicielki: "pokaż i zapisz pełny ranking
    wszystkich [...] przed wywołaniem Claude")."""
    return sorted(candidates, key=_rank_key)


def select_shortlist(
    ranked: list[RankedCandidate], *, limit: int = DEFAULT_SHORTLIST_LIMIT
) -> list[RankedCandidate]:
    """TOP `limit` po `deterministic_score_pct`, z zachowaniem WSZYSTKICH
    kandydatów remisujących z pozycją `limit` (ten sam `deterministic_
    score_pct`) — nigdy nie obcina remisu arbitralnie. Kandydaci bez
    policzalnego `deterministic_score_pct` nigdy nie wchodzą do
    shortlisty (brak sygnału do rankingu, nie "zero")."""
    scored = [c for c in ranked if c.score.deterministic_score_pct is not None]
    if len(scored) <= limit:
        return scored
    boundary = scored[limit - 1].score.deterministic_score_pct
    return [c for c in scored if c.score.deterministic_score_pct >= boundary]


def source_fingerprint(sources: list[VerifiedSource]) -> str:
    """Hash posortowanych `content_hash` zweryfikowanych źródeł — zmiana
    TREŚCI dokumentu (np. poprawiona 10-K) unieważnia cache; zmiana
    samego URL-a bez zmiany treści nie (bo `content_hash` liczony jest
    z pobranej treści, nie z URL-a — patrz `sources.py`)."""
    hashes = sorted(s.content_hash for s in sources if s.verified and s.content_hash)
    return hashlib.sha256("|".join(hashes).encode()).hexdigest()


def build_cache_key(
    *,
    cik: str,
    data_timestamp: str,
    config_version: str,
    prompt_schema_version: str,
    source_fingerprint: str,
) -> str:
    """Cache key dla pełnej analizy Claude — identyczne (cik,
    data_timestamp, config_version, prompt_schema_version,
    source_fingerprint) => identyczny wynik analizy, więc bezpiecznie
    można go ponownie wykorzystać bez nowego, kosztownego wywołania
    API. `data_timestamp` musi odzwierciedlać WSZYSTKIE dane wejściowe
    specyficzne dla tej daty (cena + fundamentals vintage), nie tylko
    `run_date` — patrz wołający (cli.py), który łączy run_date z PIT
    fundamentals filed_date/period_end_date."""
    raw = f"{cik}|{data_timestamp}|{config_version}|{prompt_schema_version}|{source_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()


def render_full_ranking_table(ranked: list[RankedCandidate]) -> str:
    """Pełny deterministyczny ranking — WSZYSCY kandydaci po decline
    screening + prefilter, nie tylko shortlist (Decyzja właścicielki:
    "Przed wywołaniem Claude pokaż i zapisz pełny ranking wszystkich")."""
    lines = [
        "| # | Ticker | score_pct | partial_score | safety | valuation | dividend | "
        "MoS (BASE) | hard_gate (deterministic) | decline trigger |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(ranked, start=1):
        s = c.score
        pct = f"{s.deterministic_score_pct:.2f}" if s.deterministic_score_pct is not None else "N/A"
        val = f"{s.valuation_score:.1f}" if s.valuation_score is not None else "N/A"
        mos = f"{s.margin_of_safety_base_pct:.1f}%" if s.margin_of_safety_base_pct is not None else "N/A"
        gate = "PASSED" if c.hard_gate_result.passed else "TRIGGERED"
        triggers = ", ".join(k for k, v in c.triggered_decline_flags.items() if v)
        lines.append(
            f"| {i} | {c.ticker} | {pct} | {s.deterministic_partial_score:.1f} | "
            f"{s.safety_score:.1f} | {val} | {s.dividend_score:.1f} | {mos} | {gate} | {triggers} |"
        )
    return "\n".join(lines)


def render_shortlist_status_table(rows) -> str:
    """`rows`: iterowalne obiektów z atrybutami `ticker`/`llm_status`/
    `llm_error` (np. `sqlite3.Row` z `live_scan_candidates`)."""
    lines = ["| Ticker | LLM status | Błąd |", "|---|---|---|"]
    for r in rows:
        error = r["llm_error"] if r["llm_error"] else ""
        lines.append(f"| {r['ticker']} | {r['llm_status']} | {error} |")
    return "\n".join(lines)
