# test_imports_corrected.py
import sys
import os
from pathlib import Path


def setup_python_path():
    """Properly set up Python path for the project"""

    # Get the directory where this script is located
    script_dir = Path(__file__).parent.absolute()
    print(f"Script directory: {script_dir}")

    # Get project root (backend directory)
    project_root = script_dir

    # Important paths
    app_dir = project_root / "app"

    # Clear any existing problematic paths
    sys.path = [p for p in sys.path if "models" not in p and "app" not in p]

    # Add paths in correct order
    paths_to_add = [
        str(project_root),  # backend/
        str(app_dir),  # backend/app/
    ]

    for path in paths_to_add:
        if path not in sys.path:
            sys.path.insert(0, path)

    print("\nPython path configured:")
    for i, p in enumerate(sys.path[:5]):
        print(f"  {i}: {p}")

    return project_root


def test_import_directly():
    """Test imports by importing the modules directly"""
    print("\n" + "=" * 60)
    print("TESTING DIRECT IMPORTS")
    print("=" * 60)

    test_modules = [
        ("app.models.general", "general"),
        ("app.models.user", "user"),
        ("app.models.order", "order"),
        ("app.models.delivery", "delivery"),
        ("app.models.payment", "payment"),
        ("app.models.restaurant", "restaurant"),
        ("app.models.driver", "driver"),
        ("app.models.analytics", "analytics"),
    ]

    for module_path, module_name in test_modules:
        try:
            module = __import__(module_path, fromlist=[''])
            print(f"✅ Successfully imported: {module_path}")

            # List available classes in the module
            classes = [attr for attr in dir(module) if not attr.startswith('_')]
            print(f"   Available in {module_name}: {', '.join(classes[:5])}{'...' if len(classes) > 5 else ''}")

        except ImportError as e:
            print(f"❌ Failed to import {module_path}: {e}")


def test_specific_imports():
    """Test importing specific classes"""
    print("\n" + "=" * 60)
    print("TESTING SPECIFIC CLASS IMPORTS")
    print("=" * 60)

    test_cases = [
        ("app.models.general", "IFTRBaseModel"),
        ("app.models.general", "OrderStatus"),
        ("app.models.general", "VehicleType"),
        ("app.models.user", "UserRole"),
        ("app.models.user", "UserResponse"),
        ("app.models.user", "UserCreate"),
        ("app.models.order", "Order"),
        ("app.models.order", "OrderItem"),
        ("app.models.delivery", "Delivery"),
        ("app.models.delivery", "DeliveryStatus"),
        ("app.models.payment", "PaymentStatus"),
        ("app.models.payment", "PaymentMethod"),
        ("app.models.payment", "PaymentTransaction"),
        ("app.models.restaurant", "Restaurant"),
        ("app.models.driver", "Driver"),
        ("app.models.analytics", "DashboardStats"),
    ]

    successes = []

    for module_path, class_name in test_cases:
        try:
            # Import the module first
            module = __import__(module_path, fromlist=[class_name])
            # Get the class
            cls = getattr(module, class_name)
            print(f"✅ {module_path}.{class_name}")
            successes.append(f"{module_path}.{class_name}")
        except ImportError as e:
            print(f"❌ {module_path}.{class_name}: ImportError - {e}")
        except AttributeError as e:
            print(f"❌ {module_path}.{class_name}: AttributeError - {e}")
        except Exception as e:
            print(f"❌ {module_path}.{class_name}: {type(e).__name__} - {e}")

    print(f"\nResults: {len(successes)}/{len(test_cases)} imports successful")
    return len(successes)


