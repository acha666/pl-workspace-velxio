/*
 * avrsim: run Arduino Uno firmware in simavr on a scripted input schedule and
 * record what the program does.
 *
 *   avrsim FIRMWARE.elf SCENARIO TRACE
 *
 * SCENARIO lines (times in CPU cycles at 16 MHz, events sorted by time):
 *   duration CYCLES
 *   limit pins N          stop after N recorded pin changes
 *   limit serial N        stop after N transmitted serial bytes
 *   digital CYCLE PIN LEVEL       drive digital pin 0-19 from outside (0 or 1)
 *   analog CYCLE CHANNEL VALUE    set analog input A0-A5 to an analogRead() value
 *
 * TRACE lines:
 *   P CYCLE PIN STATE     pin driven by the program: H, L; or input: I, U (pull-up)
 *   S CYCLE BYTE          byte transmitted on Serial
 *   E CYCLE REASON        end, done, crashed, pin-limit or serial-limit
 *
 * Simulation uses simulated time only, so a given firmware and scenario always
 * produce the same trace. The caller enforces any wall-clock limit.
 */

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "avr_adc.h"
#include "avr_ioport.h"
#include "avr_uart.h"
#include "sim_avr.h"
#include "sim_elf.h"
#include "sim_irq.h"
#include "sim_cycle_timers.h"

#define F_CPU 16000000UL
#define VCC_MV 5000
#define NUM_PINS 20
#define MAX_EVENTS 100000

typedef struct {
	avr_cycle_count_t cycle;
	int analog;
	int pin;
	int value;
} event_t;

typedef struct {
	char name;
	int first_pin;
	int count;
	uint8_t port;
	uint8_t ddr;
	uint8_t external_mask;
	uint8_t external_value;
} port_t;

/* Uno pin numbering: D0-D7 on PORTD, D8-D13 on PORTB, A0-A5 (D14-D19) on PORTC. */
static port_t ports[] = {
	{ .name = 'D', .first_pin = 0, .count = 8 },
	{ .name = 'B', .first_pin = 8, .count = 6 },
	{ .name = 'C', .first_pin = 14, .count = 6 },
};
#define NUM_PORTS (sizeof(ports) / sizeof(ports[0]))

static avr_t *avr;
static FILE *trace;
static event_t events[MAX_EVENTS];
static int num_events, next_event;
static char pin_state[NUM_PINS];
static unsigned long pin_changes, serial_bytes;
static unsigned long pin_limit = 200000, serial_limit = 65536;
static int stop_requested;

static void fail(const char *format, ...)
{
	va_list ap;
	va_start(ap, format);
	fputs("avrsim: ", stderr);
	vfprintf(stderr, format, ap);
	fputc('\n', stderr);
	va_end(ap);
	exit(2);
}

static void quiet_logger(avr_t *a, const int level, const char *format, va_list ap)
{
	(void)a; (void)level; (void)format; (void)ap;
}

static port_t *port_of_pin(int pin, int *bit)
{
	for (size_t i = 0; i < NUM_PORTS; i++) {
		if (pin >= ports[i].first_pin && pin < ports[i].first_pin + ports[i].count) {
			*bit = pin - ports[i].first_pin;
			return &ports[i];
		}
	}
	return NULL;
}

static void record_port(port_t *p)
{
	if (stop_requested)
		return;
	for (int bit = 0; bit < p->count; bit++) {
		int pin = p->first_pin + bit;
		int high = (p->port >> bit) & 1;
		char state = (p->ddr >> bit) & 1 ? (high ? 'H' : 'L') : (high ? 'U' : 'I');
		if (state == pin_state[pin])
			continue;
		pin_state[pin] = state;
		fprintf(trace, "P %llu %d %c\n", (unsigned long long)avr->cycle, pin, state);
		if (++pin_changes >= pin_limit) {
			stop_requested = 1;
			return;
		}
	}
}

static void port_written(struct avr_irq_t *irq, uint32_t value, void *param)
{
	(void)irq;
	port_t *p = param;
	p->port = value;
	record_port(p);
}

static void ddr_written(struct avr_irq_t *irq, uint32_t value, void *param)
{
	(void)irq;
	port_t *p = param;
	p->ddr = value;
	record_port(p);
}

static void serial_output(struct avr_irq_t *irq, uint32_t value, void *param)
{
	(void)irq; (void)param;
	if (stop_requested)
		return;
	fprintf(trace, "S %llu %u\n", (unsigned long long)avr->cycle, value & 0xff);
	if (++serial_bytes >= serial_limit)
		stop_requested = 1;
}

static void apply(const event_t *e)
{
	if (e->analog) {
		/* simavr converts millivolts with mV * 1023 / AVCC; round up so
		   analogRead() returns exactly the requested value. */
		uint32_t mv = (e->value * VCC_MV + 1022) / 1023;
		avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + e->pin), mv);
		return;
	}
	int bit;
	port_t *p = port_of_pin(e->pin, &bit);
	/* An external driver overrides the internal pull-up, as on real hardware. */
	p->external_mask |= 1 << bit;
	p->external_value = (p->external_value & ~(1 << bit)) | (e->value << bit);
	avr_ioport_external_t external = {
		.name = p->name, .mask = p->external_mask, .value = p->external_value,
	};
	avr_ioctl(avr, AVR_IOCTL_IOPORT_SET_EXTERNAL(p->name), &external);
	avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(p->name), bit), e->value);
}

