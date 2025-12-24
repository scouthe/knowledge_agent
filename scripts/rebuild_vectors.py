import os
from pathlib import Path

from config import OBSIDIAN_ROOT, KNOWLEDGE_STORE_ROOT, SPECIAL_USER
from utils.rebuild import rebuild_user_vectors


def rebuild():
    total = 0
    roots = [(SPECIAL_USER, Path(OBSIDIAN_ROOT))]
    if os.path.exists(KNOWLEDGE_STORE_ROOT):
        for name in os.listdir(KNOWLEDGE_STORE_ROOT):
            path = Path(KNOWLEDGE_STORE_ROOT) / name
            if path.is_dir():
                roots.append((name, path))
    for user, root in roots:
        total += rebuild_user_vectors(str(root), user)
    print(f"✅ 重建完成，写入切片总数: {total}")


if __name__ == "__main__":
    rebuild()
