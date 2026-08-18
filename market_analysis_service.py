# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from .aggregator import KhromalabsAtariaCryptoAggregator
from .technical_analysis import TechnicalAnalysisEngine

# =============================================================================
# INDUSTRY-STANDARD INDICATOR PARAMETERS
# =============================================================================
# These are universally accepted defaults defined by the original authors of
# each indicator. Changing them produces non-standard readings that cannot be
# compared to values from other platforms (TradingView, Binance, etc.).
# They are NOT configurable because they are mathematical constants, not
# strategy parameters.

RSI_PERIOD = 14        # Wilder's Relative Strength Index (1978)
MACD_FAST = 12         # Appel's Moving Average Convergence Divergence
MACD_SLOW = 26         # standard 12/26/9 triple
MACD_SIGNAL = 9        #
BB_PERIOD = 20         # Bollinger Bands: 20-period SMA center
BB_STD_DEV = 2.0       # Bollinger Bands: 2 standard deviations
VOLUME_PERIOD = 20     # Volume moving average lookback
EMA_SHORT = 12         # Short EMA for crossover detection
EMA_LONG = 26          # Long EMA for crossover detection
ATR_PERIOD = 14        # Average True Range (Wilder, 14 periods)
OB_MIN_IMPULSE_ATR = 1.8  # Minimum ATR multiple for order block impulse

# =============================================================================
# STRATEGY-DEPENDENT INTERVAL PROFILES (configurable)
# =============================================================================
# Unlike the indicator parameters above, these values define HOW SENSITIVE
# the structural detection algorithms are. They are tuning knobs that depend
# on your trading strategy's holding period and signal detection window.
#
# Users can override these via the YAML config under:
#   interval_profiles.<interval>.<parameter>
#
# Parameters:
#
#   sma_short / sma_long (int, candle count):
#     The short and long SMA windows for crossover detection.
#     - 20/50: responsive, catches medium-term moves. Good for scalping
#       and intraday swing.
#     - 50/100: moderate, filters noise on multi-hour timeframes.
#     - 20/200: classic "golden cross / death cross" territory, only fires
#       on major trend shifts.
#     Rule: shorter windows = more signals but more noise.
#
#   bos_lookback (int, candle count, valid range: 3–30):
#     How many candles on EACH SIDE of a pivot are required to confirm it
#     as a swing high/low for Break of Structure detection.
#     The swing detection loop `range(lookback, len(df) - lookback)` excludes
#     the last N candles, so this value directly controls how recent a BOS
#     can be detected:
#       - bos_lookback=4 on 4h → excludes last 16h → detects BOS within ~24h
#       - bos_lookback=6 on 4h → excludes last 24h → detects BOS within ~48h
#       - bos_lookback=24 on 4h → excludes last 96h → only major weekly pivots
#     Rule of thumb: set so (lookback × interval_hours) < your intended
#     signal detection window. Lower = catches recent structures but more
#     noise. Higher = only major pivots but blind to recent action.
#
#   ob_lookback (int, candle count, valid range: 6–120):
#     How far back (in candles) to search for Order Blocks.
#     Older OBs have lower probability of holding but provide more context.
#       - 24 on 4h → looks back 4 days
#       - 48 on 15m → looks back 12 hours
#       - 30 on 1d → looks back 1 month
#     Rule: set according to how long you expect institutional levels to
#     remain relevant for your holding period.
#
# The current defaults are tuned for short-term swing trading with
# 24–48h holding periods and signal detection within the last 24h.

_DEFAULT_INTERVAL_PROFILES = {
    "15m": {
        "sma_short": 20,
        "sma_long": 50,
        "bos_lookback": 6,
        "ob_lookback": 48,
        "obv_lookback": 48,
        "htf_lookback": 120,
        "ema_regime_change_window": 50,
        "median_dev_lookback": 30,
        "median_overextension_atr": 2.0,
        "stop_hostility_lookback": 48,
        "wick_risk": {
            "lookback": 20,
            "wick_atr_multiple": 2.5,
            "min_frequency": 0.25,
            "killer_wick_multiple": 4.0,
            "killer_wick_repetitions": 2,
        },
    },
    "1h": {
        "sma_short": 20,
        "sma_long": 50,
        "bos_lookback": 5,
        "ob_lookback": 36,
        "obv_lookback": 36,
        "htf_lookback": 120,
        "ema_regime_change_window": 30,
        "median_dev_lookback": 30,
        "median_overextension_atr": 2.0,
        "stop_hostility_lookback": 36,
        "wick_risk": {
            "lookback": 20,
            "wick_atr_multiple": 2.5,
            "min_frequency": 0.25,
            "killer_wick_multiple": 4.0,
            "killer_wick_repetitions": 2,
        },
    },
    "4h": {
        "sma_short": 50,
        "sma_long": 100,
        "bos_lookback": 4,
        "ob_lookback": 24,
        "obv_lookback": 20,
        "htf_lookback": 120,
        "ema_regime_change_window": 30,
        "median_dev_lookback": 30,
        "median_overextension_atr": 2.0,
        "stop_hostility_lookback": 24,
        "wick_risk": {
            "lookback": 20,
            "wick_atr_multiple": 2.5,
            "min_frequency": 0.25,
            "killer_wick_multiple": 4.0,
            "killer_wick_repetitions": 2,
        },
    },
    "1d": {
        "sma_short": 20,
        "sma_long": 200,
        "bos_lookback": 6,
        "ob_lookback": 30,
        "obv_lookback": 14,
        "htf_lookback": 120,
        "ema_regime_change_window": 30,
        "median_dev_lookback": 30,
        "median_overextension_atr": 2.0,
        "stop_hostility_lookback": 30,
        "wick_risk": {
            "lookback": 20,
            "wick_atr_multiple": 2.5,
            "min_frequency": 0.25,
        },
    },
}

# Public alias for backward compatibility (tests, external references).
# Skills should use MarketAnalysisService.get_profile() instead.
INTERVAL_PROFILES = _DEFAULT_INTERVAL_PROFILES

# =============================================================================
# BIAS INTERVAL MAPPING (configurable)
# =============================================================================
# Maps a signal timeframe to the next meaningful higher timeframe used for
# directional bias in multi-timeframe analysis.
#
# Users can override/extend via YAML config under:
#   bias_intervals.<signal_interval>: <bias_interval>
#
# Example: adding a custom "2h" signal interval:
#   market_analysis:
#     bias_intervals:
#       2h: "4h"
#     interval_profiles:
#       2h:
#         sma_short: 30
#         sma_long: 75
#         bos_lookback: 5
#         ob_lookback: 30
#
# If no mapping exists for a given interval, multi-timeframe analysis
# gracefully degrades (bias data marked as "unavailable", confluence
# defaults to neutral).

_DEFAULT_BIAS_INTERVALS = {
    "15m": "1h",
    "1h": "4h",
    "4h": "1d",
    "1d": "1w",
}

# Public alias for backward compatibility.
BIAS_INTERVAL = _DEFAULT_BIAS_INTERVALS


# =============================================================================
# STRATEGY-CONFIGURABLE ANALYSIS DEFAULTS
# =============================================================================
# These are tuning parameters for the technical analysis engine methods.
# Unlike the canonical indicator constants above, these control HOW AGGRESSIVE
# or CONSERVATIVE the strategy behaves. Users can override any value via:
#   <section>.<parameter>
#
# Keys MUST match the parameter names in TechnicalAnalysisEngine methods
# exactly, since they are unpacked with ** at call sites.

