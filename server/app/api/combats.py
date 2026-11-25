"""Combat HTTP routes (docs/protocol.md). Live play goes over the WebSocket."""

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import current_user
from app.auth.tokens import Principal
from app.protocol.combats import CombatCreated, CombatSummaryView
from app.services.combat_router import CombatRouter

router = APIRouter(prefix="/combats")


def get_router(request: Request) -> CombatRouter:
    return request.app.state.combat_router


@router.post("/demo")
async def create_demo(
    request: Request, principal: Principal = Depends(current_user)
) -> CombatCreated:
    combat_id = await get_router(request).create_demo(principal.user_id)
    return CombatCreated(combat_id=combat_id)


@router.get("")
async def list_combats(
    request: Request, principal: Principal = Depends(current_user)
) -> list[CombatSummaryView]:
    summaries = await request.app.state.combat_store.list_for_owner(principal.user_id)
    return [
        CombatSummaryView(
            combat_id=s.combat_id,
            mode=s.mode,
            status=s.status,
            created_at=s.created_at.isoformat(),
        )
        for s in summaries
    ]
