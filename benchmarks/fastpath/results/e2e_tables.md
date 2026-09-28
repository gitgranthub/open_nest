
### All project types  (44 conversations, 50 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 47/50 |
| Working result | 14/44 | 33/44 |
| Gary truthful (blind-graded cases) | 12/23 | 20/23 |
| Avg latency per message | 29.4 s | 9.5 s |
| Median latency | 20.1 s | 3.2 s |
| Generated tokens | 27,147 | 7,407 |
| Model calls | 249 | 60 |
| Edits landed / attempted | 53/132 | 94/113 |
| Tool refusals (retries) | 89 | 20 |
| Correct refusals (no pin given) | 1/2 | 1/2 |
| False fast-path routes | n/a | 2/34 |
| Routes | none 50 | guide 5, normal 11, recipe 34 |

### Games -- Phase 12's own requests  (18 conversations, 20 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 20/20 |
| Working result | 4/18 | 17/18 |
| Gary truthful (blind-graded cases) | 3/11 | 10/10 |
| Avg latency per message | 30.1 s | 3.9 s |
| Median latency | 20.7 s | 3.1 s |
| Generated tokens | 12,289 | 324 |
| Model calls | 109 | 5 |
| Edits landed / attempted | 26/62 | 57/58 |
| Tool refusals (retries) | 39 | 1 |
| Correct refusals (no pin given) | -- | -- |
| False fast-path routes | n/a | 0/18 |
| Routes | none 20 | guide 2, recipe 18 |

### games  (22 conversations, 28 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 26/28 |
| Working result | 5/22 | 19/22 |
| Gary truthful (blind-graded cases) | 5/14 | 13/13 |
| Avg latency per message | 27.9 s | 5.1 s |
| Median latency | 20.2 s | 3.1 s |
| Generated tokens | 15,533 | 1,267 |
| Model calls | 139 | 14 |
| Edits landed / attempted | 36/74 | 68/70 |
| Tool refusals (retries) | 42 | 3 |
| Correct refusals (no pin given) | -- | -- |
| False fast-path routes | n/a | 1/24 |
| Routes | none 28 | guide 2, normal 2, recipe 24 |

### website  (6 conversations, 6 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 6/6 |
| Working result | 2/6 | 4/6 |
| Gary truthful (blind-graded cases) | 1/2 | 1/2 |
| Avg latency per message | 20.0 s | 8.4 s |
| Median latency | 23.1 s | 1.5 s |
| Generated tokens | 2,873 | 1,344 |
| Model calls | 24 | 8 |
| Edits landed / attempted | 7/17 | 10/16 |
| Tool refusals (retries) | 10 | 6 |
| Correct refusals (no pin given) | -- | -- |
| False fast-path routes | n/a | 0/4 |
| Routes | none 6 | normal 2, recipe 4 |

### research  (6 conversations, 6 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 6/6 |
| Working result | 1/6 | 3/6 |
| Gary truthful (blind-graded cases) | 2/3 | 1/2 |
| Avg latency per message | 73.2 s | 35.0 s |
| Median latency | 102.8 s | 25.8 s |
| Generated tokens | 6,297 | 3,587 |
| Model calls | 53 | 23 |
| Edits landed / attempted | 1/26 | 4/13 |
| Tool refusals (retries) | 30 | 9 |
| Correct refusals (no pin given) | -- | -- |
| False fast-path routes | n/a | 0/2 |
| Routes | none 6 | guide 2, normal 2, recipe 2 |

### arduino  (5 conversations, 5 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 5/5 |
| Working result | 1/5 | 2/5 |
| Gary truthful (blind-graded cases) | 2/2 | 3/4 |
| Avg latency per message | 14.1 s | 10.1 s |
| Median latency | 12.4 s | 8.6 s |
| Generated tokens | 1,450 | 1,016 |
| Model calls | 18 | 11 |
| Edits landed / attempted | 5/9 | 9/11 |
| Tool refusals (retries) | 4 | 2 |
| Correct refusals (no pin given) | 0/1 | 0/1 |
| False fast-path routes | n/a | 1/2 |
| Routes | none 5 | normal 3, recipe 2 |

### raspberry_pi  (5 conversations, 5 messages per arm)

| Metric | Current Path | Fast Path |
|---|---:|---:|
| Intent correct (classifier) | n/a | 4/5 |
| Working result | 5/5 | 5/5 |
| Gary truthful (blind-graded cases) | 2/2 | 2/2 |
| Avg latency per message | 11.5 s | 4.8 s |
| Median latency | 13.7 s | 3.7 s |
| Generated tokens | 994 | 193 |
| Model calls | 15 | 4 |
| Edits landed / attempted | 4/6 | 3/3 |
| Tool refusals (retries) | 3 | 0 |
| Correct refusals (no pin given) | 1/1 | 1/1 |
| False fast-path routes | n/a | 0/2 |
| Routes | none 5 | guide 1, normal 2, recipe 2 |

### Per conversation

