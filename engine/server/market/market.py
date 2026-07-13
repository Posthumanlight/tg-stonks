from dataclasses import dataclass, field

@dataclass
class Offer:
    offer_id: str
    owner_id : str
    buy : bool
    quantity: float
    price: float
