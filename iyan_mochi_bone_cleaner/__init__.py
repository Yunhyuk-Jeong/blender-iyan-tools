
bl_info = {
    "name": "Iyan Mochi Bone Cleaner",
    "author": "Iyan-Kim",
    "version": (1, 0, 1),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > MBC",
    "description": "Classify and clean retargeted / generated bones safely",
    "category": "Rigging",
}

import bpy
import re
from bpy.types import Operator, Panel, PropertyGroup, UIList
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

RESULT_ITEMS = [
    ("SAFE_DELETE", "SAFE_DELETE", ""),
    ("REVIEW", "REVIEW", ""),
    ("KEEP", "KEEP", ""),
    ("PROTECTED", "PROTECTED", ""),
]

GENERATED_HINTS = {
    "orig", "ors", "original", "retarget", "generated", "gen",
    "copy", "tmp", "temp", "new", "bak", "old", "dup", "duplicate"
}

HELPER_HINTS = {
    "helper", "dummy", "offset", "target", "end", "tip", "twist",
    "socket", "null", "aux", "sub"
}

PROTECTED_NAMES = {
    "hips", "pelvis", "root", "armature", "center", "centre"
}

HUMANOID_CORE = {
    "hips", "pelvis", "spine", "chest", "neck", "head",
    "shoulder", "upperarm", "lowerarm", "hand",
    "thigh", "calf", "foot", "toe",
    "eye", "jaw",
    # Common Unity humanoid exact names / aliases
    "upperleg", "lowerleg", "forearm", "clavicle", "wrist", "ankle"
}

CATEGORY_ALIASES = {
    "pelvis": {"hips", "pelvis"},
    "spine": {"spine", "waist", "abdomen", "torso", "body"},
    "chest": {"chest", "upperchest", "upper_torso"},
    "neck": {"neck"},
    "head": {"head"},
    "shoulder": {"shoulder", "clavicle", "collar"},
    "upperarm": {"upperarm", "arm_upper", "uparm", "upper_arm"},
    "lowerarm": {"lowerarm", "forearm", "arm_lower", "lower_arm"},
    "hand": {"hand", "wrist"},
    "thigh": {"thigh", "upleg", "upperleg", "leg_upper"},
    "calf": {"calf", "lowerleg", "leg_lower", "shin"},
    "foot": {"foot", "ankle"},
    "toe": {"toe", "toes"},
    "eye": {"eye", "eyeball"},
    "jaw": {"jaw", "chin"},
    "hair": {"hair", "bang", "fronthair", "sidehair", "backhair", "ahoge"},
    "skirt": {"skirt", "skt", "sk"},
    "breast": {"breast", "bust"},
    "tail": {"tail"},
    "ear": {"ear"},
    "horn": {"horn"},
    "wing": {"wing"},
}

# Reverse alias map for quick canonicalization
ALIAS_TO_CATEGORY = {}
for canonical, aliases in CATEGORY_ALIASES.items():
    for a in aliases:
        ALIAS_TO_CATEGORY[a] = canonical


class IMBC_BoneItem(PropertyGroup):
    bone_name: StringProperty(name="Bone Name")
    auto_result: EnumProperty(name="Auto Result", items=RESULT_ITEMS, default="REVIEW")
    final_result: EnumProperty(name="Final Result", items=RESULT_ITEMS, default="REVIEW")
    reason: StringProperty(name="Reason", default="")
    has_weight: BoolProperty(name="Has Weight", default=False)
    has_child: BoolProperty(name="Has Child", default=False)
    outfit_match: StringProperty(name="Outfit Match", default="N/A")
    avatar_match: StringProperty(name="Avatar Match", default="N/A")
    flags_text: StringProperty(name="Flags", default="")
    is_overridden: BoolProperty(name="Overridden", default=False)


def get_target_armature(context):
    scene = context.scene
    arm = scene.imbc_mochi_output_armature
    if arm and arm.type == 'ARMATURE':
        return arm
    obj = context.object
    if obj and obj.type == 'ARMATURE':
        return obj
    return None


