import io
import os
import uuid
from datetime import datetime
from decimal import Decimal

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from PIL import Image
from werkzeug.utils import secure_filename

from config import Config
from models import (
    OrderCore,
    OrderItem,
    PrintCompatibility,
    PrintCore,
    TShirtCharacteristic,
    TShirtCore,
    db,
)

REPORTLAB_AVAILABLE = True
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception:
    REPORTLAB_AVAILABLE = False

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

PDF_FONT_NAME = 'Helvetica'
if REPORTLAB_AVAILABLE:
    for path in [
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
    ]:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont('CyrillicFont', path))
            PDF_FONT_NAME = 'CyrillicFont'
            break

COLOR_HEX_MAP = {
    'Белый': '#f5f7f9',
    'Черный': '#1d1d1f',
    'Красный': '#d74141',
    'Синий': '#3669c9',
    'Зеленый': '#2f9d67',
    'Желтый': '#e9c342',
    'Серый': '#8f969b',
    'Темно-синий': '#2f3f66',
    'Бордовый': '#7f2f45',
}


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )


def save_custom_design(file_storage):
    if not file_storage or file_storage.filename == '':
        return None
    if not allowed_file(file_storage.filename):
        return None

    filename = f'{uuid.uuid4().hex}_{secure_filename(file_storage.filename)}'
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    image = Image.open(file_storage)
    if image.mode in ('RGBA', 'P'):
        image = image.convert('RGB')
    image.thumbnail((1200, 1200))
    image.save(file_path, optimize=True, quality=90)
    return filename


def get_cart():
    return session.setdefault('cart', [])


def save_cart(items):
    session['cart'] = items
    session.modified = True


def calculate_unit_price(characteristic, print_item, custom_print_path):
    total = Decimal(characteristic.base_price)
    if print_item:
        total += Decimal(print_item.extra_price or 0)
    if custom_print_path:
        total += Decimal('300.00')
    return total.quantize(Decimal('0.01'))


def build_cart_details():
    raw_cart = get_cart()
    normalized = []
    details = []
    total = Decimal('0.00')

    for raw in raw_cart:
        tshirt = db.session.get(TShirtCore, raw.get('tshirt_id'))
        if not tshirt or not tshirt.is_active or not tshirt.characteristic:
            continue

        characteristic = tshirt.characteristic
        print_item = None
        if raw.get('print_id'):
            print_item = db.session.get(PrintCore, raw['print_id'])
            if not print_item or not print_item.is_active:
                print_item = None

        quantity = int(raw.get('quantity', 1))
        if quantity < 1:
            quantity = 1

        normalized_item = {
            'cart_id': raw.get('cart_id', uuid.uuid4().hex),
            'tshirt_id': tshirt.tshirt_id,
            'print_id': print_item.print_id if print_item else None,
            'custom_print_path': raw.get('custom_print_path'),
            'quantity': quantity,
        }
        normalized.append(normalized_item)

        unit_price = calculate_unit_price(characteristic, print_item, normalized_item['custom_print_path'])
        subtotal = (unit_price * quantity).quantize(Decimal('0.01'))
        total += subtotal

        details.append(
            {
                'cart_id': normalized_item['cart_id'],
                'tshirt_id': tshirt.tshirt_id,
                'sku': tshirt.sku,
                'model_name': characteristic.model_name,
                'color_name': characteristic.color_name,
                'size_name': characteristic.size_name,
                'image_url': characteristic.image_url,
                'stock_qty': characteristic.stock_qty,
                'print_id': print_item.print_id if print_item else None,
                'print_name': print_item.print_name if print_item else None,
                'print_extra': float(print_item.extra_price) if print_item else 0.0,
                'custom_print_path': normalized_item['custom_print_path'],
                'quantity': quantity,
                'unit_price': float(unit_price),
                'subtotal': float(subtotal),
            }
        )

    if normalized != raw_cart:
        save_cart(normalized)

    return details, float(total.quantize(Decimal('0.01')))


