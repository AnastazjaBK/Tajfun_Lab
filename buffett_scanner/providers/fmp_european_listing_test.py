"""DIAG: jednorazowy techniczny test — czy istniejący klient FMP
(`buffett_scanner/providers/fmp.py`, metoda `get_company_profile`,
NIEZMIENIONA) poprawnie rozpoznaje europejskie listingi.

Kontekst (Faza 7 KROK 7, Decyzja właścicielki pkt 6): "Nie blokuj
teraz całego UI testami Schneider/GSK. Przy implementacji formularza
'Dodaj transakcję' wykonaj techniczny test, czy istniejący FMP
provider potrafi poprawnie rozpoznać europejskie listingi. To NIE jest
Claude API call."

Narzędzie operacyjne/diagnostyczne, do usunięcia po użyciu (ten sam
wzorzec co `diag-stage6h-validation.yml`). ZERO zapisu do bazy, ZERO
wywołań Claude API, ZERO zmian produkcyjnego `fmp.py`.

Metoda: próbujemy KILKU plausible konwencji symbolu dla Schneider
Electric (Euronext Paris, EUR) i GSK (ADR na NYSE + LSE), plus jeden
znany US ticker (AAPL) jako kontrola sanity (potwierdza, że klient i
klucz w ogóle działają). Każda próba jest zaraportowana z osobna —
sukces LUB treść błędu — nigdy nie wybieramy jednej "zgadniętej"
konwencji i nie ukrywamy niepowodzeń innych (ten sam wzorzec co
`FMPClient.get_historical_sp500_constituents`).
"""

from __future__ import annotations

import sys

from buffett_scanner.config import load_config
from buffett_scanner.providers.fmp import FMPClient, FMPError

CANDIDATES: list[tuple[str, str]] = [
    ("AAPL", "KONTROLA (US, oczekiwany sukces -- potwierdza, że klient/klucz działają)"),
    ("SU.PA", "Schneider Electric SE, Euronext Paris, konwencja sufiksu w stylu Yahoo"),
    ("SU.PAR", "Schneider Electric SE, Euronext Paris, alternatywny sufiks"),
    ("SCHN.PA", "Schneider Electric SE, alternatywny symbol bazowy"),
    ("SU", "Schneider Electric SE, bez sufiksu giełdy"),
    ("GSK", "GSK plc, ADR NYSE (notowanie USD)"),
    ("GSK.L", "GSK plc, London Stock Exchange (notowanie GBP), konwencja w stylu Yahoo"),
    ("GSK.LON", "GSK plc, LSE, alternatywny sufiks"),
]


def main() -> int:
    config = load_config()
    try:
        api_key = config.data_provider.resolve_api_key()
    except RuntimeError as exc:
        print(f"BŁĄD KONFIGURACJI: {exc}", file=sys.stderr)
        return 1

    print("== Techniczny test rozpoznawania europejskich listingów przez FMP ==")
    print("(get_company_profile, NIEZMIENIONY kod produkcyjny, zero zapisu do bazy)\n")

    results = []
    with FMPClient(api_key) as client:
        for symbol, note in CANDIDATES:
            print(f"--- {symbol} ({note}) ---")
            try:
                profile = client.get_company_profile(symbol)
                summary = {
                    "symbol": profile.get("symbol"),
                    "companyName": profile.get("companyName"),
                    "exchange": profile.get("exchange") or profile.get("exchangeShortName"),
                    "currency": profile.get("currency"),
                    "price": profile.get("price"),
                    "cik": profile.get("cik"),
                }
                print(f"OK: {summary}")
                results.append((symbol, "OK", summary))
            except FMPError as exc:
                print(f"BŁĄD: {exc}")
                results.append((symbol, "ERROR", str(exc)))
            print()

    print("== PODSUMOWANIE (dla raportu do właścicielki) ==")
    for symbol, status, detail in results:
        print(f"{symbol}: {status} -- {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
