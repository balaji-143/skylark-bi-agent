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




app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