def append_item_to_cart(cart, tshirt, quantity, selected_print_id=None, custom_print_path=None):
    if quantity < 1:
        quantity = 1
    if quantity > tshirt.characteristic.stock_qty:
        return False, 'Недостаточно товара на складе'

    if not custom_print_path:
        for item in cart:
            if (
                item.get('tshirt_id') == tshirt.tshirt_id
                and item.get('print_id') == selected_print_id
                and not item.get('custom_print_path')
            ):
                next_qty = int(item.get('quantity', 1)) + quantity
                if next_qty > tshirt.characteristic.stock_qty:
                    return False, 'В корзине уже максимальное доступное количество'
                item['quantity'] = next_qty
                return True, None

    cart.append(
        {
            'cart_id': uuid.uuid4().hex,
            'tshirt_id': tshirt.tshirt_id,
            'print_id': selected_print_id,
            'custom_print_path': custom_print_path,
            'quantity': quantity,
        }
    )
    return True, None


def get_grouped_catalog_products(selected_model='', selected_color='', limit=None):
    query = (
        db.session.query(TShirtCharacteristic, TShirtCore.tshirt_id, TShirtCore.sku)
        .join(TShirtCore, TShirtCore.tshirt_id == TShirtCharacteristic.tshirt_id)
        .filter(TShirtCore.is_active.is_(True))
    )

    if selected_model:
        query = query.filter(TShirtCharacteristic.model_name == selected_model)
    if selected_color:
        query = query.filter(TShirtCharacteristic.color_name == selected_color)

    rows = query.order_by(
        TShirtCharacteristic.model_name.asc(),
        TShirtCharacteristic.color_name.asc(),
        TShirtCharacteristic.size_name.asc(),
    ).all()

    grouped = {}
    for characteristic, tshirt_id, sku in rows:
        key = (characteristic.model_name, characteristic.color_name)
        if key not in grouped:
            grouped[key] = {
                'tshirt_id': tshirt_id,
                'sku': sku,
                'model_name': characteristic.model_name,
                'color_name': characteristic.color_name,
                'image_url': characteristic.image_url,
                'base_price': float(characteristic.base_price),
                'stock_qty': 0,
                'sizes': set(),
            }
        grouped_item = grouped[key]
        grouped_item['stock_qty'] += characteristic.stock_qty
        grouped_item['base_price'] = min(grouped_item['base_price'], float(characteristic.base_price))
        grouped_item['sizes'].add(characteristic.size_name)

    products = []
    for grouped_item in grouped.values():
        grouped_item['sizes'] = sorted(grouped_item['sizes'])
        products.append(grouped_item)

    products.sort(key=lambda item: (item['model_name'], item['color_name']))
    if limit is not None:
        products = products[:limit]
    return products


@app.context_processor
def utility_processor():
    def cart_count():
        return sum(int(item.get('quantity', 1)) for item in get_cart())

    return {'cart_count': cart_count}


@app.route('/')
def index():
    featured_products = get_grouped_catalog_products(limit=6)
    prints = (
        PrintCore.query.filter_by(is_active=True)
        .order_by(PrintCore.print_name.asc())
        .limit(3)
        .all()
    )
    return render_template('index.html', featured_products=featured_products, prints=prints)


@app.route('/catalog')
def catalog():
    selected_model = request.args.get('model', '').strip()
    selected_color = request.args.get('color', '').strip()
    products = get_grouped_catalog_products(selected_model=selected_model, selected_color=selected_color)

    filter_base_query = (
        db.session.query(TShirtCharacteristic)
        .join(TShirtCore)
        .filter(TShirtCore.is_active.is_(True))
    )
    models = [row[0] for row in filter_base_query.with_entities(TShirtCharacteristic.model_name).distinct().all()]
    colors = [row[0] for row in filter_base_query.with_entities(TShirtCharacteristic.color_name).distinct().all()]

    models.sort()
    colors.sort()

    return render_template(
        'catalog.html',
        products=products,
        models=models,
        colors=colors,
        selected_model=selected_model,
        selected_color=selected_color,
    )


