import os
import shutil

# folder where the script is located
root = os.path.dirname(os.path.abspath(__file__))
dest = os.path.join(root, "tiny")

os.makedirs(dest, exist_ok=True)

for filename in os.listdir(root):
    if filename.lower().endswith(".txt"):
        src = os.path.join(root, filename)
        dst = os.path.join(dest, filename)

        # copy original
        shutil.copy2(src, dst)

        # shrink the copy
        with open(dst, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        keep = max(1, len(content) // 4)
        tiny_text = content[:keep]

        with open(dst, "w", encoding="utf-8") as f:
            f.write(tiny_text)
