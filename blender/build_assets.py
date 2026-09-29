"""Build every Kartlands GP model in Blender and export them to assets/kartlands.glb.

Run it headless with Blender:
    blender --background --factory-startup --python blender/build_assets.py
or with the bpy module from PyPI (pip install bpy):
    python blender/build_assets.py
You can also open it in Blender's Scripting tab and press Run: that builds the models into a new
scene to browse and edit, without exporting.

Options (after `--` when running through blender):
    --out PATH      where to write the GLB (default: assets/kartlands.glb next to this folder)
    --blend PATH    also save the scene as a .blend file
    --no-export     build the scene without writing the GLB

Coordinates: every part is written in the game's frame (Y up, the kart faces +Z, units are
metres) and turned to Blender's Z-up frame at the end, so the exported glTF matches the game.
Each part sits at its own pivot: wheels at the axle, heads at the neck, arms at the shoulder.
Materials are named slots; the game swaps in each racer's colours by name.
"""
import math
import os
import sys

import bpy  # must come first: the PyPI bpy module provides bmesh and mathutils
import bmesh
from mathutils import Euler, Matrix, Vector, noise

TAU = math.tau
HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()

# --------------------------------------------------------------------------- materials
# name: (base colour, roughness, metallic, emission colour, emission strength)
MATERIALS = {
    'Body': (0xe53935, .38, .2, None, 0),
    'BodyDark': (0x8e2321, .5, .15, None, 0),
    'Accent': (0xff5c4d, .4, .1, None, 0),
    'Dark': (0x1d1f26, .8, 0, None, 0),
    'Chrome': (0xd8dde6, .22, .9, None, 0),
    'Rubber': (0x15161a, .95, 0, None, 0),
    'Glass': (0x1b2a3a, .08, .4, None, 0),
    'Lamp': (0xfff4c2, .3, 0, 0xffe08a, 1.2),
    'Plate': (0xf6f1e6, .6, 0, None, 0),
    'Suit': (0x2b2b2b, .65, 0, None, 0),
    'Skin': (0xf1c27d, .75, 0, None, 0),
    'Helmet': (0xffd23f, .28, .12, None, 0),
    'Glove': (0x2a2d36, .8, 0, None, 0),
    'Eye': (0xf7f7f2, .35, 0, None, 0),
    'Glow': (0xff5c4d, .4, 0, 0xff5c4d, .7),
    'RocketBody': (0xff5c4d, .4, .1, 0xff2200, .6),
    'RocketFin': (0xffd23f, .5, 0, None, 0),
    'Oil': (0x14141a, .15, .5, None, 0),
    'ItemBox': (0x8ef0ff, .1, .1, 0x2266aa, .35),
    'Core': (0xffd23f, .5, 0, 0xff9900, .8),
    'Leaves': (0x2f7a3a, .9, 0, None, 0),
    'Bark': (0x6b4a2b, 1, 0, None, 0),
    'Frond': (0x2e9e4f, .8, 0, None, 0),
    'Cactus': (0x5f8f3e, .85, 0, None, 0),
    'Rock': (0x8a8a80, 1, 0, None, 0),
    'Crystal': (0x7ff0ff, .2, .3, 0x1fb8c8, .6),
    # realistic kart and driver; the game swaps in each racer's colours and livery textures by these names
    'Paint': (0xe53935, .3, 0, None, 0),
    'PaintDark': (0x18191c, .45, 0, None, 0),
    'Trim': (0xffd23f, .35, 0, None, 0),
    'Panel': (0xffd23f, .35, 0, None, 0),
    'Pod': (0xe53935, .3, 0, None, 0),
    'Frame': (0xc9ced6, .18, 1, None, 0),
    'Alu': (0xa9adb3, .38, .9, None, 0),
    'Exhaust': (0x6b6c70, .45, .9, None, 0),
    'Brake': (0x8d9096, .3, .9, None, 0),
    'Seat': (0x1c1d21, .25, 0, None, 0),
    'Tank': (0xe8e6df, .4, 0, None, 0),
    'Rim': (0xbfc3c9, .3, .9, None, 0),
    'Tire': (0x151515, .8, 0, None, 0),
    'Grip': (0x17181b, .9, 0, None, 0),
    'SuitAccent': (0xff5c4d, .6, 0, None, 0),
    'Boot': (0x1a1a1d, .5, 0, None, 0),
    'Visor': (0x0e1318, .05, .6, None, 0),
    'Collar': (0x202226, .9, 0, None, 0),
}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h):
    return tuple(srgb_to_linear(((h >> s) & 255) / 255) for s in (16, 8, 0)) + (1.0,)


def get_material(name):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    col, rough, metal, emit, strength = MATERIALS[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = hex_rgba(col)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    if emit is not None:
        bsdf.inputs['Emission Color'].default_value = hex_rgba(emit)
        bsdf.inputs['Emission Strength'].default_value = strength
    mat.diffuse_color = hex_rgba(col)
    return mat


# --------------------------------------------------------------------------- mesh building blocks
# All builders return a fresh bmesh in game coordinates.

def xf(bm, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), order='XYZ'):
    """Scale, then rotate (Blender Euler order), then move."""
    m = Matrix.LocRotScale(Vector(loc), Euler(rot, order), Vector(scale))
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    return bm


def mirror_x(bm):
    bmesh.ops.transform(bm, matrix=Matrix.Scale(-1, 4, (1, 0, 0)), verts=bm.verts)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    return bm


def copy(bm):
    out = bm.copy()
    return out


