// 全局变量
let socket = null;
let localStream = null;
let peerConnections = {};
let currentUser = null;
let currentRoomId = null;
let isMuted = false;
let isVideoOff = false;
let timerInterval = null;
let timerSeconds = 0;
let sessionCount = 0;
let isTimerRunning = false;

// ============ 首页功能 ============

async function refreshRooms() {
    const container = document.getElementById('roomsList');
    if (!container) return;
    container.innerHTML = '<div class="loading">加载中...</div>';
    try {
        const res = await fetch('/api/rooms');
        const rooms = await res.json();
        if (rooms.length === 0) {
            container.innerHTML = '<p style="text-align:center;color:#718096;">暂无房间，创建一个吧！</p>';
            return;
        }
        container.innerHTML = rooms.map(room => `
            <div class="room-card" onclick="joinRoom('${room.id}')">
                <h3>📚 ${room.name}</h3>
                <div class="meta">
                    <span>🆔 ${room.id}</span>
                    <span>👥 ${room.online}/${room.max_users}</span>
                </div>
                <div style="margin-top:8px;color:#718096;">${room.has_password ? '🔒 有密码' : '🔓 公开'}</div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<p style="color:red;">加载失败</p>';
    }
}

function showCreateModal() {
    document.getElementById('createModal').style.display = 'flex';
}

function hideCreateModal() {
    document.getElementById('createModal').style.display = 'none';
}

async function createRoom(event) {
    event.preventDefault();
    const name = document.getElementById('roomName').value;
    const max = document.getElementById('maxUsers').value;
    const pwd = document.getElementById('roomPassword').value;
    try {
        const res = await fetch('/api/rooms', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({room_name: name, max_users: parseInt(max), password: pwd})
        });
        const data = await res.json();
        if (data.success) {
            alert('房间创建成功！房间号: ' + data.room_id);
            hideCreateModal();
            joinRoom(data.room_id);
        }
    } catch (err) {
        alert('创建失败');
    }
}

function quickJoin() {
    const roomId = document.getElementById('roomIdInput').value.trim();
    if (!roomId) { alert('请输入房间号'); return; }
    joinRoom(roomId);
}

function joinRoom(roomId) {
    const userName = document.getElementById('userNameInput')?.value.trim() || '用户' + Math.random().toString(36).substr(2, 4);
    window.location.href = '/room?room=' + roomId + '&name=' + encodeURIComponent(userName);
}

// ============ 关于弹窗 ============

function showAbout() {
    if (document.getElementById('aboutOverlay')) return;
    var overlay = document.createElement('div');
    overlay.id = 'aboutOverlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:99999;display:flex;justify-content:center;align-items:center;';
    var box = document.createElement('div');
    box.style.cssText = 'background:white;border-radius:16px;padding:30px;text-align:center;max-width:380px;margin:20px;box-shadow:0 10px 40px rgba(0,0,0,0.3);';
    var closeMe = function() { document.body.removeChild(overlay); };
    box.innerHTML = '<div style="font-size:48px;">📚</div>' +
        '<h2 style="color:#333;margin:10px 0;">线上自习室 v1.0</h2>' +
        '<hr style="width:50px;border:1px solid #667eea;margin:10px auto;">' +
        '<p style="color:#555;line-height:2.2;font-size:15px;">👨‍💻 开发者：<b>郑智鹏</b><br>📧 15702419317@163.com<br>💬 QQ：Galler wei<br>𝕏    Twitter：Galler唯</p>' +
        '<p style="color:#aaa;font-size:12px;">© 2025 郑智鹏 版权所有</p>' +
        '<button id="aboutCloseBtn" style="margin-top:12px;padding:8px 30px;background:#667eea;color:white;border:none;border-radius:8px;cursor:pointer;font-size:14px;">关闭</button>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    document.getElementById('aboutCloseBtn').onclick = closeMe;
    overlay.onclick = function(e) { if (e.target === overlay) closeMe(); };
}

// ============ 自习室页面 ============

async function initRoom() {
    const params = new URLSearchParams(window.location.search);
    const roomId = params.get('room');
    const userName = params.get('name') || '用户' + Math.random().toString(36).substr(2, 4);
    if (!roomId) { window.location.href = '/'; return; }
    document.getElementById('roomIdDisplay').textContent = roomId;
    currentRoomId = roomId;
    socket = io(window.location.origin);
    try {
        localStream = await navigator.mediaDevices.getUserMedia({video: true, audio: true});
        addLocalVideo();
    } catch (err) {
        console.error('摄像头错误:', err);
    }
    socket.on('connect', function() {
        socket.emit('join_room', {room_id: roomId, user_name: userName});
    });
    socket.on('room_joined', function(data) {
        currentUser = data.current_user;
        document.getElementById('roomName').textContent = data.room_name;
        document.getElementById('onlineCount').textContent = data.existing_users.length + 1;
        if (data.messages) data.messages.forEach(function(msg) { addMessage(msg); });
        data.existing_users.forEach(function(user) { createPeerConnection(user.id, true); });
    });
    socket.on('user_joined', function(data) {
        createPeerConnection(data.user.id, false);
    });
    socket.on('user_left', function(data) {
        closePeerConnection(data.user_id);
        removeVideoCard(data.user_id);
    });
    socket.on('online_update', function(data) {
        document.getElementById('onlineCount').textContent = data.count;
    });
    socket.on('webrtc_offer', async function(data) {
        var pc = peerConnections[data.from_sid];
        if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
            var answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            socket.emit('webrtc_answer', {target_sid: data.from_sid, sdp: answer});
        }
    });
    socket.on('webrtc_answer', async function(data) {
        var pc = peerConnections[data.from_sid];
        if (pc) await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
    });
    socket.on('webrtc_ice_candidate', async function(data) {
        var pc = peerConnections[data.from_sid];
        if (pc) await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
    });
    socket.on('new_message', function(msg) { addMessage(msg); });
    socket.on('error', function(data) { alert(data.message); });
}

function createPeerConnection(userId, isInitiator) {
    var pc = new RTCPeerConnection({
    iceServers: [
        {urls: 'stun:stun.l.google.com:19302'},
        {urls: 'stun:stun1.l.google.com:19302'},
        {
            urls: 'turn:openrelay.metered.ca:80',
            username: 'openrelayproject',
            credential: 'openrelayproject'
        },
        {
            urls: 'turn:openrelay.metered.ca:443',
            username: 'openrelayproject',
            credential: 'openrelayproject'
        }
    ]
});
    peerConnections[userId] = pc;
    if (localStream) {
        localStream.getTracks().forEach(function(track) { pc.addTrack(track, localStream); });
    }
    pc.onicecandidate = function(event) {
        if (event.candidate) socket.emit('webrtc_ice_candidate', {target_sid: userId, candidate: event.candidate});
    };
    pc.ontrack = function(event) { addRemoteVideo(userId, event.streams[0]); };
    if (isInitiator) {
        pc.createOffer().then(function(offer) { return pc.setLocalDescription(offer); }).then(function() {
            socket.emit('webrtc_offer', {target_sid: userId, sdp: pc.localDescription});
        });
    }
}

function closePeerConnection(userId) {
    if (peerConnections[userId]) { peerConnections[userId].close(); delete peerConnections[userId]; }
}

function addLocalVideo() {
    var grid = document.getElementById('videoGrid');
    if (!grid) return;
    var card = document.createElement('div');
    card.className = 'video-card';
    card.id = 'video-local';
    var video = document.createElement('video');
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.srcObject = localStream;
    var label = document.createElement('div');
    label.className = 'user-label';
    label.textContent = '我';
    card.appendChild(video);
    card.appendChild(label);
    grid.appendChild(card);
}

function addRemoteVideo(userId, stream) {
    removeVideoCard(userId);
    var grid = document.getElementById('videoGrid');
    if (!grid) return;
    var card = document.createElement('div');
    card.className = 'video-card';
    card.id = 'video-' + userId;
    var video = document.createElement('video');
    video.autoplay = true;
    video.playsInline = true;
    video.srcObject = stream;
    var label = document.createElement('div');
    label.className = 'user-label';
    label.textContent = '用户';
    card.appendChild(video);
    card.appendChild(label);
    grid.appendChild(card);
}

function removeVideoCard(userId) {
    var card = document.getElementById('video-' + userId);
    if (card) card.remove();
}

// ============ 控制按钮 ============

function toggleMute() {
    if (localStream) {
        var at = localStream.getAudioTracks()[0];
        if (at) { at.enabled = !at.enabled; isMuted = !at.enabled; }
        document.getElementById('muteBtn').className = 'control-btn' + (isMuted ? ' active' : '');
        document.getElementById('muteIcon').textContent = isMuted ? '🔇' : '🎤';
        if (socket) socket.emit('toggle_mute', {is_muted: isMuted});
    }
}

function toggleVideo() {
    if (localStream) {
        var vt = localStream.getVideoTracks()[0];
        if (vt) { vt.enabled = !vt.enabled; isVideoOff = !vt.enabled; }
        document.getElementById('videoBtn').className = 'control-btn' + (isVideoOff ? ' active' : '');
        document.getElementById('videoIcon').textContent = isVideoOff ? '📷❌' : '📹';
        if (socket) socket.emit('toggle_video', {is_video_off: isVideoOff});
    }
}

async function shareScreen() {
    try {
        var screenStream = await navigator.mediaDevices.getDisplayMedia({video: true});
        var vt = screenStream.getVideoTracks()[0];
        Object.values(peerConnections).forEach(function(pc) {
            var sender = pc.getSenders().find(function(s) { return s.track && s.track.kind === 'video'; });
            if (sender) sender.replaceTrack(vt);
        });
        document.querySelector('#video-local video').srcObject = screenStream;
        vt.onended = function() {
            if (localStream) {
                var ct = localStream.getVideoTracks()[0];
                Object.values(peerConnections).forEach(function(pc) {
                    var sender = pc.getSenders().find(function(s) { return s.track && s.track.kind === 'video'; });
                    if (sender) sender.replaceTrack(ct);
                });
                document.querySelector('#video-local video').srcObject = localStream;
            }
        };
    } catch (err) {}
}

// ============ 聊天 ============

function toggleChat() {
    var sidebar = document.getElementById('sidebar');
    var chat = document.getElementById('chatPanel');
    var timer = document.getElementById('timerPanel');
    if (chat.style.display === 'none' || chat.style.display === '') {
        sidebar.style.display = 'block';
        chat.style.display = 'flex';
        timer.style.display = 'none';
    } else {
        sidebar.style.display = 'none';
        chat.style.display = 'none';
    }
}

function sendChatMessage() {
    var input = document.getElementById('messageInput');
    var text = input.value.trim();
    if (text && socket) { socket.emit('send_message', {text: text}); input.value = ''; }
}

function addMessage(msg) {
    var container = document.getElementById('messagesContainer');
    if (!container) return;
    var div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = '<div class="msg-header"><strong>' + msg.user_name + '</strong><span>' + new Date(msg.timestamp).toLocaleTimeString() + '</span></div><div>' + msg.text + '</div>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ============ 番茄钟 ============

function toggleTimer() {
    var sidebar = document.getElementById('sidebar');
    var chat = document.getElementById('chatPanel');
    var timer = document.getElementById('timerPanel');
    if (timer.style.display === 'none' || timer.style.display === '') {
        sidebar.style.display = 'block';
        timer.style.display = 'flex';
        chat.style.display = 'none';
        resetTimerDisplay();
    } else {
        sidebar.style.display = 'none';
        timer.style.display = 'none';
    }
}

function startTimer() {
    if (!isTimerRunning) {
        var workTime = parseInt(document.getElementById('workTime').value);
        timerSeconds = workTime * 60;
        isTimerRunning = true;
        document.getElementById('timerStartBtn').style.display = 'none';
        document.getElementById('timerPauseBtn').style.display = 'block';
        document.getElementById('timerStatus').textContent = '工作中...';
        if (socket) socket.emit('timer_start', {work_time: workTime, break_time: parseInt(document.getElementById('breakTime').value)});
        timerInterval = setInterval(function() {
            timerSeconds--;
            updateTimerDisplay();
            if (timerSeconds <= 0) {
                clearInterval(timerInterval);
                isTimerRunning = false;
                sessionCount++;
                document.getElementById('sessionCount').textContent = sessionCount;
                document.getElementById('timerStatus').textContent = '完成！';
                if (socket) socket.emit('timer_complete', {});
                var breakTime = parseInt(document.getElementById('breakTime').value);
                timerSeconds = breakTime * 60;
                document.getElementById('timerStatus').textContent = '休息中...';
                updateTimerDisplay();
                timerInterval = setInterval(function() {
                    timerSeconds--;
                    updateTimerDisplay();
                    if (timerSeconds <= 0) { clearInterval(timerInterval); resetTimerDisplay(); }
                }, 1000);
            }
        }, 1000);
    }
}

function pauseTimer() {
    if (isTimerRunning) {
        clearInterval(timerInterval);
        isTimerRunning = false;
        document.getElementById('timerStartBtn').style.display = 'block';
        document.getElementById('timerPauseBtn').style.display = 'none';
        document.getElementById('timerStatus').textContent = '已暂停';
    }
}

function resetTimer() {
    clearInterval(timerInterval);
    isTimerRunning = false;
    resetTimerDisplay();
}

function resetTimerDisplay() {
    var workTime = parseInt(document.getElementById('workTime').value);
    timerSeconds = workTime * 60;
    updateTimerDisplay();
    document.getElementById('timerStartBtn').style.display = 'block';
    document.getElementById('timerPauseBtn').style.display = 'none';
    document.getElementById('timerStatus').textContent = '准备开始';
}

function updateTimerDisplay() {
    var mins = Math.floor(Math.abs(timerSeconds) / 60);
    var secs = Math.abs(timerSeconds) % 60;
    document.getElementById('timerDisplay').textContent = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}

function leaveCurrentRoom() {
    if (confirm('确定要离开房间吗？')) {
        if (localStream) localStream.getTracks().forEach(function(t) { t.stop(); });
        Object.values(peerConnections).forEach(function(p) { p.close(); });
        if (socket) { socket.emit('leave_room'); socket.disconnect(); }
        window.location.href = '/';
    }
}

// 启动
if (window.location.pathname.includes('room')) {
    initRoom();
} else {
    refreshRooms();
}