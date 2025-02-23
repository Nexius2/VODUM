from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/login")
def login(user: LoginRequest):
    if user.email == "admin@vodum.com" and user.password == "admin":
        return {"message": "Connexion réussie", "token": "fake-jwt-token"}
    raise HTTPException(status_code=401, detail="Identifiants invalides")
