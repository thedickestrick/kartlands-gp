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

    def __init__(self, name, sharp_angle=40):
        self.name = name
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
        # game frame (Y up, +Z forward) -> Blender frame (Z up, -Y forward)
        bmesh.ops.transform(self.bm, matrix=Matrix.Rotation(math.radians(90), 4, 'X'), verts=self.bm.verts)
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


# --------------------------------------------------------------------------- kart
def build_kart_body():
    a = Asset('kart_body', sharp_angle=50)
    # main tub: lofted superellipse sections, nose to tail. Lower skirt in the darker body colour,
    # a racing stripe down the top.
    secs = [
        (-1.80, .10, .55, .72, 2.4),
        (-1.72, .68, .40, .82, 2.6),
        (-1.55, .90, .35, .93, 2.8),
        (-1.20, .99, .33, .98, 3.0),
        (-0.60, 1.02, .32, .97, 3.0),
        (0.00, 1.00, .32, .94, 3.0),
        (0.50, .92, .32, .97, 2.8),
        (1.00, .80, .33, .90, 2.6),
        (1.50, .66, .34, .80, 2.5),
        (1.95, .52, .35, .69, 2.4),
        (2.30, .38, .37, .59, 2.3),
        (2.48, .22, .40, .52, 2.2),
        (2.54, .06, .44, .48, 2.0),
    ]
    tub = loft(secs, segs=40)

    def half_width(z):
        for (z0, h0, *_), (z1, h1, *_) in zip(secs, secs[1:]):
            if z0 <= z <= z1:
                return h0 + (h1 - h0) * (z - z0) / (z1 - z0)
        return secs[-1][1]

    def tub_paint(c, n):
        if c.y < .47:
            return 'BodyDark'
        if abs(c.x) < .18 * half_width(c.z) and n.y > .5 and c.z > .45:
            return 'Accent'
        return None
    a.add(tub, 'Body', paint=tub_paint)

    # side pods between the wheels, with a dark intake slot on top
    def pod():
        p = loft([
            (-.52, .05, .50, .56, 2.0, .98),
            (-.44, .17, .40, .70, 2.6, .98),
            (-.2, .22, .38, .74, 3.0, 1.0),
            (.2, .22, .38, .74, 3.0, 1.0),
            (.40, .16, .40, .70, 2.6, .98),
            (.48, .04, .50, .56, 2.0, .98),
        ], segs=24)
        return p
    a.add(mirrored(pod), 'Body', paint=lambda c, n: 'BodyDark' if c.y < .5 else None)
    a.add(mirrored(lambda: rbox((.12, .05, .5), (1.0, .745, 0), .02)), 'Dark')

    # floor pan and front splitter
    a.add(rbox((2.0, .08, 3.3), (0, .31, .15), .035), 'Dark')
    a.add(rbox((1.0, .05, .45), (0, .36, 2.22), .02, 2), 'Dark')

    # bumpers: chrome tubes wrapping nose and tail
    front = bezier((-.95, .46, 1.35), (-1.05, .46, 2.75), (1.05, .46, 2.75), (.95, .46, 1.35), 24)
    a.add(sweep(front, .065, 10), 'Chrome')
    rear = bezier((-1.0, .5, -1.4), (-1.1, .5, -2.3), (1.1, .5, -2.3), (1.0, .5, -1.4), 24)
    a.add(sweep(rear, .065, 10), 'Chrome')

    # nerf bars along the sides, between the wheels
    def nerf():
        p = bezier((.9, .42, -.5), (1.42, .40, -.5), (1.42, .40, .5), (.9, .42, .5), 18)
        return sweep(p, .045, 10)
    a.add(mirrored(nerf), 'Chrome')

    # front suspension arms and the rear axle
    def arms():
        return merge(sweep([(.7, .42, .85), (1.0, .5, 1.05)], .035, 8),
                     sweep([(.7, .42, 1.25), (1.0, .5, 1.05)], .035, 8))
    a.add(mirrored(arms), 'Chrome')
    a.add(xf(cyl(.06, .06, 2.1, 12), (0, .5, -1.05), (0, 0, math.pi / 2)), 'Dark')

    # headlights: dark housings with glowing lenses, number plate
    def lamp():
        return xf(cyl(.12, .1, .12, 18), (.27, .56, 2.36), (math.pi / 2 - .35, 0, 0))
    a.add(mirrored(lamp), 'BodyDark')
    a.add(mirrored(lambda: ellipsoid((.27, .575, 2.415), (.085, .085, .05), 16, 10)), 'Lamp')
    a.add(rbox((.5, .22, .04), (0, .47, 2.58), .02), 'Plate')

    # hood bulge rising to the steering column, dark instrument face toward the driver
    hood = loft([(1.45, .04, .84, .86, 2.0), (1.2, .26, .78, .95, 2.4), (.8, .4, .78, 1.04, 2.6),
                 (.45, .44, .78, 1.08, 2.6), (.3, .4, .8, 1.06, 2.6), (.24, .06, .9, 1.0, 2.0)], segs=28)
    a.add(hood, 'Body', paint=lambda c, n: 'Dark' if n.z < -.5 and c.y > .85 else None)
    a.add(sweep([(0, .86, .74), (0, 1.19, .31)], .045, 10), 'Chrome')

    # bucket seat: shell with side bolsters
    seat = rbox((.95, .9, .16), (0, 0, 0), .07)
    seat = subsurf(seat, 1)
    a.add(xf(seat, (0, 1.25, -.98), (.25, 0, 0)), 'Dark')
    a.add(rbox((1.05, .14, .75), (0, .9, -.52), .06), 'Dark')
    a.add(mirrored(lambda: xf(rbox((.12, .7, .5), (0, 0, 0), .05), (.48, 1.12, -.8), (.25, 0, 0))), 'Dark')

    # roll hoop behind the seat
    hoop = bezier((-.45, .95, -1.1), (-.5, 1.75, -1.22), (.5, 1.75, -1.22), (.45, .95, -1.1), 24)
    a.add(sweep(hoop, .05, 10), 'Chrome')

    # engine: dark block, finned chrome cylinder, air filter drum
    a.add(rbox((.78, .42, .6), (0, .9, -1.58), .06), 'Dark')
    fins = []
    for i in range(9):
        x = -.4 + i * .1
        fins += [(.25, x - .02), (.34, x), (.34, x + .03), (.25, x + .05)]
    fins = [(0, -.45)] + fins + [(0, .45)]
    fin_cyl = lathe(fins, 18)
    a.add(xf(fin_cyl, (0, 1.12, -1.6), (0, 0, math.pi / 2)), 'Chrome')
    a.add(xf(cyl(.19, .19, .6, 24), (0, 1.43, -1.52), (0, 0, math.pi / 2)), 'Dark')
    a.add(mirrored(lambda: xf(cyl(.2, .2, .04, 24), (.31, 1.43, -1.52), (0, 0, math.pi / 2))), 'Chrome')

    # exhausts: curved pipes flaring at the tips
    def exhaust():
        p = bezier((.28, .98, -1.8), (.5, .95, -2.0), (.45, .8, -2.2), (.45, .78, -2.48), 16)
        return sweep(p, taper(len(p), .07, .1, 2), 14)
    a.add(mirrored(exhaust), 'Chrome')
    a.add(mirrored(lambda: xf(cyl(.075, .075, .04, 14), (.45, .78, -2.5), (math.pi / 2, 0, 0))), 'Dark')

    # rear wing: airfoil blade, accent end plates, dark struts
    foil = []
    for i in range(20):
        t = i / 20 * TAU
        # chord along z (leading edge toward the kart), cambered thickness
        z = .3 * math.cos(t)
        y = (.05 if math.sin(t) > 0 else .025) * math.sin(t) + .02 * (1 - (z / .3) ** 2)
        foil.append((z, y))
    wing = surface([[Vector((x, 1.78 + y, -1.95 + z)) for z, y in foil] for x in (-1.12, 1.12)],
                   cap_start=True, cap_end=True)
    a.add(xf(wing, (0, 0, 0)), 'Body')
    a.add(mirrored(lambda: rbox((.05, .42, .7), (1.14, 1.76, -1.97), .02)), 'Accent')
    a.add(mirrored(lambda: sweep([(.55, 1.0, -1.62), (.55, 1.77, -1.9)], .04, 10)), 'Dark')
    return a


