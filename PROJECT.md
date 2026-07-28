# 量化交易系统

> 基于 Python 的 A 股量化回测系统，从数据采集到策略回测到绩效分析的全流程工具。
> 面向学习者，代码结构清晰、模块解耦，便于逐步理解和迭代。

---

## 一、项目结构

```
quant_trading_system/
├── main.py                    # 主入口 (路由分发)
├── quant.db                   # SQLite 数据库 (日线/PE/指数/交易记录)
├── config/                    # 配置层
│   ├── settings.py            #   全局参数 (资金/止损/佣金/路径)
│   ├── stock_pool.yaml        #   股票池定义 (default/csi300/pe_universe 等)
│   ├── stock_pool_loader.py   #   股票池加载器
│   └── log_config.py          #   日志配置
│
├── data/                      # 数据层
│   ├── fetcher/               #   数据采集
│   │   ├── stock_daily.py     #     个股日线 (akshare)
│   │   ├── index.py           #     指数日线
│   │   ├── stock_basic.py     #     股票列表
│   │   ├── financial.py       #     财务数据
│   │   ├── fetch_csi300_pool.py  #  沪深300成分股拉取
│   │   ├── fetch_pe_data.py   #     历史PE数据拉取
│   │   ├── tickflow_fetcher.py#     TickFlow 备用数据源
│   │   └── pipeline.py        #     数据更新流水线
│   ├── cleaner/               #   数据清洗
│   │   └── cleaner.py         #     去重/类型转换/列名统一
│   └── storage/               #   数据存储
│       ├── models.py          #     SQLAlchemy 表定义
│       └── database.py        #     DataStore (CRUD + upsert)
│
├── strategy/                  # 策略层
│   ├── base_strategy.py       #   策略基类
│   ├── portfolio_runner.py    #   组合回测编排器 (择时)
│   ├── select_stock_runner.py #   选股回测编排器
│   ├── timing/                #   择时策略
│   │   ├── ma_cross.py        #     MA 双均线交叉
│   │   ├── rsi_revert.py      #     RSI 均值回归
│   │   └── adx_filter.py      #     ADX 趋势强度过滤
│   ├── select_stock/          #   选股策略
│   │   ├── pe_quantile.py     #     PE 历史分位数选股
│   │   └── volatility_selector.py  # 动态波动率筛选器
│   └── risk/                  #   风险控制
│       ├── stop_loss.py       #     个股止损 (追踪/固定)
│       ├── portfolio_stop.py  #     组合级回撤止损
│       ├── market_filter.py   #     市场环境过滤
│       └── position_scaler.py #     动态仓位管理
│
├── simulation/                # 模拟层
│   ├── account.py             #   虚拟账户 (Position/持仓/现金)
│   ├── order_manager.py       #   订单管理 (买入/卖出/手续费)
│   └── scheduler.py           #   日级调度器 (T+1 执行)
│
├── cli/                       # 命令行接口
│   ├── parser.py              #   argparse 参数定义
│   ├── data_commands.py       #   数据更新/拉取
│   ├── backtest_commands.py   #   回测命令 (单股/组合/PE)
│   └── sim_commands.py        #   模拟交易/报告
│
├── monitor/                   # 监控层
│   ├── reporter.py            #   文本绩效报告
│   ├── risk_monitor.py        #   实时风控检查
│   ├── report_viewer.py       #   回测结果分析 (指标计算)
│   └── dashboard.py           #   Streamlit 可视化面板
│
├── analysis/                  # 分析工具
│   ├── analyze_market_regime.py  # 大盘行情阶段分析
│   └── analyze_volatility.py     # 波动率分析
│
├── experiments/               # 实验脚本
│   ├── scan_subperiods.py     #   子区间滚动回测
│   └── scan_lookback.py       #   参数扫描
│
└── output/                    # 输出目录 (回测结果/分析报告)
```

**分层依赖关系**：`config/` ← `data/` ← `simulation/` ← `strategy/` ← `cli/` ← `main.py`
strategy 层只依赖 simulation 层，数据拉取逻辑由 cli 层（编排层）负责。

---

## 二、核心算法

### 1. MA 双均线交叉择时 (趋势跟踪)

**文件**：`strategy/timing/ma_cross.py`

**逻辑**：
- 短期均线上穿长期均线（金叉）→ BUY
- 短期均线下穿长期均线（死叉）→ SELL
- 可选 ADX 过滤：ADX > 阈值才允许买入（确认趋势已形成）

**参数**：
- `short_window`: 短期均线周期（默认 5）
- `long_window`: 长期均线周期（默认 20 或 30）
- `adx_threshold`: ADX 过滤阈值（0 = 不过滤，25 = 只在强趋势时买入）

