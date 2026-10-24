"""Tests for chart_payload: schema, finite values, bands, labels and halvings."""

import datetime as dt
import json

import pandas as pd
import pytest

import chart_payload
import config
from halvings import HalvingInfo

PAST = [dt.datetime(2012, 11, 28), dt.datetime(2016, 7, 9)]
NEXT = dt.datetime(2020, 5, 11)


def _frame(days: int = 800, start: str = "2011-01-01") -> pd.DataFrame:
    """Return an exponentially growing daily price frame."""
    dates = pd.date_range(start, periods=days, freq="D")
    closes = [1.0 * 1.004**i for i in range(days)]
    return pd.DataFrame({"Date": dates, "Close": closes})


@pytest.fixture
def payload() -> dict:
    return chart_payload.build_payload(
        _frame(), HalvingInfo(past=PAST, next_estimate=NEXT), "powerlaw"
    )


class TestSchema:
    def test_top_level_keys(self, payload):
        assert set(payload) == {
            "meta",
            "price",
            "golden",
            "powerlaw",
            "eraHighs",
            "halvings",
        }

    def test_meta(self, payload):
        meta = payload["meta"]
        assert meta["initialMode"] == "powerlaw"
        assert meta["lastDate"] == "2013-03-10"
        generated = dt.datetime.fromisoformat(meta["generatedAt"])
        assert generated.utcoffset() == dt.timedelta(0)

    def test_meta_carries_the_price_colour(self, payload):
        assert payload["meta"]["priceColor"] == config.PRICE_COLOR

    def test_price_points_are_time_value_pairs(self, payload):
        first = payload["price"][0]
        assert first == {"time": "2011-01-01", "value": 1.0}
        assert len(payload["price"]) == 800

    def test_powerlaw_keys_and_types(self, payload):
        law = payload["powerlaw"]
        assert set(law) == {"fairValue", "projectionStart", "fit", "rainbow"}
        assert set(law["fit"]) == {"slope", "intercept", "rSquared"}
        assert all(isinstance(v, float) for v in law["fit"].values())
        assert law["fairValue"]["key"] == "fair"
        assert isinstance(law["projectionStart"], str)

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="unknown mode"):
            chart_payload.build_payload(
                _frame(), HalvingInfo(past=[], next_estimate=None), "rainbow"
            )

    def test_empty_frame_is_rejected(self):
        empty = pd.DataFrame({"Date": [], "Close": []})
        with pytest.raises(ValueError, match="no price data"):
            chart_payload.build_payload(
                empty, HalvingInfo(past=[], next_estimate=None), "golden"
            )

    def test_duplicate_dates_keep_the_last_close(self):
        frame = _frame(5)
        frame = pd.concat([frame.iloc[:1].assign(Close=99.0), frame], ignore_index=True)
        result = chart_payload.build_payload(
            frame, HalvingInfo(past=[], next_estimate=None), "golden"
        )
        assert len(result["price"]) == 5
        assert result["price"][0]["value"] == 1.0


    def test_intraday_points_are_cut_to_the_day_before_deduping(self):
        frame = _frame(5)
        intraday = pd.DataFrame(
            {"Date": [pd.Timestamp("2011-01-02 13:30")], "Close": [99.0]}
        )
        frame = pd.concat([frame, intraday], ignore_index=True)
        result = chart_payload.build_payload(
            frame, HalvingInfo(past=[], next_estimate=None), "golden"
        )
        times = [p["time"] for p in result["price"]]
        assert times == [
            "2011-01-01",
            "2011-01-02",
            "2011-01-03",
            "2011-01-04",
            "2011-01-05",
        ]
        assert result["price"][1]["value"] == 99.0
        assert result["meta"]["lastDate"] == "2011-01-05"


class TestFiniteValues:
    def test_json_serialises_without_nan(self, payload):
        json.dumps(payload, allow_nan=False)

    def test_moving_average_warm_up_is_dropped(self, payload):
        data = payload["golden"]["ma"]["data"]
        assert len(data) == 800 - config.MOVING_AVERAGE_DAYS + 1
        assert data[0]["time"] == "2011-12-16"

    def test_nan_close_is_dropped_from_price(self):
        frame = _frame(5)
        frame.loc[2, "Close"] = float("nan")
        result = chart_payload.build_payload(
            frame, HalvingInfo(past=[], next_estimate=None), "golden"
        )
        assert len(result["price"]) == 4
        json.dumps(result, allow_nan=False)