_ANALYSIS_DEFAULTS: Dict[str, Any] = {
    "buffered_entry": {
        "entry_atr_buffer": 0.3,
        "sl_atr_buffer": 1.5,
        "sl_chop_floor": 1.5,
        "sl_chop_ceiling": 2.5,
        "sl_chop_low": 30.0,
        "sl_chop_high": 100.0,
        "use_choppiness_sl": True,
        "max_sl_atr_buffer": 2.5,
        "use_macro_drive": True,
        "min_macro_entry_buffer": 0.05,
        "drive_floor": 0.4,
        "drive_ceiling": 0.8,
     },
    "key_levels": {
        "atr_multiples": [1.3, 2.5],
        "max_levels": 8,
        "ob_distance_tolerance_atr": 1.0,
        "confluence_threshold_atr": 0.3,
    },
    "range_boundaries": {
        "cluster_atr_tolerance": 0.5,
        "min_touches": 2,
    },
    "order_blocks": {
        "min_impulse_atr": 1.5,
        "ob_validation_mode": "intermediate",
        "mitigation_mode": "wick",
    },
    "trend_continuation": {
        "ema_fast": 12,
        "ema_slow": 50,
        "pullback_lookback": 5,
        "proximity_atr_mult": 0.5,
        "vol_contraction_threshold": 0.8,
        "vol_contraction_strict": 0.7,
        "min_body_ratio": 0.5,
        "volume_period": 20,
    },
    # TODO: Consider stricter thresholds after production validation.
    # Current defaults are intentionally lenient (wick > 2.5× ATR, >= 25%
    # frequency) to avoid over-filtering. If wick-driven losses persist,
    # tighten to wick_atr_multiple=2.0 and min_frequency=0.20.
    "wick_risk": {
        "lookback": 20,
        "wick_atr_multiple": 2.5,
        "min_frequency": 0.25,
        "killer_wick_multiple": 4.0,
        "killer_wick_repetitions": 2,
    },
}


