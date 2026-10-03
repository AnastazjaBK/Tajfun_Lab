"""Wspólna, czysta logika retry/backoff dla klientów SEC EDGAR i FMP
(Faza 5.3b, backfill 626 CIK, Decyzja właścicielki 2026-10-03).

Właścicielka ma plan FMP Premium (750 calls/min, 50 GB/30 dni) — ale
jawnie zastrzegła: NIE wykorzystywać tego limitu agresywnie, zachować
rate limiting z bezpiecznym marginesem, obsłużyć HTTP 429 i błędy
przejściowe (5xx/sieciowe) z backoffem, bez agresywnego
równoległego/ponawianego requestowania. Zero zmiany logiki point-in-time
— to wyłącznie warstwa transportowa (kiedy i jak długo czekać przed
ponowną próbą tego samego zapytania), nie interpretacja danych."""

from __future__ import annotations

DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_CAP_S = 30.0

# Kody uznawane za przejściowe — warte ponowienia. 429 (rate limit) i
# 5xx (błąd serwera) — NIGDY 4xx inne niż 429 (np. 404 "CIK nie
# istnieje" albo 402 "Restricted Endpoint" to stałe, nie przejściowe
# błędy — ponawianie ich tylko traciłoby czas i limit).
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def backoff_seconds(attempt: int, *, base: float = DEFAULT_BACKOFF_BASE_S, cap: float = DEFAULT_BACKOFF_CAP_S) -> float:
    """Wykładniczy backoff: `base * 2**attempt`, z sufitem `cap`.
    `attempt` liczony od 0 (czas oczekiwania PO pierwszej nieudanej
    próbie, przed drugą)."""
    if attempt < 0:
        raise ValueError("attempt musi być >= 0")
    return min(base * (2 ** attempt), cap)


def parse_retry_after_seconds(header_value: str | None) -> float | None:
    """Parsuje nagłówek HTTP `Retry-After` (liczba sekund) — `None`,
    jeśli nieobecny albo nieparsowalny (np. format daty HTTP, rzadko
    używany przez SEC/FMP) — NIGDY nie zgadujemy czasu oczekiwania,
    wtedy wołający spada na `backoff_seconds`."""
    if header_value is None:
        return None
    try:
        return max(0.0, float(header_value))
    except ValueError:
        return None
