#ifndef ICC_PATH_H
#define ICC_PATH_H

#include <stdbool.h>
#include <stdint.h>
#include "icc.h"

#define PATH_DELAY_MS 2000U

#ifdef __cplusplus
extern "C"
{
#endif

	typedef enum IccPathState
	{
		PATH_IDLE = 0,
		PATH_ANNIHILATE = 1,
		PATH_CELL_A_WAIT = 2,
		PATH_CELL_A_RELAY = 3,
		PATH_CELL_B_WAIT = 4,
		PATH_CELL_B_RELAY = 5
	} IccPathState;

	typedef struct IccPath
	{
		IccPathState state;
		uint32_t wait_ms_accum;
		bool initialized;
		uint16_t delay_ms;
		Icc *cells[2];
	} IccPath;

	void icc_path_init(IccPath *path, float *t1, float *t2, uint16_t *delay_ms);
	void icc_path_update(IccPath *path, float *t1, float *t2, uint32_t dt_ms);
	uint8_t icc_path_state_index(const IccPath *path);

#ifdef __cplusplus
}
#endif

#endif
