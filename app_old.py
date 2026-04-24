"""
线上自习室 - 桌面版
自带浏览器界面，无需手动打开网页
"""

import sys
import asyncio
import threading
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QMessageBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer

import socketio
from aiohttp import web
from aiohttp.web import FileResponse
import aiohttp_cors
import uuid
from datetime import datetime

# ============ 服务器部分 ============
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')




app_web = web.Application()
sio.attach(app_web)

cors = aiohttp_cors.setup(app_web, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})

rooms = {}
users = {}
room_users = {}
chat_messages = {}

STATIC_DIR = Path(__file__).parent / "static"


async def index(request):
    return FileResponse(STATIC_DIR / "index.html")


async def room_page(request):
    return FileResponse(STATIC_DIR / "room.html")


async def get_style(request):
    return FileResponse(STATIC_DIR / "style.css")


async def get_script(request):
    return FileResponse(STATIC_DIR / "script.js")


async def api_health(request):
    return web.json_response({"status": "ok"})


async def api_create_room(request):
    data = await request.json()
    room_id = str(uuid.uuid4())[:8]
    room_name = data.get('room_name', f'自习室{room_id}')
    max_users = int(data.get('max_users', 10))
    password = data.get('password', '')

    rooms[room_id] = {
        'id': room_id, 'name': room_name,
        'max_users': max_users, 'password': password,
        'created_at': datetime.now().isoformat(), 'status': 'active'
    }
    room_users[room_id] = set()
    chat_messages[room_id] = []

    return web.json_response({'success': True, 'room_id': room_id, 'room_name': room_name})


async def api_get_rooms(request):
    rooms_list = []
    for room_id, room in rooms.items():
        rooms_list.append({
            'id': room_id, 'name': room['name'],
            'online': len(room_users.get(room_id, set())),
            'max_users': room['max_users'],
            'has_password': bool(room['password']),
            'status': room['status']
        })
    return web.json_response(rooms_list)


async def api_room_info(request):
    room_id = request.match_info.get('room_id')
    room = rooms.get(room_id)
    if not room:
        return web.json_response({'error': '房间不存在'}, status=404)
    return web.json_response({
        'id': room['id'], 'name': room['name'],
        'online': len(room_users.get(room_id, set())),
        'max_users': room['max_users'],
        'has_password': bool(room['password'])
    })


app_web.router.add_get('/', index)
app_web.router.add_get('/room', room_page)
app_web.router.add_get('/room.html', room_page)
app_web.router.add_get('/style.css', get_style)
app_web.router.add_get('/script.js', get_script)
app_web.router.add_get('/api/health', api_health)
app_web.router.add_post('/api/rooms', api_create_room)
app_web.router.add_get('/api/rooms', api_get_rooms)
app_web.router.add_get('/api/rooms/{room_id}', api_room_info)
app_web.router.add_static('/static/', path=STATIC_DIR, name='static')


@sio.event
async def connect(sid, environ):
    users[sid] = {
        'id': sid, 'name': f'用户{sid[:6]}',
        'connected_at': datetime.now().isoformat(),
        'room_id': None, 'is_muted': False, 'is_video_off': False
    }


@sio.event
async def disconnect(sid):
    await handle_user_leave(sid)


@sio.event
async def join_room(sid, data):
    room_id = data.get('room_id')
    user_name = data.get('user_name', f'用户{sid[:6]}')
    password = data.get('password', '')

    room = rooms.get(room_id)
    if not room:
        await sio.emit('error', {'message': '房间不存在'}, to=sid)
        return

    if room['password'] and room['password'] != password:
        await sio.emit('error', {'message': '密码错误'}, to=sid)
        return

    if len(room_users.get(room_id, set())) >= room['max_users']:
        await sio.emit('error', {'message': '房间已满'}, to=sid)
        return

    users[sid]['name'] = user_name
    users[sid]['room_id'] = room_id

    if room_id not in room_users:
        room_users[room_id] = set()
    room_users[room_id].add(sid)
    sio.enter_room(sid, room_id)

    existing_users = [users[u] for u in room_users[room_id] if u != sid]

    await sio.emit('user_joined', {'user': users[sid]}, room=room_id, skip_sid=sid)
    await sio.emit('room_joined', {
        'success': True, 'room_id': room_id, 'room_name': room['name'],
        'current_user': users[sid], 'existing_users': existing_users,
        'messages': chat_messages.get(room_id, [])[-50:]
    }, to=sid)

    online = [users[u] for u in room_users[room_id]]
    await sio.emit('online_update', {'count': len(online), 'users': online}, room=room_id)


@sio.event
async def leave_room(sid, data=None):
    await handle_user_leave(sid)


