"""Bake the ground and road materials for Kartlands GP into tileable PBR textures.

Run it headless with Blender:
    blender --background --factory-startup --python blender/build_textures.py
or with the bpy module from PyPI (pip install bpy):
    python blender/build_textures.py [--size 1024] [--only asphalt,grass]

Each material is a procedural Blender shader. Noise and Voronoi are sampled on a 4D torus
(u and v each walk a circle), so the baked images repeat seamlessly. For every material the
script bakes colour, height and roughness, then writes three JPEGs to assets/textures/:
    NAME_c.jpg  base colour (sRGB)
    NAME_n.jpg  normal map (OpenGL convention, +Y up), computed from the baked height
    NAME_r.jpg  packed data: R = ambient occlusion, G = roughness, B = 0 (glTF ORM layout)
"""
import math
import os
import sys

import bpy  # must come first: the PyPI bpy module provides mathutils
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
TAU = math.tau


def srgb(h):
    """sRGB hex to linear RGBA."""
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(f(((h >> s) & 255) / 255) for s in (16, 8, 0)) + (1.0,)


# --------------------------------------------------------------------------- node helpers
class Graph:
    """Tiny builder for shader node trees: numbers become default values, sockets become links."""

    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        uv = self.node('ShaderNodeTexCoord').outputs['UV']
        sep = self.node('ShaderNodeSeparateXYZ')
        self.link(uv, sep.inputs[0])
        self.u, self.v = sep.outputs[0], sep.outputs[1]
        self._torus = {}

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, val in props.items():
            setattr(n, k, val)
        return n

    def link(self, out, inp):
        self.nt.links.new(out, inp)

    def feed(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.link(val, sock)
        else:
            sock.default_value = val

    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        n = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        self.feed(n.inputs[0], a)
        self.feed(n.inputs[1], b)
        self.feed(n.inputs[2], c)
        return n.outputs[0]

    def add(self, *xs):
        out = xs[0]
        for x in xs[1:]:
            out = self.math('ADD', out, x)
        return out

    def mul(self, a, b):
        return self.math('MULTIPLY', a, b)

    def smooth(self, lo, hi, x):
        n = self.node('ShaderNodeMapRange', interpolation_type='SMOOTHSTEP')
        self.feed(n.inputs['Value'], x)
        n.inputs['From Min'].default_value = lo
        n.inputs['From Max'].default_value = hi
        return n.outputs['Result']

    def mix(self, fac, a, b):
        """Colour mix: a when fac=0, b when fac=1."""
        n = self.node('ShaderNodeMix', data_type='RGBA', clamp_factor=True)
        self.feed(n.inputs[0], fac)
        self.feed(n.inputs[6], srgb(a) if isinstance(a, int) else a)
        self.feed(n.inputs[7], srgb(b) if isinstance(b, int) else b)
        return n.outputs[2]

    def cmul(self, col, fac):
        """Scale a colour by a float."""
        n = self.node('ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY', clamp_factor=True)
        n.inputs[0].default_value = 1.0
        self.feed(n.inputs[6], col)
        comb = self.node('ShaderNodeCombineXYZ')
        for i in range(3):
            self.feed(comb.inputs[i], fac)
        self.link(comb.outputs[0], n.inputs[7])
        return n.outputs[2]

    def ramp(self, fac, stops):
        n = self.node('ShaderNodeValToRGB')
        self.feed(n.inputs[0], fac)
        els = n.color_ramp.elements
        while len(els) < len(stops):
            els.new(0.5)
        for el, (pos, col) in zip(els, stops):
            el.position = pos
            el.color = srgb(col) if isinstance(col, int) else col
        return n.outputs[0]

    def torus(self, ru=1.0, rv=1.0):
        """4D coordinates that wrap in u and v; ru/rv stretch features along each axis."""
        key = (ru, rv)
        if key not in self._torus:
            au = self.mul(self.u, TAU)
            av = self.mul(self.v, TAU)
            r_u, r_v = ru / TAU, rv / TAU
            comb = self.node('ShaderNodeCombineXYZ')
            self.feed(comb.inputs[0], self.mul(self.math('COSINE', au), r_u))
            self.feed(comb.inputs[1], self.mul(self.math('SINE', au), r_u))
            self.feed(comb.inputs[2], self.mul(self.math('COSINE', av), r_v))
            self._torus[key] = (comb.outputs[0], self.mul(self.math('SINE', av), r_v))
        return self._torus[key]

    def _coords(self, node, ru, rv, seed):
        vec, w = self.torus(ru, rv)
        off = self.node('ShaderNodeVectorMath', operation='ADD')
        self.link(vec, off.inputs[0])
        off.inputs[1].default_value = (seed * 1.37, seed * 2.11, seed * 0.73)
        self.link(off.outputs[0], node.inputs['Vector'])
        self.link(self.add(w, seed * 1.91), node.inputs['W'])

    def noise(self, scale, detail=4.0, rough=0.5, distortion=0.0, ru=1.0, rv=1.0, seed=0.0):
        n = self.node('ShaderNodeTexNoise', noise_dimensions='4D')
        self._coords(n, ru, rv, seed)
        n.inputs['Scale'].default_value = scale
        n.inputs['Detail'].default_value = detail
        n.inputs['Roughness'].default_value = rough
        n.inputs['Distortion'].default_value = distortion
        return n.outputs['Fac']

    def voronoi(self, scale, feature='F1', randomness=1.0, ru=1.0, rv=1.0, seed=0.0, out='Distance'):
        n = self.node('ShaderNodeTexVoronoi', voronoi_dimensions='4D', feature=feature)
        self._coords(n, ru, rv, seed)
        n.inputs['Scale'].default_value = scale
        n.inputs['Randomness'].default_value = randomness
        return n.outputs[out]

    def cell_random(self, scale, seed=0.0, ru=1.0, rv=1.0):
        """A random 0-1 value per Voronoi cell."""
        col = self.voronoi(scale, seed=seed, ru=ru, rv=rv, out='Color')
        sep = self.node('ShaderNodeSeparateColor')
        self.link(col, sep.inputs[0])
        return sep.outputs[0]

    def output(self, color):
        """Route a colour or float to an Emission shader so it can be baked."""
        em = self.node('ShaderNodeEmission')
        self.feed(em.inputs['Color'], color)
        out = self.node('ShaderNodeOutputMaterial')
        self.link(em.outputs[0], out.inputs['Surface'])
        return em

    def pack(self, r, g, b=0.0):
        comb = self.node('ShaderNodeCombineColor')
        self.feed(comb.inputs[0], r)
        self.feed(comb.inputs[1], g)
        self.feed(comb.inputs[2], b)
        return comb.outputs[0]


# --------------------------------------------------------------------------- materials
# Each returns (albedo colour socket, height float socket 0-1, roughness float socket, normal strength).
# Sizes in comments are the world size of one tile, which the game uses when tiling.

def asphalt(g):
    """Road surface, one tile = 4 m: aggregate stones in dark binder, tar patches, faint wear."""
    edge = g.voronoi(150, 'DISTANCE_TO_EDGE', seed=1)
    stone_mask = g.smooth(0.02, 0.12, edge)
    tone = g.cell_random(150, seed=1)
    stones = g.ramp(tone, [(0.0, 0x2c2c2e), (0.55, 0x4d4d50), (0.85, 0x6a6966), (1.0, 0x8b8883)])
    grain = g.noise(420, 2, 0.6, seed=2)
    col = g.mix(stone_mask, 0x1d1d1f, stones)
    col = g.cmul(col, g.add(0.8, g.mul(grain, 0.4)))
    tar = g.smooth(0.56, 0.64, g.noise(2.5, 5, 0.6, seed=3))
    col = g.mix(g.mul(tar, 0.55), col, 0x161617)
    worn = g.smooth(0.5, 0.75, g.noise(5, 4, 0.55, seed=4))
    col = g.mix(g.mul(worn, 0.25), col, 0x6e6e6c)
    height = g.add(g.mul(stone_mask, 0.55), g.mul(grain, 0.2), g.mul(g.noise(18, 3, seed=5), 0.25))
    rough = g.add(0.9, g.mul(tar, -0.28), g.mul(g.mul(stone_mask, tone), -0.1))
    return col, height, rough, 3.5


def grass(g):
    """Short meadow grass seen from above, one tile = 3 m: blade tips over dark gaps, clumps, clover, dry spots."""
    tips = g.voronoi(240, 'F1', seed=1)
    tip = g.math('SUBTRACT', 1.0, g.smooth(0.0, 0.6, tips))
    tone = g.cell_random(240, seed=1)
    blades = g.noise(110, 3, 0.6, distortion=0.8, ru=1, rv=3, seed=2)
    green = g.ramp(tone, [(0.0, 0x3d6a1f), (0.45, 0x5b8a2c), (0.8, 0x7aa23a), (1.0, 0x9db04c)])
    col = g.mix(g.mul(tip, g.add(0.45, g.mul(blades, 0.7))), 0x24401a, green)
    clumps = g.noise(28, 4, 0.6, seed=5)
    col = g.cmul(col, g.add(0.72, g.mul(clumps, 0.55)))
    clover = g.smooth(0.62, 0.7, g.noise(12, 3, 0.5, seed=6))
    col = g.mix(g.mul(clover, 0.5), col, 0x2f5a22)
    dry = g.smooth(0.6, 0.75, g.noise(7, 5, 0.6, distortion=0.5, seed=3))
    col = g.mix(g.mul(dry, 0.45), col, 0x9a9150)
    patch = g.smooth(0.3, 0.7, g.noise(2.5, 3, seed=4))
    col = g.cmul(col, g.add(0.85, g.mul(patch, 0.3)))
    height = g.add(g.mul(tip, 0.5), g.mul(blades, 0.3), g.mul(clumps, 0.2))
    return col, height, g.add(0.9, g.mul(tip, -0.08)), 4.0


def desert_sand(g):
    """Wind-rippled dune sand, one tile = 4 m."""
    warp = g.noise(2, 4, 0.55, seed=1)
    warp2 = g.noise(9, 3, 0.5, seed=5)
    phase = g.add(g.mul(g.v, 22 * TAU), g.mul(warp, 22.0), g.mul(warp2, 3.0), g.mul(g.u, 2 * TAU))
    ripple = g.add(0.5, g.mul(g.math('SINE', phase), 0.5))
    fade = g.smooth(0.25, 0.65, g.noise(3, 3, seed=6))
    ripple = g.mul(g.math('POWER', ripple, 1.8), g.add(0.35, g.mul(fade, 0.65)))
    grain = g.noise(500, 2, 0.7, seed=2)
    col = g.ramp(g.add(g.mul(ripple, 0.6), g.mul(g.noise(4, 4, seed=3), 0.4)),
                 [(0.0, 0xb3854d), (0.6, 0xd1a466), (1.0, 0xe2bd83)])
    col = g.cmul(col, g.add(0.88, g.mul(grain, 0.24)))
    height = g.add(g.mul(ripple, 0.7), g.mul(grain, 0.3))
    return col, height, g.add(0.93, g.mul(grain, 0.05)), 2.5


def beach_sand(g):
    """Pale fine beach sand with shell flecks and damp patches, one tile = 4 m."""
    grain = g.noise(520, 2, 0.7, seed=1)
    lumps = g.noise(14, 4, 0.55, seed=2)
    col = g.ramp(g.add(g.mul(lumps, 0.5), g.mul(grain, 0.5)), [(0.0, 0xc9b58c), (0.5, 0xe0cfa7), (1.0, 0xf0e3c4)])
    shells = g.math('SUBTRACT', 1.0, g.smooth(0.0, 0.08, g.voronoi(70, 'F1', randomness=1, seed=3)))
    col = g.mix(g.mul(shells, 0.8), col, 0xfbf6ea)
    damp = g.smooth(0.5, 0.75, g.noise(1.5, 3, seed=4))
    col = g.mix(g.mul(damp, 0.22), col, 0xa8966f)
    col = g.cmul(col, g.add(0.86, g.mul(grain, 0.28)))
    height = g.add(g.mul(lumps, 0.6), g.mul(grain, 0.3), g.mul(shells, 0.2))
    return col, height, g.add(0.9, g.mul(damp, -0.35)), 2.0


def red_dirt(g):
    """Canyon dirt: packed red earth with pebbles and dry cracks, one tile = 4 m."""
    base = g.noise(8, 5, 0.6, seed=1)
    col = g.ramp(base, [(0.0, 0x7e4327), (0.5, 0xa55c36), (1.0, 0xc07a4c)])
    peb_d = g.voronoi(55, 'F1', seed=2)
    peb = g.math('SUBTRACT', 1.0, g.smooth(0.05, 0.25, peb_d))
    peb_tone = g.cell_random(55, seed=2)
    col = g.mix(g.mul(peb, g.smooth(0.55, 0.6, peb_tone)), col,
                g.ramp(peb_tone, [(0.0, 0x6b3f2c), (1.0, 0xc9a58a)]))
    crack_d = g.voronoi(5, 'DISTANCE_TO_EDGE', seed=3)
    crack_on = g.smooth(0.45, 0.6, g.noise(3, 3, seed=5))
    cracks = g.math('MAXIMUM', g.smooth(0.0, 0.012, crack_d), g.math('SUBTRACT', 1.0, crack_on))
    col = g.cmul(col, g.add(0.65, g.mul(cracks, 0.35)))
    grain = g.noise(400, 2, 0.6, seed=4)
    col = g.cmul(col, g.add(0.9, g.mul(grain, 0.2)))
    height = g.add(g.mul(base, 0.3), g.mul(g.mul(peb, g.smooth(0.55, 0.6, peb_tone)), 0.4), g.mul(cracks, 0.3))
    return col, height, 0.94, 4.0


def snow(g):
    """Wind-packed snow with soft drifts and blue shadows in the dips, one tile = 4 m."""
    drift = g.noise(3, 4, 0.5, seed=1)
    bumps = g.noise(22, 4, 0.55, seed=2)
    grain = g.noise(450, 2, 0.6, seed=3)
    h = g.add(g.mul(drift, 0.5), g.mul(bumps, 0.35), g.mul(grain, 0.15))
    col = g.ramp(h, [(0.2, 0xaebfd4), (0.5, 0xe4ebf2), (0.8, 0xf7f9fb)])
    ice = g.smooth(0.62, 0.7, g.noise(5, 3, seed=4))
    return col, h, g.add(0.8, g.mul(ice, -0.45)), 1.6


def basalt(g):
    """Volcanic ground: broken basalt and ash, one tile = 4 m."""
    cells = g.voronoi(12, 'F1', seed=1)
    chunks = g.math('SUBTRACT', 1.0, g.smooth(0.0, 0.7, cells))
    edges = g.smooth(0.0, 0.05, g.voronoi(12, 'DISTANCE_TO_EDGE', seed=1))
    rough_n = g.noise(60, 5, 0.65, seed=2)
    ash = g.smooth(0.5, 0.7, g.noise(4, 4, seed=3))
    col = g.ramp(g.add(g.mul(rough_n, 0.6), g.mul(chunks, 0.4)), [(0.0, 0x141213), (0.6, 0x2b2627), (1.0, 0x433b39)])
    col = g.mix(g.mul(ash, 0.7), col, 0x5a5350)
    col = g.cmul(col, g.add(0.5, g.mul(edges, 0.5)))
    rust = g.smooth(0.6, 0.7, g.noise(9, 3, seed=4))
    col = g.mix(g.mul(rust, 0.4), col, 0x5a2e1e)
    height = g.add(g.mul(chunks, 0.45), g.mul(rough_n, 0.35), g.mul(edges, 0.2))
    return col, height, 0.96, 5.0


def pavers(g):
    """Wet city pavement: 50 cm stone pavers with dark grout and puddles, one tile = 4 m."""
    uu, vv = g.mul(g.u, 8), g.mul(g.v, 8)
    fu = g.math('FRACT', uu)
    fv = g.math('FRACT', g.add(vv, g.mul(g.math('FLOOR', uu), 0.5)))   # running bond
    gu = g.math('MINIMUM', fu, g.math('SUBTRACT', 1.0, fu))
    gv = g.math('MINIMUM', fv, g.math('SUBTRACT', 1.0, fv))
    grout = g.smooth(0.015, 0.04, g.math('MINIMUM', gu, gv))
    wn = g.node('ShaderNodeTexWhiteNoise', noise_dimensions='2D')
    comb = g.node('ShaderNodeCombineXYZ')
    g.link(g.math('FLOOR', uu), comb.inputs[0])
    g.link(g.math('FLOOR', g.add(vv, g.mul(g.math('FLOOR', uu), 0.5))), comb.inputs[1])
    g.link(comb.outputs[0], wn.inputs['Vector'])
    tone = wn.outputs['Value']
    stone = g.ramp(tone, [(0.0, 0x3e4046), (0.5, 0x55575c), (1.0, 0x6d6c6a)])
    grain = g.noise(300, 3, 0.6, seed=1)
    stone = g.cmul(stone, g.add(0.85, g.mul(grain, 0.3)))
    col = g.mix(grout, 0x1a1b1e, stone)
    puddle = g.smooth(0.55, 0.62, g.noise(2.2, 5, 0.55, seed=2))
    col = g.cmul(col, g.add(1.0, g.mul(puddle, -0.35)))
    height = g.add(g.mul(grout, 0.7), g.mul(grain, 0.3))
    rough = g.add(g.add(0.55, g.mul(grain, 0.2)), g.mul(puddle, -0.5))
    return col, height, rough, 3.0


MATERIALS = {
    'asphalt': asphalt,
    'grass': grass,
    'sand': desert_sand,
    'beach': beach_sand,
    'dirt': red_dirt,
    'snow': snow,
    'basalt': basalt,
    'pavers': pavers,
}


# --------------------------------------------------------------------------- baking and post-processing
def setup_scene(size):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 4
    scene.render.bake.margin = 0
    bpy.ops.mesh.primitive_plane_add(size=2)
    return scene, bpy.context.object


def bake(scene, plane, mat, sock, size):
    """Bake one colour/float socket to a float image and return it as an (h, w, 3) array."""
    em = mat.node_tree.nodes.get('bake_emit')
    if em is None:
        em = mat.node_tree.nodes.new('ShaderNodeEmission')
        em.name = 'bake_emit'
        out = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        mat.node_tree.links.new(em.outputs[0], out.inputs['Surface'])
        out.is_active_output = True
    mat.node_tree.links.new(sock, em.inputs['Color'])
    img = bpy.data.images.new('bake', size, size, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = img
    mat.node_tree.nodes.active = tex
    bpy.ops.object.bake(type='EMIT')
    arr = np.array(img.pixels[:], dtype=np.float32).reshape(size, size, 4)[:, :, :3]
    mat.node_tree.nodes.remove(tex)
    bpy.data.images.remove(img)
    return arr


def blur(a, r):
    """Box blur with wrap-around, repeated for a soft result."""
    for _ in range(3):
        acc = np.zeros_like(a)
        for d in range(-r, r + 1):
            acc += np.roll(a, d, axis=0)
        a = acc / (2 * r + 1)
        acc = np.zeros_like(a)
        for d in range(-r, r + 1):
            acc += np.roll(a, d, axis=1)
        a = acc / (2 * r + 1)
    return a


def to_srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def save_jpeg(arr, path, scene):
    """arr: (h, w, 3) floats already in the encoding to store (sRGB colour or raw data)."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new('out', w, h, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color'
    px = np.concatenate([np.clip(arr, 0, 1), np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels[:] = px.ravel()
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 88
    img.filepath_raw = path
    img.file_format = 'JPEG'
    img.save(filepath=path, quality=88)
    bpy.data.images.remove(img)


def build(name, fn, scene, plane, size, out_dir):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    g = Graph(mat)
    col, height, rough, strength = fn(g)
    if not isinstance(rough, bpy.types.NodeSocket):
        rough = g.add(rough, 0.0)
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    albedo = bake(scene, plane, mat, col, size)
    data = bake(scene, plane, mat, g.pack(height, rough), size)
    h, r = data[:, :, 0], data[:, :, 1]
    # normal from height: central differences with wrap-around, scaled per material
    k = strength * size / 1024
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * k
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * k
    n = np.stack([-dx, -dy, np.ones_like(h)], axis=2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    # ambient occlusion from how far each pixel sits below its blurred surroundings
    ao = np.clip(1.0 - np.maximum(blur(h, max(2, size // 128)) - h, 0) * 2.2, 0.35, 1.0)
    albedo = albedo * (0.75 + 0.25 * ao[:, :, None])
    save_jpeg(to_srgb(albedo), os.path.join(out_dir, name + '_c.jpg'), scene)
    save_jpeg(n * 0.5 + 0.5, os.path.join(out_dir, name + '_n.jpg'), scene)
    save_jpeg(np.stack([ao, np.clip(r, 0.04, 1), np.zeros_like(h)], axis=2), os.path.join(out_dir, name + '_r.jpg'), scene)
    print(f'{name}: albedo mean {albedo.mean():.3f}, height {h.min():.2f}..{h.max():.2f}, rough {r.mean():.2f}')


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    size, only, out_dir = 1024, None, os.path.join(HERE, '..', 'assets', 'textures')
    it = iter(argv)
    for a in it:
        if a == '--size':
            size = int(next(it))
        elif a == '--only':
            only = next(it).split(',')
        elif a == '--out':
            out_dir = next(it)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    scene, plane = setup_scene(size)
    for name, fn in MATERIALS.items():
        if only and name not in only:
            continue
        build(name, fn, scene, plane, size, out_dir)


if __name__ == '__main__':
    main()
