"""
多股票组合回测编排器

职责:
    1. 加载股票池中所有股票的日线数据
    2. 对每只股票独立生成交易信号
    3. 按日期合并所有股票的信号
    4. 用 T+1 开盘价 + 动态资金分配执行信号
    5. 共享单个 VirtualAccount, 同时处理多只股票的买卖

与单股票回测 (main.py cmd_backtest) 的差异:
    - 多只股票共享同一个账户
    - 资金按信号数量动态分配 (而非固定 50%)
    - 每只股票有目标权重上限 (避免过度集中)
    - 交易日为所有股票交易日的并集 (处理停牌)
"""
import time
from typing import Dict, List
import pandas as pd
from loguru import logger

from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler


class PortfolioRunner:
    """多股票组合回测"""

    def __init__(
        self,
        pool_config: dict,
        strategy,
        account: VirtualAccount,
        scheduler: SimulationScheduler,
        stop_loss=None,
        vol_selector=None,
        market_filter=None,
        position_scaler=None,
        extra_strategies=None,
        portfolio_stop=None,
    ):
        """
        Args:
            pool_config: load_pool() 返回的池配置
            strategy:    主策略实例 (需有 generate_signals(df) -> DataFrame)
            account:     共享的虚拟账户
            scheduler:   交易调度器
            stop_loss:   个股止损实例 (FixedStopLoss / TrailingStopLoss / None)
            vol_selector: 动态波动率筛选器 (None=用静态池)
            market_filter: 市场环境过滤器 (None=不过滤, 基于沪深300判断是否允许开仓)
            position_scaler: 动态仓位管理器 (None=固定0.9, 基于沪深300动态调整)
            extra_strategies: 附加策略列表 (方案A: 多策略并行, 信号叠加)
            portfolio_stop: 组合级回撤止损 (None=不启用)
        """
        self.pool = pool_config
        self.strategy = strategy
        self.account = account
        self.scheduler = scheduler
        self.stop_loss = stop_loss
        self.vol_selector = vol_selector
        self.market_filter = market_filter
        self.position_scaler = position_scaler
        # 多策略并行: 主策略 + 附加策略
        self.extra_strategies = extra_strategies or []
        self.portfolio_stop = portfolio_stop

        # 股票权重映射 {ts_code: weight}
        self.weights = {
            s["ts_code"]: s.get("weight", 1.0 / len(pool_config["stocks"]))
            for s in pool_config["stocks"]
        }
        # 股票名称映射 (用于日志)
        self.names = {s["ts_code"]: s.get("name", s["ts_code"]) for s in pool_config["stocks"]}

        # 数据: {ts_code: DataFrame}
        self.stock_data: Dict[str, pd.DataFrame] = {}
        # 信号: {trade_date: [signal_dict, ...]}
        self.signals_by_date: Dict[str, List[dict]] = {}

        # 资金分配参数
        self.total_budget_ratio = 0.9  # 总可用资金的 90% 用于分配

    # ======================== 数据加载 ========================
    def load_data(self, store, start_date: str, end_date: str = None):
        """
        加载池中所有股票的日线数据

        Args:
            store: DataStore 实例
            start_date: 起始日期 YYYYMMDD
            end_date:   截止日期 YYYYMMDD (None=到最新)
        """
        total = len(self.pool["stocks"])
        for i, stock in enumerate(self.pool["stocks"], 1):
            ts_code = stock["ts_code"]
            name = stock.get("name", ts_code)

            df = store.load_daily_price(ts_code=ts_code, start=start_date, end=end_date)
            if df.empty:
                logger.warning(f"[{i}/{total}] {ts_code} 数据库无数据, 跳过")
                continue

            self.stock_data[ts_code] = df
            logger.info(
                f"[{i}/{total}] {name} ({ts_code}) 加载 {len(df)} 行 "
                f"({df['trade_date'].min()} ~ {df['trade_date'].max()})"
            )

        logger.info(f"数据加载完成: {len(self.stock_data)}/{total} 只股票")

    # ======================== 信号生成 ========================
    def generate_all_signals(self):
        """为每只股票生成信号 (支持多策略并行), 合并到统一的 signals_by_date"""
        all_strategies = [self.strategy] + self.extra_strategies
        strategy_names = [s.name for s in all_strategies]
        logger.info(f"启用策略: {strategy_names}")

        for ts_code, df in self.stock_data.items():
            # 收集所有策略对这只股票的信号
            # {trade_date: set("BUY"/"SELL")} 用于去重和抵消
            date_actions = {}

            for strategy in all_strategies:
                try:
                    signals_df = strategy.generate_signals(df)
                except Exception as e:
                    logger.error(f"{ts_code} [{strategy.name}] 信号生成失败: {e}")
                    continue

                for _, row in signals_df.iterrows():
                    if row["action"] in ("BUY", "SELL"):
                        date_actions.setdefault(row["trade_date"], set()).add(row["action"])

            # 合并规则: 同日同方向去重, 同日反方向抵消
            n_buy = 0
            n_sell = 0
            for date, actions in date_actions.items():
                if actions == {"BUY", "SELL"}:
                    # 两个策略意见分歧, 抵消
                    continue
                action = list(actions)[0]  # 只有一个元素 (去重后)
                self.signals_by_date.setdefault(date, []).append({
                    "ts_code": ts_code,
                    "action": action,
                    "price": float(df[df["trade_date"] == date]["close"].iloc[0]),
                })
                if action == "BUY":
                    n_buy += 1
                else:
                    n_sell += 1

            if n_buy > 0 or n_sell > 0:
                logger.info(
                    f"{self.names.get(ts_code, ts_code)} ({ts_code}) "
                    f"合并信号: BUY={n_buy}, SELL={n_sell}"
                )

        total_signals = sum(len(v) for v in self.signals_by_date.values())
        logger.info(f"组合信号合并完成: 共 {total_signals} 个信号, 覆盖 {len(self.signals_by_date)} 个交易日")

    # ======================== 回测执行 ========================
    def run_backtest(self, trade_start_date: str = None):
        """
        执行多股票回测 (T+1 开盘成交 + 动态资金分配 + 止损检查)

        Args:
            trade_start_date: 实际交易起始日 YYYYMMDD (含). 之前为预热期,
                只更新波动率池, 不执行交易、不记录净值. None=从第一天开始交易.

        流程:
            for date in 所有交易日并集:
                [预热期] 只更新波动率池, 跳过交易和净值记录
                [交易期]
                1. 执行昨日生成、今日开盘成交的信号 (含止损 SELL)
                2. scheduler 内部: 用当日收盘价更新持仓估值 → 处理信号 → 日末结算
                3. 收盘后检查止损 (用当日收盘价) → 生成止损 SELL 信号
                4. 收集今日策略信号, 与止损信号合并去重, 入队等待明日执行
        """
        # 收集所有交易日 (所有股票的并集, 处理停牌)
        all_dates = sorted(set().union(
            *[set(df["trade_date"]) for df in self.stock_data.values()]
        ))
        warmup_label = f", 预热期 {all_dates[0]} ~ {trade_start_date}" if trade_start_date else ""
        logger.info(f"回测区间: {all_dates[0]} ~ {all_dates[-1]}, 共 {len(all_dates)} 个交易日{warmup_label}")

        # 价格查找表: {ts_code: {trade_date: (open, close)}}
        price_lookup = {}
        for ts_code, df in self.stock_data.items():
            price_lookup[ts_code] = {
                row["trade_date"]: (float(row["open"]), float(row["close"]))
                for _, row in df.iterrows()
            }

        # 信号延迟队列: T 日生成, T+1 日执行
        pending_signals: List[dict] = []
        n_stop_triggered = 0
        n_portfolio_stop_triggered = 0

        for i, date in enumerate(all_dates, 1):
            if i % 100 == 0:
                logger.info(f"进度: {i}/{len(all_dates)}")

            # 1. 收集当日所有股票的收盘价 (用于持仓估值)
            close_prices = {}
            for ts_code, lookup in price_lookup.items():
                if date in lookup:
                    close_prices[ts_code] = lookup[date][1]

            # 1.5 动态波动率筛选: 调仓日更新可买入池 (预热期也更新, 为交易期准备)
            if self.vol_selector:
                prev_date = all_dates[i-2] if i >= 2 else None
                if self.vol_selector.is_rebalance_day(date, prev_date):
                    self.vol_selector.update_pool(
                        list(self.stock_data.keys()), self.stock_data, date
                    )

            # 预热期: 只更新波动率池, 跳过交易和净值记录
            if trade_start_date and date < trade_start_date:
                # 清空预热期产生的信号队列 (不执行)
                pending_signals = []
                continue

            # 2. 执行昨日信号 (T+1 开盘成交 + 动态资金分配)
            #    BUY 信号需过波动率筛选 (方式 B: SELL 不受影响)
            signals_to_execute = pending_signals
            pending_signals = []

            if self.vol_selector:
                # 只过滤 BUY, SELL 全部放行 (已持仓的卖出由 MA/止损决定)
                signals_to_execute = [
                    s for s in signals_to_execute
                    if s["action"] != "BUY" or self.vol_selector.can_buy(s["ts_code"])
                ]

            # 2.5 市场环境过滤: 震荡/下跌市禁止开新仓 (只过滤 BUY, SELL 全部放行)
            if self.market_filter and not self.market_filter.can_open_position(date):
                signals_to_execute = [
                    s for s in signals_to_execute
                    if s["action"] != "BUY"
                ]

            # 2.6 组合回撤止损: 暂停期间禁止开新仓 (只过滤 BUY, SELL 全部放行)
            if self.portfolio_stop and not self.portfolio_stop.can_open_position():
                signals_to_execute = [
                    s for s in signals_to_execute
                    if s["action"] != "BUY"
                ]

            enriched = self._allocate_and_price(
                signals_to_execute, price_lookup, date
            )

            self.scheduler.run_daily(date, enriched, close_prices)

            # 3. 收盘后检查止损 (此时 account.positions 的 current_price 已是当日收盘价)
            stop_signals = []
            if self.stop_loss:
                stop_signals = self.stop_loss.generate_sell_signals(self.account)
                if stop_signals:
                    n_stop_triggered += len(stop_signals)
                    for s in stop_signals:
                        logger.info(
                            f"止损触发 {s['ts_code']} @收盘{s['price']:.2f} ({s['reason']})"
                        )

            # 3.5 组合级回撤止损检查 (收盘后)
            portfolio_stop_signals = []
            if self.portfolio_stop:
                triggered = self.portfolio_stop.check_and_update(self.account, date)
                if triggered:
                    portfolio_stop_signals = self.portfolio_stop.generate_liquidation_signals(
                        self.account, date
                    )
                    n_portfolio_stop_triggered += len(portfolio_stop_signals)
                    logger.info(
                        f"组合止损清仓: 生成 {len(portfolio_stop_signals)} 个 SELL 信号"
                    )

            # 4. 收集今日策略信号
            today_signals = self.signals_by_date.get(date, [])

            # 5. 合并去重, 入队等待明日 T+1 开盘成交
            #    合并三层 SELL: 个股止损 + 组合止损清仓 + 策略信号
            all_stop_signals = stop_signals + portfolio_stop_signals
            pending_signals = self._merge_signals(today_signals, all_stop_signals)

        logger.info(f"回测完成: 累计收益率 {self.account.total_return:.2%}, "
                    f"个股止损触发 {n_stop_triggered} 次, "
                    f"组合止损清仓 {self.portfolio_stop.n_triggers if self.portfolio_stop else 0} 次")

    def _merge_signals(
        self,
        strategy_signals: List[dict],
        stop_signals: List[dict],
    ) -> List[dict]:
        """
        合并策略信号和止损信号

        去重规则: 同一只股票同方向的信号只保留一个
            - 策略 SELL + 止损 SELL → 保留策略 SELL (策略信号优先, reason 保留)
            - 不同股票的信号 → 全部保留
            - BUY 信号 → 不受止损影响 (止损只生成 SELL)
        """
        merged = {}
        # 先放止损信号, 再放策略信号 (策略覆盖止损, 因为策略 SELL 已经决定卖了)
        for sig in stop_signals + strategy_signals:
            key = (sig["ts_code"], sig["action"])
            merged[key] = sig
        return list(merged.values())

    def _allocate_and_price(
        self,
        signals: List[dict],
        price_lookup: Dict[str, Dict[str, tuple]],
        exec_date: str,
    ) -> List[dict]:
        """
        资金分配 + 用 T+1 开盘价替换信号价

        策略 (动态等分 + weight 硬上限):
            1. BUY 信号: 按可用资金 × 总预算比例 / 信号数 均分
            2. 单股上限: total_asset × weight (硬上限, 不可逾越)
               - 默认 weight=0.20, 即单股最多投总资产的 20%
               - 动态等分 per_signal 若超过上限, 截断到上限
               - 动态等分 per_signal 若小于上限, 用等分值
            3. SELL 信号: 不传 volume (清仓), 价格用 T+1 开盘价
        """
        buy_signals = [s for s in signals if s["action"] == "BUY"]
        sell_signals = [s for s in signals if s["action"] == "SELL"]

        enriched = []

        # --- SELL: 清仓, 价格用 T+1 开盘价 ---
        for sig in sell_signals:
            ts_code = sig["ts_code"]
            if ts_code in price_lookup and exec_date in price_lookup[ts_code]:
                open_price = price_lookup[ts_code][exec_date][0]
                sig["price"] = open_price
            enriched.append(sig)

        # --- BUY: 动态等分资金分配 (weight 作为硬上限) ---
        if not buy_signals:
            return enriched

        # 动态仓位: 若启用 position_scaler, 根据市场环境调整资金使用比例
        if self.position_scaler:
            budget_ratio = self.position_scaler.get_budget_ratio(exec_date)
        else:
            budget_ratio = self.total_budget_ratio

        investable = self.account.available_cash * budget_ratio
        per_signal = investable / len(buy_signals)

        for sig in buy_signals:
            ts_code = sig["ts_code"]
            # 必须有 T+1 开盘价才能执行
            if ts_code not in price_lookup or exec_date not in price_lookup[ts_code]:
                logger.debug(f"{ts_code} 在 {exec_date} 无开盘价, 跳过")
                continue

            open_price = price_lookup[ts_code][exec_date][0]
            sig["price"] = open_price

            # 动态等分: 每个信号分 investable / n_signals
            # weight 作为硬上限: 单股仓位不能超过 total_asset × weight
            weight = self.weights.get(ts_code, 0.2)
            max_value = self.account.total_asset * weight
            actual_value = min(per_signal, max_value)

            volume = int(actual_value / open_price / 100) * 100  # 整手
            if volume > 0:
                sig["volume"] = volume
                enriched.append(sig)

        return enriched
