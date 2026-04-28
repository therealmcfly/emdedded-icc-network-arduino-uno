#ifndef ICC_H
#define ICC_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C"
{
#endif

#define Q1_SLOP_20SECS (-0.069979275f)
#define Q1_SLOP_23SECS (-0.052964706f)
#define Q1_SLOP_30SECS (-0.0340f)
#define Q1_SLOP_40SECS (-0.022471698f)
#define ICC_SLOPE_Q1 (43.5248f)
#define ICC_SLOPE_Q2 (-0.909759259f)
#define ICC_SLOPE_Q3 (-8.636136364f)
#define ICC_THRESHOLD_Q0_TO_Q1 (-67.6339f)
#define ICC_THRESHOLD_Q1_TO_Q2 (-24.1091f)
#define ICC_THRESHOLD_Q2_TO_Q3 (-28.9894f)
#define ICC_THRESHOLD_Q3_TO_Q0 (-66.9884f)
#define ICC_V_RESET_DEFAULT (-67.6336f)
#define ICC_V_FLOOR (-67.0f)
#define ICC_WAIT_MS (4999U)

	typedef enum IccState
	{
		Q0_RESTING = 0,
		Q1_UPSTROKE = 1,
		Q2_PLATEAU = 2,
		Q3_REPOLARIZATION = 3,
		WAIT = 4
	} IccState;

	typedef struct Icc
	{
		IccState state;
		float v;
		float vreset;
		float vmax;
		float d2;
		uint32_t wait_ms_accum;
		bool reset;
		bool initialized;
		uint32_t transition_count;
		float relay;
		float resting_slope;
	} Icc;

	void icc_init(Icc *icc, uint8_t *pm_sw_interval);
	float icc_update(Icc *icc, uint32_t dt_ms);
	uint8_t icc_state_index(const Icc *icc);

#ifdef __cplusplus
}
#endif

#endif
