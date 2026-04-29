bl_info = {
    "name": "Iyan-Kim Tools",
    "author": "Iyan-Kim",
    "version": (2, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Iyan-Kim",
    "description": "Unified tool suite for Mochi bone cleanup, mesh cleanup, and UV validation",
    "category": "3D View",
}

import bpy

from .config import ROOT_PANEL_ID, SIDEBAR_CATEGORY
from . import mesh_cleanup, mochi_bone_cleaner, uv_validation


class IYAN_PT_suite(bpy.types.Panel):
    bl_label = "Iyan-Kim Tools"
    bl_idname = ROOT_PANEL_ID
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = SIDEBAR_CATEGORY

    def draw(self, context):
        layout = self.layout
        layout.label(text="Tool Suite")
        layout.label(text="Open a section below.")


classes = (
    IYAN_PT_suite,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    mochi_bone_cleaner.register()
    mesh_cleanup.register()
    uv_validation.register()


def unregister():
    uv_validation.unregister()
    mesh_cleanup.unregister()
    mochi_bone_cleaner.unregister()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
