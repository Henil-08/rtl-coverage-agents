"""uv run python -m rag build | fetch | index | search "query" """

import sys

from rag import kb


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd in ("build", "fetch"):
        for doc_id, status in kb.fetch():
            print(f"{doc_id:<28} {status}")
    if cmd in ("build", "index"):
        print(kb.build())
    if cmd == "search":
        base = kb.load()
        if base is None:
            sys.exit("no index yet: run `uv run python -m rag build`")
        for hit in base.search(" ".join(sys.argv[2:])):
            where = f" p.{hit['page']}" if hit["page"] else ""
            print(f"[{hit['score']}] {hit['title']}{where}\n    {hit['text'][:220]}...\n")


if __name__ == "__main__":
    main()
