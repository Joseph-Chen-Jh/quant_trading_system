"""回测参数配置 (dataclass)

将原本散落在 CLI 参数和函数签名中的 30+ 个回测参数按职责分组,
打包成结构化配置对象, 替代冗长的参数列表。

分组:
    - BacktestConfig: 顶层配置 (回测区间/股票池/策略选择)
    - MAConfig: MA 双均线策略参数
    - RSIConfig: RSI 均值回归策略参数 (含多周期/自适应/波动率分组等模式)
    - VolSelectorConfig: 动态波动率筛选参数
    - RiskConfig: 风控参数 (止损/组合回撤止损)
    - PEConfig: PE 分位数选股参数
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class MAConfig:
    """MA 双均线策略参数"""
    short_window: int = 5
    long_window: int = 20
    adx_threshold: float = 0.0  # ADX 过滤阈值 (0=不过滤)


@dataclass
class RSIConfig:
    """RSI 均值回归策略参数

    支持四种模式 (按优先级):
        1. multi_period=True: 多周期共振 (RSI(14)上穿30 + RSI(21)<阈值)
        2. vol_grouped=True: 波动率分组 (高/中/低波动用不同阈值)
        3. adaptive=True: 自适应分位数 (滚动分位数替代固定阈值)
        4. 默认: 固定 30/70 阈值
    """
    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    # 自适应分位数模式 (4.15 节验证失败, 保留用于对比)
    adaptive: bool = False
    lookback: int = 60
    low_q: float = 0.10
    high_q: float = 0.90

    # 波动率分组模式 (4.16 节验证失败, 保留用于对比)
    vol_grouped: bool = False
    vol_lookback: int = 60
    vol_high: float = 0.40
    vol_low: float = 0.30

    # 多周期共振模式 (4.17 节验证成功, 推荐配置)
    multi_period: bool = False
    long_rsi_period: int = 21
    long_rsi_threshold: float = 50.0


@dataclass
class VolSelectorConfig:
    """动态波动率筛选参数"""
    dynamic_vol: bool = False
    vol_lookback: int = 60
    vol_top: int = 10
    vol_mode: str = "high"  # high=选高波动 (MA趋势), low=选低波动 (RSI均值回归)


@dataclass
class RiskConfig:
    stop_loss_type: str = "trailing"  # trailing | fixed | time | combo | none
    stop_loss_pct: Optional[float] = None  # None=用默认值
    max_hold_days: int = 20  # 时间止损/组合止损的最大持有交易日数
    portfolio_dd_threshold: Optional[float] = None  # None=不启用


@dataclass
class BacktestConfig:
    """组合回测顶层配置"""
    pool_name: str = "default"
    start_date: str = "20240101"
    end_date: Optional[str] = None
    strategy_name: str = "ma"  # ma | rsi
    market_filter_rule: Optional[str] = None  # None | price_above_ma | ma_slope_up | both
    use_position_scaler: bool = False
    use_rsi: bool = False  # 多策略并行 (MA 主策略 + RSI 附加)

    # 子配置 (嵌套)
    ma: MAConfig = field(default_factory=MAConfig)
    rsi: RSIConfig = field(default_factory=RSIConfig)
    vol_selector: VolSelectorConfig = field(default_factory=VolSelectorConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def to_dict(self) -> dict:
        """转为字典 (用于日志/序列化)"""
        return asdict(self)


@dataclass
class SingleBacktestConfig:
    """单股票回测配置"""
    ts_code: str = "000001.SZ"
    start_date: str = "20240101"
    end_date: Optional[str] = None
    short_window: int = 5
    long_window: int = 20


@dataclass
class PEConfig:
    """PE 分位数选股策略参数"""
    pool_name: str = "default"
    start_date: str = "20240101"
    end_date: Optional[str] = None
    quantile_threshold: float = 0.3
    lookback_years: int = 3
    top_n: int = 3
    rebalance_freq: str = "monthly"  # monthly | quarterly
