# app/main.py

# Entry file: app/main.py
# Server: python -m uvicorn app.main:app --reload

print("=== MAIN.PY IS LOADING ===")

from fastapi import FastAPI
from core import encryption

##### TO RUN: ######
# cd ~/PycharmProjects/iftr
# source venv/bin/activate
# uvicorn main:app --reload --port 8000

app = FastAPI()  # <-- This is YOUR backend "application"

@app.get("/")  # Root endpoint
def read_root():
    return {"message": "Hello from FastAPI!"}

# Your first custom endpoint
@app.get("/")
async def home():
    return {"message": "Welcome to MY App!", "status": "running"}

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id, "name": f"User {user_id}"}

@app.post("/items/")
async def create_item(name: str, price: float):
    return {"item": name, "price": price, "created": True}

print("Encryption test passed:", encryption.test_aes_encryption())