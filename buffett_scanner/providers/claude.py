"""Klient Claude API — Faza 3 (sekcja 8/15 design review).

Cienki wrapper wokół oficjalnego SDK `anthropic` (w przeciwieństwie do
FMP/SEC EDGAR: Anthropic ma w pełni udokumentowane, oficjalne SDK, więc
go używamy zamiast odtwarzać protokół HTTP ręcznie).

Wymusza strukturalny JSON wyjścia przez `output_format=AnalysisOutput`
(`client.messages.parse`) — Claude API gwarantuje zgodność ze
schematem, więc walidacja pydantic nigdy się nie odrzuci z powodu
złego kształtu. Reguły sekcji 8 dotyczące RELACJI między polami
(cited_source_ids musi być podzbiorem dostarczonej listy, page tylko
dla PDF, score <= max_score) nie są częścią schematu JSON i są
sprawdzane osobno przez `analysis_schema.validate_analysis_output` po
stronie kodu — nigdy nie ufamy samemu twierdzeniu modelu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from buffett_scanner.analysis_schema import AnalysisOutput, ThesisInvalidationRepair

_OutputT = TypeVar("_OutputT", bound=BaseModel)


@dataclass(frozen=True)
class ClaudeUsage:
    """Surowe pola realnie zwrócone przez `response`/`response.usage`
    zainstalowanego SDK (`anthropic==1.8.0`, zweryfikowane 2026-10-06
    przez inspekcję `anthropic.types.Usage`/`Message` — nigdy nie
    zakładane z pamięci/dokumentacji nowszej generacji SDK). Zero
    wyliczonego kosztu $ tutaj — `model` nie ma dziś zweryfikowanego
    cennika per-token (patrz COST AUDIT, Faza 6d), więc koszt jest
    liczony (jeśli w ogóle) wyżej w warstwie persystencji, tylko gdy
    jest wiarygodnie policzalny."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None
    thinking_tokens: int | None
    service_tier: str | None

    @classmethod
    def from_response(cls, response) -> "ClaudeUsage":
        usage = response.usage
        output_details = usage.output_tokens_details
        return cls(
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            thinking_tokens=output_details.thinking_tokens if output_details is not None else None,
            service_tier=usage.service_tier,
        )


@dataclass(frozen=True)
class ClaudeAnalysisResult:
    """Wynik jednego wywołania `generate_analysis` razem z realnym
    `usage` -- rozdzielone od `AnalysisOutput`, żeby nie zmieniać
    schematu JSON analizy (Faza 3, sekcja 8) ani jej walidacji."""

    output: AnalysisOutput
    usage: ClaudeUsage


@dataclass(frozen=True)
class ClaudeRepairResult:
    """Wynik `repair_thesis_invalidation` (Faza 6h, TARGETED FIELD
    REPAIR) -- analogiczne do `ClaudeAnalysisResult`, ale dla
    minimalnego, dedykowanego schematu `ThesisInvalidationRepair`
    (WYŁĄCZNIE to jedno pole, nigdy cała analiza)."""

    output: ThesisInvalidationRepair
    usage: ClaudeUsage


class ClaudeError(RuntimeError):
    def __init__(self, message: str, *, usage: ClaudeUsage | None = None):
        super().__init__(message)
        # Obecne TYLKO gdy API faktycznie zwróciło odpowiedź (refusal /
        # nie-sparsowalny JSON) -- na APIStatusError/APIConnectionError
        # (np. wyczerpany kredyt, błąd sieci) `response` nigdy nie
        # istnieje, więc `usage` zostaje None: nigdy nie wymyślamy
        # kosztu/tokenów dla niewykonanego wywołania.
        self.usage = usage