async def handle_user_leave(sid):
    user = users.get(sid)
    if not user:
        return
    room_id = user.get('room_id')
    if room_id and room_id in room_users:
        room_users[room_id].discard(sid)
        sio.leave_room(sid, room_id)
        await sio.emit('user_left', {'user_id': sid, 'user_name': user['name']}, room=room_id)
        online = [users[u] for u in room_users[room_id]]
        await sio.emit('online_update', {'count': len(online), 'users': online}, room=room_id)
        if len(room_users[room_id]) == 0:
            del room_users[room_id]
            if room_id in chat_messages:
                del chat_messages[room_id]
    users.pop(sid, None)


@sio.event
async def webrtc_offer(sid, data):
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_offer', {
            'from_sid': sid, 'from_name': users[sid]['name'], 'sdp': data['sdp']
        }, to=target)


@sio.event
async def webrtc_answer(sid, data):
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_answer', {
            'from_sid': sid, 'sdp': data['sdp']
        }, to=target)


@sio.event
async def webrtc_ice_candidate(sid, data):
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_ice_candidate', {
            'from_sid': sid, 'candidate': data['candidate']
        }, to=target)


@sio.event
async def toggle_mute(sid, data):
    if sid in users:
        users[sid]['is_muted'] = data.get('is_muted', False)
        room_id = users[sid].get('room_id')
        if room_id:
            await sio.emit('user_updated', users[sid], room=room_id)


@sio.event
async def toggle_video(sid, data):
    if sid in users:
        users[sid]['is_video_off'] = data.get('is_video_off', False)
        room_id = users[sid].get('room_id')
        if room_id:
            await sio.emit('user_updated', users[sid], room=room_id)


@sio.event
async def send_message(sid, data):
    user = users.get(sid)
    if not user or not user.get('room_id'):
        return
    room_id = user['room_id']
    message = {
        'id': str(uuid.uuid4()), 'user_id': sid,
        'user_name': user['name'], 'text': data.get('text', ''),
        'timestamp': datetime.now().isoformat(), 'type': 'text'
    }
    if room_id not in chat_messages:
        chat_messages[room_id] = []
    chat_messages[room_id].append(message)
    if len(chat_messages[room_id]) > 200:
        chat_messages[room_id] = chat_messages[room_id][-200:]
    await sio.emit('new_message', message, room=room_id)


@sio.event
async def timer_start(sid, data):
    user = users.get(sid)
    if user and user.get('room_id'):
        await sio.emit('timer_started', {
            'user_id': sid, 'user_name': user['name'],
            'work_time': data.get('work_time', 25),
            'break_time': data.get('break_time', 5)
        }, room=user['room_id'])


@sio.event
async def timer_complete(sid, data):
    user = users.get(sid)
    if user and user.get('room_id'):
        await sio.emit('timer_completed', {
            'user_id': sid, 'user_name': user['name'],
            'message': f'🎉 {user["name"]} 完成了一个番茄钟！'
        }, room=user['room_id'])


# ============ Qt 桌面界面 ============

class StudyRoomApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("📚 线上自习室 - By 郑zp")
        self.resize(1280, 800)

        # 创建浏览器控件
        self.browser = QWebEngineView()
        self.browser.setUrl(QUrl("http://localhost:8000"))

        # 创建关于按钮
        from PyQt6.QtWidgets import QPushButton
        from PyQt6.QtCore import Qt

        self.about_btn = QPushButton("ℹ️ 关于：查看作者信息")
        self.about_btn.setStyleSheet("""
            QPushButton {
                position: absolute;
                top: 10px;
                right: 10px;
                z-index: 9999;
                background: rgba(255,255,255,0.9);
                border: 1px solid #ccc;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 13px;
                cursor: pointer;
            }
            QPushButton:hover {
                background: #667eea;
                color: white;
            }
        """)
        self.about_btn.clicked.connect(self.show_about)

        # 布局
        layout = QVBoxLayout()
        layout.addWidget(self.about_btn)
        layout.addWidget(self.browser)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def show_about(self):
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox()
        msg.setWindowTitle("作者の信息")
        msg.setText("📚 线上自习室 v1.0")
        msg.setInformativeText(
            "👨‍💻 开发者：郑智鹏\n"
            "📧 邮箱：15702419317@163.com\n"
            "💬 QQ：Galler wei\n\n"
            "© 2025 郑智鹏 版权所有"
        )
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()


def run_server():
    """在后台线程运行服务器"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    web.run_app(app_web, host='0.0.0.0', port=8000, print=lambda *args: None)


def main():
    # 启动服务器线程
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # 启动 Qt 应用
    qt_app = QApplication(sys.argv)
    window = StudyRoomApp()

    # 等服务器启动后再加载页面
    QTimer.singleShot(2000, lambda: window.browser.reload())

    window.show()
    sys.exit(qt_app.exec())


if __name__ == '__main__':
    main()