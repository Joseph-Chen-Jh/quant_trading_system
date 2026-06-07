"""
测试：打印股票列表数据前 20 行
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.database import DataStore

store = DataStore()
df = store.load_stock_basic()

print(f"股票总数: {len(df)}")
print(f"列名: {list(df.columns)}")
print()
print(df.head(20).to_string(index=False))