static avr_cycle_count_t apply_due_events(avr_t *a, avr_cycle_count_t when, void *param)
{
	(void)when; (void)param;
	while (next_event < num_events && events[next_event].cycle <= a->cycle)
		apply(&events[next_event++]);
	if (next_event < num_events)
		return events[next_event].cycle;
	return 0;
}

static avr_cycle_count_t read_scenario(const char *path)
{
	FILE *f = fopen(path, "r");
	if (!f)
		fail("cannot read %s", path);
	char line[256], word[32];
	unsigned long long cycle, duration = 0;
	int a, b;
	unsigned long n;
	for (int line_no = 1; fgets(line, sizeof(line), f); line_no++) {
		if (sscanf(line, "%31s", word) != 1)
			continue;
		if (!strcmp(word, "duration") && sscanf(line, "%*s %llu", &duration) == 1)
			continue;
		if (!strcmp(word, "limit") && sscanf(line, "%*s %31s %lu", word, &n) == 2) {
			if (!strcmp(word, "pins"))
				pin_limit = n;
			else if (!strcmp(word, "serial"))
				serial_limit = n;
			else
				fail("line %d: unknown limit", line_no);
			continue;
		}
		int analog = !strcmp(word, "analog");
		if ((analog || !strcmp(word, "digital")) &&
				sscanf(line, "%*s %llu %d %d", &cycle, &a, &b) == 3) {
			if (num_events == MAX_EVENTS)
				fail("too many events");
			if (num_events && cycle < events[num_events - 1].cycle)
				fail("line %d: events must be in time order", line_no);
			if (analog ? (a < 0 || a > 5 || b < 0 || b > 1023)
					: (a < 0 || a >= NUM_PINS || (b != 0 && b != 1)))
				fail("line %d: invalid %s event", line_no, word);
			events[num_events++] = (event_t){ cycle, analog, a, b };
			continue;
		}
		fail("line %d: cannot parse '%s'", line_no, word);
	}
	fclose(f);
	if (!duration)
		fail("scenario has no duration");
	return duration;
}

int main(int argc, char *argv[])
{
	if (argc != 4)
		fail("usage: avrsim FIRMWARE.elf SCENARIO TRACE");
	avr_global_logger_set(quiet_logger);
	avr_cycle_count_t duration = read_scenario(argv[2]);

	elf_firmware_t firmware;
	memset(&firmware, 0, sizeof(firmware));
	if (elf_read_firmware(argv[1], &firmware))
		fail("cannot read firmware %s", argv[1]);
	avr = avr_make_mcu_by_name("atmega328p");
	if (!avr)
		fail("simavr has no ATmega328P core");
	avr_init(avr);
	avr->frequency = F_CPU;
	avr_load_firmware(avr, &firmware);
	avr->frequency = F_CPU;
	avr->vcc = avr->avcc = avr->aref = VCC_MV;

	uint32_t flags = 0;
	avr_ioctl(avr, AVR_IOCTL_UART_GET_FLAGS('0'), &flags);
	flags &= ~AVR_UART_FLAG_STDIO;
	avr_ioctl(avr, AVR_IOCTL_UART_SET_FLAGS('0'), &flags);

	trace = fopen(argv[3], "w");
	if (!trace)
		fail("cannot write %s", argv[3]);
	for (int pin = 0; pin < NUM_PINS; pin++) {
		pin_state[pin] = 'I';
		fprintf(trace, "P 0 %d I\n", pin);
	}
	for (size_t i = 0; i < NUM_PORTS; i++) {
		port_t *p = &ports[i];
		avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(p->name),
				IOPORT_IRQ_REG_PORT), port_written, p);
		avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(p->name),
				IOPORT_IRQ_DIRECTION_ALL), ddr_written, p);
	}
	avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT),
			serial_output, NULL);

	/* Apply time-zero inputs before the first instruction, then keep a single
	   cycle timer pointed at the next pending event. Registration is relative
	   to the current cycle; the callback returns the next absolute cycle. */
	apply_due_events(avr, 0, NULL);
	if (next_event < num_events)
		avr_cycle_timer_register(avr, events[next_event].cycle - avr->cycle,
				apply_due_events, NULL);

	const char *reason = "end";
	while (avr->cycle < duration) {
		int state = avr_run(avr);
		if (state == cpu_Done) {
			reason = "done";
			break;
		}
		if (state == cpu_Crashed) {
			reason = "crashed";
			break;
		}
		if (stop_requested) {
			reason = pin_changes >= pin_limit ? "pin-limit" : "serial-limit";
			break;
		}
	}
	unsigned long long end = avr->cycle < duration || stop_requested ? avr->cycle : duration;
	fprintf(trace, "E %llu %s\n", end, reason);
	if (fclose(trace))
		fail("cannot write %s", argv[3]);
	return 0;
}
