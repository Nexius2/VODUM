from sqlalchemy import Column, Integer, String
from backend.database import Base

class Server(Base):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    token = Column(String, nullable=False)
    type = Column(String, nullable=False)  # Plex ou Jellyfin
