from dataclasses import dataclass
from engine.player.inventory import PlayerInventory

@dataclass
class Player:
    player_id : str
    player_name : str
    currency: float
    inventory: PlayerInventory

