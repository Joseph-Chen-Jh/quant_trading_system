"""
Streamlit 启动器

在 import streamlit/tornado 之前打 SSL 补丁, 规避 Windows 证书库损坏问题.

用法:
    python run_dashboard.py
"""
import os
import sys
import ssl

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def patch_ssl():
    """用 certifi 证书替代 Windows 证书存储, 规避 ASN1 错误"""
    try:
        import certifi
        cert_path = certifi.where()

        def _safe_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(cafile=cert_path)
            ctx.check_hostname = kwargs.get("check_hostname", True)
            ctx.verify_mode = ssl.CERT_REQUIRED
            return ctx

        ssl.create_default_context = _safe_create_default_context
        print(f"[SSL] 使用 certifi 证书: {cert_path}")
    except Exception as e:
        # 退化方案: 不验证证书 (仅本地开发)
        def _no_verify_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        ssl.create_default_context = _no_verify_default_context
        print(f"[SSL] certifi 不可用 ({e}), 退化为不验证证书")


# 必须在 import streamlit 之前执行
patch_ssl()

# 现在才 import streamlit
from streamlit.web import cli as stcli


def main():
    dashboard_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "monitor", "dashboard.py"
    )
    sys.argv = [
        "streamlit",
        "run",
        dashboard_path,
        "--server.port=8501",
        "--server.headless=true",
    ]
    stcli.main()


if __name__ == "__main__":
    main()
