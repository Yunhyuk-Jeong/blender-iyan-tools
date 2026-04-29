from functools import lru_cache
import re

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Panel, PropertyGroup, UIList

from .config import ROOT_PANEL_ID, SIDEBAR_CATEGORY


RESULT_ITEMS = [
    ("SAFE_DELETE", "SAFE_DELETE", ""),
    ("REVIEW", "REVIEW", ""),
    ("KEEP", "KEEP", ""),
    ("PROTECTED", "PROTECTED", ""),
]

GENERATED_HINTS = {
    "orig", "ors", "original", "retarget", "generated", "gen",
    "copy", "tmp", "temp", "new", "bak", "old", "dup", "duplicate",
}

HELPER_HINTS = {
    "helper", "dummy", "offset", "target", "end", "tip", "twist",
    "socket", "null", "aux", "sub",
}

PROTECTED_NAMES = {
    "hips", "pelvis", "root", "armature", "center", "centre",
}

HUMANOID_CORE = {
    "hips", "pelvis", "spine", "chest", "neck", "head",
    "shoulder", "upperarm", "lowerarm", "hand",
    "thigh", "calf", "foot", "toe",
    "eye", "jaw", "upperleg", "lowerleg", "forearm", "clavicle", "wrist", "ankle",
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

ALIAS_TO_CATEGORY = {}
for canonical, aliases in CATEGORY_ALIASES.items():
    for alias in aliases:
        ALIAS_TO_CATEGORY[alias] = canonical

TOKEN_PATTERN = re.compile(r"[A-Za-z]+|\d+|[^\W\d_]+", re.UNICODE)
WEIGHT_EPSILON = 0.0001


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
    armature = scene.imbc_mochi_output_armature
    if armature and armature.type == "ARMATURE":
        return armature

    obj = context.object
    if obj and obj.type == "ARMATURE":
        return obj
    return None


def _split_camel_and_mixed(name: str):
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    text = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"(?i)(orig)(ors)", r"\1_\2", text)
    text = re.sub(r"(?i)(ors)([A-Z])", r"\1_\2", text)
    text = re.sub(r"(?i)(orig)([A-Z])", r"\1_\2", text)
    text = re.sub(r"(?i)(retarget)([A-Z])", r"\1_\2", text)
    text = re.sub(r"(?i)(copy)([A-Z])", r"\1_\2", text)
    return text


@lru_cache(maxsize=4096)
def tokenize_name(name: str):
    text = _split_camel_and_mixed(name)
    text = re.sub(r"\.\d+$", "", text)
    text = text.replace("-", "_").replace(".", "_").replace("/", "_").replace(" ", "_")
    text = re.sub(r"_+", "_", text).strip("_")

    raw_tokens = [token for token in text.split("_") if token]
    tokens = []
    for token in raw_tokens:
        parts = [token.lower()]
        changed = True
        while changed:
            changed = False
            new_parts = []
            for part in parts:
                matched = False
                for prefix in sorted(GENERATED_HINTS | HELPER_HINTS, key=len, reverse=True):
                    if part.startswith(prefix) and part != prefix:
                        rest = part[len(prefix):]
                        if rest:
                            new_parts.append(prefix)
                            new_parts.append(rest)
                            matched = True
                            changed = True
                            break
                if not matched:
                    new_parts.append(part)
            parts = new_parts

        for part in parts:
            extracted = TOKEN_PATTERN.findall(part)
            if extracted:
                tokens.extend(piece.lower() for piece in extracted if piece)
            else:
                tokens.append(part.lower())

    return tuple(ALIAS_TO_CATEGORY.get(token, token) for token in tokens)


def get_core_tokens(tokens):
    return [token for token in tokens if token not in GENERATED_HINTS and token not in HELPER_HINTS and not token.isdigit()]


def build_weighted_bone_names(armature_obj):
    if not armature_obj:
        return set()

    weighted_bones = set()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue

        uses_armature = obj.parent == armature_obj
        if not uses_armature:
            for modifier in obj.modifiers:
                if modifier.type == "ARMATURE" and getattr(modifier, "object", None) == armature_obj:
                    uses_armature = True
                    break
        if not uses_armature:
            continue

        group_by_index = {group.index: group.name for group in obj.vertex_groups}
        for vertex in obj.data.vertices:
            for group_ref in vertex.groups:
                if group_ref.weight <= WEIGHT_EPSILON:
                    continue
                group_name = group_by_index.get(group_ref.group)
                if group_name:
                    weighted_bones.add(group_name)

    return weighted_bones


