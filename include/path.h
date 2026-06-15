#ifndef ICC_PATH_H
#define ICC_PATH_H

#include <stdbool.h>
#include <stdint.h>
#include "icc.h"

#define DEFAULT_PATH_DELAY_MS 1000U // Propagation time taken between ICCs
#define DEFAULT_PATH_GAP_MM 6U // Default distance between connected ICCs

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
		uint8_t gap_mm;
		Icc *cells[2];
		float *t[2];
	} IccPath;

	void icc_path_init(IccPath *path, float *t1, float *t2, uint16_t *delay_ms, uint8_t *gap_mm);
	void icc_path_update(IccPath *path, uint32_t dt_ms);
	uint8_t icc_path_state_index(const IccPath *path);

#ifdef __cplusplus
}
#endif

#endif
