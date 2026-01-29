import os
import uuid
import certifi
from datetime import datetime
from collections import deque

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from motor.motor_asyncio import AsyncIOMotorClient
from werkzeug.security import generate_password_hash, check_password_hash

# ─────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

PORT = int(os.environ.get("PORT", 8000))
MONGO_URI = os.environ.get("MONGO_URI")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI not set")

# ─────────────────────────────────────────────
# MongoDB (Motor + TLS)
# ─────────────────────────────────────────────

client = AsyncIOMotorClient(
    MONGO_URI,
    tlsCAFile=certifi.where()
)

db = client.chatdb
users_col = db.users
messages_col = db.messages

# ─────────────────────────────────────────────
# In-memory cache
# ─────────────────────────────────────────────

MAX_CACHE = 100
message_cache = deque(maxlen=MAX_CACHE)

active_connections = {}

# ─────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await client.admin.command("ping")
    await users_col.create_index("username", unique=True)
    await messages_col.create_index("created_at")

    cursor = (
        messages_col
        .find({})
        .sort("created_at", -1)
        .limit(MAX_CACHE)
    )

    msgs = []
    async for msg in cursor:
        msgs.append(msg)

    for msg in reversed(msgs):
        message_cache.append(msg)

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = await users_col.find_one({"username": username.lower()})

    if not user or not check_password_hash(user["password_hash"], password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"}
        )

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user_id": user["user_id"],
            "display_name": user["display_name"],
            "messages": list(message_cache)
        }
    )

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/signup")
async def signup(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...)
):
    try:
        await users_col.insert_one({
            "user_id": str(uuid.uuid4()),
            "username": username.lower(),
            "display_name": display_name,
            "password_hash": generate_password_hash(password)
        })
        return RedirectResponse("/login", status_code=302)
    except:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Username already exists"}
        )

# ─────────────────────────────────────────────
# WebSocket Chat
# ─────────────────────────────────────────────

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    active_connections[user_id] = websocket

    try:
        while True:
            data = await websocket.receive_json()
            content = data["content"].strip()

            msg = {
                "sender_id": user_id,
                "sender_name": data["sender_name"],
                "content": content,
                "created_at": datetime.utcnow().isoformat()
            }

            await messages_col.insert_one(msg)

            if len(message_cache) == MAX_CACHE:
                message_cache.popleft()

            message_cache.append(msg)

            for ws in active_connections.values():
                await ws.send_json(msg)

    except WebSocketDisconnect:
        active_connections.pop(user_id, None)