class MarketAnalysisService:
    """
    Orchestrates market data fetching and technical analysis.
    This service is shared across skills to avoid code duplication.
    """

    def __init__(
        self,
        aggregator: KhromalabsAtariaCryptoAggregator,
        config_manager=None,
    ):
        self.aggregator = aggregator
        self.logger = logging.getLogger(__name__)
        self._interval_profiles = self._load_profiles(config_manager)
        self._bias_intervals = self._load_bias_intervals(config_manager)
        self.config = self._load_analysis_config(config_manager)

    def _load_profiles(self, config_manager) -> Dict[str, Dict[str, int]]:
        """
        Load interval profiles from config, merging user overrides on top of
        hardcoded defaults. Custom intervals defined only in config are also
        supported. Values are clamped to valid bounds with a warning.
        """
        if config_manager is None:
            return _DEFAULT_INTERVAL_PROFILES.copy()

        # Start with defaults
        profiles = {k: dict(v) for k, v in _DEFAULT_INTERVAL_PROFILES.items()}

        # Load user config (may contain overrides and/or new intervals)
        user_profiles = config_manager.get(
            "interval_profiles", {}
        )
        if not isinstance(user_profiles, dict):
            self.logger.warning(
                "interval_profiles config is not a dict, using"
                " defaults"
            )
            return profiles

        # Merge user overrides and custom intervals
        for interval, user_values in user_profiles.items():
            if not isinstance(user_values, dict):
                self.logger.warning(
                    f"interval_profiles.{interval} is not a"
                    " dict, skipping"
                )
                continue

            if interval in profiles:
                # Override: merge user values on top of defaults
                profiles[interval].update(user_values)
            else:
                # Custom interval: require at least sma_short, sma_long, bos_lookback, ob_lookback
                required_keys = {
                    "sma_short",
                    "sma_long",
                    "bos_lookback",
                    "ob_lookback",
                }
                if not required_keys.issubset(user_values.keys()):
                    missing = required_keys - set(user_values.keys())
                    self.logger.warning(
                        f"Custom interval '{interval}' missing required keys "
                        f"{missing}, skipping"
                    )
                    continue
                profiles[interval] = dict(user_values)

        # Validate and clamp bounds
        for interval, profile in profiles.items():
            bos = profile.get("bos_lookback", 6)
            if bos < 3 or bos > 30:
                clamped = max(3, min(30, bos))
                self.logger.warning(
                    f"interval_profiles.{interval}.bos_lookback={bos}"
                    f" out of valid range [3, 30], clamped to {clamped}"
                )
                profile["bos_lookback"] = clamped

            ob = profile.get("ob_lookback", 24)
            if ob < 6 or ob > 120:
                clamped = max(6, min(120, ob))
                self.logger.warning(
                    f"interval_profiles.{interval}.ob_lookback={ob}"
                    f" out of valid range [6, 120], clamped to {clamped}"
                )
                profile["ob_lookback"] = clamped

            sma_short = profile.get("sma_short", 20)
            sma_long = profile.get("sma_long", 50)
            if sma_short >= sma_long:
                self.logger.warning(
                    f"interval_profiles.{interval}: "
                    f"sma_short ({sma_short}) >= sma_long ({sma_long}), "
                    "this will produce invalid crossover signals"
                )

        return profiles

    def _load_bias_intervals(self, config_manager) -> Dict[str, str]:
        """
        Load bias interval mappings from config, merging user overrides
        on top of hardcoded defaults. Custom mappings are supported.
        """
        if config_manager is None:
            return _DEFAULT_BIAS_INTERVALS.copy()

        # Start with defaults
        bias = dict(_DEFAULT_BIAS_INTERVALS)

        # Load user config
        user_bias = config_manager.get("bias_intervals", {})
        if not isinstance(user_bias, dict):
            self.logger.warning(
                "bias_intervals config is not a dict, using"
                " defaults"
            )
            return bias

        # Merge: user overrides and new entries
        for signal_interval, bias_interval in user_bias.items():
            if not isinstance(bias_interval, str):
                self.logger.warning(
                    f"bias_intervals.{signal_interval} value"
                    f" must be a string, got {type(bias_interval).__name__},"
                    " skipping"
                )
                continue
            bias[signal_interval] = bias_interval

        return bias

    def _load_analysis_config(self, config_manager) -> Dict[str, Any]:
        """
        Loads strategy-configurable analysis parameters from config,
        merging user overrides onto _ANALYSIS_DEFAULTS. Single source of
        truth for all TechnicalAnalysisEngine tuning parameters.

        Config path: <section>.<parameter>
        """
        if config_manager is None:
            return self._merge_defaults(_ANALYSIS_DEFAULTS, {})

        user_config = config_manager.get("market_analysis", {}) or {}
        if not isinstance(user_config, dict):
            self.logger.warning(
                "market_analysis config is not a dict, using defaults"
            )
            return self._merge_defaults(_ANALYSIS_DEFAULTS, {})

        return self._merge_defaults(_ANALYSIS_DEFAULTS, user_config)

    @staticmethod
    def _merge_defaults(defaults: dict, overrides: dict) -> dict:
        """
        Recursively merges user overrides onto a defaults dict.
        Only keys present in defaults are considered (unknown keys ignored).
        """
        merged = {}
        for key, default_val in defaults.items():
            override_val = overrides.get(key)
            if isinstance(default_val, dict) and isinstance(override_val, dict):
                merged[key] = MarketAnalysisService._merge_defaults(
                    default_val, override_val
                )
            elif override_val is not None:
                merged[key] = override_val
            else:
                if isinstance(default_val, dict):
                    merged[key] = default_val.copy()
                elif isinstance(default_val, list):
                    merged[key] = default_val.copy()
                else:
                    merged[key] = default_val
        return merged

    def _error_result(
        self,
        coin_id: str,
        vs_currency: str,
        error: str,
    ) -> Dict[str, Any]:
        """Returns an error dict and logs the reason."""
        self.logger.warning(
            f"MarketAnalysisService: Analysis failed for "
            f"{coin_id}-{vs_currency}: {error}"
        )
        return {"error": error}

    def get_profile(self, interval: str) -> Optional[Dict[str, int]]:
        """
        Returns the interval profile for the given timeframe, or None if
        the interval is not configured.
        """
        return self._interval_profiles.get(interval.lower())

    def get_bias_interval(self, interval: str) -> Optional[str]:
        """
        Returns the higher timeframe used for directional bias analysis,
        or None if no mapping is configured for this interval.
        """
        return self._bias_intervals.get(interval)

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        """
        Converts an interval string (e.g., '4h', '1d', '15m') to milliseconds.
        """
        if interval.endswith("d"):
            days = int(interval[:-1])
            return days * 24 * 60 * 60 * 1000
        elif interval.endswith("w"):
            weeks = int(interval[:-1])
            return weeks * 7 * 24 * 60 * 60 * 1000
        elif interval.endswith("h"):
            hours = int(interval[:-1])
            return hours * 60 * 60 * 1000
        elif interval.endswith("m"):
            minutes = int(interval[:-1])
            return minutes * 60 * 1000
        else:
            # Fallback: assume hourly
            return 60 * 60 * 1000

    @staticmethod
    def _trim_forming_candle(df: pd.DataFrame, interval: str) -> pd.DataFrame:
        """
        Removes the last candle from the DataFrame if it is still forming
        (i.e., its time window has not yet closed).

        A candle is considered "forming" if:
            open_time + interval_duration > current_time

        This ensures all indicators and signals operate on confirmed
        (closed) candle data only.
        """
        if df.empty:
            return df

        interval_ms = MarketAnalysisService._interval_to_ms(interval)
        now_ms = int(time.time() * 1000)

        last_open_ms = int(df.index[-1].timestamp() * 1000)
        if last_open_ms + interval_ms > now_ms:
            return df.iloc[:-1]

        return df

    @staticmethod
    def _candles_per_day(interval: str) -> int:
        """
        Returns the number of candles per calendar day for a given interval string.
        E.g., "1d" → 1, "4h" → 6, "1h" → 24, "2h" → 12, "15m" → 96.
        """
        if interval.endswith("d"):
            days = int(interval[:-1])
            return max(1, 1 // days)
        elif interval.endswith("h"):
            hours = int(interval[:-1])
            return 24 // hours
        elif interval.endswith("m"):
            minutes = int(interval[:-1])
            return (24 * 60) // minutes
        else:
            # Fallback: assume hourly
            return 24

    async def get_macro_trend(
        self,
        macro_coins: List[str],
        vs_currency: str,
        adx_period: int = 14,
        momentum_days: int = 5,
        momentum_interval: str = "4h",
        momentum_include_current_candle: bool = False,
        daily_limit: int = 30,
    ) -> Dict[str, Any]:
        """
        Assesses the macro market trend by analyzing major coins (e.g., BTC, ETH)
        using ADX for direction/strength and rolling momentum for context.

        ADX is calculated on 1d candles for stable trend direction.
        Momentum is calculated on a configurable interval (default 4h) for
        rolling intraday updates.

        Returns a market-cap-weighted overall score.
        """
        coins_data: Dict[str, Dict[str, Any]] = {}
        total_market_cap = 0.0

        # Calculate momentum candle limit from days and interval
        cpd = self._candles_per_day(momentum_interval)
        momentum_candle_limit = momentum_days * cpd
        # Fetch one extra candle so we can compute diff from the start
        momentum_fetch_limit = momentum_candle_limit + 1

        # Fetch daily OHLCV (for ADX), momentum OHLCV, and price concurrently
        daily_ohlcv_tasks = {
            coin: self.aggregator.get_consensus_ohlcv(
                coin_id=coin,
                vs_currency=vs_currency,
                interval="1d",
                limit=daily_limit,
            )
            for coin in macro_coins
        }
        momentum_ohlcv_tasks = {
            coin: self.aggregator.get_consensus_ohlcv(
                coin_id=coin,
                vs_currency=vs_currency,
                interval=momentum_interval,
                limit=momentum_fetch_limit,
            )
            for coin in macro_coins
        }
        price_tasks = {
            coin: self.aggregator.get_consensus_price(
                coin_id=coin,
                vs_currency=vs_currency,
            )
            for coin in macro_coins
        }

        all_tasks = {}
        for coin in macro_coins:
            all_tasks[f"{coin}_daily_ohlcv"] = daily_ohlcv_tasks[coin]
            all_tasks[f"{coin}_momentum_ohlcv"] = momentum_ohlcv_tasks[coin]
            all_tasks[f"{coin}_price"] = price_tasks[coin]

        results = await asyncio.gather(
            *all_tasks.values(), return_exceptions=True
        )
        results_map = dict(zip(all_tasks.keys(), results))

        for coin in macro_coins:
            daily_ohlcv_result = results_map.get(f"{coin}_daily_ohlcv")
            momentum_ohlcv_result = results_map.get(f"{coin}_momentum_ohlcv")
            price_result = results_map.get(f"{coin}_price")

            # Handle exceptions from gather
            if isinstance(daily_ohlcv_result, Exception):
                self.logger.warning(
                    f"Macro trend: Daily OHLCV fetch failed for {coin}:"
                    f" {daily_ohlcv_result}"
                )
                continue
            if isinstance(momentum_ohlcv_result, Exception):
                self.logger.warning(
                    f"Macro trend: Momentum OHLCV fetch failed for {coin}:"
                    f" {momentum_ohlcv_result}"
                )
                continue
            if isinstance(price_result, Exception):
                self.logger.warning(
                    f"Macro trend: Price fetch failed for {coin}:"
                    f" {price_result}"
                )
                continue

            if (
                not daily_ohlcv_result
                or not daily_ohlcv_result.get("success")
                or not daily_ohlcv_result.get("data")
            ):
                self.logger.warning(
                    f"Macro trend: No daily OHLCV data for {coin}"
                )
                continue
            if (
                not momentum_ohlcv_result
                or not momentum_ohlcv_result.get("success")
                or not momentum_ohlcv_result.get("data")
            ):
                self.logger.warning(
                    f"Macro trend: No momentum OHLCV data for {coin}"
                )
                continue

            # Build DataFrame from daily OHLCV for ADX
            daily_ohlcv_data = [
                candle.__dict__ for candle in daily_ohlcv_result["data"]
            ]
            df_daily = pd.DataFrame(daily_ohlcv_data)
            df_daily["open_time"] = pd.to_datetime(
                df_daily["open_time"], unit="ms"
            )
            df_daily = df_daily.sort_values("open_time").set_index("open_time")

            # Drop the forming (incomplete) candle
            df_daily = self._trim_forming_candle(df_daily, "1d")

            # Calculate ADX on daily candles (stable trend direction)
            adx_result = TechnicalAnalysisEngine.calculate_adx(
                df_daily, period=adx_period
            )

            # Calculate daily ATR for stalling threshold
            daily_atr = TechnicalAnalysisEngine._calculate_atr(
                df_daily, period=adx_period
            )

            # Build DataFrame from momentum-interval OHLCV
            momentum_ohlcv_data = [
                candle.__dict__ for candle in momentum_ohlcv_result["data"]
            ]
            df_momentum = pd.DataFrame(momentum_ohlcv_data)
            df_momentum["open_time"] = pd.to_datetime(
                df_momentum["open_time"], unit="ms"
            )
            df_momentum = df_momentum.sort_values("open_time").set_index(
                "open_time"
            )

            # Drop the forming (incomplete) candle
            df_momentum = self._trim_forming_candle(df_momentum, momentum_interval)

            # Calculate rolling momentum from momentum-interval candles
            momentum_pct = None
            periods_green = 0
            total_periods = min(momentum_candle_limit, len(df_momentum) - 1)

            if total_periods > 0:
                recent_closes = df_momentum["close"].iloc[
                    -(total_periods + 1):
                ]
                period_changes = recent_closes.diff().dropna()

                periods_green = int((period_changes > 0).sum())
                start_price = recent_closes.iloc[0]
                end_price = recent_closes.iloc[-1]
                if start_price > 0:
                    momentum_pct = round(
                        ((end_price - start_price) / start_price) * 100, 2
                    )

            # Get market cap and current price
            market_cap = None
            current_price = None
            change_24h_percent = None
            if (
                price_result
                and price_result.get("success")
                and price_result.get("data")
            ):
                price_data = price_result["data"]
                market_cap = price_data.market_cap
                current_price = price_data.price
                change_24h_percent = price_data.change_24h_percent

            if market_cap and market_cap > 0:
                total_market_cap += market_cap

            # Classify momentum status relative to ADX direction (ratio-based, ATR-relative)
            adx_direction = adx_result.get("direction", "ranging")
            status = self._classify_momentum_status(
                adx_direction,
                momentum_pct,
                periods_green,
                total_periods,
                daily_atr=daily_atr,
                current_price=current_price,
                momentum_days=momentum_days,
            )

            # Calculate green/red ratio for display
            periods_red = total_periods - periods_green
            green_pct = (
                round((periods_green / total_periods) * 100)
                if total_periods > 0
                else 0
            )
            red_pct = 100 - green_pct

            choppiness = TechnicalAnalysisEngine.calculate_choppiness_index(
                df_daily, period=adx_period
            )

            # Compute volume ratio from daily OHLCV
            vol_analysis = TechnicalAnalysisEngine.calculate_volume_analysis(
                df_daily, period=20
            )
            vol_ratio = None
            if vol_analysis.get("values"):
                cv = vol_analysis["values"].get("current_volume")
                av = vol_analysis["values"].get("average_volume")
                if cv and av and av > 0:
                    vol_ratio = cv / av

            drive_result = TechnicalAnalysisEngine.calculate_drive_score(
                vol_ratio=vol_ratio or 1.0,
                adx_value=adx_result.get("adx_value"),
                choppiness=choppiness,
                momentum_pct=momentum_pct,
                w_vol=0.1, w_adx=0.3, w_chop=0.2, w_mom=0.4,
            )

            coins_data[coin] = {
                "direction": adx_direction,
                "strength": adx_result.get("strength", "no_trend"),
                "adx_value": adx_result.get("adx_value"),
                "plus_di": adx_result.get("plus_di"),
                "minus_di": adx_result.get("minus_di"),
                "momentum_pct": momentum_pct,
                "momentum_periods_green": periods_green,
                "momentum_periods_red": periods_red,
                "momentum_periods_total": total_periods,
                "momentum_green_pct": green_pct,
                "momentum_red_pct": red_pct,
                "momentum_interval": momentum_interval,
                "momentum_days": momentum_days,
                "status": status,
                "market_cap": market_cap,
                "current_price": current_price,
                "change_24h_percent": change_24h_percent,
                "choppiness": choppiness,
                "weight": 0.0,  # will be calculated below
                "drive_score": drive_result["score"],
                "weight": 0.0,  # will be calculated below
            }

        if not coins_data:
            return {
                "success": False,
                "error": "Could not fetch macro trend data for any coin.",
            }

        # Calculate market-cap weights
        for coin, data in coins_data.items():
            if total_market_cap > 0 and data["market_cap"]:
                data["weight"] = round(
                    data["market_cap"] / total_market_cap, 4
                )
            else:
                # Equal weight fallback
                data["weight"] = round(1.0 / len(coins_data), 4)

        # Calculate weighted overall score (-1.0 to +1.0)
        # Direction: +1 (bullish), -1 (bearish), 0 (ranging)
        # Strength multiplier: no_trend=0.0, weak=0.3, moderate=0.6, strong=1.0
        # Status dampening: confirmed=1.0x, stalling=0.5x, counter_trend=0.25x
        strength_multipliers = {
            "no_trend": 0.0,
            "weak": 0.3,
            "moderate": 0.6,
            "strong": 1.0,
        }
        direction_signs = {
            "bullish": 1.0,
            "bearish": -1.0,
            "ranging": 0.0,
        }
        status_dampening = {
            "confirmed": 1.0,
            "stalling": 0.5,
            "counter_trend": 0.25,
        }

        weighted_score = 0.0
        for coin, data in coins_data.items():
            direction_sign = direction_signs.get(data["direction"], 0.0)
            strength_mult = strength_multipliers.get(data["strength"], 0.0)
            dampening = status_dampening.get(
                data.get("status", "confirmed"), 1.0
            )
            coin_score = direction_sign * strength_mult * dampening
            weighted_score += coin_score * data["weight"]

        weighted_score = round(weighted_score, 4)

        # Calculate weighted choppiness
        weighted_chop = 0.0
        for coin, data in coins_data.items():
            chop = data.get("choppiness")
            if chop is not None:
                weighted_chop += chop * data["weight"]
        weighted_chop = round(weighted_chop, 2)

        # Calculate weighted drive
        weighted_drive = 0.0
        for coin, data in coins_data.items():
            drive = data.get("drive_score", 0.0)
            weighted_drive += drive * data["weight"]
        weighted_drive = round(weighted_drive, 4)

        # Determine overall direction
        if weighted_score > 0.1:
            overall_direction = "bullish"
        elif weighted_score < -0.1:
            overall_direction = "bearish"
        else:
            overall_direction = "ranging"

        # Determine if momentum is diverging from overall direction
        statuses = [
            data.get("status", "confirmed") for data in coins_data.values()
        ]
        has_counter_trend = "counter_trend" in statuses
        has_stalling = "stalling" in statuses

        if has_counter_trend:
            direction_qualifier = "weakening"
        elif has_stalling:
            direction_qualifier = "but stalling"
        else:
            direction_qualifier = "confirmed"

        # Build summary string
        sign = "+" if weighted_score >= 0 else ""
        if direction_qualifier == "confirmed":
            summary = (
                f"{overall_direction.upper()} {direction_qualifier}"
                f" (bias gauge: {sign}{weighted_score:.2f}/1.00)"
            )
        else:
            summary = (
                f"{overall_direction.upper()} {direction_qualifier}"
                f" (bias gauge: {sign}{weighted_score:.2f}/1.00)"
                " | momentum diverging from trend"
            )

        return {
            "success": True,
            "coins": coins_data,
            "overall": {
                "direction": overall_direction,
                "weighted_score": weighted_score,
                "weighted_choppiness": weighted_chop,
                "weighted_drive": weighted_drive,
                "summary": summary,
            }
        }

    @staticmethod
    def _classify_momentum_status(
        adx_direction: str,
        momentum_pct: Optional[float],
        periods_green: int,
        total_periods: int,
        daily_atr: float = 0.0,
        current_price: Optional[float] = None,
        momentum_days: int = 5,
    ) -> str:
        """
        Classifies the momentum status relative to the ADX trend direction.
        Uses ratio-based thresholds (interval-agnostic) and ATR-relative
        stalling detection.

        Returns one of:
        - "confirmed": momentum aligns with ADX direction
        - "stalling": momentum is weak or mixed
        - "counter_trend": momentum opposes ADX direction

        For ranging markets (no established trend), always returns "confirmed"
        since there is no directional expectation to diverge from.
        """
        if adx_direction == "ranging" or total_periods == 0:
            return "confirmed"

        if momentum_pct is None:
            return "confirmed"

        # Determine counter-trend ratio
        if adx_direction == "bearish":
            # Bearish trend: green periods are counter-trend
            counter_trend_periods = periods_green
            momentum_opposes = momentum_pct > 0
        else:
            # Bullish trend: red periods are counter-trend
            counter_trend_periods = total_periods - periods_green
            momentum_opposes = momentum_pct < 0

        counter_trend_ratio = counter_trend_periods / total_periods

        # Counter-trend: net momentum opposes ADX AND >60% of periods are counter-trend
        if momentum_opposes and counter_trend_ratio > 0.6:
            return "counter_trend"

        # Stalling threshold: ATR-relative
        # Expected movement over momentum_days is approximately
        # daily_atr * sqrt(momentum_days) as a percentage of price.
        # "Stalling" means momentum is less than 30% of that expected movement.
        stalling_pct_threshold = 0.5  # fallback if ATR unavailable
        if daily_atr > 0 and current_price and current_price > 0:
            # ATR as percentage of price, scaled by sqrt(days) for multi-day expectation
            atr_pct = (daily_atr / current_price) * 100
            expected_movement = atr_pct * (momentum_days**0.5)
            stalling_pct_threshold = expected_movement * 0.3

        # Stalling: weak momentum (below ATR-relative threshold) OR >40% counter-trend periods
        if (
            abs(momentum_pct) < stalling_pct_threshold
            or counter_trend_ratio > 0.4
        ):
            return "stalling"

        # Confirmed: momentum aligns with trend
        return "confirmed"

    async def compute_regime(
        self,
        coin_id: str,
        vs_currency: str,
        analysis_results: Dict[str, Any],
        interval: str,
        regime_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Computes the market regime (trending or ranging) for a single asset
        using a composite of 4 signals:
          1. ADX — trend strength
          2. ATR percentile — volatility expansion/compression
          3. BOS recency — structural evidence of a trending move
          4. Choppiness Index — energy dispersion vs concentration

        Classification logic (conservative, hybrid-averse):
        - "trending": requires ADX confirming AND ATR expanding AND choppiness
          not vetoing. BOS alone with low ADX is insufficient.
        - "ranging": ATR compressed OR choppiness high with weak ADX.
        - "indeterminate": conflicting signals — actively blocked from trading.

        Also fetches HTF (higher timeframe) ADX for a zoom-out context label
        when htf_enabled is True.
        """
        adx_threshold = regime_config.get("adx_threshold", 25)
        atr_pct_threshold = regime_config.get("atr_percentile_threshold", 60)
        bos_max_age = regime_config.get("bos_max_age", 6)
        min_signals = regime_config.get("min_signals_for_trending", 2)
        htf_enabled = regime_config.get("htf_enabled", True)
        chop_ranging_threshold = regime_config.get("chop_ranging_threshold", 50)
        chop_trending_threshold = regime_config.get("chop_trending_threshold", 38)

        # Signal 1: ADX
        adx_data = analysis_results.get("adx", {})
        adx_value = adx_data.get("adx_value")
        adx_trending = (adx_value is not None) and (adx_value >= adx_threshold)

        # Signal 2: ATR percentile
        atr_pct_data = analysis_results.get("atr_percentile", {})
        atr_pct_value = atr_pct_data.get("percentile")
        atr_trending = (atr_pct_value is not None) and (
            atr_pct_value >= atr_pct_threshold
        )

        # Signal 3: BOS recency + strength
        market_structure = analysis_results.get("market_structure", {})
        bos_age = market_structure.get("bos_age")
        bos_strength = market_structure.get("bias_strength", "weak")
        bos_fresh = (
            bos_age is not None
            and bos_age <= bos_max_age
            and bos_strength in ("strong", "medium")
        )

        # Signal 4: Choppiness Index (lower = more directional)
        choppiness_value = analysis_results.get("choppiness")
        chop_ranging = (
            choppiness_value is not None
            and choppiness_value > chop_ranging_threshold
        )
        chop_trending = (
            choppiness_value is not None
            and choppiness_value < chop_trending_threshold
        )

        # Four-way regime classification (conservative, hybrid-averse):
        #
        # TRENDING requires:
        #   - ADX confirming AND ATR expanding AND choppiness not vetoing
        #   - OR: ATR expanding AND BOS fresh AND choppiness confirms trending
        #     (BOS alone with high chop or low ADX is a false breakout pattern)
        #
        # RANGING:
        #   - Choppiness high AND ADX below threshold (regardless of ATR/BOS)
        #   - OR: no ATR expansion AND no ADX AND no fresh BOS
        #
        # INDETERMINATE (hybrid market — actively blocked):
        #   - Everything else: ATR expanding but chop high, BOS fresh but
        #     ADX dead, etc. These are the stop-hunt traps.
        trending_count = sum([adx_trending, atr_trending, bos_fresh, chop_trending])

        if adx_trending and atr_trending and not chop_ranging:
            classification = "trending"
        elif atr_trending and bos_fresh and chop_trending:
            # BOS + ATR only counts if choppiness confirms directional energy
            classification = "trending"
        elif chop_ranging and not adx_trending:
            # High choppiness + weak ADX = ranging regardless of ATR/BOS
            classification = "ranging"
        elif not atr_trending and not adx_trending and not bos_fresh:
            classification = "ranging"
        else:
            # Mixed signals: high ATR + low ADX + BOS
            # or ADX strong but chop high, etc. No edge — block trading.
            classification = "indeterminate"

        # HTF regime (higher timeframe ADX only)
        htf_regime = "unavailable"
        htf_direction = None
        htf_adx_value = None
        htf_directional_bias = None
        htf_high = None
        htf_low = None
        htf_atr = None
        htf_recent_change = False
        htf_change_desc = ""
        if htf_enabled:
            htf_interval = self.get_bias_interval(interval)
            if htf_interval:
                try:
                    htf_ohlcv = await self.aggregator.get_consensus_ohlcv(
                        coin_id=coin_id,
                        vs_currency=vs_currency,
                        interval=htf_interval,
                        limit=regime_config.get("htf_lookback", 120),
                    )
                    if (
                        htf_ohlcv
                        and htf_ohlcv.get("success")
                        and htf_ohlcv.get("data")
                    ):
                        htf_data = [
                            candle.__dict__ for candle in htf_ohlcv["data"]
                        ]
                        df_htf = pd.DataFrame(htf_data)
                        df_htf["open_time"] = pd.to_datetime(
                            df_htf["open_time"], unit="ms"
                        )
                        df_htf = df_htf.sort_values("open_time").set_index(
                            "open_time"
                        )
                        # Drop the forming (incomplete) candle
                        df_htf = self._trim_forming_candle(df_htf, htf_interval)

                        # --- HTF EMA regime change detection ---
                        ema_change = TechnicalAnalysisEngine.detect_ema_regime_change(
                            df_htf,
                            short_window=EMA_SHORT,
                            long_window=EMA_LONG,
                            lookback=regime_config.get("ema_regime_change_window", 30),
                        )
                        htf_recent_change = ema_change.get("regime_change", False)
                        htf_change_desc = ema_change.get("change_description", "")
                        htf_adx = TechnicalAnalysisEngine.calculate_adx(
                            df_htf, period=14
                        )
                        htf_adx_value = htf_adx.get("adx_value")
                        htf_regime = (
                            "trending"
                            if htf_adx_value is not None
                            and htf_adx_value >= adx_threshold
                            else "ranging"
                        )

                        # Extract HTF direction and ATR.
                        # Use directional_bias so a slow, grinding HTF trend
                        # (ADX below threshold) still exposes its direction.
                        htf_direction = htf_adx.get("directional_bias")
                        htf_directional_bias = htf_direction
                        htf_adx_value = htf_adx.get("adx_value")
                        htf_atr = TechnicalAnalysisEngine._calculate_atr(df_htf, period=14)
                        if pd.isna(htf_atr):
                            htf_atr = None

                        # Dynamically fetch lookback for HTF interval (DRY principle)
                        htf_profile = self.get_profile(htf_interval)
                        htf_lookback = htf_profile.get("bos_lookback", 6) if htf_profile else 6

                        # Calculate structural walls
                        htf_range = TechnicalAnalysisEngine.calculate_range_boundaries(
                            df_htf, atr_period=14, cluster_atr_tolerance=0.5, min_touches=2, lookback=htf_lookback
                        )
                        htf_sr = TechnicalAnalysisEngine.calculate_support_levels(
                            df_htf, lookback=htf_lookback
                        )

                        # Intelligently select HTF High (Resistance)
                        if htf_range.get("valid_range") and htf_range.get("resistance"):
                            htf_high = htf_range["resistance"]
                        elif htf_sr.get("resistance"):
                            htf_high = htf_sr["resistance"]
                        else:
                            htf_high = df_htf["high"].max()

                        # Intelligently select HTF Low (Support)
                        if htf_range.get("valid_range") and htf_range.get("support"):
                            htf_low = htf_range["support"]
                        elif htf_sr.get("support"):
                            htf_low = htf_sr["support"]
                        else:
                            htf_low = df_htf["low"].min()
                except Exception as e:
                    self.logger.warning(
                        f"Regime HTF fetch failed for {coin_id}: {e}"
                    )
            else:
                self.logger.debug(
                    "Regime HTF skipped for "
                    f"{coin_id}: no bias interval for {interval}"
                )

        return {
            "classification": classification,
            "signals": {
                "adx": {
                    "value": (
                        float(adx_value) if adx_value is not None else None
                    ),
                    "trending": bool(adx_trending),
                },
                "atr_percentile": {
                    "value": (
                        float(atr_pct_value)
                        if atr_pct_value is not None
                        else None
                    ),
                    "trending": bool(atr_trending),
                },
                "bos": {
                    "fresh": bool(bos_fresh),
                    "strength": bos_strength,
                    "trending": bool(bos_fresh),
                },
                "choppiness": {
                    "value": (
                        float(choppiness_value)
                        if choppiness_value is not None
                        else None
                    ),
                    "trending": bool(chop_trending),
                    "ranging": bool(chop_ranging),
                },
            },
            "trending_count": int(trending_count),
            "required": int(min_signals),
            "htf_regime": htf_regime,
            "htf_direction": htf_direction,
            "htf_directional_bias": htf_directional_bias if htf_regime != "unavailable" else None,
            "htf_adx_value": float(htf_adx_value) if htf_adx_value is not None else None,
            "htf_high": htf_high if htf_regime != "unavailable" else None,
            "htf_low": htf_low if htf_regime != "unavailable" else None,
            "htf_atr": htf_atr if htf_regime != "unavailable" else None,
            "htf_recent_regime_change": htf_recent_change,
            "htf_regime_change_description": htf_change_desc,
        }

    def has_structural_trigger(
        self, analysis_results: Dict[str, Any], bos_max_age: int = 6
    ) -> bool:
        """
        Quickly checks if analysis results contain any structural trigger
        (BOS, OB reaction, SR reversal) without performing expensive computations.
        Used to decide which coins need regime detection.
        """
        market_structure = analysis_results.get("market_structure", {})

        # Check BOS
        signal_type = market_structure.get("signal", "-")
        strength = market_structure.get("bias_strength", "-")
        bos_age = market_structure.get("bos_age")
        if (
            signal_type in ("bullish_bos", "bearish_bos")
            and strength in ("strong", "medium")
            and bos_age is not None
            and bos_age <= bos_max_age
        ):
            return True

        # Check OB reaction
        ob_rx = market_structure.get("ob_reaction", {})
        if ob_rx.get("bullish_reaction") or ob_rx.get("bearish_reaction"):
            return True

        # Check SR reversal
        sr_rev = market_structure.get("sr_reversal", {})
        if sr_rev.get("bullish_reversal") or sr_rev.get("bearish_reversal"):
            return True

        return False

    async def _get_current_price(
        self, coin_id: str, vs_currency: str
    ) -> Dict[str, Any]:
        """Fetches the current price and market data."""
        self.logger.info(
            "MarketAnalysisService: Fetching current price for"
            f" {coin_id}-{vs_currency}"
        )
        result = await self.aggregator.get_consensus_price(
            coin_id=coin_id,
            vs_currency=vs_currency,
        )

        if not result["success"] or not result["data"]:
            return {
                "current_price": None,
                "market_cap": None,
                "volume_24h": None,
                "change_24h_percent": None,
                "error": "Could not retrieve current price.",
            }

        data = result["data"]
        result = {
            "current_price": round(data.price, 4) if data.price else None,
            "market_cap": data.market_cap,
            "volume_24h": data.volume_24h,
            "change_24h_percent": data.change_24h_percent,
            "last_updated": data.last_updated,
        }
        return result

    async def analyze_single_coin(
        self,
        coin_id: str,
        vs_currency: str,
        include_technicals: bool,
        interval: str,
        short_window: int,
        long_window: int,
        ema_short_window: int,
        ema_long_window: int,
        rsi_period: int,
        bb_period: int,
        bb_std_dev: float,
        macd_fast_period: int,
        macd_slow_period: int,
        macd_signal_period: int,
        volume_period: int,
        atr_period: int = 14,
        atr_percentile_lookback: int = 50,
        bos_lookback: int = 6,
        ob_lookback: int = 6,
        obv_lookback: int = 20,
        ob_min_impulse_atr: float = 1.8,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_change_24h: Optional[float] = None,
        max_change_24h: Optional[float] = None,
        prefetched_market_data: Optional[Dict[str, Any]] = None,
        include_derivatives: bool = False,
        macro_drive: Optional[float] = None,
        stop_hostility_lookback: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """
        Helper method to analyze a single cryptocurrency.
        This is the shared logic previously in KhromalabsAtariaCryptoAnalysis._analyze_single_coin.

        If prefetched_market_data is provided, it will be used directly
        instead of fetching price data from the aggregator.
        """
        self.logger.info(
            "MarketAnalysisService: Running analysis for"
            f" {coin_id}-{vs_currency}"
        )

        # 1. Fast path: Use prefetched data or fetch market data
        current_price_task = None
        derivatives_task = None
        if prefetched_market_data is not None:
            market_data = prefetched_market_data
        else:
            current_price_task = asyncio.create_task(
                self._get_current_price(coin_id, vs_currency)
            )

        if include_derivatives:
            derivatives_task = asyncio.create_task(
                self.aggregator.get_consensus_derivatives(coin_id, vs_currency)
            )

        # Check filters if present
        if min_price or max_price or min_change_24h or max_change_24h:
            if current_price_task is not None:
                market_data = await current_price_task
            price = market_data.get("current_price")
            change_24h = market_data.get("change_24h_percent")

            if price is not None:
                if min_price and price < min_price:
                    if derivatives_task:
                        derivatives_task.cancel()
                    return None
                if max_price and price > max_price:
                    if derivatives_task:
                        derivatives_task.cancel()
                    return None

            if change_24h is not None:
                if min_change_24h and change_24h < min_change_24h:
                    if derivatives_task:
                        derivatives_task.cancel()
                    return None
                if max_change_24h and change_24h > max_change_24h:
                    if derivatives_task:
                        derivatives_task.cancel()
                    return None

        if not include_technicals:
            if current_price_task is not None:
                if not current_price_task.done():
                    market_data = await current_price_task
                else:
                    market_data = current_price_task.result()

            result = {
                "coin_id": coin_id,
                "vs_currency": vs_currency,
                "market_data": market_data,
                "interval": interval,
            }
            if derivatives_task is not None:
                deriv_res = (
                    await derivatives_task
                    if not derivatives_task.done()
                    else derivatives_task.result()
                )
                if deriv_res.get("success"):
                    result["derivatives"] = deriv_res["data"]
            return result

        # 2. Full path: Validate parameters for technicals
        if short_window >= long_window:
            return self._error_result(
                coin_id,
                vs_currency,
                "Invalid parameters: short_window must be less than long_window.",
            )
        if ema_short_window >= ema_long_window:
            return self._error_result(
                coin_id,
                vs_currency,
                "Invalid parameters: ema_short_window must be less than ema_long_window.",
            )
        if macd_fast_period >= macd_slow_period:
            return self._error_result(
                coin_id,
                vs_currency,
                "Invalid parameters: macd_fast_period must be less than macd_slow_period.",
            )

        # Fetch OHLCV data for technical analysis
        # Minimum 168 to cover 7 days of hourly candles for price change calc
        ohlcv_result = await self.aggregator.get_consensus_ohlcv(
            coin_id=coin_id,
            vs_currency=vs_currency,
            interval=interval,
            limit=max(
                long_window, ema_long_window, bb_period, volume_period, 168
            )
            + 10,
        )
        if not ohlcv_result["success"] or not ohlcv_result["data"]:
            return self._error_result(
                coin_id,
                vs_currency,
                "Could not retrieve OHLCV data for technical analysis.",
            )

        ohlcv_data = [candle.__dict__ for candle in ohlcv_result["data"]]
        df = pd.DataFrame(ohlcv_data)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df = df.sort_values("open_time").set_index("open_time")

        # Drop the forming (incomplete) candle if present
        df = self._trim_forming_candle(df, interval)
        if len(df) < 20:
            return self._error_result(
                coin_id,
                vs_currency,
                "Insufficient closed candle data after trimming forming candle.",
            )

        # Run technical analyses using the pure math engine
        sma_analysis = TechnicalAnalysisEngine.calculate_sma_crossover(
            df, short_window, long_window
        )
        ema_analysis = TechnicalAnalysisEngine.calculate_ema_crossover(
            df, ema_short_window, ema_long_window
        )
        rsi_analysis = TechnicalAnalysisEngine.calculate_rsi(df, rsi_period)
        atr_analysis = TechnicalAnalysisEngine.calculate_atr(df, atr_period)
        adx_analysis = TechnicalAnalysisEngine.calculate_adx(df, atr_period)
        atr_percentile_analysis = (
            TechnicalAnalysisEngine.calculate_atr_percentile(
                df, period=atr_period, lookback=atr_percentile_lookback
            )
        )
        bb_analysis = TechnicalAnalysisEngine.calculate_bollinger_bands(
            df, bb_period, bb_std_dev
        )
        support_analysis = TechnicalAnalysisEngine.calculate_support_levels(
            df, lookback=5
        )
        macd_analysis = TechnicalAnalysisEngine.calculate_macd(
            df, macd_fast_period, macd_slow_period, macd_signal_period
        )
        volume_analysis = TechnicalAnalysisEngine.calculate_volume_analysis(
            df, volume_period
        )

        # Derive price change from the same OHLCV dataset (interval-aware)
        price_change_analysis = TechnicalAnalysisEngine.calculate_price_change(
            df, interval
        )

        # Choppiness index for regime detection
        choppiness_value = TechnicalAnalysisEngine.calculate_choppiness_index(
            df, period=14
        )

        # Stop-hostility metrics
        efficiency_ratio_value = (
            TechnicalAnalysisEngine.calculate_efficiency_ratio(
                df, lookback=stop_hostility_lookback
            )
        )
        range_atr_ratio_value = (
            TechnicalAnalysisEngine.calculate_range_atr_ratio(
                df,
                atr_value=atr_analysis.get("value", 0),
                lookback=stop_hostility_lookback,
            )
        )


        # OBV divergence detection
        obv_divergence = TechnicalAnalysisEngine.calculate_obv_divergence(
            df, lookback=obv_lookback, pivot_lookback=3
        )

        # New market structure analysis
        bos_analysis = TechnicalAnalysisEngine.calculate_break_of_structure(
            df, bos_lookback
        )
        ob_analysis = TechnicalAnalysisEngine.calculate_order_blocks(
            df, ob_lookback, **self.config["order_blocks"]
        )
        support_analysis = TechnicalAnalysisEngine.calculate_support_levels(
            df, lookback=8
        )
        ob_reaction = TechnicalAnalysisEngine.detect_ob_reaction(
            df, ob_analysis
        )

        # Range boundary detection (cluster-based, for ranging market logic)
        # Moved before sr_reversal so we can use range walls as primary S/R
        range_boundaries = TechnicalAnalysisEngine.calculate_range_boundaries(
            df,
            atr_period=atr_period,
            lookback=bos_lookback,
            **self.config["range_boundaries"],
        )

        # Use range boundaries for SR reversal if a valid range exists,
        # otherwise fall back to generic support/resistance levels.
        sr_support = support_analysis.get("support")
        sr_resistance = support_analysis.get("resistance")
        if range_boundaries.get("valid_range"):
            sr_support = range_boundaries.get("support")
            sr_resistance = range_boundaries.get("resistance")

        sr_reversal = TechnicalAnalysisEngine.detect_sr_reversal(
            df,
            sr_support,
            sr_resistance,
        )

        market_structure = {
            "bias": bos_analysis["bias"],
            "bias_strength": bos_analysis["strength"],
            "confidence_score": bos_analysis.get("confidence_score", 60),
            "signal": bos_analysis.get(
                "signal", "no_bos"
            ),  # Añadimos el nuevo signal
            "trend_structure": bos_analysis.get(
                "trend_structure", "undefined"
            ),
            "level": bos_analysis["level"],
            "order_blocks": ob_analysis,
            "ob_reaction": ob_reaction,
            "sr_reversal": sr_reversal,
            "support": support_analysis.get("support"),
            "resistance": support_analysis.get("resistance"),
            "bos_age": bos_analysis.get("bos_age", None),
            "details": (
                f"Structure bias is {bos_analysis['bias']} with"
                f" {bos_analysis['strength']} confidence."
            ),
        }

        if market_structure["bos_age"]:
            market_structure["details"] += (
                f" Break of Structure {market_structure['bos_age']} candles"
                " ago."
            )

        # Wick risk detection (stop-hunt exclusion) — moved after market_structure
        _profile = self.get_profile(interval) or {}
        _wick_config = {
            **self.config.get("wick_risk", {}),
            **_profile.get("wick_risk", {}),
        }
        wick_risk = TechnicalAnalysisEngine.calculate_wick_instability(
            df=df,
            atr_value=atr_analysis.get("value", 0),
            lookback=_wick_config.get("lookback", 20),
            wick_atr_multiple=_wick_config.get("wick_atr_multiple", 2.5),
            min_frequency=_wick_config.get("min_frequency", 0.25),
            killer_wick_multiple=_wick_config.get("killer_wick_multiple", 4.0),
            killer_wick_repetitions=_wick_config.get("killer_wick_repetitions", 2),
            bias=market_structure.get("bias"),
        )

        # Range maturity analysis
        rm_support = range_boundaries.get("support") if range_boundaries.get("valid_range") else support_analysis.get("support")
        rm_resistance = range_boundaries.get("resistance") if range_boundaries.get("valid_range") else support_analysis.get("resistance")

        range_maturity = TechnicalAnalysisEngine.calculate_range_maturity(
            df,
            support=rm_support,
            resistance=rm_resistance,
            touch_tolerance_atr=0.3,
            atr_period=atr_period,
            min_boundary_touches=2,  # default; screener overrides via config
        )

        # Short-term momentum (for coherence checks)
        short_term_momentum = TechnicalAnalysisEngine.calculate_short_term_momentum(
            df, lookback_candles=5
        )

        # Median deviation for overextension detection (interval‑sensitive)
        median_dev_result = {}
        profile = self.get_profile(interval) or {}
        _md_lookback = profile.get("median_dev_lookback", 30)
        _md_threshold = profile.get("median_overextension_atr", 2.0)
        if atr_analysis.get("value", 0) > 0 and len(df) >= _md_lookback:
            median_dev_result = TechnicalAnalysisEngine.calculate_price_deviation(
                df,
                atr_value=atr_analysis.get("value"),
                lookback=_md_lookback,
                threshold_atr=_md_threshold,
            )
        else:
            median_dev_result = {
                "median_price": None,
                "deviation_atr": None,
                "overextended": False,
            }

        # --- Evaluate candle quality for BOS / OB reactions ---
        # Use a 20-period volume average as baseline for the quality check
        vol_avg = df['volume'].iloc[-20:].mean() if len(df) >= 20 else df['volume'].mean()

        # BOS break candle
        if bos_analysis.get('signal') in ('bullish_bos', 'bearish_bos') and bos_analysis.get('bos_age') is not None:
            bos_candle_idx = len(df) - 1 - bos_analysis['bos_age']
            if bos_candle_idx >= 0:
                direction = 'bullish' if bos_analysis['signal'] == 'bullish_bos' else 'bearish'
                bos_quality = TechnicalAnalysisEngine.evaluate_candle_quality(
                    df.iloc[bos_candle_idx], direction, vol_avg
                )
                market_structure['bos_candle_quality'] = bos_quality
            else:
                market_structure['bos_candle_quality'] = None
        else:
            market_structure['bos_candle_quality'] = None

        # OB reaction candle (if a reaction was detected)
        ob_rx = market_structure.get('ob_reaction', {})
        if ob_rx and ob_rx.get('bullish_reaction') and ob_rx.get('bullish_reaction_idx') is not None:
            idx = ob_rx['bullish_reaction_idx']
            ob_reaction_quality = TechnicalAnalysisEngine.evaluate_candle_quality(
                df.iloc[idx], 'bullish', vol_avg
            )
            market_structure['ob_reaction_quality'] = ob_reaction_quality
        elif ob_rx and ob_rx.get('bearish_reaction') and ob_rx.get('bearish_reaction_idx') is not None:
            idx = ob_rx['bearish_reaction_idx']
            ob_reaction_quality = TechnicalAnalysisEngine.evaluate_candle_quality(
                df.iloc[idx], 'bearish', vol_avg
            )
            market_structure['ob_reaction_quality'] = ob_reaction_quality
        else:
            market_structure['ob_reaction_quality'] = None

        # Trend continuation detection (pullback to EMA + volume contraction)
        trend_continuation = TechnicalAnalysisEngine.detect_trend_continuation(
            df,
            atr_value=atr_analysis.get("value", 0),
            **self.config["trend_continuation"],
        )

        # Include a rolling window of recent candles for HTF continuation detection.
        # The screener uses this after HTF regime is known, without re-fetching
        # OHLCV data. 80 = max rally lookback (60) + pause lookback (10) + buffer.
        recent_candles = [
            {
                "open_time": int(ts.timestamp() * 1000),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for ts, row in df.tail(80).iterrows()
        ]

        # Buffered entry projection
        # Determine structural anchor and direction from trigger type
        pullback_direction = None
        structural_anchor = None
        bos_signal = bos_analysis.get("signal", "no_bos")

        if bos_signal == "bullish_bos" and bos_analysis.get("level"):
            pullback_direction = "bullish"
            structural_anchor = bos_analysis["level"]
        elif bos_signal == "bearish_bos" and bos_analysis.get("level"):
            pullback_direction = "bearish"
            structural_anchor = bos_analysis["level"]
        elif ob_reaction.get("bullish_reaction") and ob_analysis.get("bullish"):
            pullback_direction = "bullish"
            structural_anchor = ob_analysis["bullish"]["low"]
        elif ob_reaction.get("bearish_reaction") and ob_analysis.get("bearish"):
            pullback_direction = "bearish"
            structural_anchor = ob_analysis["bearish"]["high"]
        elif sr_reversal.get("bullish_reversal") and support_analysis.get("support"):
            pullback_direction = "bullish"
            structural_anchor = support_analysis["support"]
        elif sr_reversal.get("bearish_reversal") and support_analysis.get("resistance"):
            pullback_direction = "bearish"
            structural_anchor = support_analysis["resistance"]
        elif (
            trend_continuation.get("signal") == "bullish_continuation"
            and trend_continuation.get("ema_value_at_touch") is not None
        ):
            pullback_direction = "bullish"
            structural_anchor = trend_continuation["ema_value_at_touch"]
        elif (
            trend_continuation.get("signal") == "bearish_continuation"
            and trend_continuation.get("ema_value_at_touch") is not None
        ):
            pullback_direction = "bearish"
            structural_anchor = trend_continuation["ema_value_at_touch"]

        buffered_entry = None
        if pullback_direction and structural_anchor is not None:
            # Get current price for interpolation
            pp_current_price = None
            if prefetched_market_data:
                pp_current_price = prefetched_market_data.get("current_price")
            elif current_price_task is not None:
                if not current_price_task.done():
                    market_data = await current_price_task
                else:
                    market_data = current_price_task.result()
                pp_current_price = market_data.get("current_price")

            pp_atr_value = atr_analysis.get("value", 0)

            if pp_current_price and pp_atr_value > 0:
                buffered_entry = TechnicalAnalysisEngine.calculate_buffered_entry(
                    current_price=pp_current_price,
                    structural_anchor=structural_anchor,
                    atr_value=pp_atr_value,
                    direction=pullback_direction,
                    choppiness=choppiness_value,
                    macro_drive=macro_drive,
                    **self.config["buffered_entry"],
                )

        # Key levels consolidation
        kl_current_price = None
        if prefetched_market_data:
            kl_current_price = prefetched_market_data.get("current_price")
        elif current_price_task is not None:
            if not current_price_task.done():
                market_data = await current_price_task
            else:
                market_data = current_price_task.result()
            kl_current_price = market_data.get("current_price")

        key_levels = TechnicalAnalysisEngine.calculate_key_levels(
            current_price=kl_current_price,
            atr_value=atr_analysis.get("value", 0),
            support=support_analysis.get("support"),
            resistance=support_analysis.get("resistance"),
            order_blocks=ob_analysis,
            bos_level=bos_analysis.get("level"),
            bos_age=bos_analysis.get("bos_age"),
            **self.config["key_levels"],
        )

        # Get market data (already awaited if filters applied, or prefetched)
        if current_price_task is not None:
            if not current_price_task.done():
                market_data = await current_price_task
            else:
                market_data = current_price_task.result()

        result = {
            "coin_id": coin_id,
            "vs_currency": vs_currency,
            "market_data": market_data,
            "interval": interval,
            "analysis_results": {
                "sma_crossover": sma_analysis,
                "ema_crossover": ema_analysis,
                "rsi": rsi_analysis,
                "atr": atr_analysis,
                "adx": adx_analysis,
                "atr_percentile": atr_percentile_analysis,
                "bollinger_bands": bb_analysis,
                "support_levels": support_analysis,
                "macd": macd_analysis,
                "volume": volume_analysis,
                "price_change": price_change_analysis,
                "market_structure": market_structure,
                "key_levels": key_levels,
                "range_maturity": range_maturity,
                "range_boundaries": range_boundaries,
                "choppiness": choppiness_value,
                "efficiency_ratio": efficiency_ratio_value,
                "range_atr_ratio": range_atr_ratio_value,
                "wick_risk": wick_risk,
                "short_term_momentum": short_term_momentum,
                "trend_continuation": trend_continuation,
                "buffered_entry": buffered_entry,
                "obv_divergence": obv_divergence,
                "median_deviation": median_dev_result,
                "recent_candles": recent_candles,
            },
        }

        if derivatives_task is not None:
            deriv_res = (
                await derivatives_task
                if not derivatives_task.done()
                else derivatives_task.result()
            )
            if deriv_res.get("success"):
                result["derivatives"] = deriv_res["data"]

        return result