class ClaudeClient:
    def __init__(self, api_key: str, *, model: str, max_output_tokens: int = 4000):
        if not api_key:
            raise ClaudeError("Pusty klucz API Claude.")
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClaudeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _parse(self, prompt: str, output_format: type[_OutputT]) -> tuple[_OutputT, ClaudeUsage]:
        """Rdzeń współdzielony przez `generate_analysis`/
        `repair_thesis_invalidation` (Faza 6h) -- identyczna obsługa
        błędów API/refusal/nie-sparsowalnego JSON, sparametryzowana
        wyłącznie `output_format`. Rzuca `ClaudeError` na każdy błąd,
        nigdy nie zwraca częściowego/domyślnego wyniku po cichu. Gdy
        odpowiedź realnie istniała (refusal/nie-sparsowalny JSON),
        `ClaudeError.usage` niesie jej realny `usage` dalej -- gdy API
        nie zwróciło żadnej odpowiedzi (APIStatusError/APIConnectionError,
        np. wyczerpany kredyt), `ClaudeError.usage` jest `None`."""
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_output_tokens,
                messages=[{"role": "user", "content": prompt}],
                output_format=output_format,
            )
        except anthropic.APIStatusError as exc:
            raise ClaudeError(
                f"Claude API zwróciło błąd ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ClaudeError(f"Błąd sieci przy wywołaniu Claude API: {exc}") from exc
        except Exception as exc:
            # Najczęstsza przyczyna: odpowiedź ucięta przez max_output_tokens,
            # zanim model skończył generować JSON — SDK rzuca wtedy błąd
            # walidacji pydantic z niekompletnego tekstu (nie APIStatusError/
            # APIConnectionError), więc trzeba go złapać osobno. Potwierdzone
            # empirycznie 2026-09-25 (Phase 3 Proof Run, patrz config.yaml).
            raise ClaudeError(
                "Nie udało się sparsować odpowiedzi Claude jako poprawny JSON zgodny ze "
                f"schematem (aktualny max_output_tokens={self._max_output_tokens} — jeśli to "
                "się powtarza, prawdopodobnie odpowiedź jest ucinana w połowie generowania; "
                f"zwiększ config.yaml -> llm.max_output_tokens). Błąd źródłowy: {exc}"
            ) from exc

        if response.stop_reason == "refusal":
            raise ClaudeError(
                "Claude odmówił odpowiedzi (stop_reason=refusal).",
                usage=ClaudeUsage.from_response(response),
            )
        if response.parsed_output is None:
            raise ClaudeError(
                "Claude API nie zwróciło poprawnie sparsowanego wyjścia (parsed_output=None).",
                usage=ClaudeUsage.from_response(response),
            )
        return response.parsed_output, ClaudeUsage.from_response(response)

    def generate_analysis(self, prompt: str) -> ClaudeAnalysisResult:
        """Wywołuje Claude API i zwraca zwalidowany strukturalnie
        `AnalysisOutput` razem z realnym `ClaudeUsage` (Faza 6e —
        telemetria usage). Patrz `_parse` co do semantyki błędów."""
        output, usage = self._parse(prompt, AnalysisOutput)
        return ClaudeAnalysisResult(output=output, usage=usage)

    def repair_thesis_invalidation(self, prompt: str) -> ClaudeRepairResult:
        """Faza 6h, TARGETED FIELD REPAIR -- osobne, minimalne wywołanie
        Claude API zwracające WYŁĄCZNIE `ThesisInvalidationRepair`
        (jedno pole), nie całą `AnalysisOutput`. Zastępuje poprzedni
        mechanizm pełnego ślepego/feedback retry (Faza 6f/6g) dla
        dokładnie jednego, empirycznie potwierdzonego przypadku:
        reszta analizy jest poprawna, zawodzi WYŁĄCZNIE
        `thesis_invalidation`. Semantyka błędów identyczna jak
        `generate_analysis` (patrz `_parse`)."""
        output, usage = self._parse(prompt, ThesisInvalidationRepair)
        return ClaudeRepairResult(output=output, usage=usage)
