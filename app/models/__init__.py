from app.extensions import db

from .inventory_model import Product, Inventory, Category
from .logistics_model import Location, Supplier, Purchase, PurchaseDetail, Movement, MovementDetail, ExchangeRateHistory, PurchaseAuditLog
from .security_model import Role, User, Notification, PasswordRecovery, LoginAudit, user_locations 
from .waste_model import WasteType, Waste, AuditLog