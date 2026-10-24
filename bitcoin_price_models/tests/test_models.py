"""Tests for models: Golden Ratio bands, power law, Rainbow bands, era highs."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

import config
import models


class TestGoldenRatioBands:
    WINDOW = 4

    def _frame(self, prices, start="2020-01-01"):
        dates = pd.date_range(start, periods=len(prices), freq="D")
        return pd.DataFrame({"Date": dates, "Close": prices})

    def test_warm_up_is_nan_then_mean(self):
        bands = models.compute_golden_ratio_bands(
            self._frame([1.0, 2.0, 3.0, 4.0, 5.0]), window=self.WINDOW, multipliers=[2]
        )
        assert bands["MA"].iloc[: self.WINDOW - 1].isna().all()
        assert bands["MA"].iloc[self.WINDOW - 1] == pytest.approx(2.5)
        assert bands["MA"].iloc[self.WINDOW] == pytest.approx(3.5)

    def test_constant_price_gives_scaled_bands(self):
        bands = models.compute_golden_ratio_bands(
            self._frame([10.0] * 6), window=self.WINDOW, multipliers=[1.6, 5]
        )
        last = bands.iloc[-1]
        assert last["MA"] == pytest.approx(10.0)
        assert last[1.6] == pytest.approx(16.0)
        assert last[5] == pytest.approx(50.0)

    def test_gaps_are_resampled_to_daily(self):
        frame = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2020-01-01", "2020-01-04", "2020-01-05"]),
                "Close": [1.0, 4.0, 5.0],
            }
        )
        bands = models.compute_golden_ratio_bands(frame, window=self.WINDOW, multipliers=[])
        assert len(bands) == 5
        assert bands["Date"].tolist() == list(pd.date_range("2020-01-01", periods=5))
        # Days 2 and 3 carry the last known price forward: mean(1, 1, 1, 4)
        assert bands["MA"].iloc[3] == pytest.approx(1.75)
        assert bands["MA"].iloc[:3].isna().all()

    def test_default_multipliers(self):
        assert config.GOLDEN_RATIO_MULTIPLIERS == [1.6, 2, 3, 5]
        assert config.MOVING_AVERAGE_DAYS == 350
        bands = models.compute_golden_ratio_bands(self._frame([1.0, 2.0]), window=2)
        assert list(bands.columns) == ["Date", "MA", *config.GOLDEN_RATIO_MULTIPLIERS]

    def test_short_data_is_all_nan(self):
        bands = models.compute_golden_ratio_bands(self._frame([1.0, 2.0, 3.0]), window=self.WINDOW)
        assert bool(bands["MA"].isna().all())
        assert bool(bands[5].isna().all())


HALVING_DATES = [
    dt.datetime(2012, 11, 28),
    dt.datetime(2016, 7, 9),
    dt.datetime(2020, 5, 11),
    dt.datetime(2024, 4, 20),
]


GENESIS = pd.Timestamp("2009-01-03")
SLOPE = 5.8
INTERCEPT = -17.0
DAY = pd.Timedelta(days=1)


def power_law_frame(noise=None, start="2010-06-01", periods=200, step_days=30):
    """Build a Date/Close frame on the exact power law, optionally with log10 noise."""
    dates = pd.date_range(start, periods=periods, freq=f"{step_days}D")
    days = np.asarray((dates - GENESIS) / DAY, dtype=float)
    log_price = SLOPE * np.log10(days) + INTERCEPT
    if noise is not None:
        log_price = log_price + noise(len(dates))
    return pd.DataFrame({"Date": dates, "Close": 10**log_price})


def noisy_fit():
    """Return a frame with deterministic log10 noise and its fit."""
    frame = power_law_frame(noise=lambda n: 0.3 * np.sin(np.arange(n)))
    return frame, models.fit_power_law(frame)


class TestFitPowerLaw:
    def test_recovers_known_slope_and_intercept(self):
        fit = models.fit_power_law(power_law_frame())
        assert fit.slope == pytest.approx(SLOPE, abs=1e-9)
        assert fit.intercept == pytest.approx(INTERCEPT, abs=1e-9)
        assert fit.r_squared == pytest.approx(1.0)
        assert fit.residual_min == pytest.approx(0.0, abs=1e-9)
        assert fit.residual_max == pytest.approx(0.0, abs=1e-9)
        assert fit.points == 200

    def test_non_positive_points_are_skipped(self):
        frame = power_law_frame()
        bad = pd.DataFrame(
            {
                "Date": pd.to_datetime(
                    ["2008-12-01", "2009-01-03", "2011-01-01", "2012-01-01"]
                ),
                "Close": [5.0, 5.0, -1.0, 0.0],
            }
        )
        fit = models.fit_power_law(pd.concat([frame, bad], ignore_index=True))
        assert fit.points == len(frame)
        assert fit.slope == pytest.approx(SLOPE, abs=1e-9)

    def test_too_few_points_raise(self):
        one = pd.DataFrame({"Date": [pd.Timestamp("2012-01-01")], "Close": [10.0]})
        with pytest.raises(ValueError):
            models.fit_power_law(one)

    def test_unusable_points_do_not_count(self):
        frame = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2008-01-01", "2012-01-01", "2013-01-01"]),
                "Close": [10.0, 0.0, 20.0],
            }
        )
        with pytest.raises(ValueError):
            models.fit_power_law(frame)

    def test_noisy_fit_has_residual_range_and_lower_r_squared(self):
        _, fit = noisy_fit()
        assert fit.residual_min < 0 < fit.residual_max
        assert 0.0 < fit.r_squared < 1.0


class TestPowerLawPrice:
    def test_matches_the_formula(self):
        fit = models.fit_power_law(power_law_frame())
        dates = pd.to_datetime(["2015-01-01", "2020-01-01"])
        result = models.power_law_price(fit, dates)
        days = np.asarray((dates - GENESIS) / DAY, dtype=float)
        expected = 10 ** (SLOPE * np.log10(days) + INTERCEPT)
        assert list(result.index) == list(dates)
        assert result.to_numpy() == pytest.approx(expected, rel=1e-6)

    def test_dates_up_to_genesis_are_nan(self):
        fit = models.fit_power_law(power_law_frame())
        dates = pd.to_datetime(["2008-01-01", "2009-01-03"])
        assert bool(models.power_law_price(fit, dates).isna().all())


class TestProjectionDates:
    LAST = dt.datetime(2026, 10, 24)

    def test_spans_day_after_last_to_estimate_plus_four_years(self):
        estimate = dt.datetime(2028, 4, 20, 13, 45)
        dates = models.projection_dates(self.LAST, estimate, 4)
        assert dates[0] == pd.Timestamp("2026-10-25")
        assert dates[-1] == pd.Timestamp("2032-04-20")
        assert (dates.to_series().diff().dropna() == DAY).all()

    def test_default_years_come_from_config(self):
        estimate = dt.datetime(2028, 4, 20)
        dates = models.projection_dates(self.LAST, estimate)
        end = pd.Timestamp(estimate) + pd.DateOffset(
            years=config.PROJECTION_YEARS_AFTER_NEXT_HALVING
        )
        assert dates[-1] == end

    def test_config_defaults(self):
        assert config.PROJECTION_YEARS_AFTER_NEXT_HALVING == 4
        assert config.PROJECTION_FALLBACK_YEARS == 6

    def test_no_estimate_falls_back_to_default_horizon(self):
        dates = models.projection_dates(self.LAST, None)
        assert dates[0] == pd.Timestamp("2026-10-25")
        assert dates[-1] == pd.Timestamp("2032-10-24")

    def test_end_before_start_is_empty(self):
        assert len(models.projection_dates(self.LAST, dt.datetime(2020, 1, 1), 1)) == 0


class TestRainbowBands:
    def test_ten_monotonic_edges_giving_nine_bands(self):
        _, fit = noisy_fit()
        bands = models.rainbow_bands(fit, pd.date_range("2024-01-01", periods=5))
        edges = bands.drop(columns="Date")
        assert list(edges.columns) == list(range(10))
        assert len(config.RAINBOW_BANDS) == 9
        assert (edges.diff(axis=1).iloc[:, 1:] > 0).all().all()

    def test_edges_are_evenly_spaced_in_log(self):
        _, fit = noisy_fit()
        bands = models.rainbow_bands(fit, pd.date_range("2024-01-01", periods=1))
        logs = np.log10(bands.drop(columns="Date").iloc[0].to_numpy(dtype=float))
        gaps = np.diff(logs)
        assert gaps == pytest.approx(np.full(9, gaps[0]))

    def test_history_lies_within_outer_edges(self):
        frame, fit = noisy_fit()
        bands = models.rainbow_bands(fit, frame["Date"])
        close = frame["Close"].to_numpy()
        assert (close >= bands[0].to_numpy() * (1 - 1e-9)).all()
        assert (close <= bands[9].to_numpy() * (1 + 1e-9)).all()

    def test_outer_edges_touch_the_extreme_residuals(self):
        frame, fit = noisy_fit()
        bands = models.rainbow_bands(fit, frame["Date"])
        ratio_low = (frame["Close"] / bands[0]).min()
        ratio_high = (bands[9] / frame["Close"]).min()
        assert ratio_low == pytest.approx(1.0)
        assert ratio_high == pytest.approx(1.0)

    def test_bottom_edge_is_fair_value_shifted_by_min_residual(self):
        _, fit = noisy_fit()
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        bands = models.rainbow_bands(fit, dates)
        fair = models.power_law_price(fit, dates).to_numpy()
        assert bands[0].to_numpy() == pytest.approx(fair * 10**fit.residual_min)

    def test_band_names_and_colors(self):
        assert config.RAINBOW_BANDS[0] == ("Fire sale!", "#4472c4")
        assert config.RAINBOW_BANDS[-1] == ("Maximum bubble territory", "#c00200")


class TestEraHighs:
    def _frame(self, rows):
        return pd.DataFrame(
            {
                "Date": pd.to_datetime([d for d, _ in rows]),
                "Close": [p for _, p in rows],
            }
        )

    def test_one_high_per_era_including_current(self):
        frame = self._frame(
            [
                ("2012-01-01", 5.0),
                ("2012-06-01", 12.0),
                ("2013-01-01", 100.0),
                ("2013-12-01", 1000.0),
                ("2014-01-01", 300.0),
                ("2016-01-01", 20.0),
                ("2017-12-01", 800.0),
            ]
        )
        halvings = [dt.datetime(2012, 11, 28), dt.datetime(2016, 7, 9)]
        assert models.era_highs(frame, halvings) == [
            models.EraHigh(date=dt.datetime(2012, 6, 1), price=12.0),
            models.EraHigh(date=dt.datetime(2013, 12, 1), price=1000.0),
            models.EraHigh(date=dt.datetime(2017, 12, 1), price=800.0),
        ]

    def test_halving_day_belongs_to_the_new_era(self):
        frame = self._frame(
            [("2012-11-27", 10.0), ("2012-11-28", 50.0), ("2012-11-29", 20.0)]
        )
        highs = models.era_highs(frame, [dt.datetime(2012, 11, 28)])
        assert highs == [
            models.EraHigh(date=dt.datetime(2012, 11, 27), price=10.0),
            models.EraHigh(date=dt.datetime(2012, 11, 28), price=50.0),
        ]

    def test_halving_time_within_the_day_belongs_to_the_new_era(self):
        frame = self._frame(
            [("2024-04-19", 10.0), ("2024-04-20", 50.0), ("2024-04-21", 20.0)]
        )
        highs = models.era_highs(frame, [dt.datetime(2024, 4, 20, 0, 9)])
        assert highs == [
            models.EraHigh(date=dt.datetime(2024, 4, 19), price=10.0),
            models.EraHigh(date=dt.datetime(2024, 4, 20), price=50.0),
        ]

    def test_empty_eras_are_skipped(self):
        frame = self._frame([("2013-01-01", 100.0), ("2021-01-01", 60000.0)])
        highs = models.era_highs(frame, HALVING_DATES)
        assert [h.price for h in highs] == [100.0, 60000.0]

    def test_no_halvings_gives_a_single_era(self):
        frame = self._frame(
            [("2013-01-01", 100.0), ("2014-01-01", 900.0), ("2015-01-01", 5.0)]
        )
        assert models.era_highs(frame, []) == [
            models.EraHigh(date=dt.datetime(2014, 1, 1), price=900.0)
        ]

    def test_date_is_a_plain_datetime(self):
        high = models.era_highs(self._frame([("2013-01-01", 100.0)]), [])[0]
        assert type(high.date) is dt.datetime
