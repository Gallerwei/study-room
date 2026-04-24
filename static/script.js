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
                <div style="margin-top:8px;color:#718096;">
                    ${room.has_password ? '🔒 有密码' : '🔓 公开'}
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<p style="color:red;">加载失败</p>';
        console.error(err);
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
            body: JSON.stringify({
                room_name: name,
                max_users: parseInt(max),
                password: pwd
            })
        });

        const data = await res.json();

        if (data.success) {
            alert(`房间创建成功！房间号: ${data.room_id}`);
            hideCreateModal();
            joinRoom(data.room_id);
        } else {
            alert('创建失败: ' + (data.error || '未知错误'));
        }
    } catch (err) {
        alert('创建失败');
        console.error(err);
    }
}

function quickJoin() {
    const roomId = document.getElementById('roomIdInput').value.trim();
    if (!roomId) {
        alert('请输入房间号');
        return;
    }
    joinRoom(roomId);
}

function joinRoom(roomId) {
    const userName = document.getElementById('userNameInput')?.value.trim() ||
                     '用户' + Math.random().toString(36).substr(2, 4);
    window.location.href = `/room?room=${roomId}&name=${encodeURIComponent(userName)}`;
}

// ============ 自习室页面 ============

async function initRoom() {
    const params = new URLSearchParams(window.location.search);
    const roomId = params.get('room');
    const userName = params.get('name') || '用户' + Math.random().toString(36).substr(2, 4);

    if (!roomId) {
        window.location.href = '/';
        return;
    }

    document.getElementById('roomIdDisplay').textContent = roomId;
    currentRoomId = roomId;

    // 连接 Socket.IO
    socket = io(window.location.origin);

    // 获取本地媒体
    try {
        localStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true
        });
        addLocalVideo();
    } catch (err) {
        console.error('无法访问摄像头:', err);
        alert('需要摄像头和麦克风权限');
    }

    // Socket 事件
    socket.on('connect', () => {
        console.log('已连接');
        socket.emit('join_room', {
            room_id: roomId,
            user_name: userName
        });
    });

    socket.on('room_joined', (data) => {
        console.log('加入成功:', data);
        currentUser = data.current_user;
        document.getElementById('roomName').textContent = data.room_name;
        document.getElementById('onlineCount').textContent = data.existing_users.length + 1;

        // 显示消息历史
        if (data.messages) {
            data.messages.forEach(msg => addMessage(msg));
        }

        // 为现有用户创建连接
        data.existing_users.forEach(user => {
            createPeerConnection(user.id, true);
        });
    });

    socket.on('user_joined', (data) => {
        console.log('新用户:', data.user.name);
        createPeerConnection(data.user.id, false);
        showNotification(`${data.user.name} 加入了房间`);
    });

    socket.on('user_left', (data) => {
        console.log('用户离开:', data.user_name);
        closePeerConnection(data.user_id);
        removeVideoCard(data.user_id);
        showNotification(`${data.user_name} 离开了房间`);
    });

    socket.on('online_update', (data) => {
        document.getElementById('onlineCount').textContent = data.count;
    });

    socket.on('webrtc_offer', async (data) => {
        const pc = peerConnections[data.from_sid];
        if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            socket.emit('webrtc_answer', {
                target_sid: data.from_sid,
                sdp: answer
            });
        }
    });

    socket.on('webrtc_answer', async (data) => {
        const pc = peerConnections[data.from_sid];
        if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(data.sdp));
        }
    });

    socket.on('webrtc_ice_candidate', async (data) => {
        const pc = peerConnections[data.from_sid];
        if (pc) {
            await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
        }
    });

    socket.on('new_message', (msg) => {
        addMessage(msg);
    });

    socket.on('user_updated', (user) => {
        updateUserStatus(user);
    });

    socket.on('error', (data) => {
        alert(data.message);
    });

    socket.on('timer_started', (data) => {
        showNotification(`⏱ ${data.user_name} 开始了番茄钟`);
    });

    socket.on('timer_completed', (data) => {
        showNotification(data.message);
    });

    // 页面刷新
    refreshRooms();
}