@app.route('/product/<int:tshirt_id>')
def product_detail(tshirt_id):
    tshirt = db.session.get(TShirtCore, tshirt_id)
    if not tshirt or not tshirt.is_active or not tshirt.characteristic:
        flash('Товар не найден', 'warning')
        return redirect(url_for('catalog'))

    characteristic = tshirt.characteristic
    variants = (
        db.session.query(TShirtCore)
        .join(TShirtCharacteristic)
        .filter(
            TShirtCore.is_active.is_(True),
            TShirtCharacteristic.model_name == characteristic.model_name,
        )
        .order_by(
            TShirtCharacteristic.color_name.asc(),
            TShirtCharacteristic.size_name.asc(),
        )
        .all()
    )

    variant_ids = [variant.tshirt_id for variant in variants]
    all_prints = (
        PrintCore.query.filter_by(is_active=True)
        .order_by(PrintCore.print_name.asc())
        .all()
    )
    print_by_id = {
        print_item.print_id: {
            'print_id': print_item.print_id,
            'print_name': print_item.print_name,
            'extra_price': float(print_item.extra_price),
            'image_url': print_item.image_url,
        }
        for print_item in all_prints
    }

    compatibility_rows = (
        PrintCompatibility.query.filter(
            PrintCompatibility.tshirt_id.in_(variant_ids),
            PrintCompatibility.is_allowed.is_(True),
        ).all()
    )
    allowed_map = {}
    for row in compatibility_rows:
        allowed_map.setdefault(row.tshirt_id, []).append(row.print_id)

    variants_payload = []
    for variant in variants:
        ch = variant.characteristic
        allowed_prints = [
            print_by_id[print_id]
            for print_id in allowed_map.get(variant.tshirt_id, [])
            if print_id in print_by_id
        ]
        variants_payload.append(
            {
                'tshirt_id': variant.tshirt_id,
                'sku': variant.sku,
                'model_name': ch.model_name,
                'color_name': ch.color_name,
                'size_name': ch.size_name,
                'image_url': ch.image_url,
                'base_price': float(ch.base_price),
                'stock_qty': ch.stock_qty,
                'color_hex': COLOR_HEX_MAP.get(ch.color_name, '#aab2b8'),
                'prints': allowed_prints,
            }
        )

    current_variant = next(
        (variant for variant in variants_payload if variant['tshirt_id'] == tshirt_id),
        variants_payload[0] if variants_payload else None,
    )
    current_prints = current_variant['prints'] if current_variant else []
    color_options = sorted(
        {(variant['color_name'], variant['color_hex']) for variant in variants_payload},
        key=lambda item: item[0]
    )
    size_order = {'XS': 1, 'S': 2, 'M': 3, 'L': 4, 'XL': 5, 'XXL': 6, 'XXXL': 7}
    size_options = sorted(
        {variant['size_name'] for variant in variants_payload},
        key=lambda item: size_order.get(item, 100)
    )

    return render_template(
        'product_detail.html',
        tshirt=tshirt,
        characteristic=characteristic,
        prints=current_prints,
        variants_payload=variants_payload,
        current_variant=current_variant,
        color_options=color_options,
        size_options=size_options,
    )


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    tshirt_id = request.form.get('tshirt_id', type=int)
    quantity = request.form.get('quantity', type=int, default=1) or 1
    print_mode = request.form.get('print_mode', 'none')
    print_id = request.form.get('print_id', type=int)

    tshirt = db.session.get(TShirtCore, tshirt_id)
    if not tshirt or not tshirt.is_active or not tshirt.characteristic:
        flash('Товар недоступен', 'danger')
        return redirect(url_for('catalog'))

    selected_print_id = None
    custom_print_path = None

    if print_mode == 'ready':
        if not print_id:
            flash('Выберите принт', 'warning')
            return redirect(url_for('product_detail', tshirt_id=tshirt_id))

        print_item = db.session.get(PrintCore, print_id)
        compatibility = PrintCompatibility.query.filter_by(
            tshirt_id=tshirt_id,
            print_id=print_id,
            is_allowed=True,
        ).first()
        if not print_item or not print_item.is_active or not compatibility:
            flash('Этот принт нельзя использовать для выбранной футболки', 'warning')
            return redirect(url_for('product_detail', tshirt_id=tshirt_id))
        selected_print_id = print_id

    elif print_mode == 'custom':
        custom_print_path = save_custom_design(request.files.get('custom_print'))
        if not custom_print_path:
            flash('Загрузите изображение PNG/JPG/JPEG/GIF', 'warning')
            return redirect(url_for('product_detail', tshirt_id=tshirt_id))

    elif print_mode != 'none':
        flash('Некорректный режим принта', 'danger')
        return redirect(url_for('product_detail', tshirt_id=tshirt_id))

    cart = get_cart()
    success, message = append_item_to_cart(
        cart=cart,
        tshirt=tshirt,
        quantity=quantity,
        selected_print_id=selected_print_id,
        custom_print_path=custom_print_path,
    )
    if not success:
        flash(message, 'warning')
        return redirect(url_for('product_detail', tshirt_id=tshirt_id))

    save_cart(cart)
    flash('Товар добавлен в корзину', 'success')
    return redirect(url_for('cart'))


