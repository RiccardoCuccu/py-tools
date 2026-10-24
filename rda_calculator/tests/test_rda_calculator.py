"""Tests for rda_calculator: reference values, amount parsing, RDA percentage math,
result formatting, and the calculate() glue. No Tk window is ever created: the
variables passed to calculate() are plain stand-ins.
"""

from __future__ import annotations

import pytest

import rda_calculator as rda


class FakeVar:
    """Minimal stand-in for tkinter.StringVar."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def rda_of(name: str) -> float:
    return next(n.rda_mg for n in rda.NUTRIENTS if n.name == name)


class TestReferenceValues:
    def test_eu_reference_values(self):
        assert rda_of("Vitamin A") == 0.8
        assert rda_of("Vitamin C") == 80.0
        assert rda_of("Iron") == 14.0
        assert rda_of("Calcium") == 800.0

    def test_order_matches_display_rows(self):
        assert [n.name for n in rda.NUTRIENTS] == [
            "Vitamin A", "Vitamin C", "Iron", "Calcium"
        ]


class TestParseMg:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("5", 5.0),
            ("  2.5 ", 2.5),
            ("0,5", 0.5),
            ("0", 0.0),
            ("1e2", 100.0),
        ],
    )
    def test_valid(self, text, expected):
        assert rda.parse_mg(text) == expected

    @pytest.mark.parametrize(
        "text", ["abc", "", "-1", "nan", "inf", "-inf", "1e999", "1,000.5", "1,2,3"]
    )
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            rda.parse_mg(text)


class TestMath:
    def test_exact_rda_is_one_hundred_percent(self):
        for nutrient in rda.NUTRIENTS:
            assert rda.mg_to_rda_percent(nutrient.rda_mg, nutrient.rda_mg) == pytest.approx(100.0)

    def test_half_and_double(self):
        assert rda.mg_to_rda_percent(40, 80) == pytest.approx(50.0)
        assert rda.mg_to_rda_percent(160, 80) == pytest.approx(200.0)

    def test_zero(self):
        assert rda.mg_to_rda_percent(0, 14.0) == 0.0


class TestFormatRdaResult:
    def test_value_rounded_to_two_decimals(self):
        assert rda.format_rda_result("1", 14.0) == "7.14"

    def test_whole_percentage(self):
        assert rda.format_rda_result("80", 80.0) == "100.0"

    def test_blank_clears_result(self):
        assert rda.format_rda_result("", 80.0) == ""
        assert rda.format_rda_result("   ", 80.0) == ""

    @pytest.mark.parametrize("text", ["abc", "-5", "nan", "inf"])
    def test_invalid_input_message(self, text):
        assert rda.format_rda_result(text, 80.0) == rda.INVALID_INPUT_MESSAGE

    def test_decimal_comma(self):
        assert rda.format_rda_result("0,4", 0.8) == "50.0"


class TestCalculate:
    def _vars(self, *inputs: str):
        mg = [FakeVar(v) for v in inputs]
        results = [FakeVar("stale") for _ in inputs]
        return mg, results

    def test_each_field_uses_its_own_reference(self):
        mg, results = self._vars("0.8", "80", "14", "800")
        rda.calculate(mg, results)
        assert [r.get() for r in results] == ["100.0"] * 4

    def test_cleared_field_drops_stale_result(self):
        mg, results = self._vars("", "40", "", "")
        rda.calculate(mg, results)
        assert [r.get() for r in results] == ["", "50.0", "", ""]

    def test_invalid_field_does_not_affect_others(self):
        mg, results = self._vars("x", "80", "-3", "400")
        rda.calculate(mg, results)
        assert [r.get() for r in results] == [
            rda.INVALID_INPUT_MESSAGE, "100.0", rda.INVALID_INPUT_MESSAGE, "50.0"
        ]
