"""Интерьерный рендер кухни (Blender): то, чего нет в модели мебели, но есть на хорошей визуализации.

Включается разделом render в scene.json (из конфига кухни). Мебель и техника не меняются — только картинка:
материалы (фаска 1 мм на фасадах, матовый МДФ, чёрная матовая столешница, стеклянный фартук, шлифованная нержавейка,
гранит, чугун), комната для «закрытых» видов (стены продлены за камеру, потолок, пол ёлочкой из дуба с разбросом тона,
шторы складками, белая дверь с ручкой, доска и ваза), свет (солнце и небо через окно, мягкая заливка, тёплая LED-полоса
под верхними 3000–4000 K).
Оси помещения (мм): X вдоль A, Y в комнату, Z вверх -> Blender (X, -Y, Z) в метрах.
"""
import math
import random

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector


def kelvin_rgb(k):
    """Цвет чёрного тела (приближение Tanner Helland), линейный RGB."""
    t = k / 100.0
    r = 255 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = [min(max(v, 0), 255) / 255.0 for v in (r, g, b)]
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)


class Dress:
    def __init__(self, S, objs, MAT, sc, V, hex_rgb, set_in):
        self.S, self.objs, self.MAT, self.sc, self.V, self.hex, self.set_in = S, objs, MAT, sc, V, hex_rgb, set_in
        self.R = S["render"]
        self.room = S["room"]
        self.closed_only = []          # объекты только для «закрытых» видов (комната вокруг камеры)
        self.floor_objs = []           # пол ёлочкой и подложка — в закрытых видах и на плане сверху
        self.always = []               # добавленные объекты, видимые везде
        self.hide_closed = set()       # объекты модели, которые прячем в закрытых видах (пол-плитка)
        self.replaced = set()          # объекты модели, заменённые картинкой во всех видах (шторы-коробки)
        self.col = bpy.data.collections.new("interior")
        sc.collection.children.link(self.col)
        random.seed(27)

    # ---------- материалы ----------
    def pbr(self, name, color, rough=0.5, metal=0.0, coat=0.0, coat_rough=0.05, spec=0.5, aniso=0.0, sheen=0.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        si = self.set_in
        si(b, ["Base Color"], self.hex(color) if isinstance(color, str) else color)
        si(b, ["Roughness"], rough)
        si(b, ["Metallic"], metal)
        si(b, ["Specular IOR Level", "Specular"], spec)
        if coat:
            si(b, ["Coat Weight", "Clearcoat"], coat)
            si(b, ["Coat Roughness", "Clearcoat Roughness"], coat_rough)
        if aniso:
            si(b, ["Anisotropic"], aniso)
        if sheen:
            si(b, ["Sheen Weight", "Sheen"], sheen)
        return m

    def _bsdf(self, m):
        return m.node_tree.nodes["Principled BSDF"]

    def brushed(self, name, color):
        """Шлифованная нержавейка: металл, анизотропия, вертикальные штрихи шумом в шероховатости."""
        m = self.pbr(name, color, rough=0.3, metal=1.0, aniso=0.6)
        nt = m.node_tree
        tc, mp, nz, rp = (nt.nodes.new(t) for t in ("ShaderNodeTexCoord", "ShaderNodeMapping", "ShaderNodeTexNoise",
                                                    "ShaderNodeValToRGB"))
        mp.inputs["Scale"].default_value = (600.0, 600.0, 4.0)
        nz.inputs["Scale"].default_value = 1.0
        nz.inputs["Detail"].default_value = 6.0
        rp.color_ramp.elements[0].color = (0.2, 0.2, 0.2, 1)
        rp.color_ramp.elements[1].color = (0.38, 0.38, 0.38, 1)
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        nt.links.new(nz.outputs["Fac"], rp.inputs["Fac"])
        nt.links.new(rp.outputs["Color"], self._bsdf(m).inputs["Roughness"])
        return m

    def speckled(self, name, base, grain, rough):
        """Гранит: тёмная основа с мелкими светлыми зёрнами."""
        m = self.pbr(name, base, rough=rough)
        nt = m.node_tree
        tc, vo, rp = (nt.nodes.new(t) for t in ("ShaderNodeTexCoord", "ShaderNodeTexVoronoi", "ShaderNodeValToRGB"))
        vo.inputs["Scale"].default_value = 900.0
        rp.color_ramp.elements[0].position = 0.0
        rp.color_ramp.elements[0].color = self.hex(grain)
        rp.color_ramp.elements[1].position = 0.06
        rp.color_ramp.elements[1].color = self.hex(base)
        nt.links.new(tc.outputs["Object"], vo.inputs["Vector"])
        nt.links.new(vo.outputs["Distance"], rp.inputs["Fac"])
        nt.links.new(rp.outputs["Color"], self._bsdf(m).inputs["Base Color"])
        return m

    def emissive(self, name, kelvin, strength):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = self._bsdf(m)
        col = kelvin_rgb(kelvin) + (1.0,)
        self.set_in(b, ["Base Color"], col)
        self.set_in(b, ["Emission Color", "Emission"], col)
        self.set_in(b, ["Emission Strength"], strength)
        return m

    def oak_planks(self, tones):
        """Дуб: тон доски из атрибута tone, волокна — полосы вдоль доски по UV."""
        m = self.pbr("floor_oak", tones[0], rough=0.42, coat=0.15, coat_rough=0.3)
        nt = m.node_tree
        at = nt.nodes.new("ShaderNodeAttribute")
        at.attribute_name = "tone"
        at.attribute_type = "GEOMETRY"
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        cr = ramp.color_ramp
        cr.interpolation = "CONSTANT"
        while len(cr.elements) < len(tones):
            cr.elements.new(0.5)
        for i, c in enumerate(tones):
            cr.elements[i].position = i / len(tones)
            cr.elements[i].color = self.hex(c)
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "UVMap"
        wv = nt.nodes.new("ShaderNodeTexWave")
        wv.wave_type = "BANDS"
        wv.bands_direction = "X"                 # UV.x — поперёк доски: полосы идут вдоль доски
        wv.inputs["Scale"].default_value = 9.0
        wv.inputs["Distortion"].default_value = 3.0
        wv.inputs["Detail"].default_value = 4.0
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 0.18
        gr = nt.nodes.new("ShaderNodeValToRGB")
        gr.color_ramp.elements[0].color = (0.55, 0.5, 0.45, 1)
        gr.color_ramp.elements[1].color = (1, 1, 1, 1)
        nt.links.new(at.outputs["Fac"], ramp.inputs["Fac"])
        nt.links.new(uv.outputs["UV"], wv.inputs["Vector"])
        nt.links.new(wv.outputs["Fac"], gr.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], mix.inputs[6])
        nt.links.new(gr.outputs["Color"], mix.inputs[7])
        nt.links.new(mix.outputs[2], self._bsdf(m).inputs["Base Color"])
        return m

    def materials(self):
        R, MAT = self.R, self.MAT
        look = R.get("look", {})

        def swap(key, m):
            for ob, s in self.objs.values():
                if s["mat"] == key:
                    ob.data.materials.clear()
                    ob.data.materials.append(m)
            MAT[key] = m
        swap("facade", self.pbr("facade_mdf", look.get("facade", "#e4ddcc"), rough=0.6, spec=0.35))
        swap("plinth", MAT["facade"])
        swap("worktop", self.pbr("worktop_black", look.get("worktop", "#0c0c0d"), rough=0.75, spec=0.1))
        swap("apron", self.pbr("apron_glass", look.get("apron", "#f1f1ee"), rough=0.03, coat=1.0, spec=0.6))
        swap("steel_fridge", self.brushed("fridge_inox", look.get("fridge", "#9a9792")))
        swap("steel", self.brushed("inox", "#b9bbbd"))
        swap("black_glass", self.pbr("black_glass", "#050506", rough=0.08, coat=0.35, spec=0.25))
        swap("cast_iron", self.pbr("cast_iron", "#141414", rough=0.65, metal=0.3))
        swap("granite_black", self.speckled("granite", "#121213", "#3b3b3e", 0.42))
        swap("faucet_black", self.pbr("faucet_black", "#101011", rough=0.3, metal=0.85))
        swap("wall", self.pbr("wall_paint", look.get("wall", "#d8d2c9"), rough=0.92, spec=0.2))
        swap("door", self.pbr("door_white", "#f2f1ed", rough=0.38))
        swap("door_frame", MAT["door"])
        swap("curtain", self.pbr("curtain", look.get("curtain", "#c7c0b4"), rough=1.0, sheen=0.6, spec=0.1))
        swap("led", self.emissive("led_warm", R.get("led_k", 3500), R.get("led_strength", 12.0)))
        glass = self.pbr("window_glass", "#ffffff", rough=0.0, spec=0.5)
        self.set_in(self._bsdf(glass), ["Transmission Weight", "Transmission"], 1.0)
        self.set_in(self._bsdf(glass), ["IOR"], 1.45)
        swap("glass", glass)
        # фаска 1 мм на кромках фасадов, планок и торцов (одна коробка — без швов)
        for ob, s in self.objs.values():
            if s["kind"] in ("facade", "filler") and len(s["boxes"]) == 1:
                mod = ob.modifiers.new("faska", "BEVEL")
                mod.width = 0.001
                mod.segments = 2
                mod.limit_method = "ANGLE"

    # ---------- комната для закрытых видов ----------
    def box(self, name, mat, x0, y0, z0, x1, y1, z1, closed=True):
        bm = bmesh.new()
        c = self.V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        m = Matrix.Translation(c) @ Matrix.Diagonal(((x1 - x0) / 1000, (y1 - y0) / 1000, (z1 - z0) / 1000, 1))
        bmesh.ops.create_cube(bm, size=1.0, matrix=m)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mat)
        ob = bpy.data.objects.new(name, me)
        self.col.objects.link(ob)
        (self.closed_only if closed else self.always).append(ob)
        return ob

    def room_ext(self):
        a, b, H, w = (float(self.room[k]) for k in ("a", "b", "height", "wall"))
        cams = [c for c in self.S["cameras"].values() if c.get("closed")]
        self.b_ext = max([b] + [c["pos"][1] + 700 for c in cams])
        wall, ceil = self.MAT["wall"], self.pbr("ceiling", self.R.get("look", {}).get("ceiling", "#f4f3f0"), rough=0.95)
        if self.b_ext > b:
            self.box("ext_wall_B", wall, -w, b + w, 0, 0, self.b_ext + w, H)
            self.box("ext_wall_C", wall, a, b + w, 0, a + w, self.b_ext + w, H)
            self.box("ext_wall_D", wall, -w, self.b_ext, 0, a + w, self.b_ext + w, H)
        self.box("ceiling", ceil, -w, -w, H, a + w, self.b_ext + w, H + 80)
        fb = self.box("floor_base", self.pbr("floor_gap", "#3e362d", rough=0.8), -w, -w, -40, a + w, self.b_ext + w, 0)
        self.closed_only.remove(fb)
        self.floor_objs.append(fb)
        for oid, (ob, s) in self.objs.items():
            if s["mat"] == "floor":
                self.hide_closed.add(oid)

    def herringbone(self):
        """Пол ёлочкой: доска L×W, полосы вдоль Y, разброс тона, щель между досками; обрезка по комнате."""
        fl = self.R.get("floor", {})
        L, W = (float(v) for v in fl.get("plank", (600, 100)))
        gap = float(fl.get("gap", 1.0))
        tones = fl.get("tones", ["#cfae84", "#c19d72", "#b48e64", "#d7b98f", "#c6a379"])
        a = float(self.room["a"])
        bm = bmesh.new()
        tone = bm.faces.layers.float.new("tone")
        uvl = bm.loops.layers.uv.new("UVMap")
        n = L / W
        k_range = int((a + self.b_ext) / L) + 4
        i_range = int((a + self.b_ext) / W) + 8
        rot = math.radians(45)
        cs, sn = math.cos(rot), math.sin(rot)
        cx, cy = a / 2, self.b_ext / 2
        z = 0.6
        for k in range(-k_range, k_range):
            for i in range(-i_range, i_range):
                for (x, y, w_, h_) in ((i + k * n, i - k * n, n, 1), (i + n + k * n, i + 1 - n - k * n, 1, n)):
                    X0, Y0, X1, Y1 = x * W + gap / 2, y * W + gap / 2, (x + w_) * W - gap / 2, (y + h_) * W - gap / 2
                    pts = []
                    for px, py in ((X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)):
                        rx, ry = px * cs - py * sn + cx, px * sn + py * cs + cy
                        pts.append((rx, ry))
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    if max(xs) < -50 or min(xs) > a + 50 or max(ys) < -50 or min(ys) > self.b_ext + 50:
                        continue
                    vs = [bm.verts.new(self.V(px, py, z)) for px, py in pts]
                    f = bm.faces.new(vs)
                    f[tone] = random.random()
                    off = random.random() * 3
                    long_x = w_ > h_
                    for lp, (px, py) in zip(f.loops, ((X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1))):
                        u = (px if long_x else py) / 1000 + off
                        v = (py if long_x else px) / 1000
                        lp[uvl].uv = (v * 8, u)
        for co, no in (((0, 0, 0), (-1, 0, 0)), ((a / 1000, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0)),
                       ((0, -self.b_ext / 1000, 0), (0, -1, 0))):
            geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
            bmesh.ops.bisect_plane(bm, geom=geom, plane_co=co, plane_no=no, clear_outer=True)
        me = bpy.data.meshes.new("floor_herringbone")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(self.oak_planks(tones))
        ob = bpy.data.objects.new("floor_herringbone", me)
        self.col.objects.link(ob)
        self.floor_objs.append(ob)

    def curtains(self):
        """Шторы складками вместо коробок декора: синусоида по ширине, к полу складки чуть глубже."""
        mat = self.MAT.get("curtain") or self.pbr("curtain", "#c7c0b4", rough=1.0, sheen=0.6)
        for oid, (ob, s) in self.objs.items():
            if s["mat"] != "curtain":
                continue
            x0, y0, z0, x1, y1, z1 = s["boxes"][0]
            self.replaced.add(oid)
            amp = (x1 - x0) / 2 - 4
            xc = (x0 + x1) / 2
            period = 130.0
            ny, nz = int((y1 - y0) / 8), 6
            bm = bmesh.new()
            grid = []
            for iz in range(nz + 1):
                zz = z0 + (z1 - z0) * iz / nz
                row = []
                for iy in range(ny + 1):
                    yy = y0 + (y1 - y0) * iy / ny
                    a_ = amp * (0.75 + 0.25 * (1 - iz / nz))
                    xx = xc + a_ * math.sin(2 * math.pi * (yy - y0) / period + 0.4 * math.sin(iy * 0.13))
                    row.append(bm.verts.new(self.V(xx, yy, zz)))
                grid.append(row)
            for iz in range(nz):
                for iy in range(ny):
                    bm.faces.new((grid[iz][iy], grid[iz][iy + 1], grid[iz + 1][iy + 1], grid[iz + 1][iy]))
            me = bpy.data.meshes.new("curtain_" + oid)
            bm.to_mesh(me)
            bm.free()
            for p in me.polygons:
                p.use_smooth = True
            me.materials.append(mat)
            o = bpy.data.objects.new("curtain_" + oid, me)
            o.modifiers.new("solid", "SOLIDIFY").thickness = 0.002
            self.col.objects.link(o)
            self.always.append(o)

    def door_handle(self):
        dl = self.objs.get("door_leaf")
        if not dl:
            return
        x0, y0, z0, x1, y1, z1 = dl[1]["boxes"][0]
        chrome = self.MAT["chrome"]
        yh = y0 + 70
        self.box("door_handle_rose", chrome, x1, yh - 25, 1000 - 25, x1 + 12, yh + 25, 1000 + 25, closed=False)
        self.box("door_handle_lever", chrome, x1 + 12, yh, 990, x1 + 62, yh + 130, 1010, closed=False)

    def decor(self):
        oak = self.oak_planks([self.R.get("board", "#9c8667")])
        for d in self.R.get("decor", []):
            if d["type"] == "board":
                x, y, z = d["at"]
                w, h, t = d["size"]
                ob = self.box("decor_board", oak, x - w / 2, y, z, x + w / 2, y + t, z + h, closed=False)
                ob.data.transform(Matrix.Translation(-self.V(x, y, z)))
                ob.location = self.V(x, y, z)
                ob.rotation_euler = Euler((math.radians(-d.get("lean", 10)), 0, 0))
            elif d["type"] == "vase":
                x, y, z = d["at"]
                r, h = d["r"], d["h"]
                bm = bmesh.new()
                bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=r / 1000, radius2=r * 0.7 / 1000,
                                      depth=h / 1000, matrix=Matrix.Translation(self.V(x, y, z + h / 2)))
                me = bpy.data.meshes.new("decor_vase")
                bm.to_mesh(me)
                bm.free()
                for p in me.polygons:
                    p.use_smooth = True
                me.materials.append(self.pbr("ceramic", d.get("color", "#efede8"), rough=0.25, coat=0.5))
                ob = bpy.data.objects.new("decor_vase", me)
                self.col.objects.link(ob)
                self.always.append(ob)

    def window_sky(self):
        """За окном — светлое небо (светящаяся плоскость снаружи стены C): в интерьерке окно «засвечено»."""
        win = self.R.get("window")
        if not win:
            return
        a, w = float(self.room["a"]), float(self.room["wall"])
        y0, y1, z0, z1 = win
        m = self.emissive("sky_backdrop", 7500, self.R.get("backdrop_strength", 3.0))
        self.set_in(self._bsdf(m), ["Base Color", "Emission Color", "Emission"], self.hex("#eef3f8"))
        self.box("window_backdrop", m, a + w + 600, y0 - 900, z0 - 900, a + w + 610, y1 + 900, z1 + 900)

    def _front(self, sid):
        """Лицевая плоскость техники: (оси, функция (u от правого края, z, выступ) -> точка комнаты)."""
        x0, y0, z0, x1, y1, z1 = self.objs[sid][1]["boxes"][0]
        if (x1 - x0) < (y1 - y0):             # ряд B: лицо при X = x1, справа (смотрим на стену B) — меньший Y
            return (y1 - y0, z1 - z0), (lambda u, z, d: (x1 + d, y0 + u, z0 + z)), "B"
        return (x1 - x0, z1 - z0), (lambda u, z, d: (x1 - u, y1 + d, z0 + z)), "A"

    def _panel(self, name, mat, P, u0, u1, z0, z1, d0, d1, run):
        a, b = P(u0, z0, d0), P(u1, z1, d1)
        return self.box(name, mat, min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]), max(a[0], b[0]),
                        max(a[1], b[1]), max(a[2], b[2]), closed=False)

    def _knob(self, name, mat, P, u, z, r, d, run):
        c = P(u, z, d / 2)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r / 1000, radius2=r * 0.9 / 1000, depth=d / 1000)
        rot = Matrix.Rotation(math.radians(90), 4, "Y") if run == "B" else Matrix.Rotation(math.radians(90), 4, "X")
        bmesh.ops.transform(bm, matrix=Matrix.Translation(self.V(*c)) @ rot, verts=bm.verts)
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = True
        me.materials.append(mat)
        ob = bpy.data.objects.new(name, me)
        self.col.objects.link(ob)
        self.always.append(ob)

    def appliances(self):
        """СВЧ и духовка: рамка, стеклянная дверца со смотровым окном, панель управления."""
        frame = self.pbr("appl_frame", "#1b1b1d", rough=0.35, metal=0.4)
        glass = self.pbr("appl_glass", "#050506", rough=0.03, coat=1.0, spec=0.5)
        window = self.pbr("appl_window", "#26272a", rough=0.15, coat=0.6)
        disp = self.emissive("appl_display", 9000, 1.6)
        knob = self.pbr("appl_knob", "#8f9295", rough=0.25, metal=1.0)
        if "mw_front" in self.objs:
            (W, H), P, run = self._front("mw_front")
            self.replaced.add("mw_front")
            self._panel("mw_frame", frame, P, 0, W, 0, H, -20, 0, run)
            self._panel("mw_door", glass, P, 150, W - 14, 14, H - 14, 0, 3, run)
            self._panel("mw_window", window, P, 190, W - 60, 60, H - 60, 3, 4, run)
            self._panel("mw_display", disp, P, 30, 120, H - 70, H - 46, 0, 1.5, run)
            self._knob("mw_knob", knob, P, 75, H - 170, 22, 10, run)
            self._knob("mw_button", knob, P, 75, 70, 14, 5, run)
        if "oven_front" in self.objs:
            (W, H), P, run = self._front("oven_front")
            self.replaced.add("oven_front")
            self._panel("oven_frame", frame, P, 0, W, 0, H, -18, 0, run)
            self._panel("oven_panel", self.pbr("oven_panel", "#111113", rough=0.25, coat=0.5), P, 6, W - 6, H - 92,
                        H - 4, 0, 2, run)
            self._panel("oven_door", glass, P, 6, W - 6, 8, H - 98, 0, 3, run)
            self._panel("oven_window", window, P, 70, W - 70, 70, H - 190, 3, 4, run)
            self._panel("oven_display", disp, P, W / 2 - 45, W / 2 + 45, H - 62, H - 38, 2, 3, run)
            for i, u in enumerate((70, 140, W - 140, W - 70)):
                self._knob(f"oven_knob{i}", knob, P, u, H - 48, 16, 14, run)

    # ---------- свет ----------
    def light(self, name, kind, energy, color, loc, rot=(0, 0, 0), size=None, size_y=None, camera=False):
        ld = bpy.data.lights.new(name, kind)
        ld.energy = energy
        ld.color = color
        if kind == "AREA":
            ld.shape = "RECTANGLE"
            ld.size = size
            ld.size_y = size_y
        if kind == "SUN":
            ld.angle = math.radians(1.2)
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = rot
        try:
            ob.visible_camera = camera
        except Exception:
            pass
        self.col.objects.link(ob)
        return ob

    def lights(self):
        R = self.R
        a, H = float(self.room["a"]), float(self.room["height"])
        win = R.get("window")                       # [y0, y1, z0, z1] на стене C
        world = bpy.data.worlds.new("world_int")
        self.sc.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes["Background"]
        bg.inputs["Color"].default_value = self.hex(R.get("sky", "#dce5ee"))
        bg.inputs["Strength"].default_value = R.get("sky_strength", 0.5)
        sun_el, sun_az = math.radians(R.get("sun_elev", 28)), math.radians(R.get("sun_az", 18))
        # солнце светит из окна на стене C (+X) в комнату (-X), чуть вглубь (+Y)
        d = Vector((-math.cos(sun_el) * math.cos(sun_az), -math.cos(sun_el) * math.sin(sun_az), -math.sin(sun_el)))
        rot = d.to_track_quat("-Z", "Y").to_euler()
        self.light("sun", "SUN", R.get("sun", 2.8), kelvin_rgb(6000), (0, 0, 0), rot)
        if win:
            y0, y1, z0, z1 = win
            c = self.V(a - 6, (y0 + y1) / 2, (z0 + z1) / 2)
            self.light("window_sky", "AREA", R.get("window_power", 380), kelvin_rgb(7500), c,
                       Euler((0, math.radians(90), 0)), size=(z1 - z0) / 1000, size_y=(y1 - y0) / 1000)
        fill = R.get("fill", 120)
        cx, cy = a / 2, min(self.b_ext - 600, 2600)
        self.light("fill_ceiling", "AREA", fill, kelvin_rgb(6000), self.V(cx, cy, H - 40), (0, 0, 0),
                   size=2.6, size_y=2.0)
        # подсветка под верхними: тонкие прямоугольные источники по каждому сегменту LED, светят вниз
        per_m = R.get("led_w_per_m", 22)
        for ob, s in self.objs.values():
            if s["kind"] != "led":
                continue
            x0, y0, z0, x1, y1, z1 = s["boxes"][0]
            ln = max(x1 - x0, y1 - y0) / 1000
            along_x = (x1 - x0) > (y1 - y0)
            loc = self.V((x0 + x1) / 2, (y0 + y1) / 2, z0 - 1)
            self.light(f"led_light_{s['id']}", "AREA", per_m * ln, kelvin_rgb(R.get("led_k", 3500)), loc,
                       Euler((0, 0, 0 if along_x else math.radians(90))), size=ln, size_y=0.025)

    def build(self):
        self.materials()
        self.room_ext()
        self.herringbone()
        self.curtains()
        self.door_handle()
        self.decor()
        self.window_sky()
        self.appliances()
        self.lights()
