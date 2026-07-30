"""
全局配置文件
"""

import os

# ======================== 网络代理配置 ========================
# 背景: VPN/科学上网工具会自动恢复 Windows 系统代理 (ProxyEnable=1,
#       ProxyServer=127.0.0.1:15490), 但代理服务未运行,
#       导致 requests 走死代理后所有 HTTPS 请求失败 (ProxyError/RemoteDisconnected)。
# 本项目所有数据源 (新浪/腾讯/东方财富) 均为国内直连, 不需要代理,
# 故全局禁用 requests 读取系统/环境代理。
os.environ.setdefault(
    "NO_PROXY",
    "eastmoney.com,push2his.eastmoney.com,sinajs.cn,sina.com.cn,gtimg.cn,qq.com,127.0.0.1,localhost",
)
try:
    import requests.utils as _req_utils
    # monkey-patch: 让 requests 不再从系统注册表/环境变量读取代理
    _req_utils.get_environ_proxies = lambda url, no_proxy=None: {}
except ImportError:
    pass

# ======================== 路径配置 ========================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 数据库路径
DATABASE_PATH = os.path.join(BASE_DIR, "quant.db")

# ======================== 市场规则 ========================
T_PLUS_1 = True              # T+1 交易制度
LIMIT_UP_DOWN = 0.10         # 主板涨跌停 10%
MIN_LOT = 100                # 最小交易单位 (1手 = 100股)
STAMP_TAX = 0.001            # 卖出印花税 0.1%
COMMISSION_RATE = 0.0003     # 券商佣金 0.03%
SLIPPAGE = 0.001             # 滑点 0.1%

# ======================== 模拟交易 ========================
INITIAL_CASH = 1_000_000     # 初始虚拟资金
MAX_POSITION_PCT = 0.20      # 单只股票最大仓位
MAX_TOTAL_POSITION = 0.80    # 总仓位上限
STOP_LOSS_PCT = 0.10         # 固定止损比例 (亏损达 10% 触发)
TRAILING_STOP_PCT = 0.08     # 追踪止损比例 (从最高价回撤 8% 触发)
MAX_DRAWDOWN = 0.15          # 最大回撤清仓线
DAILY_TRADE_LIMIT = 10       # 每日最大交易次数
MIN_DAILY_AMOUNT = 10_000_000  # 最小日成交额 (1000万)

# ======================== 回测 ========================
BACKTEST_INITIAL_CASH = 1_000_000
BACKTEST_COMMISSION = 0.0003

# ======================== 数据配置 ========================
# AkShare 请求间隔 (秒)，避免频率限制
AKSHARE_REQUEST_INTERVAL = 0.5

# 股票池过滤
STOCK_POOL_EXCLUDE_ST = True
STOCK_POOL_EXCLUDE_NEW = True  # 排除上市不足60天的新股

# ======================== 日志 ========================
LOG_LEVEL = "INFO"
LOG_RETENTION = "30 days"

# ======================== API Keys (如有) ========================
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
