"""SIC point-in-time z nagłówków raportów rocznych EDGAR (decyzja
właścicielki 2026-10-24, punkt 13).

SEC Submissions API podaje wyłącznie BIEŻĄCY kod SIC. Backtest klasyfikował
nim wszystkie daty 2012-2021 (wiedza z przyszłości: np. AMT, CCI, EQIX,
IRM, SBAC stały się REIT-ami w trakcie okna). Nagłówek każdego zgłoszenia
zachowuje SIC z dnia złożenia -- sprawdzone w diagnostyce 2026-10-24
(run 40098265387): najnowszy nagłówek zgodny z bieżącym SIC u 610/610
spółek, a 33 spółki mają w starszych nagłówkach inny kod.

Reguła: profil w dacie decyzji = SIC z najnowszego 10-K złożonego najpóźniej
w tej dacie. Brak takiego nagłówka -> NIEZNANY (spółka poza ocenianym
rankingiem tej daty), nigdy bieżący SIC ani GENERAL.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from buffett_scanner.sector_classification import UNKNOWN_PROFILE, classify_sic_to_sector_profile

ANNUAL_FORMS = ("10-K", "10-K405", "10-KT")
HEADER_OK = "OK"

_CIK_RE = re.compile(r"(?:<CIK>|CENTRAL INDEX KEY:)\s*0*(\d+)")
_SIC_RE = re.compile(r"(?:<ASSIGNED-SIC>\s*(\d{3,4})|STANDARD INDUSTRIAL CLASSIFICATION:[^\n\[]*\[(\d{3,4})\])")


def norm_cik(cik) -> str:
    return str(int(str(cik)))


def parse_header_sic(text: str, cik: str) -> tuple[str | None, str]:
    """SIC filera o danym CIK z nagłówka zgłoszenia (format SGML .hdr.sgml
    albo tekstowy). Każdy kod SIC przypisany do najbliższego wcześniejszego
    CIK w nagłówku. Zwraca (sic, status)."""
    text = html.unescape(text)
    ciks = [(m.start(), m.group(1)) for m in _CIK_RE.finditer(text)]
    sics = [(m.start(), m.group(1) or m.group(2)) for m in _SIC_RE.finditer(text)]
    if not sics:
        return None, "BRAK_SIC_W_NAGLOWKU"
    target = norm_cik(cik)
    for pos, sic in sics:
        owner = None
        for cpos, c in ciks:
            if cpos < pos:
                owner = c
        if owner == target:
            return sic, HEADER_OK
    return None, "BRAK_DOPASOWANIA_CIK"


def annual_filings(submissions_pages: list[dict]) -> list[dict]:
    """Raporty roczne z głównej strony Submissions API (`filings.recent`)
    i stron archiwalnych (kolumny na najwyższym poziomie), bez duplikatów,
    chronologicznie. Korekty (10-K/A) pominięte."""
    out, seen = [], set()
    for page in submissions_pages:
        cols = page.get("filings", {}).get("recent", page)
        for i, form in enumerate(cols.get("form", [])):
            if form not in ANNUAL_FORMS:
                continue
            acc = cols["accessionNumber"][i]
            if acc in seen:
                continue
            seen.add(acc)
            out.append({"form": form, "accession": acc, "filing_date": cols["filingDate"][i]})
    return sorted(out, key=lambda f: f["filing_date"])


def pit_sic(headers: list[dict], decision_date: str) -> str | None | bool:
    """SIC z najnowszego odczytanego nagłówka 10-K złożonego najpóźniej w
    dniu decyzji. False = brak takiego nagłówka."""
    best = None
    for h in headers:
        if h["filing_date"] <= decision_date and h["status"] == HEADER_OK:
            if best is None or h["filing_date"] > best["filing_date"]:
                best = h
    return False if best is None else best["sic"]


@dataclass(frozen=True)
class PointInTimeProfiles:
    """Profil sektorowy spółki w dacie decyzji z historii nagłówków."""

    headers_by_cik: dict[str, list[dict]]

    def profile_at(self, cik: str, decision_date: str) -> str:
        sic = pit_sic(self.headers_by_cik.get(norm_cik(cik), []), decision_date)
        if sic is False:
            return UNKNOWN_PROFILE
        return classify_sic_to_sector_profile(sic)


def fetch_sic_history(client, cik: str, *, filed_from: str) -> tuple[list[dict], list[str]]:
    """Nagłówki 10-K spółki złożone od `filed_from` (klient: `SecEdgarClient`).
    Zwraca (wiersze historii, błędy). Wiersz: filing_date, accession, form,
    sic, status."""
    pages, errors = client.get_submissions_pages(cik, filed_from=filed_from)
    rows = []
    for f in annual_filings(pages):
        if f["filing_date"] < filed_from:
            continue
        text, how = client.get_filing_header(cik, f["accession"])
        if text is None:
            rows.append({**f, "sic": None, "status": f"BRAK_NAGLOWKA {how}"})
            continue
        sic, status = parse_header_sic(text, cik)
        rows.append({**f, "sic": sic, "status": status})
    return rows, errors
