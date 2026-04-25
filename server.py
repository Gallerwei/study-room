"""
线上自习室服务器 - 支持手机号密码登录
"""

import hashlib
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import socketio
from aiohttp import web
from aiohttp.web import FileResponse
import aiohttp_cors

# ============ 数据库初始化 ============
DB_PATH = Path(__file__).parent / "study_room.db"


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        nickname TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS rooms_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL,
        room_name TEXT,
        user_phone TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit()
    conn.close()


init_db()


# ============ 数据库操作 ============
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(phone, password, nickname=""):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (phone, password, nickname) VALUES (?, ?, ?)",
                  (phone, hash_password(password), nickname or phone))
        conn.commit()
        return True, "注册成功"
    except sqlite3.IntegrityError:
        return False, "手机号已注册"
    finally:
        conn.close()


def login_user(phone, password):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT phone, nickname FROM users WHERE phone=? AND password=?",
              (phone, hash_password(password)))
    user = c.fetchone()
    conn.close()
    if user:
        return True, {"phone": user[0], "nickname": user[1]}
    return False, "手机号或密码错误"


def save_room_history(phone, room_id, room_name):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("INSERT INTO rooms_history (room_id, room_name, user_phone) VALUES (?, ?, ?)",
              (room_id, room_name, phone))
    conn.commit()
    conn.close()


def get_user_history(phone):
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT room_id, room_name, created_at FROM rooms_history WHERE user_phone=? ORDER BY id DESC LIMIT 10",
              (phone,))
    rows = c.fetchall()
    conn.close()
    return [{"room_id": r[0], "room_name": r[1], "time": r[2]} for r in rows]


# ============ 服务器初始化 ============
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*")
})

rooms = {}
users = {}
room_users = {}
chat_messages = {}

STATIC_DIR = Path(__file__).parent / "static"


# ============ HTTP路由 ============
async def index(request):
    return FileResponse(STATIC_DIR / "index.html")


async def room_page(request):
    return FileResponse(STATIC_DIR / "room.html")


async def get_style(request):
    return FileResponse(STATIC_DIR / "style.css")


async def get_script(request):
    return FileResponse(STATIC_DIR / "script.js")


async def get_miku(request):
    return FileResponse(STATIC_DIR / "miku.png")


async def api_health(request):
    return web.json_response({"status": "ok"})


async def api_register(request):
    data = await request.json()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    nickname = data.get('nickname', phone)
    if not phone or not password:
        return web.json_response({"success": False, "message": "手机号和密码不能为空"})
    if len(password) < 4:
        return web.json_response({"success": False, "message": "密码至少4位"})
    ok, msg = register_user(phone, password, nickname)
    return web.json_response({"success": ok, "message": msg})


async def api_login(request):
    data = await request.json()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    ok, result = login_user(phone, password)
    if ok:
        return web.json_response({"success": True, "user": result, "history": get_user_history(phone)})
    return web.json_response({"success": False, "message": result})


async def api_create_room(request):
    data = await request.json()
    room_id = str(uuid.uuid4())[:8]
    room_name = data.get('room_name', f'自习室{room_id}')
    max_users = int(data.get('max_users', 10))
    password = data.get('password', '')
    creator_phone = data.get('creator_phone', '')

    rooms[room_id] = {
        'id': room_id, 'name': room_name, 'max_users': max_users,
        'password': password, 'created_at': datetime.now().isoformat(), 'status': 'active'
    }
    room_users[room_id] = set()
    chat_messages[room_id] = []

    if creator_phone:
        save_room_history(creator_phone, room_id, room_name)

    return web.json_response({'success': True, 'room_id': room_id, 'room_name': room_name})


async def api_get_rooms(request):
    rooms_list = []
    for room_id, room in rooms.items():
        rooms_list.append({
            'id': room_id, 'name': room['name'],
            'online': len(room_users.get(room_id, set())),
            'max_users': room['max_users'], 'has_password': bool(room['password']),
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
        'max_users': room['max_users'], 'has_password': bool(room['password'])
    })