**适用场景**：趋势市，高波动股票池。震荡市频繁假信号，需配合止损。

---

### 2. RSI 均值回归择时 (震荡市)

**文件**：`strategy/timing/rsi_revert.py`

**逻辑**：
- RSI 从下方上穿超卖线（30）→ BUY（超卖反弹）
- RSI 从上方下穿超买线（70）→ SELL（超买回落）
- 使用 Wilder 平滑法计算 RSI

**参数**：
- `rsi_period`: RSI 计算周期（默认 14）
- `oversold`: 超卖阈值（默认 30）
- `overbought`: 超买阈值（默认 70）

**适用场景**：震荡市，与 MA 趋势策略互补。可作为附加策略并行运行，信号叠加。

---

### 3. PE 历史分位数选股 (价值投资)

**文件**：`strategy/select_stock/pe_quantile.py`

**逻辑**：
- 调仓日计算每只候选股票当前 PE 在过去 N 年历史中的分位数
- 选分位数最低的 top_n 只股票（估值相对自身历史最便宜）
- 等权持有，定期调仓

**参数**：
- `quantile_threshold`: PE 分位数上限（默认 0.3，只选历史 30% 分位以下）
- `lookback_years`: 历史回看年数（默认 3）
- `top_n`: 最多持有股票数（默认 3）
- `rebalance_freq`: 调仓频率（monthly / quarterly）

**适用场景**：横截面选股，与 MA 择时（时间序列）互补。PE 数据存储在 quant.db 的 pe_history 表。

---

### 4. 动态波动率筛选器 (事前选股)

**文件**：`strategy/select_stock/volatility_selector.py`

**逻辑**：
- 每月调仓日，从候选池按"过去 N 天日收益率标准差"排序
- 选波动率最高的 top_n 只作为"可买入池"
- 已持仓股票跌出 top_n 不清仓，交给 MA 死叉/止损决定卖出
- 新买入信号只允许买"可买入池"里的股票

**参数**：
- `lookback_days`: 波动率计算回看天数（默认 60 交易日）
- `top_n`: 选波动率前 N 只（默认 10）
- `rebalance_freq`: 调仓频率（monthly / weekly）

**适用场景**：MA 趋势策略在高波动股票上表现更好，波动率筛选器用于从大池子中事前选出适合趋势跟踪的股票。

---

### 5. 风险控制模块

#### 5.1 个股止损 `strategy/risk/stop_loss.py`

| 类型 | 逻辑 | 参数 |
|------|------|------|
| 追踪止损 (推荐) | 从持仓最高价回撤达阈值则卖出 | `trailing_pct` (默认 8%) |
| 固定止损 | 亏损达阈值则卖出（相对成本价） | `stop_loss_pct` (默认 10%) |

执行时机：T 日收盘价检查 → T+1 开盘成交，与策略信号一致。

#### 5.2 组合级回撤止损 `strategy/risk/portfolio_stop.py`

- 跟踪组合净值峰值，回撤超阈值时清仓所有持仓并暂停开新仓
- 等待 recovery_days 个交易日后自动恢复
- 参数：`drawdown_threshold` (如 0.12)、`recovery_days` (默认 20)

#### 5.3 市场环境过滤 `strategy/risk/market_filter.py`

基于沪深300指数判断是否适合开仓：
- `price_above_ma`: 收盘价 > MA60 → 允许开仓
- `ma_slope_up`: MA60 斜率向上 → 允许开仓
- `both`: 两者同时满足

只影响 BUY 信号，不影响 SELL。

#### 5.4 动态仓位管理 `strategy/risk/position_scaler.py`

基于沪深300均线位置连续调整开仓资金比例：
- 价格远高于 MA60（强趋势）：满仓 (90%)
- 价格在 MA60 附近（震荡）：半仓 (45%)
- 价格远低于 MA60（下跌）：轻仓 (10%)

线性插值平滑过渡，避免追涨杀跌。

---

## 三、运行指令

### 3.1 数据准备

```bash
# 初始化数据库（建表）
python main.py --init-db

# 增量更新所有数据（股票列表 + 日线 + 指数）
python main.py --mode update_data

# 拉取指定股票池的日线数据
python main.py --mode fetch-pool --pool default --start 20240101

# 拉取沪深300成分股列表
python data/fetcher/fetch_csi300_pool.py

# 拉取历史PE数据（写入 quant.db）
python data/fetcher/fetch_pe_data.py --pool default
```

### 3.2 回测

