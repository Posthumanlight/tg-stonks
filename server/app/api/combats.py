"""Combat HTTP routes (docs/protocol.md). Live play goes over the WebSocket."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.static_json import respond
from app.auth.dependencies import current_user
from app.auth.tokens import Principal
from app.protocol.builder import BuilderView, CustomCombatRequest
from app.protocol.combats import CombatCreated, CombatSummaryView
from app.services.combat_router import CombatRouter
from app.services.custom_battles import CustomBattles

router = APIRouter(prefix="/combats")


def get_router(request: Request) -> CombatRouter:
    return request.app.state.combat_router


def get_battles(request: Request) -> CustomBattles:
    return request.app.state.custom_battles


@router.get(
    "/builder", response_model=BuilderView, dependencies=[Depends(current_user)]
)
async def get_builder(request: Request) -> Response:
    return respond(request, get_battles(request).builder)


@router.post("/custom", status_code=201)
async def create_custom(
    body: CustomCombatRequest,
    request: Request,
    principal: Principal = Depends(current_user),
) -> CombatCreated:
    setup = get_battles(request).setup_for(body)
    combat_id = await get_router(request).start_hotseat(
        principal.user_id, setup, resume_active=False
    )
    return CombatCreated(combat_id=combat_id)


@router.post("/demo")
async def create_demo(
    request: Request, principal: Principal = Depends(current_user)
) -> CombatCreated:
    """The quick battle: the default armies, or the user's active fight."""
    combat_id = await get_router(request).start_hotseat(
        principal.user_id, get_battles(request).default_setup, resume_active=True
    )
    return CombatCreated(combat_id=combat_id)


@router.post("/{combat_id}/abandon", status_code=204)
async def abandon(
    combat_id: str, request: Request, principal: Principal = Depends(current_user)
) -> Response:
    await get_router(request).abandon(principal.user_id, combat_id)
    return Response(status_code=204)


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