@app.route('/add_bundle_to_cart', methods=['POST'])
def add_bundle_to_cart():
    raw_ids = request.form.getlist('selected_tshirt_ids')
    if not raw_ids:
        flash('Выберите минимум одну позицию в каталоге', 'warning')
        return redirect(url_for('catalog'))

    tshirt_ids = []
    for raw_id in raw_ids:
        try:
            tshirt_id = int(raw_id)
        except (ValueError, TypeError):
            continue
        if tshirt_id not in tshirt_ids:
            tshirt_ids.append(tshirt_id)

    if not tshirt_ids:
        flash('Не удалось обработать выбранные позиции', 'warning')
        return redirect(url_for('catalog'))

    bundle_print_mode = request.form.get('bundle_print_mode', 'none')
    bundle_print_id = request.form.get('bundle_print_id', type=int)
    selected_print = None
    custom_print_path = None

    if bundle_print_mode == 'ready':
        selected_print = db.session.get(PrintCore, bundle_print_id)
        if not selected_print or not selected_print.is_active:
            flash('Выберите корректный общий принт', 'warning')
            return redirect(url_for('catalog'))
    elif bundle_print_mode == 'custom':
        custom_print_path = save_custom_design(request.files.get('bundle_custom_print'))
        if not custom_print_path:
            flash('Загрузите файл для общего принта (PNG/JPG/JPEG/GIF)', 'warning')
            return redirect(url_for('catalog'))
    elif bundle_print_mode != 'none':
        flash('Некорректный режим общего принта', 'danger')
        return redirect(url_for('catalog'))

    cart = get_cart()
    added_positions = 0
    skipped_positions = 0

    for tshirt_id in tshirt_ids:
        tshirt = db.session.get(TShirtCore, tshirt_id)
        if not tshirt or not tshirt.is_active or not tshirt.characteristic:
            skipped_positions += 1
            continue

        quantity = request.form.get(f'qty_{tshirt_id}', type=int, default=1) or 1
        if quantity < 1:
            quantity = 1

        if selected_print:
            compatibility = PrintCompatibility.query.filter_by(
                tshirt_id=tshirt_id,
                print_id=selected_print.print_id,
                is_allowed=True,
            ).first()
            if not compatibility:
                skipped_positions += 1
                continue

        success, _ = append_item_to_cart(
            cart=cart,
            tshirt=tshirt,
            quantity=quantity,
            selected_print_id=selected_print.print_id if selected_print else None,
            custom_print_path=custom_print_path,
        )
        if success:
            added_positions += 1
        else:
            skipped_positions += 1

    if added_positions > 0:
        save_cart(cart)
        flash(f'Добавлено позиций: {added_positions}', 'success')
        if skipped_positions > 0:
            flash(f'Пропущено позиций (остаток или несовместимость): {skipped_positions}', 'info')
        return redirect(url_for('cart'))

    flash('Ни одна выбранная позиция не была добавлена', 'warning')
    return redirect(url_for('catalog'))


