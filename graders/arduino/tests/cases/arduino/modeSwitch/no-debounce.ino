// Mode switch: a debounced button cycles modes 0-3 shown on LEDs; a long press,
// Serial commands and a potentiometer are handled without delay().
const int buttonPin = 2;
const int ledPins[3] = {13, 9, 7};
const int potPin = A0;
const unsigned long debounceMs = 30;
const unsigned long holdMs = 1000;

int mode = 0;
int rawLevel = HIGH;      // the level last read
int stableLevel = HIGH;   // the debounced level; LOW while pressed
unsigned long changedAt = 0;
unsigned long pressedAt = 0;
bool held = false;        // the current press already counted as a long press
unsigned long toggledAt = 0;
bool blinkOn = false;
char line[16];
int lineLength = 0;

void setMode(int newMode) {
  mode = newMode;
  for (int i = 0; i < 3; i++) digitalWrite(ledPins[i], mode == i + 1);
  blinkOn = mode == 3;
  toggledAt = millis();
  Serial.print("mode ");
  Serial.println(mode);
}

void setup() {
  pinMode(buttonPin, INPUT_PULLUP);
  for (int i = 0; i < 3; i++) pinMode(ledPins[i], OUTPUT);
  Serial.begin(9600);
  Serial.println("ready");
}

void readButton(unsigned long now) {
  int level = digitalRead(buttonPin);
  if (level != stableLevel) {
    stableLevel = level;
    if (stableLevel == LOW) {
      pressedAt = now;
      held = false;
    } else if (!held) {
      setMode((mode + 1) % 4);
    }
  }
  if (stableLevel == LOW && !held && now - pressedAt >= holdMs) {
    held = true;
    setMode(0);
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      line[lineLength] = '\0';
      if (strncmp(line, "mode ", 5) == 0 && line[5] >= '0' && line[5] <= '3') setMode(line[5] - '0');
      lineLength = 0;
    } else if (lineLength < (int)sizeof(line) - 1) {
      line[lineLength++] = c;
    }
  }
}

void blink(unsigned long now) {
  if (mode != 3) return;
  unsigned long period = map(analogRead(potPin), 0, 1023, 100, 1000);
  if (now - toggledAt >= period / 2) {
    toggledAt = now;
    blinkOn = !blinkOn;
    digitalWrite(ledPins[2], blinkOn);
  }
}

void loop() {
  unsigned long now = millis();
  readButton(now);
  readSerial();
  blink(now);
}
