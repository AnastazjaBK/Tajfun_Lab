"""Klasy aktywów portfela (Faza 11, P4).

Jeden portfel: te same pozycje i transakcje dla akcji, ETF/ETC/ETN,
metali fizycznych i kryptowalut -- różnią się tylko danymi instrumentu
(kolumny `positions`) i źródłem ceny. Scoring Buffetta dotyczy WYŁĄCZNIE
akcji ze scannera; metali i kryptowalut nie ocenia.

Metale fizyczne: `shares` = liczba sztuk. Wartość spot sztuki = masa x
próba x cena czystego metalu. Wartość spot NIE jest ceną odkupu -- tę
wpisuje się ręcznie (dealer, spread, premia). Moneta kolekcjonerska nie
jest wyceniana po spot (tylko wycena ręczna).

Metal na platformie (COMMODITY, np. XAG/XAU w Revolut): `shares` = uncje
trojańskie czystego metalu, których nie przechowuje się samodzielnie.
Wartość rynkowa = uncje x cena spot. Kwota możliwa do uzyskania przy
sprzedaży jest niższa o opłatę platformy -- pokazywana OBOK wartości
rynkowej (`realizable_value_pln`), nigdy zamiast niej.

ETC/ETN/ETF na metale to papiery wyceniane rynkowo, NIE gramy metalu na
własność -- w ekspozycji pokazywane osobno ("giełdowe"), bez przeliczania
na gramy, więc bez podwójnego liczenia.
"""

from __future__ import annotations

TROY_OUNCE_G = 31.1034768

STOCK, ETF, ETC, ETN = "STOCK", "ETF", "ETC", "ETN"
PHYSICAL_GOLD, PHYSICAL_SILVER, CRYPTO = "PHYSICAL_GOLD", "PHYSICAL_SILVER", "CRYPTO"
COMMODITY = "COMMODITY"
# Symbol platformy -> metal; ilość zawsze w uncjach trojańskich.
COMMODITY_SYMBOLS = {"XAU": "GOLD", "XAG": "SILVER"}
EXCHANGE_TRADED = (STOCK, ETF, ETC, ETN)
PHYSICAL = (PHYSICAL_GOLD, PHYSICAL_SILVER)

ASSET_CLASS_LABELS = {
    STOCK: "Akcja", ETF: "ETF", ETC: "ETC (np. złoto/srebro giełdowe)", ETN: "ETN",
    PHYSICAL_GOLD: "Złoto fizyczne", PHYSICAL_SILVER: "Srebro fizyczne", CRYPTO: "Kryptowaluta",
    COMMODITY: "Metal na platformie (np. Revolut)",
}
METAL_LABELS = {"GOLD": "złoto", "SILVER": "srebro"}
EXPOSURE_LABELS = {
    "PHYSICAL_BACKED": "zabezpieczony fizycznie", "SYNTHETIC": "syntetyczny",
    "FUTURES": "kontrakty terminowe", "OTHER": "inny",
}
PRODUCT_FORM_LABELS = {"COIN": "moneta", "BAR": "sztabka", "OTHER": "inny"}


def asset_class_of(position) -> str:
    """NULL (pozycje sprzed Fazy 11) = akcja."""
    try:
        value = position["asset_class"]
    except (KeyError, IndexError):
        value = None
    return value or STOCK


def pure_grams_per_piece(unit_weight: float | None, weight_unit: str | None, fineness: float | None) -> float | None:
    """Masa czystego metalu w jednej sztuce. Próba jako ułamek (0.9999)
    albo w promilach (999.9) -- oba zapisy akceptowane."""
    if not unit_weight or unit_weight <= 0 or not fineness or fineness <= 0:
        return None
    grams = unit_weight * (TROY_OUNCE_G if (weight_unit or "").upper() == "OZT" else 1.0)
    if fineness <= 1.0:
        purity = fineness
    elif 100.0 <= fineness <= 1000.0:
        purity = fineness / 1000.0
    else:
        return None  # ani ułamek, ani promile -- nie zgadujemy
    return grams * purity


def metal_of(position) -> str | None:
    asset_class = asset_class_of(position)
    if asset_class == PHYSICAL_GOLD:
        return "GOLD"
    if asset_class == PHYSICAL_SILVER:
        return "SILVER"
    try:
        return position["metal"] or None
    except (KeyError, IndexError):
        return None


def exposure_summary(positions_with_summaries: list) -> dict:
    """Wartość (PLN, dziś) według klasy aktywów i ekspozycja na metale:
    {"by_class": {klasa: PLN}, "metals": {"GOLD": {"physical", "platform",
    "exchange"}, "SILVER": {...}}, "unpriced": [tickery bez wyceny]}. Każda
    pozycja liczona RAZ -- fizyczne i na platformie po wartości metalu,
    giełdowe po wartości rynkowej."""
    by_class: dict[str, float] = {}
    metals = {m: {"physical": 0.0, "platform": 0.0, "exchange": 0.0} for m in METAL_LABELS}
    unpriced: list[str] = []
    for position, summary in positions_with_summaries:
        held = [s for s in summary.by_broker_currency if s.shares_held > 1e-12]
        if not held:
            continue
        values = [s.current_value_pln for s in held]
        if any(v is None for v in values):
            unpriced.append(position["ticker"])
            continue
        value = sum(values)
        asset_class = asset_class_of(position)
        by_class[asset_class] = by_class.get(asset_class, 0.0) + value
        metal = metal_of(position)
        if metal in metals:
            bucket = "physical" if asset_class in PHYSICAL else "platform" if asset_class == COMMODITY else "exchange"
            metals[metal][bucket] += value
    return {"by_class": by_class, "metals": metals, "unpriced": unpriced}


