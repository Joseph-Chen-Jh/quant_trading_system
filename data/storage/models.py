"""
SQLAlchemy 数据模型定义
"""
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, Text,
    create_engine, PrimaryKeyConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker
from config.settings import DATABASE_PATH

Base = declarative_base()


class StockBasic(Base):
    """股票基础信息

    字段与 fetcher.stock_basic.fetch_all_stocks() 输出对齐:
    akshare 的 stock_zh_a_spot_em / stock_info_a_code_name 仅提供这些字段。
    若后续需要 industry/area/list_date，应换用支持更丰富字段的接口。
    """
    __tablename__ = "stock_basic"

    ts_code = Column(String(20), primary_key=True, comment="股票代码 000001.SZ")
    code = Column(String(10), index=True, comment="纯数字代码 000001")
    name = Column(String(50), comment="股票名称")
    market = Column(String(10), comment="市场 SH / SZ")
    is_st = Column(Integer, comment="是否ST: 0/1")


class DailyPrice(Base):
    """日线行情"""
    __tablename__ = "daily_price"
    __table_args__ = (PrimaryKeyConstraint("ts_code", "trade_date"),)

    ts_code = Column(String(20), index=True)
    trade_date = Column(String(10))
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    amount = Column(Float)
    turnover = Column(Float, comment="换手率(%)")


class IndexDaily(Base):
    """指数日线"""
    __tablename__ = "index_daily"
    __table_args__ = (PrimaryKeyConstraint("ts_code", "trade_date"),)

    ts_code = Column(String(20), index=True)
    trade_date = Column(String(10))
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    amount = Column(Float)


class FinancialData(Base):
    """财务数据"""
    __tablename__ = "financial_data"
    __table_args__ = (PrimaryKeyConstraint("ts_code", "end_date"),)

    ts_code = Column(String(20), index=True)
    end_date = Column(String(10), comment="报告期")
    ann_date = Column(String(10), comment="公告日期")
    revenue = Column(Float, comment="营业收入")
    profit = Column(Float, comment="净利润")
    roe = Column(Float, comment="净资产收益率")
    pe = Column(Float, comment="市盈率")
    pb = Column(Float, comment="市净率")


class PEHistory(Base):
    """历史PE数据 (每日PE值, 用于PE分位数选股)"""
    __tablename__ = "pe_history"
    __table_args__ = (PrimaryKeyConstraint("ts_code", "trade_date"),)

    ts_code = Column(String(20), index=True)
    trade_date = Column(String(10))
    pe = Column(Float, comment="市盈率(TTM)")


class ChipDistribution(Base):
    """筹码分布衍生指标 (基于 K线+换手率 估算, 精度约 90%, 对标通达信 CYQ)

    计算方法: 三角分布 + 换手率衰减
    - 当日新增筹码按三角形落在 [low, high, avg] 区间, avg=(H+L+C)/3
    - 旧筹码按 (1 - turnover * decay_coeff) 衰减
    - 计算窗口: 滚动 120 天
    """
    __tablename__ = "chip_distribution"
    __table_args__ = (PrimaryKeyConstraint("ts_code", "trade_date"),)

    ts_code = Column(String(20), index=True)
    trade_date = Column(String(10))
    profit_ratio = Column(Float, comment="获利比例 (0-1): 当前价以下筹码占比")
    avg_cost = Column(Float, comment="平均成本: 筹码加权均价")
    cost_90_low = Column(Float, comment="90%筹码下沿")
    cost_90_high = Column(Float, comment="90%筹码上沿")
    concentration_90 = Column(Float, comment="90%集中度: (上沿-下沿)/均价")
    cost_70_low = Column(Float, comment="70%筹码下沿")
    cost_70_high = Column(Float, comment="70%筹码上沿")
    concentration_70 = Column(Float, comment="70%集中度: (上沿-下沿)/均价")


class TradeRecord(Base):
    """交易记录"""
    __tablename__ = "trade_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20))
    direction = Column(String(10), comment="BUY / SELL")
    price = Column(Float)
    volume = Column(Integer)
    commission = Column(Float)
    stamp_tax = Column(Float)
    trade_time = Column(DateTime)
    profit_loss = Column(Float, nullable=True, comment="平仓盈亏")


class DailyNAV(Base):
    """每日净值"""
    __tablename__ = "daily_nav"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(String(10), unique=True)
    nav = Column(Float, comment="总资产")
    cash = Column(Float)
    position_value = Column(Float)
    daily_return = Column(Float, comment="日收益率")


def init_database():
    """建表"""
    engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    """获取数据库会话"""
    if engine is None:
        engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
    Session = sessionmaker(bind=engine)
    return Session()
