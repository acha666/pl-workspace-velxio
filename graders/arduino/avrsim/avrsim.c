/*
 * avrsim: run Arduino Uno firmware in simavr under a line protocol, so the
 * caller can drive inputs in response to what the program does.
 *
 *   avrsim FIRMWARE.elf
 *
 * Commands on stdin, one per line (times are CPU cycles at 16 MHz):
 *   limit pins N          stop once the program has changed its pins N times
 *   limit serial N        stop once the program has transmitted N serial bytes
 *   set PIN LEVEL         drive digital pin 0-19 from outside (0 or 1)
 *   release PIN           stop driving PIN from outside: it reads HIGH under
 *                         the program's pull-up and LOW without one
 *   analog CHANNEL VALUE  make analogRead() on A0-A5 return VALUE (0-1023)
 *   send HEX              queue bytes for the program's Serial, delivered at
 *                         one byte per millisecond
 *   run CYCLE             run until CYCLE
 *   run CYCLE until KIND KEY
 *                         ... or until the program produces a record of KIND:
 *                         P with the pin number as KEY, or S (KEY is ignored)
 *
 * Replies on stdout, one record per line:
 *   P CYCLE PIN STATE     pin driven by the program: H, L; or input: I, U (pull-up)
 *   S CYCLE BYTE          byte transmitted on Serial
 *   T CYCLE REASON        the run ended: reached, watched, done, crashed,
 *                         pin-limit or serial-limit
 *
 * The initial state of every pin is reported before the first reply. Once the
 * program is done, crashed or over a limit, every later run ends at once with
 * the same reason. Simulation uses simulated time only, so a firmware and
 * command sequence always produce the same replies; the caller enforces any
 * wall-clock limit. Protocol errors go to stderr with exit status 2.
 */

#include <ctype.h>
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
#define CYCLES_PER_MS (F_CPU / 1000)
#define VCC_MV 5000
#define NUM_PINS 20
#define LINE_MAX 1024
#define SEND_QUEUE 65536

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
static char pin_state[NUM_PINS];
static unsigned long pin_changes, serial_bytes;
static unsigned long pin_limit = 200000, serial_limit = 65536;
static const char *final_reason;  /* done, crashed or a limit: sticky */
static const char *watch_reason;  /* "watched": a record of the watched kind ended the run */
static char watch_kind;           /* 'P' or 'S' while a run watches, else 0 */
static int watch_key = -1;        /* the pin, for 'P' */
static uint8_t send_queue[SEND_QUEUE];
static unsigned send_head, send_tail;
static int send_timer_active;

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

/* -- What the program does ------------------------------------------------- */

static void record_port(port_t *p)
{
	if (final_reason)
		return;
	for (int bit = 0; bit < p->count; bit++) {
		int pin = p->first_pin + bit;
		int high = (p->port >> bit) & 1;
		char state = (p->ddr >> bit) & 1 ? (high ? 'H' : 'L') : (high ? 'U' : 'I');
		if (state == pin_state[pin])
			continue;
		pin_state[pin] = state;
		printf("P %llu %d %c\n", (unsigned long long)avr->cycle, pin, state);
		pin_changes++;
		if (watch_kind == 'P' && pin == watch_key)
			watch_reason = "watched";
	}
	if (pin_changes >= pin_limit)
		final_reason = "pin-limit";
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
	if (final_reason)
		return;
	printf("S %llu %u\n", (unsigned long long)avr->cycle, value & 0xff);
	if (++serial_bytes >= serial_limit)
		final_reason = "serial-limit";
	if (watch_kind == 'S')
		watch_reason = "watched";
}

/* -- What the outside world does ------------------------------------------- */

static void set_digital(int pin, int level)
{
	int bit;
	port_t *p = port_of_pin(pin, &bit);
	/* An external driver overrides the internal pull-up, as on real hardware. */
	p->external_mask |= 1 << bit;
	p->external_value = (p->external_value & ~(1 << bit)) | (level << bit);
	avr_ioport_external_t external = {
		.name = p->name, .mask = p->external_mask, .value = p->external_value,
	};
	avr_ioctl(avr, AVR_IOCTL_IOPORT_SET_EXTERNAL(p->name), &external);
	avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(p->name), bit), level);
}

static void release_digital(int pin)
{
	int bit;
	port_t *p = port_of_pin(pin, &bit);
	p->external_mask &= ~(1 << bit);
	avr_ioport_external_t external = {
		.name = p->name, .mask = p->external_mask, .value = p->external_value,
	};
	avr_ioctl(avr, AVR_IOCTL_IOPORT_SET_EXTERNAL(p->name), &external);
	/* simavr only re-raises the pins it still pulls, so settle this one: an
	   input reads its pull-up, the PORT bit, or LOW; an output reads PORT too. */
	avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(p->name), bit),
			(p->port >> bit) & 1);
}

static void set_analog(int channel, int value)
{
	/* simavr converts millivolts with mV * 1023 / AVCC; round up so
	   analogRead() returns exactly the requested value. */
	uint32_t mv = (value * VCC_MV + 1022) / 1023;
	avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + channel), mv);
}

