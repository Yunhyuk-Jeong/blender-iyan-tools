import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from .config import ROOT_PANEL_ID, SIDEBAR_CATEGORY


def polygon_area_2d(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index in range(len(points)):
        p1 = points[index]
        p2 = points[(index + 1) % len(points)]
        area += (p1.x * p2.y) - (p2.x * p1.y)
    return abs(area) * 0.5


def uv_bbox(points):
    min_u = min(point.x for point in points)
    max_u = max(point.x for point in points)
    min_v = min(point.y for point in points)
    max_v = max(point.y for point in points)
    return max_u - min_u, max_v - min_v


def is_all_same_uv(uv_points, threshold=1e-4):
    if not uv_points:
        return False
    first = uv_points[0]
    for point in uv_points[1:]:
        if (point - first).length > threshold:
            return False
    return True


def count_unique_uv_points(uv_points, threshold=1e-4):
    unique = []
    for point in uv_points:
        found = False
        for existing in unique:
            if (point - existing).length <= threshold:
                found = True
                break
        if not found:
            unique.append(point)
    return len(unique)


def edge_uvs_for_face(face, edge, uv_layer):
    loops = [loop for loop in face.loops if loop.edge == edge]
    if len(loops) != 1:
        return None
    loop = loops[0]
    uv1 = loop[uv_layer].uv.copy()
    uv2 = loop.link_loop_next[uv_layer].uv.copy()
    v1 = loop.vert
    v2 = loop.link_loop_next.vert
    return (v1, v2, uv1, uv2)


def faces_uv_connected_by_edge(face_a, face_b, uv_layer, threshold=1e-4):
    shared_edges = set(face_a.edges).intersection(set(face_b.edges))
    if not shared_edges:
        return False
    for edge in shared_edges:
        a = edge_uvs_for_face(face_a, edge, uv_layer)
        b = edge_uvs_for_face(face_b, edge, uv_layer)
        if a is None or b is None:
            continue

        av1, av2, au1, au2 = a
        bv1, bv2, bu1, bu2 = b
        same_dir = av1 == bv1 and av2 == bv2 and (au1 - bu1).length <= threshold and (au2 - bu2).length <= threshold
        rev_dir = av1 == bv2 and av2 == bv1 and (au1 - bu2).length <= threshold and (au2 - bu1).length <= threshold
        if same_dir or rev_dir:
            return True
    return False


def get_uv_islands(bm, uv_layer, threshold=1e-4):
    islands = []
    visited = set()
    for face in bm.faces:
        if face in visited:
            continue

        stack = [face]
        island = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            island.append(current)
            for edge in current.edges:
                for linked in edge.link_faces:
                    if linked in visited:
                        continue
                    if faces_uv_connected_by_edge(current, linked, uv_layer, threshold):
                        stack.append(linked)
        islands.append(island)
    return islands


def island_points(island, uv_layer):
    points = []
    for face in island:
        for loop in face.loops:
            points.append(loop[uv_layer].uv.copy())
    return points


def get_target_objects(context, scan_mode):
    if scan_mode == "ACTIVE":
        obj = context.active_object
        return [obj] if obj and obj.type == "MESH" else []
    if scan_mode == "SELECTED":
        return [obj for obj in context.selected_objects if obj.type == "MESH"]
    return []


class IYAN_OT_uv_validate(bpy.types.Operator):
    bl_idname = "iyan.uv_validate"
    bl_label = "Validate UV"
    bl_description = "Detect collapsed UV faces and bad UV islands"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):
        scene = context.scene
        targets = get_target_objects(context, scene.iyan_uv_scan_mode)
        if not targets:
            self.report({"WARNING"}, "No mesh targets available for UV validation.")
            return {"CANCELLED"}

        total_bad_faces = 0
        total_bad_islands = 0
        no_uv_objects = []
        original_active = context.view_layer.objects.active

        bpy.ops.object.mode_set(mode="OBJECT")
        for obj in targets:
            for selected in context.selected_objects:
                selected.select_set(False)

            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")

            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                no_uv_objects.append(obj.name)
                bpy.ops.object.mode_set(mode="OBJECT")
                continue

            if scene.iyan_uv_deselect_others:
                for face in bm.faces:
                    face.select = False

            bad_faces = set()
            bad_islands = []

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue
                uv_points = [loop[uv_layer].uv.copy() for loop in face.loops]
                area = polygon_area_2d(uv_points)
                width, height = uv_bbox(uv_points)
                unique_count = count_unique_uv_points(uv_points, scene.iyan_uv_same_uv_threshold)

                is_bad = False
                if scene.iyan_uv_detect_face_zero_area and area <= scene.iyan_uv_face_area_threshold:
                    is_bad = True
                if scene.iyan_uv_detect_face_tiny_bbox and width <= scene.iyan_uv_face_bbox_threshold and height <= scene.iyan_uv_face_bbox_threshold:
                    is_bad = True
                if scene.iyan_uv_detect_face_same_uv:
                    if is_all_same_uv(uv_points, scene.iyan_uv_same_uv_threshold):
                        is_bad = True
                    elif unique_count <= 2:
                        is_bad = True
                if is_bad:
                    bad_faces.add(face)

            islands = get_uv_islands(bm, uv_layer, scene.iyan_uv_same_uv_threshold)
            for island in islands:
                points = island_points(island, uv_layer)
                width, height = uv_bbox(points)
                is_bad = False
                if scene.iyan_uv_detect_island_tiny_bbox and width <= scene.iyan_uv_island_bbox_threshold and height <= scene.iyan_uv_island_bbox_threshold:
                    is_bad = True
                if scene.iyan_uv_detect_island_thin:
                    if height > 0 and (width / height) <= scene.iyan_uv_island_thin_ratio:
                        is_bad = True
                    elif width > 0 and (height / width) <= scene.iyan_uv_island_thin_ratio:
                        is_bad = True
                if is_bad:
                    bad_islands.append(island)
                    for face in island:
                        bad_faces.add(face)

            if scene.iyan_uv_select_result:
                for face in bad_faces:
                    face.select = True

            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data)

            obj_bad_faces = len(bad_faces)
            obj_bad_islands = len(bad_islands)
            total_bad_faces += obj_bad_faces
            total_bad_islands += obj_bad_islands

            if scene.iyan_uv_print_result:
                print(f"[Iyan UV Validation] {obj.name}: bad faces={obj_bad_faces}, bad islands={obj_bad_islands}")

            bpy.ops.object.mode_set(mode="OBJECT")

        if targets:
            context.view_layer.objects.active = targets[0]
            targets[0].select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
        elif original_active:
            context.view_layer.objects.active = original_active

        scene.iyan_uv_last_bad_faces = total_bad_faces
        scene.iyan_uv_last_bad_islands = total_bad_islands
        scene.iyan_uv_last_no_uv_objects = len(no_uv_objects)

        if scene.iyan_uv_print_result and no_uv_objects:
            print("[Iyan UV Validation] No active UV map:")
            for name in no_uv_objects:
                print(f"  - {name}")

        self.report({"INFO"}, f"Bad faces: {total_bad_faces}, Bad islands: {total_bad_islands}, No UV: {len(no_uv_objects)}")
        return {"FINISHED"}


