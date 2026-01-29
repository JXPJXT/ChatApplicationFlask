from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
import certifi

load_dotenv()

MONGO_DETAILS = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# Use certifi to provide valid CA certificates
client = AsyncIOMotorClient(MONGO_DETAILS, tlsCAFile=certifi.where())

db = client.chatapp

user_collection = db.get_collection("users")
conversation_collection = db.get_collection("conversations")
message_collection = db.get_collection("messages")
