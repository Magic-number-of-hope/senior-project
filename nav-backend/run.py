# -*- coding: utf-8 -*-
"""启动脚本。"""
import os
import uvicorn
from app.config.settings import AMAP_API_KEY

if __name__ == "__main__":
    _dk = os.getenv("DASHSCOPE_API_KEY", "")
    _wk = os.getenv("AMAP_WEB_KEY", "")
    _ws = os.getenv("AMAP_WEB_SECRET", "")
    _sh = os.getenv("AMAP_WEB_SERVICE_HOST", "")
    print(f"[BOOT] DASHSCOPE_API_KEY: {'已设置 (' + _dk[:8] + '...)' if _dk else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_API_KEY:      {'已设置 (' + AMAP_API_KEY[:8] + '...)' if AMAP_API_KEY else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_WEB_KEY:      {'已设置 (' + _wk[:8] + '...)' if _wk else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_WEB_SECRET:   {'已设置 (' + _ws[:8] + '...)' if _ws else '⚠ 未设置!'}")
    print(f"[BOOT] AMAP_SERVICE_HOST: {_sh if _sh else '未设置(开发环境可使用 securityJsCode)'}")
    uvicorn.run("app.main:app", host="localhost", port=8000, reload=True, log_level="info")
