"""Check the code against the layers docs/architecture.md declares.

    python scripts/layer_check.py

Reads the table under "## Code layers" in docs/architecture.md: each row
is a layer number and the components in it. A component is a top-level
package under package/src. A component imports only from layers below
its own, and components in one layer import none of each other.

Builds the import graph of package/src with ast, then reports each
import against the layers, with the importing file, and each cycle
between components. Exits 1 when it reports anything, or when a package
under package/src that holds code is in no layer.
"""

import ast
import re
import sys

from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "package" / "src"
ARCHITECTURE = ROOT / "docs" / "architecture.md"


def declared_layers() -> dict[str, int]:
    """Component name to layer number, from the Code layers table."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("## Code layers", 1)[1].split("\n## ", 1)[0]
    layers = {}

    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.match(r"^\d+\b", cells[0]):
            number = int(re.match(r"^\d+", cells[0])[0])
            for component in cells[1].split(","):
                layers[component.strip().strip("`")] = number

    if not layers:
        sys.exit(f"{ARCHITECTURE}: no table under '## Code layers'")

    return layers


def module_name(path: Path) -> tuple[str, bool]:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def imports(path: Path) -> list[str]:
    """Absolute names a file imports, relative imports resolved."""
    name, is_package = module_name(path)
    package = name.split(".") if is_package else name.split(".")[:-1]
    names = []

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                base = ".".join(base + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            names.append(base)

    return names


def main() -> int:
    layers = declared_layers()
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    # A package holding only __init__.py, such as compose/, holds data, not code.
    components = {
        p.relative_to(SRC).parts[0]
        for p in files
        if len(p.relative_to(SRC).parts) > 1 and p.name != "__init__.py"
    }
    problems = []

    for component in sorted(components - set(layers)):
        problems.append(f"package/src/{component} is in no layer")

    edges = defaultdict(list)

    for path in files:
        source = path.relative_to(SRC).parts[0]
        for name in imports(path):
            target = name.split(".")[0]
            if target in components and target != source:
                edges[(source, target)].append(f"{path.relative_to(ROOT)} imports {name}")

    for (source, target), sites in sorted(edges.items()):
        if source not in layers or target not in layers:
            continue
        if layers[source] < layers[target]:
            kind = f"layer {layers[source]} imports layer {layers[target]}"
        elif layers[source] == layers[target]:
            kind = f"{source} and {target} share layer {layers[source]}"
        else:
            continue
        problems += [f"{site}: {kind}" for site in sites]

    graph = defaultdict(set)
    for source, target in edges:
        graph[source].add(target)

    for cycle in cycles(graph):
        problems.append("cycle: " + " -> ".join(cycle + [cycle[0]]))

    for problem in problems:
        print(problem)

    return 1 if problems else 0


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected sets of two or more components (Tarjan)."""
    index, low, stack, on_stack, found = {}, {}, [], set(), []

    def visit(node):
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)

    return found


if __name__ == "__main__":
    sys.exit(main())
