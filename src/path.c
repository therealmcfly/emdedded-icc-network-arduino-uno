#include "path.h"

static void clear_outputs(float *relay_atob, float *relay_btoa, float *t1, float *t2)
{
	if (relay_atob != 0)
	{
		*relay_atob = 0.0f;
	}
	if (relay_btoa != 0)
	{
		*relay_btoa = 0.0f;
	}
	if (t1 != 0)
	{
		*t1 = -1.0f;
	}
	if (t2 != 0)
	{
		*t2 = -1.0f;
	}
}

static bool icc_is_active(const Icc *cell)
{
	if (cell == 0)
	{
		return false;
	}

	return (cell->state == Q1_UPSTROKE) || (cell->state == Q2_PLATEAU) || (cell->state == Q3_REPOLARIZATION);
}
static bool check_relay_due_next_step(const IccPath *path, uint32_t dt_ms)
{
	const uint32_t delay_ms = (uint32_t)path->delay_ms;

	if (path->wait_ms_accum >= delay_ms)
	{
		return true;
	}

	return dt_ms >= delay_ms - path->wait_ms_accum;
}
void icc_path_init(IccPath *path, float *t0, float *t1, uint16_t *delay_ms, uint8_t *gap_mm)
{
	if (path == 0)
	{
		return;
	}

	path->state = PATH_IDLE;
	path->wait_ms_accum = 0U;
	path->initialized = true;
	path->delay_ms =
			(delay_ms != 0 && *delay_ms > 0U)
					? *delay_ms
					: DEFAULT_PATH_DELAY_MS;
	path->gap_mm =
			(gap_mm != 0 && *gap_mm > 0U)
					? *gap_mm
					: DEFAULT_PATH_GAP_MM;
	path->cells[0] = 0;
	path->cells[1] = 0;
	path->t[0] = t0;
	path->t[1] = t1;

	if (t0 != 0)
	{
		*path->t[0] = -1.0f;
	}
	if (t1 != 0)
	{
		*path->t[1] = -1.0f;
	}
}

void icc_path_update(IccPath *path, uint32_t dt_ms)
{

	if (path == 0)
	{
		return;
	}

	if (!path->initialized ||
			dt_ms == 0U ||
			path->cells[0] == 0 ||
			path->cells[1] == 0 ||
			path->t[0] == 0 ||
			path->t[1] == 0)
	{
		clear_outputs(0, 0, path->t[0], path->t[1]);
		return;
	}

	switch (path->state)
	{
	case PATH_IDLE:
		if (icc_is_active(path->cells[0]) && icc_is_active(path->cells[1]))
		{
			path->state = PATH_ANNIHILATE;
		}
		else if (icc_is_active(path->cells[0]) && !icc_is_active(path->cells[1]))
		{
			path->wait_ms_accum = 0U;
			*path->t[0] = (float)path->wait_ms_accum * 1.0e-3f;
			path->state = PATH_CELL_A_WAIT;
		}
		else if (icc_is_active(path->cells[1]) && !icc_is_active(path->cells[0]))
		{
			path->wait_ms_accum = 0U;
			*path->t[1] = (float)path->wait_ms_accum * 1.0e-3f;
			path->state = PATH_CELL_B_WAIT;
		}
		break;

	case PATH_ANNIHILATE:
		if (!icc_is_active(path->cells[0]) && !icc_is_active(path->cells[1]))
		{
			path->state = PATH_IDLE;
			clear_outputs(0, 0, path->t[0], path->t[1]);
		}
		break;

	case PATH_CELL_A_WAIT:

		path->wait_ms_accum += dt_ms;
		*path->t[0] = (float)path->wait_ms_accum * 1.0e-3f;

		if (check_relay_due_next_step(path, dt_ms))
		{
			path->cells[1]->relay = 1.0f;
			path->state = PATH_CELL_A_RELAY;
		}
		break;

	case PATH_CELL_A_RELAY:
		path->state = PATH_IDLE;
		clear_outputs(0, 0, path->t[0], path->t[1]);
		break;

	case PATH_CELL_B_WAIT:
		path->wait_ms_accum += dt_ms;
		*path->t[1] = (float)path->wait_ms_accum * 1.0e-3f;
		if (check_relay_due_next_step(path, dt_ms))
		{
			path->cells[0]->relay = 1.0f;
			path->state = PATH_CELL_B_RELAY;
		}
		break;

	case PATH_CELL_B_RELAY:
		path->state = PATH_IDLE;
		clear_outputs(0, 0, path->t[0], path->t[1]);
		break;

	default:
		path->state = PATH_IDLE;
		clear_outputs(0, 0, path->t[0], path->t[1]);
		break;
	}
}

uint8_t icc_path_state_index(const IccPath *path)
{
	if (path == 0)
	{
		return (uint8_t)PATH_IDLE;
	}

	return (uint8_t)path->state;
}
