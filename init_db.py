import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from decimal import Decimal

from app import app, db
from models import (
    OrderCore,
    OrderItem,
    PrintCompatibility,
    PrintCore,
    TShirtCharacteristic,
    TShirtCore,
)


COLOR_IMAGE_MAP = {
    'Белый': 'images/tshirts/tshirt_white.png',
    'Черный': 'images/tshirts/tshirt_black.png',
    'Красный': 'images/tshirts/tshirt_red.png',
    'Синий': 'images/tshirts/tshirt_blue.png',
    'Зеленый': 'images/tshirts/tshirt_green.png',
    'Желтый': 'images/tshirts/tshirt_yellow.png',
    'Серый': 'images/tshirts/tshirt_gray.png',
    'Темно-синий': 'images/tshirts/tshirt_navy.png',
    'Бордовый': 'images/tshirts/tshirt_burgundy.png',
}


PRINT_SEED = [
    ('Базовый принт 1', 'Демо-принт по умолчанию', 'images/prints/logo.png', Decimal('160.00')),
    ('Базовый принт 2', 'Демо-принт по умолчанию', 'images/prints/graphic.png', Decimal('200.00')),
    ('Базовый принт 3', 'Демо-принт по умолчанию', 'images/prints/photo.png', Decimal('240.00')),
]

PRINT_SOURCE_DIRS = ['prints']
PRINT_TARGET_DIR = os.path.join('static', 'images', 'prints')


def make_sku(model_name, color_name, size_name):
    model_code = ''.join(part[0] for part in model_name.split()).upper()
    color_code = color_name[:2].upper()
    return f'{model_code}-{color_code}-{size_name.upper()}'


def calc_unit_price(characteristic, print_item=None, custom_print_path=None):
    total = Decimal(characteristic.base_price)
    if print_item:
        total += Decimal(print_item.extra_price)
    if custom_print_path:
        total += Decimal('300.00')
    return total.quantize(Decimal('0.01'))


def normalize_filename(filename, index):
    name, ext = os.path.splitext(filename)
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '_', name).strip('_').lower()
    if not slug:
        slug = f'custom_print_{index + 1}'
    return f'{slug}{ext.lower()}'


def collect_custom_print_images():
    os.makedirs(PRINT_TARGET_DIR, exist_ok=True)

    source_dir = None
    for directory in PRINT_SOURCE_DIRS:
        if os.path.isdir(directory):
            png_files = [
                filename for filename in sorted(os.listdir(directory))
                if filename.lower().endswith('.png')
            ]
            if png_files:
                source_dir = directory
                break

    if not source_dir:
        return [], None

    copied_rel_paths = []
    used_names = set()
    source_files = [
        filename for filename in sorted(os.listdir(source_dir))
        if filename.lower().endswith('.png')
    ]

    for index, source_name in enumerate(source_files):
        target_name = normalize_filename(source_name, index)
        suffix = 1
        while target_name in used_names:
            base, ext = os.path.splitext(source_name)
            target_name = normalize_filename(f'{base}_{suffix}', index)
            suffix += 1
        used_names.add(target_name)

        src_path = os.path.join(source_dir, source_name)
        dst_path = os.path.join(PRINT_TARGET_DIR, target_name)
        shutil.copy2(src_path, dst_path)
        copied_rel_paths.append(f'images/prints/{target_name}')

    return copied_rel_paths, source_dir


def build_print_seed():
    copied_images, source_dir = collect_custom_print_images()
    if not copied_images:
        return PRINT_SEED, None

    selected_images = copied_images[:3]
    while len(selected_images) < 3:
        selected_images.append(copied_images[len(selected_images) % len(copied_images)])

    labels = [
        ('Авторский принт A', 'Принт загружен из вашей директории prints', Decimal('170.00')),
        ('Авторский принт B', 'Принт загружен из вашей директории prints', Decimal('210.00')),
        ('Авторский принт C', 'Принт загружен из вашей директории prints', Decimal('260.00')),
    ]

    custom_seed = []
    for index, (title, description, extra_price) in enumerate(labels):
        image_url = selected_images[index]
        custom_seed.append((title, description, image_url, extra_price))

    return custom_seed, source_dir


