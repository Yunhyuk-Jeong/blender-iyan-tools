import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from .config import ROOT_PANEL_ID, SIDEBAR_CATEGORY


_overlay_handler = None


def active_mesh_object(context):
    obj = context.active_object
    if not obj or obj.type != "MESH":
        return None
    return obj


def ensure_edit_mesh(obj):
    if bpy.context.object != obj:
        bpy.context.view_layer.objects.active = obj
    if obj.mode != "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


def bm_get(obj):
    ensure_edit_mesh(obj)
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm, mesh


def flush_edit_mesh(mesh):
    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def deselect_all(bm):
    for vert in bm.verts:
        vert.select = False
    for edge in bm.edges:
        edge.select = False
    for face in bm.faces:
        face.select = False


def round_vec(vec, decimals):
    return (round(vec.x, decimals), round(vec.y, decimals), round(vec.z, decimals))


def get_active_bmface(bm):
    try:
        return bm.faces.active
    except Exception:
        return None


def scan_loose(bm):
    loose_verts = [vert for vert in bm.verts if len(vert.link_edges) == 0 and len(vert.link_faces) == 0]
    loose_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
    return loose_verts, loose_edges


def scan_degenerate_faces(bm, area_eps):
    faces = []
    for face in bm.faces:
        if len(face.verts) < 3:
            faces.append(face)
            continue
        try:
            if face.calc_area() <= area_eps:
                faces.append(face)
        except Exception:
            faces.append(face)
    return faces


def _face_signature(face, decimals, include_material):
    coords = tuple(sorted(round_vec(vert.co, decimals) for vert in face.verts))
    signature = (len(coords), coords)
    if include_material:
        return signature, int(getattr(face, "material_index", 0))
    return signature


def duplicate_face_groups(bm, decimals, include_material):
    buckets = {}
    for face in bm.faces:
        key = _face_signature(face, decimals, include_material)
        buckets.setdefault(key, []).append(face)
    groups = [(key, faces) for key, faces in buckets.items() if len(faces) >= 2]
    groups.sort(key=lambda pair: str(pair[0]))
    return groups


def duplicate_faces_all(bm, decimals, include_material):
    groups = duplicate_face_groups(bm, decimals, include_material)
    return [face for _key, group in groups for face in group]


def duplicate_faces_split(bm, decimals, include_material, keep_selector):
    groups = duplicate_face_groups(bm, decimals, include_material)
    keep_faces = []
    extras = []
    for _key, group in groups:
        keep = keep_selector(group)
        keep_faces.append(keep)
        for face in group:
            if face is not keep:
                extras.append(face)
    return groups, keep_faces, extras


def duplicate_verts(bm, epsilon):
    if epsilon <= 0.0:
        buckets = {}
        for vert in bm.verts:
            key = (vert.co.x, vert.co.y, vert.co.z)
            buckets.setdefault(key, []).append(vert)
        groups = [group for group in buckets.values() if len(group) >= 2]
        return [vert for group in groups for vert in group], groups

    inv = 1.0 / epsilon
    buckets = {}
    for vert in bm.verts:
        key = (int(vert.co.x * inv), int(vert.co.y * inv), int(vert.co.z * inv))
        buckets.setdefault(key, []).append(vert)
    groups = [group for group in buckets.values() if len(group) >= 2]
    return [vert for group in groups for vert in group], groups


def _draw_overlay():
    scene = bpy.context.scene
    if not scene or not hasattr(scene, "mesh_cleanup_props"):
        return

    props = scene.mesh_cleanup_props
    if not props.overlay_enabled:
        return

    try:
        import blf
    except Exception:
        return

    lines = [
        "Mesh Cleanup",
        f"Loose V/E: {props.last_loose_v}/{props.last_loose_e}",
        f"Deg Faces: {props.last_deg_f}",
        f"Dup Groups: {props.last_dup_groups}  Extras: {props.last_dup_extras}",
        f"Dup Vert Groups: {props.last_dup_verts_groups}",
        f"Group Index: {props.group_index}  Nav Mode: {props.group_select_mode}",
        f"Keep: {props.dup_keep_strategy}  MatKey: {'ON' if props.dup_include_material else 'OFF'}",
    ]

    x = 20
    y = 60
    font_size = int(props.overlay_font_size)
    blf.size(0, font_size)
    for index, line in enumerate(lines):
        blf.position(0, x, y + index * (font_size + 4), 0)
        blf.draw(0, line)


