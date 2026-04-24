"""
线上自习室服务器，郑智鹏编制
在 PyCharm 中右键运行此文件即可启动
"""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import socketio
from aiohttp import web
from aiohttp.web import FileResponse
import aiohttp_cors

# ============ 创建服务器 ============
sio = socketio.AsyncServer(
    async_mode='aiohttp',
    cors_allowed_origins='*',
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False
)

app = web.Application()
sio.attach(app)

# 配置跨域
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
})

# ============ 数据存储 ============
rooms: Dict[str, dict] = {}
users: Dict[str, dict] = {}
room_users: Dict[str, set] = {}
chat_messages: Dict[str, list] = {}

# ============ 静态文件路径 ============
STATIC_DIR = Path(__file__).parent / "static"


# ============ HTTP 路由处理 ============
async def index(request):
    """首页"""
    return FileResponse(STATIC_DIR / "index.html")


async def room_page(request):
    """自习室页面"""
    return FileResponse(STATIC_DIR / "room.html")


async def get_style(request):
    """CSS样式"""
    return FileResponse(STATIC_DIR / "style.css")


async def get_script(request):
    """JavaScript"""
    return FileResponse(STATIC_DIR / "script.js")


async def api_health(request):
    """健康检查"""
    return web.json_response({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "rooms_count": len(rooms),
        "users_online": len(users)
    })


async def api_create_room(request):
    """创建房间"""
    try:
        data = await request.json()
        room_id = str(uuid.uuid4())[:8]
        room_name = data.get('room_name', f'自习室{room_id}')
        max_users = int(data.get('max_users', 10))
        password = data.get('password', '')

        rooms[room_id] = {
            'id': room_id,
            'name': room_name,
            'max_users': max_users,
            'password': password,
            'created_at': datetime.now().isoformat(),
            'status': 'active'
        }
        room_users[room_id] = set()
        chat_messages[room_id] = []

        print(f'✅ 房间创建成功: {room_id} - {room_name}')
        return web.json_response({
            'success': True,
            'room_id': room_id,
            'room_name': room_name,
            'message': '房间创建成功！'
        })
    except Exception as e:
        print(f'❌ 创建房间失败: {e}')
        return web.json_response({'error': str(e)}, status=400)


async def api_get_rooms(request):
    """获取房间列表"""
    rooms_list = []
    for room_id, room in rooms.items():
        rooms_list.append({
            'id': room_id,
            'name': room['name'],
            'online': len(room_users.get(room_id, set())),
            'max_users': room['max_users'],
            'has_password': bool(room['password']),
            'status': room['status']
        })
    return web.json_response(rooms_list)


async def api_room_info(request):
    """获取房间信息"""
    room_id = request.match_info.get('room_id')
    room = rooms.get(room_id)
    if not room:
        return web.json_response({'error': '房间不存在'}, status=404)

    return web.json_response({
        'id': room['id'],
        'name': room['name'],
        'online': len(room_users.get(room_id, set())),
        'max_users': room['max_users'],
        'has_password': bool(room['password']),
        'status': room['status']
    })


# 注册路由
app.router.add_get('/', index)
app.router.add_get('/room', room_page)
app.router.add_get('/room.html', room_page)
app.router.add_get('/style.css', get_style)
app.router.add_get('/script.js', get_script)
app.router.add_get('/api/health', api_health)
app.router.add_post('/api/rooms', api_create_room)
app.router.add_get('/api/rooms', api_get_rooms)
app.router.add_get('/api/rooms/{room_id}', api_room_info)
app.router.add_static('/static/', path=STATIC_DIR, name='static')
app.router.add_get('/miku.png', lambda r: FileResponse(STATIC_DIR / "miku.png"))


# ============ Socket.IO 事件处理 ============

@sio.event
async def connect(sid, environ):
    """用户连接"""
    print(f'🟢 新连接: {sid}')
    users[sid] = {
        'id': sid,
        'name': f'用户{sid[:6]}',
        'connected_at': datetime.now().isoformat(),
        'room_id': None,
        'is_muted': False,
        'is_video_off': False
    }


@sio.event
async def disconnect(sid):
    """用户断开"""
    print(f'🔴 断开连接: {sid}')
    await handle_user_leave(sid)


@sio.event
async def join_room(sid, data):
    """加入房间"""
    try:
        room_id = data.get('room_id')
        user_name = data.get('user_name', f'用户{sid[:6]}')
        password = data.get('password', '')

        print(f'📥 {user_name} 请求加入房间 {room_id}')

        # 验证房间
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

        # 更新用户信息
        users[sid]['name'] = user_name
        users[sid]['room_id'] = room_id

        # 加入房间
        if room_id not in room_users:
            room_users[room_id] = set()
        room_users[room_id].add(sid)
        sio.enter_room(sid, room_id)

        # 获取房间内其他用户
        existing_users = []
        for uid in room_users[room_id]:
            if uid != sid:
                existing_users.append(users[uid])

        # 通知其他人
        await sio.emit('user_joined', {
            'user': users[sid]
        }, room=room_id, skip_sid=sid)

        # 发送给新用户
        await sio.emit('room_joined', {
            'success': True,
            'room_id': room_id,
            'room_name': room['name'],
            'current_user': users[sid],
            'existing_users': existing_users,
            'messages': chat_messages.get(room_id, [])[-50:]
        }, to=sid)

        # 更新在线列表
        online_users = [users[u] for u in room_users[room_id]]
        await sio.emit('online_update', {
            'count': len(online_users),
            'users': online_users
        }, room=room_id)

        print(f'✅ {user_name} 成功加入房间 {room_id}，当前在线: {len(online_users)}人')

    except Exception as e:
        print(f'❌ 加入房间失败: {e}')
        await sio.emit('error', {'message': str(e)}, to=sid)