function createPeerConnection(userId, isInitiator) {
    const configuration = {
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' }
        ]
    };

    const pc = new RTCPeerConnection(configuration);
    peerConnections[userId] = pc;

    // 添加本地流
    if (localStream) {
        localStream.getTracks().forEach(track => {
            pc.addTrack(track, localStream);
        });
    }

    // ICE 候选
    pc.onicecandidate = (event) => {
        if (event.candidate) {
            socket.emit('webrtc_ice_candidate', {
                target_sid: userId,
                candidate: event.candidate
            });
        }
    };

    // 接收远程流
    pc.ontrack = (event) => {
        addRemoteVideo(userId, event.streams[0]);
    };

    // 创建 Offer（发起者）
    if (isInitiator) {
        pc.createOffer()
            .then(offer => pc.setLocalDescription(offer))
            .then(() => {
                socket.emit('webrtc_offer', {
                    target_sid: userId,
                    sdp: pc.localDescription
                });
            })
            .catch(err => console.error('创建Offer失败:', err));
    }
}

function closePeerConnection(userId) {
    const pc = peerConnections[userId];
    if (pc) {
        pc.close();
        delete peerConnections[userId];
    }
}

function addLocalVideo() {
    const grid = document.getElementById('videoGrid');
    const card = document.createElement('div');
    card.className = 'video-card';
    card.id = 'video-local';

    const video = document.createElement('video');
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    video.srcObject = localStream;

    const label = document.createElement('div');
    label.className = 'user-label';
    label.textContent = '我';

    card.appendChild(video);
    card.appendChild(label);
    grid.appendChild(card);
}

function addRemoteVideo(userId, stream) {
    removeVideoCard(userId);

    const grid = document.getElementById('videoGrid');
    const card = document.createElement('div');
    card.className = 'video-card';
    card.id = 'video-' + userId;

    const video = document.createElement('video');
    video.autoplay = true;
    video.playsInline = true;
    video.srcObject = stream;

    const label = document.createElement('div');
    label.className = 'user-label';
    label.textContent = '用户';

    card.appendChild(video);
    card.appendChild(label);
    grid.appendChild(card);
}

function removeVideoCard(userId) {
    const card = document.getElementById('video-' + userId);
    if (card) card.remove();
}

function updateUserStatus(user) {
    const card = document.getElementById('video-' + user.id);
    if (card) {
        const label = card.querySelector('.user-label');
        if (label) {
            label.textContent = user.name + (user.is_muted ? ' 🔇' : '') +
                              (user.is_video_off ? ' 📷❌' : '');
        }
    }
}

// ============ 控制功能 ============

function toggleMute() {
    if (localStream) {
        const audioTrack = localStream.getAudioTracks()[0];
        if (audioTrack) {
            audioTrack.enabled = !audioTrack.enabled;
            isMuted = !audioTrack.enabled;

            document.getElementById('muteBtn').className =
                'control-btn' + (isMuted ? ' active' : '');
            document.getElementById('muteIcon').textContent = isMuted ? '🔇' : '🎤';

            if (socket) {
                socket.emit('toggle_mute', { is_muted: isMuted });
            }
        }
    }
}

function toggleVideo() {
    if (localStream) {
        const videoTrack = localStream.getVideoTracks()[0];
        if (videoTrack) {
            videoTrack.enabled = !videoTrack.enabled;
            isVideoOff = !videoTrack.enabled;

            document.getElementById('videoBtn').className =
                'control-btn' + (isVideoOff ? ' active' : '');
            document.getElementById('videoIcon').textContent = isVideoOff ? '📷❌' : '📹';

            if (socket) {
                socket.emit('toggle_video', { is_video_off: isVideoOff });
            }
        }
    }
}

async function shareScreen() {
    try {
        const screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: true
        });

        // 替换所有连接的视频轨道
        const videoTrack = screenStream.getVideoTracks()[0];
        Object.values(peerConnections).forEach(pc => {
            const sender = pc.getSenders().find(s => s.track?.kind === 'video');
            if (sender) {
                sender.replaceTrack(videoTrack);
            }
        });

        // 更新本地显示
        const localVideo = document.querySelector('#video-local video');
        if (localVideo) {
            localVideo.srcObject = screenStream;
        }

        // 停止时恢复
        videoTrack.onended = () => {
            if (localStream) {
                const camTrack = localStream.getVideoTracks()[0];
                Object.values(peerConnections).forEach(pc => {
                    const sender = pc.getSenders().find(s => s.track?.kind === 'video');
                    if (sender) {
                        sender.replaceTrack(camTrack);
                    }
                });
                if (localVideo) {
                    localVideo.srcObject = localStream;
                }
            }
        };
    } catch (err) {
        console.error('屏幕共享失败:', err);
    }
}