def _split_camel_and_mixed(name: str):
    # Split camel case boundaries first
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", s)
    # Explicitly split common generated prefixes when glued together
    s = re.sub(r"(?i)(orig)(ors)", r"\1_\2", s)
    s = re.sub(r"(?i)(ors)([A-Z])", r"\1_\2", s)
    s = re.sub(r"(?i)(orig)([A-Z])", r"\1_\2", s)
    s = re.sub(r"(?i)(retarget)([A-Z])", r"\1_\2", s)
    s = re.sub(r"(?i)(copy)([A-Z])", r"\1_\2", s)
    return s


def tokenize_name(name: str):
    s = _split_camel_and_mixed(name)
    s = re.sub(r"\.\d+$", "", s)  # blender suffix
    s = s.replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_")

    raw_tokens = [t for t in s.split("_") if t]
    tokens = []

    for t in raw_tokens:
        lower_t = t.lower()

        # Split glued generated prefixes from remaining token, e.g. origorships -> orig ors hips
        changed = True
        parts = [lower_t]
        while changed:
            changed = False
            new_parts = []
            for p in parts:
                matched = False
                for prefix in sorted(GENERATED_HINTS | HELPER_HINTS, key=len, reverse=True):
                    if p.startswith(prefix) and p != prefix:
                        rest = p[len(prefix):]
                        if rest:
                            new_parts.append(prefix)
                            new_parts.append(rest)
                            changed = True
                            matched = True
                            break
                if not matched:
                    new_parts.append(p)
            parts = new_parts

        for p in parts:
            extracted = re.findall(r"[a-zA-Z]+|\d+|[가-힣ぁ-んァ-ヴー一-龯]+", p)
            if extracted:
                tokens.extend([x.lower() for x in extracted if x])
            else:
                tokens.append(p.lower())

    # Normalize common aliases to canonical category names where safe
    normalized = []
    for t in tokens:
        normalized.append(ALIAS_TO_CATEGORY.get(t, t))
    return normalized


def bone_has_actual_weight(arm_obj, bone_name: str):
    if not arm_obj:
        return False

    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue

        uses_arm = False
        if obj.parent == arm_obj:
            uses_arm = True
        else:
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and getattr(mod, "object", None) == arm_obj:
                    uses_arm = True
                    break
        if not uses_arm:
            continue

        vg = obj.vertex_groups.get(bone_name)
        if vg is None:
            continue

        vg_index = vg.index
        for v in obj.data.vertices:
            for g in v.groups:
                if g.group == vg_index and g.weight > 0.0001:
                    return True
    return False


def exact_name_exists(name: str, ref_arm):
    if not ref_arm or ref_arm.type != 'ARMATURE':
        return False
    return name in {b.name for b in ref_arm.data.bones}


def get_core_tokens(tokens):
    return [t for t in tokens if t not in GENERATED_HINTS and t not in HELPER_HINTS and not t.isdigit()]


def infer_match_level(name: str, ref_arm):
    if not ref_arm or ref_arm.type != 'ARMATURE':
        return "N/A"

    bone_names = {b.name for b in ref_arm.data.bones}
    if name in bone_names:
        return "strong"

    tokens = tokenize_name(name)
    if not tokens:
        return "none"

    candidate_core = get_core_tokens(tokens)
    if not candidate_core:
        candidate_core = [t for t in tokens if not t.isdigit()]
    if not candidate_core:
        return "none"

    for ref_name in bone_names:
        ref_tokens = tokenize_name(ref_name)
        ref_core = get_core_tokens(ref_tokens)
        if not ref_core:
            ref_core = [t for t in ref_tokens if not t.isdigit()]

        if candidate_core == ref_core:
            # Same core, but only exact original name should be strong
            return "generated_core"

        # Tail-token weak match only
        if candidate_core and ref_core and candidate_core[-1] == ref_core[-1]:
            if set(candidate_core) != set(ref_core):
                return "weak"

    return "none"


