"""
订单管理 & 风控检查
"""
from typing import Dict, List
from config.settings import (
    MAX_POSITION_PCT, MAX_TOTAL_POSITION, STOP_LOSS_PCT,
    MAX_DRAWDOWN, DAILY_TRADE_LIMIT, MIN_DAILY_AMOUNT, LIMIT_UP_DOWN
)
from simulation.account import VirtualAccount


class OrderManager:
    """订单管理器 —— 负责信号 → 订单 + 风控"""

    def __init__(self, account: VirtualAccount):
        self.account = account
        self.daily_trade_count = 0

    def reset_daily(self):
        self.daily_trade_count = 0

    def process_signals(self, signals: List[Dict], prices: Dict[str, float],
                        amounts: Dict[str, float] = None) -> List[Dict]:
        """
        处理信号队列，返回执行结果

        signals: [{"ts_code": ..., "action": "BUY"/"SELL", "volume": ..., "price": ...}]
        prices:  {code: current_price}
        amounts: {code: daily_amount}  用于流动性检查
        """
        results = []
        for sig in signals:
            result = self._execute(sig, prices, amounts or {})
            results.append(result)
        return results

    def _execute(self, signal: Dict, prices: Dict[str, float],
                 amounts: Dict[str, float]) -> dict:
        ts_code = signal["ts_code"]
        action = signal["action"]
        price = prices.get(ts_code) or signal.get("price", 0)

        if price <= 0:
            return {"signal": signal, "result": "SKIP", "reason": "无有效价格"}

        # ---- 风控检查 ----
        # 1. 日交易次数
        if self.daily_trade_count >= DAILY_TRADE_LIMIT:
            return {"signal": signal, "result": "SKIP", "reason": "超过单日交易上限"}

        # 2. 流动性检查
        if amounts and amounts.get(ts_code, 0) < MIN_DAILY_AMOUNT:
            return {"signal": signal, "result": "SKIP", "reason": "日成交额不足"}

        # 3. 总回撤
        if self.account.total_return < -MAX_DRAWDOWN and self.account.positions:
            return {"signal": signal, "result": "SKIP", "reason": f"总回撤超过{MAX_DRAWDOWN:.0%}警戒线"}

        if action == "BUY":
            return self._execute_buy(signal, price, signal.get("price", price))
        elif action == "SELL":
            return self._execute_sell(signal, price)
        else:
            return {"signal": signal, "result": "SKIP", "reason": f"未知动作 {action}"}

    def _execute_buy(self, signal: dict, price: float, ref_price: float) -> dict:
        ts_code = signal["ts_code"]
        volume = signal.get("volume", 100)

        # 仓位上限
        total_asset = self.account.total_asset
        cost = price * volume
        if cost > total_asset * MAX_POSITION_PCT:
            volume = int((total_asset * MAX_POSITION_PCT) / price / 100) * 100
            if volume == 0:
                return {"signal": signal, "result": "SKIP", "reason": "单票仓位超限"}

        # 总仓位检查
        if self.account.position_value + cost > total_asset * MAX_TOTAL_POSITION:
            return {"signal": signal, "result": "SKIP", "reason": "总仓位超限"}

        # 涨停不追
        if ref_price > 0 and (price / ref_price - 1) >= LIMIT_UP_DOWN:
            return {"signal": signal, "result": "SKIP", "reason": "涨停不追"}

        result = self.account.buy(ts_code, price, volume)
        if result["success"]:
            self.daily_trade_count += 1
        return {"signal": signal, "result": "FILLED" if result["success"] else "REJECTED",
                "detail": result}

    def _execute_sell(self, signal: dict, price: float) -> dict:
        ts_code = signal["ts_code"]

        # 止损检查由策略层面处理，这里主要做硬风控
        result = self.account.sell(ts_code, price, signal.get("volume"))
        if result["success"]:
            self.daily_trade_count += 1
        return {"signal": signal, "result": "FILLED" if result["success"] else "REJECTED",
                "detail": result}
