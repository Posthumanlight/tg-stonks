from dataclasses import dataclass, field

@dataclass
class Item:
    item_id : str
    name : str
    units : str
    item_type : str | list = 'generic'
    tags : list = field(default_factory=list)