def ensure_overlay_handler():
    global _overlay_handler
    if _overlay_handler is not None:
        return
    _overlay_handler = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (), "WINDOW", "POST_PIXEL")


def remove_overlay_handler():
    global _overlay_handler
    if _overlay_handler is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_overlay_handler, "WINDOW")
    except Exception:
        pass
    _overlay_handler = None


class MeshCleanupProps(bpy.types.PropertyGroup):
    epsilon: FloatProperty(name="Merge Distance", description="Vertex merge distance for remove doubles", default=0.0001, min=0.0, precision=6)
    face_hash_decimals: IntProperty(name="Face Hash Precision", description="Rounding precision for duplicate-face detection", default=6, min=0, max=10)
    area_epsilon: FloatProperty(name="Degenerate Area", description="Faces with area <= this are treated as degenerate", default=1e-12, min=0.0, precision=12)
    auto_deselect: BoolProperty(name="Auto Deselect", description="Deselect everything before selecting scan results", default=True)
    dup_include_material: BoolProperty(name="Include Material in Dup Key", description="Duplicate-face grouping also requires same material index", default=False)
    dup_keep_strategy: EnumProperty(
        name="Keep Strategy",
        description="Which face to keep when removing fully-overlapping duplicates",
        items=[
            ("FIRST", "Keep First", ""),
            ("ACTIVE", "Keep Active", ""),
            ("MATERIAL", "Prefer Active Material", ""),
            ("SMOOTH", "Prefer Smooth", ""),
        ],
        default="ACTIVE",
    )
    safe_delete_block_keep_faces: BoolProperty(name="Safe Delete: Block Keep Faces", description="Refuse to delete chosen keep faces from duplicate groups", default=True)
    group_index: IntProperty(name="Group Index", default=0, min=0)
    group_select_mode: EnumProperty(
        name="Nav Select Mode",
        items=[
            ("EXTRAS", "Extras", ""),
            ("ALL", "All Faces", ""),
            ("KEEP", "Keep Face", ""),
        ],
        default="EXTRAS",
    )
    overlay_enabled: BoolProperty(name="Overlay Enabled", default=True)
    overlay_font_size: IntProperty(name="Overlay Font Size", default=14, min=8, max=48)
    last_loose_v: IntProperty(default=0)
    last_loose_e: IntProperty(default=0)
    last_deg_f: IntProperty(default=0)
    last_dup_groups: IntProperty(default=0)
    last_dup_extras: IntProperty(default=0)
    last_dup_verts_groups: IntProperty(default=0)
    store_vgroup_name: StringProperty(name="VGroup Name", default="MC_Issues")


def _make_keep_selector(bm, props):
    active_face = get_active_bmface(bm)
    active_material = getattr(active_face, "material_index", None) if active_face else None
    strategy = props.dup_keep_strategy

    def keep_first(group):
        return group[0]

    def keep_active(group):
        if active_face is not None:
            for face in group:
                if face is active_face:
                    return face
        return group[0]

    def keep_material(group):
        if active_material is not None:
            for face in group:
                if getattr(face, "material_index", None) == active_material:
                    return face
        return group[0]

    def keep_smooth(group):
        for face in group:
            if getattr(face, "smooth", False):
                return face
        return group[0]

    if strategy == "ACTIVE":
        return keep_active
    if strategy == "MATERIAL":
        return keep_material
    if strategy == "SMOOTH":
        return keep_smooth
    return keep_first


def _get_dup_groups_and_split(bm, props):
    keep_selector = _make_keep_selector(bm, props)
    return duplicate_faces_split(bm, props.face_hash_decimals, props.dup_include_material, keep_selector)


def _select_group(bm, props, group_index, mode):
    groups = duplicate_face_groups(bm, props.face_hash_decimals, props.dup_include_material)
    if not groups:
        return 0, 0
    index = group_index % len(groups)
    _key, faces = groups[index]
    keep_selector = _make_keep_selector(bm, props)
    keep_face = keep_selector(faces)

    if mode == "ALL":
        for face in faces:
            face.select = True
        return index, len(faces)
    if mode == "KEEP":
        keep_face.select = True
        return index, 1

    count = 0
    for face in faces:
        if face is not keep_face:
            face.select = True
            count += 1
    return index, count


class MESH_OT_cleanup_scan(bpy.types.Operator):
    bl_idname = "mesh_cleanup.scan"
    bl_label = "Scan Issues (Select)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        if props.auto_deselect:
            deselect_all(bm)

        loose_v, loose_e = scan_loose(bm)
        deg_f = scan_degenerate_faces(bm, props.area_epsilon)
        groups, keep_faces, dup_f_extras = _get_dup_groups_and_split(bm, props)
        dup_v, dup_v_groups = duplicate_verts(bm, props.epsilon)

        for vert in loose_v:
            vert.select = True
        for edge in loose_e:
            edge.select = True
        for face in deg_f:
            face.select = True
        for face in dup_f_extras:
            face.select = True
        for vert in dup_v:
            vert.select = True
        flush_edit_mesh(mesh)

        props.last_loose_v = len(loose_v)
        props.last_loose_e = len(loose_e)
        props.last_deg_f = len(deg_f)
        props.last_dup_groups = len(groups)
        props.last_dup_extras = len(dup_f_extras)
        props.last_dup_verts_groups = len(dup_v_groups)
        props.group_index = 0

        self.report({"INFO"}, f"looseV:{props.last_loose_v} looseE:{props.last_loose_e} degF:{props.last_deg_f} dupGroups:{props.last_dup_groups} dupExtras:{props.last_dup_extras} dupVGroups:{props.last_dup_verts_groups}")
        return {"FINISHED"}


class MESH_OT_cleanup_select_only(bpy.types.Operator):
    bl_idname = "mesh_cleanup.select_only"
    bl_label = "Select Only"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=[
        ("LOOSE", "Loose", ""),
        ("DEGENERATE", "Degenerate", ""),
        ("DUP_FACES_ALL", "Dup Faces (All)", ""),
        ("DUP_FACES_EXTRAS", "Dup Faces (Extras)", ""),
        ("DUP_FACES_KEEP", "Dup Faces (Keep)", ""),
        ("DUP_VERTS", "Dup Verts", ""),
    ])

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        deselect_all(bm)

        if self.mode == "LOOSE":
            loose_v, loose_e = scan_loose(bm)
            for vert in loose_v:
                vert.select = True
            for edge in loose_e:
                edge.select = True
            self.report({"INFO"}, f"looseV:{len(loose_v)} looseE:{len(loose_e)}")
        elif self.mode == "DEGENERATE":
            faces = scan_degenerate_faces(bm, props.area_epsilon)
            for face in faces:
                face.select = True
            self.report({"INFO"}, f"degF:{len(faces)}")
        elif self.mode == "DUP_FACES_ALL":
            faces = duplicate_faces_all(bm, props.face_hash_decimals, props.dup_include_material)
            for face in faces:
                face.select = True
            self.report({"INFO"}, f"dupF_all:{len(faces)}")
        elif self.mode == "DUP_FACES_EXTRAS":
            groups, keep_faces, extras = _get_dup_groups_and_split(bm, props)
            for face in extras:
                face.select = True
            self.report({"INFO"}, f"dupGroups:{len(groups)} extras:{len(extras)}")
        elif self.mode == "DUP_FACES_KEEP":
            groups, keep_faces, extras = _get_dup_groups_and_split(bm, props)
            for face in keep_faces:
                face.select = True
            self.report({"INFO"}, f"dupGroups:{len(groups)} keep:{len(keep_faces)}")
        elif self.mode == "DUP_VERTS":
            verts, groups = duplicate_verts(bm, props.epsilon)
            for vert in verts:
                vert.select = True
            self.report({"INFO"}, f"dupV_groups:{len(groups)} dupV:{len(verts)}")

        flush_edit_mesh(mesh)
        return {"FINISHED"}


class MESH_OT_cleanup_delete_selected_safe(bpy.types.Operator):
    bl_idname = "mesh_cleanup.delete_selected_safe"
    bl_label = "Delete Selected (Guarded)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        sel_faces = [face for face in bm.faces if face.select]
        sel_edges = [edge for edge in bm.edges if edge.select]
        sel_verts = [vert for vert in bm.verts if vert.select]

        if props.safe_delete_block_keep_faces and sel_faces:
            groups, keep_faces, extras = _get_dup_groups_and_split(bm, props)
            keep_set = set(keep_faces)
            hit = [face for face in sel_faces if face in keep_set]
            if hit:
                self.report({"ERROR"}, "Safe Delete blocked: selection includes KEEP faces from duplicate groups.")
                return {"CANCELLED"}

        if sel_faces:
            bmesh.ops.delete(bm, geom=sel_faces, context="FACES_ONLY")
        if sel_edges:
            bmesh.ops.delete(bm, geom=sel_edges, context="EDGES")
        if sel_verts:
            bmesh.ops.delete(bm, geom=sel_verts, context="VERTS")

        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"deleted F:{len(sel_faces)} E:{len(sel_edges)} V:{len(sel_verts)}")
        return {"FINISHED"}


class MESH_OT_cleanup_merge_selected_verts(bpy.types.Operator):
    bl_idname = "mesh_cleanup.merge_selected_verts"
    bl_label = "Merge Selected Verts"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        sel_verts = [vert for vert in bm.verts if vert.select]
        if not sel_verts:
            self.report({"WARNING"}, "No selected verts.")
            return {"CANCELLED"}

        before = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=sel_verts, dist=props.epsilon)
        after = len(bm.verts)
        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"remove_doubles: verts {before} -> {after}")
        return {"FINISHED"}


class MESH_OT_cleanup_delete_dup_faces_keep_one(bpy.types.Operator):
    bl_idname = "mesh_cleanup.delete_dup_faces_keep_one"
    bl_label = "Delete Duplicate Faces (Keep One)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        groups, keep_faces, extras = _get_dup_groups_and_split(bm, props)
        if not extras:
            self.report({"INFO"}, "No duplicate faces found.")
            return {"CANCELLED"}

        bmesh.ops.delete(bm, geom=extras, context="FACES_ONLY")
        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"Deleted dup faces: {len(extras)} (groups:{len(groups)} kept:{len(keep_faces)})")
        return {"FINISHED"}


class MESH_OT_cleanup_quick_fix(bpy.types.Operator):
    bl_idname = "mesh_cleanup.quick_fix"
    bl_label = "Quick Fix"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)

        loose_v, _loose_e = scan_loose(bm)
        if loose_v:
            bmesh.ops.delete(bm, geom=loose_v, context="VERTS")
        if props.epsilon > 0.0:
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=props.epsilon)
        deg_f = scan_degenerate_faces(bm, props.area_epsilon)
        if deg_f:
            bmesh.ops.delete(bm, geom=deg_f, context="FACES_ONLY")
        groups, keep_faces, extras = _get_dup_groups_and_split(bm, props)
        if extras:
            bmesh.ops.delete(bm, geom=extras, context="FACES_ONLY")

        flush_edit_mesh(mesh)
        props.last_loose_v = len(loose_v)
        props.last_loose_e = 0
        props.last_deg_f = len(deg_f)
        props.last_dup_groups = len(groups)
        props.last_dup_extras = len(extras)
        self.report({"INFO"}, f"QuickFix: deadV:{len(loose_v)} degF:{len(deg_f)} dupExtras:{len(extras)}")
        return {"FINISHED"}


