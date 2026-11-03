"""Mode switch: a debounced button cycles modes on LEDs; a long press, Serial and a pot too."""

import arduinograder as ag
from arduinograder.extras import no_calls

BUTTON = 2
LEDS = {1: 13, 2: 9, 3: 7}
ALL_LEDS = tuple(LEDS.values())
POT = "A0"
DEBOUNCE_MS = 30
HOLD_MS = 1000
CLICK_MS = 50
TIME_BUDGET_S = 40

gates = [no_calls("delay")]
scenario = ag.Scenario(duration_ms=600).pulse(BUTTON, ag.LOW, at_ms=100, duration_ms=CLICK_MS)


def click(run):
    """Press the button to ground for a short while; the pull-up releases it."""
    run.pulse(BUTTON, ag.LOW, duration_ms=CLICK_MS)


def leds_on(run):
    """The modes whose LED is on right now."""
    return {mode for mode, pin in LEDS.items() if run.state(pin).is_high}


def period_ms(run, pin, timeout_ms):
    """The interval between the last two of the pin's next three rising edges, or None."""
    edges = [run.wait_for(pin, "HIGH", timeout_ms=timeout_ms) for _ in range(3)]
    return None if None in edges else edges[2] - edges[1]


def describe(period):
    return "no blinking" if period is None else f"{period:.0f} ms"


@ag.points(1)
@ag.name("Pin 2 uses the internal pull-up")
def test_pull_up(trace):
    assert trace.pin(BUTTON).at(50) is ag.PinState.INPUT_PULLUP, (
        "The button connects pin 2 to ground, so configure it with pinMode(2, INPUT_PULLUP)."
    )


@ag.points(2)
@ag.name("Starts in mode 0 and says 'ready'; one click enters mode 1")
def test_first_click(trace, check):
    check(trace.levels(ALL_LEDS, at_ms=90) == (0, 0, 0), "Before any click all LEDs must be off.")
    check(
        trace.levels(ALL_LEDS, at_ms=500) == (1, 0, 0),
        "After one click only LED 13 (mode 1) should be on.",
    )
    texts = [line.text for line in trace.serial.lines()]
    check(
        texts == ["ready", "mode 1"],
        f"Serial should show 'ready', then 'mode 1' after the click; it showed {texts}.",
    )
    return check.fraction


@ag.points(3)
@ag.name("Clicks are debounced and count on release")
def test_click_is_debounced(session):
    with session() as run:
        run.run_until(100)
        run.pulse(BUTTON, ag.LOW, duration_ms=10)
        run.run_for(200)
        assert not leds_on(run), (
            "A 10 ms blip is contact bounce, not a click: the mode must not change."
        )
        pressed_at = run.now_ms
        click(run)
        lit_at = run.wait_for(LEDS[1], "HIGH", timeout_ms=100)
        assert lit_at is not None, f"A {CLICK_MS} ms click should enter mode 1 and light LED 13."
        after_release = lit_at - (pressed_at + CLICK_MS)
        assert after_release >= 0, (
            "Count the click when the button is released, not when it is pressed, "
            "so that a long press can be told apart."
        )
        assert after_release <= DEBOUNCE_MS + 15, (
            f"LED 13 came on {after_release:.0f} ms after the release; act as soon as the "
            f"release has held for {DEBOUNCE_MS} ms."
        )


@ag.points(3)
@ag.name("Contact bounce does not count as extra clicks")
def test_bounce_counts_once(session):
    with session() as run:
        run.run_until(100)
        for _ in range(3):
            run.set(BUTTON, ag.LOW)
            run.run_for(2)
            run.release(BUTTON)
            run.run_for(2)
        run.set(BUTTON, ag.LOW)
        run.run_for(60)
        run.release(BUTTON)
        assert run.wait_for(LEDS[1], "HIGH", timeout_ms=100) is not None, (
            "A press that bounces for 12 ms and then holds for 60 ms is one click: "
            "it should enter mode 1."
        )
        run.run_for(200)
        assert leds_on(run) == {1}, "The bounce was counted as more clicks: the mode moved past 1."