def classify_bone(bone, arm_obj, outfit_arm=None, avatar_arm=None):
    name = bone.name
    lower_name = name.lower()
    has_child = len(bone.children) > 0
    has_weight = bone_has_actual_weight(arm_obj, name)

    tokens = tokenize_name(name)
    token_set = set(tokens)
    core_tokens = get_core_tokens(tokens)

    outfit_match = infer_match_level(name, outfit_arm)
    avatar_match = infer_match_level(name, avatar_arm)

    flags = []

    if token_set & GENERATED_HINTS:
        flags.append("generated_like")
    if token_set & HELPER_HINTS:
        flags.append("helper_like")

    exact_outfit = exact_name_exists(name, outfit_arm)
    exact_avatar = exact_name_exists(name, avatar_arm)

    core_category = core_tokens[-1] if core_tokens else None
    core_is_humanoid = core_category in HUMANOID_CORE or core_category in ALIAS_TO_CATEGORY.values()

    # Important: prefix+humanoid pattern like origORS_Hips should be treated as generated-like
    extra_noncore_tokens = [t for t in tokens if t not in core_tokens and not t.isdigit()]
    if core_is_humanoid:
        if len(core_tokens) == 1 and len(tokens) > 1:
            flags.append("prefixed_humanoid_like")
        if extra_noncore_tokens:
            flags.append("extra_unmatched_token")

    if lower_name in PROTECTED_NAMES:
        flags.append("protected_name")

    # Explicit protection
    if lower_name in PROTECTED_NAMES:
        return ("PROTECTED", "Protected root-like name", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    # Actual deformation usage always wins
    if has_weight:
        return ("KEEP", "Has actual vertex weight", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    # Only exact name matches are strong protection
    if exact_outfit or exact_avatar:
        return ("KEEP", "Exact name match to outfit/avatar", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    # Very important tuned rule:
    # prefix/generated/helper humanoid leftovers like origORS_Hips should safely delete if unused leaf
    if ("generated_like" in flags or "prefixed_humanoid_like" in flags or "helper_like" in flags):
        if not has_child:
            return ("SAFE_DELETE", "Generated/prefixed humanoid or helper leftover + no child", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))
        return ("REVIEW", "Generated/prefixed humanoid or helper-like but has child", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    # Weak/generated core match should no longer protect unused leaf bones
    if outfit_match in {"weak", "generated_core"} or avatar_match in {"weak", "generated_core"}:
        if not has_child:
            return ("SAFE_DELETE", "Weak/generated core match + no child + no weight", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))
        return ("REVIEW", "Weak/generated core match with child chain", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    if not has_child:
        return ("SAFE_DELETE", "No weight + no child + no exact match", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))

    return ("REVIEW", "Structural bone without strong usage evidence", has_weight, has_child, outfit_match, avatar_match, ", ".join(sorted(set(flags))))


def filtered_items(scene):
    result = []
    for item in scene.imbc_bones:
        r = item.final_result
        if r == "SAFE_DELETE" and not scene.imbc_show_safe_delete:
            continue
        if r == "REVIEW" and not scene.imbc_show_review:
            continue
        if r == "KEEP" and not scene.imbc_show_keep:
            continue
        if r == "PROTECTED" and not scene.imbc_show_protected:
            continue
        result.append(item)
    return result


def summary_counts(scene):
    counts = {"SAFE_DELETE": 0, "REVIEW": 0, "KEEP": 0, "PROTECTED": 0}
    for item in scene.imbc_bones:
        counts[item.final_result] = counts.get(item.final_result, 0) + 1
    return counts


def selected_item(scene):
    idx = scene.imbc_bones_index
    if 0 <= idx < len(scene.imbc_bones):
        return scene.imbc_bones[idx]
    return None


class IMBC_OT_Analyze(bpy.types.Operator):
    bl_idname = "imbc.analyze"
    bl_label = "Analyze Bones"
    bl_description = "Analyze current Mochi output armature bones"

    def execute(self, context):
        scene = context.scene
        arm = get_target_armature(context)
        if not arm:
            self.report({'ERROR'}, "Select an armature or assign Mochi Output Armature")
            return {'CANCELLED'}

        scene.imbc_bones.clear()
        scene.imbc_bones_index = 0

        outfit_arm = scene.imbc_original_outfit_armature
        avatar_arm = scene.imbc_avatar_armature

        for bone in arm.data.bones:
            auto, reason, has_weight, has_child, outfit_match, avatar_match, flags_text = classify_bone(
                bone, arm, outfit_arm, avatar_arm
            )
            item = scene.imbc_bones.add()
            item.bone_name = bone.name
            item.auto_result = auto
            item.final_result = auto
            item.reason = reason
            item.has_weight = has_weight
            item.has_child = has_child
            item.outfit_match = outfit_match
            item.avatar_match = avatar_match
            item.flags_text = flags_text
            item.is_overridden = False

        self.report({'INFO'}, f"Analyzed {len(scene.imbc_bones)} bones")
        return {'FINISHED'}


class IMBC_OT_DeleteSafe(bpy.types.Operator):
    bl_idname = "imbc.delete_safe"
    bl_label = "Delete SAFE_DELETE Bones"
    bl_description = "Delete bones whose Final Result is SAFE_DELETE"

    def execute(self, context):
        scene = context.scene
        arm = get_target_armature(context)
        if not arm:
            self.report({'ERROR'}, "Select an armature or assign Mochi Output Armature")
            return {'CANCELLED'}

        if context.object != arm:
            bpy.ops.object.select_all(action='DESELECT')
            arm.select_set(True)
            context.view_layer.objects.active = arm

        prior_mode = arm.mode
        if prior_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.mode_set(mode='EDIT')
        ebones = arm.data.edit_bones

        deleted = 0
        names_to_delete = [item.bone_name for item in scene.imbc_bones if item.final_result == "SAFE_DELETE"]

        for bone_name in names_to_delete:
            eb = ebones.get(bone_name)
            if eb:
                ebones.remove(eb)
                deleted += 1

        bpy.ops.object.mode_set(mode='OBJECT')

        keep_entries = [item for item in scene.imbc_bones if item.final_result != "SAFE_DELETE"]
        snapshot = [{
            "bone_name": i.bone_name,
            "auto_result": i.auto_result,
            "final_result": i.final_result,
            "reason": i.reason,
            "has_weight": i.has_weight,
            "has_child": i.has_child,
            "outfit_match": i.outfit_match,
            "avatar_match": i.avatar_match,
            "flags_text": i.flags_text,
            "is_overridden": i.is_overridden,
        } for i in keep_entries]

        scene.imbc_bones.clear()
        for src in snapshot:
            item = scene.imbc_bones.add()
            for k, v in src.items():
                setattr(item, k, v)

        scene.imbc_bones_index = min(scene.imbc_bones_index, max(0, len(scene.imbc_bones) - 1))
        self.report({'INFO'}, f"Deleted {deleted} bones")
        return {'FINISHED'}


class IMBC_OT_SetOverride(bpy.types.Operator):
    bl_idname = "imbc.set_override"
    bl_label = "Set Override"

    new_result: EnumProperty(items=RESULT_ITEMS, default="REVIEW")

    def execute(self, context):
        item = selected_item(context.scene)
        if not item:
            return {'CANCELLED'}
        item.final_result = self.new_result
        item.is_overridden = (item.final_result != item.auto_result)
        return {'FINISHED'}


class IMBC_OT_ResetOverride(bpy.types.Operator):
    bl_idname = "imbc.reset_override"
    bl_label = "Reset Override"

    def execute(self, context):
        item = selected_item(context.scene)
        if not item:
            return {'CANCELLED'}
        item.final_result = item.auto_result
        item.is_overridden = False
        return {'FINISHED'}


class IMBC_OT_FilterPresetCandidates(bpy.types.Operator):
    bl_idname = "imbc.filter_preset_candidates"
    bl_label = "Candidates Only"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = True
        scene.imbc_show_review = True
        scene.imbc_show_keep = False
        scene.imbc_show_protected = False
        return {'FINISHED'}


class IMBC_OT_FilterAll(bpy.types.Operator):
    bl_idname = "imbc.filter_all"
    bl_label = "All"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = True
        scene.imbc_show_review = True
        scene.imbc_show_keep = True
        scene.imbc_show_protected = True
        return {'FINISHED'}


class IMBC_OT_FilterNone(bpy.types.Operator):
    bl_idname = "imbc.filter_none"
    bl_label = "None"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = False
        scene.imbc_show_review = False
        scene.imbc_show_keep = False
        scene.imbc_show_protected = False
        return {'FINISHED'}


def result_icon(result):
    return {
        "SAFE_DELETE": 'TRASH',
        "REVIEW": 'QUESTION',
        "KEEP": 'CHECKMARK',
        "PROTECTED": 'LOCKED',
    }.get(result, 'DOT')


class IMBC_UL_BoneResults(UIList):
    bl_idname = "IMBC_UL_bone_results"

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = []
        for item in items:
            visible = True
            if item.final_result == "SAFE_DELETE" and not data.imbc_show_safe_delete:
                visible = False
            elif item.final_result == "REVIEW" and not data.imbc_show_review:
                visible = False
            elif item.final_result == "KEEP" and not data.imbc_show_keep:
                visible = False
            elif item.final_result == "PROTECTED" and not data.imbc_show_protected:
                visible = False
            flags.append(self.bitflag_filter_item if visible else 0)
        return flags, []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text="", icon=result_icon(item.final_result))
            row.label(text=item.bone_name)
            text = item.final_result + (" *" if item.is_overridden else "")
            row.label(text=text)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon=result_icon(item.final_result))


