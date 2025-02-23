from fastapi import FastAPI
from backend.routes import auth, servers
from backend.database import init_db

app = FastAPI(title="VODUM API")

# Charger les routes
app.include_router(auth.router)
app.include_router(servers.router)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/")
def read_root():
    return {"message": "VODUM API is running!"}
