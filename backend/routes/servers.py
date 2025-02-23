from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import Server
from pydantic import BaseModel

router = APIRouter(prefix="/servers", tags=["servers"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ServerCreate(BaseModel):
    name: str
    url: str
    token: str
    type: str  # "Plex" ou "Jellyfin"

@router.post("/")
def add_server(server: ServerCreate, db: Session = Depends(get_db)):
    db_server = Server(**server.dict())
    db.add(db_server)
    db.commit()
    return {"message": "Serveur ajouté avec succès"}