| id | messages | current: working, s, tokens | fast: route, working, s, tokens |
|---|---|---|---|
| A1 | make it blink faster | False, 12 s, 147 | recipe, True, 3 s, 0 |
| A2 | i plugged a red led into pin 9, make t | True, 24 s, 276 | normal, True, 23 s, 276 |
| A3 | add a button on pin 2 that turns the l | False, 12 s, 287 | recipe, False, 2 s, 0 |
| A4 | add another LED | False, 9 s, 270 | normal, False, 9 s, 270 |
| A5 | make it like a spooky haunted house li | False, 14 s, 470 | normal, False, 14 s, 470 |
| G1 | Make a game where a spaceship moves ar | False, 20 s, 174 | recipe, True, 4 s, 0 |
| G2 | Make a game where a spaceship moves ar / Make the asteroids move faster. | False, 46 s, 549 | recipe/recipe, True, 6 s, 0 |
| G3 | Add a ball that bounces around the scr | False, 62 s, 1224 | recipe, True, 3 s, 0 |
| G4 | Make the square fall down the screen a | False, 7 s, 143 | guide, False, 12 s, 214 |
| G5 | Add a second square that slides left a | False, 42 s, 1289 | recipe, True, 3 s, 0 |
| G6 | Make a game where you catch falling bl | False, 54 s, 1327 | recipe, True, 2 s, 0 |
| G7 | Add an enemy that chases the player. | False, 40 s, 873 | recipe, True, 3 s, 0 |
| G8 | Add a coin that you can collect for po | False, 44 s, 1132 | recipe, True, 3 s, 0 |
| G9 | Add stars that drift down the backgrou | False, 7 s, 121 | recipe, True, 3 s, 0 |
| G10 | Add a score that goes up every second. | False, 16 s, 180 | recipe, True, 3 s, 0 |
| G11 | Make the player bigger. | True, 21 s, 287 | recipe, True, 3 s, 0 |
| G12 | Change the background colour to dark b | True, 16 s, 161 | recipe, True, 3 s, 0 |
| G13 | Call my game Space Rocks. | False, 16 s, 146 | recipe, True, 3 s, 0 |
| G14 | Make the player move faster. | True, 20 s, 252 | recipe, True, 3 s, 0 |
| G15 | Change the background to dark green. | False, 16 s, 152 | recipe, True, 3 s, 0 |
| G16 | Add a score in the top left corner. | False, 36 s, 497 | recipe, True, 3 s, 0 |
| G17 | Make the player bigger. / Now make it blue. | True, 36 s, 441 | recipe/guide, True, 14 s, 110 |
| G18 | Use this picture for my spaceship. | False, 105 s, 3341 | recipe, True, 4 s, 0 |
| G19 | Make this feel more mysterious. | False, 6 s, 59 | normal, False, 6 s, 59 |
| G20 | Make the enemies scared of the player. | False, 65 s, 2247 | normal, False, 39 s, 884 |
| G21 | Make a game where a spaceship moves ar / Make the asteroids zigzag instead of g / Make the asteroids move faster. | False, 57 s, 414 | recipe/recipe/recipe, True, 9 s, 0 |
| G22 | Make the player move faster. / Even faster. / Now make it bigger. | True, 50 s, 524 | recipe/recipe/recipe, True, 11 s, 0 |
| P1 | make it blink 10 times | True, 23 s, 521 | recipe, True, 7 s, 0 |
| P2 | blink faster pls | True, 15 s, 204 | recipe, True, 2 s, 0 |
| P3 | change the pin to 18 thats where i put | True, 14 s, 146 | guide, True, 7 s, 70 |
| P4 | add a button | True, 3 s, 79 | normal, True, 4 s, 79 |
| P5 | make it more magical | True, 3 s, 44 | normal, True, 3 s, 44 |
| R1 | Graph this and tell me what changed th | False, 4 s, 75 | normal, False, 5 s, 75 |
| R2 | make a line graph of how tall each pla | False, 103 s, 1549 | recipe, True, 7 s, 0 |
| R3 | work out the average height for each p | False, 109 s, 1464 | recipe, True, 7 s, 0 |
| R4 | i want to see if more water = taller p | False, 122 s, 1776 | guide, False, 117 s, 2131 |
| R5 | what's in my data? | True, 49 s, 669 | normal, True, 48 s, 669 |
| R6 | make it look professional like a real  | False, 53 s, 764 | guide, False, 26 s, 712 |
| W1 | change the title to "Maya's Dog Club" | True, 14 s, 143 | recipe, True, 1 s, 0 |
| W2 | make the background dark blue | False, 10 s, 136 | recipe, True, 0 s, 0 |
| W3 | add a section about my favourite films | False, 23 s, 724 | normal, False, 23 s, 724 |
| W4 | add a button that counts how many time | True, 39 s, 1077 | recipe, True, 1 s, 0 |
| W5 | the words are too small make them bigg | False, 10 s, 173 | recipe, True, 1 s, 0 |
| W6 | make it feel like summer | False, 24 s, 620 | normal, False, 24 s, 620 |
