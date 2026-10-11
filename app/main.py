"""Entrypoint (solution.md §1): GET /health, POST /tasks, GET /tasks/{id}, Bearer auth on the task routes."""
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app import runner
from synth.web import router as evals_router

REQUIRED_ENV = ("TEAM_TOKEN", "OPENROUTER_API_KEY", "MODEL_FAST", "MODEL_VLM", "MODEL_PLANNER")


@asynccontextmanager
async def lifespan(_):
    if missing := [k for k in REQUIRED_ENV if not os.environ.get(k)]:
        raise RuntimeError(f"refusing to start, unset: {', '.join(missing)} (see .env.example)")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(evals_router)


def bearer(authorization: str = Header("")) -> None:
    if not secrets.compare_digest(authorization.encode(), f"Bearer {os.environ['TEAM_TOKEN']}".encode()):
        raise HTTPException(401, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"})


class Desktop(BaseModel):
    url: str
    password: str


class TaskIn(BaseModel):
    task: str
    desktop: Desktop


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tasks", dependencies=[Depends(bearer)])
async def create_task(body: TaskIn):
    return {"task_id": runner.start(body.task, body.desktop.url, body.desktop.password)}


@app.get("/tasks/{task_id}", dependencies=[Depends(bearer)])
def get_task(task_id: str):
    if task_id not in runner.tasks:
        raise HTTPException(404, "unknown task_id")
    return runner.tasks[task_id]