class MESH_OT_cleanup_store_selection_vgroup(bpy.types.Operator):
    bl_idname = "mesh_cleanup.store_selection_vgroup"
    bl_label = "Store Selection to VGroup (Verts)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        group_name = (props.store_vgroup_name or "MC_Issues").strip() or "MC_Issues"
        vertex_group = obj.vertex_groups.get(group_name)
        if vertex_group is None:
            vertex_group = obj.vertex_groups.new(name=group_name)

        bm, _mesh = bm_get(obj)
        selected_indices = [vert.index for vert in bm.verts if vert.select]
        if not selected_indices:
            self.report({"WARNING"}, "No selected verts to store.")
            return {"CANCELLED"}

        vertex_group.add(selected_indices, 1.0, "REPLACE")
        self.report({"INFO"}, f"Stored {len(selected_indices)} verts to '{group_name}'")
        return {"FINISHED"}


class MESH_OT_cleanup_restore_selection_vgroup(bpy.types.Operator):
    bl_idname = "mesh_cleanup.restore_selection_vgroup"
    bl_label = "Restore Selection from VGroup (Verts)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        group_name = (props.store_vgroup_name or "MC_Issues").strip() or "MC_Issues"
        vertex_group = obj.vertex_groups.get(group_name)
        if vertex_group is None:
            self.report({"ERROR"}, f"Vertex group '{group_name}' not found.")
            return {"CANCELLED"}

        bm, mesh = bm_get(obj)
        deselect_all(bm)
        selected = 0
        for vert in bm.verts:
            try:
                if vertex_group.weight(vert.index) > 0.0:
                    vert.select = True
                    selected += 1
            except RuntimeError:
                pass

        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"Restored {selected} verts from '{group_name}'")
        return {"FINISHED"}


class MESH_OT_cleanup_group_next(bpy.types.Operator):
    bl_idname = "mesh_cleanup.group_next"
    bl_label = "Next Dup Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        groups = duplicate_face_groups(bm, props.face_hash_decimals, props.dup_include_material)
        if not groups:
            self.report({"INFO"}, "No duplicate face groups.")
            return {"CANCELLED"}

        props.group_index = (props.group_index + 1) % len(groups)
        deselect_all(bm)
        index, count = _select_group(bm, props, props.group_index, props.group_select_mode)
        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"Group {index + 1}/{len(groups)} selected ({props.group_select_mode}) count:{count}")
        return {"FINISHED"}


class MESH_OT_cleanup_group_prev(bpy.types.Operator):
    bl_idname = "mesh_cleanup.group_prev"
    bl_label = "Prev Dup Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_overlay_handler()
        obj = active_mesh_object(context)
        if not obj:
            self.report({"ERROR"}, "Active object is not a mesh.")
            return {"CANCELLED"}

        props = context.scene.mesh_cleanup_props
        bm, mesh = bm_get(obj)
        groups = duplicate_face_groups(bm, props.face_hash_decimals, props.dup_include_material)
        if not groups:
            self.report({"INFO"}, "No duplicate face groups.")
            return {"CANCELLED"}

        props.group_index = (props.group_index - 1) % len(groups)
        deselect_all(bm)
        index, count = _select_group(bm, props, props.group_index, props.group_select_mode)
        flush_edit_mesh(mesh)
        self.report({"INFO"}, f"Group {index + 1}/{len(groups)} selected ({props.group_select_mode}) count:{count}")
        return {"FINISHED"}


class MESH_OT_cleanup_toggle_overlay(bpy.types.Operator):
    bl_idname = "mesh_cleanup.toggle_overlay"
    bl_label = "Toggle Overlay"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.mesh_cleanup_props
        props.overlay_enabled = not props.overlay_enabled
        self.report({"INFO"}, f"Overlay {'ON' if props.overlay_enabled else 'OFF'}")
        return {"FINISHED"}


