"""A tiny game to build on. Change the numbers and see what happens."""

import pygame

from scene import Coin, Picture, Road, Scene, Sky, Vehicle
import random

# Things you can change
WIDTH = 640
HEIGHT = 480
PLAYER_SPEED = 5
PLAYER_SIZE = 85
BACKGROUND = (60, 130, 230)
COIN_COUNT = 5
COIN_SIZE = 23
COIN_COLOUR = (240, 200, 60)
SCORE_COLOUR = (240, 240, 240)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("My Game")
clock = pygame.time.Clock()

player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)

# The scene: everything the game shows, drawn back to front by scene.draw().
scene = Scene(screen)
sky = scene.add("sky", Sky(BACKGROUND), size=(640, 480), at=(0, 0), layer="background")
road = scene.add("road", Road("gray"), size=(640, 30), at=(0, 450), layer="scenery")
scene.add("player", Picture("assets/eagle.png"), rect=player, scale=1.5, layer="things")
car = scene.add("car", Vehicle(),
                size=(80, 40), at=(600, 300), moves=(-3, 0), layer="things")

coins = []
for i in range(COIN_COUNT):
    coin_x = random.randint(0, WIDTH - COIN_SIZE)
    coin_y = random.randint(0, HEIGHT // 3)
    coins.append(pygame.Rect(coin_x, coin_y, COIN_SIZE, COIN_SIZE))
scene.add("coins", Coin(COIN_COLOUR, size=(23, 23)), rects=coins, layer="things")
score = 0
font = pygame.font.Font(None, 36)

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        player.x -= PLAYER_SPEED
    if keys[pygame.K_RIGHT]:
        player.x += PLAYER_SPEED
    if keys[pygame.K_UP]:
        player.y -= PLAYER_SPEED
    if keys[pygame.K_DOWN]:
        player.y += PLAYER_SPEED

    player.clamp_ip(screen.get_rect())

    scene.update()
    # Open Nest: touching car sends the player back to the start.
    if scene.touching(player, "car"):
        player.topleft = (WIDTH // 2, HEIGHT // 2)
    for coin in coins:
        if player.colliderect(coin):
            score += 1
            coin.x = random.randint(0, WIDTH - COIN_SIZE)
            coin.y = random.randint(0, HEIGHT - COIN_SIZE)

    screen.fill(BACKGROUND)
    scene.draw()
    screen.blit(font.render(f"Score: {score}", True, SCORE_COLOUR), (10, 10))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
