import os

class Config:
    SECRET_KEY = 'your-secret-key-change-this'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///tshirt_shop.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads/designs'  # Изменяем путь
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}