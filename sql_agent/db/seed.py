from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from sql_agent.db.models import Category, Order, OrderItem, Product, Sale, User

SEED_VERSION = "2026.09"
ORDER_STATUSES = ["pending", "paid", "shipped", "completed", "cancelled", "refunded"]
SUCCESS_STATUSES = {"paid", "shipped", "completed", "refunded"}
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "苏州"]
CHANNELS = ["web", "app", "mini_program", "offline", "partner"]
CATEGORY_NAMES = [
    ("手机数码", "手机、平板、智能穿戴等数码产品"),
    ("电脑办公", "笔记本、显示器、键鼠和办公设备"),
    ("家用电器", "大家电、厨房电器和生活电器"),
    ("服饰鞋包", "服装、鞋靴、箱包和配饰"),
    ("食品生鲜", "休闲食品、粮油和生鲜商品"),
    ("美妆个护", "护肤、彩妆、洗护和个人护理"),
    ("母婴玩具", "母婴用品、玩具和童装"),
    ("运动户外", "运动装备、健身和户外用品"),
    ("图书文娱", "图书、乐器、文创和娱乐产品"),
    ("家居建材", "家具、家装和五金工具"),
    ("汽车用品", "车载电器、养护和汽车配件"),
    ("医药保健", "健康监测、保健和医疗辅具"),
    ("宠物生活", "宠物食品、用品和服务"),
    ("珠宝配饰", "珠宝、钟表和时尚配饰"),
    ("礼品鲜花", "礼品、鲜花和节庆用品"),
    ("工业品", "工业耗材、仪器和设备"),
    ("虚拟服务", "会员、课程和数字服务"),
    ("其他", "未归入其他分类的商品"),
]
PRODUCT_WORDS = ["基础款", "轻享版", "专业版", "旗舰款", "便携款", "家庭装", "经典款", "智能款"]


def _scaled_count(base: int, scale: float, minimum: int = 1) -> int:
    return max(minimum, int(base * max(scale, 0.001)))


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _in_chunks(rows: list[dict[str, Any]], size: int = 2_000):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _clear_business_tables(session: Session) -> None:
    for model in (Sale, OrderItem, Order, Product, Category, User):
        session.execute(delete(model))


