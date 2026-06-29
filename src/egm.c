#include "egm.h"

#include <math.h>
#include <stddef.h>

#define DIPOLE_MOMENT_DEFAULT 18.0f
#define DIPOLE_LONGITUDINAL_WEIGHT 1.0f
#define DIPOLE_TRANSVERSE_WEIGHT 0.1f
#define DIPOLE_EPSILON 1.0e-6f

static bool path_is_valid(const IccPath *path)
{
	return path != NULL &&
				 path->cells[0] != NULL &&
				 path->cells[1] != NULL &&
				 path->t[0] != NULL &&
				 path->t[1] != NULL &&
				 path->gap_mm > 0U &&
				 path->delay_ms > 0U;
}

static void set_inactive(PathDipole *dipole)
{
	dipole->active = false;
	dipole->direction_x = 0.0f;
	dipole->direction_y = 0.0f;
}

void electrode_init(
		Electrode *electrode,
		uint8_t row,
		uint8_t col,
		uint8_t height_mm)
{
	if (electrode == NULL)
	{
		return;
	}

	electrode->row = row;
	electrode->col = col;
	electrode->height_mm = height_mm;
	electrode->potential = 0.0f;
}

void electrode_clear(Electrode *electrode)
{
	if (electrode == NULL)
	{
		return;
	}

	electrode->potential = 0.0f;
}

void electrode_add_dipole(
		Electrode *electrode,
		const PathDipole *dipole)
{
	if (electrode == NULL ||
			dipole == NULL ||
			!dipole->active ||
			dipole->path == NULL ||
			dipole->path->gap_mm == 0U)
	{
		return;
	}

	const float gap_mm = (float)dipole->path->gap_mm;
	const float electrode_x_mm = (float)electrode->col * gap_mm;
	const float electrode_y_mm = (float)electrode->row * gap_mm;
	const float electrode_dx = electrode_x_mm - dipole->x_mm;
	const float electrode_dy = electrode_y_mm - dipole->y_mm;
	const float along_path_mm =
			electrode_dx * dipole->direction_x +
			electrode_dy * dipole->direction_y;
	const float perpendicular_x =
			electrode_dx - along_path_mm * dipole->direction_x;
	const float perpendicular_y =
			electrode_dy - along_path_mm * dipole->direction_y;
	const float height_mm = (float)electrode->height_mm;
	const float perpendicular_mm = sqrtf(
			perpendicular_x * perpendicular_x +
			perpendicular_y * perpendicular_y +
			height_mm * height_mm);
	const float distance_squared =
			along_path_mm * along_path_mm +
			perpendicular_mm * perpendicular_mm;

	if (distance_squared <= DIPOLE_EPSILON)
	{
		return;
	}

	const float distance_cubed =
			distance_squared * sqrtf(distance_squared);
	const float longitudinal =
			DIPOLE_LONGITUDINAL_WEIGHT *
			along_path_mm / distance_cubed;
	const float transverse =
			-DIPOLE_TRANSVERSE_WEIGHT *
			perpendicular_mm / distance_cubed;

	electrode->potential +=
			(longitudinal + transverse) * DIPOLE_MOMENT_DEFAULT;
}

void path_dipole_init(PathDipole *dipole, const IccPath *path)
{
	if (dipole == NULL)
	{
		return;
	}

	dipole->path = path;
	dipole->x_mm = 0.0f;
	dipole->y_mm = 0.0f;
	set_inactive(dipole);

	if (!path_is_valid(path))
	{
		return;
	}

	dipole->x_mm =
			(float)path->cells[0]->pos.col * (float)path->gap_mm;
	dipole->y_mm =
			(float)path->cells[0]->pos.row * (float)path->gap_mm;
}

void path_dipole_update(PathDipole *dipole)
{
	if (dipole == NULL)
	{
		return;
	}

	if (!path_is_valid(dipole->path))
	{
		set_inactive(dipole);
		return;
	}

	const IccPath *path = dipole->path;
	const float forward_time_s = *path->t[0];
	const float reverse_time_s = *path->t[1];
	const Icc *start_cell;
	const Icc *end_cell;
	float elapsed_s;

	if (forward_time_s >= 0.0f)
	{
		start_cell = path->cells[0];
		end_cell = path->cells[1];
		elapsed_s = forward_time_s;
	}
	else if (reverse_time_s >= 0.0f)
	{
		start_cell = path->cells[1];
		end_cell = path->cells[0];
		elapsed_s = reverse_time_s;
	}
	else
	{
		set_inactive(dipole);
		return;
	}

	const float gap_mm = (float)path->gap_mm;
	const float start_x_mm = (float)start_cell->pos.col * gap_mm;
	const float start_y_mm = (float)start_cell->pos.row * gap_mm;
	const float end_x_mm = (float)end_cell->pos.col * gap_mm;
	const float end_y_mm = (float)end_cell->pos.row * gap_mm;
	const float dx = end_x_mm - start_x_mm;
	const float dy = end_y_mm - start_y_mm;
	const float path_length_mm = sqrtf(dx * dx + dy * dy);

	if (path_length_mm <= DIPOLE_EPSILON)
	{
		set_inactive(dipole);
		return;
	}

	dipole->direction_x = dx / path_length_mm;
	dipole->direction_y = dy / path_length_mm;

	const float velocity_mm_s =
			gap_mm * 1000.0f / (float)path->delay_ms;
	float travelled_mm = velocity_mm_s * elapsed_s;
	if (travelled_mm > path_length_mm)
	{
		travelled_mm = path_length_mm;
	}

	dipole->x_mm =
			start_x_mm + travelled_mm * dipole->direction_x;
	dipole->y_mm =
			start_y_mm + travelled_mm * dipole->direction_y;
	dipole->active = true;
}
