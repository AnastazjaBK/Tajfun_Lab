"""Kuratorowana allowlista rename tickerów + reguła wielosygnałowej
weryfikacji (Faza 5.3, zatwierdzone przez właściciela 2026-09-30, po
Proof Run zero-gap adjacency, który wykazał: sama strukturalna
jednoznaczność NIE jest wystarczającym dowodem ciągłości spółki — może
to być TICKER RENAME SAME COMPANY albo INDEX REPLACEMENT DIFFERENT
COMPANY (potwierdzone empirycznie: np. EA->FERG w tabeli "jednoznacznych"
kandydatów to najpewniej przypadkowa podmiana 1-do-1, nie rename).

Podejście LIMITED_BUT_HONEST: NIE implementujemy ogólnej automatycznej
reguły `INFERRED_VIA_ADJACENT_TICKER` stosowanej do wszystkich
kandydatów. Zamiast tego:
  (1) jawna, ręcznie kuratorowana allowlista (`CURATED_ALLOWLIST_SEED`)
      z 2 przypadkami potwierdzonymi wielokrotnie, niezależnie, w tej
      sesji (ANTM/ELV, FB/META),
  (2) reguła wielosygnałowej weryfikacji (`evaluate_rename_signals`) do
      PRÓBY rozszerzenia listy o kolejne przypadki — NIGDY na podstawie
      pojedynczego sygnału, zawsze z jawnym, audytowalnym śladem
      dowodowym. Przypadek bez wystarczającego potwierdzenia ZOSTAJE
      `CIK_UNRESOLVED` — brak rozwiązania jest preferowany względem
      potencjalnie błędnego przypisania (jawna decyzja właściciela).

Zero I/O w tym module poza stałą listą seed — pobieranie sygnałów
(FMP profile/event log, SEC formerNames) dzieje się w warstwie
providerów."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VALIDATION_RULE_VERSION = "ticker_rename_multi_signal_v1"


@dataclass(frozen=True)
class TickerRenameRecord:
    old_ticker: str
    new_ticker: str
    cik: str
    zero_gap_date: str
    evidence: tuple[str, ...]
    resolution_method: str  # "CURATED_MANUAL_ALLOWLIST_V1" | "MULTI_SIGNAL_VERIFIED_V1"
    validation_run_id: str
    validation_rule_version: str = VALIDATION_RULE_VERSION


# Ręcznie kuratorowane, na podstawie dowodów zebranych w tej sesji
# (FMP get_company_profile, FMP historical-sp500-constituent event log,
# SEC formerNames — patrz Proof Run 2026-09-30). Data zero-gap i CIK
# wzięte z realnych uruchomień `ticker_adjacency_proof_run`.
# Każdy rekord niesie TRZY oddzielne potwierdzenia (wymóg właścicielki,
# 2026-10-01, po znalezisku błędu kierunku FI/FISV): (1) same-company —
# że oba tickery to naprawdę ta sama spółka, (2) CIK — który konkretnie
# CIK, (3) direction/chronology — który ticker jest STARY (kończy się),
# który NOWY (zaczyna się). Dowód (1)+(2) NIE implikuje automatycznie
# (3) — to osobne pytanie, patrz `universe_ticker_adjacency.chronological_order`.
CURATED_ALLOWLIST_SEED: tuple[TickerRenameRecord, ...] = (
    TickerRenameRecord(
        old_ticker="ANTM",
        new_ticker="ELV",
        cik="1156039",
        zero_gap_date="2022-06-28",
        evidence=(
            "same-company+CIK: FMP get_company_profile('ANTM'/'ELV') — Proof Run 2026-09-30 (rename diagnosis)",
            "same-company+CIK: SEC formerNames: 'Anthem, Inc.' to=2022-06-24 (4 dni od zero-gap)",
            "direction: publicznie znana historia korporacyjna — Anthem Inc. (ANTM) formalnie zmieniła nazwę "
            "na Elevance Health, Inc. i ticker na ELV 2022-06-28; ANTM jest tickerem STARYM (kończy się), "
            "ELV NOWYM (zaczyna się) — zgodne ze strukturalnym kierunkiem w fja05680 "
            "(ANTM w koszyku UNIQUE_CANDIDATE od pierwszego Proof Run, bez odwrócenia)",
        ),
        resolution_method="CURATED_MANUAL_ALLOWLIST_V1",
        validation_run_id="seed-2026-09-30",
    ),
    TickerRenameRecord(
        old_ticker="FB",
        new_ticker="META",
        cik="1326801",
        zero_gap_date="2022-06-09",
        evidence=(
            "same-company+CIK: FMP get_company_profile('FB') — Proof Run 2026-09-30 (Price Data Proof Run #2)",
            "same-company+CIK: SEC formerNames: 'Facebook Inc' to=2021-10-27 (225 dni od zero-gap)",
            "direction: publicznie znana historia korporacyjna — Facebook Inc. (FB) formalnie zmieniła nazwę "
            "na Meta Platforms, Inc. (2021-10-28) i ticker na META (2022-06-09); FB jest tickerem STARYM "
            "(kończy się), META NOWYM (zaczyna się) — potwierdzone strukturalnie w realnym Proof Run 1 "
            "(dir=UNRESOLVED_ENDS_RESOLVED_STARTS dla kandydata FB->META, 2026-09-30)",
        ),
        resolution_method="CURATED_MANUAL_ALLOWLIST_V1",
        validation_run_id="seed-2026-09-30",
    ),
)


@dataclass(frozen=True)
class RenameSignals:
    """`None` = sygnał nie sprawdzony / brak danych (NIGDY traktowany
    jako potwierdzenie — tylko jako nieobecny). `False` w
    `fmp_profile_cik_match` oznacza JAWNĄ sprzeczność (FMP dziś kojarzy
    stary ticker z INNYM CIK — np. recykling, jak odkryte dla FB->ProShares
    ETF wcześniej w tej sesji) i unieważnia cały kandydat, niezależnie od
    pozostałych sygnałów."""

    fmp_profile_cik_match: bool | None
    fmp_name_match: bool | None
    former_name_match: bool | None


@dataclass(frozen=True)
class RenameVerdict:
    status: Literal["DISCONFIRMED", "INSUFFICIENT_EVIDENCE", "CONFIRMED_MULTI_SIGNAL"]
    positive_signal_count: int
    reasons: tuple[str, ...]


def evaluate_rename_signals(signals: RenameSignals) -> RenameVerdict:
    """Reguła wielosygnałowa: żaden pojedynczy sygnał nie wystarcza.
    `fmp_profile_cik_match is False` (JAWNA sprzeczność — FMP dziś
    kojarzy stary ticker z innym CIK) dyskwalifikuje kandydata
    natychmiast, niezależnie od pozostałych sygnałów — to bezpośredni
    dowód PRZECIW tożsamości, silniejszy niż jakakolwiek liczba
    sygnałów pośrednich. W przeciwnym razie: >=2 z 3 sygnałów `True`
    -> `CONFIRMED_MULTI_SIGNAL`; mniej -> `INSUFFICIENT_EVIDENCE`
    (pozostaje `CIK_UNRESOLVED`, NIGDY nie jest to traktowane jako
    odrzucenie kandydata — tylko jako brak wystarczającego dowodu)."""
    if signals.fmp_profile_cik_match is False:
        return RenameVerdict(
            status="DISCONFIRMED",
            positive_signal_count=0,
            reasons=("fmp_profile_cik_match=False: FMP dziś kojarzy stary ticker z INNYM CIK (prawdopodobny recykling)",),
        )

    checks = {
        "fmp_profile_cik_match": signals.fmp_profile_cik_match,
        "fmp_name_match": signals.fmp_name_match,
        "former_name_match": signals.former_name_match,
    }
    positive = tuple(name for name, value in checks.items() if value is True)
    count = len(positive)

    if count >= 2:
        return RenameVerdict(
            status="CONFIRMED_MULTI_SIGNAL",
            positive_signal_count=count,
            reasons=tuple(f"{name}=True" for name in positive),
        )
    return RenameVerdict(
        status="INSUFFICIENT_EVIDENCE",
        positive_signal_count=count,
        reasons=tuple(f"{name}=True" for name in positive) or ("brak żadnego pozytywnego sygnału",),
    )