def merge(*bms):
    out = bmesh.new()
    me = bpy.data.meshes.new('_merge')
    for b in bms:
        b.to_mesh(me)
        out.from_mesh(me)
        b.free()
    bpy.data.meshes.remove(me)
    return out


def surface(rings, wrap=True, cap_start=False, cap_end=False, fix_normals=True):
    """Skin consecutive rings of points into quads. Rings that collapse to a point become poles."""
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    m = n if wrap else n - 1
    for a, b in zip(vs, vs[1:]):
        for i in range(m):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    if cap_start:
        bm.faces.new(list(reversed(vs[0])))
    if cap_end:
        bm.faces.new(vs[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-7)
    if fix_normals:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def lathe(profile, segs=32, arc=TAU, start=0.0):
    """Revolve (radius, height) points about the Y axis. Profile runs bottom to top."""
    full = abs(arc - TAU) < 1e-6
    steps = segs if full else segs + 1
    rings = []
    for r, y in profile:
        ring = []
        for i in range(steps):
            t = start + arc * i / segs
            ring.append(Vector((r * math.sin(t), y, r * math.cos(t))))
        rings.append(ring)
    # transpose so rings run around the axis and consecutive rings follow the profile
    return surface(rings, wrap=full)


def cyl(r1, r2, h, segs=24, y=0.0):
    return lathe([(0, y - h / 2), (r1, y - h / 2), (r2, y + h / 2), (0, y + h / 2)], segs)


def ellipsoid(center, radii, segs=24, rings=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1)
    return xf(bm, center, scale=radii)


def ico(radius=1.0, subdiv=2):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    return bm


def rbox(size, center=(0, 0, 0), bevel=0.05, segs=2, rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    xf(bm, scale=size)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=segs, profile=0.5,
                        affect='EDGES', clamp_overlap=True)
    return xf(bm, center, rot)


def torus(R, r, segs=32, rsegs=10, arc=TAU):
    prof = [(R + r * math.cos(a), r * math.sin(a)) for a in
            [i / rsegs * TAU for i in range(rsegs + 1)]]
    bm = lathe(prof, segs, arc)
    return bm


def superellipse(t, n):
    c, s = math.cos(t), math.sin(t)
    return (math.copysign(abs(c) ** (2 / n), c), math.copysign(abs(s) ** (2 / n), s))


def loft(sections, segs=32, cap=True):
    """Sections along Z: (z, hx, y_bottom, y_top, n[, cx]). Cross-sections are superellipses."""
    rings = []
    for sec in sections:
        z, hx, yb, yt, n = sec[:5]
        cx = sec[5] if len(sec) > 5 else 0.0
        cy, hy_t, hy_b = (yb + yt) / 2, (yt - yb) / 2, (yt - yb) / 2
        ring = []
        for i in range(segs):
            t = i / segs * TAU
            u, v = superellipse(t, n)
            ring.append(Vector((cx + hx * u, cy + (hy_t if v > 0 else hy_b) * v, z)))
        rings.append(ring)
    return surface(rings, cap_start=cap, cap_end=cap)


def frames(path):
    """Parallel-transport frames along a polyline."""
    tans = []
    for i in range(len(path)):
        a = path[max(i - 1, 0)]
        b = path[min(i + 1, len(path) - 1)]
        tans.append((b - a).normalized())
    up = Vector((0, 1, 0)) if abs(tans[0].y) < 0.9 else Vector((1, 0, 0))
    n = tans[0].cross(up).normalized()
    out = []
    for i, t in enumerate(tans):
        if i:
            n = n - t * n.dot(t)
            n.normalize()
        out.append((t, n, t.cross(n).normalized()))
    return out


def sweep(path, radius, segs=12, caps=True):
    """Tube along a polyline; radius can be a number or a list matching the path."""
    path = [Vector(p) for p in path]
    radii = radius if isinstance(radius, (list, tuple)) else [radius] * len(path)
    rings = []
    for p, (t, n, b), r in zip(path, frames(path), radii):
        rings.append([p + (n * math.cos(a) + b * math.sin(a)) * r for a in
                      [i / segs * TAU for i in range(segs)]])
    return surface(rings, cap_start=caps and radii[0] > 0, cap_end=caps and radii[-1] > 0)


def bezier(p0, p1, p2, p3=None, steps=16):
    """Quadratic (3 points) or cubic (4 points) Bezier as a point list."""
    p0, p1, p2 = Vector(p0), Vector(p1), Vector(p2)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        if p3 is None:
            pts.append((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t * t * p2)
        else:
            q = Vector(p3)
            pts.append((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * q)
    return pts


def taper(n, r0, r1, power=1.0):
    return [r0 + (r1 - r0) * (i / (n - 1)) ** power for i in range(n)]


def extrude_outline(pts, depth, bevel=0.0):
    """Flat outline in the XY plane extruded along Z, centred on z=0."""
    bm = bmesh.new()
    front = [bm.verts.new((x, y, depth / 2)) for x, y in pts]
    back = [bm.verts.new((x, y, -depth / 2)) for x, y in pts]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((front[i], back[i], back[j], front[j]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if bevel:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=bevel, segments=2, profile=0.5,
                        affect='EDGES', clamp_overlap=True)
    return bm


def with_modifiers(bm, mods):
    """Run Blender modifiers over a bmesh: mods is [(type, {prop: value})]."""
    me = bpy.data.meshes.new('_mod')
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new('_mod', me)
    bpy.context.scene.collection.objects.link(ob)
    for kind, props in mods:
        mod = ob.modifiers.new(kind, kind)
        for k, v in props.items():
            setattr(mod, k, v)
    dg = bpy.context.evaluated_depsgraph_get()
    me2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    out = bmesh.new()
    out.from_mesh(me2)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    bpy.data.meshes.remove(me2)
    return out


def subsurf(bm, levels=2):
    return with_modifiers(bm, [('SUBSURF', {'levels': levels, 'render_levels': levels})])


def text_mesh(body, size=1.0, extrude=0.1, bevel=0.02):
    cu = bpy.data.curves.new('_text', 'FONT')
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.bevel_depth = bevel
    cu.bevel_resolution = 2
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    ob = bpy.data.objects.new('_text', cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    bpy.data.meshes.remove(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    # centre it exactly on the origin
    lo = Vector([min(v.co[i] for v in bm.verts) for i in range(3)])
    hi = Vector([max(v.co[i] for v in bm.verts) for i in range(3)])
    return xf(bm, -(lo + hi) / 2)


# --------------------------------------------------------------------------- assets
ASSETS = []


class Asset:
    """One exported mesh object built from parts, each part tagged with a material slot."""

    def __init__(self, name, sharp_angle=40, scale=1.0):
        self.name = name
        self.scale = scale
        self.bm = bmesh.new()
        self.mats = []
        self.sharp_angle = sharp_angle
        self._me = bpy.data.meshes.new('_part')
        ASSETS.append(self)

    def slot(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def add(self, part, mat, smooth=True, paint=None):
        """paint(center, normal) may return another material name for individual faces."""
        idx = self.slot(mat)
        for f in part.faces:
            f.smooth = smooth
            f.material_index = idx
            if paint:
                other = paint(f.calc_center_median(), f.normal)
                if other:
                    f.material_index = self.slot(other)
        part.to_mesh(self._me)
        self.bm.from_mesh(self._me)
        part.free()
        return self

    def build(self):
        me = bpy.data.meshes.new(self.name)
        # game frame (Y up, +Z forward) -> Blender frame (Z up, -Y forward), at game scale
        bmesh.ops.transform(self.bm, matrix=Matrix.Rotation(math.radians(90), 4, 'X') @ Matrix.Scale(self.scale, 4),
                            verts=self.bm.verts)
        self.bm.to_mesh(me)
        self.bm.free()
        bpy.data.meshes.remove(self._me)
        me.set_sharp_from_angle(angle=math.radians(self.sharp_angle))
        for m in self.mats:
            me.materials.append(get_material(m))
        ob = bpy.data.objects.new(self.name, me)
        return ob


def mirrored(fn):
    """Build a part on the +X side and return both sides merged."""
    return merge(fn(), mirror_x(fn()))


# --------------------------------------------------------------------------- realistic kart and driver
# Modelled in real-world metres, a CIK-style 125cc race kart and an adult driver, then scaled by K
# to the size the game's physics expects. PIVOTS become empty nodes in the GLB: the game reads the
# wheel, steering, hip, neck and shoulder positions from them instead of hard-coding numbers.
K = 1.9
PIVOTS = {}


def pivot(name, pos, rx=0.0):
    PIVOTS[name] = (Vector(pos), rx)


def uv_map(bm, fn, wrap_u=False):
    """Per-loop UVs from fn(co) -> (u, v); wrap_u fixes faces that straddle the u=0/1 seam."""
    lay = bm.loops.layers.uv.get('UVMap') or bm.loops.layers.uv.new('UVMap')
    for f in bm.faces:
        uvs = [fn(l.vert.co) for l in f.loops]
        if wrap_u:
            cu = fn(f.calc_center_median())[0]
            uvs = [((u + 1) if cu - u > .5 else (u - 1) if u - cu > .5 else u, v) for u, v in uvs]
        for l, uv in zip(f.loops, uvs):
            l[lay].uv = uv
    return bm


def planar_uv(bm, a, b, lo, hi):
    """Project onto axes a and b (0=x, 1=y, 2=z), mapping lo..hi to 0..1."""
    return uv_map(bm, lambda co: ((co[a] - lo[0]) / (hi[0] - lo[0]), (co[b] - lo[1]) / (hi[1] - lo[1])))


def local(bm, origin):
    """Move a part built in kart coordinates into a pivot's frame."""
    return xf(bm, (-origin[0], -origin[1], -origin[2]))


def build_kart():
    a = Asset('kart_body', sharp_angle=45, scale=K)
    R = .015   # 30 mm chassis tube
    # chassis rails, cross members, front and side bumpers
    a.add(mirrored(lambda: sweep(bezier((.19, .075, .8), (.35, .06, .45), (.34, .06, -.2), (.3, .085, -.56), 22), R, 10)), 'Frame')
    for z, hw, y in [(.64, .26, .07), (.2, .34, .06), (-.3, .33, .065)]:
        a.add(sweep([(-hw, y, z), (hw, y, z)], R * .9, 10), 'Frame')
    a.add(sweep(bezier((-.3, .12, .72), (-.36, .15, 1.02), (.36, .15, 1.02), (.3, .12, .72), 18), R * .9, 10), 'Frame')
    a.add(mirrored(lambda: sweep(bezier((.3, .07, .38), (.63, .1, .38), (.63, .1, -.34), (.3, .07, -.34), 18), R * .9, 10)), 'Frame')
    # floor tray, fuel tank, pedals
    a.add(rbox((.36, .012, .6), (0, .05, .28), .005, 1), 'Alu')
    a.add(rbox((.17, .11, .25), (0, .12, .43), .045, 3), 'Tank')
    a.add(xf(cyl(.018, .018, .03, 12), (0, .19, .43), (0, 0, 0)), 'Dark')
    for x in (-.1, .1):
        a.add(rbox((.07, .012, .1), (x, .13, .67), .004, 1, rot=(-.9, 0, 0)), 'Alu')
    # front axle stubs, kingpins and tie rods
    for sg in (-1, 1):
        a.add(rbox((.05, .07, .06), (sg * .43, .127, .52), .012), 'Alu')
        a.add(sweep([(sg * .32, .1, .5), (sg * .43, .127, .52)], .012, 8), 'Frame')
        a.add(sweep([(0, .1, .66), (sg * .42, .12, .45)], .007, 6), 'Alu')
    # rear axle with bearing hangers, brake disc and caliper, sprocket and chain guard
    a.add(xf(cyl(.025, .025, 1.46, 18), (0, .14, -.52), (0, 0, math.pi / 2)), 'Alu')
    for x in (-.3, .3):
        a.add(rbox((.05, .09, .06), (x, .12, -.52), .01), 'Alu')
    a.add(xf(cyl(.1, .1, .008, 32), (-.14, .14, -.52), (0, 0, math.pi / 2)), 'Brake')
    a.add(rbox((.04, .07, .06), (-.14, .21, -.52), .012), 'Trim')
    a.add(xf(cyl(.075, .075, .006, 28), (.42, .14, -.52), (0, 0, math.pi / 2)), 'Alu')
    a.add(rbox((.02, .09, .34), (.45, .14, -.37), .008), 'Dark')
    # front nose cone: black lower half, livery colour on top, accent strip across the front
    nose = loft([(.64, .36, .1, .17, 3.0), (.78, .45, .08, .21, 3.4), (.92, .44, .09, .2, 3.2),
                 (.99, .37, .105, .18, 2.6), (1.03, .2, .12, .16, 2.2)], segs=40)
    a.add(nose, 'Paint', paint=lambda c, n: 'PaintDark' if c.y < .115 else ('Trim' if c.z > .97 else None))
    # front number panel, curved, mounted on the steering column
    rows = []
    for i in range(9):
        y = .2 + .26 * i / 8
        rows.append([Vector((x, y, .6 - .07 * (x / .21) ** 2 - (y - .2) * .32)) for x in [-.21 + .42 * k / 16 for k in range(17)]])
    panel = with_modifiers(surface(rows, wrap=False), [('SOLIDIFY', {'thickness': .008, 'offset': 0})])
    a.add(planar_uv(panel, 0, 1, (-.21, .2), (.21, .46)), 'Panel')
    a.add(sweep([(0, .12, .64), (0, .22, .6)], .01, 6), 'Dark')
    # side pods; UVs run front-to-back as seen from each side so the stickers read correctly
    for sg in (-1, 1):
        pod = loft([(-.42, .02, .11, .14, 2.0, .53), (-.37, .085, .08, .19, 3.0, .53), (-.2, .1, .07, .21, 3.4, .53),
                    (.22, .1, .07, .2, 3.4, .53), (.37, .085, .08, .18, 3.0, .53), (.42, .02, .1, .14, 2.0, .53)], segs=28)
        if sg < 0:
            mirror_x(pod)
        planar_uv(pod, 2, 1, (.42, .07), (-.42, .21)) if sg > 0 else planar_uv(pod, 2, 1, (-.42, .07), (.42, .21))
        a.add(pod, 'Pod', paint=lambda c, n: 'PaintDark' if c.y < .09 else None)
    # rear bumper: black plastic bar that wraps round the rear wheels
    bump = loft([(-.76, .03, .1, .16, 2.0), (-.72, .1, .07, .2, 3), (.72, .1, .07, .2, 3), (.76, .03, .1, .16, 2.0)], segs=20)
    xf(bump, rot=(0, math.pi / 2, 0))
    xf(bump, (0, 0, -.84))
    a.add(bump, 'PaintDark')
    for sg in (-1, 1):
        a.add(rbox((.08, .12, .26), (sg * .72, .13, -.74), .03), 'PaintDark')
        a.add(sweep([(sg * .3, .09, -.56), (sg * .5, .12, -.82)], R * .8, 8), 'Frame')
    # bucket seat: a U-shaped fibreglass shell swept up the driver's back
    spine = bezier((0, .07, -.02), (0, .06, -.28), (0, .52, -.44), steps=14)
    sec_rows = []
    for (p, (t, n, bn), i) in zip(spine, frames([Vector(v) for v in spine]), range(len(spine))):
        s = i / (len(spine) - 1)
        w, d = .17 + .04 * s, .07 + .05 * math.sin(math.pi * s)
        nrm = t.cross(Vector((1, 0, 0))).normalized()
        if nrm.y < 0 and s < .5 or nrm.z > 0:
            nrm = -nrm
        sec_rows.append([Vector(p) + Vector((w * math.sin(th), 0, 0)) + nrm * (d * (1 - math.cos(th)))
                         for th in [-1.35 + 2.7 * k / 16 for k in range(17)]])
    seat = with_modifiers(surface(sec_rows, wrap=False), [('SOLIDIFY', {'thickness': .008, 'offset': 0})])
    a.add(seat, 'Seat')
    for sg in (-1, 1):
        a.add(sweep([(sg * .16, .3, -.36), (sg * .3, .09, -.4)], .009, 6), 'Frame')
    # engine on the right: crankcase, finned cylinder, head, carburettor, airbox behind the seat
    a.add(rbox((.13, .14, .18), (.34, .13, -.3), .03), 'Alu')
    fins = [(0, 0)]
    for i in range(8):
        y = .012 + i * .018
        fins += [(.045, y), (.068, y + .004), (.068, y + .01), (.045, y + .014)]
    fins += [(0, .16)]
    a.add(xf(lathe(fins, 20), (.34, .2, -.27), (0, 0, -.25)), 'Alu')
    a.add(xf(rbox((.08, .04, .08), (0, 0, 0), .015), (.38, .36, -.27), (0, 0, -.25)), 'Dark')
    a.add(xf(cyl(.012, .012, .05, 10), (.4, .39, -.25), (0, 0, -.25)), 'Trim')
    a.add(xf(cyl(.028, .028, .09, 16), (.33, .24, -.17), (math.pi / 2, 0, 0)), 'Alu')
    a.add(rbox((.34, .14, .13), (.02, .25, -.6), .035), 'PaintDark')
    for x in (-.08, .1):
        a.add(sweep(bezier((x, .24, -.53), (x, .25, -.45), (x, .22, -.4), steps=8), .025, 12), 'PaintDark')
    # exhaust: header curling out of the cylinder into a silencer along the right side
    hdr = bezier((.4, .24, -.22), (.52, .22, -.2), (.58, .3, -.35), (.52, .32, -.46), 16)
    a.add(sweep(hdr, taper(len(hdr), .02, .026), 12), 'Exhaust')
    a.add(xf(lathe([(0, -.19), (.04, -.19), (.052, -.15), (.052, .15), (.04, .19), (0, .19)], 22), (.52, .32, -.64), (math.pi / 2, 0, 0)), 'Exhaust')
    a.add(xf(cyl(.018, .018, .05, 12), (.52, .32, -.84), (math.pi / 2, 0, 0)), 'Dark')
    # steering column from the floor up to the wheel hub (the steer pivot)
    hub, tilt = Vector((0, .47, .15)), -1.0
    axis = Vector((0, math.cos(tilt), math.sin(tilt)))
    a.add(sweep([hub - axis * .72, hub - axis * .03], .011, 10), 'Frame')
    pivot('pivot_steer', hub, tilt)
    return a


def build_wheel(name, r, w, side):
    """Slick tyre on a magnesium rim, at its axle pivot; the hub faces outward (side = +1 right, -1 left)."""
    a = Asset(name, sharp_angle=35, scale=K)
    rim_r, hw = .066, w / 2
    prof = [(rim_r + .002, -hw + .008), (rim_r + .02, -hw - .002), (r * .8, -hw - .007), (r - .013, -hw + .002),
            (r - .003, -hw + .02), (r, -hw + .04), (r, 0), (r, hw - .04), (r - .003, hw - .02), (r - .013, hw - .002),
            (r * .8, hw + .007), (rim_r + .02, hw + .002), (rim_r + .002, hw - .008)]
    tire = xf(lathe(prof + [prof[0]], 56), rot=(0, 0, -math.pi / 2))
    rim = xf(lathe([(0, .03), (.03, .03), (.035, hw - .03), (rim_r - .004, hw - .018), (rim_r + .004, hw - .004),
                    (rim_r - .002, hw), (rim_r - .004, -hw + .006), (rim_r + .003, -hw + .004), (rim_r - .002, -hw)], 36),
             rot=(0, 0, -math.pi / 2))
    hubp = merge(xf(cyl(.03, .026, .03, 16), (hw - .005, 0, 0), (0, 0, -math.pi / 2)),
                 *[xf(cyl(.006, .006, .02, 8), (hw + .004, .018 * math.cos(k * TAU / 3), .018 * math.sin(k * TAU / 3)), (0, 0, -math.pi / 2)) for k in range(3)])
    if side < 0:
        for p in (tire, rim, hubp):
            mirror_x(p)

    def tyre_uv(co):
        ang = math.atan2(co.y, co.z) / TAU + .5
        if co.x * side < 0:   # inner sidewall reads the other way round
            ang = 1 - ang
        if side < 0:
            ang = 1 - ang
        rr = math.hypot(co.y, co.z)
        return ang, min(max((rr - rim_r) / (r - rim_r), 0), 1)
    a.add(uv_map(tire, tyre_uv, wrap_u=True), 'Tire')
    a.add(rim, 'Rim')
    a.add(hubp, 'Alu')
    return a


def build_steering_wheel():
    """In the steer pivot frame: rim in the local XZ plane, turning about local Y (the column)."""
    a = Asset('kart_steer', scale=K)
    pts = []
    for i in range(40):   # a slightly flattened-bottom rim
        t = i / 40 * TAU
        x, z = .16 * math.cos(t), .15 * math.sin(t)
        pts.append(Vector((x, 0, max(z, -.12))))
    rim = sweep(pts + [pts[0]], .015, 10, caps=False)
    a.add(rim, 'Grip')
    a.add(cyl(.04, .04, .03, 20), 'Trim')
    for ang in (0, math.pi, math.pi * 1.5):
        a.add(xf(rbox((.12, .01, .03), (.08, 0, 0), .004, 1), rot=(0, ang, 0)), 'Alu')
    return a


# --------------------------------------------------------------------------- driver (real metres, pivots in kart frame)
HIP = Vector((0, .22, -.2))
NECK = Vector((0, .69, -.37))
SHOULDER = Vector((.2, .6, -.33))
UPPER, FORE = .29, .27


def build_driver():
    pivot('pivot_driver', HIP)
    pivot('pivot_head', NECK)
    pivot('pivot_shoulder_R', SHOULDER)
    pivot('pivot_shoulder_L', (-SHOULDER.x, SHOULDER.y, SHOULDER.z))
    a = Asset('driver_body', scale=K)
    lean = .5
    torso = loft([(0, .16, -.11, .11, 2.6), (.1, .17, -.12, .12, 2.8), (.2, .16, -.11, .12, 2.8), (.32, .2, -.13, .12, 3.0),
                  (.4, .21, -.12, .11, 3.0), (.46, .16, -.1, .09, 2.6), (.5, .07, -.06, .06, 2.2)], segs=28)
    xf(torso, rot=(-math.pi / 2 - lean, 0, 0))
    xf(torso, (0, .16, -.19))

    def suit_paint(c, n):
        if abs(c.x) > .135:
            return 'SuitAccent'
        return None
    a.add(local(torso, HIP), 'Suit', paint=suit_paint)
    a.add(local(ellipsoid((0, .15, -.2), (.18, .1, .16), 20, 12), HIP), 'Suit')
    for sg in (-1, 1):
        a.add(local(ellipsoid((sg * .19, .59, -.33), (.075, .065, .075), 14, 10), HIP), 'SuitAccent')
        hip_j, knee, ankle = Vector((sg * .1, .18, -.14)), Vector((sg * .21, .34, .2)), Vector((sg * .16, .15, .52))
        a.add(local(sweep([hip_j, hip_j.lerp(knee, .5), knee], [.08, .072, .062], 14), HIP), 'Suit')
        a.add(local(ellipsoid(knee, (.064, .064, .064), 14, 10), HIP), 'Suit')
        a.add(local(sweep([knee, knee.lerp(ankle, .5), ankle], [.058, .05, .045], 14), HIP), 'Suit')
        boot = loft([(0, .045, -.05, .05, 2.4), (.06, .045, -.045, .04, 2.6), (.13, .04, -.035, .025, 2.6), (.16, .02, -.025, .015, 2.2)], segs=16)
        xf(boot, rot=(.35, 0, 0))
        a.add(local(xf(boot, (ankle.x, ankle.y - .02, ankle.z - .02)), HIP), 'Boot')
    # neck collar (foam support) where the helmet sits
    a.add(local(xf(torus(.085, .035, 22, 8), (0, .66, -.36), (-.45, 0, 0)), HIP), 'Collar')
    return a


def build_helmet():
    """Full-face helmet in the neck pivot frame, spherical UVs for the livery (front of helmet at u=0.5)."""
    a = Asset('driver_head', scale=K)
    c, rx, ry, rz = Vector((0, .13, .01)), .135, .145, .158
    lat_n, lon_n = 20, 48
    bm = bmesh.new()
    verts = {}
    for i in range(lat_n + 1):
        lat = -math.pi / 2 + math.pi * i / lat_n
        for j in range(lon_n):
            lon = j / lon_n * TAU
            # flatten the underside into a neck opening and pull the chin bar forward
            y = math.sin(lat)
            chin = max(0.0, -y) * max(0.0, math.cos(lon)) * .25
            verts[i, j] = bm.verts.new((c.x + rx * math.cos(lat) * math.sin(lon), c.y + ry * max(y, -.72),
                                        c.z + rz * math.cos(lat) * math.cos(lon) * (1 + chin)))
    for i in range(lat_n):
        lat = -math.pi / 2 + math.pi * (i + .5) / lat_n
        if lat < -1.2:
            continue   # neck opening
        for j in range(lon_n):
            lon = (j + .5) / lon_n * TAU
            lon_c = lon if lon < math.pi else lon - TAU
            if abs(lon_c) < .95 and -.18 < lat < .26:
                continue   # eye port
            bm.faces.new((verts[i, j], verts[i, (j + 1) % lon_n], verts[i + 1, (j + 1) % lon_n], verts[i + 1, j]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    def sph_uv(co):
        d = co - c
        return math.atan2(d.x, d.z) / TAU + .5, math.asin(max(-1, min(1, d.y / ry))) / math.pi + .5
    uv_map(bm, sph_uv, wrap_u=True)
    shell = with_modifiers(bm, [('SOLIDIFY', {'thickness': .012, 'offset': -1})])
    a.add(shell, 'Helmet')
    a.add(ellipsoid(c + Vector((0, 0, -.01)), (rx - .02, ry - .025, rz - .03), 20, 14), 'Dark')   # padding seen through the visor
    # tinted visor over the eye port, with pivot screws
    rows = []
    for i in range(7):
        lat = -.24 + .56 * i / 6
        rows.append([c + Vector(((rx + .006) * math.cos(lat) * math.sin(lon), (ry + .004) * math.sin(lat),
                                 (rz + .01) * math.cos(lat) * math.cos(lon))) for lon in [-1.08 + 2.16 * k / 20 for k in range(21)]])
    a.add(with_modifiers(surface(rows, wrap=False), [('SOLIDIFY', {'thickness': .004, 'offset': 0})]), 'Visor')
    for sg in (-1, 1):
        a.add(xf(cyl(.016, .016, .01, 14), (sg * (rx + .004), c.y + .01, c.z + .02), (0, 0, math.pi / 2)), 'Dark')
    # chin vent and rear spoiler
    a.add(rbox((.06, .025, .02), (0, c.y - .09, c.z + rz * 1.14), .008), 'Dark')
    spoiler = extrude_outline([(-.05, 0), (.04, 0), (.025, .014), (-.04, .012)], .1, .004)
    a.add(xf(spoiler, (0, c.y + .07, c.z - rz + .005), (0, math.pi / 2, 0)), 'Helmet')
    # balaclava neck between collar and helmet
    a.add(cyl(.055, .06, .08, 16, y=.02), 'Collar')
    return a


def build_arms():
    """Upper arm and forearm point along +Z from their joint; the game solves the elbow each frame."""
    a = Asset('driver_upperarm', scale=K)
    a.add(sweep([(0, 0, 0), (0, 0, UPPER * .5), (0, 0, UPPER)], [.052, .047, .042], 14), 'Suit')
    a.add(ellipsoid((0, 0, 0), (.058, .058, .058), 14, 10), 'Suit')
    a.add(ellipsoid((0, 0, UPPER), (.043, .043, .043), 12, 8), 'Suit')
    a = Asset('driver_forearm', scale=K)
    a.add(sweep([(0, 0, 0), (0, 0, FORE * .6), (0, 0, FORE - .02)], [.041, .038, .034], 14), 'Suit')
    a.add(xf(torus(.036, .008, 16, 6), (0, 0, FORE * .7), (math.pi / 2, 0, 0)), 'SuitAccent')
    a = Asset('driver_glove', scale=K)
    a.add(rbox((.085, .035, .1), (0, 0, .03), .016, 2), 'Glove')
    a.add(xf(sweep([(0, 0, 0), (0, 0, .05)], .012, 8), (.045, .004, .01), (0, -.6, 0)), 'Glove')
    a.add(xf(cyl(.042, .046, .06, 16), (0, 0, -.03), (math.pi / 2, 0, 0)), 'Glove')
    return UPPER * K, FORE * K


def build_kart_and_driver():
    build_kart()
    for name, z, r, w, x in [('front', .52, .127, .115, .51), ('rear', -.52, .14, .185, .6)]:
        for side, tag in ((1, 'R'), (-1, 'L')):
            build_wheel(f'kart_wheel_{name}_{tag}', r, w, side)
            pivot(f'pivot_wheel_{name}_{tag}', (side * x, r, z))
    build_steering_wheel()
    build_driver()
    build_helmet()
    build_arms()


# --------------------------------------------------------------------------- items
def build_items():
    # homing rocket, nose toward +Z
    a = Asset('rocket')
    body = lathe([(0, -.8), (.28, -.78), (.36, -.55), (.4, -.1), (.38, .25), (.32, .5), (.2, .75), (.08, .9),
                  (0, .95)], 28)
    a.add(xf(body, rot=(math.pi / 2, 0, 0)), 'RocketBody',
          paint=lambda c, n: 'RocketFin' if c.z > .55 or -.2 < c.z < -.05 else None)
    for i in range(4):
        fin = extrude_outline([(.3, -.75), (.72, -.95), (.72, -.72), (.3, -.25)], .05, .012)
        xf(fin, rot=(math.pi / 2, 0, 0))
        xf(fin, rot=(0, 0, i * math.pi / 2 + math.pi / 4))
        a.add(fin, 'RocketFin')
    a.add(xf(cyl(.2, .26, .2, 20), (0, 0, -.88), (math.pi / 2, 0, 0)), 'Dark')
    for sg in (-1, 1):
        a.add(ellipsoid((sg * .3, .12, .15), (.06, .09, .09), 12, 8), 'Glass')

    # oil slick: a puddle with a lumpy rim and a few bubbles, lying flat on the road
    a = Asset('oil')
    ring = []
    for i in range(40):
        t = i / 40 * TAU
        r = 1.6 * (1 + .12 * math.sin(3 * t + .5) + .08 * math.sin(5 * t + 1.3) + .05 * math.sin(9 * t))
        ring.append((r * math.cos(t), r * math.sin(t)))
    rings = []
    for k, (s, h) in enumerate([(1, 0), (.92, .05), (.7, .07), (.35, .08), (0, .08)]):
        rings.append([Vector((x * s, h, -y * s)) for x, y in ring])
    a.add(surface(rings), 'Oil')
    for x, z, r in [(.5, .3, .18), (-.6, -.2, .12), (.1, -.7, .1), (-.3, .6, .08)]:
        a.add(ellipsoid((x, .08, z), (r, r * .6, r), 14, 8), 'Oil')

    # item box: rounded cube, with a floating question mark inside
    a = Asset('itembox')
    a.add(rbox((1.7, 1.7, 1.7), bevel=.22, segs=4), 'ItemBox')
    a = Asset('itembox_core')
    a.add(text_mesh('?', size=1.25, extrude=.12, bevel=.03), 'Core')


# --------------------------------------------------------------------------- scenery (geometry the game instances)
def build_scenery():
    # pine: trunk y in [-1.5, 1.5], three jagged tiers of needles y in [-3, 3]
    a = Asset('tree_trunk')
    a.add(lathe([(0, -1.5), (.62, -1.5), (.48, -1.2), (.4, -.4), (.34, .6), (.28, 1.5), (0, 1.5)], 10), 'Bark')
    a = Asset('tree_leaves', sharp_angle=30)
    for base, top, r in [(-3.0, .4, 2.4), (-1.3, 1.9, 1.9), (.4, 3.0, 1.3)]:
        segs = 11
        skirt, inner = [], []
        for i in range(segs * 2):
            t = i / (segs * 2) * TAU
            rr = r if i % 2 == 0 else r * .78
            dy = -.25 if i % 2 == 0 else .05
            skirt.append(Vector((rr * math.sin(t), base + dy, rr * math.cos(t))))
            inner.append(Vector((rr * .45 * math.sin(t), base + .35, rr * .45 * math.cos(t))))
        tip = [Vector((0, top, 0))] * (segs * 2)
        mid = [p.lerp(Vector((0, top, 0)), .45) + Vector((0, .1, 0)) for p in skirt]
        a.add(surface([inner, skirt, mid, tip]), 'Leaves', smooth=False)

    # palm: ringed trunk y in [-3.5, 3.5]; frond along +Y y in [-2.2, 2.2] with leaflets across X
    a = Asset('palm_trunk')
    prof = [(0, -3.5)]
    for i in range(15):
        y = -3.5 + i * .5
        r = .42 + (.2 - .42) * i / 14
        prof += [(r, y), (r * 1.1, y + .12), (r * .95, y + .45)]
    prof += [(0, 3.5)]
    a.add(lathe(prof, 10), 'Bark')
    a = Asset('palm_frond', sharp_angle=20)
    rows = []
    for i in range(17):
        y = -2.2 + 4.4 * i / 16
        w = .75 * math.sin(math.pi * min(i + .5, 16) / 16.5) * (1 if i % 2 else .72)   # serrated edge
        sweep_fwd = .25 * w
        rows.append([Vector((-w, y + sweep_fwd, .1 * w)), Vector((0, y, 0)), Vector((w, y + sweep_fwd, .1 * w))])
    blade = surface(rows, wrap=False, fix_normals=False)
    back = surface(rows, wrap=False, fix_normals=False)
    bmesh.ops.reverse_faces(back, faces=back.faces)   # two-sided, so it reads from above and below
    a.add(merge(blade, back), 'Frond', smooth=False)

    # cactus: ribbed capsules, body y in [-1.85, 1.85] radius .35, arm y in [-.75, .75] radius .2
    def ribbed(radius, half, segs=24, ribs=8):
        rings, prof, n_cap = [], [], 5
        for k in range(n_cap + 1):   # bottom cap
            a_ = -math.pi / 2 + k / n_cap * math.pi / 2
            prof.append((-half + radius + radius * math.sin(a_), radius * math.cos(a_)))
        for k in range(1, 6):
            prof.append((-half + radius + (2 * half - 2 * radius) * k / 6, radius))
        for k in range(n_cap + 1):   # top cap
            a_ = k / n_cap * math.pi / 2
            prof.append((half - radius + radius * math.sin(a_), radius * math.cos(a_)))
        for y, r in prof:
            ring = []
            for i in range(segs):
                t = i / segs * TAU
                rr = r * (1 + .1 * math.cos(ribs * t))
                ring.append(Vector((rr * math.sin(t), y, rr * math.cos(t))))
            rings.append(ring)
        return surface(rings)
    Asset('cactus_body').add(ribbed(.35, 1.85), 'Cactus')
    Asset('cactus_arm').add(ribbed(.2, .75, 16, 6), 'Cactus')

    # rock: a lumpy, faceted boulder of radius ~1.2
    a = Asset('rock', sharp_angle=1)
    bm = ico(1.2, 2)
    for v in bm.verts:
        d = noise.noise(v.co * 1.1 + Vector((3.1, 7.7, 1.3)))
        v.co *= 1 + .22 * d
        v.co.y *= .9
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(10), verts=bm.verts, edges=bm.edges)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    a.add(bm, 'Rock', smooth=False)

    # crystal cluster, radius ~1 and y in [-.5, .5] to fit the old cone's footprint
    a = Asset('crystal', sharp_angle=1)
    for (x, z, h, r, tx, tz) in [(0, 0, 1.0, .5, 0, 0), (.45, .15, .62, .3, 0, -.45), (-.35, .3, .5, .26, .4, .35),
                                 (.05, -.45, .45, .22, .45, -.1)]:
        c = lathe([(0, 0), (r, 0), (r, h * .72), (0, h)], 6)
        xf(c, rot=(tx, 0, tz))
        xf(c, (x, -.5, z))
        a.add(c, 'Crystal', smooth=False)


# --------------------------------------------------------------------------- main
def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    opts = {'out': os.path.join(HERE, '..', 'assets', 'kartlands.glb'), 'blend': None, 'export': bpy.app.background}
    it = iter(argv)
    for arg in it:
        if arg == '--out':
            opts['out'] = next(it)
        elif arg == '--blend':
            opts['blend'] = next(it)
        elif arg == '--no-export':
            opts['export'] = False
    return opts


def main():
    opts = parse_args()
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
    else:   # inside the Blender UI: build into a fresh scene and leave the user's file alone
        scene = bpy.data.scenes.new('Kartlands')
        bpy.context.window.scene = scene
    build_kart_and_driver()
    build_items()
    build_scenery()

    # lay the objects out in a grid so the .blend is easy to browse; the game ignores placement
    col = bpy.data.collections.new('Kartlands')
    bpy.context.scene.collection.children.link(col)
    for i, asset in enumerate(ASSETS):
        ob = asset.build()
        if ob.data.uv_layers:
            ob.data.uv_layers[0].name = 'UVMap'
        col.objects.link(ob)
        ob.location = ((i % 8) * 7.0, (i // 8) * 7.0, 0)
    tris = sum(sum(len(p.vertices) - 2 for p in ob.data.polygons) for ob in col.objects)
    # pivots: empties in the kart's frame (game Y-up coordinates -> Blender Z-up), at game scale
    for name, (pos, rx) in PIVOTS.items():
        em = bpy.data.objects.new(name, None)
        em.empty_display_size = .15
        em.location = (pos.x * K, -pos.z * K, pos.y * K)
        em.rotation_euler = (rx, 0, 0)
        col.objects.link(em)
    print(f'built {len(col.objects)} meshes, {tris} triangles')

    if opts['blend']:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(opts['blend']))
    if opts['export']:
        # export at the origin: every part carries its own pivot
        for ob in col.objects:
            if ob.type == 'MESH':
                ob.location = (0, 0, 0)
        out = os.path.abspath(opts['out'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_yup=True, export_apply=True,
                                  export_texcoords=True, export_normals=True, export_materials='EXPORT',
                                  export_animations=False, export_extras=False)
        print(f'wrote {out} ({os.path.getsize(out) // 1024} KB)')


if __name__ == '__main__':
    main()