class IMBC_PT_Main(Panel):
    bl_label = "Iyan Mochi Bone Cleaner"
    bl_idname = "IMBC_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MBC'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        counts = summary_counts(scene)

        col = layout.column(align=True)
        col.label(text="Inputs")
        col.prop(scene, "imbc_original_outfit_armature")
        col.prop(scene, "imbc_avatar_armature")
        col.prop(scene, "imbc_mochi_output_armature")

        col.separator()
        row = col.row(align=True)
        row.operator("imbc.analyze", icon='VIEWZOOM')
        row.operator("imbc.delete_safe", icon='TRASH')

        col.separator()
        col.label(text="Summary")
        box = col.box()
        box.label(text=f"SAFE_DELETE: {counts['SAFE_DELETE']}", icon=result_icon("SAFE_DELETE"))
        box.label(text=f"REVIEW: {counts['REVIEW']}", icon=result_icon("REVIEW"))
        box.label(text=f"KEEP: {counts['KEEP']}", icon=result_icon("KEEP"))
        box.label(text=f"PROTECTED: {counts['PROTECTED']}", icon=result_icon("PROTECTED"))


class IMBC_PT_Results(Panel):
    bl_label = "Bone Results"
    bl_idname = "IMBC_PT_results"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MBC'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        col = layout.column(align=True)
        col.label(text="Filter")

        row = col.row(align=True)
        row.prop(scene, "imbc_show_safe_delete", text="SAFE_DELETE")
        row.prop(scene, "imbc_show_review", text="REVIEW")

        row = col.row(align=True)
        row.prop(scene, "imbc_show_keep", text="KEEP")
        row.prop(scene, "imbc_show_protected", text="PROTECTED")

        row = col.row(align=True)
        row.operator("imbc.filter_preset_candidates", text="Candidates Only")
        row = col.row(align=True)
        row.operator("imbc.filter_all", text="All")
        row.operator("imbc.filter_none", text="None")

        col.separator()
        col.template_list(
            "IMBC_UL_bone_results",
            "",
            scene,
            "imbc_bones",
            scene,
            "imbc_bones_index",
            rows=10
        )

        shown = len(filtered_items(scene))
        total = len(scene.imbc_bones)
        col.label(text=f"Showing {shown} / {total} bones")


