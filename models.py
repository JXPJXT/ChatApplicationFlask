from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid objectid")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")

class UserBase(BaseModel):
    username: str = Field(..., min_length=3)

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class UserInDB(UserBase):
    id: Optional[str] = Field(None, alias="_id")
    hashed_password: str

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}
        schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "jdoe@example.com",
            }
        }

class MessageModel(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    sender_id: str
    text: str
    timestamp: float = Field(default_factory=datetime.now().timestamp)

    class Config:
        allow_population_by_field_name = True

class ConversationModel(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    participants: List[str] = []
    is_group: bool = False
    group_name: Optional[str] = None
    last_message_at: float = Field(default_factory=datetime.now().timestamp)

    class Config:
        allow_population_by_field_name = True
