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
    # Poniższe 5 potwierdzonych przez wielosygnałową weryfikację
    # (`ticker_rename_multi_signal_verification.py`, realny run
    # 2026-10-01, >=2/3 sygnałów: FMP get_company_profile + nazwa) ORAZ
    # dodatkowo niezależnie zweryfikowanych przez właścicielkę w
    # źródłach SEC (2026-10-01) — zatwierdzone do produkcyjnego wpięcia.
    # Kierunek dla każdego potwierdzony strukturalnie przez
    # `chronological_order()` (naprawione po znalezisku błędu FI/FISV).
    TickerRenameRecord(
        old_ticker="MMC",
        new_ticker="MRSH",
        cik="62709",
        zero_gap_date="2026-01-14",
        evidence=(
            "same-company+CIK: multi-signal 2/3 (fmp_profile_cik_match=True, fmp_name_match=True) "
            "— ticker_rename_multi_signal_verification.py, run 2026-10-01",
            "same-company+CIK+direction: niezależna weryfikacja właścicielki w źródłach SEC, 2026-10-01",
            "direction: strukturalne dir=UNRESOLVED_ENDS_RESOLVED_STARTS (MMC kończy się, MRSH zaczyna) "
            "— chronological_order(), bez odwrócenia",
        ),
        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
        validation_run_id="ticker-rename-multi-signal-2026-09-30",
    ),
    TickerRenameRecord(
        old_ticker="SATS",
        new_ticker="ECHO",
        cik="1415404",
        zero_gap_date="2026-06-24",
        evidence=(
            "same-company+CIK: multi-signal 2/3 (fmp_profile_cik_match=True, fmp_name_match=True) "
            "— ticker_rename_multi_signal_verification.py, run 2026-10-01",
            "same-company+CIK+direction: niezależna weryfikacja właścicielki w źródłach SEC, 2026-10-01",
            "direction: strukturalne dir=UNRESOLVED_ENDS_RESOLVED_STARTS (SATS kończy się, ECHO zaczyna) "
            "— chronological_order(), bez odwrócenia",
        ),
        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
        validation_run_id="ticker-rename-multi-signal-2026-09-30",
    ),
    TickerRenameRecord(
        old_ticker="BK",
        new_ticker="BNY",
        cik="1390777",
        zero_gap_date="2026-05-21",
        evidence=(
            "same-company+CIK: multi-signal 2/3 (fmp_profile_cik_match=True, fmp_name_match=True) "
            "— ticker_rename_multi_signal_verification.py, run 2026-10-01",
            "same-company+CIK+direction: niezależna weryfikacja właścicielki w źródłach SEC, 2026-10-01",
            "direction: strukturalne dir=UNRESOLVED_ENDS_RESOLVED_STARTS (BK kończy się, BNY zaczyna) "
            "— chronological_order(), bez odwrócenia",
        ),
        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
        validation_run_id="ticker-rename-multi-signal-2026-09-30",
    ),
    TickerRenameRecord(
        old_ticker="DISCK",
        new_ticker="WBD",
        cik="1437107",
        zero_gap_date="2022-04-11",
        evidence=(
            "same-company+CIK: multi-signal 2/3 (fmp_profile_cik_match=True, fmp_name_match=True) "
            "— ticker_rename_multi_signal_verification.py, run 2026-10-01",
            "same-company+CIK+direction: niezależna weryfikacja właścicielki w źródłach SEC, 2026-10-01; "
            "zgodne też z publicznie znaną historią (fuzja Discovery/WarnerMedia, kwiecień 2022)",
            "direction: strukturalne dir=UNRESOLVED_ENDS_RESOLVED_STARTS (DISCK kończy się, WBD zaczyna) "
            "— chronological_order(), bez odwrócenia",
        ),
        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
        validation_run_id="ticker-rename-multi-signal-2026-09-30",
    ),
    TickerRenameRecord(
        old_ticker="FISV",
        new_ticker="FI",
        cik="798354",
        zero_gap_date="2023-06-07",
        evidence=(
            "same-company+CIK: multi-signal 2/3 (fmp_profile_cik_match=True, fmp_name_match=True) "
            "— ticker_rename_multi_signal_verification.py, run 2026-10-01",
            "direction: BŁĄD ZNALEZIONY I NAPRAWIONY (2026-10-01) — pierwszy automatyczny wynik "
            "('FI -> FISV') miał odwrócony kierunek, bo kod mylił 'nierozwiązany wg dzisiejszej mapy SEC' "
            "z 'chronologicznie starszy'. Właścicielka niezależnie zweryfikowała w źródle pierwotnym: "
            "Fiserv notowany jako FISV na Nasdaq, przeniesiony na NYSE pod FI 2023-06-07 — "
            "FISV jest tickerem STARYM, FI NOWYM. Po naprawie (chronological_order(), strukturalne, "
            "dir=RESOLVED_ENDS_UNRESOLVED_STARTS) ponowny realny run zwrócił poprawnie 'FISV -> FI', "
            "zgodne z jej weryfikacją.",
        ),
        resolution_method="MULTI_SIGNAL_VERIFIED_V1",
        validation_run_id="ticker-rename-multi-signal-2026-09-30",
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


@dataclass(frozen=True)
class AllowlistApplicationResult:
    resolved: dict[str, str]
    resolved_via_curated_allowlist: dict[str, str]  # old_ticker -> nota provenance (do zapisu w DB)
    still_unresolved: tuple[str, ...]


def _provenance_note(record: TickerRenameRecord) -> str:
    return (
        f"{record.resolution_method} old={record.old_ticker} new={record.new_ticker} "
        f"run={record.validation_run_id} rule={record.validation_rule_version} "
        f"evidence={'; '.join(record.evidence)}"
    )


def apply_curated_allowlist(
    resolved: dict[str, str],
    unresolved: tuple[str, ...],
    allowlist: tuple[TickerRenameRecord, ...] = CURATED_ALLOWLIST_SEED,
) -> AllowlistApplicationResult:
    """Rozszerza wynik `universe_history.resolve_tickers_to_cik` o
    kuratorowaną allowlistę rename tickerów (Faza 5.3, LIMITED_BUT_HONEST,
    zatwierdzone przez właścicielkę 2026-10-01, po dwóch realnych Proof
    Run i naprawie błędu kierunku starego/nowego tickera).

    WAŻNE (błąd znaleziony i naprawiony 2026-10-01, ten sam rodzaj co w
    `chronological_order`): `old_ticker` NIE jest zawsze tickerem
    nierozwiązanym dziś — dla par z kierunkiem `RESOLVED_ENDS_
    UNRESOLVED_STARTS` (np. FISV->FI) to `new_ticker` jest nierozwiązany
    dziś, a `old_ticker` jest kotwicą. Dlatego funkcja sprawdza OBA
    kierunki: albo `old_ticker` jest nierozwiązany i `new_ticker` jest
    kotwicą (typowy przypadek), albo odwrotnie — `new_ticker` jest
    nierozwiązany i `old_ticker` jest kotwicą. W obu przypadkach kotwica
    MUSI rozwiązywać się DZIŚ do DOKŁADNIE tego CIK, co deklaruje rekord
    — krzyżowa kontrola z aktualnym stanem SEC, NIGDY ślepe zaufanie
    allowlistie. Jeśli żaden z dwóch wariantów nie jest spełniony (np.
    dane SEC się zmieniły od zatwierdzenia rekordu, albo oba tickery są
    dziś nierozwiązane — nie ma czego użyć jako kotwicy), rekord jest
    POMIJANY i ticker zostaje `CIK_UNRESOLVED` — zgodnie z zasadą „brak
    rozwiązania jest preferowany względem potencjalnie błędnego
    przypisania"."""
    new_resolved = dict(resolved)
    notes: dict[str, str] = {}
    unresolved_set = set(unresolved)
    for record in allowlist:
        if record.old_ticker in unresolved_set and resolved.get(record.new_ticker) == record.cik:
            ticker_to_add = record.old_ticker
        elif record.new_ticker in unresolved_set and resolved.get(record.old_ticker) == record.cik:
            ticker_to_add = record.new_ticker
        else:
            continue
        new_resolved[ticker_to_add] = record.cik
        notes[ticker_to_add] = _provenance_note(record)
    remaining_unresolved = tuple(sorted(unresolved_set - notes.keys()))
    return AllowlistApplicationResult(
        resolved=new_resolved, resolved_via_curated_allowlist=notes, still_unresolved=remaining_unresolved,
    )


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
