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

import anthropic

from buffett_scanner.analysis_schema import AnalysisOutput


class ClaudeError(RuntimeError):
    pass


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

    def generate_analysis(self, prompt: str) -> AnalysisOutput:
        """Wywołuje Claude API i zwraca zwalidowany strukturalnie
        `AnalysisOutput`. Rzuca `ClaudeError` na każdy błąd API, odmowę
        (`stop_reason == "refusal"`) lub brak sparsowanego wyjścia —
        nigdy nie zwraca częściowego/domyślnego wyniku po cichu."""
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_output_tokens,
                messages=[{"role": "user", "content": prompt}],
                output_format=AnalysisOutput,
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
            raise ClaudeError("Claude odmówił odpowiedzi (stop_reason=refusal).")
        if response.parsed_output is None:
            raise ClaudeError(
                "Claude API nie zwróciło poprawnie sparsowanego wyjścia (parsed_output=None)."
            )
        return response.parsed_output
