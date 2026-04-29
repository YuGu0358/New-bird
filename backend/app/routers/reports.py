"""HTML report endpoints — backtest tearsheet + portfolio overview."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.dependencies import SessionDep, service_error
from app.services import report_builder_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get(
    "/backtest/{run_id}.html",
    response_class=HTMLResponse,
)
async def get_backtest_tearsheet_html(
    run_id: int, session: SessionDep
) -> HTMLResponse:
    """Tearsheet as a print-friendly HTML page (browser → PDF works fine)."""
    try:
        html = await report_builder_service.render_backtest_tearsheet(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return HTMLResponse(content=html)


@router.get(
    "/portfolio/{broker_account_id}.html",
    response_class=HTMLResponse,
)
async def get_portfolio_overview_html(
    broker_account_id: int, session: SessionDep
) -> HTMLResponse:
    """Per-account portfolio overview HTML."""
    try:
        html = await report_builder_service.render_portfolio_overview(
            session, broker_account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return HTMLResponse(content=html)