```bash
# 单股票回测 (MA 双均线)
python main.py --mode backtest --stock 000001.SZ --start 20240101 --short 5 --long 20

# 多股票组合回测 (MA + 追踪止损)
python main.py --mode backtest-pool --pool default --start 20240101 \
    --short 5 --long 30 --stop-loss trailing

# 组合回测 + 动态波动率筛选 (60日回看, 选前10只)
python main.py --mode backtest-pool --pool csi300 --start 20240101 \
    --short 5 --long 30 --stop-loss trailing \
    --dynamic-vol --vol-lookback 60 --vol-top 10

# 组合回测 + 市场环境过滤 + 动态仓位
python main.py --mode backtest-pool --pool default --start 20240101 \
    --short 5 --long 30 --stop-loss trailing \
    --market-filter price_above_ma --position-scaler

# 组合回测 + RSI 多策略并行
python main.py --mode backtest-pool --pool default --start 20240101 \
    --short 5 --long 30 --stop-loss trailing --rsi

# 组合回测 + 组合级回撤止损 (12% 阈值)
python main.py --mode backtest-pool --pool default --start 20240101 \
    --short 5 --long 30 --stop-loss trailing --portfolio-dd 0.12

# PE 选股回测
python main.py --mode backtest-pe --pool default --start 20230101 \
    --quantile 0.3 --lookback 3 --top-n 3 --freq monthly
```

### 3.3 模拟交易与报告

```bash
# 运行模拟交易 (示例空跑)
python main.py --mode simulation

# 启动 Streamlit 可视化面板
python run_dashboard.py
# 或
streamlit run monitor/dashboard.py
```

### 3.4 实验脚本

```bash
# 子区间滚动回测 (验证策略在不同时间段的表现)
python experiments/scan_subperiods.py

# 参数扫描 (对比不同 lookback 天数的效果)
python experiments/scan_lookback.py

# 大盘行情阶段分析
python analysis/analyze_market_regime.py
```

### 3.5 常用参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 运行模式 | simulation |
| `--pool` | 股票池名称 | default |
| `--start` | 回测起始日期 YYYYMMDD | 20240101 |
| `--short` / `--long` | MA 短期/长期均线周期 | 5 / 20 |
| `--stop-loss` | 止损类型 (trailing/fixed/none) | trailing |
| `--stop-pct` | 自定义止损比例 | trailing=0.08, fixed=0.10 |
| `--adx-threshold` | ADX 过滤阈值 (0=不过滤) | 0 |
| `--dynamic-vol` | 启用动态波动率筛选 | 关 |
| `--vol-lookback` / `--vol-top` | 波动率回看天数 / 选前N只 | 60 / 10 |
| `--market-filter` | 市场环境过滤规则 | 关 |
| `--position-scaler` | 动态仓位管理 | 关 |
| `--rsi` | RSI 多策略并行 | 关 |
| `--portfolio-dd` | 组合回撤止损阈值 | 关 |
| `--quantile` | PE 分位数阈值 | 0.3 |
| `--lookback` | PE 历史回看年数 | 3 |
| `--top-n` | 最多持有股票数 | 3 |
| `--freq` | 调仓频率 (monthly/quarterly) | monthly |

---

## 四、股票池

在 `config/stock_pool.yaml` 中定义，可用池：

| 池名 | 说明 | 数量 |
|------|------|------|
| `default` | 高波动成长股 | 5 |
| `pe_universe` | PE选股候选池（多行业分散） | 30 |
| `high_vol` | 高波动筛选池 | 10 |
| `high_vol_alt` | 对照池A（与high_vol不重叠） | 10 |
| `high_vol_mix` | 对照池B（混合高波动） | 10 |
| `conservative` | 保守蓝筹池 | 3 |
| `mini` | 最小验证池 | 2 |
| `csi100` | 沪深300前100只 | 100 |
| `csi300` | 沪深300全部成分股 | 300 |

---

## 五、关键实验结论

> 详见 `EXPERIMENTS.md`

- **追踪止损 8%** 最优：54.37% 收益，-14.22% 回撤，1.058 夏普（优于 5%/12%）
- **MA(5,30)** 优于 MA(5,20)：减少震荡市假信号，配合高波动池(10只)达 50.98% 收益
- **候选池大小关键**：csi300 池 6/10 子区间跑赢基准，csi100 仅 2/5；波动率筛选需要足够大的池子
- **5年回测**（2021-2026，csi300 + MA(5,30) + 8%追踪止损）：6/10 子区间跑赢沪深300，超额收益 -0.23%（基本持平）
- **MA 趋势策略特性**：小池子上是"市场放大器"，趋势市跑赢、震荡市跑输，无法通过简单过滤消除

---

## 六、技术栈

- **数据源**：akshare（主）+ TickFlow（备用）
- **存储**：SQLite + SQLAlchemy
- **回测**：自研 VirtualAccount + OrderManager + SimulationScheduler
- **分析**：pandas + numpy
- **可视化**：Streamlit + Plotly
- **日志**：loguru
