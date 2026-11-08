from dotenv import load_dotenv # <-- 1. Importas la librería
import os

# 2. Cargas las variables antes que cualquier otra cosa
load_dotenv() 

from app import create_app, db
from flask_migrate import Migrate

app = create_app()

# Flask-Migrate necesita vincularse a la app y a la db aquí
migrate = Migrate(app, db)

if __name__ == "__main__":
    app.run(debug=True)