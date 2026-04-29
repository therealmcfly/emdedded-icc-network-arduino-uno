#include "icc.h"
#include <avr/pgmspace.h>

static const float kRestingSlopes[5] PROGMEM = {
    0.0f,            /* 0 — disabled (interval = 0) */
    Q1_SLOP_20SECS,  /* 1 — 20 s */
    Q1_SLOP_23SECS,  /* 2 — 23 s */
    Q1_SLOP_30SECS,  /* 3 — 30 s */
    Q1_SLOP_40SECS,  /* 4 — 40 s */
};

static float clampf(float x, float lo, float hi)
{
	if (x < lo)
	{
		return lo;
	}
	if (x > hi)
	{
		return hi;
	}
	return x;
}

void icc_init(Icc *icc, uint8_t *pm_sw_interval)
{
	if (icc == 0)
	{
		return;
	}

	icc->state = WAIT;
	icc->v = 0.0f;
	icc->vreset = ICC_V_RESET_DEFAULT;
	icc->vmax = ICC_THRESHOLD_Q1_TO_Q2;
	icc->d2 = ICC_SLOPE_Q2;
	icc->wait_ms_accum = 0U;
	icc->reset = false;
	icc->initialized = true;
	icc->relay = 0.0f;

	switch (*pm_sw_interval)
	{
	case 20: icc->slope_idx = 1; break;
	case 23: icc->slope_idx = 2; break;
	case 30: icc->slope_idx = 3; break;
	case 40: icc->slope_idx = 4; break;
	default: icc->slope_idx = 0; break;
	}
}

float icc_update(Icc *icc, uint32_t dt_ms)
{
	bool did_reset = false;
	float dt_seconds = dt_ms * 1.0e-3f;

	if (icc == 0 || dt_ms == 0U || !icc->initialized)
	{
		return 0.0f;
	}

	switch (icc->state)
	{
	case Q0_RESTING:
		if (icc->relay > 0.0f || icc->v < ICC_THRESHOLD_Q0_TO_Q1)
		{
			icc->vreset = icc->v;
			icc->vmax = ICC_THRESHOLD_Q1_TO_Q2;
			icc->d2 = ICC_SLOPE_Q2;
			icc->state = Q1_UPSTROKE;
			did_reset = true;
			icc->relay = 0.0f;
		}
		break;

	case Q1_UPSTROKE:
		if (icc->v >= icc->vmax)
		{
			icc->vreset = icc->v;
			icc->state = Q2_PLATEAU;
			did_reset = true;
		}
		break;

	case Q2_PLATEAU:
		if (icc->v < ICC_THRESHOLD_Q2_TO_Q3)
		{
			icc->vreset = icc->v;
			icc->state = Q3_REPOLARIZATION;
			did_reset = true;
		}
		break;

	case Q3_REPOLARIZATION:
		if (icc->v < ICC_THRESHOLD_Q3_TO_Q0)
		{
			icc->vreset = icc->v;
			icc->state = Q0_RESTING;
			did_reset = true;
		}
		break;

	case WAIT:
	default:
		icc->wait_ms_accum += dt_ms;
		if (icc->wait_ms_accum >= ICC_WAIT_MS)
		{
			icc->vreset = ICC_V_RESET_DEFAULT;
			icc->state = Q0_RESTING;
			icc->wait_ms_accum = 0U;
			did_reset = true;
		}
		break;
	}

	if (did_reset)
	{
		icc->reset = !icc->reset;
		icc->v = icc->vreset;
	}

	switch (icc->state)
	{
	case Q0_RESTING:
		icc->v += pgm_read_float(&kRestingSlopes[icc->slope_idx]) * dt_seconds;
		break;

	case Q1_UPSTROKE:
		icc->v += ICC_SLOPE_Q1 * dt_seconds;
		icc->v = clampf(icc->v, -1.0e30f, ICC_THRESHOLD_Q1_TO_Q2);
		break;

	case Q2_PLATEAU:
		icc->v += icc->d2 * dt_seconds;
		break;

	case Q3_REPOLARIZATION:
		icc->v += ICC_SLOPE_Q3 * dt_seconds;
		icc->v = clampf(icc->v, ICC_V_FLOOR, 1.0e30f);
		break;

	case WAIT:
	default:
		break;
	}

	return icc->v;
}

uint8_t icc_state_index(const Icc *icc)
{
	if (icc == 0)
	{
		return (uint8_t)WAIT;
	}
	return (uint8_t)icc->state;
}
