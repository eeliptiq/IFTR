# menu_item.py (or restaurant.py if adding there)
from typing import List, Dict, Optional, Any  # Make sure Any is imported
from datetime import datetime
from enum import Enum
from pydantic import Field, validator, ConfigDict

# Import from your general base model
from app.models.general import IFTRBaseModel, generate_id


# Don't import from order.py here if order.py imports from this file
# That creates a circular import. Instead, define the enums here:

class OptionType(str, Enum):
    """Types of menu item options/customizations"""
    SINGLE_CHOICE = "single_choice"  # Choose one from list
    MULTIPLE_CHOICE = "multiple_choice"  # Choose multiple
    QUANTITY = "quantity"  # Number (e.g., extra cheese portions)
    BOOLEAN = "boolean"  # Yes/No toggle
    TEXT = "text"  # Free text (e.g., special instructions)


class MenuOption(IFTRBaseModel):
    """A single customization option for a menu item"""
    option_id: str = Field(default_factory=lambda: generate_id("opt"))
    name: str  # e.g., "Spice Level", "Extra Toppings"
    description: str = ""
    option_type: OptionType = OptionType.SINGLE_CHOICE
    required: bool = False
    min_choices: int = 0  # For multiple_choice
    max_choices: int = 5  # For multiple_choice
    min_quantity: int = 0  # For quantity type
    max_quantity: int = 10  # For quantity type

    # Available choices for single/multiple choice
    choices: List[Dict[str, Any]] = Field(default_factory=list)  # Now Any is available

    @validator('choices')
    def validate_choices(cls, v, values):
        """Validate choices based on option type"""
        if 'option_type' in values:
            option_type = values['option_type']
            if option_type in [OptionType.SINGLE_CHOICE, OptionType.MULTIPLE_CHOICE]:
                if not v:
                    raise ValueError(f"{option_type.value} options must have choices")

                # Ensure each choice has required fields
                for choice in v:
                    if 'id' not in choice or 'name' not in choice:
                        raise ValueError("Choice must have 'id' and 'name'")
        return v

    @property
    def has_extra_cost(self) -> bool:
        """Check if any choices have additional cost"""
        return any(choice.get('price', 0) > 0 for choice in self.choices)


class MenuItemModifier(IFTRBaseModel):
    """Base modifier that can adjust price, calories, etc."""
    modifier_id: str = Field(default_factory=lambda: generate_id("mod"))
    name: str
    description: str = ""
    price_adjustment: float = 0.0
    calorie_adjustment: int = 0
    available: bool = True



# Enhanced MenuItem class with options
class MenuItem(IFTRBaseModel):
    item_id: str = Field(default_factory=lambda: generate_id("item"))
    name: str
    description: str = ""
    price: float

    # Item categories and tags
    category: str = ""
    subcategory: str = ""
    tags: List[str] = Field(default_factory=list)  # ["spicy", "vegetarian", "gluten-free"]

    # Item properties
    is_available: bool = True
    is_surplus: bool = False
    surplus_quantity: int = 0
    surplus_expiry: Optional[datetime] = None

    # Nutritional info (optional)
    calories: Optional[int] = None
    allergens: List[str] = Field(default_factory=list)  # ["nuts", "dairy", "gluten"]

    # Images
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

    # Customization options
    options: List[MenuOption] = Field(default_factory=list)
    modifiers: List[MenuItemModifier] = Field(default_factory=list)

    # Preparation info
    prep_time_minutes: int = 15  # Estimated preparation time
    is_preorder_only: bool = False

    @property
    def has_options(self) -> bool:
        """Check if item has customization options"""
        return len(self.options) > 0

    @property
    def base_price(self) -> float:
        """Get base price before any customizations"""
        return self.price

    @property
    def min_price(self) -> float:
        """Minimum possible price with required options"""
        min_price = self.price

        # Add minimum required option costs
        for option in self.options:
            if option.required:
                if option.option_type == OptionType.SINGLE_CHOICE:
                    # Find cheapest required choice
                    min_choice_price = min((choice.get('price', 0) for choice in option.choices), default=0)
                    min_price += min_choice_price
                elif option.option_type == OptionType.QUANTITY:
                    min_price += option.min_quantity * min((choice.get('price', 0) for choice in option.choices),
                                                           default=0)

        return min_price

    @property
    def max_price(self) -> float:
        """Maximum possible price with all premium options"""
        max_price = self.price

        # Add maximum possible option costs
        for option in self.options:
            if option.option_type == OptionType.MULTIPLE_CHOICE:
                # Sort by price descending and take max_choices most expensive
                sorted_choices = sorted(option.choices, key=lambda x: x.get('price', 0), reverse=True)
                top_choices = sorted_choices[:option.max_choices]
                max_price += sum(choice.get('price', 0) for choice in top_choices)
            elif option.option_type == OptionType.QUANTITY:
                max_choice_price = max((choice.get('price', 0) for choice in option.choices), default=0)
                max_price += option.max_quantity * max_choice_price

        return max_price

    def get_option_by_id(self, option_id: str) -> Optional[MenuOption]:
        """Find an option by its ID"""
        for option in self.options:
            if option.option_id == option_id:
                return option
        return None