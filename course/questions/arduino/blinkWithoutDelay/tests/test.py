"""Blink pin 13 with millis(): on for 500 ms, then off for 500 ms."""

import arduinograder as ag
from arduinograder.extras import no_calls

LED = 13
HALF_PERIOD_MS = 500
TOLERANCE_MS = 20

gates = [no_calls("delay")]
scenario = ag.Scenario(duration_ms=2600)


@ag.points(1)
@ag.name("Pin 13 is an output")
def test_output(trace):
    assert trace.pin(LED).at(50).is_output, (
        "Pin 13 is not an output. Call pinMode(LED_BUILTIN, OUTPUT) in setup()."
    )


@ag.points(3)
@ag.name("The LED alternates every 500 ms, starting on")
def test_blink(trace, check):
    led = trace.pin(LED)
    for start in range(0, 2500, HALF_PERIOD_MS):
        middle = start + HALF_PERIOD_MS // 2
        expected = start // HALF_PERIOD_MS % 2 == 0
        check(
            led.at(middle).is_high == expected,
            f"At {middle} ms the LED should be {'on' if expected else 'off'}.",
        )
    edges = led.edges(start_ms=100)
    check(
        edges.match(range(HALF_PERIOD_MS, 2600, HALF_PERIOD_MS), tolerance_ms=TOLERANCE_MS),
        f"The LED should switch every 500 ms (within 20 ms). It switched at: {edges.describe()}.",
    )


if __name__ == "__main__":
    ag.main()
