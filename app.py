from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict
import json
import asyncio
from bson import ObjectId

from database import user_collection, conversation_collection, message_collection, client
from models import UserCreate, UserInDB, MessageModel, ConversationModel
from auth import get_password_hash, verify_password, create_access_token

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https://.*\.vercel\.app|http://localhost:.*|https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Chat Application Backend is Running"}

@app.on_event("startup")
async def startup_db_client():
    try:
        await client.admin.command('ping')
        print("✅ MONGO CONNECTION SUCCESSFUL")
    except Exception as e:
        print(f"❌ MONGO CONNECTION FAILED: {e}")

# --- WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        # Map user_id to list of active websockets (multiple tabs possible)
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(f"WS: Client {user_id} connected. Active clients: {list(self.active_connections.keys())}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        print(f"WS: Client {user_id} disconnected.")

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            print(f"WS: Sending message to {user_id}")
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass
        else:
            print(f"WS: User {user_id} not connected. Message dropped.")

manager = ConnectionManager()

# --- Auth Routes ---

@app.post("/auth/register", response_model=UserInDB)
async def register(user: UserCreate):
    existing_user = await user_collection.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user.password)
    user_dict = user.dict()
    user_dict["hashed_password"] = hashed_password
    del user_dict["password"]
    
    new_user = await user_collection.insert_one(user_dict)
    created_user = await user_collection.find_one({"_id": new_user.inserted_id})
    # Convert ObjectId to str to satisfy Pydantic
    created_user["_id"] = str(created_user["_id"])
    return UserInDB(**created_user)

@app.post("/auth/login")
async def login(user: UserCreate):
    db_user = await user_collection.find_one({"username": user.username})
    if not db_user or not verify_password(user.password, db_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": db_user["username"], "id": str(db_user["_id"])})
    return {"access_token": access_token, "token_type": "bearer", "user_id": str(db_user["_id"]), "username": db_user["username"]}

@app.get("/users")
async def get_users():
    users = []
    cursor = user_collection.find({})
    async for document in cursor:
        users.append({"id": str(document["_id"]), "username": document["username"]})
    return users

# --- Chat Routes ---

@app.post("/chat/start")
async def start_chat(conversation: ConversationModel):
    # Check if private chat exists
    if not conversation.is_group and len(conversation.participants) == 2:
        # Try to find existing
        p = conversation.participants
        existing = await conversation_collection.find_one({
            "is_group": False,
            "participants": {"$all": p, "$size": 2}
        })
        if existing:
            return {"id": str(existing["_id"]), "is_group": False}

    result = await conversation_collection.insert_one(conversation.dict(by_alias=True, exclude={"id"}))
    chat_id = str(result.inserted_id)
    
    # Broadcast 'new_chat' event to all participants
    event = {
        "type": "new_chat",
        "chat_id": chat_id
    }
    for p in conversation.participants:
        await manager.send_personal_message(event, p)
        
    return {"id": chat_id, "is_group": conversation.is_group}

@app.delete("/chat/{conversation_id}")
async def delete_conversation(conversation_id: str):
    # Hard delete for v2.0 simplicity - in prod, maybe just 'leave' or archive
    try:
        await conversation_collection.delete_one({"_id": ObjectId(conversation_id)})
        await message_collection.delete_many({"conversation_id": conversation_id})
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/recent/{user_id}")
async def get_recent_chats(user_id: str):
    # Find conversations where user_id is in participants
    # Sort by last_message_at desc
    cursor = conversation_collection.find({"participants": user_id}).sort("last_message_at", -1)
    chats = []
    async for conv in cursor:
        chat_data = {
            "id": str(conv["_id"]),
            "is_group": conv["is_group"],
            "group_name": conv.get("group_name"),
            "participants": conv["participants"],
            "last_message_at": conv.get("last_message_at")
        }
        chats.append(chat_data)
    return chats

@app.get("/chat/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    # In a real app, pagination is key. Here we fetch all.
    cursor = message_collection.find({"conversation_id": conversation_id}).sort("timestamp", 1) # Oldest first
    messages = []
    async for msg in cursor:
        messages.append({
            "id": str(msg["_id"]),
            "sender_id": msg["sender_id"],
            "text": msg["text"],
            "timestamp": msg["timestamp"]
        })
    return messages

# --- WebSocket ---

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            # Expecting: { "type": "message", "conversation_id": "...", "text": "...", "sender_id": "..." }
            
            if data.get("type") == "message":
                conversation_id = data["conversation_id"]
                text = data["text"]
                sender_id = data["sender_id"] # Should verify against token in real app

                # Save to DB
                new_msg = {
                    "conversation_id": conversation_id,
                    "sender_id": sender_id,
                    "text": text,
                    "timestamp": asyncio.get_event_loop().time() # Or datetime.now().timestamp()
                }
                res = await message_collection.insert_one(new_msg)
                
                # Update conversation last_message_at
                await conversation_collection.update_one(
                    {"_id": ObjectId(conversation_id)},
                    {"$set": {"last_message_at": new_msg["timestamp"]}}
                )

                # Broadcast to all participants
                conv = await conversation_collection.find_one({"_id": ObjectId(conversation_id)})
                if conv:
                    out_msg = {
                        "type": "new_message",
                        "conversation_id": conversation_id,
                        "message": {
                            "id": str(res.inserted_id),
                            "sender_id": sender_id,
                            "text": text,
                            "timestamp": new_msg["timestamp"]
                        }
                    }
                    for p in conv["participants"]:
                        await manager.send_personal_message(out_msg, p)

    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
