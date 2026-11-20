"""Blender (фон, без окна): scene.json кухни -> рендеры PNG (Cycles на CPU), kuhnya.blend, kuhnya.glb.

blender -b --factory-startup --python tools/kitchen_blender.py -- scene.json out_dir [--samples 128] [--scale 1.0]
        [--views front,angle,top] [--no-files]
Оси помещения (X вдоль A, Y в комнату, Z вверх) -> Blender (X, -Y, Z), метры. Дискретную видеокарту не трогаем: только CPU.
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
scene_path, out_dir = argv[0], argv[1]
opt = {"samples": 128, "scale": 1.0, "views": "front,angle,top", "files": True, "denoise": False, "threads": 6}
i = 2
while i < len(argv):
    a = argv[i]
    if a == "--samples":
        opt["samples"] = int(argv[i + 1]); i += 2
    elif a == "--scale":
        opt["scale"] = float(argv[i + 1]); i += 2
    elif a == "--views":
        opt["views"] = argv[i + 1]; i += 2
    elif a == "--no-files":
        opt["files"] = False; i += 1
    elif a == "--denoise":                # OIDN на CPU (GPU-устройства OIDN запрещены переменными окружения)
        opt["denoise"] = True; i += 1
    elif a == "--threads":
        opt["threads"] = int(argv[i + 1]); i += 2
    elif a == "--cycles-device":          # аргумент самого Cycles (после --), его разбирает Blender
        i += 2
    else:
        raise SystemExit(f"неизвестный аргумент {a}")

S = json.load(open(scene_path, encoding="utf-8"))
os.makedirs(out_dir, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def V(x, y, z):
    return Vector((x / 1000.0, -y / 1000.0, z / 1000.0))


def hex_rgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c] + [1.0]


def set_in(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


def make_material(key, m):
    mat = bpy.data.materials.new(key)
    mat.use_nodes = True
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    set_in(b, ["Base Color"], hex_rgb(m["color"]))
    set_in(b, ["Roughness"], m.get("rough", 0.5))
    set_in(b, ["Metallic"], m.get("metal", 0.0))
    if "opacity" in m:
        set_in(b, ["Alpha"], m["opacity"])
        try:
            mat.surface_render_method = "BLENDED"
        except Exception:
            pass
    if m.get("emissive"):
        set_in(b, ["Emission Color", "Emission"], hex_rgb(m["color"]))
        set_in(b, ["Emission Strength"], m["emissive"])
    if m.get("wood"):
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1.0, 6.0, 1.0)
        nz = nt.nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = 3.0
        nz.inputs["Detail"].default_value = 8.0
        wv = nt.nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "Y"
        wv.inputs["Scale"].default_value = 7.0
        wv.inputs["Distortion"].default_value = 2.5
        wv.inputs["Detail"].default_value = 3.0
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], wv.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "FLOAT"
        mix.inputs["Factor"].default_value = 0.3
        nt.links.new(wv.outputs["Fac"], mix.inputs["A"])
        nt.links.new(nz.outputs["Fac"], mix.inputs["B"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.25
        ramp.color_ramp.elements[0].color = hex_rgb("#a98257")
        ramp.color_ramp.elements[1].position = 0.85
        ramp.color_ramp.elements[1].color = hex_rgb("#cdae86")
        nt.links.new(mix.outputs["Result"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
        mat["wood_mapping"] = mp.name
        mat["wood_wave"] = wv.name
    if m.get("tiles"):
        tc = nt.nodes.new("ShaderNodeTexCoord")
        br = nt.nodes.new("ShaderNodeTexBrick")
        br.inputs["Scale"].default_value = 1.0
        br.inputs["Mortar Size"].default_value = 0.003
        br.inputs["Brick Width"].default_value = 0.6
        br.inputs["Row Height"].default_value = 0.6
        br.offset = 0.0
        br.inputs["Color1"].default_value = hex_rgb("#d8d0c4")
        br.inputs["Color2"].default_value = hex_rgb("#d2cabd")
        br.inputs["Mortar"].default_value = hex_rgb("#bdb4a8")
        nt.links.new(tc.outputs["Object"], br.inputs["Vector"])
        nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    return mat


MAT = {k: make_material(k, m) for k, m in S["mats"].items()}
col_main = bpy.data.collections.new("kuhnya")
sc.collection.children.link(col_main)
objs = {}
for s in S["solids"]:
    bm = bmesh.new()
    if s["shape"] == "cyl_z":
        x0, y0, z0, x1, y1, z1 = s["boxes"][0]
        r = (x1 - x0) / 2000.0
        h = (z1 - z0) / 1000.0
        c = V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=h,
                              matrix=Matrix.Translation(c))
    else:
        for x0, y0, z0, x1, y1, z1 in s["boxes"]:
            c = V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
            m = Matrix.Translation(c) @ Matrix.Diagonal(((x1 - x0) / 1000, (y1 - y0) / 1000, (z1 - z0) / 1000, 1))
            bmesh.ops.create_cube(bm, size=1.0, matrix=m)
    me = bpy.data.meshes.new(s["id"])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(s["id"], me)
    ob["name_ru"] = s["name"]
    ob["kind"] = s["kind"]
    ob["module"] = s["module"]
    mat = MAT[s["mat"]]
    if s.get("grain") == "y" and "wood_mapping" in MAT[s["mat"]]:
        mat = MAT[s["mat"]].copy()
        mat.name = s["mat"] + "_y"
        mp = mat.node_tree.nodes[mat["wood_mapping"]]
        mp.inputs["Scale"].default_value = (6.0, 1.0, 1.0)          # волокна вдоль Y: полосы меняются по X
        mat.node_tree.nodes[mat["wood_wave"]].bands_direction = "X"
    me.materials.append(mat)
    if s["kind"] == "point":
        ob.hide_render = True
    col_main.objects.link(ob)
    objs[s["id"]] = (ob, s)

R = S.get("render")
D = None
if R:                                     # интерьерный рендер: материалы, комната, пол, шторы, декор, свет
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from kitchen_dress import Dress
    D = Dress(S, objs, MAT, sc, V, hex_rgb, set_in)
    D.build()

if not R:
    # свет: небо + солнце через окно + мягкий свет под потолком
    world = bpy.data.worlds.new("world")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = hex_rgb("#e4ebf2")
    bg.inputs["Strength"].default_value = 0.35

    sun_d = bpy.data.lights.new("sun", "SUN")
    sun_d.energy = 2.2
    sun_d.angle = math.radians(2.5)
    sun_d.color = (1.0, 0.96, 0.9)
    sun = bpy.data.objects.new("sun", sun_d)
    sun.rotation_euler = (math.radians(52), 0, math.radians(200))
    sc.collection.objects.link(sun)

    a, b, H = (float(S["room"][x]) for x in ("a", "b", "height"))
    ar_d = bpy.data.lights.new("area", "AREA")
    ar_d.shape = "RECTANGLE"
    ar_d.size = a / 1000 * 0.7
    ar_d.size_y = b / 1000 * 0.7
    ar_d.energy = 160
    ar_d.color = (1.0, 0.95, 0.88)
    ar = bpy.data.objects.new("area", ar_d)
    ar.location = V(a / 2, b / 2, H - 20)
    sc.collection.objects.link(ar)
    for o in (sun, ar):
        try:
            o.visible_camera = False
        except Exception:
            pass

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = opt["samples"]
# Встроенный денойзер Cycles (OIDN) не включаем: даже в режиме CPU он опрашивает GPU-устройства.
sc.cycles.use_denoising = False
if opt["denoise"]:
    # Денойз OIDN — нодой композитора на CPU: так видеокарта не задействуется (в отличие от встроенного денойза Cycles).
    sc.view_layers[0].cycles.denoising_store_passes = True
    ng = bpy.data.node_groups.new("denoise", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl, dn, go = (ng.nodes.new(t) for t in ("CompositorNodeRLayers", "CompositorNodeDenoise", "NodeGroupOutput"))
    ng.links.new(rl.outputs["Image"], dn.inputs["Image"])
    ng.links.new(rl.outputs["Denoising Albedo"], dn.inputs["Albedo"])
    ng.links.new(rl.outputs["Denoising Normal"], dn.inputs["Normal"])
    ng.links.new(dn.outputs[0], go.inputs[0])
    sc.compositing_node_group = ng
    sc.render.compositor_device = "CPU"
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.015
sc.cycles.sample_clamp_indirect = 1.5
sc.cycles.blur_glossy = 1.0
sc.cycles.caustics_reflective = False
sc.cycles.caustics_refractive = False
sc.cycles.max_bounces = 6
sc.render.threads_mode = "FIXED"
sc.render.threads = opt["threads"]
if R:
    sc.cycles.max_bounces = 10
    sc.cycles.sample_clamp_indirect = 3.0
    sc.cycles.adaptive_threshold = 0.01
try:
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
sc.view_settings.exposure = R.get("exposure", 0.0) if R else -0.2


def add_camera(name, cfg):
    cd = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cd)
    sc.collection.objects.link(cam)
    cam.location = V(*cfg["pos"])
    if cfg.get("ortho"):
        cd.type = "ORTHO"
        cd.ortho_scale = cfg["ortho"] / 1000
        cam.rotation_euler = (0, 0, 0)
    else:
        cd.lens = cfg["lens"]
        cd.sensor_width = 36
        cd.sensor_fit = "HORIZONTAL"
        cd.shift_x = cfg.get("shift_x", 0.0)
        cd.shift_y = cfg.get("shift_y", 0.0)
        d = V(*cfg["target"]) - cam.location
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cd.clip_start = 0.05
    cd.clip_end = 100
    return cam


# срезанные по высоте копии стен/окна/двери для видов с "clip" (только для рендера, в .blend/.glb не идут)
cut_objs = {}
for view, cfg in S["cameras"].items():
    if not cfg.get("clip"):
        continue
    zc = cfg["clip"]
    for s in S["solids"]:
        if s["kind"] not in cfg.get("clip_kinds", []) or s["shape"] != "box" or s["id"] in cfg.get("clip_drop", []):
            continue
        boxes = [[x0, y0, z0, x1, y1, min(z1, zc)] for x0, y0, z0, x1, y1, z1 in s["boxes"] if z0 < zc - 0.5]
        if not boxes:
            continue
        bm = bmesh.new()
        for x0, y0, z0, x1, y1, z1 in boxes:
            c = V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
            m = Matrix.Translation(c) @ Matrix.Diagonal(((x1 - x0) / 1000, (y1 - y0) / 1000, (z1 - z0) / 1000, 1))
            bmesh.ops.create_cube(bm, size=1.0, matrix=m)
        me = bpy.data.meshes.new(s["id"] + "_cut")
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(s["id"] + "_cut", me)
        me.materials.append(MAT[s["mat"]])
        ob.hide_render = True
        sc.collection.objects.link(ob)
        cut_objs.setdefault(view, []).append(ob)

cams = {k: add_camera("cam_" + k, c) for k, c in S["cameras"].items()}
res = {"front": (1920, 1200), "angle": (1920, 1200), "top": (1920, 1200)}
for view in [v for v in opt["views"].split(",") if v]:
    cfg = S["cameras"][view]
    clip_kinds = cfg.get("clip_kinds", []) if cfg.get("clip") else []
    closed = bool(cfg.get("closed")) and D is not None
    plan = bool(cfg.get("plan")) and D is not None
    above = cfg.get("hide_above")                    # план сверху: прячем всё, что выше (верхние, планки, LED)
    for oid, (ob, s) in objs.items():
        ob.hide_render = s["kind"] == "point" or (s.get("wall") in cfg["hide"]) or s["kind"] in clip_kinds
        if D is not None and (oid in D.replaced or ((closed or plan) and oid in D.hide_closed)):
            ob.hide_render = True
        if above and s["kind"] not in ("wall", "window", "door", "room") and min(b[2] for b in s["boxes"]) >= above:
            ob.hide_render = True
    if D is not None:
        for ob in D.closed_only:
            ob.hide_render = not closed
        for ob in D.floor_objs:
            ob.hide_render = not (closed or plan)
        for ob in D.col.objects:                     # добавленная техника/декор на плане — по той же высоте
            if above and ob not in D.closed_only and ob not in D.floor_objs and ob.type == "MESH":
                zmin = min((ob.matrix_world @ v.co).z for v in ob.data.vertices) * 1000
                ob.hide_render = zmin >= above
        sc.render.film_transparent = not closed       # план сверху — на прозрачном фоне (в PDF ляжет на белый)
    for v2, lst in cut_objs.items():
        for ob in lst:
            ob.hide_render = v2 != view
    sc.camera = cams[view]
    w, h = cfg.get("res") or res.get(view, (1920, 1200))
    sc.render.resolution_x = int(w * opt["scale"])
    sc.render.resolution_y = int(h * opt["scale"])
    sc.render.filepath = os.path.join(out_dir, f"render_{view}.png")
    bpy.ops.render.render(write_still=True)
    print("RENDER", view, sc.render.filepath, flush=True)

for oid, (ob, s) in objs.items():
    ob.hide_render = s["kind"] == "point" or (D is not None and oid in D.replaced)
if D is not None:                          # комната вокруг камеры — только для картинки, в .blend/.glb не идёт
    for ob in D.closed_only:
        bpy.data.objects.remove(ob, do_unlink=True)
for lst in cut_objs.values():
    for ob in lst:
        bpy.data.objects.remove(ob, do_unlink=True)
if opt["files"]:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, "kuhnya.blend"))
    try:
        bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "kuhnya.glb"), export_format="GLB",
                                  export_apply=True, export_cameras=False, export_lights=False)
    except TypeError:
        bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "kuhnya.glb"), export_format="GLB")
    print("FILES", out_dir, flush=True)