def check_module_structure():
    """Check if modules exist and can be imported"""
    print("\n" + "=" * 60)
    print("CHECKING MODULE STRUCTURE")
    print("=" * 60)

    script_dir = Path(__file__).parent
    app_dir = script_dir / "app"
    models_dir = app_dir / "models"

    print(f"Checking directories:")
    print(f"  Script dir: {script_dir} - {'✅ Exists' if script_dir.exists() else '❌ Missing'}")
    print(f"  App dir: {app_dir} - {'✅ Exists' if app_dir.exists() else '❌ Missing'}")
    print(f"  Models dir: {models_dir} - {'✅ Exists' if models_dir.exists() else '❌ Missing'}")

    if models_dir.exists():
        print(f"\nModel files found:")
        py_files = list(models_dir.glob("*.py"))
        for py_file in py_files[:10]:  # Show first 10
            print(f"  - {py_file.name}")
        if len(py_files) > 10:
            print(f"  ... and {len(py_files) - 10} more")

    # Check __init__.py files
    print(f"\nChecking __init__.py files:")
    for dir_path in [app_dir, models_dir]:
        init_file = dir_path / "__init__.py"
        exists = init_file.exists()
        print(f"  {init_file}: {'✅ Exists' if exists else '❌ Missing'}")

        if exists:
            try:
                content = init_file.read_text()
                print(f"    Size: {len(content)} bytes")
            except:
                print(f"    Could not read")


def test_model_creation():
    """Test creating actual model instances"""
    print("\n" + "=" * 60)
    print("TESTING MODEL CREATION")
    print("=" * 60)

    try:
        # Try to import and create models
        from app.models.general import OrderStatus, VehicleType
        print(f"✅ OrderStatus: {OrderStatus.PENDING}")
        print(f"✅ VehicleType: {VehicleType.CAR}")

        # Try user model
        try:
            from app.models.user import UserCreate, UserRole

            user = UserCreate(
                email="test@example.com",
                name="Test User",
                role=UserRole.CUSTOMER
            )
            print(f"✅ Created User: {user.email} ({user.role})")
        except Exception as e:
            print(f"⚠ User creation failed: {e}")

    except Exception as e:
        print(f"❌ Model creation test failed: {e}")
        import traceback
        traceback.print_exc()


def create_fix_suggestions():
    """Provide specific fix suggestions based on the errors"""
    print("\n" + "=" * 60)
    print("FIX SUGGESTIONS")
    print("=" * 60)

    script_dir = Path(__file__).parent
    models_dir = script_dir / "app" / "models"

    if not models_dir.exists():
        print("❌ CRITICAL: models directory doesn't exist!")
        print(f"   Expected: {models_dir}")
        return

    # Check a few key files
    key_files = ["general.py", "user.py", "__init__.py"]

    for file_name in key_files:
        file_path = models_dir / file_name
        if file_path.exists():
            try:
                content = file_path.read_text()

                # Check for common issues
                issues = []

                if file_name == "__init__.py":
                    if len(content.strip()) < 10:
                        issues.append("Empty or nearly empty __init__.py")

                elif "from ." in content and "app.models." not in content:
                    issues.append("Contains relative imports that might need fixing")

                if issues:
                    print(f"⚠ {file_name}: {', '.join(issues)}")
                else:
                    print(f"✅ {file_name}: Looks good")

            except Exception as e:
                print(f"❌ {file_name}: Error reading - {e}")
        else:
            print(f"❌ {file_name}: Missing!")


def main():
    print("IFTR IMPORT TESTER - CORRECTED VERSION")
    print("=" * 60)

    # Setup Python path
    project_root = setup_python_path()

    # Check module structure
    check_module_structure()

    # Test imports
    test_import_directly()

    # Test specific imports
    success_count = test_specific_imports()

    # Test model creation if imports worked
    if success_count > 0:
        test_model_creation()

    # Provide fix suggestions
    create_fix_suggestions()

    print("\n" + "=" * 60)
    print("QUICK FIX COMMANDS:")
    print("=" * 60)

    print("\nIf imports are failing, try these commands:")
    print("1. Check your current directory:")
    print(f"   cd {project_root}")

    print("\n2. Run Python with explicit module syntax:")
    print(
        "   python -c \"import sys; sys.path.insert(0, '.'); from app.models.general import IFTRBaseModel; print('✅ Import successful')\"")

    print("\n3. Or create a simple test:")
    print("   cat > simple_test.py << 'EOF'")
    print("   import sys")
    print("   sys.path.insert(0, '.')")
    print("   from app.models.general import OrderStatus")
    print("   print(f'OrderStatus: {OrderStatus.PENDING}')")
    print("   EOF")
    print("   python simple_test.py")

    print("\n4. If you need to fix imports in model files:")
    print("   Run the fix_imports.py script again from the backend directory")


if __name__ == "__main__":
    main()