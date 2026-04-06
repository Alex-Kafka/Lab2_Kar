from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class TShirtCore(db.Model):
    __tablename__ = 'Футболки_Стержневая'

    tshirt_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sku = db.Column(db.String(50), unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    characteristic = db.relationship(
        'TShirtCharacteristic',
        back_populates='tshirt',
        uselist=False,
        cascade='all, delete-orphan'
    )
    compatibilities = db.relationship(
        'PrintCompatibility',
        back_populates='tshirt',
        cascade='all, delete-orphan'
    )
    order_items = db.relationship('OrderItem', back_populates='tshirt')


class TShirtCharacteristic(db.Model):
    __tablename__ = 'ХарактеристикиФутболок_Характеристическая'

    characteristic_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tshirt_id = db.Column(
        db.Integer,
        db.ForeignKey('Футболки_Стержневая.tshirt_id'),
        nullable=False,
        unique=True
    )
    model_name = db.Column(db.String(100), nullable=False)
    color_name = db.Column(db.String(50), nullable=False)
    size_name = db.Column(db.String(20), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    base_price = db.Column(db.Numeric(10, 2), nullable=False)
    stock_qty = db.Column(db.Integer, nullable=False, default=0)

    tshirt = db.relationship('TShirtCore', back_populates='characteristic')


class PrintCore(db.Model):
    __tablename__ = 'Принты_Стержневая'

    print_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    print_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    extra_price = db.Column(db.Numeric(10, 2), default=0)
    is_active = db.Column(db.Boolean, default=True)

    compatibilities = db.relationship(
        'PrintCompatibility',
        back_populates='print_item',
        cascade='all, delete-orphan'
    )
    order_items = db.relationship('OrderItem', back_populates='print_item')


class OrderCore(db.Model):
    __tablename__ = 'Заказы_Стержневая'

    order_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    client_name = db.Column(db.String(150), nullable=False)
    client_phone = db.Column(db.String(30))
    client_email = db.Column(db.String(100))
    order_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(30), nullable=False, default='new')
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    comment = db.Column(db.Text)

    items = db.relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')


class PrintCompatibility(db.Model):
    __tablename__ = 'СовместимостьПринтов_Ассоциативная'

    compatibility_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tshirt_id = db.Column(
        db.Integer,
        db.ForeignKey('Футболки_Стержневая.tshirt_id'),
        nullable=False
    )
    print_id = db.Column(
        db.Integer,
        db.ForeignKey('Принты_Стержневая.print_id'),
        nullable=False
    )
    is_allowed = db.Column(db.Boolean, nullable=False, default=True)

    tshirt = db.relationship('TShirtCore', back_populates='compatibilities')
    print_item = db.relationship('PrintCore', back_populates='compatibilities')

    __table_args__ = (
        db.UniqueConstraint('tshirt_id', 'print_id', name='uq_tshirt_print'),
    )


class OrderItem(db.Model):
    __tablename__ = 'СоставЗаказа_Ассоциативная'

    order_item_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id = db.Column(
        db.Integer,
        db.ForeignKey('Заказы_Стержневая.order_id'),
        nullable=False
    )
    tshirt_id = db.Column(
        db.Integer,
        db.ForeignKey('Футболки_Стержневая.tshirt_id'),
        nullable=False
    )
    print_id = db.Column(
        db.Integer,
        db.ForeignKey('Принты_Стержневая.print_id')
    )
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    custom_print_path = db.Column(db.String(255))
    item_total = db.Column(db.Numeric(10, 2), nullable=False)

    order = db.relationship('OrderCore', back_populates='items')
    tshirt = db.relationship('TShirtCore', back_populates='order_items')
    print_item = db.relationship('PrintCore', back_populates='order_items')
