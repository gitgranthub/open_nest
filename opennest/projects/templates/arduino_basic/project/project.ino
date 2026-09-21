// Blink the light that is already on your board.
//
// BOARD: whichever one you picked in Open Nest. This sketch only uses LED_BUILTIN,
// which every Arduino board defines as its own onboard LED, so it works without
// anyone having to guess a pin number.
//
// When you add your own parts -- a different LED, a button, a sensor -- put the pin
// numbers here as named constants and write them down in wiring.md too. Never leave a
// bare number in the middle of the code: in six weeks you will not remember what pin 7
// was for.

const int LED_PIN = LED_BUILTIN;

const unsigned long ON_MILLISECONDS = 500;
const unsigned long OFF_MILLISECONDS = 500;

void setup() {
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_PIN, HIGH);
  delay(ON_MILLISECONDS);
  digitalWrite(LED_PIN, LOW);
  delay(OFF_MILLISECONDS);
}
