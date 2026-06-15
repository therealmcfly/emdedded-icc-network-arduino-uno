#ifndef EMBEDDED_ICC_UNO_EGM_H
#define EMBEDDED_ICC_UNO_EGM_H

#include <stdbool.h>
#include <stdint.h>

#include "path.h"

#ifdef __cplusplus
extern "C"
{
#endif

	typedef struct PathDipole
	{
		const IccPath *path;
		bool active;
		float x_mm;
		float y_mm;
		float direction_x;
		float direction_y;
	} PathDipole;

	typedef struct Electrode
	{
		uint8_t row;
		uint8_t col;
		uint8_t height_mm;
		float potential;
	} Electrode;

	void electrode_init(
			Electrode *electrode,
			uint8_t row,
			uint8_t col,
			uint8_t height_mm);

	void electrode_clear(
			Electrode *electrode);

	void electrode_add_dipole(
			Electrode *electrode,
			const PathDipole *dipole);

	void path_dipole_init(
			PathDipole *dipole,
			const IccPath *path);

	void path_dipole_update(
			PathDipole *dipole);

#ifdef __cplusplus
}
#endif

#endif
