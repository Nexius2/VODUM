from fastapi import FastAPI, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import List
import databases
import sqlalchemy

DATABASE_URL = "postgresql://vodum_user:password@db/vodum_db"
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

users = sqlalchemy.Table(
    "users", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password", sqlalchemy.String),
    sqlalchemy.Column("is_admin", sqlalchemy.Boolean, default=False)
)

subscriptions = sqlalchemy.Table(
    "subscriptions", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("start_date", sqlalchemy.DateTime),
    sqlalchemy.Column("end_date", sqlalchemy.DateTime),
    sqlalchemy.Column("active", sqlalchemy.Boolean, default=True)
)

servers = sqlalchemy.Table(
    "servers", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("type", sqlalchemy.String),
    sqlalchemy.Column("url", sqlalchemy.String),
    sqlalchemy.Column("token", sqlalchemy.String)
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@app.post("/users/")
async def create_user(user: UserCreate):
    query = users.insert().values(username=user.username, email=user.email, password=user.password)
    await database.execute(query)
    return {"message": "User created successfully"}

@app.get("/users/", response_model=List[UserCreate])
async def get_users():
    query = users.select()
    return await database.fetch_all(query)

@app.get("/servers/")
async def get_servers():
    query = servers.select()
    return await database.fetch_all(query)
