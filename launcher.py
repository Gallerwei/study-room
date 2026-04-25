import subprocess
import sys
import time
import webbrowser
import os

started = False

# 检查服务器是否已经在运行
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', 8000))
s.close()

if result != 0:
    # 服务器没运行，启动它
    server_path = os.path.join(os.path.dirname(__file__), "server.py")
    subprocess.Popen([sys.executable, server_path], creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(3)
    started = True

# 只打开一次浏览器
webbrowser.open("http://localhost:8000", new=0)

if started:
    print("服务器已启动！浏览器已打开。")
else:
    print("服务器已在运行，浏览器已打开。")

# 保持运行
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass