#include <Arduino.h>
#include "icc.h"
#include "path.h"

#define MAX_V_ICC_COUNT 10
#define MAX_H_ICC_COUNT 10

#define DEFAULT_ICC_H_COUNT 10
#define DEFAULT_ICC_V_COUNT 10
#define DEFAULT_ICC_SLOWWAVE_INTERVAL 20

// #define PACEMAKER_CELL_ROW 0
// #define PACEMAKER_CELL_COL 0
// #define DEFAULT_PM_SLOWWAVE_INTERVAL 20
// #define OTHER_ICC_SLOWWAVE_INTERVAL 0
#define DEFAULT_TIME_STEP_MS 200U

static Icc iccs[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT];
static IccPath h_paths[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT - 1];
static float h_path_t1[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT - 1];
static float h_path_t2[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT - 1];
static IccPath v_paths[MAX_V_ICC_COUNT - 1][MAX_H_ICC_COUNT];
static float v_path_t1[MAX_V_ICC_COUNT - 1][MAX_H_ICC_COUNT];
static float v_path_t2[MAX_V_ICC_COUNT - 1][MAX_H_ICC_COUNT];

static int8_t icc_interval_buff[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT];
static uint16_t h_path_delay_buff[MAX_V_ICC_COUNT][MAX_H_ICC_COUNT - 1];
static uint16_t v_path_delay_buff[MAX_V_ICC_COUNT - 1][MAX_H_ICC_COUNT];

static uint32_t next_step_ms = 0U;
static uint32_t sample_index = 0U;
static const uint8_t kPacketHeader[2] = {0xAA, 0x55};

uint8_t v_count = DEFAULT_ICC_V_COUNT;
uint8_t h_count = DEFAULT_ICC_H_COUNT;
uint32_t time_step_ms = DEFAULT_TIME_STEP_MS;

static void init_icc_network_1d()
{
	for (uint8_t i = 0; i < v_count; i++)
	{
		for (uint8_t j = 0; j < h_count; j++)
		{
			// if (i == PACEMAKER_CELL_ROW && j == PACEMAKER_CELL_COL)
			// {
			// 	icc_init(&iccs[i][j], DEFAULT_PM_SLOWWAVE_INTERVAL);
			// }
			// else
			// {
			// 	icc_init(&iccs[i][j], OTHER_ICC_SLOWWAVE_INTERVAL);
			// }
			icc_init(&iccs[i][j], &icc_interval_buff[i][j]);
		}
	}

	if (h_count > 1)
	{
		for (uint8_t i = 0; i < v_count; i++)
		{
			for (uint8_t j = 0; j < h_count - 1; j++)
			{
				icc_path_init(&h_paths[i][j], &h_path_t1[i][j], &h_path_t2[i][j], &h_path_delay_buff[i][j]);
				h_paths[i][j].cells[0] = &iccs[i][j];
				h_paths[i][j].cells[1] = &iccs[i][j + 1];
			}
		}
	}

	if (v_count > 1)
	{
		for (uint8_t i = 0; i < v_count - 1; i++)
		{
			for (uint8_t j = 0; j < h_count; j++)
			{
				icc_path_init(&v_paths[i][j], &v_path_t1[i][j], &v_path_t2[i][j], &v_path_delay_buff[i][j]);
				v_paths[i][j].cells[0] = &iccs[i][j];
				v_paths[i][j].cells[1] = &iccs[i + 1][j];
			}
		}
	}
}

static void step_icc_network_1d(uint32_t *dt_ms)
{
	for (uint8_t i = 0; i < v_count; i++)
	{
		for (uint8_t j = 0; j < h_count; j++)
		{
			(void)icc_update(&iccs[i][j], *dt_ms);
		}
	}
	if (h_count > 1)
	{
		for (uint8_t i = 0; i < v_count; i++)
		{
			for (uint8_t j = 0; j < h_count - 1; j++)
			{
				icc_path_update(&h_paths[i][j], &h_path_t1[i][j], &h_path_t2[i][j], *dt_ms);
			}
		}
	}
	if (v_count > 1)
	{
		for (uint8_t i = 0; i < v_count - 1; i++)
		{
			for (uint8_t j = 0; j < h_count; j++)
			{
				icc_path_update(&v_paths[i][j], &v_path_t1[i][j], &v_path_t2[i][j], *dt_ms);
			}
		}
	}
}