def build_kart_wheel():
    """Wheel at its axle pivot; axle along X, hub face toward +X."""
    a = Asset('kart_wheel', sharp_angle=45)
    prof = [(.30, -.20), (.40, -.215), (.455, -.205), (.475, -.17), (.48, -.1), (.48, .1), (.475, .17),
            (.455, .205), (.40, .215), (.30, .20)]
    tire = lathe(prof + [(.30, -.20)], 32)
    a.add(xf(tire, rot=(0, 0, math.pi / 2)), 'Rubber')
    # tread blocks, chevrons in two staggered rows
    for i in range(20):
        ang = i / 20 * TAU
        for side in (-1, 1):
            blk = rbox((.16, .05, .12), (side * .095, 0, 0), 0, rot=(0, side * .35, 0))
            xf(blk, (0, .495, 0))
            xf(blk, rot=(ang + (side * .07), 0, 0))
            a.add(blk, 'Rubber')
    # rim: dished barrel, five spokes, hub, hubcap in body colour
    rim = lathe([(.0, -.12), (.29, -.15), (.31, -.18), (.305, .18), (.315, .2), (.28, .2), (.27, .14),
                 (.1, .12), (0, .12)], 24)
    a.add(xf(rim, rot=(0, 0, -math.pi / 2)), 'Chrome')
    for i in range(5):
        sp = rbox((.05, .2, .045), (.155, .2, 0), .012, 1)
        xf(sp, rot=(i / 5 * TAU, 0, 0))
        a.add(sp, 'Chrome')
    a.add(xf(cyl(.1, .09, .1, 18), (.17, 0, 0), (0, 0, -math.pi / 2)), 'Dark')
    a.add(ellipsoid((.22, 0, 0), (.05, .075, .075), 16, 10), 'Body')
    return a