class IMBC_PT_SelectedBone(Panel):
    bl_label = "Selected Bone"
    bl_idname = "IMBC_PT_selected_bone"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MBC'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        item = selected_item(scene)

        if not item:
            layout.label(text="No result selected")
            return

        box = layout.box()
        box.label(text=item.bone_name, icon=result_icon(item.final_result))
        box.label(text=f"Auto Result: {item.auto_result}")
        box.label(text=f"Final Result: {item.final_result}")
        box.label(text=f"Override: {'Yes' if item.is_overridden else 'No'}")

        box.separator()
        box.label(text=f"Reason: {item.reason}")
        box.label(text=f"Has Actual Weight: {'Yes' if item.has_weight else 'No'}")
        box.label(text=f"Has Child: {'Yes' if item.has_child else 'No'}")
        box.label(text=f"Outfit Match: {item.outfit_match}")
        box.label(text=f"Avatar Match: {item.avatar_match}")
        box.label(text=f"Flags: {item.flags_text if item.flags_text else 'None'}")

        box.separator()
        row = box.row(align=True)
        op = row.operator("imbc.set_override", text="Mark Keep", icon='CHECKMARK')
        op.new_result = "KEEP"
        op = row.operator("imbc.set_override", text="Mark Delete", icon='TRASH')
        op.new_result = "SAFE_DELETE"

        row = box.row(align=True)
        op = row.operator("imbc.set_override", text="Mark Review", icon='QUESTION')
        op.new_result = "REVIEW"
        row.operator("imbc.reset_override", text="Reset Override", icon='LOOP_BACK')


