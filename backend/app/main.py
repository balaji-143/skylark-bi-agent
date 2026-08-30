from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os

from . import agent

app = FastAPI(title="Skylark Drones BI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    history: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.history or req.history[-1].role != "user":
        raise HTTPException(400, "history must end with a user message")
    try:
        reply = agent.answer_question([m.model_dump() for m in req.history])
    except Exception as e:
        raise HTTPException(500, f"Agent error: {e}")
    return ChatResponse(reply=reply)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug-env")
def debug_env():
    key = os.environ.get("GEMINI_API_KEY", "")
    return {
        "MONDAY_API_TOKEN_set": bool(os.environ.get("MONDAY_API_TOKEN")),
        "GEMINI_API_KEY_length": len(key),
        "GEMINI_API_KEY_has_leading_or_trailing_space": key != key.strip(),
        "GEMINI_API_KEY_first_3_chars": key[:3],
        "GEMINI_API_KEY_last_3_chars": key[-3:],
        "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "NOT SET"),
        "DEALS_BOARD_ID_set": bool(os.environ.get("DEALS_BOARD_ID")),
        "WORK_ORDERS_BOARD_ID_set": bool(os.environ.get("WORK_ORDERS_BOARD_ID")),
    }


app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
