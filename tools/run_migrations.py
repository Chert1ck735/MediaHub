from alembic.config import Config
from alembic import command

cfg = Config("alembic.ini")

print("=== 1) stamp init revision f3410cd5e9c7 ===")
command.stamp(cfg, "f3410cd5e9c7")

print("\n=== 2) upgrade head ===")
command.upgrade(cfg, "head")

print("\n=== 3) current ===")
command.current(cfg)
