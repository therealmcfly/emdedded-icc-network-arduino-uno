import bpy
import serial
import struct

# -------------------------------
# Serial configuration
# -------------------------------
# Packet format from Arduino:
#   [0xAA, 0x55] + [rows*cols float32 little-endian]
PORT = "COM7"
BAUD = 115200
HEADER = b"\xAA\x55"

# ICC grid size from embedded project (for example: 3x3 -> 9 floats).
ICC_ROWS = 1
ICC_COLS = 10
PACKET_FLOAT_COUNT = ICC_ROWS * ICC_COLS

PAYLOAD_SIZE = 4 * PACKET_FLOAT_COUNT
FRAME_SIZE = 2 + PAYLOAD_SIZE

# -------------------------------
# Blender target configuration
# -------------------------------
# Naming convention:
#   Armature.001.001, Armature.001.002, ...
#   Bone.001.001, Bone.001.002, ...
ARMATURE_PREFIX = "Armature"
BONE_PREFIX = "Bone"
TIMER_SECONDS = 0.2

# -------------------------------
# Value mapping configuration
# -------------------------------
# Incoming ICC voltage range is mapped to bone local scale.y range.
ICC_V_MIN = -67.0
ICC_V_MAX = -24.1091
BONE_Y_MIN = 0.3
BONE_Y_MAX = 1.0


class SerialSingleIccOperator(bpy.types.Operator):
    """Modal operator that reads ICC grid packets and drives a bone grid."""

    bl_idname = "wm.serial_single_icc_link"
    bl_label = "Serial Single ICC Link"

    # Runtime state kept by the operator instance.
    _timer = None
    _ser = None
    _buf = bytearray()
    _packet_counter = 0

    def _map_icc_to_bone_y(self, icc_v):
        """Linearly map ICC voltage to the configured local scale.y range."""
        if ICC_V_MAX <= ICC_V_MIN:
            return BONE_Y_MIN

        t = (icc_v - ICC_V_MIN) / (ICC_V_MAX - ICC_V_MIN)
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0

        return BONE_Y_MIN + t * (BONE_Y_MAX - BONE_Y_MIN)

    def _armature_name(self, row_idx, col_idx):
        """Format armature object name for 1-based row/col indices."""
        return f"{ARMATURE_PREFIX}.{row_idx:03d}.{col_idx:03d}"

    def _bone_name(self, row_idx, col_idx):
        """Format pose bone name for 1-based row/col indices."""
        return f"{BONE_PREFIX}.{row_idx:03d}.{col_idx:03d}"

    def _apply_grid_values(self, values):
        """Apply one full ICC grid frame to matching Blender bones."""
        for r in range(ICC_ROWS):
            for c in range(ICC_COLS):
                value = values[(r * ICC_COLS) + c]
                mapped_y = self._map_icc_to_bone_y(value)

                row_idx = r + 1
                col_idx = c + 1
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

                bone.scale.y = mapped_y

    def _redraw_viewports(self, context):
        """Force viewport update so deformation appears immediately."""
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
        """
        Consume buffered bytes.
        For each full frame: parse float array, apply to grid bones, redraw.
        """
        while True:
            # Sync to frame header.
            start = self._buf.find(HEADER)
            if start < 0:
                # Keep only one trailing byte for possible partial header match.
                if len(self._buf) > 1:
                    del self._buf[:-1]
                return

            if start > 0:
                del self._buf[:start]

            # Wait until full frame is available.
            if len(self._buf) < FRAME_SIZE:
                return

            # Extract payload and remove full frame from buffer.
            payload = bytes(self._buf[2:2 + PAYLOAD_SIZE])
            del self._buf[:FRAME_SIZE]

            try:
                values = struct.unpack("<" + ("f" * PACKET_FLOAT_COUNT), payload)
            except struct.error:
                continue

            self._packet_counter += 1
            if self._packet_counter % 5 == 0:
                preview = ", ".join(f"{v:.3f}" for v in values)
                print(f"pkt={self._packet_counter} values=[{preview}]")

            self._apply_grid_values(values)
            self._redraw_viewports(context)

    def modal(self, context, event):
        """Runs repeatedly while operator is active."""
        if event.type == "ESC":
            return self.cancel(context)

        if event.type == "TIMER" and self._ser is not None:
            try:
                count = self._ser.in_waiting
                if count > 0:
                    self._buf.extend(self._ser.read(count))
                    self._process_buffer(context)
            except Exception as exc:
                self.report({"ERROR"}, f"Serial read error: {exc}")
                return self.cancel(context)

        return {"PASS_THROUGH"}

    def execute(self, context):
        """Start serial link and timer-driven modal loop."""
        try:
            self._ser = serial.Serial(PORT, BAUD, timeout=0)
            self._ser.reset_input_buffer()

            wm = context.window_manager
            self._timer = wm.event_timer_add(TIMER_SECONDS, window=context.window)
            wm.modal_handler_add(self)

            print(f"ICC link active on {PORT} @ {BAUD}")
            print(f"Grid: {ICC_ROWS}x{ICC_COLS} ({PACKET_FLOAT_COUNT} floats per packet)")
            print(f"Naming: {ARMATURE_PREFIX}.RRR.CCC and {BONE_PREFIX}.RRR.CCC")
            print("Drive mode: strict local scale.y for all matched cells")
            self._packet_counter = 0
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self.report({"ERROR"}, f"Could not open {PORT}: {exc}")
            return {"CANCELLED"}

    def cancel(self, context):
        """Stop timer + close serial port."""
        wm = context.window_manager

        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None

        if self._ser is not None:
            self._ser.close()
            self._ser = None

        print("Single ICC link stopped")
        return {"CANCELLED"}


def register():
    """Register operator in Blender."""
    bpy.utils.register_class(SerialSingleIccOperator)


def unregister():
    """Unregister operator from Blender."""
    bpy.utils.unregister_class(SerialSingleIccOperator)


if __name__ == "__main__":
    register()