def build_kart_steer():
    """Steering wheel in its column frame: rim in the XZ plane, turns about local Y."""
    a = Asset('kart_steer')
    a.add(torus(.3, .045, 32, 10), 'Dark')
    # grips where the hands go
    for sg in (-1, 1):
        g = torus(.3, .055, 10, 10, arc=.9)
        xf(g, rot=(0, sg * math.pi / 2 - .45, 0))
        a.add(g, 'Accent')
    a.add(cyl(.09, .09, .07, 18), 'Accent')
    for ang in (math.pi / 2, -math.pi / 2, math.pi):
        sp = rbox((.05, .025, .24), (0, 0, .15), .01, 1)
        a.add(xf(sp, rot=(0, ang, 0)), 'Chrome')
    return a


# --------------------------------------------------------------------------- driver
def build_driver_body():
    """Driver from the hips up plus legs, in the driver frame (hips pivot)."""
    a = Asset('driver_body')
    torso = loft([
        (.18, .12, -.14, .14, 2.2),
        (.24, .30, -.22, .24, 2.4),
        (.42, .33, -.24, .27, 2.5),
        (.60, .34, -.22, .26, 2.6),
        (.76, .31, -.2, .23, 2.6),
        (.86, .22, -.15, .17, 2.4),
        (.92, .08, -.06, .08, 2.2),
    ], segs=28)
    # built along Z: stand it up so Z becomes Y, and keep the chest (old +Y) facing +Z
    xf(torso, rot=(-math.pi / 2, 0, 0))
    xf(torso, (0, 0, .04), rot=(.1, 0, 0))

    def suit_paint(c, n):
        if abs(c.x) < .08 and n.z > .3 and c.y > .35:
            return 'Accent'
        if .3 < c.y < .38:
            return 'Dark'
        return None
    a.add(torso, 'Suit', paint=suit_paint)
    a.add(ellipsoid((0, .3, .06), (.36, .2, .32), 20, 12), 'Suit')
    a.add(xf(torus(.14, .045, 20, 8), (0, .88, .04)), 'Dark')
    for sg in (-1, 1):
        a.add(ellipsoid((sg * .31, .76, .06), (.15, .13, .15), 14, 10), 'Suit')
    # legs stretched to the pedals, with boots
    def leg():
        p = bezier((.17, .26, .05), (.2, .34, .5), (.21, .22, .85), steps=12)
        return sweep(p, taper(len(p), .14, .11), 12)
    a.add(mirrored(leg), 'Suit')
    a.add(mirrored(lambda: ellipsoid((.21, .24, .95), (.12, .14, .17), 12, 8)), 'Dark')
    # harness straps
    def strap():
        p = bezier((.13, .88, .12), (.2, .8, .33), (.13, .4, .3), steps=10)
        return sweep(p, .03, 6)
    a.add(mirrored(strap), 'Dark')
    return a


