"""
API статистики посетителей.
"""

from typing import Optional
from fastapi import APIRouter, Request, Query

from backend.state import AppState

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _app(request: Request) -> AppState:
    return request.app.state.app


@router.get("/summary")
async def get_summary(request: Request):
    """Сводка за сегодня."""
    return _app(request).db.get_today_summary()


@router.get("/daily")
async def get_daily(request: Request, days: int = Query(default=30, ge=1, le=365)):
    """Ежедневная статистика за последние N дней."""
    return _app(request).db.get_daily_stats(days)


@router.get("/hourly")
async def get_hourly(request: Request,
                     date: Optional[str] = Query(default=None,
                                                 description="YYYY-MM-DD, по умолчанию сегодня")):
    """Почасовая статистика за конкретную дату."""
    return _app(request).db.get_hourly_stats(date)


@router.get("/monthly")
async def get_monthly(request: Request, months: int = Query(default=12, ge=1, le=60)):
    """Помесячная статистика за последние N месяцев."""
    return _app(request).db.get_monthly_stats(months)
