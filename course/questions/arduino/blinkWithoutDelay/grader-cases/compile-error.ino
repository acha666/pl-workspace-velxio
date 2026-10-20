const int ledPin = LED_BUILTIN;
const unsigned long HALF_PERIOD_MS = 500;

unsigned long lastSwitch = 0;
bool ledOn = true;

void setup() {
  pinMode(ledPin, OUTPUT);
  digitalWrite(ledPin, HIGH);
}

void loop() {
  if (millis() - lastSwitch >= HALF_PERIOD_MS) {
    lastSwitch += HALF_PERIOD_MS;
    ledOn = !ledOn
    digitalWrite(ledPin, ledOn ? HIGH : LOW);
  }
}