class VIEW3D_PT_mesh_cleanup(bpy.types.Panel):
    bl_label = "Mesh Cleanup"
    bl_idname = "VIEW3D_PT_mesh_cleanup"
    bl_parent_id = ROOT_PANEL_ID
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        props = context.scene.mesh_cleanup_props

        box = layout.box()
        box.label(text="Thresholds")
        box.prop(props, "epsilon")
        box.prop(props, "face_hash_decimals")
        box.prop(props, "area_epsilon")

        box = layout.box()
        box.label(text="Duplicate Face Options")
        box.prop(props, "dup_include_material")
        box.prop(props, "dup_keep_strategy")

        box = layout.box()
        box.label(text="Safety")
        box.prop(props, "safe_delete_block_keep_faces")

        box = layout.box()
        box.label(text="Overlay / Navigation")
        row = box.row(align=True)
        row.prop(props, "overlay_enabled", text="Overlay")
        row.prop(props, "overlay_font_size", text="Size")
        row.operator("mesh_cleanup.toggle_overlay", text="Toggle")
        box.prop(props, "group_select_mode")
        nav = box.row(align=True)
        nav.operator("mesh_cleanup.group_prev", text="Prev")
        nav.operator("mesh_cleanup.group_next", text="Next")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Scan & Select")
        col.operator("mesh_cleanup.scan", icon="VIEWZOOM")

        row = col.row(align=True)
        op = row.operator("mesh_cleanup.select_only", text="Loose", icon="VERTEXSEL")
        op.mode = "LOOSE"
        op = row.operator("mesh_cleanup.select_only", text="Degenerate", icon="FACESEL")
        op.mode = "DEGENERATE"

        row = col.row(align=True)
        op = row.operator("mesh_cleanup.select_only", text="Dup Faces All", icon="FACESEL")
        op.mode = "DUP_FACES_ALL"
        op = row.operator("mesh_cleanup.select_only", text="Dup Faces Extras", icon="FACESEL")
        op.mode = "DUP_FACES_EXTRAS"

        row = col.row(align=True)
        op = row.operator("mesh_cleanup.select_only", text="Dup Faces Keep", icon="FACESEL")
        op.mode = "DUP_FACES_KEEP"
        op = row.operator("mesh_cleanup.select_only", text="Dup Verts", icon="VERTEXSEL")
        op.mode = "DUP_VERTS"

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Fix")
        col.operator("mesh_cleanup.delete_selected_safe", icon="TRASH")
        col.operator("mesh_cleanup.delete_dup_faces_keep_one", icon="X")
        col.operator("mesh_cleanup.merge_selected_verts", icon="AUTOMERGE_ON")
        col.operator("mesh_cleanup.quick_fix", icon="CHECKMARK")

        layout.separator()
        box = layout.box()
        box.label(text="Selection Memory (Verts)")
        box.prop(props, "store_vgroup_name")
        row = box.row(align=True)
        row.operator("mesh_cleanup.store_selection_vgroup", text="Store")
        row.operator("mesh_cleanup.restore_selection_vgroup", text="Restore")

        layout.separator()
        box = layout.box()
        box.label(text="Last Scan Stats")
        box.label(text=f"Loose V/E: {props.last_loose_v}/{props.last_loose_e}")
        box.label(text=f"Deg Faces: {props.last_deg_f}")
        box.label(text=f"Dup Groups: {props.last_dup_groups}  Extras: {props.last_dup_extras}")
        box.label(text=f"Dup Vert Groups: {props.last_dup_verts_groups}")


classes = (
    MeshCleanupProps,
    MESH_OT_cleanup_scan,
    MESH_OT_cleanup_select_only,
    MESH_OT_cleanup_delete_selected_safe,
    MESH_OT_cleanup_merge_selected_verts,
    MESH_OT_cleanup_delete_dup_faces_keep_one,
    MESH_OT_cleanup_quick_fix,
    MESH_OT_cleanup_store_selection_vgroup,
    MESH_OT_cleanup_restore_selection_vgroup,
    MESH_OT_cleanup_group_next,
    MESH_OT_cleanup_group_prev,
    MESH_OT_cleanup_toggle_overlay,
    VIEW3D_PT_mesh_cleanup,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mesh_cleanup_props = bpy.props.PointerProperty(type=MeshCleanupProps)
    ensure_overlay_handler()


def unregister():
    remove_overlay_handler()
    if hasattr(bpy.types.Scene, "mesh_cleanup_props"):
        del bpy.types.Scene.mesh_cleanup_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
