"""A maze, laid out as text: "#" a wall, " " a path -- what ``layout: maze`` writes.

The owner's Maze_test01 (2026-10-03): the "Maze" idea card, their monster picture, and
"make this a top down view of a maze you create, no road". The 4B understood -- it asked
"should they avoid walls or find a path to the monster?" -- and had nothing to build a
maze with: the scene layer knew skies, roads and buildings standing on them, so its walls
were buildings on a road. A maze is a layout, not a drawing, the way ``count`` is a row:
Gary decides there is one, and this lays it out.

Every maze here can be solved: it is carved as a tree of corridors from the start, so
there is exactly one way between any two open squares. The start is the top-left square;
the end is the open square farthest from it along the corridors. Nothing here uses
pygame, and the same seed always gives the same maze.
"""

from __future__ import annotations

import random
from collections import deque


def carve(columns: int, rows: int, seed: int = 0) -> list[str]:
    """A maze ``columns`` x ``rows`` squares (both odd, at least 5), one string a row."""
    columns, rows = max(5, columns | 1), max(5, rows | 1)
    grid = [["#"] * columns for _ in range(rows)]
    pick = random.Random(seed)
    stack = [(1, 1)]
    grid[1][1] = " "
    while stack:
        x, y = stack[-1]
        steps = [(dx, dy) for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))
                 if 0 < x + dx < columns - 1 and 0 < y + dy < rows - 1
                 and grid[y + dy][x + dx] == "#"]
        if not steps:
            stack.pop()
            continue
        dx, dy = pick.choice(steps)
        grid[y + dy // 2][x + dx // 2] = " "
        grid[y + dy][x + dx] = " "
        stack.append((x + dx, y + dy))
    return ["".join(row) for row in grid]


def open_squares(grid: list[str]) -> set[tuple[int, int]]:
    return {(x, y) for y, row in enumerate(grid) for x, mark in enumerate(row) if mark != "#"}


def start(grid: list[str]) -> tuple[int, int] | None:
    """The square a player starts on: the top-left-most open square."""
    squares = sorted(open_squares(grid), key=lambda square: (square[0] + square[1], square))
    return squares[0] if squares else None


def end(grid: list[str]) -> tuple[int, int] | None:
    """The open square farthest from the start along the corridors -- the goal."""
    first = start(grid)
    if first is None:
        return None
    squares = open_squares(grid)
    far, seen, queue = first, {first}, deque([first])
    while queue:
        square = queue.popleft()
        far = square
        x, y = square
        for step in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if step in squares and step not in seen:
                seen.add(step)
                queue.append(step)
    return far