static avr_cycle_count_t feed_serial(avr_t *a, avr_cycle_count_t when, void *param)
{
	(void)param;
	if (send_head == send_tail) {
		send_timer_active = 0;
		return 0;
	}
	uint8_t byte = send_queue[send_head];
	send_head = (send_head + 1) % SEND_QUEUE;
	avr_raise_irq(avr_io_getirq(a, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT), byte);
	if (send_head == send_tail) {
		send_timer_active = 0;
		return 0;
	}
	return when + CYCLES_PER_MS;
}

static int hex_digit(int c)
{
	return isdigit(c) ? c - '0' : tolower(c) - 'a' + 10;
}

static void queue_serial(const char *hex, int line_no)
{
	for (; *hex && !isspace((unsigned char)*hex); hex += 2) {
		if (!isxdigit((unsigned char)hex[0]) || !isxdigit((unsigned char)hex[1]))
			fail("line %d: send takes hex bytes", line_no);
		unsigned next = (send_tail + 1) % SEND_QUEUE;
		if (next == send_head)
			fail("line %d: serial input queue full", line_no);
		send_queue[send_tail] = (hex_digit(hex[0]) << 4) | hex_digit(hex[1]);
		send_tail = next;
	}
	if (!send_timer_active && send_head != send_tail) {
		send_timer_active = 1;
		avr_cycle_timer_register(avr, CYCLES_PER_MS, feed_serial, NULL);
	}
}

/* -- Running ----------------------------------------------------------------- */

static void run(unsigned long long target, char kind, int key)
{
	watch_kind = kind;
	watch_key = key;
	watch_reason = NULL;
	while (!final_reason && !watch_reason && avr->cycle < target) {
		int state = avr_run(avr);
		if (state == cpu_Done)
			final_reason = "done";
		else if (state == cpu_Crashed)
			final_reason = "crashed";
	}
	unsigned long long cycle = avr->cycle;
	const char *reason = final_reason ? final_reason : watch_reason;
	if (!reason) {
		reason = "reached";
		cycle = target;
	}
	printf("T %llu %s\n", cycle, reason);
	fflush(stdout);
	watch_kind = 0;
	watch_key = -1;
}

static void command(const char *line, int line_no)
{
	char word[32], arg[32];
	unsigned long long cycle;
	unsigned long n;
	int a, b;
	if (sscanf(line, "%31s", word) != 1)
		return;
	if (!strcmp(word, "run")) {
		char kind[32] = "";
		int fields = sscanf(line, "%*s %llu %31s %31s %d", &cycle, arg, kind, &a);
		if (fields == 1)
			run(cycle, 0, -1);
		else if (fields == 4 && !strcmp(arg, "until") && !strcmp(kind, "P")
				&& a >= 0 && a < NUM_PINS)
			run(cycle, 'P', a);
		else if (fields == 4 && !strcmp(arg, "until") && !strcmp(kind, "S"))
			run(cycle, 'S', -1);
		else
			fail("line %d: cannot parse run command", line_no);
	} else if (!strcmp(word, "limit")) {
		if (sscanf(line, "%*s %31s %lu", arg, &n) != 2)
			fail("line %d: cannot parse limit", line_no);
		if (!strcmp(arg, "pins"))
			pin_limit = n;
		else if (!strcmp(arg, "serial"))
			serial_limit = n;
		else
			fail("line %d: unknown limit", line_no);
	} else if (!strcmp(word, "set")) {
		if (sscanf(line, "%*s %d %d", &a, &b) != 2 || a < 0 || a >= NUM_PINS || (b != 0 && b != 1))
			fail("line %d: invalid set command", line_no);
		set_digital(a, b);
	} else if (!strcmp(word, "release")) {
		if (sscanf(line, "%*s %d", &a) != 1 || a < 0 || a >= NUM_PINS)
			fail("line %d: invalid release command", line_no);
		release_digital(a);
	} else if (!strcmp(word, "analog")) {
		if (sscanf(line, "%*s %d %d", &a, &b) != 2 || a < 0 || a > 5 || b < 0 || b > 1023)
			fail("line %d: invalid analog command", line_no);
		set_analog(a, b);
	} else if (!strcmp(word, "send")) {
		const char *hex = strstr(line, word) + strlen(word);
		while (isspace((unsigned char)*hex))
			hex++;
		queue_serial(hex, line_no);
	} else {
		fail("line %d: unknown command '%s'", line_no, word);
	}
}

int main(int argc, char *argv[])
{
	if (argc != 2)
		fail("usage: avrsim FIRMWARE.elf");
	avr_global_logger_set(quiet_logger);

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

	static char out_buffer[1 << 16];
	setvbuf(stdout, out_buffer, _IOFBF, sizeof(out_buffer));
	for (int pin = 0; pin < NUM_PINS; pin++) {
		pin_state[pin] = 'I';
		printf("P 0 %d I\n", pin);
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

	char line[LINE_MAX];
	for (int line_no = 1; fgets(line, sizeof(line), stdin); line_no++) {
		if (!strchr(line, '\n') && !feof(stdin))
			fail("line %d: too long", line_no);
		command(line, line_no);
	}
	return 0;
}
