"""Source Assembly Layer — Faza 2 (sekcja 9/BLOCKER 3/4 design review).

Jedyne miejsce w systemie, które tworzy zweryfikowane źródła. LLM
(Faza 3+) będzie cytować wyłącznie po `source_id` z listy, którą ta
warstwa dostarcza — nigdy nie twierdzi samodzielnie, że dokument
istnieje lub ma daną treść.

`VerifiedSource` odzwierciedla schemat `analysis_sources` z sekcji 5
design review, pomniejszony o `source_id`/`analysis_id` — te FK powstaną
dopiero w Fazie 3, kiedy istnieje `analyses`, do którego source packet
się dowiąże. Na razie source packet to samodzielna struktura danych,
nie wiersze w bazie — nie rozszerzamy schematu przed czasem.

Niezweryfikowany dokument (błąd sieci, 404, brak dostępu) NIGDY nie
znika po cichu: trafia do wyniku jako `verified=False` z wypełnionym
`reason` — SOURCE NOT VERIFIED, dokładnie zgodnie z sekcją 9/10.
"""

from __future__ import annotations

from dataclasses import dataclass

from buffett_scanner.providers.sec_edgar import SecEdgarClient, SecEdgarError

DEFAULT_FORMS = ("10-K", "10-Q")
DEFAULT_LIMIT_PER_FORM = 2


@dataclass(frozen=True)
class VerifiedSource:
    source_type: str  # 'SEC_FILING' | 'IR_DOC' | 'PRESS_RELEASE' | 'EARNINGS_CALL' | 'OTHER'
    title: str
    issuer: str
    doc_date: str | None
    url: str
    accession_number: str | None
    section: str | None
    content_hash: str | None
    verified: bool
    reason: str | None = None  # wypełnione tylko gdy verified=False


def build_sec_source_packet(
    client: SecEdgarClient,
    *,
    cik: str,
    issuer: str,
    forms: tuple[str, ...] = DEFAULT_FORMS,
    limit_per_form: int = DEFAULT_LIMIT_PER_FORM,
) -> list[VerifiedSource]:
    """Buduje source packet z rzeczywiście pobranych i zahashowanych
    filingów SEC EDGAR dla danego CIK, najwyżej `limit_per_form`
    najnowszych na każdy typ formularza w `forms`."""
    try:
        filings = client.get_filings(cik)
    except SecEdgarError as exc:
        return [
            VerifiedSource(
                source_type="SEC_FILING", title="(lista filingów)", issuer=issuer,
                doc_date=None, url="", accession_number=None, section=None,
                content_hash=None, verified=False, reason=str(exc),
            )
        ]

    counts = {form: 0 for form in forms}
    sources: list[VerifiedSource] = []
    for filing in filings:
        form = filing["form"]
        if form not in forms or counts[form] >= limit_per_form:
            continue
        counts[form] += 1
        url = SecEdgarClient.build_filing_url(
            cik, filing["accession_number"], filing["primary_document"]
        )
        title = f"{form} ({filing['filing_date']})"
        try:
            fetched = client.fetch_and_hash_document(url)
        except SecEdgarError as exc:
            sources.append(
                VerifiedSource(
                    source_type="SEC_FILING", title=title, issuer=issuer,
                    doc_date=filing["filing_date"], url=url,
                    accession_number=filing["accession_number"], section=None,
                    content_hash=None, verified=False, reason=str(exc),
                )
            )
            continue
        sources.append(
            VerifiedSource(
                source_type="SEC_FILING", title=title, issuer=issuer,
                doc_date=filing["filing_date"], url=fetched["url"],
                accession_number=filing["accession_number"], section=None,
                content_hash=fetched["content_hash"], verified=True, reason=None,
            )
        )
    return sources
