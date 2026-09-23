"""A tiny game to build on. Change the numbers and see what happens."""

import pygame

# Things you can change
WIDTH = 640
HEIGHT = 480
PLAYER_SPEED = 5
PLAYER_SIZE = 40
BACKGROUND = (18, 22, 34)
PLAYER_COLOUR = (214, 142, 62)

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("My Game")
clock = pygame.time.Clock()

player = pygame.Rect(WIDTH // 2, HEIGHT // 2, PLAYER_SIZE, PLAYER_SIZE)

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

    screen.fill(BACKGROUND)
    pygame.draw.rect(screen, PLAYER_COLOUR, player)
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
