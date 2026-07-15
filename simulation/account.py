"""
虚拟资金账户
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
from config.settings import (
    INITIAL_CASH, COMMISSION_RATE, STAMP_TAX, SLIPPAGE, MIN_LOT
)


@dataclass
class Position:
    """单只股票持仓"""
    ts_code: str
    volume: int             # 持有股数
    cost_price: float       # 开仓均价
    current_price: float    # 当前市价

    @property
    def market_value(self) -> float:
        return self.volume * self.current_price

    @property
    def profit_loss(self) -> float:
        return (self.current_price - self.cost_price) * self.volume

    @property
    def profit_loss_pct(self) -> float:
        if self.cost_price == 0:
            return 0.0
        return (self.current_price - self.cost_price) / self.cost_price


class VirtualAccount:
    """虚拟资金账户"""

    def __init__(
        self,
        initial_cash: float = INITIAL_CASH,
        commission_rate: float = COMMISSION_RATE,
        stamp_tax: float = STAMP_TAX,
        slippage: float = SLIPPAGE,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.frozen_cash = 0.0
        self.commission_rate = commission_rate
        self.stamp_tax = stamp_tax
        self.slippage = slippage

        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict] = []
        self.daily_nav: List[Dict] = []

        # T+1 记录: 今日买入的股票，明日才能卖出
        self.today_bought: set = set()
        # 当前交易日 (由 scheduler 在每日开始时设置)
        self.current_trade_date: str = ""

    # ---------- 属性 ----------
    @property
    def available_cash(self) -> float:
        return self.cash - self.frozen_cash

    @property
    def total_asset(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def total_return(self) -> float:
        return (self.total_asset - self.initial_cash) / self.initial_cash

    @property
    def position_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    # ---------- 行情更新 ----------
    def update_prices(self, prices: Dict[str, float]):
        """批量更新持仓市价"""
        for code, price in prices.items():
            if code in self.positions:
                self.positions[code].current_price = price

    def set_trade_date(self, trade_date: str):
        """由 scheduler 调用, 设置当前交易日, 供交易记录使用"""
        self.current_trade_date = trade_date

    # ---------- 买入 ----------
    def buy(self, ts_code: str, price: float, volume: int) -> dict:
        """买入股票"""
        volume = (volume // MIN_LOT) * MIN_LOT
        if volume <= 0:
            return {"success": False, "reason": "最小交易单位为100股"}

        actual_price = price * (1 + self.slippage)
        cost = actual_price * volume
        commission = cost * self.commission_rate
        total_required = cost + commission

        if total_required > self.available_cash:
            return {"success": False, "reason": f"资金不足 (需要 {total_required:,.0f}, 可用 {self.available_cash:,.0f})"}

        # 更新持仓 (同步成交, 不需要冻结资金)
        if ts_code in self.positions:
            pos = self.positions[ts_code]
            combined = pos.cost_price * pos.volume + actual_price * volume
            pos.volume += volume
            pos.cost_price = combined / pos.volume if pos.volume > 0 else 0
        else:
            self.positions[ts_code] = Position(
                ts_code=ts_code, volume=volume,
                cost_price=actual_price, current_price=price
            )

        # 结算
        self.cash -= total_required
        self.today_bought.add(ts_code)

        self._log_trade("BUY", ts_code, actual_price, volume, commission, 0)
        logger.info(f"买入 {ts_code} {volume}股 @{actual_price:.2f}, 余资 {self.cash:,.0f}")
        return {"success": True, "price": actual_price, "volume": volume}

    # ---------- 卖出 ----------
    def sell(self, ts_code: str, price: float, volume: int = None) -> dict:
        """卖出股票"""
        if ts_code not in self.positions:
            return {"success": False, "reason": "无该股票持仓"}

        # T+1 检查
        if ts_code in self.today_bought:
            return {"success": False, "reason": f"{ts_code} 今日买入,T+1规则明日才能卖出"}

        pos = self.positions[ts_code]
        sell_volume = volume if volume else pos.volume
        sell_volume = (sell_volume // MIN_LOT) * MIN_LOT
        if sell_volume <= 0 or sell_volume > pos.volume:
            return {"success": False, "reason": "卖出数量无效或超出持仓"}

        actual_price = price * (1 - self.slippage)
        proceeds = actual_price * sell_volume
        commission = proceeds * self.commission_rate
        tax = proceeds * self.stamp_tax

        # 计算盈亏
        pnl = (actual_price - pos.cost_price) * sell_volume

        # 更新
        pos.volume -= sell_volume
        if pos.volume == 0:
            del self.positions[ts_code]
        self.cash += (proceeds - commission - tax)

        self._log_trade("SELL", ts_code, actual_price, sell_volume, commission, tax, pnl)
        logger.info(f"卖出 {ts_code} {sell_volume}股 @{actual_price:.2f}, 盈亏 {pnl:,.0f}")
        return {"success": True, "price": actual_price, "pnl": pnl}

    # ---------- 日末结算 ----------
    def end_of_day(self, trade_date: str):
        """每日结算: 记录净值、清除T+1标记"""
        nav = self.total_asset
        prev_nav = self.daily_nav[-1]["nav"] if self.daily_nav else self.initial_cash
        daily_ret = (nav - prev_nav) / prev_nav if prev_nav > 0 else 0

        self.daily_nav.append({
            "date": trade_date,
            "nav": nav,
            "cash": self.cash,
            "position_value": self.position_value,
            "return": daily_ret,
        })
        self.today_bought.clear()

    # ---------- 摘要 ----------
    def get_summary(self) -> dict:
        pos_list = []
        for code, p in self.positions.items():
            pos_list.append({
                "ts_code": code,
                "volume": p.volume,
                "cost_price": p.cost_price,
                "current_price": p.current_price,
                "market_value": p.market_value,
                "pnl": p.profit_loss,
                "pnl_pct": p.profit_loss_pct,
            })

        return {
            "total_asset": self.total_asset,
            "cash": self.cash,
            "available_cash": self.available_cash,
            "total_return": self.total_return,
            "position_count": len(self.positions),
            "positions": pos_list,
        }

    # ---------- 内部 ----------
    def _log_trade(self, direction, ts_code, price, volume, commission, tax, pnl=None):
        self.trade_history.append({
            "trade_date": self.current_trade_date,  # 真实交易日, 由 scheduler 设置
            "time": datetime.now(),                 # 回测运行时刻 (保留用于调试)
            "direction": direction,
            "ts_code": ts_code,
            "price": price,
            "volume": volume,
            "commission": commission,
            "stamp_tax": tax,
            "pnl": pnl,
        })