static void step_icc_network_2d(uint32_t *dt_ms)
{
	for (uint8_t i = 0; i < v_count; i++)
	{
		for (uint8_t j = 0; j < h_count; j++)
		{
			(void)icc_update(&iccs[i][j], *dt_ms);
		}
	}

	for (uint8_t i = 0; i < v_count; i++)
	{
		for (uint8_t j = 0; j < h_count - 1; j++)
		{
			icc_path_update(&h_paths[i][j], &h_path_t1[i][j], &h_path_t2[i][j], *dt_ms);
		}
	}
	for (uint8_t i = 0; i < v_count - 1; i++)
	{
		for (uint8_t j = 0; j < h_count; j++)
		{
			icc_path_update(&v_paths[i][j], &v_path_t1[i][j], &v_path_t2[i][j], *dt_ms);
		}
	}
}

static void print_telemetry()
{
	Serial.print("sample=");
	Serial.print(sample_index);
	Serial.print(" ms=");
	Serial.print(millis());

	Serial.print(" v=[");
	for (uint8_t j = 0; j < h_count; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print(iccs[0][j].v, 3);
	}
	Serial.print(']');

	Serial.print(" s=[");
	for (uint8_t j = 0; j < h_count; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print((int)icc_state_index(&iccs[0][j]));
	}
	Serial.print(']');

	Serial.print(" p=[");
	for (uint8_t j = 0; j < h_count - 1; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print((int)icc_path_state_index(&h_paths[0][j]));
	}
	Serial.print(']');

	Serial.print(" t1=[");
	for (uint8_t j = 0; j < h_count - 1; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print(h_path_t1[0][j], 3);
	}
	Serial.print(']');

	Serial.print(" t2=[");
	for (uint8_t j = 0; j < h_count - 1; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print(h_path_t2[0][j], 3);
	}
	Serial.print(']');

	Serial.println();
	sample_index++;
}

static void send_telemetry_packet()
{
	Serial.write(kPacketHeader, sizeof(kPacketHeader));
	for (size_t i = 0; i < v_count; i++)
	{
		for (size_t j = 0; j < h_count; j++)
		{
			Serial.write((const uint8_t *)&iccs[i][j].v, sizeof(iccs[i][j].v));
		}
	}
}

static void apply_ext_stimulus(int8_t row, int8_t col)
{
	if (row < 0 || col < 0)
	{
		return;
	}
	if ((uint8_t)row >= v_count || (uint8_t)col >= h_count)
	{
		return;
	}
	iccs[(uint8_t)row][(uint8_t)col].relay = 1;
}

static void check_ext_stimuli()
{
	static uint8_t match_index = 0U;
	static bool waiting_payload = false;

	if (waiting_payload)
	{
		if (Serial.available() < 2)
		{
			return;
		}
		int8_t row = (int8_t)Serial.read();
		int8_t col = (int8_t)Serial.read();
		waiting_payload = false;
		match_index = 0U;
		apply_ext_stimulus(row, col);
	}

	while (Serial.available() > 0)
	{
		int incoming = Serial.read();
		if (incoming < 0)
		{
			continue;
		}

		uint8_t byte = (uint8_t)incoming;
		if (byte == kPacketHeader[match_index])
		{
			match_index++;
			if (match_index == sizeof(kPacketHeader))
			{
				if (Serial.available() < 2)
				{
					waiting_payload = true;
					return;
				}
				int8_t row = (int8_t)Serial.read();
				int8_t col = (int8_t)Serial.read();
				match_index = 0U;
				apply_ext_stimulus(row, col);
			}
		}
		else
		{
			match_index = (byte == kPacketHeader[0]) ? 1U : 0U;
		}
	}
}

