from pathlib import Path

def sz(d):
    b = sum(p.stat().st_size for p in Path(d).rglob("*") if p.is_file())
    return b, b / 1e9

for label, d in [
    ("data/curated", "D:/claude_space/MakeMeMeme/data/curated"),
    ("data/reddit (leftover dropped)", "D:/claude_space/MakeMeMeme/data/reddit"),
    ("data (total)", "D:/claude_space/MakeMeMeme/data"),
]:
    try:
        n, gb = sz(d)
        print(f"{label}: {n} files, {gb:.2f} GB")
    except Exception as e:
        print(label, "ERR", e)
