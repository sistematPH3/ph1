from sqlalchemy import text

class SupplierRepository:
    def __init__(self, db_connection):
        self.db = db_connection

    def find_by_tax_id(self, tax_id):
        query = text("SELECT id FROM suppliers WHERE tax_id = :tax_id")
        result = self.db.session.execute(query, {'tax_id': tax_id}).fetchone()
        return result is not None

    def save(self, supplier_data):
        query = text("""
            INSERT INTO suppliers (name, tax_id, contact_name, phone, email, status)
            VALUES (:name, :tax_id, :contact_name, :phone, :email, :status) RETURNING id;
        """)
        
        result = self.db.session.execute(query, {
            'name': supplier_data.name,
            'tax_id': supplier_data.tax_id,
            'contact_name': supplier_data.contact_name,
            'phone': supplier_data.phone,
            'email': supplier_data.email,
            'status': supplier_data.status
        })
        
        self.db.session.commit()
        return result.fetchone()[0]