from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from collections import deque
from datetime import datetime
from pymongo import MongoClient
import uuid
import os

# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────

app = Flask(__name__)
socketio = SocketIO(app, async_mode="eventlet")

PORT = int(os.environ.get("PORT", 5000))
MONGO_URI = os.environ["MONGO_URI"]

# ─────────────────────────────────────────────
# MongoDB setup
# ─────────────────────────────────────────────

client = MongoClient(MONGO_URI)
db = client.chatdb

users_col = db.users
messages_col = db.messages

users_col.create_index("username", unique=True)
messages_col.create_index("created_at")

# ─────────────────────────────────────────────
# In-memory hot cache (O(1))
# ─────────────────────────────────────────────

MAX_CACHE = 100
message_cache = deque(maxlen=MAX_CACHE)
message_index = {}

active_users = {}   # sid → user info

# ─────────────────────────────────────────────
# Load recent messages at startup
# ─────────────────────────────────────────────

def load_recent_messages():
    cursor = (
        messages_col
        .find({})
        .sort("created_at", -1)
        .limit(MAX_CACHE)
    )

    for msg in reversed(list(cursor)):
        msg["_id"] = str(msg["_id"])
        message_cache.append(msg)
        message_index[msg["_id"]] = msg

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        try:
            users_col.insert_one({
                "user_id": str(uuid.uuid4()),
                "username": request.form['username'].lower(),
                "password_hash": generate_password_hash(request.form['password']),
                "display_name": request.form['display_name']
            })
            return redirect(url_for('login'))
        except:
            return render_template("signup.html", error="Username exists")

    return render_template("signup.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = users_col.find_one({
            "username": request.form['username'].lower()
        })

        if user and check_password_hash(user["password_hash"], request.form['password']):
            return render_template(
                "chat.html",
                user_id=user["user_id"],
                display_name=user["display_name"],
                messages=list(message_cache)
            )

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# ─────────────────────────────────────────────
# Socket.IO
# ─────────────────────────────────────────────

@socketio.on("register_user")
def register_user(data):
    active_users[request.sid] = {
        "user_id": data["user_id"],
        "display_name": data["display_name"]
    }

@socketio.on("disconnect")
def disconnect():
    active_users.pop(request.sid, None)

@socketio.on("send_message")
def send_message(data):
    user = active_users.get(request.sid)
    if not user:
        return

    msg_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    msg = {
        "_id": msg_id,
        "sender_id": user["user_id"],
        "sender_name": user["display_name"],
        "content": data["content"].strip(),
        "created_at": now
    }

    # Persist
    messages_col.insert_one(msg)

    # Cache
    if len(message_cache) == message_cache.maxlen:
        message_index.pop(message_cache[0]["_id"], None)

    message_cache.append(msg)
    message_index[msg_id] = msg

    emit("new_message", msg, broadcast=True)

# ─────────────────────────────────────────────
# Boot
# ─────────────────────────────────────────────

if __name__ == "__main__":
    load_recent_messages()
    socketio.run(app, host="0.0.0.0", port=PORT)
