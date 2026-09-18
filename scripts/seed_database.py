from __future__ import annotations

import argparse
import json

from sql_agent.core.config import Settings
from sql_agent.db.models import Base
from sql_agent.db.seed import seed_database
from sql_agent.db.session import build_engine, ensure_sqlite_parent


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化并填充模拟业务数据库")
    parser.add_argument("--force", action="store_true", help="清空现有业务数据后重新生成")
    parser.add_argument("--scale", type=float, default=1.0, help="数据规模倍率，默认 1.0")
    args = parser.parse_args()

    settings = Settings()
    ensure_sqlite_parent(settings.database_url)
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    stats = seed_database(engine, force=args.force, scale=args.scale)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

