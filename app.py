"""
线上自习室 - 启动器版
双击自动启动服务器并打开浏览器
"""

import webbrowser
import subprocess
import sys
import time
import os

# 启动 server
server_path = os.path.join(os.path.dirname(__file__), "server.py")
subprocess.Popen([sys.executable, server_path])

# 等2秒让服务器启动
time.sleep(2)

# 自动打开浏览器
webbrowser.open("http://localhost:8000")

print("✅ 服务器已启动！浏览器即将打开...")
print("📚 线上自习室 - By 郑智鹏")
print("📧 15702419317@163.com")
print("按 Ctrl+C 退出")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("👋 已退出")