@sio.event
async def leave_room(sid, data=None):
    """离开房间"""
    await handle_user_leave(sid)


async def handle_user_leave(sid):
    """处理用户离开"""
    user = users.get(sid)
    if not user:
        return

    room_id = user.get('room_id')
    user_name = user.get('name')

    if room_id and room_id in room_users:
        room_users[room_id].discard(sid)
        sio.leave_room(sid, room_id)

        # 通知其他用户
        await sio.emit('user_left', {
            'user_id': sid,
            'user_name': user_name
        }, room=room_id)

        # 更新在线列表
        online_users = [users[u] for u in room_users[room_id]]
        await sio.emit('online_update', {
            'count': len(online_users),
            'users': online_users
        }, room=room_id)

        print(f'👋 {user_name} 离开了房间 {room_id}')

        # 清理空房间
        if len(room_users[room_id]) == 0:
            del room_users[room_id]
            if room_id in chat_messages:
                del chat_messages[room_id]
            print(f'🗑️ 房间 {room_id} 已清空')

    users.pop(sid, None)


# ============ WebRTC 信令 ============

@sio.event
async def webrtc_offer(sid, data):
    """转发 WebRTC Offer"""
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_offer', {
            'from_sid': sid,
            'from_name': users[sid]['name'],
            'sdp': data['sdp']
        }, to=target)


@sio.event
async def webrtc_answer(sid, data):
    """转发 WebRTC Answer"""
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_answer', {
            'from_sid': sid,
            'sdp': data['sdp']
        }, to=target)


@sio.event
async def webrtc_ice_candidate(sid, data):
    """转发 ICE Candidate"""
    target = data.get('target_sid')
    if target:
        await sio.emit('webrtc_ice_candidate', {
            'from_sid': sid,
            'candidate': data['candidate']
        }, to=target)


# ============ 媒体控制 ============

@sio.event
async def toggle_mute(sid, data):
    """切换静音"""
    if sid in users:
        users[sid]['is_muted'] = data.get('is_muted', False)
        room_id = users[sid].get('room_id')
        if room_id:
            await sio.emit('user_updated', users[sid], room=room_id)


@sio.event
async def toggle_video(sid, data):
    """切换视频"""
    if sid in users:
        users[sid]['is_video_off'] = data.get('is_video_off', False)
        room_id = users[sid].get('room_id')
        if room_id:
            await sio.emit('user_updated', users[sid], room=room_id)


# ============ 聊天功能 ============

@sio.event
async def send_message(sid, data):
    """发送消息"""
    user = users.get(sid)
    if not user or not user.get('room_id'):
        return

    room_id = user['room_id']
    message = {
        'id': str(uuid.uuid4()),
        'user_id': sid,
        'user_name': user['name'],
        'text': data.get('text', ''),
        'timestamp': datetime.now().isoformat(),
        'type': 'text'
    }

    if room_id not in chat_messages:
        chat_messages[room_id] = []
    chat_messages[room_id].append(message)

    if len(chat_messages[room_id]) > 200:
        chat_messages[room_id] = chat_messages[room_id][-200:]

    await sio.emit('new_message', message, room=room_id)


# ============ 番茄钟同步 ============

@sio.event
async def timer_start(sid, data):
    """开始计时"""
    user = users.get(sid)
    if user and user.get('room_id'):
        await sio.emit('timer_started', {
            'user_id': sid,
            'user_name': user['name'],
            'work_time': data.get('work_time', 25),
            'break_time': data.get('break_time', 5)
        }, room=user['room_id'])


@sio.event
async def timer_complete(sid, data):
    """计时完成"""
    user = users.get(sid)
    if user and user.get('room_id'):
        await sio.emit('timer_completed', {
            'user_id': sid,
            'user_name': user['name'],
            'message': f'🎉 {user["name"]} 完成了一个番茄钟！'
        }, room=user['room_id'])


# ============ 启动服务器 ============

def print_banner():
    """打印启动横幅"""
    banner = """
    ╔══════════════════════════════════════╗
    ║     📚 Python 线上自习室 📚         ║
    ║                                    ║
    ║  本地访问: http://localhost:8000    ║
    ║  局域网访问: http://你的IP:8000     ║
    ║  按 Ctrl+C 停止服务器               ║
    ╚══════════════════════════════════════╝
    """
    print(banner)


if __name__ == '__main__':
    print_banner()
    web.run_app(
        app,
        host='0.0.0.0',  # 允许外部访问
        port=8000,
        print=lambda *args: None  # 减少日志输出
    )