@app.route('/cart')
def cart():
    cart_items, total = build_cart_details()
    return render_template('cart.html', cart_items=cart_items, total=total)


@app.route('/update_cart', methods=['POST'])
def update_cart():
    cart_id = request.form.get('cart_id')
    action = request.form.get('action')
    quantity = request.form.get('quantity', type=int, default=1)

    cart = get_cart()
    item = next((entry for entry in cart if entry.get('cart_id') == cart_id), None)

    if not item:
        flash('Позиция корзины не найдена', 'warning')
        return redirect(url_for('cart'))

    if action == 'remove':
        cart = [entry for entry in cart if entry.get('cart_id') != cart_id]
        save_cart(cart)
        flash('Товар удален из корзины', 'info')
        return redirect(url_for('cart'))

    tshirt = db.session.get(TShirtCore, item.get('tshirt_id'))
    if not tshirt or not tshirt.characteristic:
        flash('Товар уже недоступен', 'warning')
        return redirect(url_for('cart'))

    if quantity < 1:
        quantity = 1
    if quantity > tshirt.characteristic.stock_qty:
        flash('Недостаточно товара на складе', 'warning')
        return redirect(url_for('cart'))

    item['quantity'] = quantity
    save_cart(cart)
    flash('Количество обновлено', 'success')
    return redirect(url_for('cart'))


@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart_items, total = build_cart_details()
    if not cart_items:
        flash('Корзина пуста', 'warning')
        return redirect(url_for('catalog'))

    if request.method == 'POST':
        client_name = request.form.get('client_name', '').strip()
        client_phone = request.form.get('client_phone', '').strip()
        client_email = request.form.get('client_email', '').strip()
        comment = request.form.get('comment', '').strip()

        if not client_name:
            flash('Укажите имя получателя', 'warning')
            return redirect(url_for('checkout'))

        for item in cart_items:
            tshirt = db.session.get(TShirtCore, item['tshirt_id'])
            if not tshirt or not tshirt.characteristic:
                flash('Один из товаров больше недоступен', 'danger')
                return redirect(url_for('cart'))
            if item['quantity'] > tshirt.characteristic.stock_qty:
                flash(
                    f"Недостаточный остаток для {item['model_name']} ({item['size_name']})",
                    'warning',
                )
                return redirect(url_for('cart'))

        try:
            order = OrderCore(
                client_name=client_name,
                client_phone=client_phone or None,
                client_email=client_email or None,
                order_date=datetime.now(),
                status='new',
                total_amount=Decimal(str(total)).quantize(Decimal('0.01')),
                comment=comment or None,
            )
            db.session.add(order)
            db.session.flush()

            for item in cart_items:
                unit_price = Decimal(str(item['unit_price'])).quantize(Decimal('0.01'))
                item_total = Decimal(str(item['subtotal'])).quantize(Decimal('0.01'))

                db.session.add(
                    OrderItem(
                        order_id=order.order_id,
                        tshirt_id=item['tshirt_id'],
                        print_id=item['print_id'],
                        quantity=item['quantity'],
                        unit_price=unit_price,
                        custom_print_path=item['custom_print_path'],
                        item_total=item_total,
                    )
                )

                tshirt = db.session.get(TShirtCore, item['tshirt_id'])
                tshirt.characteristic.stock_qty -= item['quantity']

            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            flash(f'Ошибка оформления заказа: {exc}', 'danger')
            return redirect(url_for('checkout'))

        save_cart([])
        flash('Заказ успешно оформлен', 'success')
        return redirect(url_for('order_success', order_id=order.order_id))

    return render_template('checkout.html', cart_items=cart_items, total=total)


@app.route('/order_success/<int:order_id>')
def order_success(order_id):
    order = db.session.get(OrderCore, order_id)
    if not order:
        flash('Заказ не найден', 'warning')
        return redirect(url_for('catalog'))

    return render_template('order_success.html', order=order)


