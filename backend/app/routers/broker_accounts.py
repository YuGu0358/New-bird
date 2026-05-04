"""CRUD for connected broker accounts (alpaca / ibkr / kraken / ...)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models.broker_accounts import (
    BrokerAccountActiveUpdateRequest,
    BrokerAccountAliasUpdateRequest,
    BrokerAccountCreateRequest,
    BrokerAccountListResponse,
    BrokerAccountTierUpdateRequest,
    BrokerAccountView,
)
from app.services import broker_accounts_service

router = APIRouter(prefix="/api/broker-accounts", tags=["broker-accounts"])


@router.get("", response_model=BrokerAccountListResponse)
async def list_accounts(
    session: SessionDep, only_active: bool = False
) -> BrokerAccountListResponse:
    items = await broker_accounts_service.list_accounts(
        session, only_active=only_active
    )
    return BrokerAccountListResponse(items=items)


@router.get("/{account_pk}", response_model=BrokerAccountView)
async def get_account(
    account_pk: int, session: SessionDep
) -> BrokerAccountView:
    payload = await broker_accounts_service.get_account(session, account_pk)
    if payload is None:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return BrokerAccountView(**payload)


@router.post("", response_model=BrokerAccountView, status_code=201)
async def create_account(
    request: BrokerAccountCreateRequest, session: SessionDep
) -> BrokerAccountView:
    try:
        payload = await broker_accounts_service.create_account(
            session,
            broker=request.broker,
            account_id=request.account_id,
            alias=request.alias,
            tier=request.tier,
        )
    except ValueError as exc:
        # Either invalid input or duplicate (broker, account_id).
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return BrokerAccountView(**payload)


@router.patch("/{account_pk}/alias", response_model=BrokerAccountView)
async def update_alias(
    account_pk: int,
    request: BrokerAccountAliasUpdateRequest,
    session: SessionDep,
) -> BrokerAccountView:
    payload = await broker_accounts_service.update_alias(
        session, account_pk, request.alias
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return BrokerAccountView(**payload)


@router.patch("/{account_pk}/tier", response_model=BrokerAccountView)
async def update_tier(
    account_pk: int,
    request: BrokerAccountTierUpdateRequest,
    session: SessionDep,
) -> BrokerAccountView:
    try:
        payload = await broker_accounts_service.update_tier(
            session, account_pk, request.tier
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return BrokerAccountView(**payload)


@router.patch("/{account_pk}/active", response_model=BrokerAccountView)
async def update_active(
    account_pk: int,
    request: BrokerAccountActiveUpdateRequest,
    session: SessionDep,
) -> BrokerAccountView:
    payload = await broker_accounts_service.set_active(
        session, account_pk, is_active=request.is_active
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return BrokerAccountView(**payload)


@router.delete("/{account_pk}", status_code=204)
async def delete_account(account_pk: int, session: SessionDep) -> None:
    deleted = await broker_accounts_service.delete_account(session, account_pk)
    if not deleted:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return None
