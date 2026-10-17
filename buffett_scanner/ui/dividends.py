"""Dywidendy -- dane spółek i portfela (Faza 11, P3).

WYŁĄCZNIE prezentacja i analityka portfela: scoring dywidendowy
scannera (`shareholder_returns.py`, łączne `dividends_paid` z
przepływów pieniężnych) pozostaje nietknięty. Tu pracujemy na
WYPŁATACH NA AKCJĘ z dat ex-dividend (FMP `dividends`, EODHD `div`).

Zasady:
- wypłaty specjalne/nieregularne są rozróżniane i NIE wchodzą do yieldu
  TTM ani prognozy (pokazywane osobno);
- yield TTM = suma regularnych wypłat z ex-date w ostatnich 365 dniach
  / cena -- w tej samej walucie (pensy -> funty), inaczej None;
- przyszła data ex-dividend jest "potwierdzona" tylko, gdy dostawca podaje
  datę ogłoszenia (declarationDate) -- nigdy prognozowana;
- trend porównuje regularne wypłaty z ostatnich 12 miesięcy z
  poprzednimi 12 -- bez wniosków o bezpieczeństwie z samej wysokości yieldu.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from buffett_scanner.ui.pricing import MINOR_UNIT_CURRENCIES

REGULAR = "REGULAR"
SPECIAL = "SPECIAL"

FREQUENCY_LABELS = {
    "MONTHLY": "miesięczna", "QUARTERLY": "kwartalna", "SEMI_ANNUAL": "półroczna",
    "ANNUAL": "roczna", "IRREGULAR": "nieregularna", "NONE": "brak wypłat",
}
TREND_LABELS = {
    "UP": "rośnie", "STABLE": "stabilna", "DOWN": "spada", "CUT": "obcięta", "NO_DATA": "brak danych",
}


@dataclass(frozen=True)
class DividendEvent:
    ex_date: str
    amount: float  # w walucie GŁÓWNEJ (pensy -> funty)
    currency: str | None
    kind: str  # REGULAR / SPECIAL
    pay_date: str | None = None
    declaration_date: str | None = None
    provider_frequency: str | None = None


def _major(amount: float, currency: str | None) -> tuple[float, str | None]:
    if currency is None:
        return amount, None
    code = currency.strip()
    if code in MINOR_UNIT_CURRENCIES:
        major, divisor = MINOR_UNIT_CURRENCIES[code]
        return amount / divisor, major
    return amount, code.upper()


def _clean_date(value) -> str | None:
    text = str(value or "").strip()[:10]
    return text if len(text) == 10 else None


def events_from_fmp(rows: list[dict], quote_currency: str | None) -> list[DividendEvent]:
    """FMP podaje kwotę w walucie notowania (GSK.L: 17 = 17 pensów)."""
    events = []
    for r in rows or []:
        ex = _clean_date(r.get("date"))
        amount = r.get("dividend")
        if ex is None or amount is None or amount <= 0:
            continue
        value, currency = _major(float(amount), quote_currency)
        frequency = str(r.get("frequency") or "")
        kind = SPECIAL if frequency.lower() in ("special", "irregular", "one-time") else REGULAR
        events.append(DividendEvent(
            ex_date=ex, amount=value, currency=currency, kind=kind,
            pay_date=_clean_date(r.get("paymentDate")), declaration_date=_clean_date(r.get("declarationDate")),
            provider_frequency=frequency or None,
        ))
    return sorted(events, key=lambda e: e.ex_date)


def events_from_eodhd(rows: list[dict]) -> list[DividendEvent]:
    """EODHD podaje walutę wypłaty (LSE: GBP, nie pensy -- potwierdzone
    2026-10-17) i `period` (Final/Interim/Quarterly/Special...)."""
    events = []
    for r in rows or []:
        ex = _clean_date(r.get("date"))
        amount = r.get("value")
        if ex is None or amount is None or amount <= 0:
            continue
        value, currency = _major(float(amount), r.get("currency"))
        period = str(r.get("period") or "")
        kind = SPECIAL if "special" in period.lower() else REGULAR
        events.append(DividendEvent(
            ex_date=ex, amount=value, currency=currency, kind=kind,
            pay_date=_clean_date(r.get("paymentDate")), declaration_date=_clean_date(r.get("declarationDate")),
            provider_frequency=period or None,
        ))
    return sorted(events, key=lambda e: e.ex_date)


@dataclass(frozen=True)
class DividendMetrics:
    last_event: DividendEvent | None
    ttm_dps: float  # regularne, ostatnie 365 dni
    ttm_special: float
    ytd_dps: float  # regularne + specjalne, od 1 stycznia
    currency: str | None
    yield_ttm_pct: float | None
    gross_per_100_pln: float | None  # brutto rocznie na 100 PLN zainwestowane po bieżącej cenie
    frequency: str  # klucz FREQUENCY_LABELS
    trend: str  # klucz TREND_LABELS
    next_confirmed: DividendEvent | None  # przyszła ex-date z datą ogłoszenia
    by_year: dict[int, float]  # regularne + specjalne, ostatnie 5 lat kalendarzowych
    history_years: float  # długość dostępnej historii wypłat


def _frequency(regular: list[DividendEvent], as_of: dt.date) -> str:
    if not regular:
        return "NONE"
    window = [e for e in regular if as_of - dt.timedelta(days=730) < dt.date.fromisoformat(e.ex_date) <= as_of]
    per_year = len(window) / 2.0
    if per_year >= 10:
        return "MONTHLY"
    if per_year >= 3.5:
        return "QUARTERLY"
    if per_year >= 1.5:
        return "SEMI_ANNUAL"
    if per_year >= 0.75:
        return "ANNUAL"
    return "IRREGULAR"


def _trend(regular: list[DividendEvent], as_of: dt.date, history_years: float) -> str:
    if not regular or history_years < 1.9:
        return "NO_DATA"

    def window_sum(lo_days: int, hi_days: int) -> float:
        return sum(
            e.amount for e in regular
            if as_of - dt.timedelta(days=hi_days) < dt.date.fromisoformat(e.ex_date) <= as_of - dt.timedelta(days=lo_days)
        )

    current, previous = window_sum(0, 365), window_sum(365, 730)
    if previous <= 0:
        return "UP" if current > 0 else "NO_DATA"
    change = (current / previous - 1.0) * 100.0
    if change <= -25.0:
        return "CUT"
    if change < -2.0:
        return "DOWN"
    if change > 2.0:
        return "UP"
    return "STABLE"


def compute_dividend_metrics(
    events: list[DividendEvent], *, price: float | None, price_currency: str | None, as_of: str,
) -> DividendMetrics:
    """`as_of` = dzień, na który liczymy (dziś albo data skanu -- wtedy
    wypłaty z późniejszymi ex-date są ignorowane, bez look-ahead)."""
    as_of_day = dt.date.fromisoformat(as_of[:10])
    past = [e for e in events if dt.date.fromisoformat(e.ex_date) <= as_of_day]
    regular = [e for e in past if e.kind == REGULAR]
    year_ago = as_of_day - dt.timedelta(days=365)
    ttm = sum(e.amount for e in regular if dt.date.fromisoformat(e.ex_date) > year_ago)
    ttm_special = sum(e.amount for e in past if e.kind == SPECIAL and dt.date.fromisoformat(e.ex_date) > year_ago)
    ytd = sum(e.amount for e in past if e.ex_date[:4] == str(as_of_day.year))
    currencies = {e.currency for e in past if e.currency}
    currency = currencies.pop() if len(currencies) == 1 else None
    history_years = (
        (as_of_day - dt.date.fromisoformat(past[0].ex_date)).days / 365.25 if past else 0.0
    )
    yield_pct = None
    if price and price > 0 and currency and price_currency and currency == price_currency.upper():
        yield_pct = ttm / price * 100.0
    future = [
        e for e in events
        if dt.date.fromisoformat(e.ex_date) > as_of_day and e.declaration_date and e.declaration_date <= as_of[:10]
    ]
    by_year: dict[int, float] = {}
    for e in past:
        year = int(e.ex_date[:4])
        if year > as_of_day.year - 5:
            by_year[year] = by_year.get(year, 0.0) + e.amount
    return DividendMetrics(
        last_event=past[-1] if past else None, ttm_dps=ttm, ttm_special=ttm_special, ytd_dps=ytd,
        currency=currency, yield_ttm_pct=yield_pct,
        gross_per_100_pln=yield_pct,  # 100 PLN x yield% / 100 -- kwota w PLN brutto, orientacyjnie
        frequency=_frequency(regular, as_of_day), trend=_trend(regular, as_of_day, history_years),
        next_confirmed=future[0] if future else None, by_year=dict(sorted(by_year.items())),
        history_years=history_years,
    )


def cut_risk_note(metrics: DividendMetrics, payout_ratio_pct: float | None) -> str | None:
    """Ostrożna, jawnie wyprowadzona notatka o ryzyku obniżki -- tylko
    gdy są fakty (obcięcie w danych, wypłata > FCF). Nigdy z samego yieldu."""
    notes = []
    if metrics.trend == "CUT":
        notes.append("wypłaty z ostatnich 12 mies. są o ponad 25% niższe niż rok wcześniej")
    if payout_ratio_pct is not None and payout_ratio_pct > 100.0:
        notes.append(f"dywidendy przekraczają wolne przepływy pieniężne (wypłata {payout_ratio_pct:.0f}% FCF)")
    return "; ".join(notes) or None


@dataclass(frozen=True)
class ReceiptsSummary:
    gross_by_currency: dict[str, float]
    net_by_currency: dict[str, float]
    tax_by_currency: dict[str, float]
    gross_pln: float | None
    net_pln: float | None
    ytd_net_pln: float | None
    ytd_net_by_currency: dict[str, float]
    estimated: bool  # choć jeden kurs PLN z NBP (orientacyjny)
    count: int


def receipt_net(receipt) -> float:
    """Netto podane przez użytkownika, inaczej brutto minus podatek u źródła."""
    if receipt["net_amount"] is not None:
        return receipt["net_amount"]
    return receipt["gross_amount"] - (receipt["withholding_tax"] or 0.0)


def summarize_receipts(receipts: list, *, pln_rate_fn, year: int) -> ReceiptsSummary:
    """Faktycznie otrzymane dywidendy (rejestr, NIE prognoza). Kwoty w PLN
    po kursie z dnia wypłaty: kurs brokera, jeśli zapisany, inaczej NBP
    sprzed dnia wypłaty (orientacyjnie). Brak kursu -> suma PLN = None."""
    gross: dict[str, float] = {}
    net: dict[str, float] = {}
    tax: dict[str, float] = {}
    ytd_net: dict[str, float] = {}
    gross_pln: float | None = 0.0
    net_pln: float | None = 0.0
    ytd_net_pln: float | None = 0.0
    estimated = False
    for r in receipts:
        currency = str(r["currency"]).strip().upper()
        n = receipt_net(r)
        gross[currency] = gross.get(currency, 0.0) + r["gross_amount"]
        net[currency] = net.get(currency, 0.0) + n
        tax[currency] = tax.get(currency, 0.0) + (r["withholding_tax"] or 0.0)
        in_year = str(r["pay_date"])[:4] == str(year)
        if in_year:
            ytd_net[currency] = ytd_net.get(currency, 0.0) + n
        rate = pln_rate_fn(currency, str(r["pay_date"])[:10], r["fx_rate_actual"])
        if rate is None:
            gross_pln = net_pln = None
            if in_year:
                ytd_net_pln = None
            continue
        estimated = estimated or rate[1] == "NBP"
        if gross_pln is not None:
            gross_pln += r["gross_amount"] * rate[0]
            net_pln += n * rate[0]
        if in_year and ytd_net_pln is not None:
            ytd_net_pln += n * rate[0]
    return ReceiptsSummary(
        gross_by_currency=gross, net_by_currency=net, tax_by_currency=tax, gross_pln=gross_pln,
        net_pln=net_pln, ytd_net_pln=ytd_net_pln, ytd_net_by_currency=ytd_net, estimated=estimated,
        count=len(receipts),
    )