@ag.points(3)
@ag.name("Clicks cycle through modes 1, 2, 3 and back to 0")
def test_clicks_cycle(session, check):
    with session() as run:
        run.run_until(100)
        for mode in (1, 2):
            click(run)
            check(
                run.wait_for(LEDS[mode], "HIGH", timeout_ms=100) is not None,
                f"Click {mode} should light LED {LEDS[mode]} (mode {mode}).",
            )
            run.run_for(200)
            check(
                leds_on(run) == {mode},
                f"In mode {mode} only LED {LEDS[mode]} should be on; on: {sorted(leds_on(run))}.",
            )
        click(run)
        check(
            run.wait_for(LEDS[3], "HIGH", timeout_ms=1200) is not None,
            "Click 3 should start LED 7 blinking (mode 3).",
        )
        check(not leds_on(run) & {1, 2}, "In mode 3 LEDs 13 and 9 should be off.")
        click(run)
        run.run_for(1200)
        check(not leds_on(run), "The fourth click should return to mode 0 with all LEDs off.")
    return check.fraction


@ag.points(3)
@ag.name("Holding the button for a second returns to mode 0")
def test_long_press_resets(session):
    with session() as run:
        run.run_until(100)
        click(run)
        assert run.wait_for(LEDS[1], "HIGH", timeout_ms=100) is not None, (
            "A click should enter mode 1 first."
        )
        run.run_for(200)
        run.set(BUTTON, ag.LOW)
        held_at = run.now_ms
        assert run.wait_for(LEDS[1], "LOW", timeout_ms=HOLD_MS - 100) is None, (
            f"The mode must not change before the button has been held for {HOLD_MS} ms."
        )
        off_at = run.wait_for(LEDS[1], "LOW", timeout_ms=300)
        run.release(BUTTON)
        assert off_at is not None, (
            f"Holding the button for {HOLD_MS} ms should return to mode 0 and turn LED 13 off."
        )
        assert off_at - held_at <= HOLD_MS + DEBOUNCE_MS + 20, (
            f"The reset came {off_at - held_at:.0f} ms into the hold; "
            f"it should come at {HOLD_MS} ms."
        )
        run.run_for(200)
        assert not leds_on(run), (
            "Releasing the button after the long hold must not count as a click."
        )


@ag.points(3)
@ag.name("'mode N' on Serial sets the mode, and every change is reported")
def test_serial_command(session):
    with session() as run:
        run.run_until(100)
        run.send("mode 2\n")
        assert run.wait_for(LEDS[2], "HIGH", timeout_ms=50) is not None, (
            "'mode 2' on Serial should turn on LED 9 within 50 ms of the newline."
        )
        line = run.wait_for_line(timeout_ms=50)
        assert line is not None and line.text == "mode 2", (
            f"After the change Serial should say 'mode 2', "
            f"not {(line.text if line else 'nothing')!r}."
        )
        click(run)
        line = run.wait_for_line(timeout_ms=100)
        assert line is not None and line.text == "mode 3", (
            f"A click in mode 2 should report 'mode 3', not {(line.text if line else 'nothing')!r}."
        )


@ag.points(3)
@ag.name("In mode 3 the potentiometer sets the blink period, also while running")
def test_pot_sets_blink_period(session, check):
    with session() as run:
        run.analog(POT, 1023)
        run.send("mode 3\n")
        slow = period_ms(run, LEDS[3], timeout_ms=1500)
        check(
            slow is not None and abs(slow - 1000) <= 30,
            f"At A0 = 1023 LED 7 should blink with a 1000 ms period; measured {describe(slow)}.",
        )
        run.analog(POT, 0)
        fast = period_ms(run, LEDS[3], timeout_ms=1500)
        check(
            fast is not None and abs(fast - 100) <= 10,
            f"After turning A0 to 0 the period should become 100 ms; measured {describe(fast)}.",
        )
    return check.fraction


if __name__ == "__main__":
    ag.main()