def build_driver_head():
    """Helmet with an open face window, eyes looking out, raised visor. Head frame (neck pivot)."""
    a = Asset('driver_head')
    R, cy = .47, .1
    win_w, win_lo, win_hi = .72, -.32, .2   # half width (radians) and lat range of the face opening
    lat_n, lon_n = 16, 36
    bm = bmesh.new()
    verts = {}
    for i in range(lat_n + 1):
        lat = -math.pi / 2 + math.pi * i / lat_n
        for j in range(lon_n):
            lon = j / lon_n * TAU
            verts[i, j] = bm.verts.new((R * math.cos(lat) * math.sin(lon), cy + R * math.sin(lat),
                                        R * math.cos(lat) * math.cos(lon)))
    for i in range(lat_n):
        lat = -math.pi / 2 + math.pi * (i + .5) / lat_n
        for j in range(lon_n):
            lon = (j + .5) / lon_n * TAU
            lon_c = lon if lon < math.pi else lon - TAU
            if abs(lon_c) < win_w and win_lo < lat < win_hi:
                continue
            bm.faces.new((verts[i, j], verts[i, (j + 1) % lon_n], verts[i + 1, (j + 1) % lon_n],
                          verts[i + 1, j]))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-7)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    shell = with_modifiers(bm, [('SOLIDIFY', {'thickness': .045, 'offset': -1})])

    def helmet_paint(c, n):
        if abs(c.x) < .07 and c.y > cy + .1 and n.y > 0:
            return 'Accent'
        return None
    a.add(shell, 'Helmet', paint=helmet_paint)
    # face inside the opening, with eyes and a little nose
    a.add(ellipsoid((0, .03, .02), (.4, .38, .4), 22, 14), 'Skin')
    for sg in (-1, 1):
        a.add(ellipsoid((sg * .13, .09, .395), (.075, .095, .04), 16, 10), 'Eye')
        a.add(ellipsoid((sg * .125, .085, .43), (.036, .05, .02), 12, 8), 'Dark')
    a.add(ellipsoid((0, .0, .425), (.045, .035, .03), 12, 8), 'Skin')
    # raised visor over the forehead
    vis = bmesh.new()
    rows = []
    for i in range(5):
        lat = .22 + .38 * i / 4
        rows.append([Vector(((R + .03) * math.cos(lat) * math.sin(lon), cy + (R + .03) * math.sin(lat),
                             (R + .03) * math.cos(lat) * math.cos(lon)))
                     for lon in [-.85 + 1.7 * k / 16 for k in range(17)]])
    vis = surface(rows, wrap=False)
    vis = with_modifiers(vis, [('SOLIDIFY', {'thickness': .03, 'offset': 0})])
    a.add(vis, 'Glass')
    for sg in (-1, 1):   # visor hinges
        a.add(xf(cyl(.06, .06, .05, 14), (sg * (R + .01), cy + .1, .05), (0, 0, math.pi / 2)), 'Dark')
    return a


