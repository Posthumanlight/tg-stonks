from dataclasses import dataclass, field


class NotEnoughItemsError(Exception):
    def __init__(self, item_id, requested, available):
        self.item_id = item_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Not enough of item '{item_id}': requested {requested}, have {available}"
        )


@dataclass
class PlayerInventory:
    contents: dict = field(default_factory=dict)

    def add_item(self, item_id, quantity):
        if item_id in self.contents:
            self.contents[item_id] += quantity
        else:
            self.contents[item_id] = quantity

    def remove_item(self, item_id, quantity):
        available = self.contents.get(item_id, 0)
        if available < quantity:
            raise NotEnoughItemsError(item_id, quantity, available)
        elif available == quantity:
            self.contents.pop(item_id)
        else:
            self.contents[item_id] -= quantity