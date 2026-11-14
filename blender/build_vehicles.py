"""Build the eight derby vehicles and their drivers in Blender and export them to assets/vehicles.glb.

Run it headless with Blender:
    blender --background --factory-startup --python blender/build_vehicles.py
or with the bpy module from PyPI (pip install bpy):
    python blender/build_vehicles.py
Options (after `--` when running through blender): --out PATH, --blend PATH, --no-export.

Everything is written in the game's frame (Y up, the vehicle faces +Z, metres) and turned to
Blender's Z-up frame at the end, like build_assets.py, whose mesh helpers this script borrows.

Each vehicle `v` is a handful of objects, each modelled around its own pivot:
    v_body                  the hull, with the driver's shoulders
    v_head                  the driver's head, which turns with the steering
    v_wheel (or _f / _r)    one wheel, placed at every pivot_v_wheel_N
    v_gun, v_spin           the part that swivels, recoils or spins
Colours are painted per face into a vertex colour layer, so a vehicle needs only a few
materials, one per kind of surface: VPaint, VMatte, VMetal, VGlow and VGlass.
"""
import math
import os
import sys

import bpy  # must come first: the PyPI bpy module provides bmesh and mathutils
import bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
sys.path.insert(0, HERE)
from build_assets import (TAU, bezier, cyl, ellipsoid, extrude_outline, hex_rgba, lathe, merge,  # noqa: E402
                          mirror_x, rbox, sweep, torus, xf)

PI = math.pi
# surface kinds: roughness, metallic, emission strength, alpha
SURFACES = {'Paint': (.32, .1, 0, 1), 'Matte': (.85, 0, 0, 1), 'Metal': (.3, 1, 0, 1), 'Glow': (.4, 0, 2, 1),
            'Glass': (.06, 0, 0, .35)}
ASSETS, PIVOTS = [], {}