class IYAN_PT_uv_panel(bpy.types.Panel):
    bl_label = "UV Validation"
    bl_idname = "IYAN_PT_uv_tool"
    bl_parent_id = ROOT_PANEL_ID
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.label(text="Scan")
        col.prop(scene, "iyan_uv_scan_mode", text="")

        col.separator()
        col.label(text="Face Checks")
        col.prop(scene, "iyan_uv_detect_face_zero_area")
        col.prop(scene, "iyan_uv_detect_face_tiny_bbox")
        col.prop(scene, "iyan_uv_detect_face_same_uv")
        col.prop(scene, "iyan_uv_face_area_threshold")
        col.prop(scene, "iyan_uv_face_bbox_threshold")
        col.prop(scene, "iyan_uv_same_uv_threshold")

        col.separator()
        col.label(text="Island Checks")
        col.prop(scene, "iyan_uv_detect_island_tiny_bbox")
        col.prop(scene, "iyan_uv_detect_island_thin")
        col.prop(scene, "iyan_uv_island_bbox_threshold")
        col.prop(scene, "iyan_uv_island_thin_ratio")

        col.separator()
        col.label(text="Output")
        col.prop(scene, "iyan_uv_deselect_others")
        col.prop(scene, "iyan_uv_select_result")
        col.prop(scene, "iyan_uv_print_result")

        col.separator()
        col.operator("iyan.uv_validate", text="Validate UV", icon="UV")

        box = layout.box()
        box.label(text="Last Result")
        box.label(text=f"Bad Faces: {scene.iyan_uv_last_bad_faces}")
        box.label(text=f"Bad Islands: {scene.iyan_uv_last_bad_islands}")
        box.label(text=f"No UV Objects: {scene.iyan_uv_last_no_uv_objects}")


