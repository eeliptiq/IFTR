"""
menu_builder.py - Tools for building and managing restaurant menus
"""

from typing import List, Dict, Any, Optional
from decimal import Decimal
from menu_item import MenuOption, OptionType, MenuItem
from order import SelectedOption



class MenuBuilder:
    """Helper class for building and managing restaurant menus"""

    @staticmethod
    def create_single_choice_option(
            name: str,
            choices: List[Dict[str, Any]],
            required: bool = False,
            description: str = ""
    ) -> MenuOption:
        """Create a single choice option (radio buttons)"""
        return MenuOption(
            name=name,
            description=description,
            option_type=OptionType.SINGLE_CHOICE,
            required=required,
            choices=choices,
            min_choices=1 if required else 0,
            max_choices=1
        )

    @staticmethod
    def create_multiple_choice_option(
            name: str,
            choices: List[Dict[str, Any]],
            min_choices: int = 0,
            max_choices: int = 5,
            required: bool = False,
            description: str = ""
    ) -> MenuOption:
        """Create a multiple choice option (checkboxes)"""
        return MenuOption(
            name=name,
            description=description,
            option_type=OptionType.MULTIPLE_CHOICE,
            required=required,
            min_choices=min_choices,
            max_choices=max_choices,
            choices=choices
        )

    @staticmethod
    def create_quantity_option(
            name: str,
            base_price: float,
            min_quantity: int = 0,
            max_quantity: int = 10,
            required: bool = False,
            description: str = ""
    ) -> MenuOption:
        """Create a quantity option (number selector)"""
        return MenuOption(
            name=name,
            description=description,
            option_type=OptionType.QUANTITY,
            required=required,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            choices=[{"id": "default", "name": name, "price": base_price}]
        )

    @staticmethod
    def create_boolean_option(
            name: str,
            extra_price: float = 0.0,
            required: bool = False,
            description: str = ""
    ) -> MenuOption:
        """Create a yes/no option (toggle)"""
        return MenuOption(
            name=name,
            description=description,
            option_type=OptionType.BOOLEAN,
            required=required,
            choices=[{"id": "yes", "name": "Yes", "price": extra_price}]
        )

    @staticmethod
    def create_text_option(
            name: str,
            required: bool = False,
            description: str = "",
            placeholder: str = ""
    ) -> MenuOption:
        """Create a free text option (text input)"""
        option = MenuOption(
            name=name,
            description=description,
            option_type=OptionType.TEXT,
            required=required
        )
        # Store placeholder in metadata
        option.choices = [{"id": "text", "name": name, "placeholder": placeholder}]
        return option


class MenuValidator:
    """Validate menu items and customizations"""

    @staticmethod
    def validate_item_selection(
            menu_item: MenuItem,
            selected_options: List[SelectedOption],
            quantity: int = 1
    ) -> Dict[str, Any]:
        """
        Validate that selected options match the menu item's requirements

        Returns: {
            "valid": bool,
            "total_price": float,
            "errors": List[str],
            "warnings": List[str]
        }
        """
        errors = []
        warnings = []
        total_price = menu_item.price * quantity

        # Track which options were selected
        selected_option_ids = {opt.option_id for opt in selected_options}

        # Check required options
        for option in menu_item.options:
            if option.required and option.option_id not in selected_option_ids:
                errors.append(f"Required option missing: {option.name}")

        # Validate each selected option
        for selected_opt in selected_options:
            option = menu_item.get_option_by_id(selected_opt.option_id)
            if not option:
                errors.append(f"Invalid option selected: {selected_opt.option_name}")
                continue

            # Validate based on option type
            if option.option_type == OptionType.SINGLE_CHOICE:
                if len(selected_opt.selected_choices) != 1:
                    errors.append(f"{option.name}: Must select exactly one choice")

            elif option.option_type == OptionType.MULTIPLE_CHOICE:
                if len(selected_opt.selected_choices) < option.min_choices:
                    errors.append(f"{option.name}: Must select at least {option.min_choices} choices")
                if len(selected_opt.selected_choices) > option.max_choices:
                    errors.append(f"{option.name}: Cannot select more than {option.max_choices} choices")

            elif option.option_type == OptionType.QUANTITY:
                if selected_opt.selected_quantity < option.min_quantity:
                    errors.append(f"{option.name}: Minimum quantity is {option.min_quantity}")
                if selected_opt.selected_quantity > option.max_quantity:
                    errors.append(f"{option.name}: Maximum quantity is {option.max_quantity}")

            # Calculate extra cost
            if option.option_type == OptionType.QUANTITY:
                choice_price = option.choices[0].get('price', 0) if option.choices else 0
                selected_opt.extra_cost = choice_price * selected_opt.selected_quantity
            elif option.option_type == OptionType.BOOLEAN and selected_opt.selected_boolean:
                selected_opt.extra_cost = option.choices[0].get('price', 0) if option.choices else 0
            else:
                selected_opt.extra_cost = sum(choice.get('price', 0) for choice in selected_opt.selected_choices)

            total_price += selected_opt.extra_cost * quantity

        return {
            "valid": len(errors) == 0,
            "total_price": total_price,
            "errors": errors,
            "warnings": warnings
        }