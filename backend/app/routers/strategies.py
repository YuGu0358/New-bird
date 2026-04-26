from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.dependencies import SessionDep, service_error
from app.models import (
    QuantBrainFactorAnalysisRequest,
    RegisteredStrategiesResponse,
    RegisteredStrategyEntry,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyLibraryResponse,
    StrategyPreviewRequest,
    StrategyPreviewResponse,
    StrategySaveRequest,
)
from app.services import (
    quantbrain_factor_service,
    strategy_document_service,
    strategy_profiles_service,
)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=StrategyLibraryResponse)
async def get_strategy_library(session: SessionDep) -> StrategyLibraryResponse:
    payload = await strategy_profiles_service.list_strategies(session)
    return StrategyLibraryResponse(**payload)


@router.post("/analyze", response_model=StrategyAnalysisDraft)
async def analyze_strategy(request: StrategyAnalysisRequest) -> StrategyAnalysisDraft:
    try:
        payload = await strategy_profiles_service.analyze_strategy(request.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@router.post("/analyze-upload", response_model=StrategyAnalysisDraft)
async def analyze_strategy_with_files(
    description: str = Form(""),
    files: list[UploadFile] | None = File(None),
) -> StrategyAnalysisDraft:
    try:
        payloads: list[tuple[str, bytes]] = []
        for file in files or []:
            payloads.append((file.filename or "strategy-note.txt", await file.read()))
        documents = strategy_document_service.extract_strategy_documents(payloads)
        payload = await strategy_profiles_service.analyze_strategy(description, documents)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@router.post("/analyze-factor-code", response_model=StrategyAnalysisDraft)
async def analyze_quantbrain_factor_code(
    request: QuantBrainFactorAnalysisRequest,
) -> StrategyAnalysisDraft:
    try:
        payload = await strategy_profiles_service.analyze_factor_code_strategy(
            request.code,
            description=request.description,
            source_name=request.source_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@router.post("/analyze-factor-upload", response_model=StrategyAnalysisDraft)
async def analyze_quantbrain_factor_upload(
    description: str = Form(""),
    code: str = Form(""),
    files: list[UploadFile] | None = File(None),
) -> StrategyAnalysisDraft:
    try:
        payloads: list[tuple[str, bytes]] = []
        for file in files or []:
            payloads.append((file.filename or "quantbrain-factor.py", await file.read()))
        documents = quantbrain_factor_service.extract_factor_code_files(payloads)
        code_sections = []
        if str(code or "").strip():
            code_sections.append(f"# Source: pasted-quantbrain-factor.py\n{code.strip()}")
        code_sections.extend(f"# Source: {item['name']}\n{item['code']}" for item in documents)
        combined_code = "\n\n".join(code_sections)
        source_names = ["pasted-quantbrain-factor.py"] if str(code or "").strip() else []
        source_names.extend(item["name"] for item in documents)
        source_name = ", ".join(source_names)
        payload = await strategy_profiles_service.analyze_factor_code_strategy(
            combined_code,
            description=description,
            source_name=source_name or "uploaded-factor.py",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@router.post("", response_model=StrategyLibraryResponse)
async def save_strategy(
    request: StrategySaveRequest,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.save_strategy(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@router.put("/{strategy_id}", response_model=StrategyLibraryResponse)
async def update_strategy(
    strategy_id: int,
    request: StrategySaveRequest,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.update_strategy(session, strategy_id, request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "没有找到" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@router.post("/preview", response_model=StrategyPreviewResponse)
async def preview_strategy(request: StrategyPreviewRequest) -> StrategyPreviewResponse:
    try:
        payload = await strategy_profiles_service.preview_strategy(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyPreviewResponse(**payload)


@router.post("/{strategy_id}/activate", response_model=StrategyLibraryResponse)
async def activate_strategy(
    strategy_id: int,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.activate_strategy(session, strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@router.delete("/{strategy_id}", response_model=StrategyLibraryResponse)
async def delete_strategy(
    strategy_id: int,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.delete_strategy(session, strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@router.get("/registered", response_model=RegisteredStrategiesResponse)
async def list_registered_strategies() -> RegisteredStrategiesResponse:
    """Return every strategy registered in the framework registry.

    Frontend uses this to render parameter schemas in the strategy editor.
    """
    # Import here so registration decorators run at first request rather than
    # at app boot. (At app boot the routers import early; the strategies
    # package may not be loaded yet, which would yield an empty list.)
    import strategies  # noqa: F401

    from core.strategy.registry import default_registry

    items: list[RegisteredStrategyEntry] = []
    for name, cls in default_registry.items():
        items.append(
            RegisteredStrategyEntry(
                name=name,
                description=cls.description,
                parameters_schema=cls.parameters_schema().model_json_schema(),
            )
        )
    return RegisteredStrategiesResponse(items=items)
