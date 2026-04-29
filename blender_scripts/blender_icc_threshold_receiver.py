import bpy
import serial
import struct
import time

# -------------------------------
# Serial configuration
# -------------------------------
# Packet format from Arduino:
#   [0xAA, 0x55] + [rows*cols float32 little-endian]
PORT = "COM7"
BAUD = 115200
HEADER = b"\xAA\x55"

# Grid size must match the sender firmware.
ICC_ROWS = 1
ICC_COLS = 10
PACKET_FLOAT_COUNT = ICC_ROWS * ICC_COLS

PAYLOAD_SIZE = 4 * PACKET_FLOAT_COUNT
FRAME_SIZE = 2 + PAYLOAD_SIZE

# -------------------------------
# Blender target configuration
# -------------------------------
# Naming convention expected:
#   Armature.001.001, Armature.001.002, ...
#   Bone.001.001, Bone.001.002, ...
ARMATURE_PREFIX = "Armature"
BONE_PREFIX = "Bone"
TIMER_SECONDS = 0.01

# -------------------------------
# Threshold behavior
# -------------------------------
# If ICC value > CONTRACTION_THRESHOLD, set contracted scale.
# Else, set relaxed scale.
CONTRACTION_THRESHOLD = -30.0
CONTRACTED_SCALE_Y = 1.0
RELAXED_SCALE_Y = 0.3

# Transition timing (seconds).
# Set to 0.0 for an immediate jump.
CONTRACTION_TIME_S = 1.0
RELAXATION_TIME_S = 1.0


class SerialIccThresholdOperator(bpy.types.Operator):
    """Reads ICC packets and drives each bone scale.y by threshold state."""

    bl_idname = "wm.serial_icc_threshold_link"
    bl_label = "Serial ICC Threshold Link"

    _timer = None
    _ser = None
    _buf = bytearray()
    _target_by_cell = None
    _last_tick_time = None

    def _armature_name(self, row_idx, col_idx):
        return f"{ARMATURE_PREFIX}.{row_idx:03d}.{col_idx:03d}"

    def _bone_name(self, row_idx, col_idx):
        return f"{BONE_PREFIX}.{row_idx:03d}.{col_idx:03d}"

    def _target_scale(self, icc_value):
        if icc_value > CONTRACTION_THRESHOLD:
            return CONTRACTED_SCALE_Y
        return RELAXED_SCALE_Y

    def _cell_key(self, row_idx, col_idx):
        return (row_idx, col_idx)

    def _step_toward(self, current, target, dt_s):
        if current == target:
            return target

        going_up = target > current
        duration = CONTRACTION_TIME_S if going_up else RELAXATION_TIME_S
        if duration <= 0.0:
            return target

        full_span = abs(CONTRACTED_SCALE_Y - RELAXED_SCALE_Y)
        if full_span <= 0.0:
            return target

        max_delta = (full_span / duration) * dt_s
        diff = target - current

        if abs(diff) <= max_delta:
            return target

        return current + (max_delta if diff > 0.0 else -max_delta)

    def _update_targets_from_values(self, values):
        for r in range(ICC_ROWS):
            for c in range(ICC_COLS):
                value = values[(r * ICC_COLS) + c]
                row_idx = r + 1
                col_idx = c + 1
                key = self._cell_key(row_idx, col_idx)
                self._target_by_cell[key] = self._target_scale(value)

    def _apply_smoothing_step(self, dt_s):
        changed = False

        for (row_idx, col_idx), target_scale_y in self._target_by_cell.items():
            arm_name = self._armature_name(row_idx, col_idx)
            bone_name = self._bone_name(row_idx, col_idx)

            arm = bpy.data.objects.get(arm_name)
            if arm is None:
                continue

            bone = arm.pose.bones.get(bone_name)
            if bone is None:
                continue

            if bone.lock_scale[1]:
                continue

            current = float(bone.scale.y)
            next_value = self._step_toward(current, target_scale_y, dt_s)
            if next_value != current:
                bone.scale.y = next_value
                changed = True

        return changed

    def _redraw_viewports(self, context):
        context.view_layer.update()
        wm = context.window_manager
        for win in wm.windows:
            screen = win.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def _process_buffer(self, context):
        while True:
            start = self._buf.find(HEADER)
            if start < 0:
                if len(self._buf) > 1:
                    del self._buf[:-1]
                return

            if start > 0:
                del self._buf[:start]

            if len(self._buf) < FRAME_SIZE:
                return

            payload = bytes(self._buf[2:2 + PAYLOAD_SIZE])
            del self._buf[:FRAME_SIZE]

            try:
                values = struct.unpack("<" + ("f" * PACKET_FLOAT_COUNT), payload)
            except struct.error:
                continue

            self._update_targets_from_values(values)

    def modal(self, context, event):
        if event.type == "ESC":
            return self.cancel(context)

        if event.type == "TIMER" and self._ser is not None:
            now = time.perf_counter()
            if self._last_tick_time is None:
                dt_s = 0.0
            else:
                dt_s = now - self._last_tick_time
            self._last_tick_time = now

            try:
                count = self._ser.in_waiting
                if count > 0:
                    self._buf.extend(self._ser.read(count))
                    self._process_buffer(context)

                if self._apply_smoothing_step(dt_s):
                    self._redraw_viewports(context)
            except Exception as exc:
                self.report({"ERROR"}, f"Serial read error: {exc}")
                return self.cancel(context)

        return {"PASS_THROUGH"}

    def execute(self, context):
        try:
            self._ser = serial.Serial(PORT, BAUD, timeout=0)
            self._ser.reset_input_buffer()

            wm = context.window_manager
            self._timer = wm.event_timer_add(TIMER_SECONDS, window=context.window)
            wm.modal_handler_add(self)

            self._target_by_cell = {}
            for r in range(ICC_ROWS):
                for c in range(ICC_COLS):
                    row_idx = r + 1
                    col_idx = c + 1
                    self._target_by_cell[self._cell_key(row_idx, col_idx)] = RELAXED_SCALE_Y
            self._last_tick_time = None

            print(f"ICC threshold link active on {PORT} @ {BAUD}")
            print(f"Grid: {ICC_ROWS}x{ICC_COLS} ({PACKET_FLOAT_COUNT} floats per packet)")
            print(f"Naming: {ARMATURE_PREFIX}.RRR.CCC and {BONE_PREFIX}.RRR.CCC")
            print(
                f"Threshold mode: if v>{CONTRACTION_THRESHOLD} -> y={CONTRACTED_SCALE_Y}, "
                f"else y={RELAXED_SCALE_Y}"
            )
            print(
                f"Transition times: contraction={CONTRACTION_TIME_S}s, "
                f"relaxation={RELAXATION_TIME_S}s"
            )
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not open {PORT}: {exc}")
            return {"CANCELLED"}

    def cancel(self, context):
        wm = context.window_manager

        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None

        if self._ser is not None:
            self._ser.close()
            self._ser = None

        print("ICC threshold link stopped")
        return {"CANCELLED"}


def register():
    bpy.utils.register_class(SerialIccThresholdOperator)


def unregister():
    bpy.utils.unregister_class(SerialIccThresholdOperator)


if __name__ == "__main__":
    register()
