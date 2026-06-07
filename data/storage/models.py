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
    """股票基础信息"""
    __tablename__ = "stock_basic"

    ts_code = Column(String(20), primary_key=True, comment="股票代码")
    name = Column(String(50), comment="股票名称")
    industry = Column(String(50), comment="行业")
    area = Column(String(20), comment="地区")
    list_date = Column(Date, comment="上市日期")
    delist_date = Column(Date, comment="退市日期")
    is_hs = Column(String(10), comment="是否沪深港通")


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