classes = (
    IMBC_BoneItem,
    IMBC_OT_Analyze,
    IMBC_OT_DeleteSafe,
    IMBC_OT_SetOverride,
    IMBC_OT_ResetOverride,
    IMBC_OT_FilterPresetCandidates,
    IMBC_OT_FilterAll,
    IMBC_OT_FilterNone,
    IMBC_UL_BoneResults,
    IMBC_PT_Main,
    IMBC_PT_Results,
    IMBC_PT_SelectedBone,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.imbc_bones = CollectionProperty(type=IMBC_BoneItem)
    bpy.types.Scene.imbc_bones_index = IntProperty(default=0)

    bpy.types.Scene.imbc_original_outfit_armature = PointerProperty(
        name="Original Outfit",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == 'ARMATURE'
    )
    bpy.types.Scene.imbc_avatar_armature = PointerProperty(
        name="Avatar",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == 'ARMATURE'
    )
    bpy.types.Scene.imbc_mochi_output_armature = PointerProperty(
        name="Mochi Output",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == 'ARMATURE'
    )

    bpy.types.Scene.imbc_show_safe_delete = BoolProperty(name="SAFE_DELETE", default=True)
    bpy.types.Scene.imbc_show_review = BoolProperty(name="REVIEW", default=True)
    bpy.types.Scene.imbc_show_keep = BoolProperty(name="KEEP", default=False)
    bpy.types.Scene.imbc_show_protected = BoolProperty(name="PROTECTED", default=False)


def unregister():
    del bpy.types.Scene.imbc_bones
    del bpy.types.Scene.imbc_bones_index
    del bpy.types.Scene.imbc_original_outfit_armature
    del bpy.types.Scene.imbc_avatar_armature
    del bpy.types.Scene.imbc_mochi_output_armature
    del bpy.types.Scene.imbc_show_safe_delete
    del bpy.types.Scene.imbc_show_review
    del bpy.types.Scene.imbc_show_keep
    del bpy.types.Scene.imbc_show_protected

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