static bool wait_for_init_packet()
{
	static const uint8_t kInitHeader[4] = {'I', 'C', 'C', 'F'};
	uint8_t match_index = 0U;

	while (true)
	{
		while (Serial.available() > 0)
		{
			int incoming = Serial.read();
			if (incoming < 0)
			{
				continue;
			}

			uint8_t byte = (uint8_t)incoming;
			if (byte == kInitHeader[match_index])
			{
				match_index++;
				if (match_index == sizeof(kInitHeader))
				{
					return true;
				}
			}
			else
			{
				match_index = (byte == kInitHeader[0]) ? 1U : 0U;
			}
		}
	}
}

void setup()
{
	bool is_serial_connected = false;

	Serial.begin(115200);

	while (!is_serial_connected)
	{
		is_serial_connected = wait_for_init_packet();
	}

	// Read and unpack the init packet payload into the local buffers.
	// Packet layout after the ASCII header: rows(1), cols(1), time_step_ms(uint16 LE),
	// then rows*cols bytes of per-cell freq, then (if cols>1) rows*(cols-1) uint16 LE
	// horizontal delays, then (if rows>1) (rows-1)*cols uint16 LE vertical delays.
	{
		uint8_t b = 0;

		// read rows
		while (Serial.available() == 0)
			;
		b = (uint8_t)Serial.read();
		v_count = b;

		// read cols
		while (Serial.available() == 0)
			;
		b = (uint8_t)Serial.read();
		h_count = b;

		// read time_step_ms (uint16 little-endian)
		uint8_t lo = 0;
		uint8_t hi = 0;
		while (Serial.available() == 0)
			;
		lo = (uint8_t)Serial.read();
		while (Serial.available() == 0)
			;
		hi = (uint8_t)Serial.read();
		uint16_t step = (uint16_t)lo | ((uint16_t)hi << 8);
		time_step_ms = (uint32_t)step;

		// clamp to compile-time maxima

		if (v_count > MAX_V_ICC_COUNT)
			v_count = MAX_V_ICC_COUNT;
		if (h_count > MAX_H_ICC_COUNT)
			h_count = MAX_H_ICC_COUNT;

		// read per-cell frequencies (one byte each), row-major
		for (int i = 0; i < v_count; i++)
		{
			for (int j = 0; j < h_count; j++)
			{
				while (Serial.available() == 0)
					;
				int8_t interval = (int8_t)Serial.read();
				icc_interval_buff[i][j] = interval;
			}
		}

		// read horizontal path delays (uint16 LE) if present
		if (h_count > 1)
		{
			for (int i = 0; i < v_count; i++)
			{
				for (int j = 0; j < h_count - 1; j++)
				{
					while (Serial.available() == 0)
						;
					uint8_t l = (uint8_t)Serial.read();
					while (Serial.available() == 0)
						;
					uint8_t h = (uint8_t)Serial.read();
					h_path_delay_buff[i][j] = ((uint16_t)l | ((uint16_t)h << 8));
				}
			}
		}

		// read vertical path delays (uint16 LE) if present
		if (v_count > 1)
		{
			for (int i = 0; i < v_count - 1; i++)
			{
				for (int j = 0; j < h_count; j++)
				{
					while (Serial.available() == 0)
						;
					uint8_t l = (uint8_t)Serial.read();
					while (Serial.available() == 0)
						;
					uint8_t h = (uint8_t)Serial.read();
					v_path_delay_buff[i][j] = ((uint16_t)l | ((uint16_t)h << 8));
				}
			}
		}
	}

	init_icc_network_1d();
	next_step_ms = millis() + time_step_ms;

	Serial.println("embedded-icc-uno: ICC 1D model running");
}

void loop()
{
	if ((int32_t)(millis() - next_step_ms) < 0)
	{
		return;
	}

	step_icc_network_1d(&time_step_ms);
	// print_telemetry();
	send_telemetry_packet();
	check_ext_stimuli();
	next_step_ms += time_step_ms;
}