classes = (
    IYAN_OT_uv_validate,
    IYAN_PT_uv_panel,
)


def register_props():
    scene = bpy.types.Scene
    scene.iyan_uv_scan_mode = EnumProperty(
        name="Scan Mode",
        items=[("ACTIVE", "Active Object", ""), ("SELECTED", "Selected Objects", "")],
        default="ACTIVE",
    )
    scene.iyan_uv_deselect_others = BoolProperty(name="Deselect Others", default=True)
    scene.iyan_uv_select_result = BoolProperty(name="Select Result", default=True)
    scene.iyan_uv_print_result = BoolProperty(name="Print Result", default=True)
    scene.iyan_uv_face_area_threshold = FloatProperty(name="Face Area Threshold", default=1e-5, min=0.0, precision=10)
    scene.iyan_uv_face_bbox_threshold = FloatProperty(name="Face BBox Threshold", default=1e-3, min=0.0, precision=10)
    scene.iyan_uv_same_uv_threshold = FloatProperty(name="Same UV Threshold", default=1e-4, min=0.0, precision=10)
    scene.iyan_uv_island_bbox_threshold = FloatProperty(name="Island BBox Threshold", default=1e-3, min=0.0, precision=10)
    scene.iyan_uv_island_thin_ratio = FloatProperty(name="Island Thin Ratio", default=0.05, min=0.0, precision=6)
    scene.iyan_uv_detect_face_zero_area = BoolProperty(name="Detect Face Zero Area", default=True)
    scene.iyan_uv_detect_face_tiny_bbox = BoolProperty(name="Detect Face Tiny BBox", default=True)
    scene.iyan_uv_detect_face_same_uv = BoolProperty(name="Detect Face All-Same UV", default=True)
    scene.iyan_uv_detect_island_tiny_bbox = BoolProperty(name="Detect Island Tiny BBox", default=True)
    scene.iyan_uv_detect_island_thin = BoolProperty(name="Detect Island Thin", default=True)
    scene.iyan_uv_last_bad_faces = IntProperty(name="Last Bad Faces", default=0)
    scene.iyan_uv_last_bad_islands = IntProperty(name="Last Bad Islands", default=0)
    scene.iyan_uv_last_no_uv_objects = IntProperty(name="Last No UV Objects", default=0)


def unregister_props():
    props = [
        "iyan_uv_scan_mode",
        "iyan_uv_deselect_others",
        "iyan_uv_select_result",
        "iyan_uv_print_result",
        "iyan_uv_face_area_threshold",
        "iyan_uv_face_bbox_threshold",
        "iyan_uv_same_uv_threshold",
        "iyan_uv_island_bbox_threshold",
        "iyan_uv_island_thin_ratio",
        "iyan_uv_detect_face_zero_area",
        "iyan_uv_detect_face_tiny_bbox",
        "iyan_uv_detect_face_same_uv",
        "iyan_uv_detect_island_tiny_bbox",
        "iyan_uv_detect_island_thin",
        "iyan_uv_last_bad_faces",
        "iyan_uv_last_bad_islands",
        "iyan_uv_last_no_uv_objects",
    ]
    for name in props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


def register():
    register_props()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_props()