def build_reference_index(ref_armature):
    if not ref_armature or ref_armature.type != "ARMATURE":
        return None

    exact_names = {bone.name for bone in ref_armature.data.bones}
    core_sequences = set()
    tail_token_sets = {}
    for bone_name in exact_names:
        ref_tokens = tokenize_name(bone_name)
        ref_core = get_core_tokens(ref_tokens)
        if not ref_core:
            ref_core = [token for token in ref_tokens if not token.isdigit()]
        if not ref_core:
            continue
        core_sequences.add(tuple(ref_core))
        tail_token_sets.setdefault(ref_core[-1], []).append(frozenset(ref_core))

    return {
        "exact_names": exact_names,
        "core_sequences": core_sequences,
        "tail_token_sets": tail_token_sets,
    }


def infer_match_level(name: str, ref_index):
    if not ref_index:
        return "N/A"
    if name in ref_index["exact_names"]:
        return "strong"

    tokens = tokenize_name(name)
    if not tokens:
        return "none"

    candidate_core = get_core_tokens(tokens)
    if not candidate_core:
        candidate_core = [token for token in tokens if not token.isdigit()]
    if not candidate_core:
        return "none"

    candidate_tuple = tuple(candidate_core)
    if candidate_tuple in ref_index["core_sequences"]:
        return "generated_core"

    candidate_tail = candidate_core[-1]
    candidate_set = frozenset(candidate_core)
    for ref_set in ref_index["tail_token_sets"].get(candidate_tail, []):
        if candidate_set != ref_set:
            return "weak"
    return "none"


def classify_bone(bone, weighted_bones, outfit_index=None, avatar_index=None):
    name = bone.name
    lower_name = name.lower()
    has_child = len(bone.children) > 0
    has_weight = name in weighted_bones

    tokens = tokenize_name(name)
    token_set = set(tokens)
    core_tokens = get_core_tokens(tokens)
    outfit_match = infer_match_level(name, outfit_index)
    avatar_match = infer_match_level(name, avatar_index)

    flags = []
    if token_set & GENERATED_HINTS:
        flags.append("generated_like")
    if token_set & HELPER_HINTS:
        flags.append("helper_like")

    exact_outfit = bool(outfit_index and name in outfit_index["exact_names"])
    exact_avatar = bool(avatar_index and name in avatar_index["exact_names"])

    core_category = core_tokens[-1] if core_tokens else None
    core_is_humanoid = core_category in HUMANOID_CORE or core_category in ALIAS_TO_CATEGORY.values()
    extra_noncore_tokens = [token for token in tokens if token not in core_tokens and not token.isdigit()]

    if core_is_humanoid:
        if len(core_tokens) == 1 and len(tokens) > 1:
            flags.append("prefixed_humanoid_like")
        if extra_noncore_tokens:
            flags.append("extra_unmatched_token")

    if lower_name in PROTECTED_NAMES:
        flags.append("protected_name")

    flags_text = ", ".join(sorted(set(flags)))

    if lower_name in PROTECTED_NAMES:
        return ("PROTECTED", "Protected root-like name", has_weight, has_child, outfit_match, avatar_match, flags_text)
    if has_weight:
        return ("KEEP", "Has actual vertex weight", has_weight, has_child, outfit_match, avatar_match, flags_text)
    if exact_outfit or exact_avatar:
        return ("KEEP", "Exact name match to outfit/avatar", has_weight, has_child, outfit_match, avatar_match, flags_text)
    if "generated_like" in flags or "prefixed_humanoid_like" in flags or "helper_like" in flags:
        if not has_child:
            return ("SAFE_DELETE", "Generated/prefixed humanoid or helper leftover + no child", has_weight, has_child, outfit_match, avatar_match, flags_text)
        return ("REVIEW", "Generated/prefixed humanoid or helper-like but has child", has_weight, has_child, outfit_match, avatar_match, flags_text)
    if outfit_match in {"weak", "generated_core"} or avatar_match in {"weak", "generated_core"}:
        if not has_child:
            return ("SAFE_DELETE", "Weak/generated core match + no child + no weight", has_weight, has_child, outfit_match, avatar_match, flags_text)
        return ("REVIEW", "Weak/generated core match with child chain", has_weight, has_child, outfit_match, avatar_match, flags_text)
    if not has_child:
        return ("SAFE_DELETE", "No weight + no child + no exact match", has_weight, has_child, outfit_match, avatar_match, flags_text)
    return ("REVIEW", "Structural bone without strong usage evidence", has_weight, has_child, outfit_match, avatar_match, flags_text)


