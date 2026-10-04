"""A 3D world made of blocks, seen through your own eyes. Walk with W A S D.

W and S walk forward and back, A and D turn (the arrow keys do the same).
Walk into the gold blocks to pick them up.
"""

import math
import random

import pygame

# Things you can change
WIDTH = 640
HEIGHT = 480
WALK_SPEED = 3.0          # metres a second: a bigger number walks faster
TURN_SPEED = 2.0          # a bigger number turns faster
SKY = "day"               # "day", "sunset", "night" or "space" (night and space have stars)
GROUND = "grass"          # "grass", "sand", "snow" or "moon"
HANDS = (232, 190, 150)   # the colour of your hands
SHOW_HANDS = True

# The world, seen from above. Every block is 1 metre on each side.
# Each letter is one kind of block (BLOCKS below says which), a space is open
# ground, and P is where you start.
WORLD = [
    "####################",
    "#                  #",
    "#  ww       *   ss #",
    "#  ww           ss #",
    "#        P         #",
    "#   g          *   #",
    "#   gg    sss      #",
    "# *  ggg   s    ww #",
    "#               ww #",
    "####################",
]

# What each letter in WORLD is: a name, its colour, and how many blocks high.
BLOCKS = {
    "#": ("stone", (128, 128, 138), 3),
    "s": ("stone", (128, 128, 138), 2),
    "g": ("grass", (98, 168, 76), 1),
    "w": ("wood", (122, 84, 50), 2),
    "*": ("gold", (242, 200, 64), 1),
}
# Walking into a block with this name picks it up for a point.
COLLECT = "gold"

# Planets in the sky: (direction in degrees, height above the ground in degrees,
# size, colour). For example (40, 20, 50, (220, 120, 80)) is a big orange one.
PLANETS = []

# What each SKY looks like: its colour, whether it has stars, and how much light there
# is. A colour like (200, 120, 60) works too. GROUNDS is the same for the ground.
SKIES = {
    "day": ((126, 184, 236), False, 1.0),
    "sunset": ((238, 150, 96), False, 0.85),
    "night": ((16, 22, 52), True, 0.5),
    "space": ((3, 3, 12), True, 0.8),
}
GROUNDS = {
    "grass": (92, 150, 76),
    "sand": (212, 188, 128),
    "snow": (232, 238, 244),
    "moon": (112, 112, 120),
}

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Block World")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 32)

# -- how the world is drawn: a ray for every few pixels across the screen --------
EYE = 1.6                 # how high your eyes are, in metres
FIELD_OF_VIEW = math.radians(66)
COLUMN = 4                # pixels each ray draws: smaller is sharper and slower
FAR = 24.0                # metres you can see
HORIZON = HEIGHT // 2
PROJECTION = (WIDTH / 2) / math.tan(FIELD_OF_VIEW / 2)
sky_colour, stars_out, light = SKIES.get(SKY, SKIES["day"]) if isinstance(SKY, str) \
    else (SKY, False, 1.0)
ground_colour = GROUNDS.get(GROUND, GROUNDS["grass"]) if isinstance(GROUND, str) else GROUND

blocks = {}               # (column, row) -> the letter of the block there
x, y = 1.5, 1.5           # where you are, in metres
for row, line in enumerate(WORLD):
    for column, letter in enumerate(line):
        if letter in BLOCKS:
            blocks[(column, row)] = letter
        elif letter == "P":
            x, y = column + 0.5, row + 0.5
facing = 0.0              # which way you look, in radians
score = 0
to_find = sum(1 for letter in blocks.values() if BLOCKS[letter][0] == COLLECT)
tallest = max([BLOCKS[letter][2] for letter in blocks.values()] or [1])
stars = [(random.uniform(0, math.tau), random.randint(0, HORIZON)) for _ in range(120)]


def mix(colour, other, amount):
    """``colour`` moved ``amount`` of the way toward ``other``."""
    return tuple(int(a + (b - a) * amount) for a, b in zip(colour, other, strict=True))


def shade(colour, amount):
    return tuple(max(0, min(255, int(c * amount))) for c in colour)


def screen_y(height, distance):
    """Where a point ``height`` metres up and ``distance`` metres away is on screen."""
    return HORIZON + (EYE - height) * PROJECTION / distance


def cast(ray_x, ray_y):
    """Every block this ray passes over, nearest first: (enter, leave, letter, side)."""
    cell_x, cell_y = int(x), int(y)
    step_x = 1 if ray_x > 0 else -1
    step_y = 1 if ray_y > 0 else -1
    delta_x = abs(1 / ray_x) if ray_x else 1e9
    delta_y = abs(1 / ray_y) if ray_y else 1e9
    next_x = ((cell_x + 1 - x) if ray_x > 0 else (x - cell_x)) * delta_x
    next_y = ((cell_y + 1 - y) if ray_y > 0 else (y - cell_y)) * delta_y
    hits = []
    distance = 0.0
    while distance < FAR:
        if next_x < next_y:
            distance, side = next_x, 0
            next_x += delta_x
            cell_x += step_x
        else:
            distance, side = next_y, 1
            next_y += delta_y
            cell_y += step_y
        letter = blocks.get((cell_x, cell_y))
        if letter:
            hits.append((distance, min(next_x, next_y), letter, side))
            if BLOCKS[letter][2] >= tallest:
                break             # nothing behind a block this tall can be seen
    return hits


