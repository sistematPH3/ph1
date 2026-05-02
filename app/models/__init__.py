from app.extensions import db

# Importamos todo para que Alembic (Migrate) lo detecte
from .inventory_model import Product, Inventory
from .logistics_model import Location, Supplier, Purchase, Movement, MovementDetail
from .security_model import Role, User, Notification, PasswordRecovery, user_locations
from .waste_model import WasteType, Waste, AuditLog