"""Klasy aktywów portfela (Faza 11, P4).

Jeden portfel: te same pozycje i transakcje dla akcji, ETF/ETC/ETN,
metali fizycznych i kryptowalut -- różnią się tylko danymi instrumentu
(kolumny `positions`) i źródłem ceny. Scoring Buffetta dotyczy WYŁĄCZNIE
akcji ze scannera; metali i kryptowalut nie ocenia.

Metale fizyczne: `shares` = liczba sztuk. Wartość spot sztuki = masa x
próba x cena czystego metalu. Wartość spot NIE jest ceną odkupu -- tę
wpisuje się ręcznie (dealer, spread, premia). Moneta kolekcjonerska nie
jest wyceniana po spot (tylko wycena ręczna).

ETC/ETN/ETF na metale to papiery wyceniane rynkowo, NIE gramy metalu na
własność -- w ekspozycji pokazywane osobno ("giełdowe"), bez przeliczania
na gramy, więc bez podwójnego liczenia.
"""

from __future__ import annotations

TROY_OUNCE_G = 31.1034768

STOCK, ETF, ETC, ETN = "STOCK", "ETF", "ETC", "ETN"
PHYSICAL_GOLD, PHYSICAL_SILVER, CRYPTO = "PHYSICAL_GOLD", "PHYSICAL_SILVER", "CRYPTO"
EXCHANGE_TRADED = (STOCK, ETF, ETC, ETN)
PHYSICAL = (PHYSICAL_GOLD, PHYSICAL_SILVER)

ASSET_CLASS_LABELS = {
    STOCK: "Akcja", ETF: "ETF", ETC: "ETC (np. złoto/srebro giełdowe)", ETN: "ETN",
    PHYSICAL_GOLD: "Złoto fizyczne", PHYSICAL_SILVER: "Srebro fizyczne", CRYPTO: "Kryptowaluta",
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
    {"by_class": {klasa: PLN}, "metals": {"GOLD": {"physical", "exchange"},
    "SILVER": {...}}, "unpriced": [tickery bez wyceny]}. Każda pozycja liczona
    RAZ -- fizyczne po wartości metalu, giełdowe po wartości rynkowej."""
    by_class: dict[str, float] = {}
    metals = {m: {"physical": 0.0, "exchange": 0.0} for m in METAL_LABELS}
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
            metals[metal]["physical" if asset_class in PHYSICAL else "exchange"] += value
    return {"by_class": by_class, "metals": metals, "unpriced": unpriced}
