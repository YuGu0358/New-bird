from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import service_error
from app.models import BotStatus, ControlResponse
from app.services import bot_controller

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/status", response_model=BotStatus)
async def get_bot_status() -> BotStatus:
    return BotStatus(**await bot_controller.get_status())


@router.post("/start", response_model=ControlResponse)
async def start_bot() -> ControlResponse:
    status = await bot_controller.start_bot()
    message = "机器人已启动。" if status["is_running"] else "机器人启动失败。"
    return ControlResponse(success=status["is_running"], message=message)


@router.post("/stop", response_model=ControlResponse)
async def stop_bot() -> ControlResponse:
    status = await bot_controller.stop_bot()
    message = "机器人已停止。" if not status["is_running"] else "机器人仍在运行。"
    return ControlResponse(success=not status["is_running"], message=message)
