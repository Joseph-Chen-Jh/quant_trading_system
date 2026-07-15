"""
止损策略模块

功能:
    - 固定比例止损 (FixedStopLoss): 亏损达阈值即止损 (相对成本价)
    - 追踪止损 (TrailingStopLoss): 从持仓最高价回撤达阈值即止损 (推荐趋势策略使用)

接入方式:
    由 PortfolioRunner 在每日收盘后调用, 生成 SELL 信号,
    与策略 SELL 信号合并去重后, 于 T+1 开盘价成交 (无未来函数偏差).

信号格式 (与策略信号一致):
    {
        "ts_code": "000001.SZ",
        "action": "SELL",
        "price": <当日收盘价>,        # 执行时由 portfolio_runner 替换为 T+1 开盘价
        "reason": "trailing_stop",    # 标记来源, 方便日志和调试
    }
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Dict, List, Union
from dataclasses import dataclass
from loguru import logger

from simulation.account import VirtualAccount
from config.settings import STOP_LOSS_PCT, TRAILING_STOP_PCT


@dataclass
class StopLossSignal:
    """止损信号"""
    ts_code: str
    current_price: float
    loss_pct: float        # 相对成本价的盈亏比例 (负数表示亏损)
    trigger_pct: float     # 触发条件的关键比例


class FixedStopLoss:
    """
    固定比例止损

    语义: 持仓亏损达到 stop_loss_pct 时触发 (相对成本价)
    适用: 严格控制单笔最大亏损
    """

    def __init__(self, stop_loss_pct: float = STOP_LOSS_PCT, enabled: bool = True):
        self.stop_loss_pct = stop_loss_pct
        self.enabled = enabled

    def check(self, account: VirtualAccount) -> List[StopLossSignal]:
        """检查所有持仓, 返回需要止损的信号列表"""
        if not self.enabled:
            return []

        signals = []
        for ts_code, position in account.positions.items():
            # 跳过今日买入的股票 (T+1 规则, 明日才能卖)
            if ts_code in account.today_bought:
                continue

            if position.profit_loss_pct <= -self.stop_loss_pct:
                signals.append(StopLossSignal(
                    ts_code=ts_code,
                    current_price=position.current_price,
                    loss_pct=position.profit_loss_pct,
                    trigger_pct=self.stop_loss_pct,
                ))
        return signals

    def generate_sell_signals(self, account: VirtualAccount) -> List[Dict]:
        """生成止损 SELL 信号 (格式与策略信号一致)"""
        stop_signals = self.check(account)
        return [
            {
                "ts_code": s.ts_code,
                "action": "SELL",
                "price": s.current_price,
                "reason": "fixed_stop",
            }
            for s in stop_signals
        ]

    def on_position_closed(self, ts_code: str):
        """持仓清仓后调用 (FixedStopLoss 无状态, 空实现)"""
        pass


class TrailingStopLoss:
    """
    追踪止损 (推荐趋势策略使用)

    语义: 从持仓以来的最高价回撤 trailing_pct 时触发
    特点:
        - 止损线随股价上涨而上移, 不会回落
        - 既能锁住盈利, 又能让利润奔跑
        - 比固定止损更适合趋势跟踪策略 (如双均线)
    """

    def __init__(self, trailing_pct: float = TRAILING_STOP_PCT, enabled: bool = True):
        self.trailing_pct = trailing_pct
        self.enabled = enabled
        self._highest_price: Dict[str, float] = {}  # ts_code -> 持仓期最高价

    def _cleanup_closed(self, account: VirtualAccount):
        """清理已清仓股票的最高价记录"""
        closed = [code for code in self._highest_price if code not in account.positions]
        for code in closed:
            del self._highest_price[code]

    def check(self, account: VirtualAccount) -> List[StopLossSignal]:
        """检查所有持仓, 返回需要止损的信号列表"""
        if not self.enabled:
            return []

        self._cleanup_closed(account)

        signals = []
        for ts_code, position in account.positions.items():
            # 跳过今日买入的股票 (T+1 规则)
            if ts_code in account.today_bought:
                continue

            current_price = position.current_price

            # 更新最高价 (只上不下)
            if ts_code not in self._highest_price:
                self._highest_price[ts_code] = current_price
            elif current_price > self._highest_price[ts_code]:
                self._highest_price[ts_code] = current_price

            highest = self._highest_price[ts_code]
            stop_price = highest * (1 - self.trailing_pct)

            if current_price <= stop_price:
                loss_pct = (
                    (current_price - position.cost_price) / position.cost_price
                    if position.cost_price > 0 else 0.0
                )
                signals.append(StopLossSignal(
                    ts_code=ts_code,
                    current_price=current_price,
                    loss_pct=loss_pct,
                    trigger_pct=self.trailing_pct,
                ))
        return signals

    def generate_sell_signals(self, account: VirtualAccount) -> List[Dict]:
        """生成止损 SELL 信号 (格式与策略信号一致)"""
        stop_signals = self.check(account)
        return [
            {
                "ts_code": s.ts_code,
                "action": "SELL",
                "price": s.current_price,
                "reason": "trailing_stop",
            }
            for s in stop_signals
        ]

    def on_position_closed(self, ts_code: str):
        """持仓清仓后调用, 清理最高价记录"""
        if ts_code in self._highest_price:
            del self._highest_price[ts_code]


def generate_stop_loss_signals(
    account: VirtualAccount,
    stop_loss: Union[FixedStopLoss, TrailingStopLoss],
) -> List[Dict]:
    """
    检查止损并生成 SELL 信号

    在每日收盘后 (scheduler.run_daily 之后) 调用,
    生成的信号与策略信号合并, 于 T+1 开盘价成交.
    """
    return stop_loss.generate_sell_signals(account)


if __name__ == "__main__":
    # 自测: 用一个虚拟账户验证止损逻辑
    from simulation.account import VirtualAccount, Position

    print("=" * 60)
    print("止损模块自测")
    print("=" * 60)

    # --- 测试 TrailingStopLoss ---
    print("\n--- 测试 TrailingStopLoss ---")
    account = VirtualAccount()
    ts = TrailingStopLoss(trailing_pct=0.08)

    # 模拟买入 000001.SZ @10 元
    account.positions["000001.SZ"] = Position(
        ts_code="000001.SZ", volume=1000, cost_price=10.0, current_price=10.0
    )

    # Day 1: 价格涨到 12 元 (最高价更新为 12)
    account.update_prices({"000001.SZ": 12.0})
    sigs = ts.generate_sell_signals(account)
    print(f"价格 10→12 (涨 20%): 触发止损 {len(sigs)} 个 (应=0)")
    assert len(sigs) == 0, "上涨不应触发止损"

    # Day 2: 价格回落到 11.5 元 (从最高 12 回撤 4.2%, < 8%)
    account.update_prices({"000001.SZ": 11.5})
    sigs = ts.generate_sell_signals(account)
    print(f"价格 12→11.5 (回撤 4.2%): 触发止损 {len(sigs)} 个 (应=0)")
    assert len(sigs) == 0, "回撤 < 8% 不应触发"

    # Day 3: 价格回落到 11.0 元 (从最高 12 回撤 8.3%, > 8%)
    account.update_prices({"000001.SZ": 11.0})
    sigs = ts.generate_sell_signals(account)
    print(f"价格 12→11.0 (回撤 8.3%): 触发止损 {len(sigs)} 个 (应=1)")
    assert len(sigs) == 1, "回撤 >= 8% 应触发"
    print(f"  信号: {sigs[0]}")
    assert sigs[0]["reason"] == "trailing_stop"

    # --- 测试 T+1 跳过 ---
    print("\n--- 测试 T+1 跳过 ---")
    account2 = VirtualAccount()
    ts2 = TrailingStopLoss(trailing_pct=0.08)
    account2.positions["300750.SZ"] = Position(
        ts_code="300750.SZ", volume=1000, cost_price=100.0, current_price=80.0
    )
    account2.today_bought.add("300750.SZ")  # 模拟今日买入
    sigs = ts2.generate_sell_signals(account2)
    print(f"今日买入股票大跌 20%: 触发止损 {len(sigs)} 个 (应=0, T+1 跳过)")
    assert len(sigs) == 0, "今日买入的股票应跳过"

    # --- 测试清仓后清理 ---
    print("\n--- 测试清仓后清理 ---")
    account3 = VirtualAccount()
    ts3 = TrailingStopLoss(trailing_pct=0.08)
    account3.positions["000001.SZ"] = Position(
        ts_code="000001.SZ", volume=1000, cost_price=10.0, current_price=15.0
    )
    _ = ts3.generate_sell_signals(account3)  # 初始化最高价
    print(f"持仓时最高价记录: {ts3._highest_price}")
    assert "000001.SZ" in ts3._highest_price

    del account3.positions["000001.SZ"]  # 模拟清仓
    _ = ts3.generate_sell_signals(account3)  # 触发清理
    print(f"清仓后最高价记录: {ts3._highest_price}")
    assert "000001.SZ" not in ts3._highest_price

    print("\n✓ 全部测试通过")
