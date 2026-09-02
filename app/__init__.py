import os
from flask import Flask

DOCS_FOLDER = "documents"
ALLOWED_EXT = (".txt", ".pdf", ".docx")

def create_app():
    os.makedirs(DOCS_FOLDER, exist_ok=True)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB
    
    # Register routes
    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    return app