def realizable_value_pln(
    market_value_pln: float | None, *, sale_fee_pct: float | None = None, sale_price_value_pln: float | None = None,
) -> tuple[float | None, str | None]:
    """Kwota możliwa do uzyskania przy sprzedaży (PLN) i jej podstawa.
    Pierwszeństwo: cena sprzedaży podana przez platformę (wpis ręczny),
    potem wartość rynkowa minus opłata platformy w %. Bez żadnej z nich
    -- None: opłaty nie zgadujemy."""
    if sale_price_value_pln is not None:
        return sale_price_value_pln, "cena sprzedaży z platformy"
    if market_value_pln is not None and sale_fee_pct is not None and 0 <= sale_fee_pct < 100:
        return market_value_pln * (1 - sale_fee_pct / 100), f"wartość rynkowa − opłata {sale_fee_pct:g}%"
    return None, None


def commodity_cost_error(quantity: float, price: float, fee: float, total: float) -> str | None:
    """Łączny koszt musi zgadzać się z ilość x cena + opłata. Tolerancja:
    zaokrąglenie ceny do 0,01 na każdą uncję + 0,01, ale co najmniej
    0,5% kwoty -- wyłapuje literówki, nie zaokrąglenia platformy."""
    expected = quantity * price + fee
    tolerance = max(quantity * 0.005 + 0.01, total * 0.005)
    if abs(expected - total) > tolerance:
        return (
            f"Ilość × cena + opłata = {expected:,.2f}, a łączny koszt to {total:,.2f}. "
            "Sprawdź ilość, cenę i opłatę (albo zostaw łączny koszt pusty — zostanie wyliczony)."
        )
    return None


# Kategorie PORTFELA (nawigacja, 2026-10-19). Każda klasa aktywa należy do
# DOKŁADNIE jednej kategorii -- o kategorii decyduje zapisana klasa
# (`asset_class`), nigdy nazwa ani ticker; pozycje sprzed Fazy 11 (NULL) to akcje.
PORTFOLIO_CATEGORIES = (
    ("STOCKS", "Akcje", (STOCK,)),
    ("FUNDS", "ETF / ETC / ETN", (ETF, ETC, ETN)),
    ("SILVER", "Srebro fizyczne", (PHYSICAL_SILVER,)),
    ("GOLD", "Złoto fizyczne", (PHYSICAL_GOLD,)),
    ("PLATFORM_METALS", "Metale na platformie", (COMMODITY,)),
    ("CRYPTO", "Kryptowaluty", (CRYPTO,)),
)
CATEGORY_LABELS = {key: label for key, label, _ in PORTFOLIO_CATEGORIES}
_CATEGORY_OF_CLASS = {cls: key for key, _, classes in PORTFOLIO_CATEGORIES for cls in classes}


def portfolio_category_of(position) -> str:
    return _CATEGORY_OF_CLASS.get(asset_class_of(position), "STOCKS")


def is_active(summary) -> bool:
    """Pozycja z jednostkami w posiadaniu (sprzedana w całości -> False)."""
    return any(sub.shares_held > 1e-12 for sub in summary.by_broker_currency)


def has_no_valid_transactions(summary) -> bool:
    """Wszystkie wpisy pozycji anulowane -- to nie jest pozycja zamknięta
    (sprzedana), tylko błędny wpis do usunięcia w karcie pozycji."""
    return not summary.by_broker_currency


def category_summaries(positions_with_summaries: list) -> dict[str, dict]:
    """Dashboard kategorii: dla każdej kategorii z pozycjami -- wartość,
    koszt, wynik niezrealizowany (kwota, %), zrealizowany, udział w
    wycenionej wartości portfela, liczba aktywnych/zamkniętych pozycji,
    braki cen. Liczone TĄ SAMĄ funkcją co podsumowanie całego portfela
    (`compute_portfolio_pln_summary`) na podzbiorze pozycji."""
    from buffett_scanner.ui.portfolio import compute_portfolio_pln_summary

    total_value = compute_portfolio_pln_summary(positions_with_summaries)["value_pln"]
    result: dict[str, dict] = {}
    for key, _label, _classes in PORTFOLIO_CATEGORIES:
        subset = [(p, s) for p, s in positions_with_summaries if portfolio_category_of(p) == key]
        if not subset:
            continue
        pln = compute_portfolio_pln_summary(subset)
        active = sum(1 for _, s in subset if is_active(s))
        empty = sum(1 for _, s in subset if has_no_valid_transactions(s))
        result[key] = {
            **pln,
            "share_pct": (pln["value_pln"] / total_value * 100.0) if total_value > 0 else None,
            "active_count": active,
            "closed_count": len(subset) - active - empty,
            "positions": subset,
        }
    return result
