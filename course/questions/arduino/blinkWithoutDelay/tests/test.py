"""Blink pin 13 with millis(): on for 500 ms, then off for 500 ms."""

import arduinograder as ag
from arduinograder.extras import forbid_calls

LED = 13
HALF_PERIOD_MS = 500
TOLERANCE_MS = 20


class QuestionGrader(ag.ArduinoGrader):
    def tests(self):
        forbid_calls(self.source, "delay")
        firmware = self.compile()
        trace = self.simulate(firmware, ag.Scenario(duration_ms=2600))

        with self.test("Pin 13 is an output", points=1) as test:
            test.expect(
                trace.state(LED, at_ms=50) in ("HIGH", "LOW"),
                "Pin 13 is not an output. Call pinMode(LED_BUILTIN, OUTPUT) in setup().",
            )

        with self.test(
            "The LED alternates every 500 ms, starting on", points=3
        ) as test:
            for start in range(0, 2500, HALF_PERIOD_MS):
                middle = start + HALF_PERIOD_MS // 2
                expected = 1 if start // HALF_PERIOD_MS % 2 == 0 else 0
                test.expect(
                    trace.level(LED, at_ms=middle) == expected,
                    f"At {middle} ms the LED should be {'on' if expected else 'off'}.",
                )
            switches = [time for time, _ in trace.changes(LED, start_ms=100)]
            expected_switches = range(HALF_PERIOD_MS, 2600, HALF_PERIOD_MS)
            test.expect(
                len(switches) == len(expected_switches)
                and all(
                    abs(actual - expected) <= TOLERANCE_MS
                    for actual, expected in zip(switches, expected_switches)
                ),
                "The LED should switch every 500 ms (within 20 ms). It switched at: "
                + (", ".join(f"{time:.0f} ms" for time in switches) or "never")
                + ".",
            )


if __name__ == "__main__":
    QuestionGrader().start()
