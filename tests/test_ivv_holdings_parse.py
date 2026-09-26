"""Testy defensywnego parsera CSV holdingów IVV (Faza 5.2, research
v1.27) — syntetyczny fixture naśladujący udokumentowany (nie
bezpośrednio potwierdzony) kształt pliku: kilka wierszy preambuły,
nagłówek z `Ticker`, wiersze danych, stopka disclaimer."""

from __future__ import annotations

from buffett_scanner.ivv_holdings_parse import locate_header_row, parse_ivv_holdings_csv

REALISTIC_FIXTURE = (
    "iShares Core S&P 500 ETF\n"
    "Fund Holdings as of,\"Dec 30, 2022\"\n"
    "Inception Date,\"May 15, 2000\"\n"
    "Shares Outstanding,\"913,000,000.00\"\n"
    "Stock,,,,,,,,,,,,,,,,\n"
    "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,CUSIP,ISIN,SEDOL,Price,Location,Exchange,Currency,FX Rate,Market Currency\n"
    "AAPL,APPLE INC,Information Technology,Equity,980033676.65,4.38868,980033676.65,7500000,037833100,US0378331005,2046251,130.67,United States,NASDAQ,USD,1,USD\n"
    "MSFT,MICROSOFT CORP,Information Technology,Equity,850000000.00,3.80000,850000000.00,3500000,594918104,US5949181045,2588173,242.85,United States,NASDAQ,USD,1,USD\n"
    "KO,COCA-COLA CO,Consumer Staples,Equity,120000000.00,0.53000,120000000.00,1900000,191216100,US1912161007,2206657,63.15,United States,NYSE,USD,1,USD\n"
    "USD,USD,Cash and/or Derivatives,Cash,5000000.00,0.02000,5000000.00,5000000,,,,,United States,,USD,1,USD\n"
    "\n"
    "The content contained herein is proprietary to BlackRock...\n"
)


def test_locate_header_row_finds_ticker_column_not_substring():
    lines = REALISTIC_FIXTURE.splitlines()
    idx = locate_header_row(lines)
    assert lines[idx].startswith("Ticker,Name,Sector")


def test_locate_header_row_returns_none_when_no_ticker_column():
    lines = ["a,b,c", "1,2,3"]
    assert locate_header_row(lines) is None


def test_parse_ivv_holdings_csv_skips_preamble_and_parses_data_rows():
    result = parse_ivv_holdings_csv(REALISTIC_FIXTURE)
    assert result.header_row_index == 5
    assert "Ticker" in result.columns
    assert "CUSIP" in result.columns
    assert len(result.rows) == 4  # AAPL, MSFT, KO, USD (kandydat do odrzucenia niżej)


def test_parse_ivv_holdings_csv_tickers_property_extracts_equity_and_cash_row():
    result = parse_ivv_holdings_csv(REALISTIC_FIXTURE)
    assert result.tickers == {"AAPL", "MSFT", "KO", "USD"}
    # Uwaga: "USD" (wiersz cash/derivatives) TEŻ ma wypełnione pole Ticker
    # w tym fixturze -> parser go nie odrzuca (nie zgaduje, że to "nie
    # akcja" bez jawnej reguły) - filtrowanie cash-wierszy to osobna
    # decyzja biznesowa do podjęcia PO zobaczeniu realnych danych, nie
    # zgadywana teraz w parserze transportowym.


def test_parse_ivv_holdings_csv_skips_footer_row_without_ticker():
    result = parse_ivv_holdings_csv(REALISTIC_FIXTURE)
    tickers = {r["Ticker"] for r in result.rows}
    assert "The content contained herein is proprietary to BlackRock..." not in tickers


def test_parse_ivv_holdings_csv_unrecognized_structure_returns_empty_not_crash():
    result = parse_ivv_holdings_csv("<html><body>Error page, not CSV</body></html>")
    assert result.header_row_index is None
    assert result.rows == ()
    assert result.tickers == set()