async def api_user_history(request):
    phone = request.query.get('phone', '')
    if not phone:
        return web.json_response([])
    return web.json_response(get_user_history(phone))


app.router.add_get('/', index)
app.router.add_get('/room', room_page)
app.router.add_get('/room.html', room_page)
app.router.add_get('/style.css', get_style)
app.router.add_get('/script.js', get_script)
app.router.add_get('/static/miku.png', get_miku)
app.router.add_get('/miku.png', get_miku)
app.router.add_get('/api/health', api_health)
app.router.add_post('/api/register', api_register)
app.router.add_post('/api/login', api_login)
app.router.add_post('/api/rooms', api_create_room)
app.router.add_get('/api/rooms', api_get_rooms)
app.router.add_get('/api/rooms/{room_id}', api_room_info)
app.router.add_get('/api/history', api_user_history)
# ============ Socket.IO事件 ============
@sio.event
async def test_msg(sid, data):
    print("========== 测试成功！==========")
    print(f"data: {data}")
@sio.event
async def connect(sid, environ):
    users[sid] = {'id': sid, 'name': f'用户{sid[:6]}', 'room_id': None, 'is_muted': False, 'is_video_off': False}


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
    existing = [users[u] for u in room_users[room_id] if u != sid]
    await sio.emit('user_joined', {'user': users[sid]}, room=room_id, skip_sid=sid)
    await sio.emit('room_joined', {
        'success': True, 'room_id': room_id, 'room_name': room['name'],
        'current_user': users[sid], 'existing_users': existing,
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
    users.pop(sid, None)


@sio.event
async def webrtc_offer(sid, data):
    t = data.get('target_sid')
    if t:
        await sio.emit('webrtc_offer', {'from_sid': sid, 'from_name': users[sid]['name'], 'sdp': data['sdp']}, to=t)


@sio.event
async def webrtc_answer(sid, data):
    t = data.get('target_sid')
    if t:
        await sio.emit('webrtc_answer', {'from_sid': sid, 'sdp': data['sdp']}, to=t)


@sio.event
async def webrtc_ice_candidate(sid, data):
    t = data.get('target_sid')
    if t:
        await sio.emit('webrtc_ice_candidate', {'from_sid': sid, 'candidate': data['candidate']}, to=t)


@sio.event
async def toggle_mute(sid, data):
    if sid in users:
        users[sid]['is_muted'] = data.get('is_muted', False)
        r = users[sid].get('room_id')
        if r:
            await sio.emit('user_updated', users[sid], room=r)

async def handle_room_msg(sid, data):
    user = users.get(sid)
    if not user:
        return
    room_id = user.get('room_id')
    if not room_id:
        return

    msg = {
        'id': str(uuid.uuid4()),
        'user_id': sid,
        'user_name': user.get('name', '未知'),
        'text': data.get('text', ''),
        'timestamp': datetime.now().isoformat()
    }

    if room_id not in chat_messages:
        chat_messages[room_id] = []
    chat_messages[room_id].append(msg)

    # 发给房间所有人（包括自己）
    await sio.emit('chat_new', msg, room=str(room_id))


sio.on('room_msg', handler=handle_room_msg)





@sio.event
async def timer_start(sid, data):
    u = users.get(sid)
    if u and u.get('room_id'):
        await sio.emit('timer_started', {
            'user_id': sid, 'user_name': u['name'],
            'work_time': data.get('work_time', 25)
        }, room=u['room_id'])


@sio.event
async def timer_complete(sid, data):
    u = users.get(sid)
    if u and u.get('room_id'):
        await sio.emit('timer_completed', {
            'user_id': sid, 'user_name': u['name'],
            'message': '🎉 完成番茄钟！'
        }, room=u['room_id'])




# ============ 启动服务器 ============
if __name__ == '__main__':
    print("""╔══════════════════════════════════════╗
║     📚 Python 线上自习室 📚         ║
║  本地访问: http://localhost:8000    ║
╚══════════════════════════════════════╝""")
    web.run_app(app, host='0.0.0.0', port=8000)