def filtered_items(scene):
    result = []
    for item in scene.imbc_bones:
        status = item.final_result
        if status == "SAFE_DELETE" and not scene.imbc_show_safe_delete:
            continue
        if status == "REVIEW" and not scene.imbc_show_review:
            continue
        if status == "KEEP" and not scene.imbc_show_keep:
            continue
        if status == "PROTECTED" and not scene.imbc_show_protected:
            continue
        result.append(item)
    return result


def summary_counts(scene):
    counts = {"SAFE_DELETE": 0, "REVIEW": 0, "KEEP": 0, "PROTECTED": 0}
    for item in scene.imbc_bones:
        counts[item.final_result] = counts.get(item.final_result, 0) + 1
    return counts


def selected_item(scene):
    index = scene.imbc_bones_index
    if 0 <= index < len(scene.imbc_bones):
        return scene.imbc_bones[index]
    return None


class IMBC_OT_Analyze(bpy.types.Operator):
    bl_idname = "imbc.analyze"
    bl_label = "Analyze Bones"
    bl_description = "Analyze current Mochi output armature bones"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        armature = get_target_armature(context)
        if not armature:
            self.report({"ERROR"}, "Select an armature or assign Mochi Output Armature")
            return {"CANCELLED"}

        scene.imbc_bones.clear()
        scene.imbc_bones_index = 0

        weighted_bones = build_weighted_bone_names(armature)
        outfit_index = build_reference_index(scene.imbc_original_outfit_armature)
        avatar_index = build_reference_index(scene.imbc_avatar_armature)

        for bone in armature.data.bones:
            auto, reason, has_weight, has_child, outfit_match, avatar_match, flags_text = classify_bone(
                bone,
                weighted_bones=weighted_bones,
                outfit_index=outfit_index,
                avatar_index=avatar_index,
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

        self.report({"INFO"}, f"Analyzed {len(scene.imbc_bones)} bones")
        return {"FINISHED"}


class IMBC_OT_DeleteSafe(bpy.types.Operator):
    bl_idname = "imbc.delete_safe"
    bl_label = "Delete SAFE_DELETE Bones"
    bl_description = "Delete bones whose Final Result is SAFE_DELETE"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        armature = get_target_armature(context)
        if not armature:
            self.report({"ERROR"}, "Select an armature or assign Mochi Output Armature")
            return {"CANCELLED"}
        if not scene.imbc_bones:
            self.report({"ERROR"}, "Run Analyze Bones before deleting")
            return {"CANCELLED"}

        names_to_delete = [item.bone_name for item in scene.imbc_bones if item.final_result == "SAFE_DELETE"]
        if not names_to_delete:
            self.report({"INFO"}, "No SAFE_DELETE bones to remove")
            return {"CANCELLED"}

        if context.object != armature:
            bpy.ops.object.select_all(action="DESELECT")
            armature.select_set(True)
            context.view_layer.objects.active = armature

        prior_mode = armature.mode
        deleted = 0
        try:
            if prior_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            bpy.ops.object.mode_set(mode="EDIT")
            edit_bones = armature.data.edit_bones
            for bone_name in names_to_delete:
                edit_bone = edit_bones.get(bone_name)
                if edit_bone:
                    edit_bones.remove(edit_bone)
                    deleted += 1
        finally:
            current_mode = armature.mode
            if current_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            if prior_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=prior_mode)

        keep_entries = [item for item in scene.imbc_bones if item.final_result != "SAFE_DELETE"]
        snapshot = [{
            "bone_name": item.bone_name,
            "auto_result": item.auto_result,
            "final_result": item.final_result,
            "reason": item.reason,
            "has_weight": item.has_weight,
            "has_child": item.has_child,
            "outfit_match": item.outfit_match,
            "avatar_match": item.avatar_match,
            "flags_text": item.flags_text,
            "is_overridden": item.is_overridden,
        } for item in keep_entries]

        scene.imbc_bones.clear()
        for src in snapshot:
            item = scene.imbc_bones.add()
            for key, value in src.items():
                setattr(item, key, value)

        scene.imbc_bones_index = min(scene.imbc_bones_index, max(0, len(scene.imbc_bones) - 1))
        self.report({"INFO"}, f"Deleted {deleted} bones")
        return {"FINISHED"}