def init_database():
    try:
        with app.app_context():
            os.makedirs('static/uploads/designs', exist_ok=True)

            db.drop_all()
            db.create_all()
            print('✅ Таблицы пересозданы')

            catalog_plan = [
                ('Nova Classic', Decimal('1090.00'), ['Белый', 'Черный', 'Синий', 'Серый'], ['S', 'M', 'L', 'XL']),
                ('Pulse Slim', Decimal('1190.00'), ['Белый', 'Красный', 'Синий', 'Темно-синий'], ['S', 'M', 'L']),
                ('Orbit Oversize', Decimal('1390.00'), ['Черный', 'Зеленый', 'Бордовый', 'Желтый'], ['M', 'L', 'XL']),
                ('Street Core', Decimal('990.00'), ['Белый', 'Черный', 'Красный', 'Серый'], ['S', 'M', 'L']),
            ]

            size_extra = {'S': Decimal('0.00'), 'M': Decimal('50.00'), 'L': Decimal('100.00'), 'XL': Decimal('170.00')}
            tshirts = []

            for model_name, base_price, colors, sizes in catalog_plan:
                for color_name in colors:
                    for size_name in sizes:
                        tshirt = TShirtCore(
                            sku=make_sku(model_name, color_name, size_name),
                            is_active=True,
                        )
                        db.session.add(tshirt)
                        db.session.flush()

                        stock_qty = 45 + ((tshirt.tshirt_id * 3) % 20)
                        characteristic = TShirtCharacteristic(
                            tshirt_id=tshirt.tshirt_id,
                            model_name=model_name,
                            color_name=color_name,
                            size_name=size_name,
                            image_url=COLOR_IMAGE_MAP[color_name],
                            base_price=base_price + size_extra.get(size_name, Decimal('0.00')),
                            stock_qty=stock_qty,
                        )
                        db.session.add(characteristic)
                        tshirts.append(tshirt)

            active_print_seed, source_dir = build_print_seed()

            prints = []
            for print_name, description, image_url, extra_price in active_print_seed:
                prints.append(
                    PrintCore(
                        print_name=print_name,
                        description=description,
                        image_url=image_url,
                        extra_price=extra_price,
                        is_active=True,
                    )
                )
            db.session.add_all(prints)
            db.session.flush()

            dark_colors = {'Черный', 'Темно-синий', 'Бордовый'}
            dark_restricted_print_id = prints[2].print_id if len(prints) > 2 else None
            xl_restricted_print_id = prints[0].print_id if len(prints) > 0 else None

            compat_count = 0
            compatibility_map = {}
            for tshirt in tshirts:
                ch = tshirt.characteristic
                for print_item in prints:
                    is_allowed = True
                    if dark_restricted_print_id and ch.color_name in dark_colors and print_item.print_id == dark_restricted_print_id:
                        is_allowed = False
                    if xl_restricted_print_id and ch.size_name == 'XL' and print_item.print_id == xl_restricted_print_id:
                        is_allowed = False

                    compatibility = PrintCompatibility(
                        tshirt_id=tshirt.tshirt_id,
                        print_id=print_item.print_id,
                        is_allowed=is_allowed,
                    )
                    db.session.add(compatibility)
                    compatibility_map[(tshirt.tshirt_id, print_item.print_id)] = is_allowed
                    compat_count += 1

            status_cycle = ['new', 'processing', 'paid', 'shipped', 'completed']
            order_count = 12
            order_item_count = 0
            now = datetime.now()

            for i in range(order_count):
                order = OrderCore(
                    client_name=f'Клиент {i + 1}',
                    client_phone=f'+7 (900) 000-{i:02d}-{(i + 11):02d}',
                    client_email=f'client{i + 1}@mail.ru',
                    order_date=now - timedelta(days=(order_count - i)),
                    status=status_cycle[i % len(status_cycle)],
                    total_amount=Decimal('0.00'),
                    comment='Демо-заказ для заполнения базы',
                )
                db.session.add(order)
                db.session.flush()

                line_count = 2 if i % 2 == 0 else 3
                order_total = Decimal('0.00')

                for j in range(line_count):
                    tshirt = tshirts[(i * 4 + j * 7) % len(tshirts)]
                    ch = tshirt.characteristic
                    quantity = 1 + ((i + j) % 3)

                    allowed_prints = [
                        print_item for print_item in prints
                        if compatibility_map.get((tshirt.tshirt_id, print_item.print_id), False)
                    ]

                    print_item = None
                    if allowed_prints and (i + j) % 4 != 0:
                        print_item = allowed_prints[(i + j) % len(allowed_prints)]

                    custom_print_path = None
                    if not print_item and (i + j) % 5 == 0:
                        custom_print_path = f'seed_custom_{i}_{j}.png'

                    unit_price = calc_unit_price(ch, print_item, custom_print_path)
                    item_total = (unit_price * quantity).quantize(Decimal('0.01'))

                    db.session.add(
                        OrderItem(
                            order_id=order.order_id,
                            tshirt_id=tshirt.tshirt_id,
                            print_id=print_item.print_id if print_item else None,
                            quantity=quantity,
                            unit_price=unit_price,
                            custom_print_path=custom_print_path,
                            item_total=item_total,
                        )
                    )

                    ch.stock_qty = max(0, ch.stock_qty - quantity)
                    order_total += item_total
                    order_item_count += 1

                order.total_amount = order_total.quantize(Decimal('0.01'))

            db.session.commit()

            table_counts = {
                'Футболки_Стержневая': TShirtCore.query.count(),
                'ХарактеристикиФутболок_Характеристическая': TShirtCharacteristic.query.count(),
                'Принты_Стержневая': PrintCore.query.count(),
                'СовместимостьПринтов_Ассоциативная': PrintCompatibility.query.count(),
                'Заказы_Стержневая': OrderCore.query.count(),
                'СоставЗаказа_Ассоциативная': OrderItem.query.count(),
            }

            print(f'✅ Добавлено записей совместимости: {compat_count}')
            print(f'✅ Добавлено демо-заказов: {order_count}')
            print(f'✅ Добавлено позиций в заказах: {order_item_count}')
            if source_dir:
                print(f'✅ Принты загружены из директории: {source_dir}')
            print('📊 Количество записей по таблицам:')
            for table_name, count in table_counts.items():
                print(f'   - {table_name}: {count}')
            print('\n🎉 База данных успешно инициализирована.')
            print('Запуск: python app.py')

    except Exception as exc:
        print(f'❌ Ошибка инициализации: {exc}')
        db.session.rollback()
        sys.exit(1)


if __name__ == '__main__':
    init_database()
