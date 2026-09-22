const int segmentPins[7] = {2, 3, 4, 5, 6, 7, 8};
const byte digitPatterns[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66,
                                0x6d, 0x7d, 0x07, 0x7f, 0x6f};

void showDigit(int digit) {
  for (int segment = 0; segment < 7; segment++) {
    digitalWrite(segmentPins[segment], bitRead(digitPatterns[digit], segment));
  }
}

void setup() {
  for (int segment = 0; segment < 7; segment++) {
    pinMode(segmentPins[segment], OUTPUT);
  }
}

void loop() {
  for (int digit = 0; digit < 10; digit++) {
    showDigit(digit);
    delay(1000);
  }
}