def draw_sky():
    screen.fill(sky_colour, (0, 0, WIDTH, HORIZON))
    screen.fill(shade(ground_colour, light), (0, HORIZON, WIDTH, HEIGHT - HORIZON))
    if stars_out:
        for direction, height in stars:
            across = (direction - facing + math.pi) % math.tau - math.pi
            if abs(across) < FIELD_OF_VIEW:
                screen.fill((255, 255, 255),
                            (WIDTH / 2 + across * PROJECTION, height, 2, 2))
    for direction, up, size, colour in PLANETS:
        across = (math.radians(direction) - facing + math.pi) % math.tau - math.pi
        if abs(across) < FIELD_OF_VIEW:
            centre = (WIDTH / 2 + math.tan(across) * PROJECTION,
                      HORIZON - math.tan(math.radians(up)) * PROJECTION)
            pygame.draw.circle(screen, colour, centre, size)


def draw_blocks():
    look_x, look_y = math.cos(facing), math.sin(facing)
    spread = math.tan(FIELD_OF_VIEW / 2)
    for left in range(0, WIDTH, COLUMN):
        camera = 2 * (left + COLUMN / 2) / WIDTH - 1
        ray_x = look_x - look_y * spread * camera
        ray_y = look_y + look_x * spread * camera
        # far blocks first, so nearer ones are drawn over them
        for enter, leave, letter, side in reversed(cast(ray_x, ray_y)):
            _name, colour, high = BLOCKS[letter]
            colour = shade(colour, light)
            enter = max(enter, 0.05)
            haze = min(0.75, enter / FAR)
            # the top of the stack, when your eyes are above it
            if high < EYE:
                near = screen_y(high, enter)
                far = screen_y(high, max(leave, enter + 0.01))
                screen.fill(mix(shade(colour, 1.15), sky_colour, haze),
                            (left, int(far), COLUMN, int(near - far) + 1))
            # the side facing you, one 1 metre block at a time
            face = mix(shade(colour, 0.82 if side else 1.0), sky_colour, haze)
            edge = shade(face, 0.65)
            for level in range(high):
                low = screen_y(level, enter)
                top = screen_y(level + 1, enter)
                screen.fill(face, (left, int(top), COLUMN, int(low - top) + 1))
                screen.fill(edge, (left, int(top), COLUMN, 1))
            # the corners where one block meets the next
            hit = (y + ray_y * enter) if side == 0 else (x + ray_x * enter)
            if hit % 1.0 < 0.04 or hit % 1.0 > 0.96:
                top = screen_y(high, enter)
                screen.fill(edge, (left, int(top), COLUMN,
                                   int(screen_y(0, enter) - top) + 1))


def draw_hands():
    for side in (-1, 1):
        middle = WIDTH // 2 + side * 150
        arm = pygame.Rect(0, 0, 70, 120)
        arm.midtop = (middle + side * 20, HEIGHT - 70)
        pygame.draw.rect(screen, shade(HANDS, 0.85), arm, border_radius=18)
        fist = pygame.Rect(0, 0, 86, 70)
        fist.center = (middle, HEIGHT - 60)
        pygame.draw.rect(screen, HANDS, fist, border_radius=24)


def walk_to(new_x, new_y):
    """Move there unless a block is in the way. A block to collect is picked up."""
    global x, y, score
    for spot in ((int(new_x), int(y)), (int(x), int(new_y))):
        letter = blocks.get(spot)
        if letter and BLOCKS[letter][0] == COLLECT:
            del blocks[spot]
            score += 1
    if (int(new_x), int(y)) not in blocks:
        x = new_x
    if (int(x), int(new_y)) not in blocks:
        y = new_y


running = True
while running:
    seconds = clock.tick(60) / 1000
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    keys = pygame.key.get_pressed()
    if keys[pygame.K_a] or keys[pygame.K_LEFT]:
        facing -= TURN_SPEED * seconds
    if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
        facing += TURN_SPEED * seconds
    forward = 0
    if keys[pygame.K_w] or keys[pygame.K_UP]:
        forward += 1
    if keys[pygame.K_s] or keys[pygame.K_DOWN]:
        forward -= 1
    if forward:
        step = forward * WALK_SPEED * seconds
        walk_to(x + math.cos(facing) * step, y + math.sin(facing) * step)

    draw_sky()
    draw_blocks()
    if SHOW_HANDS:
        draw_hands()
    if to_find:
        words = (f"{COLLECT.title()}: {score} of {to_find}" if score < to_find
                 else f"You found all the {COLLECT}!")
        screen.blit(font.render(words, True, (255, 255, 255)), (16, 14))
    pygame.display.flip()

pygame.quit()