def build_driver_arm():
    """Sleeve along Y, one unit long and centred: the game stretches it to reach the wheel."""
    a = Asset('driver_arm')
    p = [(0, y, 0) for y in (-.5, -.3, 0, .3, .5)]
    a.add(sweep(p, [.09, .088, .082, .078, .076], 14), 'Suit')
    a.add(xf(torus(.08, .02, 14, 6), (0, .42, 0)), 'Accent')
    return a


def build_driver_glove():
    a = Asset('driver_glove')
    a.add(ellipsoid((0, 0, .01), (.11, .1, .12), 16, 10), 'Glove')
    a.add(ellipsoid((.06, .05, -.02), (.04, .04, .06), 10, 6), 'Glove')
    a.add(xf(cyl(.09, .1, .08, 14), (0, 0, -.1), (math.pi / 2, 0, 0)), 'Glove')
    return a


# --------------------------------------------------------------------------- helmet toppers (head frame)
def star_outline(points=5, r_out=1.0, r_in=.45):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        t = math.pi / 2 + i * math.pi / points
        pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def build_toppers():
    top = .57  # helmet crown

    # Blaze: a crest of flames licking back over the helmet
    a = Asset('topper_blaze')
    for i, (z, h, lean) in enumerate([(.28, .26, .5), (.12, .38, .45), (-.06, .44, .4), (-.24, .36, .45),
                                      (-.38, .24, .5)]):
        base = Vector((0, .1 + math.sqrt(max(.47 ** 2 - z * z, 0)) - .04, z))
        tip = base + Vector((0, h, -h * lean))
        mid = base.lerp(tip, .5) + Vector((0, 0, .06))
        p = bezier(base, mid, tip, steps=10)
        a.add(sweep(p, taper(len(p), .09, .0, 1.3), 10), 'Accent')
    a.add(xf(torus(.34, .065, 28, 8, arc=math.pi), (0, .16, 0), (0, 0, math.pi / 2)), 'Accent')

    # Pip: round ears
    a = Asset('topper_pip')
    for sg in (-1, 1):
        a.add(xf(ellipsoid((0, 0, 0), (.17, .17, .07), 20, 12), (sg * .38, .44, -.02), (0, 0, -sg * .5)),
              'Helmet')
        a.add(xf(ellipsoid((0, 0, .04), (.1, .1, .04), 16, 10), (sg * .38, .44, -.02), (0, 0, -sg * .5)),
              'Accent')

    # Luna: cat ears
    a = Asset('topper_luna')
    for sg in (-1, 1):
        ear = cyl(.16, .0, .36, 4)
        xf(ear, rot=(0, math.pi / 4, 0), scale=(1, 1, .5))
        a.add(xf(ear, (sg * .27, .6, 0), (0, 0, -sg * .35)), 'Helmet')
        inner = cyl(.1, .0, .24, 4)
        xf(inner, rot=(0, math.pi / 4, 0), scale=(1, 1, .3))
        a.add(xf(inner, (sg * .27, .59, .05), (0, 0, -sg * .35)), 'Accent')

    # Bolt: a fin down the middle and glowing lightning bolts on the sides
    a = Asset('topper_bolt')
    fin = extrude_outline([(-.36, 0), (.32, 0), (.2, .16), (-.32, .34)], .06, .015)
    a.add(xf(fin, (0, .5, 0), (0, math.pi / 2, 0)), 'Accent')
    bolt = [(-.02, .16), (.1, .16), (.03, .03), (.1, .03), (-.08, -.17), (-.02, -.03), (-.09, -.03)]
    for sg in (-1, 1):
        b = extrude_outline(bolt, .04, .006)
        a.add(xf(b, (sg * .47, .12, 0), (0, sg * math.pi / 2, 0)), 'Glow')

    # Coral: swinging ponytail with a hair tie
    a = Asset('topper_coral')
    p = bezier((0, .3, -.38), (0, .45, -.7), (0, -.05, -.72), (0, -.25, -.62), 18)
    a.add(sweep(p, taper(len(p), .13, .04, .8), 14), 'Accent')
    a.add(xf(torus(.12, .04, 18, 8), (0, .31, -.43), (1.1, 0, 0)), 'Skin')

    # Mossy: a sprout with two leaves and a berry
    a = Asset('topper_mossy')
    stem = bezier((0, top - .03, 0), (0, top + .12, .02), (.03, top + .2, -.02), steps=8)
    a.add(sweep(stem, .025, 8), 'Accent')

    def leaf():
        pts = []
        for i in range(13):
            t = i / 12 * math.pi
            pts.append((.2 * (1 - math.cos(t)), .08 * math.sin(t)))
        for i in range(1, 12):
            t = (12 - i) / 12 * math.pi
            pts.append((.2 * (1 - math.cos(t)), -.08 * math.sin(t)))
        return extrude_outline(pts, .02, .006)
    a.add(xf(leaf(), (.03, top + .19, -.02), (0, 0, .5)), 'Accent')
    a.add(xf(leaf(), (.03, top + .19, -.02), (0, math.pi, .35)), 'Accent')
    a.add(ellipsoid((.14, top - .02, .2), (.08, .08, .08), 12, 8), 'Glow')

    # Zed: antenna with a glowing tip and goggles on the brow
    a = Asset('topper_zed')
    ant = bezier((.12, top - .02, -.1), (.16, top + .2, -.14), (.1, top + .45, -.22), steps=10)
    a.add(sweep(ant, .022, 8), 'Chrome')
    a.add(ellipsoid((.1, top + .48, -.23), (.08, .08, .08), 14, 10), 'Glow')
    for sg in (-1, 1):
        g = xf(cyl(.1, .1, .08, 20), (sg * .13, .44, .3), (math.pi / 2 - .75, 0, 0))
        a.add(g, 'Chrome')
        a.add(xf(cyl(.075, .075, .085, 20), (sg * .13, .44, .3), (math.pi / 2 - .75, 0, 0)), 'Glow')
    band = bezier((-.46, .3, 0), (-.3, .5, .42), (.3, .5, .42), (.46, .3, 0), 18)
    a.add(sweep(band, .025, 8), 'Dark')

    # Nova: a star on top and a halo ring
    a = Asset('topper_nova')
    star = extrude_outline(star_outline(5, .2, .09), .08, .02)
    a.add(xf(star, (0, top + .2, 0)), 'Glow')
    a.add(xf(torus(.5, .025, 48, 8), (0, .12, 0)), 'Glow')


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
    build_kart_body()
    build_kart_wheel()
    build_kart_steer()
    build_driver_body()
    build_driver_head()
    build_driver_arm()
    build_driver_glove()
    build_toppers()
    build_items()
    build_scenery()

    # lay the objects out in a grid so the .blend is easy to browse; the game ignores placement
    col = bpy.data.collections.new('Kartlands')
    bpy.context.scene.collection.children.link(col)
    for i, asset in enumerate(ASSETS):
        ob = asset.build()
        col.objects.link(ob)
        ob.location = ((i % 8) * 7.0, (i // 8) * 7.0, 0)
    tris = sum(sum(len(p.vertices) - 2 for p in ob.data.polygons) for ob in col.objects)
    print(f'built {len(col.objects)} meshes, {tris} triangles')

    if opts['blend']:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(opts['blend']))
    if opts['export']:
        # export at the origin: every part carries its own pivot
        for ob in col.objects:
            ob.location = (0, 0, 0)
        out = os.path.abspath(opts['out'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_yup=True, export_apply=True,
                                  export_texcoords=False, export_normals=True, export_materials='EXPORT',
                                  export_animations=False, export_extras=False)
        print(f'wrote {out} ({os.path.getsize(out) // 1024} KB)')


if __name__ == '__main__':
    main()
