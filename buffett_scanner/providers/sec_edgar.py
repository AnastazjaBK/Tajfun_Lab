"""Klient SEC EDGAR — Faza 2, warstwa źródeł (sekcja 9/10 design review).

SEC EDGAR to bezpłatne, nie wymagające klucza API archiwum dokumentów
(10-K/10-Q/8-K/...). Wymaga deklarowanego nagłówka User-Agent z danymi
kontaktowymi (nazwa aplikacji + e-mail) — to udokumentowany wymóg SEC,
nie opcja (https://www.sec.gov/os/webmaster-faq#developers). Limit
10 żądań/s, egzekwowany throttlingiem poniżej.

Ta warstwa jest jedynym miejscem w systemie, które może stwierdzić
"to źródło istnieje i ma tę treść" (BLOCKER 3, sekcja 9): URL budowany
deterministycznie z danych Submissions API, dokument faktycznie
pobierany (HTTP 200) i hashowany (SHA-256) w trakcie danego
uruchomienia — nigdy na podstawie samego twierdzenia LLM.
"""

from __future__ import annotations

import hashlib
import time

import httpx

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_TIMEOUT = 15.0


class SecEdgarError(RuntimeError):
    pass


def _pad_cik(cik: str) -> str:
    return cik.zfill(10)


class SecEdgarClient:
    def __init__(self, user_agent: str, *, min_interval_s: float = 0.11):
        # SEC limit: 10 req/s. 0.11s > 0.10s zostawia margines na jitter.
        if not user_agent or "@" not in user_agent:
            raise SecEdgarError(
                "User-Agent SEC EDGAR musi zawierać dane kontaktowe (np. "
                "'Tajfun Lab kontakt@example.com') — to wymóg SEC, nie opcja."
            )
        self._user_agent = user_agent
        self._min_interval_s = min_interval_s
        self._last_call_ts = 0.0
        self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, headers={"User-Agent": user_agent})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SecEdgarClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self._min_interval_s:
            time.sleep(self._min_interval_s - elapsed)

    def _get(self, url: str) -> httpx.Response:
        self._throttle()
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise SecEdgarError(f"Błąd sieci przy wywołaniu SEC EDGAR ({url}): {exc}") from exc
        finally:
            self._last_call_ts = time.monotonic()
        return resp

    def get_filings(self, cik: str) -> list[dict]:
        """Lista filingów spółki z EDGAR Submissions API. Zwraca listę
        słowników: form, accession_number, filing_date, report_date,
        primary_document. Wiersz z brakującym polem krytycznym (form/
        accession_number/filing_date/primary_document) jest pomijany —
        nigdy nie zgadujemy brakującej wartości."""
        url = SUBMISSIONS_URL.format(cik10=_pad_cik(cik))
        resp = self._get(url)
        if resp.status_code != 200:
            raise SecEdgarError(
                f"SEC EDGAR zwrócił status {resp.status_code} dla submissions CIK={cik}."
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise SecEdgarError(f"SEC EDGAR zwrócił niepoprawny JSON dla CIK={cik}") from exc

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])

        n = len(forms)
        filings = []
        for i in range(n):
            if i >= len(accession_numbers) or i >= len(filing_dates) or i >= len(primary_documents):
                continue
            filings.append(
                {
                    "form": forms[i],
                    "accession_number": accession_numbers[i],
                    "filing_date": filing_dates[i],
                    "report_date": report_dates[i] if i < len(report_dates) else None,
                    "primary_document": primary_documents[i],
                }
            )
        return filings

    @staticmethod
    def build_filing_url(cik: str, accession_number: str, primary_document: str) -> str:
        """Deterministyczny URL do dokumentu SEC EDGAR (sekcja 10 design
        review: "Link buduje kod, nie LLM")."""
        accession_no_dashes = accession_number.replace("-", "")
        cik_no_leading_zeros = str(int(cik))
        return f"{ARCHIVES_BASE_URL}/{cik_no_leading_zeros}/{accession_no_dashes}/{primary_document}"

    def fetch_and_hash_document(self, url: str) -> dict:
        """Faktycznie pobiera dokument i liczy SHA-256 treści — jedyny
        sposób, w jaki system stwierdza, że źródło istnieje i ma daną
        treść (BLOCKER 3). Zwraca {url, content_hash, content_length}."""
        resp = self._get(url)
        if resp.status_code != 200:
            raise SecEdgarError(f"SEC EDGAR zwrócił status {resp.status_code} dla dokumentu {url}.")
        content = resp.content
        return {
            "url": url,
            "content_hash": hashlib.sha256(content).hexdigest(),
            "content_length": len(content),
        }

    def get_company_facts(self, cik: str) -> dict:
        """Pełny zestaw faktów XBRL spółki (company-facts API). Każdy
        fakt ma pole `filed` (data faktycznego złożenia) — podstawa
        warstwy point-in-time (BLOCKER 1, sekcja 13 design review,
        Faza 5.1): pozwala odtworzyć "jaka była ostatnia wartość X
        *filed* na dzień <= D" zamiast dzisiejszego, skorygowanego
        widoku, jaki dają komercyjni dostawcy danych (FMP itp.)."""
        url = COMPANY_FACTS_URL.format(cik10=_pad_cik(cik))
        resp = self._get(url)
        if resp.status_code != 200:
            raise SecEdgarError(
                f"SEC EDGAR zwrócił status {resp.status_code} dla company facts CIK={cik}."
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise SecEdgarError(f"SEC EDGAR zwrócił niepoprawny JSON dla company facts CIK={cik}") from exc

    def get_company_tickers(self) -> dict[str, str]:
        """Aktualne (DZISIEJSZE, nie point-in-time) mapowanie ticker->CIK
        z `company_tickers.json` — podstawa pierwszego przebiegu
        diagnostycznego rozwiązywania tożsamości w Fazie 5.2
        (`universe_history.resolve_tickers_to_cik`). Zwraca `{ticker:
        cik_jako_string}`, cik BEZ wiodących zer (jak w reszcie
        projektu). Surowy JSON to `{"0": {"cik_str": ..., "ticker":
        ..., "title": ...}, "1": {...}, ...}` — wiersz bez `cik_str`
        lub `ticker` jest pomijany, nigdy nie fabrykujemy brakującego
        pola. NIE jest to mapowanie historyczne — ticker mógł w
        przeszłości należeć do innej spółki (recykling tickerów),
        więc rozwiązanie przez tę metodę to pierwszy przebieg
        diagnostyczny, nie finalna walidacja tożsamości point-in-time."""
        resp = self._get(COMPANY_TICKERS_URL)
        if resp.status_code != 200:
            raise SecEdgarError(
                f"SEC EDGAR zwrócił status {resp.status_code} dla company_tickers.json."
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise SecEdgarError("SEC EDGAR zwrócił niepoprawny JSON dla company_tickers.json") from exc

        mapping: dict[str, str] = {}
        for entry in data.values():
            ticker = entry.get("ticker")
            cik = entry.get("cik_str")
            if not ticker or cik is None:
                continue
            mapping[ticker] = str(cik)
        return mapping