def surface_material(kind):
    name = 'V' + kind
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    rough, metal, glow, alpha = SURFACES[kind]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    col = nodes.new('ShaderNodeVertexColor')
    col.layer_name = 'Col'
    links.new(col.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    bsdf.inputs['Alpha'].default_value = alpha
    if glow:
        links.new(col.outputs['Color'], bsdf.inputs['Emission Color'])
        bsdf.inputs['Emission Strength'].default_value = glow
    if alpha < 1:
        mat.surface_render_method = 'BLENDED'
    return mat


class Asset:
    """One exported mesh object: parts appended with a colour and a surface kind."""

    def __init__(self, name, sharp=38):
        self.name, self.sharp, self.kinds = name, sharp, []
        self.bm = bmesh.new()
        self.bm.loops.layers.float_color.new('Col')
        self._me = bpy.data.meshes.new('_part')
        ASSETS.append(self)

    def add(self, part, color, kind='Paint', smooth=True):
        if kind not in self.kinds:
            self.kinds.append(kind)
        idx, n0, rgba = self.kinds.index(kind), len(self.bm.faces), hex_rgba(color)
        part.to_mesh(self._me)
        self.bm.from_mesh(self._me)
        part.free()
        self.bm.faces.ensure_lookup_table()
        layer = self.bm.loops.layers.float_color['Col']
        for f in self.bm.faces[n0:]:
            f.smooth, f.material_index = smooth, idx
            for loop in f.loops:
                loop[layer] = rgba
        return self

    def both(self, fn, color, kind='Paint', smooth=True):
        """A part built on the +X side, added on both sides."""
        self.add(fn(), color, kind, smooth)
        return self.add(mirror_x(fn()), color, kind, smooth)

    def build(self):
        me = bpy.data.meshes.new(self.name)
        # game frame (Y up, +Z forward) -> Blender frame (Z up, -Y forward)
        bmesh.ops.transform(self.bm, matrix=Matrix.Rotation(PI / 2, 4, 'X'), verts=self.bm.verts)
        self.bm.to_mesh(me)
        self.bm.free()
        bpy.data.meshes.remove(self._me)
        me.set_sharp_from_angle(angle=math.radians(self.sharp))
        for kind in self.kinds:
            me.materials.append(surface_material(kind))
        me.color_attributes.active_color = me.color_attributes['Col']
        me.color_attributes.render_color_index = 0
        return bpy.data.objects.new(self.name, me)


def pivot(name, pos):
    PIVOTS['pivot_' + name] = Vector(pos)


# --------------------------------------------------------------------------- shorthands
def box(sx, sy, sz, x=0.0, y=0.0, z=0.0, b=.05, rot=(0, 0, 0)):
    small = min(sx, sy, sz)
    return rbox((sx, sy, sz), (x, y, z), 0 if b < .015 else min(b, small * .45), 2 if small > .45 else 1, rot)


def ball(r, x=0.0, y=0.0, z=0.0, s=(1, 1, 1), segs=None, rings=None, rot=None):
    segs = segs or (20 if r > .3 else 14 if r > .12 else 10)
    bm = ellipsoid((0, 0, 0), (r * s[0], r * s[1], r * s[2]), segs, rings or max(6, segs * 2 // 3))
    return xf(bm, (x, y, z), rot or (0, 0, 0))


def tube(r, h, x=0.0, y=0.0, z=0.0, rot=(0, 0, 0), r2=None, segs=None):
    """A cylinder along Y before `rot`; r2 tapers the top."""
    return xf(cyl(r, r if r2 is None else r2, h, segs or (16 if r > .1 else 10)), (x, y, z), rot)


def tubez(r, length, x=0.0, y=0.0, z=0.0, r2=None, segs=None):
    """A cylinder along Z, centred on (x, y, z); r2 is the radius at the front."""
    return tube(r, length, x, y, z, (PI / 2, 0, 0), r2, segs)


def tubex(r, length, x=0.0, y=0.0, z=0.0, segs=None):
    return tube(r, length, x, y, z, (0, 0, PI / 2), None, segs)


def cone(r, h, x=0.0, y=0.0, z=0.0, rot=(0, 0, 0), segs=14):
    """A cone with its base at the origin pointing up Y before `rot`."""
    return xf(lathe([(0, 0), (r, 0), (0, h)], segs), (x, y, z), rot)


def pipe(points, r, segs=10):
    return sweep(points, r, segs)


def ring(R, r, x=0.0, y=0.0, z=0.0, rot=(0, 0, 0), segs=28):
    return xf(torus(R, r, segs, 8), (x, y, z), rot)


def plate(outline, depth, x=0.0, y=0.0, z=0.0, rot=(0, 0, 0)):
    """A flat shape (outline in XY) of the given thickness."""
    return xf(extrude_outline(outline, depth), (x, y, z), rot)


def on_ball(c, r, yaw, pitch, k=1.0):
    """A point on a sphere centred at c: yaw from straight ahead (+Z) toward +X, pitch up."""
    return (c[0] + r * k * math.sin(yaw) * math.cos(pitch), c[1] + r * k * math.sin(pitch),
            c[2] + r * k * math.cos(yaw) * math.cos(pitch))


HEART = [(0, -.5), (.42, -.08), (.5, .2), (.38, .44), (.16, .5), (0, .32), (-.16, .5), (-.38, .44), (-.5, .2), (-.42, -.08)]
STAR = [(math.sin(i * PI / 5) * (.5 if i % 2 == 0 else .21), math.cos(i * PI / 5) * (.5 if i % 2 == 0 else .21)) for i in range(10)]
FLAME = [(-.5, -.28), (.5, -.28), (.42, -.05), (.2, .02), (.34, .16), (.02, .1), (.12, .3), (-.2, .12), (-.14, .28), (-.42, .06)]
BLACK, WHITE, CHROME, STEEL, GUN, TYRE, RED, AMBER = 0x15161a, 0xf4f1ea, 0xd5dae2, 0x8a9099, 0x2c2f35, 0x17181b, 0xe6332a, 0xffc21a


def eyes(a, c, r, yaw=.4, pitch=.1, size=.2, pupil=.5, white=WHITE, iris=BLACK, squint=1.0):
    for sg in (-1, 1):
        a.add(ball(size * r, *on_ball(c, r, sg * yaw, pitch, .9), s=(1, squint, 1)), white, 'Paint')
        a.add(ball(size * r * pupil, *on_ball(c, r, sg * yaw * .97, pitch, .9 + size * .66)), iris, 'Paint')


def wheel(name, r, w, tyre=TYRE, rim=CHROME, hub=STEEL, knobs=0, rim_kind='Metal'):
    """A wheel on its axle (along X), the same from both sides."""
    a = Asset(name)
    turn = lambda bm: xf(bm, rot=(0, 0, PI / 2))
    a.add(turn(lathe([(r * .6, -w / 2), (r * .93, -w / 2), (r, -w * .3), (r, w * .3), (r * .93, w / 2), (r * .6, w / 2)], 22)), tyre, 'Matte')
    a.add(turn(lathe([(0, -w * .4), (r * .28, -w * .42), (r * .62, -w * .36), (r * .62, w * .36), (r * .28, w * .42), (0, w * .4)], 20)), rim, rim_kind)
    for sg in (-1, 1):
        a.add(ball(r * .17, sg * w * .44, 0, 0, s=(.5, 1, 1), segs=12, rings=8), hub, 'Metal')
        for i in range(5):
            t = i / 5 * TAU
            a.add(ball(r * .055, sg * w * .43, math.cos(t) * r * .4, math.sin(t) * r * .4, segs=6, rings=4), hub, 'Metal')
    for i in range(knobs):
        t = i / knobs * TAU
        a.add(box(w * .92, r * .1, r * .2, 0, math.cos(t) * r * 1.02, math.sin(t) * r * 1.02, 0, (t, 0, 0)), tyre, 'Matte')
    return a


def wheels(v, spots, front=None):
    for i, p in enumerate(spots):
        pivot(f'{v}_wheel_{i}', p)


def lamp(a, x, y, z, r=.13, color=0xfff2c0):
    a.add(tubez(r * 1.15, .1, x, y, z - .03), CHROME, 'Metal')
    a.add(ball(r, x, y, z, s=(1, 1, .5), segs=14, rings=8), color, 'Glow')


def steering(a, x, y, z, r=.24, tilt=-.9):
    a.add(ring(r, .035, x, y, z, (tilt + PI / 2, 0, 0), 20), BLACK, 'Matte')
    a.add(tube(.03, .5, x, y - .18, z + .22, (tilt + PI, 0, 0)), GUN, 'Metal')


def arms(a, shoulder, hand, color, r=.1, bend=(.0, -.12, .1)):
    """Two arms from the shoulders to the hands (given for the +X side)."""
    for sg in (-1, 1):
        s, h = Vector((sg * shoulder[0], shoulder[1], shoulder[2])), Vector((sg * hand[0], hand[1], hand[2]))
        mid = (s + h) / 2 + Vector((sg * bend[0], bend[1], bend[2]))
        a.add(pipe(bezier(s, mid, h, steps=8), r, 10), color, 'Matte')
        a.add(ball(r * 1.35, *h, segs=12, rings=8), color, 'Matte')


# --------------------------------------------------------------------------- 1. armoured 4x4, roof gun
def build_humvee():
    v, olive, dark, tan = 'humvee', 0x66763f, 0x434e2c, 0xb99a6b
    a = Asset(v + '_body')
    a.add(box(2.12, .8, 3.95, 0, .86, 0, .12), olive)                       # hull
    a.add(box(1.86, .1, 1.3, 0, 1.3, 1.22, .04), dark)                       # bonnet panel
    a.add(box(2.0, .66, 1.95, 0, 1.56, -.38, .1), olive)                     # cab
    a.add(box(1.7, .44, .06, 0, 1.58, .62, .02, (-.14, 0, 0)), 0x1b2a33, 'Glass')
    a.both(lambda: box(.05, .36, 1.5, 1.0, 1.6, -.4, .02), 0x1b2a33, 'Glass')
    a.add(ring(.56, .08, 0, 1.92, -.38), dark, 'Metal')                      # turret ring
    a.both(lambda: box(.34, .12, 1.1, 1.06, 1.3, 1.25, .05), dark)           # arches
    a.both(lambda: box(.34, .12, 1.1, 1.06, 1.3, -1.25, .05), dark)
    a.add(box(2.2, .22, .2, 0, .62, 2.04, .06), GUN, 'Metal')                # bumpers
    a.add(box(2.2, .22, .2, 0, .62, -2.04, .06), GUN, 'Metal')
    for x in (-.7, 0, .7):                                                    # brush guard
        a.add(tube(.05, .78, x, 1.0, 2.1), GUN, 'Metal')
    a.add(tubex(.05, 1.6, 0, 1.38, 2.1), GUN, 'Metal')
    a.add(box(1.5, .36, .08, 0, .98, 1.99, .02), BLACK, 'Matte')             # grille
    for x in (-.78, .78):
        lamp(a, x, 1.0, 2.0, .14)
        a.add(box(.2, .12, .04, x, 1.0, -1.99, .01), RED, 'Glow')
    a.add(pipe([(.98, 1.2, .9), (.98, 2.0, .7), (.98, 2.12, .5)], .07), dark, 'Matte')      # snorkel
    a.add(xf(lathe([(.2, -.14), (.42, -.14), (.46, 0), (.42, .14), (.2, .14)], 20), (0, 1.3, -2.12), (PI / 2, 0, 0)), TYRE, 'Matte')   # spare
    a.add(tubez(.2, .2, 0, 1.3, -2.14), olive)
    a.both(lambda: box(.16, .46, .34, 1.14, 1.0, -.2, .04), dark)            # jerry cans
    a.both(lambda: box(.5, .5, .02, 1.065, .95, .55, .0, (0, PI / 2, 0)), tan)   # door panel
    a.add(plate(STAR, .03, 0, 1.36, 1.2, (PI / 2, 0, 0)), WHITE, 'Matte')    # bonnet star
    a.add(ball(.44, 0, 2.06, -.38, s=(1, .66, .7)), 0x4b5a32, 'Matte')       # shoulders in the hatch
    wheel(v + '_wheel', .62, .5, rim=dark, hub=GUN, knobs=14, rim_kind='Paint')
    wheels(v, [(1.04, .62, 1.25), (-1.04, .62, 1.25), (1.04, .62, -1.25), (-1.04, .62, -1.25)])
    # the fifty: swivels on the ring, in front of the driver
    g = Asset(v + '_gun')
    g.add(tube(.07, .3, 0, .08, .62), GUN, 'Metal')
    g.add(box(.2, .2, .8, 0, .28, .86, .04), GUN, 'Metal')
    g.add(tubez(.045, 1.35, 0, .3, 1.9), 0x3a3d44, 'Metal')
    g.add(tubez(.075, .5, 0, .3, 1.46), GUN, 'Metal')
    g.add(tubez(.07, .16, 0, .3, 2.6), GUN, 'Metal')
    g.add(box(.3, .24, .34, -.3, .26, .74, .03), 0x4b5a32)
    g.add(box(.86, .34, .05, 0, .3, 1.1, .02, (-.25, 0, 0)), olive)
    g.both(lambda: tube(.03, .26, .1, .28, .4, (PI / 2 - .3, 0, 0)), BLACK, 'Matte')
    pivot(v + '_gun', (0, 1.94, -.38))
    # driver: bandana, shades, ponytail
    h, c, r, skin, hair = Asset(v + '_head'), (0, .56, 0), .5, 0xc98d5e, 0x3a2417
    h.add(ball(r, *c, s=(1, 1.04, 1)), skin, 'Matte')
    h.add(ball(r * .78, 0, .3, .06, s=(1.05, .7, 1)), skin, 'Matte')          # jaw
    h.add(tube(.17, .26, 0, .05, 0), skin, 'Matte')
    h.add(ball(r * 1.05, 0, .7, -.02, s=(1, .82, 1.02)), hair, 'Matte')
    h.add(ring(r * 1.03, .09, 0, .74, .0, (.1, 0, 0)), RED, 'Matte')          # bandana
    for sg in (-1, 1):
        h.add(box(.1, .34, .04, sg * .09, .5, -.56, .02, (.35, 0, sg * .3)), RED, 'Matte')
        h.add(box(.3, .19, .1, sg * .19, .6, .44, .06), BLACK)                # shades
        h.add(box(.2, .05, .06, sg * .2, .76, .46, .02, (0, 0, -sg * .25)), hair, 'Matte')
        h.add(box(.16, .045, .03, sg * .3, .42, .43, .01, (0, sg * .35, 0)), 0x20291a, 'Matte')   # war paint
    h.add(box(.12, .04, .1, 0, .62, .46, .02), BLACK)
    h.add(ball(.07, 0, .47, .5), skin, 'Matte')
    h.add(box(.26, .07, .05, 0, .27, .44, .02), WHITE)                        # gritted teeth
    for i, (y, z, s) in enumerate([(.86, -.52, .2), (.74, -.72, .17), (.56, -.84, .14), (.38, -.88, .11)]):
        h.add(ball(s, 0, y, z), hair, 'Matte')
    pivot(v + '_head', (0, 2.16, -.38))


# --------------------------------------------------------------------------- 2. pink jeep, rocket pods
def build_jeep():
    v, pink, hot, cream = 'jeep', 0xff5fae, 0xd81b77, 0xfff6ee
    a = Asset(v + '_body')
    a.add(box(1.86, .62, 3.3, 0, .84, 0, .1), pink)
    a.add(box(1.5, .22, 1.1, 0, 1.2, 1.02, .07), pink)
    a.add(box(1.34, .46, .08, 0, .98, 1.66, .03), cream)
    for i in range(5):
        a.add(box(.1, .3, .04, -.36 + i * .18, .98, 1.7, .01), BLACK, 'Matte')
    a.both(lambda: box(.44, .09, 1.0, .96, 1.12, 1.05, .04), cream)
    a.both(lambda: box(.44, .09, .9, .96, 1.12, -1.05, .04), cream)
    for x in (-.56, .56):
        lamp(a, x, 1.0, 1.7, .15)
        a.add(box(.18, .12, .04, x, 1.0, -1.66, .01), RED, 'Glow')
    a.add(box(1.96, .16, .16, 0, .6, 1.72, .05), CHROME, 'Metal')
    a.add(box(1.96, .16, .16, 0, .6, -1.72, .05), CHROME, 'Metal')
    for sg in (-1, 1):                                                        # windscreen frame
        a.add(tube(.04, .62, sg * .8, 1.62, .4, (-.2, 0, 0)), cream)
    a.add(tubex(.04, 1.64, 0, 1.92, .34), cream)
    a.add(box(1.56, .56, .03, 0, 1.62, .4, .0, (-.2, 0, 0)), 0xbfe6ff, 'Glass')
    a.add(box(1.4, .5, .16, 0, 1.36, -.62, .07, (.12, 0, 0)), cream, 'Matte')   # seat back
    a.add(box(1.4, .14, .7, 0, 1.12, -.3, .06), cream, 'Matte')
    a.add(pipe([(.86, 1.15, -.75), (.86, 1.98, -.75), (-.86, 1.98, -.75), (-.86, 1.15, -.75)], .06), cream)   # roll bar
    a.both(lambda: pipe([(.86, 1.95, -.75), (.86, 1.2, -1.55)], .05), cream)
    a.both(lambda: plate(HEART, .03, .945, .9, .1, (0, PI / 2, 0)), cream)
    a.both(lambda: xf(plate(HEART, .03), (.945, .9, -.75), (0, PI / 2, 0), (.6, .6, 1)), hot)
    a.add(xf(lathe([(.18, -.13), (.44, -.13), (.48, 0), (.44, .13), (.18, .13)], 20), (0, 1.12, -1.8), (PI / 2, 0, 0)), TYRE, 'Matte')
    a.add(tubez(.4, .1, 0, 1.12, -1.9), pink)
    a.add(plate(HEART, .03, 0, 1.12, -1.96, (0, PI, 0)), cream)
    a.add(tube(.012, 1.3, -.8, 1.9, -1.5), CHROME, 'Metal')
    a.add(ball(.08, -.8, 2.56, -1.5), hot)
    # rocket pods on the roll bar
    for sg in (-1, 1):
        a.add(box(.46, .46, 1.0, sg * 1.12, 1.92, -.62, .06, (-.1, 0, 0)), hot)
        a.add(box(.5, .12, .5, sg * 1.12, 1.92, -.62, .03, (-.1, 0, 0)), cream)
        for dx in (-.11, .11):
            for dy in (-.11, .11):
                a.add(tubez(.085, .08, sg * 1.12 + dx, 1.97 + dy, -.1), BLACK, 'Matte')
                a.add(cone(.07, .2, sg * 1.12 + dx, 1.975 + dy, -.1, (PI / 2 - .1, 0, 0), 10), cream)
    steering(a, 0, 1.5, .22, .22)
    a.add(ball(.36, 0, 1.52, -.34, s=(1, .9, .7)), hot, 'Matte')              # top
    arms(a, (.3, 1.6, -.3), (.2, 1.5, .2), 0xf6cfa8, .07)
    wheel(v + '_wheel', .56, .42, rim=cream, hub=pink, knobs=12, rim_kind='Paint')
    wheels(v, [(.97, .56, 1.05), (-.97, .56, 1.05), (.97, .56, -1.05), (-.97, .56, -1.05)])
    # driver: pigtails, huge shades, bubblegum
    h, c, r, skin, hair = Asset(v + '_head'), (0, .52, 0), .47, 0xf6cfa8, 0xffe066
    h.add(ball(r, *c), skin, 'Matte')
    h.add(tube(.13, .22, 0, .05, 0), skin, 'Matte')
    h.add(ball(r * 1.07, 0, .6, -.07, s=(1.02, .9, 1)), hair, 'Matte')
    h.add(box(.72, .16, .2, 0, .8, .34, .08, (-.3, 0, 0)), hair, 'Matte')     # fringe
    for sg in (-1, 1):
        for i, (dx, dy, s) in enumerate([(.56, .66, .22), (.76, .52, .2), (.86, .32, .17), (.9, .13, .13)]):
            h.add(ball(s, sg * dx, dy, -.08), hair, 'Matte')
        h.add(cone(.12, .2, sg * .5, .74, -.08, (0, 0, -sg * 1.2), 8), hot)
        h.add(cone(.12, .2, sg * .5, .74, -.08, (0, 0, -sg * 1.2 + PI), 8), hot)
        h.add(xf(plate(HEART, .08), (sg * .2, .58, .43), (0, sg * .2, 0), (.38, .34, 1)), hot)   # heart shades
        h.add(xf(plate(HEART, .1), (sg * .2, .58, .43), (0, sg * .2, 0), (.28, .25, 1)), BLACK)
        h.add(ball(.05, sg * .45, .42, .04), 0xffd23f, 'Metal')               # earrings
    h.add(box(.1, .03, .05, 0, .6, .46, .01), hot)
    h.add(ball(.05, 0, .47, .46), skin, 'Matte')
    h.add(ball(.2, 0, .33, .6), 0xff8fcf)                                     # bubblegum
    for i in range(5):                                                        # tiara
        h.add(cone(.04, .1 + .06 * (2 - abs(i - 2)), (i - 2) * .09, 1.02, .08, segs=6), 0xffd23f, 'Metal')
    pivot(v + '_head', (0, 1.78, -.34))


# --------------------------------------------------------------------------- 3. janky ice cream truck
def build_truck():
    v, cream, pink, mint, rust = 'truck', 0xfff1d0, 0xff8fb8, 0x9be8d0, 0x8a4a2a
    a = Asset(v + '_body')
    lean = lambda bm: xf(bm, (0, .45, 0), (0, 0, .045))                       # the whole box sits crooked on its axles
    add = lambda bm, col, kind='Paint': a.add(lean(xf(bm, (0, -.45, 0))), col, kind)
    add(box(2.0, 1.75, 2.6, 0, 1.52, -.62, .12), cream)                       # box
    add(box(2.04, .5, 2.64, 0, .8, -.62, .08), pink)
    add(box(1.92, 1.3, 1.25, 0, 1.3, 1.28, .14), pink)                        # cab
    add(box(1.94, .34, 1.27, 0, .82, 1.28, .08), cream)
    add(box(1.66, .56, .06, 0, 1.52, 1.9, .02, (-.08, 0, 0)), 0x9fd6e8, 'Glass')
    for sg in (-1, 1):
        add(box(.05, .46, .7, sg * .96, 1.5, 1.3, .02), 0x9fd6e8, 'Glass')
    add(box(2.0, .1, 2.7, 0, 2.42, -.62, .04), pink)                          # roof trim
    add(box(.06, .66, 1.2, 1.0, 1.72, -.6, .02), 0x2a2030, 'Matte')           # serving hatch
    for i in range(6):                                                        # awning
        add(box(.52, .05, .22, 1.24, 2.1, -1.15 + i * .22, .01, (0, 0, -.35)), pink if i % 2 else WHITE, 'Matte')
    add(box(.3, .04, 1.3, 1.12, 1.36, -.6, .01), CHROME, 'Metal')             # counter
    for i, col in enumerate([0xff9a3c, mint, 0xd77bff]):                     # lolly stickers
        add(box(.03, .46, .2, -1.01, 1.72, -1.2 + i * .5, .01), col)
        add(box(.03, .2, .05, -1.01, 1.4, -1.2 + i * .5, .0), 0xd9a05b, 'Matte')
    add(box(.03, .9, .8, -1.0, 1.45, .0, .0), mint)                           # the door from another truck
    for (x, y, z, sx, sz) in [(1.0, .72, -1.5, .5, .4), (-1.0, .66, .6, .7, .3), (.4, .62, 1.9, .5, .03), (-1.0, 2.2, -1.6, .3, .5)]:
        add(box(.05 if abs(x) > .9 else sx, .22, sz, x, y, z, .0), rust, 'Matte')   # rust
    add(box(1.4, .3, .06, 0, .95, 1.92, .02), GUN, 'Metal')                   # grille
    for x in (-.74, .74):
        lamp(a, x, 1.0, 1.93, .15, 0xfff2c0 if x < 0 else 0x6b5a30)           # one headlamp is dead
        add(box(.16, .2, .04, x, .9, -1.93, .01), RED, 'Glow')
    a.add(box(2.1, .16, .14, .06, .58, 1.98, .04, (0, 0, -.14)), CHROME, 'Metal')    # bumper hanging off
    a.add(box(2.06, .16, .14, 0, .6, -1.96, .04), CHROME, 'Metal')
    add(pipe([(-.7, 2.45, .9), (-.72, 2.9, .92), (-.6, 3.25, .95), (-.72, 3.5, .9)], .014), CHROME, 'Metal')   # bent aerial
    for sg in (-1, 1):                                                        # loudspeakers
        add(xf(lathe([(.05, 0), (.24, .34), (.26, .34), (.07, 0)], 14), (sg * .66, 2.62, -1.7), (-PI / 2 - .25, 0, 0)), 0xcfd3d8, 'Metal')
    add(ring(.5, .07, 0, 2.48, 1.2), GUN, 'Metal')                            # roof hatch
    add(ball(.4, 0, 2.5, 1.2, s=(1, .6, .7)), 0x7a3fb0, 'Matte')              # shoulders
    add(ring(.3, .09, 0, 2.66, 1.2), WHITE, 'Matte')                          # ruff
    wheel(v + '_wheel', .54, .42, rim=cream, hub=pink, rim_kind='Paint')
    wheels(v, [(1.0, .54, 1.3), (-1.0, .54, 1.3), (1.0, .54, -1.25), (-1.0, .54, -1.25)])
    # the cone on the roof: a scoop launcher
    g, waffle = Asset(v + '_gun'), 0xd9a05b
    g.add(xf(lathe([(.06, -1.1), (.52, .25), (.56, .25), (.1, -1.1)], 18), (0, .55, .1), (.95, 0, 0)), waffle, 'Matte')
    for i in range(5):
        g.add(xf(ring(.14 + i * .085, .02, 0, -.86 + i * .24, 0, segs=18), (0, .55, .1), (.95, 0, 0)), 0xb9803f, 'Matte')
    g.add(ball(.56, 0, .98, .68), pink)
    g.add(ball(.47, 0, 1.52, .98), mint)
    g.add(ball(.14, 0, 1.98, 1.2), RED)
    g.add(pipe([(0, 2.08, 1.24), (.05, 2.24, 1.3), (.16, 2.3, 1.3)], .016, 6), 0x3f7a2c, 'Matte')
    g.add(box(.5, .16, .5, 0, .06, -.2, .04), GUN, 'Metal')
    pivot(v + '_gun', (0, 2.46, -.9))
    # driver: a clown
    h, c, r, face = Asset(v + '_head'), (0, .54, 0), .49, 0xf7f4ee
    h.add(ball(r, *c, s=(1, 1.05, 1)), face, 'Matte')
    h.add(ball(.15, 0, .52, .5), RED)                                         # nose
    eyes(h, c, r, .42, .2, .19, .45)
    for sg in (-1, 1):
        h.add(xf(ball(.1, 0, 0, 0, s=(.7, 2.0, .4)), on_ball(c, r, sg * .42, .2, .93)), 0x2f7fe0, 'Matte')   # eye paint
        h.add(pipe(bezier(on_ball(c, r, sg * .2, .58, 1.0), on_ball(c, r, sg * .42, .78, 1.02), on_ball(c, r, sg * .66, .58, 1.0), steps=8), .028, 6), BLACK, 'Matte')
        for (dx, dy, dz, s, col) in [(.5, .72, -.02, .3, 0xff7a1a if sg > 0 else 0x3ddc5a), (.66, .44, -.06, .27, 0xffd23f if sg > 0 else 0x2f7fe0),
                                     (.36, .98, -.1, .24, 0xe6332a if sg > 0 else 0xd77bff)]:
            h.add(ball(s, sg * dx, dy, dz, segs=14, rings=10), col, 'Matte')  # hair in clashing puffs
    h.add(pipe(bezier(on_ball(c, r, -.62, -.18, 1.0), on_ball(c, r, 0, -.62, 1.06), on_ball(c, r, .62, -.18, 1.0), steps=12), .06, 8), RED)   # grin
    h.add(pipe(bezier(on_ball(c, r, -.5, -.2, 1.0), on_ball(c, r, 0, -.52, 1.05), on_ball(c, r, .5, -.2, 1.0), steps=10), .035, 6), WHITE)
    h.add(tube(.17, .26, .12, 1.14, 0, (0, 0, -.3)), 0x7a3fb0)                # little hat
    h.add(tube(.27, .03, .08, 1.02, 0, (0, 0, -.3)), 0x7a3fb0)
    h.add(box(.2, .1, .1, 0, .06, .34, .04), 0x2f7fe0)                        # bow tie
    for sg in (-1, 1):
        h.add(cone(.16, .26, sg * .32, .06, .34, (0, 0, sg * PI / 2), 8), 0xffd23f)
    pivot(v + '_head', (0, 2.62, 1.2))


# --------------------------------------------------------------------------- 4. hot rod
def build_rod():
    v, black, flame, yellow = 'rod', 0x17181c, 0xff6a1a, 0xffd23f
    a = Asset(v + '_body')
    a.both(lambda: box(.12, .16, 3.7, .5, .5, .15, .04), GUN, 'Metal')         # rails
    a.add(box(1.3, .7, 1.75, 0, .98, -.7, .2), black)                         # tub
    a.add(ball(.66, 0, .98, -1.55, s=(1, .53, .7)), black)
    a.add(box(1.24, .1, 1.5, 0, .58, -.7, .03), GUN, 'Metal')
    a.add(box(.84, .8, .14, 0, .9, 1.78, .05), CHROME, 'Metal')               # grille shell
    a.add(box(.66, .62, .06, 0, .9, 1.86, .02), BLACK, 'Matte')
    a.add(box(.7, .46, 1.0, 0, .8, 1.02, .06), 0x3a3d44, 'Metal')             # block
    for sg in (-1, 1):
        a.add(box(.2, .14, .8, sg * .26, 1.1, 1.02, .04, (0, 0, -sg * .5)), CHROME, 'Metal')   # rocker covers
        for i in range(4):                                                    # headers
            z = 1.34 - i * .2
            a.add(pipe([(sg * .36, .98, z), (sg * .74, .9, z - .06), (sg * .82, .72, z - .45)], .05, 8), CHROME, 'Metal')
            a.add(ball(.05, sg * .82, .72, z - .47), flame, 'Glow')
        lamp(a, sg * .62, 1.08, 1.72, .13)
        a.add(tube(.03, .3, sg * .62, .93, 1.7), CHROME, 'Metal')
        a.add(xf(plate(FLAME, .03), (sg * .665, 1.0, -.2), (0, sg * PI / 2, 0), (1.5 * sg, .8, 1)), flame)       # painted flames
        a.add(xf(plate(FLAME, .04), (sg * .67, .96, -.05), (0, sg * PI / 2, 0), (.9 * sg, .5, 1)), yellow)
        a.add(box(.14, .1, .04, sg * .4, .98, -2.0, .01), RED, 'Glow')
    a.add(box(.5, .3, .5, 0, 1.32, 1.02, .06), CHROME, 'Metal')               # blower
    a.add(box(.56, .22, .34, 0, 1.56, 1.08, .05), RED)
    a.add(box(.46, .14, .04, 0, 1.56, 1.26, .0), BLACK, 'Matte')
    a.add(tubex(.05, 2.0, 0, .44, 1.45), CHROME, 'Metal')                     # front axle
    a.add(box(1.2, .36, .05, 0, 1.44, .12, .02, (-.5, 0, 0)), 0x33404a, 'Glass')   # chopped screen
    a.add(box(1.1, .5, .16, 0, 1.3, -1.2, .07, (.15, 0, 0)), 0x7a1f1f, 'Matte')     # seat
    a.add(box(.5, .12, .03, 0, .82, -2.02, .0), yellow)
    steering(a, 0, 1.4, -.12, .2)
    a.add(ball(.36, 0, 1.4, -.82, s=(1.15, .85, .7)), 0x1b1b1f, 'Matte')      # leather jacket
    arms(a, (.34, 1.5, -.78), (.19, 1.42, -.2), 0xeee6d2, .055)
    wheel(v + '_wheel_f', .42, .26, rim=CHROME, hub=RED)
    wheel(v + '_wheel_r', .76, .62, rim=CHROME, hub=RED)
    wheels(v, [(1.02, .42, 1.45), (-1.02, .42, 1.45), (1.02, .76, -1.1), (-1.02, .76, -1.1)])
    # driver: a skull on fire
    h, c, r, bone = Asset(v + '_head'), (0, .56, 0), .46, 0xf2ead8
    h.add(ball(r, *c, s=(1, 1.02, 1.05)), bone, 'Matte')
    h.add(box(.5, .32, .44, 0, .2, .12, .1), bone, 'Matte')                   # jaw
    h.add(tube(.08, .2, 0, .02, -.05), bone, 'Matte')
    for sg in (-1, 1):
        h.add(ball(.15, sg * .19, .58, .37, s=(1.1, 1.2, .5), rot=(0, 0, -sg * .25)), BLACK, 'Matte')   # sockets
        h.add(ball(.055, sg * .19, .57, .43), flame, 'Glow')
        h.add(box(.18, .06, .2, sg * .3, .38, .2, .02), bone, 'Matte')        # cheekbones
    h.add(cone(.07, .12, 0, .36, .47, (PI, 0, 0), 3), BLACK, 'Matte')
    for i in range(7):
        h.add(box(.055, .1, .04, -.2 + i * .067, .24, .36, .01), WHITE)       # teeth
        h.add(box(.055, .09, .04, -.2 + i * .067, .12, .36, .01), WHITE)
    h.add(box(.5, .02, .05, 0, .18, .35, .0), BLACK, 'Matte')
    for (x, z, hgt, rr, col) in [(0, -.1, 1.0, .26, flame), (.26, -.05, .7, .2, flame), (-.26, -.05, .74, .2, flame), (.12, -.34, .82, .2, flame),
                                 (-.14, -.34, .6, .18, flame), (0, .12, .5, .16, flame), (.05, -.12, .62, .15, yellow), (-.12, -.2, .44, .12, yellow), (.18, -.2, .4, .1, yellow)]:
        h.add(cone(rr, hgt, x, .78, z, (-.22, 0, -x * .5), 9), col, 'Glow')   # the fire
    pivot(v + '_head', (0, 1.62, -.82))


# --------------------------------------------------------------------------- 5. flying saucer
def build_ufo():
    v, silver, green = 'ufo', 0xc4ccd6, 0x7dff8a
    a = Asset(v + '_body')
    a.add(lathe([(0, .52), (.72, .52), (1.22, .66), (1.74, .9), (1.78, 1.0), (1.3, 1.2), (.98, 1.3), (.98, 1.36), (0, 1.36)], 40), silver, 'Metal')
    a.add(lathe([(0, .5), (.66, .5)], 28), green, 'Glow')                     # the hum underneath
    a.add(lathe([(1.0, 1.36), (1.06, 1.4), (1.0, 1.46), (.94, 1.4)], 32), GUN, 'Metal')
    for i in range(12):
        t = i / 12 * TAU
        a.add(ball(.09, math.sin(t) * 1.5, .8, math.cos(t) * 1.5, segs=10, rings=8), 0x59c8ff if i % 2 else 0xff5fae, 'Glow')
    for i in range(3):
        t = i / 3 * TAU + .5
        a.add(ball(.2, math.sin(t) * .95, .52, math.cos(t) * .95, s=(1, .6, 1), segs=12, rings=8), GUN, 'Metal')
    a.add(cone(.1, .34, 0, .74, 1.5, (PI / 2 + .25, 0, 0), 10), GUN, 'Metal')  # ray emitter
    a.add(ball(.09, 0, .66, 1.86), green, 'Glow')
    a.add(ball(1.0, 0, 1.36, 0, s=(1, 1.46, 1), segs=28, rings=18), 0xbfe9ff, 'Glass')   # dome
    a.add(ball(.3, 0, 1.56, 0, s=(1, 1, .75)), 0x5fd24a, 'Matte')             # a small body
    a.add(tube(.02, .36, 0, 1.56, .34, (.5, 0, 0)), GUN, 'Metal')
    a.add(ball(.07, 0, 1.72, .43), RED)
    arms(a, (.26, 1.66, .0), (.06, 1.66, .38), 0x5fd24a, .045)
    s = Asset(v + '_spin')                                                    # the rim that turns
    s.add(torus(1.82, .075, 44, 8), GUN, 'Metal')
    for i in range(10):
        t = i / 10 * TAU
        s.add(box(.3, .1, .2, math.sin(t) * 1.84, 0, math.cos(t) * 1.84, .03, (0, t, 0)), silver, 'Metal')
        s.add(ball(.06, math.sin(t + .31) * 1.9, 0, math.cos(t + .31) * 1.9, segs=8, rings=6), green, 'Glow')
    pivot(v + '_spin', (0, .97, 0))
    # driver: big head, bigger eyes
    h, skin = Asset(v + '_head'), 0x6fdc5a
    h.add(ball(.42, 0, .44, 0, s=(1.12, .95, 1)), skin, 'Matte')
    h.add(ball(.3, 0, .2, .06, s=(.9, .8, .9)), skin, 'Matte')                # chin
    h.add(tube(.07, .2, 0, .0, 0), skin, 'Matte')
    for sg in (-1, 1):
        h.add(ball(.19, sg * .2, .42, .33, s=(1, 1.45, .45), rot=(0, sg * .3, sg * .5)), BLACK)   # almond eyes
        h.add(ball(.04, sg * .24, .5, .42), WHITE)
        h.add(pipe([(sg * .16, .8, 0), (sg * .26, 1.0, .02), (sg * .34, 1.12, .0)], .018, 6), skin, 'Matte')
        h.add(ball(.06, sg * .34, 1.14, 0, segs=10, rings=8), 0xff5fae, 'Glow')
    h.add(box(.12, .02, .03, 0, .16, .32, .0), 0x2a5a22, 'Matte')
    pivot(v + '_head', (0, 1.74, 0))


# --------------------------------------------------------------------------- 6. monster truck
def build_monster():
    v, green, mud, skin = 'monster', 0x4f8a3c, 0x6b4a2b, 0x86c043
    a = Asset(v + '_body')
    a.add(box(1.76, .62, 3.3, 0, 1.78, 0, .12), green)
    a.add(box(1.8, .2, 3.34, 0, 1.52, 0, .06), mud, 'Matte')
    a.add(box(1.62, .66, 1.15, 0, 2.3, .0, .12), green)                       # what is left of the cab
    a.add(box(1.4, .4, .05, 0, 2.36, .6, .02, (-.2, 0, 0)), 0x9fc6c0, 'Glass')
    a.add(box(1.6, .12, 1.2, 0, 2.02, -1.0, .04), 0x33373c, 'Metal')          # bed
    a.both(lambda: box(.1, .34, 1.25, .8, 2.14, -1.0, .03), green)
    for sg in (-1, 1):
        a.add(tube(.11, 1.5, sg * .62, 2.75, -.5), CHROME, 'Metal')           # stacks
        a.add(tube(.13, .2, sg * .62, 3.5, -.5), BLACK, 'Matte')
        a.add(ball(.2, sg * .58, 1.98, 1.68, s=(1.2, .6, .4), rot=(0, 0, sg * .35)), AMBER, 'Glow')   # angry lamps
        a.add(pipe(bezier((sg * .5, 2.18, 1.5), (sg * 1.0, 2.3, 1.6), (sg * 1.1, 2.85, 1.72), steps=8), [.11, .11, .1, .09, .08, .07, .05, .03, .01], 8), WHITE)   # horns
        for z in (-1.35, 1.35):                                               # springs and links
            a.add(tube(.11, .75, sg * .78, 1.28, z), 0xffd23f)
            a.add(pipe([(sg * .5, 1.5, z * .3), (sg * .95, .95, z)], .05, 6), GUN, 'Metal')
        a.add(ball(.3, sg * .98, 2.74, .12, segs=14, rings=10), skin, 'Matte')   # fists on the sills
    for z in (-1.35, 1.35):
        a.add(tubex(.1, 2.3, 0, .95, z), GUN, 'Metal')
        a.add(ball(.26, 0, .95, z, s=(1, 1, 1), segs=12, rings=8), GUN, 'Metal')
    a.add(box(1.5, .5, .08, 0, 1.8, 1.67, .02), BLACK, 'Matte')               # a grille with teeth
    for i in range(7):
        a.add(cone(.09, .2, -.6 + i * .2, 2.04, 1.72, (PI, 0, 0), 4), WHITE)
        a.add(cone(.09, .2, -.6 + i * .2, 1.56, 1.72, (0, 0, 0), 4), WHITE)
    a.add(box(1.9, .18, .16, 0, 1.46, 1.72, .05), GUN, 'Metal')
    a.add(box(1.9, .18, .16, 0, 1.46, -1.72, .05), GUN, 'Metal')
    for x in (-.5, .5):
        a.add(box(.2, .12, .04, x, 1.8, -1.67, .01), RED, 'Glow')
    for (x, y, z, s) in [(.88, 1.7, .9, .3), (-.88, 1.75, -.4, .36), (.88, 1.66, -1.2, .26), (-.5, 1.6, 1.66, .24)]:
        a.add(ball(s, x, y, z, s=(.14, .7, 1), segs=10, rings=6), mud, 'Matte')   # mud
    a.add(ball(.82, 0, 2.72, .05, s=(1.05, .6, .62)), skin, 'Matte')          # shoulders through the roof
    a.add(box(1.2, .3, .7, 0, 2.5, .05, .1), 0x6b4a2b, 'Matte')               # torn vest
    wheel(v + '_wheel', .95, .78, rim=0xd9dde2, hub=green, knobs=16)
    wheels(v, [(1.2, .95, 1.35), (-1.2, .95, 1.35), (1.2, .95, -1.35), (-1.2, .95, -1.35)])
    # driver: an ogre with an underbite
    h, c, r = Asset(v + '_head'), (0, .6, 0), .56
    h.add(ball(r, *c, s=(1.05, .95, 1)), skin, 'Matte')
    h.add(ball(r * .86, 0, .3, .14, s=(1.12, .62, 1)), skin, 'Matte')         # jaw
    h.add(tube(.24, .26, 0, .06, 0), skin, 'Matte')
    h.add(box(.78, .14, .2, 0, .82, .44, .06, (.12, 0, 0)), 0x5f9a2c, 'Matte')   # brow
    eyes(h, c, r, .26, .22, .13, .5, white=0xffe36a)
    h.add(ball(.14, 0, .58, .56, s=(1.3, .8, .8)), 0x6da832, 'Matte')         # nose
    h.add(box(.5, .04, .06, 0, .36, .62, .0), 0x2a3a12, 'Matte')
    for sg in (-1, 1):
        h.add(cone(.075, .26, sg * .22, .36, .62, (-.12, 0, sg * .1), 8), WHITE)   # tusks
        h.add(cone(.13, .36, sg * .52, .66, -.02, (0, 0, -sg * 1.25), 6), skin, 'Matte')   # ears
        h.add(ring(.06, .018, sg * .76, .58, -.02, (0, 0, PI / 2), 12), 0xffd23f, 'Metal')
    for (x, z, hh) in [(0, -.05, .34), (.12, -.14, .26), (-.12, -.1, .28)]:
        h.add(cone(.08, hh, x, 1.08, z, (-.3, 0, -x), 6), BLACK, 'Matte')     # a tuft
    pivot(v + '_head', (0, 2.96, .05))


# --------------------------------------------------------------------------- 7. a small, polite tank
def build_tank():
    v, lilac, deep, cream, pink = 'tank', 0xb295e6, 0x7d5fc0, 0xf6ecd6, 0xff7fb0
    a = Asset(v + '_body')
    track = [(1.72, .98), (1.98, .62), (1.6, .04), (-1.6, .04), (-1.98, .62), (-1.72, .98)]
    for sg in (-1, 1):
        a.add(xf(extrude_outline(track, .56, .07), (sg * 1.08, 0, 0), (0, -PI / 2, 0)), 0x2b2d31, 'Matte')
        for i in range(15):                                                    # grousers along the top run
            a.add(box(.6, .05, .1, sg * 1.08, 1.0, -1.6 + i * .23, 0), 0x3c3f45, 'Matte')
        for i in range(5):
            a.add(box(.6, .1, .05, sg * 1.08, .86 - i * .16, 1.8 + i * .037 - (.12 if i > 2 else 0) * (i - 2), 0, (.6, 0, 0)), 0x3c3f45, 'Matte')
        a.add(box(.66, .06, 3.5, sg * 1.08, 1.06, 0, .02), deep)               # guards
    a.add(box(1.7, .62, 3.5, 0, .82, 0, .12), lilac)
    a.add(box(1.68, .5, .9, 0, .98, 1.5, .1, (.5, 0, 0)), lilac)               # glacis
    a.add(lathe([(0, 1.08), (1.02, 1.08), (1.08, 1.3), (.94, 1.62), (.6, 1.8), (0, 1.82)], 28), cream)   # turret
    a.add(xf(lathe([(0, 1.08), (1.02, 1.08), (1.08, 1.3), (.94, 1.62), (.6, 1.8), (0, 1.82)], 28), (0, 0, -.15)), cream)
    a.add(box(.7, .5, .4, 0, 1.42, .9, .12), deep)                            # mantlet
    a.add(ring(.46, .07, 0, 1.84, -.3), deep, 'Metal')                        # hatch
    a.add(box(.5, .06, .5, .0, 1.86, -.9, .02, (.9, 0, 0)), deep)
    petals = lambda x, y, z, rot, s=1.0: [a.add(xf(ball(.09 * s, 0, 0, 0, s=(1, 1, .3), segs=10, rings=6), (x + math.cos(i / 5 * TAU) * .12 * s * (0 if abs(rot[1]) > 1 else 1), y + math.sin(i / 5 * TAU) * .12 * s,
                                                                                               z + math.cos(i / 5 * TAU) * .12 * s * (1 if abs(rot[1]) > 1 else 0)), rot), pink) for i in range(5)]
    for sg in (-1, 1):                                                        # flowers on the turret and the hull
        for (y, z, s) in [(1.38, .25, 1.2), (1.3, -.5, .9)]:
            petals(sg * 1.06, y, z, (0, sg * PI / 2, 0), s)
            a.add(ball(.07 * s, sg * 1.08, y, z, segs=10, rings=6), 0xffd23f)
        a.add(box(.2, .12, .04, sg * .6, .9, -1.76, .01), RED, 'Glow')
        lamp(a, sg * .62, 1.12, 1.76, .1)
    petals(0, .98, 1.86, (0, 0, 0), 1.3)
    a.add(ball(.09, 0, .98, 1.9, segs=10, rings=6), 0xffd23f)
    a.add(lathe([(0, 1.12), (.16, 1.12), (.2, 1.14), (0, 1.14)], 16).copy() and xf(lathe([(0, 0), (.16, 0), (.2, .02), (.05, .03), (.11, .16), (.13, .16), (.06, .0)], 16), (1.08, 1.09, 1.2)), WHITE)   # teacup
    a.add(ball(.2, -.5, 1.26, -1.5, segs=14, rings=10), 0xe6332a, 'Matte')     # yarn
    for sg in (-1, 1):
        a.add(tube(.012, .7, -.5 + sg * .08, 1.4, -1.5, (.5, 0, sg * .5)), CHROME, 'Metal')
    a.add(tube(.05, .5, .7, 1.9, -.9), GUN, 'Metal')                          # aerial with a bow
    a.add(pipe([(.7, 2.1, -.9), (.7, 3.0, -.92)], .012, 6), CHROME, 'Metal')
    a.add(ball(.07, .7, 3.0, -.92), pink)
    a.add(ball(.42, 0, 1.94, -.3, s=(1.05, .6, .75)), 0xd58fd0, 'Matte')       # shawl
    for i in range(9):
        t = (i - 4) * .26
        a.add(ball(.05, math.sin(t) * .34, 2.08, -.3 + math.cos(t) * .26, segs=8, rings=6), WHITE)   # pearls
    wheel(v + '_wheel', .27, .2, tyre=0x3c3f45, rim=deep, hub=cream, rim_kind='Paint')
    wheels(v, [(sg * 1.38, .33, z) for z in (1.3, .65, 0, -.65, -1.3) for sg in (1, -1)])
    g = Asset(v + '_gun')                                                      # the barrel: it kicks
    g.add(tubez(.13, 1.9, 0, 0, 1.05), cream)
    g.add(tubez(.17, .4, 0, 0, .9), deep)
    g.add(box(.42, .3, .34, 0, 0, 2.1, .06), deep)
    g.add(tubez(.09, .36, 0, 0, 2.12), BLACK, 'Matte')
    g.add(ring(.15, .035, 0, 0, 1.6, (PI / 2, 0, 0), 16), pink)
    pivot(v + '_gun', (0, 1.42, 1.0))
    # driver: somebody's grandmother
    h, c, r, skin, hair = Asset(v + '_head'), (0, .52, 0), .46, 0xf2d3b3, 0xdfe2e8
    h.add(ball(r, *c, s=(1.05, .98, 1)), skin, 'Matte')
    h.add(tube(.12, .2, 0, .05, 0), skin, 'Matte')
    h.add(ball(r * 1.05, 0, .62, -.08, s=(1.04, .86, 1)), hair, 'Matte')
    h.add(ball(.24, 0, 1.06, -.12), hair, 'Matte')                            # bun
    h.add(tube(.014, .7, 0, 1.08, -.12, (0, 0, 1.1)), CHROME, 'Metal')
    h.add(ball(.05, .32, 1.24, -.12, segs=8, rings=6), pink)
    eyes(h, c, r, .36, .1, .12, .45)
    for sg in (-1, 1):
        h.add(ring(.125, .02, sg * .17, .56, .45, (PI / 2, 0, 0), 18), 0xffd23f, 'Metal')   # glasses
        h.add(ball(.11, sg * .3, .36, .32, s=(1, .7, .5)), 0xf7a9a0, 'Matte')  # rosy cheeks
        h.add(box(.16, .03, .05, sg * .17, .74, .44, .01, (0, 0, sg * .15)), hair, 'Matte')
        h.add(ball(.05, sg * .47, .4, .0, segs=8, rings=6), WHITE)
    h.add(box(.1, .02, .04, 0, .57, .47, .0), 0xffd23f, 'Metal')
    h.add(ball(.06, 0, .46, .47), skin, 'Matte')
    h.add(pipe(bezier(on_ball(c, r, -.3, -.42, 1.0), on_ball(c, r, 0, -.62, 1.03), on_ball(c, r, .3, -.42, 1.0), steps=8), .025, 6), 0xc2504a, 'Matte')
    pivot(v + '_head', (0, 2.08, -.3))


# --------------------------------------------------------------------------- 8. muscle car, twin rotary guns
def build_muscle():
    v, red, gold, skin = 'muscle', 0xd22b2b, 0xf2b91e, 0xb9774a
    a = Asset(v + '_body')
    a.add(box(2.02, .56, 4.15, 0, .78, 0, .16), red)
    a.add(box(1.82, .2, 1.75, 0, 1.1, 1.08, .08), red)                        # bonnet
    a.add(box(1.82, .2, 1.0, 0, 1.1, -1.5, .08), red)                         # boot
    for z, length in ((1.08, 1.77), (-1.5, 1.02)):
        a.both(lambda z=z, length=length: box(.2, .03, length, .2, 1.205, z, .0), gold)   # stripes
    a.add(box(1.7, .44, .05, 0, 1.36, .22, .02, (-.55, 0, 0)), 0x9fd0e8, 'Glass')
    a.add(box(1.76, .05, .08, 0, 1.56, .1, .02), CHROME, 'Metal')
    a.add(box(1.6, .5, .2, 0, 1.3, -.92, .08, (.18, 0, 0)), 0x1c1d21, 'Matte')   # seats
    a.add(box(1.6, .14, .9, 0, 1.0, -.5, .06), 0x1c1d21, 'Matte')
    a.add(box(1.9, .1, .46, 0, 1.3, -1.95, .04, (-.35, 0, 0)), red)           # ducktail
    a.add(box(.56, .32, .7, 0, 1.3, 1.1, .08), CHROME, 'Metal')               # blower through the bonnet
    a.add(box(.64, .2, .4, 0, 1.52, 1.2, .06), BLACK, 'Matte')
    a.add(box(1.84, .34, .08, 0, .86, 2.06, .03), BLACK, 'Matte')             # grille
    a.add(box(2.06, .1, .3, 0, .5, 2.02, .03), BLACK, 'Matte')                # splitter
    for sg in (-1, 1):
        for dx in (.56, .82):
            lamp(a, sg * dx, .88, 2.08, .1)
        a.add(box(.62, .1, .04, sg * .55, .9, -2.08, .01), RED, 'Glow')
        a.add(tubez(.07, 2.3, sg * 1.04, .52, -.1), CHROME, 'Metal')          # side pipes
        a.add(box(.2, .2, .5, sg * .66, 1.24, 1.05, .04), GUN, 'Metal')       # gun cradles
    a.add(box(2.06, .14, .14, 0, .6, -2.1, .04), CHROME, 'Metal')
    steering(a, 0, 1.36, .0, .21)
    a.add(ball(.5, 0, 1.44, -.62, s=(1.2, .8, .62)), skin, 'Matte')           # shoulders
    arms(a, (.5, 1.5, -.56), (.2, 1.38, -.06), skin, .1)
    a.add(box(1.0, .05, .9, 0, 1.24, -1.5, .02, (-.1, 0, 0)), gold, 'Matte')  # cape over the boot
    a.add(ring(.34, .07, 0, 1.2, -.62, (0, 0, 0), 20), gold, 'Metal')         # the belt
    wheel(v + '_wheel_f', .5, .4, rim=CHROME, hub=gold)
    wheel(v + '_wheel_r', .62, .56, rim=CHROME, hub=gold)
    wheels(v, [(1.0, .5, 1.32), (-1.0, .5, 1.32), (1.0, .62, -1.28), (-1.0, .62, -1.28)])
    g = Asset(v + '_spin')                                                     # six barrels; one mesh, two guns
    for i in range(6):
        t = i / 6 * TAU
        g.add(tubez(.028, 1.1, math.cos(t) * .075, math.sin(t) * .075, .55, segs=8), GUN, 'Metal')
    for z in (.05, .6, 1.05):
        g.add(tubez(.115, .05, 0, 0, z, segs=14), 0x4a4e56, 'Metal')
    g.add(tubez(.1, .4, 0, 0, -.15, segs=14), GUN, 'Metal')
    pivot(v + '_spin_0', (.66, 1.4, 1.0))
    pivot(v + '_spin_1', (-.66, 1.4, 1.0))
    # driver: a luchador
    h, c, r = Asset(v + '_head'), (0, .54, 0), .48
    h.add(ball(r, *c, s=(1.02, 1.05, 1)), red, 'Matte')
    h.add(tube(.22, .24, 0, .06, 0), skin, 'Matte')
    for sg in (-1, 1):
        h.add(ball(.2, *on_ball(c, r, sg * .4, .12, .9), s=(1.25, .9, .5), rot=(0, sg * .4, sg * .5)), gold)   # flared eye holes
        h.add(xf(plate([(0, 0), (.5, .16), (.36, -.06), (.56, -.2), (.2, -.2)], .03), (sg * .44, .7, -.1), (0, sg * PI / 2 - sg * .4, 0), (sg * .9, .9, 1)), gold)   # wings
    eyes(h, c, r, .4, .12, .13, .5)
    h.add(ball(.2, 0, .3, .36, s=(1.25, .8, .6)), skin, 'Matte')              # mouth opening
    h.add(box(.3, .08, .05, 0, .3, .48, .02), WHITE)
    h.add(xf(plate(STAR, .04), (0, .86, .4), (-.5, 0, 0), (.3, .3, 1)), gold)
    for i in range(5):
        h.add(box(.2, .025, .03, 0, .8 - i * .12, -.5 - (.04 if i in (1, 3) else 0) + i * .0, .0, (0, 0, .5 if i % 2 else -.5)), WHITE, 'Matte')   # laces
    pivot(v + '_head', (0, 1.56, -.62))


# --------------------------------------------------------------------------- main
def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    opts = {'out': os.path.join(HERE, '..', 'assets', 'vehicles.glb'), 'blend': None, 'export': bpy.app.background}
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
    else:
        bpy.context.window.scene = bpy.data.scenes.new('Vehicles')
    for build in (build_humvee, build_jeep, build_truck, build_rod, build_ufo, build_monster, build_tank, build_muscle):
        build()
    col = bpy.data.collections.new('Vehicles')
    bpy.context.scene.collection.children.link(col)
    tris = 0
    for asset in ASSETS:
        ob = asset.build()
        col.objects.link(ob)
        tris += sum(len(p.vertices) - 2 for p in ob.data.polygons)
    for name, pos in PIVOTS.items():       # pivots: empties, game Y-up coordinates -> Blender Z-up
        em = bpy.data.objects.new(name, None)
        em.empty_display_size = .15
        em.location = (pos.x, -pos.z, pos.y)
        col.objects.link(em)
    print(f'built {len(ASSETS)} meshes, {len(PIVOTS)} pivots, {tris} triangles')
    if opts['blend']:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(opts['blend']))
    if opts['export']:
        out = os.path.abspath(opts['out'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_yup=True, export_apply=True,
                                  export_texcoords=False, export_normals=True, export_materials='EXPORT',
                                  export_vertex_color='ACTIVE', export_all_vertex_colors=False,
                                  export_animations=False, export_extras=False)
        print(f'wrote {out} ({os.path.getsize(out) // 1024} KB)')


if __name__ == '__main__':
    main()