def seed_database(
    engine: Engine,
    *,
    force: bool = False,
    scale: float = 1.0,
    random_seed: int = 42,
) -> dict[str, int]:
    """Populate a realistic, deterministic business dataset.

    Default scale creates roughly 160k+ rows across six business tables. A
    smaller scale is useful for tests and local smoke checks.
    """

    rng = random.Random(random_seed)
    now = datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(days=180)
    total_seconds = int((now - start).total_seconds())

    category_count = _scaled_count(18, scale, 1)
    product_count = _scaled_count(600, scale, 5)
    user_count = _scaled_count(12_000, scale, 20)
    order_count = _scaled_count(30_000, scale, 50)

    with Session(engine) as session:
        existing = session.scalar(select(func.count()).select_from(Category)) or 0
        if existing and not force:
            return {
                "seed_version": SEED_VERSION,
                "categories": int(session.scalar(select(func.count()).select_from(Category)) or 0),
                "products": int(session.scalar(select(func.count()).select_from(Product)) or 0),
                "users": int(session.scalar(select(func.count()).select_from(User)) or 0),
                "orders": int(session.scalar(select(func.count()).select_from(Order)) or 0),
                "order_items": int(session.scalar(select(func.count()).select_from(OrderItem)) or 0),
                "sales": int(session.scalar(select(func.count()).select_from(Sale)) or 0),
            }

        if force:
            _clear_business_tables(session)

        category_rows = []
        for category_id in range(1, category_count + 1):
            name, description = CATEGORY_NAMES[(category_id - 1) % len(CATEGORY_NAMES)]
            category_rows.append(
                {
                    "id": category_id,
                    "name": f"{name}-{category_id:02d}" if category_id > len(CATEGORY_NAMES) else name,
                    "description": description,
                    "is_active": category_id != category_count,
                    "created_at": now - timedelta(days=240),
                    "updated_at": now - timedelta(days=240),
                }
            )

        product_rows: list[dict[str, Any]] = []
        for product_id in range(1, product_count + 1):
            category_id = ((product_id - 1) % category_count) + 1
            base = 20 + (category_id * 17) + rng.uniform(5, 1_800)
            price = _money(base)
            cost = _money(float(price) * rng.uniform(0.45, 0.82))
            status = "active"
            status_roll = rng.random()
            if status_roll > 0.94:
                status = "discontinued"
            elif status_roll > 0.88:
                status = "inactive"
            product_rows.append(
                {
                    "id": product_id,
                    "category_id": category_id,
                    "sku": f"SKU-{category_id:02d}-{product_id:06d}",
                    "name": f"{PRODUCT_WORDS[(product_id - 1) % len(PRODUCT_WORDS)]}-{product_id:04d}",
                    "price": price,
                    "cost": cost,
                    "stock_quantity": rng.choice([0, 1, 2, 5, 12, 30, 80, 150]),
                    "status": status,
                    "description": None if product_id % 19 == 0 else f"模拟商品 {product_id}",
                    "created_at": start - timedelta(days=rng.randint(1, 300)),
                    "updated_at": now - timedelta(days=rng.randint(0, 120)),
                }
            )

        user_rows: list[dict[str, Any]] = []
        for user_id in range(1, user_count + 1):
            created_at = start + timedelta(seconds=rng.randrange(total_seconds + 1))
            status_roll = rng.random()
            if status_roll > 0.98:
                status = "banned"
            elif status_roll > 0.94:
                status = "inactive"
            elif status_roll > 0.92:
                status = "deleted"
            else:
                status = "active"

            likely_login = created_at + timedelta(days=rng.randint(0, max(1, (now - created_at).days)))
            last_login_at = likely_login if rng.random() > 0.16 else None
            user_rows.append(
                {
                    "id": user_id,
                    "name": f"用户{user_id:05d}",
                    "email": f"user{user_id:05d}@example.com",
                    "phone": None if user_id % 13 == 0 else f"13{rng.randint(100000000, 999999999)}",
                    "city": None if user_id % 17 == 0 else rng.choice(CITIES),
                    "age": None if user_id % 11 == 0 else rng.randint(18, 65),
                    "status": status,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "last_login_at": last_login_at,
                }
            )

        order_rows: list[dict[str, Any]] = []
        item_rows: list[dict[str, Any]] = []
        sale_rows: list[dict[str, Any]] = []
        item_id = 0
        sale_id = 0

        for order_id in range(1, order_count + 1):
            created_at = start + timedelta(seconds=rng.randrange(total_seconds + 1))
            status = rng.choices(
                ORDER_STATUSES,
                weights=[7, 24, 18, 34, 7, 10],
                k=1,
            )[0]
            user_id = None if order_id % 97 == 0 else rng.randint(1, user_count)
            item_count = rng.choices([1, 2, 3, 4], weights=[32, 38, 21, 9], k=1)[0]
            order_total = Decimal("0")
            discount_total = Decimal("0")

            for _ in range(item_count):
                product = product_rows[rng.randrange(product_count)]
                quantity = rng.choices([1, 2, 3, 4, 5], weights=[52, 25, 13, 7, 3], k=1)[0]
                unit_price = product["price"]
                item_discount = _money(float(unit_price) * quantity * rng.uniform(0, 0.12))
                gross = _money(float(unit_price) * quantity)
                net = _money(float(gross) - float(item_discount))
                order_total += gross
                discount_total += item_discount

                item_id += 1
                item_rows.append(
                    {
                        "id": item_id,
                        "order_id": order_id,
                        "product_id": product["id"],
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "discount_amount": item_discount,
                    }
                )

                if status in SUCCESS_STATUSES:
                    sale_id += 1
                    if status == "refunded" and rng.random() < 0.72:
                        refund_amount = _money(float(net) * rng.uniform(0.2, 1.0))
                        sale_status = "refunded"
                    else:
                        refund_amount = Decimal("0.00")
                        sale_status = "normal"
                    if rng.random() < 0.015:
                        sale_status = "abnormal"
                        refund_amount = _money(float(net) * rng.uniform(0.8, 1.15))
                    sale_rows.append(
                        {
                            "id": sale_id,
                            "order_id": order_id,
                            "product_id": product["id"],
                            "sale_date": created_at + timedelta(minutes=rng.randint(2, 180)),
                            "quantity": quantity,
                            "sales_amount": net,
                            "refund_amount": refund_amount,
                            "channel": None if sale_id % 29 == 0 else rng.choice(CHANNELS),
                            "status": sale_status,
                        }
                    )

            order_rows.append(
                {
                    "id": order_id,
                    "order_no": f"ORD-{created_at:%Y%m%d}-{order_id:07d}",
                    "user_id": user_id,
                    "status": status,
                    "total_amount": order_total,
                    "discount_amount": discount_total,
                    "created_at": created_at,
                    "paid_at": created_at + timedelta(minutes=rng.randint(2, 60))
                    if status in SUCCESS_STATUSES
                    else None,
                }
            )

        session.execute(insert(Category), category_rows)
        for chunk in _in_chunks(product_rows):
            session.execute(insert(Product), chunk)
        for chunk in _in_chunks(user_rows):
            session.execute(insert(User), chunk)
        for chunk in _in_chunks(order_rows):
            session.execute(insert(Order), chunk)
        for chunk in _in_chunks(item_rows):
            session.execute(insert(OrderItem), chunk)
        for chunk in _in_chunks(sale_rows):
            session.execute(insert(Sale), chunk)
        session.commit()

    return {
        "seed_version": SEED_VERSION,
        "categories": len(category_rows),
        "products": len(product_rows),
        "users": len(user_rows),
        "orders": len(order_rows),
        "order_items": len(item_rows),
        "sales": len(sale_rows),
    }