class IMBC_OT_SetOverride(bpy.types.Operator):
    bl_idname = "imbc.set_override"
    bl_label = "Set Override"
    bl_options = {"REGISTER", "UNDO"}

    new_result: EnumProperty(items=RESULT_ITEMS, default="REVIEW")

    def execute(self, context):
        item = selected_item(context.scene)
        if not item:
            return {"CANCELLED"}
        item.final_result = self.new_result
        item.is_overridden = item.final_result != item.auto_result
        return {"FINISHED"}


class IMBC_OT_ResetOverride(bpy.types.Operator):
    bl_idname = "imbc.reset_override"
    bl_label = "Reset Override"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        item = selected_item(context.scene)
        if not item:
            return {"CANCELLED"}
        item.final_result = item.auto_result
        item.is_overridden = False
        return {"FINISHED"}


class IMBC_OT_FilterPresetCandidates(bpy.types.Operator):
    bl_idname = "imbc.filter_preset_candidates"
    bl_label = "Candidates Only"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = True
        scene.imbc_show_review = True
        scene.imbc_show_keep = False
        scene.imbc_show_protected = False
        return {"FINISHED"}


class IMBC_OT_FilterAll(bpy.types.Operator):
    bl_idname = "imbc.filter_all"
    bl_label = "All"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = True
        scene.imbc_show_review = True
        scene.imbc_show_keep = True
        scene.imbc_show_protected = True
        return {"FINISHED"}


class IMBC_OT_FilterNone(bpy.types.Operator):
    bl_idname = "imbc.filter_none"
    bl_label = "None"

    def execute(self, context):
        scene = context.scene
        scene.imbc_show_safe_delete = False
        scene.imbc_show_review = False
        scene.imbc_show_keep = False
        scene.imbc_show_protected = False
        return {"FINISHED"}


def result_icon(result):
    return {
        "SAFE_DELETE": "TRASH",
        "REVIEW": "QUESTION",
        "KEEP": "CHECKMARK",
        "PROTECTED": "LOCKED",
    }.get(result, "DOT")


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
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text="", icon=result_icon(item.final_result))
            row.label(text=item.bone_name)
            row.label(text=item.final_result + (" *" if item.is_overridden else ""))
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon=result_icon(item.final_result))


class IMBC_PT_Main(Panel):
    bl_label = "Mochi Bone Cleaner"
    bl_idname = "IMBC_PT_main"
    bl_parent_id = ROOT_PANEL_ID
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY

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
        row.operator("imbc.analyze", icon="VIEWZOOM")
        row.operator("imbc.delete_safe", icon="TRASH")

        col.separator()
        col.label(text="Summary")
        box = col.box()
        box.label(text=f"SAFE_DELETE: {counts['SAFE_DELETE']}", icon=result_icon("SAFE_DELETE"))
        box.label(text=f"REVIEW: {counts['REVIEW']}", icon=result_icon("REVIEW"))
        box.label(text=f"KEEP: {counts['KEEP']}", icon=result_icon("KEEP"))
        box.label(text=f"PROTECTED: {counts['PROTECTED']}", icon=result_icon("PROTECTED"))


class IMBC_PT_Results(Panel):
    bl_label = "Results"
    bl_idname = "IMBC_PT_results"
    bl_parent_id = "IMBC_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

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
        col.template_list("IMBC_UL_bone_results", "", scene, "imbc_bones", scene, "imbc_bones_index", rows=10)

        shown = len(filtered_items(scene))
        total = len(scene.imbc_bones)
        col.label(text=f"Showing {shown} / {total} bones")


class IMBC_PT_SelectedBone(Panel):
    bl_label = "Selected Bone"
    bl_idname = "IMBC_PT_selected_bone"
    bl_parent_id = "IMBC_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY
    bl_options = {"DEFAULT_CLOSED"}

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
        op = row.operator("imbc.set_override", text="Mark Keep", icon="CHECKMARK")
        op.new_result = "KEEP"
        op = row.operator("imbc.set_override", text="Mark Delete", icon="TRASH")
        op.new_result = "SAFE_DELETE"

        row = box.row(align=True)
        op = row.operator("imbc.set_override", text="Mark Review", icon="QUESTION")
        op.new_result = "REVIEW"
        row.operator("imbc.reset_override", text="Reset Override", icon="LOOP_BACK")


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
        poll=lambda self, obj: obj and obj.type == "ARMATURE",
    )
    bpy.types.Scene.imbc_avatar_armature = PointerProperty(
        name="Avatar",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "ARMATURE",
    )
    bpy.types.Scene.imbc_mochi_output_armature = PointerProperty(
        name="Mochi Output",
        type=bpy.types.Object,
        poll=lambda self, obj: obj and obj.type == "ARMATURE",
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