// ============ 聊天功能 ============

function toggleChat() {
    const sidebar = document.getElementById('sidebar');
    const chatPanel = document.getElementById('chatPanel');
    const timerPanel = document.getElementById('timerPanel');

    if (chatPanel.style.display === 'none' || chatPanel.style.display === '') {
        sidebar.style.display = 'block';
        chatPanel.style.display = 'flex';
        timerPanel.style.display = 'none';
    } else {
        sidebar.style.display = 'none';
        chatPanel.style.display = 'none';
    }
}

function sendChatMessage() {
    const input = document.getElementById('messageInput');
    const text = input.value.trim();

    if (text && socket) {
        socket.emit('send_message', { text });
        input.value = '';
    }
}

function addMessage(msg) {
    const container = document.getElementById('messagesContainer');
    if (!container) return;

    const div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = `
        <div class="msg-header">
            <strong>${msg.user_name}</strong>
            <span>${new Date(msg.timestamp).toLocaleTimeString()}</span>
        </div>
        <div>${msg.text}</div>
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ============ 番茄钟 ============

function toggleTimer() {
    const sidebar = document.getElementById('sidebar');
    const chatPanel = document.getElementById('chatPanel');
    const timerPanel = document.getElementById('timerPanel');

    if (timerPanel.style.display === 'none' || timerPanel.style.display === '') {
        sidebar.style.display = 'block';
        timerPanel.style.display = 'flex';
        chatPanel.style.display = 'none';
        resetTimerDisplay();
    } else {
        sidebar.style.display = 'none';
        timerPanel.style.display = 'none';
    }
}

function startTimer() {
    if (!isTimerRunning) {
        const workTime = parseInt(document.getElementById('workTime').value);
        timerSeconds = workTime * 60;
        isTimerRunning = true;

        document.getElementById('timerStartBtn').style.display = 'none';
        document.getElementById('timerPauseBtn').style.display = 'block';
        document.getElementById('timerStatus').textContent = '工作中...';

        if (socket) {
            socket.emit('timer_start', {
                work_time: workTime,
                break_time: parseInt(document.getElementById('breakTime').value)
            });
        }

        timerInterval = setInterval(() => {
            timerSeconds--;
            updateTimerDisplay();

            if (timerSeconds <= 0) {
                clearInterval(timerInterval);
                isTimerRunning = false;
                sessionCount++;
                document.getElementById('sessionCount').textContent = sessionCount;
                document.getElementById('timerStatus').textContent = '完成！';

                if (socket) {
                    socket.emit('timer_complete', {});
                }

                // 自动开始休息
                const breakTime = parseInt(document.getElementById('breakTime').value);
                timerSeconds = breakTime * 60;
                document.getElementById('timerStatus').textContent = '休息中...';
                updateTimerDisplay();

                timerInterval = setInterval(() => {
                    timerSeconds--;
                    updateTimerDisplay();

                    if (timerSeconds <= 0) {
                        clearInterval(timerInterval);
                        resetTimerDisplay();
                    }
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
    const workTime = parseInt(document.getElementById('workTime').value);
    timerSeconds = workTime * 60;
    updateTimerDisplay();
    document.getElementById('timerStartBtn').style.display = 'block';
    document.getElementById('timerPauseBtn').style.display = 'none';
    document.getElementById('timerStatus').textContent = '准备开始';
}

function updateTimerDisplay() {
    const mins = Math.floor(Math.abs(timerSeconds) / 60);
    const secs = Math.abs(timerSeconds) % 60;
    document.getElementById('timerDisplay').textContent =
        `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function showNotification(message) {
    // 简单通知
    const div = document.createElement('div');
    div.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: #48bb78;
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;
    div.textContent = message;
    document.body.appendChild(div);

    setTimeout(() => {
        div.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => div.remove(), 300);
    }, 3000);
}

function leaveCurrentRoom() {
    if (confirm('确定要离开房间吗？')) {
        if (localStream) {
            localStream.getTracks().forEach(track => track.stop());
        }
        Object.values(peerConnections).forEach(pc => pc.close());
        if (socket) {
            socket.emit('leave_room');
            socket.disconnect();
        }
        window.location.href = '/';
    }
}

// 页面加载时初始化
if (window.location.pathname.includes('room')) {
    initRoom();
} else {
    refreshRooms();
}