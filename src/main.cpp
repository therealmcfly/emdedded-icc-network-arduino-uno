#include <Arduino.h>
#include "icc.h"
#include "path.h"

#define ICC_H_COUNT 10
#define ICC_V_COUNT 1
#define PACEMAKER_CELL_ROW 0
#define PACEMAKER_CELL_COL 0
#define PM_SLOWWAVE_INTERVAL 20
#define OTHER_ICC_SLOWWAVE_INTERVAL 0
#define TIME_STEP_MS_1D 200U

static Icc iccs[ICC_V_COUNT][ICC_H_COUNT];
static IccPath h_paths[ICC_V_COUNT][ICC_H_COUNT - 1];
static float h_path_t1[ICC_V_COUNT][ICC_H_COUNT - 1];
static float h_path_t2[ICC_V_COUNT][ICC_H_COUNT - 1];

static uint32_t next_step_ms = 0U;
static uint32_t sample_index = 0U;
static const uint8_t kPacketHeader[2] = {0xAA, 0x55};
static const uint16_t kPacketFloatCount = (uint16_t)(ICC_V_COUNT * ICC_H_COUNT);

static void init_icc_network_1d()
{
	for (size_t i = 0; i < ICC_V_COUNT; i++)
	{
		for (size_t j = 0; j < ICC_H_COUNT; j++)
		{
			if (i == PACEMAKER_CELL_ROW && j == PACEMAKER_CELL_COL)
			{
				icc_init(&iccs[i][j], PM_SLOWWAVE_INTERVAL);
			}
			else
			{
				icc_init(&iccs[i][j], OTHER_ICC_SLOWWAVE_INTERVAL);
			}
		}
	}

	for (size_t i = 0; i < ICC_V_COUNT; i++)
	{
		for (size_t j = 0; j < ICC_H_COUNT - 1; j++)
		{
			icc_path_init(&h_paths[i][j], &h_path_t1[i][j], &h_path_t2[i][j]);
			h_paths[i][j].cells[0] = &iccs[i][j];
			h_paths[i][j].cells[1] = &iccs[i][j + 1];
		}
	}
}

static void step_icc_network_1d(uint32_t dt_ms)
{
	for (size_t i = 0; i < ICC_V_COUNT; i++)
	{
		for (size_t j = 0; j < ICC_H_COUNT; j++)
		{
			(void)icc_update(&iccs[i][j], dt_ms);
		}
	}

	for (size_t i = 0; i < ICC_V_COUNT; i++)
	{
		for (size_t j = 0; j < ICC_H_COUNT - 1; j++)
		{
			icc_path_update(&h_paths[i][j], &h_path_t1[i][j], &h_path_t2[i][j], dt_ms);
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
	for (size_t j = 0; j < ICC_H_COUNT; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print(iccs[0][j].v, 3);
	}
	Serial.print(']');

	Serial.print(" s=[");
	for (size_t j = 0; j < ICC_H_COUNT; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print((int)icc_state_index(&iccs[0][j]));
	}
	Serial.print(']');

	Serial.print(" p=[");
	for (size_t j = 0; j < ICC_H_COUNT - 1; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print((int)icc_path_state_index(&h_paths[0][j]));
	}
	Serial.print(']');

	Serial.print(" t1=[");
	for (size_t j = 0; j < ICC_H_COUNT - 1; j++)
	{
		if (j > 0)
		{
			Serial.print(' ');
		}
		Serial.print(h_path_t1[0][j], 3);
	}
	Serial.print(']');

	Serial.print(" t2=[");
	for (size_t j = 0; j < ICC_H_COUNT - 1; j++)
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
	for (size_t i = 0; i < ICC_V_COUNT; i++)
	{
		for (size_t j = 0; j < ICC_H_COUNT; j++)
		{
			Serial.write((const uint8_t *)&iccs[i][j].v, sizeof(iccs[i][j].v));
		}
	}
}

void setup()
{
	Serial.begin(115200);

	init_icc_network_1d();
	next_step_ms = millis() + TIME_STEP_MS_1D;

	Serial.println("embedded-icc-uno: ICC 1D model running");
	Serial.print("packet_floats=");
	Serial.println(kPacketFloatCount);
}

void loop()
{
	if ((int32_t)(millis() - next_step_ms) < 0)
	{
		return;
	}

	step_icc_network_1d(TIME_STEP_MS_1D);
	// print_telemetry();
	send_telemetry_packet();
	next_step_ms += TIME_STEP_MS_1D;
}