class TestGolden:
    def test_only_four_bands_with_one_golden(self, payload):
        bands = payload["golden"]["bands"]
        assert [b["multiplier"] for b in bands] == [1.6, 2, 3, 5]
        assert [b["golden"] for b in bands] == [True, False, False, False]
        assert [b["key"] for b in bands] == ["x1.6", "x2", "x3", "x5"]
        assert bands[0]["label"] == "1.6x Multiplier"
        assert bands[0]["color"] == config.GOLDEN_BAND_COLOR

    def test_band_values_are_multiples_of_the_average(self, payload):
        ma = payload["golden"]["ma"]["data"][-1]["value"]
        top = payload["golden"]["bands"][-1]["data"][-1]["value"]
        assert top == pytest.approx(5 * ma, rel=1e-4)


class TestPowerLaw:
    def test_rainbow_has_nine_bands_and_ten_equal_edges(self, payload):
        rainbow = payload["powerlaw"]["rainbow"]
        assert len(rainbow["bands"]) == 9
        assert rainbow["bands"][0] == {"name": "Fire sale!", "color": "#4472c4"}
        assert len(rainbow["edges"]) == 10
        fair = len(payload["powerlaw"]["fairValue"]["data"])
        assert {len(edge) for edge in rainbow["edges"]} == {fair}

    def test_edges_share_the_fair_value_dates(self, payload):
        fair_times = [p["time"] for p in payload["powerlaw"]["fairValue"]["data"]]
        for edge in payload["powerlaw"]["rainbow"]["edges"]:
            assert [p["time"] for p in edge] == fair_times

    def test_projection_starts_after_the_last_date(self, payload):
        assert payload["powerlaw"]["projectionStart"] > payload["meta"]["lastDate"]
        times = [p["time"] for p in payload["powerlaw"]["fairValue"]["data"]]
        assert times[-1] > payload["powerlaw"]["projectionStart"]
        assert payload["powerlaw"]["projectionStart"] in times

    def test_projection_runs_years_past_the_next_halving(self, payload):
        last = payload["powerlaw"]["fairValue"]["data"][-1]["time"]
        assert last == "2024-05-11"

    def test_without_an_estimate_the_fallback_horizon_applies(self):
        result = chart_payload.build_payload(
            _frame(), HalvingInfo(past=[], next_estimate=None), "golden"
        )
        last = result["powerlaw"]["fairValue"]["data"][-1]["time"]
        assert last == "2019-03-10"


    @pytest.mark.parametrize(
        "stale", [dt.datetime(2013, 3, 10, 5, 0), dt.datetime(2012, 1, 1)]
    )
    def test_stale_estimate_is_dropped_and_the_fallback_applies(self, stale):
        result = chart_payload.build_payload(
            _frame(), HalvingInfo(past=PAST, next_estimate=stale), "powerlaw"
        )
        assert result["halvings"]["next"] is None
        last = result["powerlaw"]["fairValue"]["data"][-1]["time"]
        assert last == "2019-03-10"


class TestEraHighsAndHalvings:
    def test_era_highs_are_labelled(self, payload):
        highs = payload["eraHighs"]
        assert len(highs) == 2
        assert all(h["label"].startswith("$") for h in highs)
        assert highs[-1]["time"] == "2013-03-10"
        assert highs[-1]["label"] == chart_payload.format_compact_dollars(
            highs[-1]["price"]
        )

    def test_halving_labels(self, payload):
        halvings = payload["halvings"]
        assert halvings["past"] == [
            {"time": "2012-11-28", "label": "Halving 2012-11-28"},
            {"time": "2016-07-09", "label": "Halving 2016-07-09"},
        ]
        assert halvings["next"] == {
            "time": "2020-05-11",
            "label": "Next halving (est.) 2020-05-11",
        }

    def test_next_is_null_without_an_estimate(self):
        result = chart_payload.build_payload(
            _frame(), HalvingInfo(past=PAST, next_estimate=None), "golden"
        )
        assert result["halvings"]["next"] is None
        json.dumps(result, allow_nan=False)


class TestFormatCompactDollars:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (33.8, "$33.80"),
            (0.05, "$0.05"),
            (999.99, "$999.99"),
            (1_140, "$1.14K"),
            (19_300, "$19.3K"),
            (124_800, "$124.8K"),
            (1_200_000, "$1.2M"),
            (2_500_000_000, "$2.5B"),
            (999_990, "$1.0M"),
            (999.999, "$1.00K"),
        ],
    )
    def test_examples(self, value, expected):
        assert chart_payload.format_compact_dollars(value) == expected