def _build_receipt_pdf(order, line_items):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName=PDF_FONT_NAME,
        fontSize=22,
        textColor=colors.HexColor('#0f3d3e'),
        alignment=1,
        spaceAfter=8,
    )
    normal_style = ParagraphStyle(
        'NormalRu',
        parent=styles['Normal'],
        fontName=PDF_FONT_NAME,
        fontSize=10,
        leading=14,
    )

    story = [
        Paragraph('Чек заказа футболок', title_style),
        Paragraph(f'Дата: {order.order_date.strftime("%d.%m.%Y %H:%M")}', normal_style),
        Paragraph(f'Номер заказа: {order.order_id}', normal_style),
        Paragraph(f'Клиент: {order.client_name}', normal_style),
        Spacer(1, 8 * mm),
    ]

    table_data = [['№', 'Товар', 'Принт', 'Кол-во', 'Цена', 'Сумма']]
    for idx, line in enumerate(line_items, start=1):
        table_data.append(
            [
                str(idx),
                line['name'],
                line['print_name'],
                str(line['quantity']),
                f"{line['unit_price']:.2f} ₽",
                f"{line['item_total']:.2f} ₽",
            ]
        )
    table_data.append(['', '', '', '', 'Итого', f'{float(order.total_amount):.2f} ₽'])

    table = Table(table_data, colWidths=[12 * mm, 70 * mm, 35 * mm, 22 * mm, 25 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ('FONTNAME', (0, 0), (-1, -1), PDF_FONT_NAME),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f3d3e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cfd8dc')),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f5f8f9')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#d8ecec')),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph('Спасибо за покупку.', normal_style))

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route('/download_receipt/<int:order_id>')
def download_receipt(order_id):
    if not REPORTLAB_AVAILABLE:
        flash('Для PDF-чека требуется библиотека reportlab', 'warning')
        return redirect(url_for('order_success', order_id=order_id))

    order = db.session.get(OrderCore, order_id)
    if not order:
        flash('Заказ не найден', 'warning')
        return redirect(url_for('catalog'))

    line_items = []
    for item in order.items:
        characteristic = item.tshirt.characteristic if item.tshirt else None
        if not characteristic:
            continue
        print_name = (
            item.print_item.print_name if item.print_item else (
                'Свой принт' if item.custom_print_path else 'Без принта'
            )
        )
        line_items.append(
            {
                'name': f"{characteristic.model_name} / {characteristic.color_name} / {characteristic.size_name}",
                'print_name': print_name,
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'item_total': float(item.item_total),
            }
        )

    pdf_buffer = _build_receipt_pdf(order, line_items)
    return send_file(
        pdf_buffer,
        as_attachment=False,
        download_name=f'order_{order.order_id}_receipt.pdf',
        mimetype='application/pdf',
    )


@app.route('/download_cart_receipt')
def download_cart_receipt():
    if not REPORTLAB_AVAILABLE:
        flash('Для PDF-чека требуется библиотека reportlab', 'warning')
        return redirect(url_for('cart'))

    cart_items, total = build_cart_details()
    if not cart_items:
        flash('Корзина пуста', 'warning')
        return redirect(url_for('cart'))

    pseudo_order = OrderCore(
        order_id=0,
        client_name='Гость',
        order_date=datetime.now(),
        total_amount=Decimal(str(total)),
    )

    line_items = []
    for item in cart_items:
        print_name = item['print_name'] or ('Свой принт' if item['custom_print_path'] else 'Без принта')
        line_items.append(
            {
                'name': f"{item['model_name']} / {item['color_name']} / {item['size_name']}",
                'print_name': print_name,
                'quantity': item['quantity'],
                'unit_price': item['unit_price'],
                'item_total': item['subtotal'],
            }
        )

    pdf_buffer = _build_receipt_pdf(pseudo_order, line_items)
    return send_file(
        pdf_buffer,
        as_attachment=False,
        download_name=f'cart_receipt_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
        mimetype='application/pdf',
    )


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5001)
